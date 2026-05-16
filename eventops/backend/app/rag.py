from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import insert, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from .agent.alice import YandexEmbeddingClient
from .models import DocumentChunk

logger = logging.getLogger(__name__)

CHUNK_SIZE = 1200
CHUNK_OVERLAP = 160


def decode_document_text(content: bytes) -> str:
    return content.decode("utf-8", errors="ignore").strip()


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
    chunks = split_text(decode_document_text(content))
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
) -> list[dict[str, Any]]:
    is_postgres = db.bind is not None and db.bind.dialect.name == "postgresql"
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
                {"event_id": event_id, "embedding": vector_literal(embedding), "limit": limit},
            )
            return [dict(row._mapping) for row in result.all()]
        except Exception:
            logger.exception("Vector RAG search failed; falling back to text search")

    result = await db.execute(
        select(DocumentChunk)
        .where(DocumentChunk.event_id == event_id, DocumentChunk.content.ilike(f"%{query}%"))
        .order_by(DocumentChunk.id.desc())
        .limit(limit)
    )
    return [
        {
            "id": chunk.id,
            "event_id": chunk.event_id,
            "knowledge_base_link_id": chunk.knowledge_base_link_id,
            "ticket_id": chunk.ticket_id,
            "content": chunk.content,
            "source_title": chunk.source_title,
            "source_url": chunk.source_url,
            "chunk_index": chunk.chunk_index,
            "score": None,
        }
        for chunk in result.scalars().all()
    ]
