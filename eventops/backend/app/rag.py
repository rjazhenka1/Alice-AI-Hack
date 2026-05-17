from __future__ import annotations

import logging
import mimetypes
import re
import string
from typing import Any

from sqlalchemy import insert, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from .agent.alice import VisionOCRClient, YandexEmbeddingClient
from .models import DocumentChunk, KnowledgeBaseLink, Role, Staff, Ticket, TicketAssignment, Visibility

logger = logging.getLogger(__name__)

CHUNK_SIZE = 1200
CHUNK_OVERLAP = 160
MIN_PRINTABLE_RATIO = 0.85
OCR_MIME_TYPES = {"image/jpeg", "image/png", "image/webp", "image/tiff", "image/bmp", "application/pdf"}
MIN_KEYWORD_LENGTH = 4


def _infer_content_type(
    *,
    source_title: str,
    source_url: str | None,
    metadata: dict[str, Any] | None,
) -> str | None:
    metadata = metadata or {}
    content_type = metadata.get("content_type")
    if isinstance(content_type, str) and content_type:
        return content_type

    for value in (metadata.get("filename"), source_url, source_title):
        if isinstance(value, str) and value:
            guessed, _ = mimetypes.guess_type(value)
            if guessed:
                return guessed
    return None


async def extract_indexable_text(
    content: bytes,
    *,
    source_title: str,
    source_url: str | None,
    metadata: dict[str, Any] | None,
) -> str:
    content_type = _infer_content_type(source_title=source_title, source_url=source_url, metadata=metadata)
    if content_type in OCR_MIME_TYPES:
        try:
            return await VisionOCRClient().recognize_text(content=content, mime_type=content_type)
        except Exception:
            logger.exception("Failed to extract text with OCR: source_title=%s content_type=%s", source_title, content_type)
            return decode_document_text(content)

    return decode_document_text(content)


def decode_document_text(content: bytes) -> str:
    if b"\x00" in content:
        return ""

    text_value = content.decode("utf-8", errors="ignore").strip()
    if not text_value:
        return ""

    printable = set(string.printable)
    printable_count = sum(1 for char in text_value if char in printable or char.isprintable())
    if printable_count / max(len(text_value), 1) < MIN_PRINTABLE_RATIO:
        return ""

    return text_value.replace("\x00", "").strip()


def split_text(text_value: str, *, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    text_value = " ".join((text_value or "").split())
    if not text_value:
        return []

    chunks: list[str] = []
    start = 0
    while start < len(text_value):
        end = min(start + chunk_size, len(text_value))
        chunks.append(text_value[start:end])
        if end == len(text_value):
            break
        start = max(0, end - overlap)
    return chunks


def vector_literal(embedding: list[float]) -> str:
    return "[" + ",".join(f"{value:.8f}" for value in embedding) + "]"


def _query_keywords(query: str) -> list[str]:
    words = re.findall(r"[\wА-Яа-яЁё]+", (query or "").lower())
    words.extend(re.findall(r"\b\d{1,2}:\d{2}\b", query or ""))
    synonyms = {
        "волонтер": ["volunteer"],
        "волонтеров": ["volunteer"],
        "волонтёр": ["volunteer"],
        "волонтёров": ["volunteer"],
        "обед": ["обед", "обедов"],
        "обедают": ["обед", "обедов"],
    }
    seen: set[str] = set()
    result: list[str] = []
    for word in words:
        if len(word) < MIN_KEYWORD_LENGTH or word in seen:
            continue
        seen.add(word)
        result.append(word)
        for synonym in synonyms.get(word, []):
            if synonym not in seen:
                seen.add(synonym)
                result.append(synonym)
    return result[:8]


def _chunk_to_result(chunk: DocumentChunk, *, score: float | None = None) -> dict[str, Any]:
    return {
        "id": chunk.id,
        "event_id": chunk.event_id,
        "knowledge_base_link_id": chunk.knowledge_base_link_id,
        "ticket_id": chunk.ticket_id,
        "content": chunk.content,
        "source_title": chunk.source_title,
        "source_url": chunk.source_url,
        "chunk_index": chunk.chunk_index,
        "score": score,
    }


async def _staff_can_see_confidential(db: AsyncSession, staff: Staff) -> bool:
    if staff.is_admin:
        return True
    if staff.role_id is None:
        return False
    result = await db.execute(select(Role.can_see_confidential).where(Role.id == staff.role_id))
    return bool(result.scalar_one_or_none())


async def _can_access_chunk(db: AsyncSession, item: dict[str, Any], staff: Staff) -> bool:
    if staff.is_admin:
        return True

    knowledge_base_link_id = item.get("knowledge_base_link_id")
    if knowledge_base_link_id is not None:
        link = await db.get(KnowledgeBaseLink, int(knowledge_base_link_id))
        if link is None or not link.is_active or link.event_id != staff.event_id:
            return False
        if link.visibility in {Visibility.public, Visibility.role_only}:
            return True
        return await _staff_can_see_confidential(db, staff)

    ticket_id = item.get("ticket_id")
    if ticket_id is not None:
        ticket = await db.get(Ticket, int(ticket_id))
        if ticket is None or ticket.event_id != staff.event_id:
            return False
        if ticket.visibility == Visibility.public:
            return True
        if ticket.visibility == Visibility.role_only and ticket.assignee_role_id == staff.role_id:
            return True
        if ticket.visibility == Visibility.confidential and await _staff_can_see_confidential(db, staff):
            return True
        if ticket.created_by_id == staff.id:
            return True
        assignment_id = await db.scalar(
            select(TicketAssignment.id)
            .where(TicketAssignment.ticket_id == ticket.id, TicketAssignment.staff_id == staff.id)
            .limit(1)
        )
        return assignment_id is not None

    return item.get("event_id") == staff.event_id


async def _filter_chunks_for_staff(
    db: AsyncSession,
    items: list[dict[str, Any]],
    *,
    current_staff: Staff | None,
    limit: int,
) -> list[dict[str, Any]]:
    if current_staff is None:
        return items[:limit]

    visible: list[dict[str, Any]] = []
    seen: set[int] = set()
    for item in items:
        item_id = int(item["id"])
        if item_id in seen:
            continue
        seen.add(item_id)
        if await _can_access_chunk(db, item, current_staff):
            visible.append(item)
            if len(visible) >= limit:
                break
    return visible


async def _keyword_search_document_chunks(
    db: AsyncSession,
    *,
    event_id: int,
    query: str,
    limit: int,
) -> list[dict[str, Any]]:
    keywords = _query_keywords(query)
    if not keywords:
        return []

    score_parts = [
        f"CASE WHEN lower(content) LIKE :keyword_{index} THEN 1 ELSE 0 END"
        for index, _ in enumerate(keywords)
    ]
    params: dict[str, Any] = {"event_id": event_id, "limit": limit}
    for index, keyword in enumerate(keywords):
        params[f"keyword_{index}"] = f"%{keyword}%"

    result = await db.execute(
        text(
            f"""
            SELECT id, event_id, knowledge_base_link_id, ticket_id, content,
                   source_title, source_url, chunk_index,
                   ({' + '.join(score_parts)})::float AS score
            FROM document_chunks
            WHERE event_id = :event_id
              AND ({' OR '.join(f'lower(content) LIKE :keyword_{index}' for index, _ in enumerate(keywords))})
            ORDER BY score DESC, id DESC
            LIMIT :limit
            """
        ),
        params,
    )
    return [dict(row._mapping) for row in result.all()]


async def index_document_chunks(
    db: AsyncSession,
    *,
    event_id: int,
    content: bytes,
    source_title: str,
    source_url: str | None,
    knowledge_base_link_id: int | None = None,
    ticket_id: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> int:
    chunks = split_text(
        await extract_indexable_text(
            content,
            source_title=source_title,
            source_url=source_url,
            metadata=metadata,
        )
    )
    if not chunks:
        return 0

    embedding_client = YandexEmbeddingClient()
    indexed = 0
    is_postgres = db.bind is not None and db.bind.dialect.name == "postgresql"

    for index, chunk in enumerate(chunks):
        result = await db.execute(
            insert(DocumentChunk)
            .values(
                event_id=event_id,
                knowledge_base_link_id=knowledge_base_link_id,
                ticket_id=ticket_id,
                content=chunk,
                source_title=source_title,
                source_url=source_url,
                chunk_index=index,
                chunk_metadata=metadata or {},
            )
            .returning(DocumentChunk.id)
        )
        chunk_id = int(result.scalar_one())

        if is_postgres:
            try:
                async with db.begin_nested():
                    embedding = await embedding_client.embed(chunk, model="text-search-doc")
                    await db.execute(
                        text("UPDATE document_chunks SET embedding = (:embedding)::vector WHERE id = :chunk_id"),
                        {"embedding": vector_literal(embedding), "chunk_id": chunk_id},
                    )
            except Exception:
                logger.exception("Failed to embed document chunk: chunk_id=%s", chunk_id)
        indexed += 1

    return indexed


async def search_document_chunks(
    db: AsyncSession,
    *,
    event_id: int,
    query: str,
    limit: int = 5,
    current_staff: Staff | None = None,
) -> list[dict[str, Any]]:
    is_postgres = db.bind is not None and db.bind.dialect.name == "postgresql"
    results: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    search_limit = max(limit * 5, limit)

    if is_postgres:
        try:
            for row in await _keyword_search_document_chunks(db, event_id=event_id, query=query, limit=search_limit):
                seen_ids.add(int(row["id"]))
                results.append(row)
        except Exception:
            logger.exception("Keyword RAG search failed")

    if is_postgres:
        try:
            embedding = await YandexEmbeddingClient().embed(query, model="text-search-query")
            result = await db.execute(
                text(
                    """
                    SELECT id, event_id, knowledge_base_link_id, ticket_id, content,
                           source_title, source_url, chunk_index,
                           1 - (embedding <=> (:embedding)::vector) AS score
                    FROM document_chunks
                    WHERE event_id = :event_id AND embedding IS NOT NULL
                    ORDER BY embedding <=> (:embedding)::vector
                    LIMIT :limit
                    """
                ),
                {"event_id": event_id, "embedding": vector_literal(embedding), "limit": search_limit},
            )
            for row in result.all():
                item = dict(row._mapping)
                item_id = int(item["id"])
                if item_id in seen_ids:
                    continue
                seen_ids.add(item_id)
                results.append(item)
                if len(results) >= search_limit:
                    break
            if results:
                return await _filter_chunks_for_staff(db, results, current_staff=current_staff, limit=limit)
        except Exception:
            logger.exception("Vector RAG search failed; falling back to text search")

    keywords = _query_keywords(query)
    content_filter = (
        or_(*(DocumentChunk.content.ilike(f"%{keyword}%") for keyword in keywords))
        if keywords
        else DocumentChunk.content.ilike(f"%{query}%")
    )
    result = await db.execute(
        select(DocumentChunk)
        .where(DocumentChunk.event_id == event_id, content_filter)
        .order_by(DocumentChunk.id.desc())
        .limit(search_limit)
    )
    results.extend(_chunk_to_result(chunk) for chunk in result.scalars().all() if chunk.id not in seen_ids)
    return await _filter_chunks_for_staff(db, results, current_staff=current_staff, limit=limit)
