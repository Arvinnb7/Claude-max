"""دفترِ آفر: ماندگارسازیِ پیشنهادِ تخفیف و تصمیمِ انسان — §۲۰.۳.

## دو قاعده‌ی سخت

1. **موتور تصمیمِ انسان را پاک نمی‌کند.** اجرای بعدی فقط می‌تواند تصمیم را «کهنه»
   کند (وقتی مبنای پیشنهاد — حاشیه یا کف — عوض شده) یا پیشنهادِ تازه‌ای کنارِ
   ردِ قبلی بگذارد. `approved` هرگز بی‌صدا به `suggested` برنمی‌گردد.
2. **تأیید در لحظه‌ی خودش دوباره حساب می‌شود.** حاشیه‌ی دیروز مبنای تأییدِ امروز
   نیست؛ اگر پله زیرِ کف رفته باشد، تأیید رد می‌شود و ردیف `stale` می‌خورد.

## چرا از `margin_lookup` و نه `margin_by_product`

`margin_by_product` فقط با نامِ canonical کلید دارد؛ `margin_lookup` با هر نامی
که ممکن است در پیشنهاد بیاید (نمایشی، canonical، دسته). موتور با دومی کار
می‌کند؛ اگر تأیید با اولی حساب کند، بیشترِ تأییدها بی‌دلیل «حاشیه نامعلوم»
می‌گیرند.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sqlalchemy import select

from mktcore.catalog.normalize import normalize_product_name
from mktcore.db.base import now_ts
from mktcore.db.engine import session_scope, write_lock
from mktcore.db.migrations import ensure_schema
from mktcore.db.models import (
    AuditEvent,
    Opportunity,
    OpportunityEvent,
    OpportunityOffer,
    Product,
)
from mktcore.db.repo_audit import record_audit_event

from .contract import OpportunityCandidate
from .filters import OFFER_BASIS_CUSTOMER, OFFER_BASIS_NAME, post_discount_margin_bp

if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.orm import Session

logger = logging.getLogger("mktcore.opportunities.offers")

DECISION_APPROVE = "approve"
DECISION_REJECT = "reject"
DECISIONS = (DECISION_APPROVE, DECISION_REJECT)

__all__ = [
    "DECISIONS",
    "DECISION_APPROVE",
    "DECISION_REJECT",
    "OfferDecisionError",
    "decide_offer",
    "offer_payload",
    "offers_by_opportunity",
    "upsert_offer",
]


class OfferDecisionError(ValueError):
    """تصمیم انجام نشد؛ `conflict=True` یعنی ۴۰۹ (وضعیت)، وگرنه ۴۰۴."""

    def __init__(self, reason_fa: str, *, conflict: bool = True):
        super().__init__(reason_fa)
        self.reason_fa = reason_fa
        self.conflict = conflict


# ----------------------------------------------------------------- موتور
def upsert_offer(
    session: Session,
    business_id: int,
    opportunity: Opportunity,
    candidate: OpportunityCandidate,
    run_id: int,
) -> None:
    """پیشنهادِ این اجرا را روی ردیفِ آفرِ فرصت می‌نشاند — بدون پاک‌کردنِ تصمیمِ انسان."""
    rung = candidate.suggested_discount_bp
    existing = session.scalar(
        select(OpportunityOffer).where(OpportunityOffer.opportunity_id == opportunity.id)
    )
    stamp = now_ts()

    if not rung:
        # موتور دیگر پیشنهادی ندارد (نردبان برداشته شد، طبقه عوض شد، …). ردیف
        # «برداشته‌شده» می‌شود — نه «کهنه»: کهنه یعنی «پیشنهادِ تازه‌ای هست، دوباره
        # تأیید کن»، ولی اینجا پیشنهادی نیست که تأیید شود. رابط کاربری برای
        # برداشته‌شده دکمه‌ی تأیید ندارد و `decide_offer` هم ردش می‌کند.
        if existing is None:
            return
        if existing.status in (OpportunityOffer.STATUS_APPROVED, OpportunityOffer.STATUS_SUGGESTED,
                               OpportunityOffer.STATUS_STALE):
            if existing.status == OpportunityOffer.STATUS_APPROVED:
                existing.decision_note_fa = (
                    "برداشته شد: اجرای بعدیِ موتور برای این فرصت دیگر تخفیفی پیشنهاد نداد؛ "
                    "تأییدِ قبلی دیگر ارسال نمی‌شود."
                )
            existing.status = OpportunityOffer.STATUS_WITHDRAWN
        existing.run_id = run_id
        existing.updated_at = stamp
        return

    if existing is None:
        session.add(OpportunityOffer(
            business_id=business_id,
            opportunity_id=opportunity.id,
            suggested_discount_bp=int(rung),
            margin_bp_at_suggestion=candidate.offer_margin_bp,
            floor_bp_at_suggestion=candidate.offer_floor_bp,
            tier=candidate.offer_tier,
            margin_basis=candidate.offer_margin_basis,
            margin_key=candidate.offer_margin_key,
            status=OpportunityOffer.STATUS_SUGGESTED,
            run_id=run_id,
            created_at=stamp,
            updated_at=stamp,
        ))
        return

    changed = (
        existing.suggested_discount_bp != int(rung)
        or existing.margin_bp_at_suggestion != candidate.offer_margin_bp
        or existing.floor_bp_at_suggestion != candidate.offer_floor_bp
    )
    if existing.status == OpportunityOffer.STATUS_APPROVED:
        if changed:
            existing.status = OpportunityOffer.STATUS_STALE
            existing.decision_note_fa = (
                f"کهنه شد: مبنای پیشنهاد عوض شد (پله‌ی تازه {int(rung) / 100:g}٪، "
                f"حاشیه {(candidate.offer_margin_bp or 0) / 100:g}٪، "
                f"کف {(candidate.offer_floor_bp or 0) / 100:g}٪)؛ تأیید دوباره لازم است."
            )
    elif existing.status == OpportunityOffer.STATUS_REJECTED:
        if existing.suggested_discount_bp != int(rung):
            # پله‌ی متفاوت، پیشنهادِ تازه است؛ همان پله را هر روز دوباره پیشنهاد
            # نمی‌کنیم — ردِ انسان محترم است.
            existing.status = OpportunityOffer.STATUS_SUGGESTED
            existing.decision_note_fa = None
            existing.decided_by = None
            existing.decided_at = None
        else:
            existing.run_id = run_id
            existing.updated_at = stamp
            return
    else:
        existing.status = OpportunityOffer.STATUS_SUGGESTED

    existing.suggested_discount_bp = int(rung)
    existing.margin_bp_at_suggestion = candidate.offer_margin_bp
    existing.floor_bp_at_suggestion = candidate.offer_floor_bp
    existing.tier = candidate.offer_tier
    existing.margin_basis = candidate.offer_margin_basis
    existing.margin_key = candidate.offer_margin_key
    existing.run_id = run_id
    existing.updated_at = stamp


# ------------------------------------------------------------------ خواندن
def offers_by_opportunity(
    session: Session, opportunity_ids: set[int],
) -> dict[int, OpportunityOffer]:
    if not opportunity_ids:
        return {}
    rows = session.scalars(
        select(OpportunityOffer).where(
            OpportunityOffer.opportunity_id.in_(sorted(opportunity_ids))
        )
    ).all()
    return {row.opportunity_id: row for row in rows}


def offer_payload(offer: OpportunityOffer | None) -> dict | None:
    if offer is None:
        return None
    return {
        "suggested_discount_bp": offer.suggested_discount_bp,
        "suggested_discount_text": f"{offer.suggested_discount_bp / 100:g}٪",
        "status": offer.status,
        "tier": offer.tier,
        "margin_bp_at_suggestion": offer.margin_bp_at_suggestion,
        "floor_bp_at_suggestion": offer.floor_bp_at_suggestion,
        "decided_by": offer.decided_by,
        "decided_at": offer.decided_at,
        "decision_note_fa": offer.decision_note_fa,
        "updated_at": offer.updated_at,
        # قاعده‌ی سخت، همیشه در پاسخ: بدون approved چیزی ارسال نمی‌شود
        "sendable": offer.status == OpportunityOffer.STATUS_APPROVED,
    }


# ------------------------------------------------------------------ تصمیم
def decide_offer(
    opportunity_id: int,
    decision: str,
    *,
    decided_by: str | None = None,
    note_fa: str | None = None,
    actor_label: str | None = None,
    source_ip: str | None = None,
    db_path: Path | None = None,
) -> dict:
    """تأیید یا ردِ پیشنهادِ تخفیفِ یک فرصت — با بازمحاسبه‌ی حاشیه در همین لحظه."""
    if decision not in DECISIONS:
        raise OfferDecisionError(
            f"تصمیم نامعتبر است؛ مجاز: {'، '.join(DECISIONS)}", conflict=False,
        )
    ensure_schema(db_path)
    who = (decided_by or "").strip() or "کاربر"
    def _apply(session) -> tuple[dict | None, str | None]:
        opportunity = session.get(Opportunity, opportunity_id)
        if opportunity is None:
            raise OfferDecisionError("این فرصت یافت نشد.", conflict=False)
        offer = session.scalar(
            select(OpportunityOffer).where(OpportunityOffer.opportunity_id == opportunity_id)
        )
        if offer is None:
            raise OfferDecisionError(
                "برای این فرصت پیشنهادِ تخفیفی ثبت نشده است.", conflict=False,
            )

        stamp = now_ts()
        if offer.status == OpportunityOffer.STATUS_WITHDRAWN:
            raise OfferDecisionError(
                "این پیشنهاد برداشته شده است (موتور دیگر تخفیفی برای این فرصت پیشنهاد "
                "نمی‌دهد)؛ چیزی برای تصمیم نیست."
            )
        if decision == DECISION_REJECT:
            offer.status = OpportunityOffer.STATUS_REJECTED
            offer.decided_by, offer.decided_at = who, stamp
            offer.decision_note_fa = note_fa
            event_type, action = "offer_rejected", AuditEvent.ACTION_OFFER_REJECTED
            detail = f"تخفیفِ پیشنهادی {offer.suggested_discount_bp / 100:g}٪ رد شد."
        else:
            from mktcore.settings_store import offer_ladder_bp

            # نردبانِ **جاری**: پله‌ای که دیگر روی نردبان نیست (یا نردبانی نیست)
            # تأیید نمی‌شود — وگرنه ردیفِ کهنه‌ی یک نردبانِ برداشته‌شده با یک
            # کلیک به پیامک می‌رسید.
            ladder = offer_ladder_bp(session, opportunity.business_id)
            if ladder is None:
                return None, _refuse(
                    session, opportunity, offer, who, actor_label, source_ip, stamp,
                    "نردبانِ تخفیف تعیین نشده است؛ تا نردبانی نباشد، هیچ تخفیفی تأیید نمی‌شود.",
                )
            if offer.suggested_discount_bp not in ladder:
                return None, _refuse(
                    session, opportunity, offer, who, actor_label, source_ip, stamp,
                    f"پله‌ی {offer.suggested_discount_bp / 100:g}٪ روی نردبانِ فعلی "
                    f"({'، '.join(f'{r / 100:g}٪' for r in ladder)}) نیست؛ منتظرِ پیشنهادِ "
                    "تازه‌ی موتور بمانید.",
                )
            margin_bp, floor_bp = _current_margin_and_floor(session, opportunity, offer)
            if floor_bp is None:
                return None, _refuse(
                    session, opportunity, offer, who, actor_label, source_ip, stamp,
                    "کف حاشیه تعیین نشده است؛ بدون کف، هیچ تخفیفی تأیید نمی‌شود.",
                )
            if margin_bp is None:
                return None, _refuse(
                    session, opportunity, offer, who, actor_label, source_ip, stamp,
                    "حاشیه‌ی مبنای این پیشنهاد در حال حاضر محاسبه‌شدنی نیست (بها ندارد)؛ "
                    "تأیید ممکن نیست.",
                )
            post = post_discount_margin_bp(margin_bp, offer.suggested_discount_bp)
            if post is None or post < floor_bp:
                return None, _refuse(
                    session, opportunity, offer, who, actor_label, source_ip, stamp,
                    f"تأیید رد شد: با حاشیه‌ی امروز ({margin_bp / 100:g}٪) این پله "
                    f"حاشیه را به {(post or 0) / 100:g}٪ می‌رساند که زیرِ کف "
                    f"({floor_bp / 100:g}٪) است.",
                )
            offer.status = OpportunityOffer.STATUS_APPROVED
            offer.margin_bp_at_suggestion = margin_bp
            offer.floor_bp_at_suggestion = floor_bp
            offer.decided_by, offer.decided_at = who, stamp
            offer.decision_note_fa = note_fa
            event_type, action = "offer_approved", AuditEvent.ACTION_OFFER_APPROVED
            detail = (
                f"تخفیفِ {offer.suggested_discount_bp / 100:g}٪ تأیید شد؛ حاشیه‌ی پس از "
                f"تخفیف {post / 100:g}٪ (کف {floor_bp / 100:g}٪)."
            )
        offer.updated_at = stamp

        session.add(OpportunityEvent(
            opportunity_id=opportunity_id,
            event_type=event_type,
            from_status=opportunity.status,
            to_status=opportunity.status,
            actor=who,
            note_fa=detail,
        ))
        record_audit_event(
            session,
            action=action,
            business_id=opportunity.business_id,
            entity_type="opportunity",
            entity_id=opportunity_id,
            actor=actor_label or who,
            source_ip=source_ip,
            detail_fa=f"{detail} (تصمیم‌گیرنده: {who})",
        )
        session.flush()
        return offer_payload(offer), None

    with write_lock, session_scope(db_path) as session:
        payload, refusal = _apply(session)

    if refusal is not None:
        raise OfferDecisionError(refusal)
    assert payload is not None
    return payload


def _refuse(
    session: Session, opportunity: Opportunity, offer: OpportunityOffer,
    who: str, actor_label: str | None, source_ip: str | None, stamp: float,
    reason_fa: str,
) -> str:
    """تأییدی که سیستم رد کرد — با رخداد و ممیزی، و بدون پاک‌کردنِ تصمیمِ انسان.

    * علامت باید **بماند**: اگر همین‌جا استثنا پرت شود، `session_scope` تراکنش را
      rollback می‌کند. پس فقط ردیف را علامت می‌زنیم و دلیل را برمی‌گردانیم؛
      فراخوان بعد از commit استثنا می‌اندازد.
    * ردِ قبلیِ انسان (`rejected`) دست نمی‌خورد: یک تأییدِ ناموفق نباید یادداشتِ
      «نه، این مشتری تخفیف نمی‌خواهد» را با متنِ سیستم بازنویسی کند.
    """
    if offer.status != OpportunityOffer.STATUS_REJECTED:
        offer.status = OpportunityOffer.STATUS_STALE
        if offer.decided_by is None:
            offer.decision_note_fa = reason_fa
    offer.updated_at = stamp
    session.add(OpportunityEvent(
        opportunity_id=opportunity.id,
        event_type="offer_approval_refused",
        from_status=opportunity.status,
        to_status=opportunity.status,
        actor=who,
        note_fa=reason_fa,
    ))
    record_audit_event(
        session,
        action=AuditEvent.ACTION_OFFER_APPROVAL_REFUSED,
        business_id=opportunity.business_id,
        entity_type="opportunity",
        entity_id=opportunity.id,
        actor=actor_label or who,
        source_ip=source_ip,
        detail_fa=f"{reason_fa} (درخواست‌دهنده: {who})",
    )
    session.flush()
    return reason_fa


def _current_margin_and_floor(
    session: Session, opportunity: Opportunity, offer: OpportunityOffer,
) -> tuple[int | None, int | None]:
    """حاشیه‌ی **امروز** با همان مبنایی که موتور پیشنهاد را رویش ساخت.

    مبنا روی خودِ ردیف است (`margin_basis`/`margin_key`). ردیف‌های پیش از
    مهاجرت ۱۶ مبنا ندارند؛ برایشان همان قاعده‌ی موتور بازسازی می‌شود: نامِ کالا
    اگر هست، وگرنه سبدِ مشتری.
    """
    from mktcore.costs.register import margin_by_customer, margin_lookup
    from mktcore.settings_store import margin_floor_bp

    floor = margin_floor_bp(session, opportunity.business_id)
    basis, key = offer.margin_basis, offer.margin_key
    if basis is None:
        product = session.get(Product, opportunity.product_id) if opportunity.product_id else None
        if product is not None:
            basis, key = OFFER_BASIS_NAME, product.display_name or product.canonical_name
        else:
            basis = OFFER_BASIS_CUSTOMER

    if basis == OFFER_BASIS_NAME:
        margins = margin_lookup(session, opportunity.business_id)
        for name in (key, normalize_product_name(key) if key else None):
            if name and name in margins:
                return int(margins[name]), floor
        return None, floor
    if opportunity.customer_id is None:
        return None, floor
    return margin_by_customer(session, opportunity.business_id).get(
        int(opportunity.customer_id)
    ), floor
