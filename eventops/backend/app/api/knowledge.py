from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import and_, false, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from .. import schemas
from ..auth import get_current_staff
from ..database import get_db
from ..models import ConfidentialityRule, KnowledgeBaseLink, Staff, Visibility
from .common import can_see_confidential, ensure_event_access

router = APIRouter(prefix="/events/{event_id}", tags=["knowledge"])


async def _kb_visibility_filter(db: AsyncSession, staff: Staff) -> Any:
    if staff.is_admin:
        return true()

    confidential_allowed = await can_see_confidential(db, staff)
    return or_(
        KnowledgeBaseLink.visibility == Visibility.public,
        and_(KnowledgeBaseLink.visibility == Visibility.role_only, true() if staff.role_id else false()),
        and_(KnowledgeBaseLink.visibility == Visibility.confidential, true() if confidential_allowed else false()),
    )


async def _require_admin(staff: Staff) -> None:
    if not staff.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only admin can modify knowledge settings")


@router.get("/knowledge", response_model=list[schemas.KnowledgeBaseLink])
async def list_knowledge_links(
    event_id: int,
    db: AsyncSession = Depends(get_db),
    current_staff: Staff = Depends(get_current_staff),
) -> list[KnowledgeBaseLink]:
    await ensure_event_access(event_id, current_staff)
    visible_clause = await _kb_visibility_filter(db, current_staff)
    result = await db.execute(
        select(KnowledgeBaseLink)
        .where(KnowledgeBaseLink.event_id == event_id, KnowledgeBaseLink.is_active.is_(True))
        .where(visible_clause)
        .order_by(KnowledgeBaseLink.id.asc())
    )
    return list(result.scalars().all())


@router.post("/knowledge", response_model=schemas.KnowledgeBaseLink, status_code=status.HTTP_201_CREATED)
async def create_knowledge_link(
    event_id: int,
    payload: schemas.KnowledgeBaseLinkCreate,
    db: AsyncSession = Depends(get_db),
    current_staff: Staff = Depends(get_current_staff),
) -> KnowledgeBaseLink:
    await ensure_event_access(event_id, current_staff)
    await _require_admin(current_staff)
    link = KnowledgeBaseLink(event_id=event_id, **payload.model_dump())
    db.add(link)
    await db.commit()
    await db.refresh(link)
    return link


@router.patch("/knowledge/{link_id}", response_model=schemas.KnowledgeBaseLink)
async def update_knowledge_link(
    event_id: int,
    link_id: int,
    payload: schemas.KnowledgeBaseLinkUpdate,
    db: AsyncSession = Depends(get_db),
    current_staff: Staff = Depends(get_current_staff),
) -> KnowledgeBaseLink:
    await ensure_event_access(event_id, current_staff)
    await _require_admin(current_staff)
    link = await db.get(KnowledgeBaseLink, link_id)
    if link is None or link.event_id != event_id:
        raise HTTPException(status_code=404, detail="Knowledge link not found")

    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(link, key, value)
    await db.commit()
    await db.refresh(link)
    return link


@router.get("/confidentiality-rules", response_model=list[schemas.ConfidentialityRule])
async def list_confidentiality_rules(
    event_id: int,
    db: AsyncSession = Depends(get_db),
    current_staff: Staff = Depends(get_current_staff),
) -> list[ConfidentialityRule]:
    await ensure_event_access(event_id, current_staff)
    if not await can_see_confidential(db, current_staff):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No access to confidentiality rules")

    result = await db.execute(
        select(ConfidentialityRule)
        .where(ConfidentialityRule.event_id == event_id, ConfidentialityRule.is_active.is_(True))
        .order_by(ConfidentialityRule.severity.desc(), ConfidentialityRule.id.asc())
    )
    return list(result.scalars().all())


@router.post("/confidentiality-rules", response_model=schemas.ConfidentialityRule, status_code=status.HTTP_201_CREATED)
async def create_confidentiality_rule(
    event_id: int,
    payload: schemas.ConfidentialityRuleCreate,
    db: AsyncSession = Depends(get_db),
    current_staff: Staff = Depends(get_current_staff),
) -> ConfidentialityRule:
    await ensure_event_access(event_id, current_staff)
    await _require_admin(current_staff)
    rule = ConfidentialityRule(event_id=event_id, **payload.model_dump())
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return rule


@router.patch("/confidentiality-rules/{rule_id}", response_model=schemas.ConfidentialityRule)
async def update_confidentiality_rule(
    event_id: int,
    rule_id: int,
    payload: schemas.ConfidentialityRuleUpdate,
    db: AsyncSession = Depends(get_db),
    current_staff: Staff = Depends(get_current_staff),
) -> ConfidentialityRule:
    await ensure_event_access(event_id, current_staff)
    await _require_admin(current_staff)
    rule = await db.get(ConfidentialityRule, rule_id)
    if rule is None or rule.event_id != event_id:
        raise HTTPException(status_code=404, detail="Confidentiality rule not found")

    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(rule, key, value)
    await db.commit()
    await db.refresh(rule)
    return rule
