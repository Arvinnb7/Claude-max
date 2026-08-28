"""نوشتن و خواندنِ رویدادهای ممیزی.

قاعده‌ی این ماژول یک جمله است: **ممیزی نباید کارِ اصلی را زمین بزند.**
اگر ثبتِ رویداد به هر دلیلی شکست بخورد، خروجیِ کاربر نباید خطا شود — ولی
شکست هم بی‌صدا نمی‌ماند و در لاگ می‌آید. عکسش (خطا دادنِ دانلود به‌خاطرِ
ناتوانی در نوشتنِ یک ردیفِ لاگ) از خودِ مشکل بدتر است.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from mktcore.db.models import AuditEvent

logger = logging.getLogger("mktcore.audit")

__all__ = ["record_audit_event", "recent_audit_events"]


def record_audit_event(
    session: Session,
    *,
    action: str,
    business_id: int | None = None,
    entity_type: str | None = None,
    entity_id: str | int | None = None,
    actor: str | None = None,
    source_ip: str | None = None,
    row_count: int | None = None,
    detail_fa: str | None = None,
) -> AuditEvent | None:
    """یک رویداد ممیزی ثبت می‌کند. در همان تراکنشِ فراخوان می‌نشیند."""
    try:
        event = AuditEvent(
            action=action,
            business_id=business_id,
            entity_type=entity_type,
            entity_id=None if entity_id is None else str(entity_id),
            actor=actor,
            source_ip=source_ip,
            row_count=row_count,
            detail_fa=detail_fa,
        )
        session.add(event)
        session.flush()
        return event
    except Exception:  # pragma: no cover - مسیرِ خرابیِ نادر
        logger.exception("ثبت رویداد ممیزی «%s» شکست خورد", action)
        return None


def recent_audit_events(
    session: Session,
    *,
    action: str | None = None,
    entity_id: str | int | None = None,
    limit: int = 50,
) -> list[AuditEvent]:
    stmt = select(AuditEvent).order_by(AuditEvent.at.desc()).limit(limit)
    if action is not None:
        stmt = stmt.where(AuditEvent.action == action)
    if entity_id is not None:
        stmt = stmt.where(AuditEvent.entity_id == str(entity_id))
    return list(session.scalars(stmt).all())
