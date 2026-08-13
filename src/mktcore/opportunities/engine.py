"""اجرای موتور فرصت‌ها و ماندگارسازی با چرخه‌ی حیات.

قواعد چرخه‌ی حیات (تصمیم‌های صریح، نه پیش‌فرضِ اتفاقی):

* فرصتِ تازه → `open`.
* فرصتی که دوباره تولید شد → **تازه‌سازی** می‌شود (ارزش، متن، شواهد)، ولی
  **وضعیت انسانی بازنویسی نمی‌شود**: اگر کسی آن را پذیرفته یا رد کرده، تصمیمش
  با اجرای بعدیِ موتور پاک نمی‌شود.
* فرصتِ بازی که دیگر تولید نشد → `superseded` («دیگر مصداق ندارد»)، نه حذف.
  حذف یعنی از دست دادن تاریخچه‌ای که برای سنجش اثر لازم است.
* فرصتی که از تاریخ انقضا گذشت → `expired`.
* هر تغییر وضعیت یک رخداد append-only ثبت می‌کند.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import pandas as pd
from sqlalchemy import select

from mktcore.db.base import now_ts
from mktcore.db.engine import session_scope, write_lock
from mktcore.db.lookup import customer_ids_by_raw_key, product_ids_by_raw_name
from mktcore.db.migrations import ensure_schema
from mktcore.db.models import (
    Business,
    Opportunity,
    OpportunityEvent,
    OpportunityFactor,
    OpportunityRun,
)
from mktcore.money import to_basis_points, to_rial_int

from .contract import OpportunityCandidate
from .filters import apply_filters
from .generators import generate_candidates

if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.orm import Session

logger = logging.getLogger("mktcore.opportunities.engine")

ENGINE_VERSION = 1

STATUS_OPEN = "open"
STATUS_ACCEPTED = "accepted"
STATUS_DISMISSED = "dismissed"
STATUS_SNOOZED = "snoozed"
STATUS_DONE = "done"
STATUS_EXPIRED = "expired"
STATUS_SUPERSEDED = "superseded"

# وضعیت‌هایی که انسان تعیین کرده و موتور حق بازنویسی‌شان را ندارد
_HUMAN_STATUSES = frozenset({STATUS_ACCEPTED, STATUS_DISMISSED, STATUS_SNOOZED, STATUS_DONE})
# وضعیت‌هایی که «هنوز روی میز» محسوب می‌شوند
_LIVE_STATUSES = frozenset({STATUS_OPEN, STATUS_ACCEPTED, STATUS_SNOOZED})

# اعتبار پیش‌فرض یک فرصت. فرصتِ بی‌انقضا صندوق را از کارهای کهنه پر می‌کند.
DEFAULT_TTL_DAYS = 45

# سقف فرصت‌هایی که در هر اجرا ماندگار می‌شوند.
# نامزدها گسترده تولید می‌شوند (تا مقایسه‌ی رتبه‌بندی معنادار باشد) ولی صندوقی
# با هزاران کارت برای تیم فروش بی‌فایده است — و نوشتنِ همه‌ی آن‌ها در هر تحلیل
# هزینه‌ی واقعی دارد. ارزشمندترین‌ها می‌مانند و **تعداد حذف‌شده‌ها صریحاً
# گزارش می‌شود** (سقفِ بی‌صدا ممنوع است).
MAX_PERSISTED_PER_RUN = 500


@dataclass
class OpportunityRunResult:
    run_id: int
    generated: int
    filtered_out: int
    created: int
    refreshed: int
    superseded: int
    expired: int
    capped_out: int = 0
    skipped_filters: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        payload = {
            "run_id": self.run_id,
            "generated": self.generated,
            "filtered_out": self.filtered_out,
            "created": self.created,
            "refreshed": self.refreshed,
            "superseded": self.superseded,
            "expired": self.expired,
            "capped_out": self.capped_out,
            "skipped_filters": self.skipped_filters,
        }
        if self.capped_out:
            payload["cap_note_fa"] = (
                f"{self.capped_out} فرصتِ کم‌ارزش‌تر ذخیره نشد؛ سقف هر اجرا "
                f"{MAX_PERSISTED_PER_RUN} فرصت است."
            )
        return payload


def _as_of(clean: pd.DataFrame) -> str:
    if "date" in clean.columns and len(clean):
        stamp = pd.Timestamp(clean["date"].max())
        if not pd.isna(stamp):
            return stamp.date().isoformat()
    return pd.Timestamp.now().date().isoformat()


def _recently_contacted(window_days: int) -> tuple[set[str], int | None]:
    """مشتریانی که اخیراً پیام گرفته‌اند — از همان outbox موجود.

    خواندنِ فقط‌خواندنی از لایه‌ی legacy است و آن را تغییر نمی‌دهد.
    """
    try:
        from api.persistence import store

        return set(store.recent_contact_customer_ids(window_days)), window_days
    except Exception:  # noqa: BLE001 - نبودِ تاریخچه نباید موتور را بخواباند
        logger.debug("تاریخچه‌ی تماس در دسترس نبود؛ فیلتر خستگی رد شد", exc_info=True)
        return set(), None


def build_context(
    clean: pd.DataFrame,
    *,
    fatigue_window_days: int = 14,
    per_customer_open_cap: int = 3,
) -> dict:
    """ساخت زمینه‌ی فیلترها از آنچه **واقعاً** در دست است.

    هر کلیدِ «has_*» صادقانه از داده خوانده می‌شود؛ هیچ‌کدام فرضِ خوش‌بینانه
    ندارند.
    """
    recent, window = _recently_contacted(fatigue_window_days)
    has_cost = bool(
        "cost" in clean.columns and clean["cost"].notna().any()
    )
    return {
        "has_cost_data": has_cost,
        # کفِ حاشیه حتی با وجود ستون بها تعیین نشده است: معنای آن ستون (خرید؟
        # تمام‌شده؟ با سربار؟) باید از کاربر پرسیده شود، نه حدس زده شود.
        "margin_floor_bp": None,
        "has_inventory_data": False,   # هیچ مسیر ورودِ موجودی وجود ندارد
        "has_consent_data": False,     # داده‌ی رضایت در فایل فروش نیست
        "compatibility_rules": None,   # قاعده‌ی دامنه‌ای تعریف نشده است
        "recently_contacted": recent,
        "fatigue_window_days": window,
        "per_customer_open_cap": per_customer_open_cap,
    }


def run_opportunity_engine(
    bundle: Any,
    clean: pd.DataFrame,
    *,
    session_id: str | None = None,
    display_currency: str = "تومان",
    business_slug: str = "default",
    db_path: Path | None = None,
) -> OpportunityRunResult | None:
    """یک اجرای کامل: تولید → فیلتر → ماندگارسازی → چرخه‌ی حیات."""
    ensure_schema(db_path)
    as_of = _as_of(clean)
    candidates = generate_candidates(bundle, clean)
    ctx = build_context(clean)
    accepted, rejected = apply_filters(candidates, ctx)

    # `apply_filters` خروجی را بر پایه‌ی ارزش نزولی پردازش می‌کند، پس بریدنِ
    # انتها یعنی حذف کم‌ارزش‌ترین‌ها — نه تصادفی‌ها.
    overflow = accepted[MAX_PERSISTED_PER_RUN:]
    capped_out = len(overflow)
    if capped_out:
        accepted = accepted[:MAX_PERSISTED_PER_RUN]
        logger.info(
            "سقف صندوق: %s فرصتِ کم‌ارزش‌تر از %s نامزدِ واجد شرایط ذخیره نشد",
            capped_out, capped_out + MAX_PERSISTED_PER_RUN,
        )
    # فرصت‌هایی که فقط به‌خاطر سقف کنار ماندند هنوز **مصداق دارند**؛ اگر
    # «ناپدید» حساب شوند، هر اجرا بین باز و بی‌مصداق نوسان می‌کنند.
    still_valid = {c.dedupe_key() for c in overflow}

    skipped: dict[str, int] = {}
    for candidate in accepted:
        for note in candidate.factors:
            if note.outcome == "filter_skip":
                skipped[note.code] = skipped.get(note.code, 0) + 1

    with write_lock, session_scope(db_path) as session:
        business = session.scalar(select(Business).where(Business.slug == business_slug))
        if business is None:
            logger.warning("کسب‌وکار «%s» وجود ندارد؛ موتور فرصت‌ها اجرا نشد.", business_slug)
            return None

        run = OpportunityRun(
            business_id=business.id,
            session_id=session_id,
            as_of_date=as_of,
            engine_version=ENGINE_VERSION,
            candidates_generated=len(candidates),
            candidates_filtered=len(rejected),
            notes_json=json.dumps(
                {"skipped_filters": skipped, "capped_out": capped_out},
                ensure_ascii=False,
            ),
        )
        session.add(run)
        session.flush()

        customer_ids = _customer_ids(session, business.id, accepted)
        product_ids = _product_ids(session, business.id, accepted)

        created, refreshed, seen_keys = _persist(
            session, business.id, run.id, accepted,
            customer_ids=customer_ids, product_ids=product_ids,
            display_currency=display_currency, as_of=as_of,
        )
        superseded = _supersede_missing(
            session, business.id, run.id, seen_keys | still_valid,
        )
        expired = _expire_overdue(session, business.id, as_of)

        run.opportunities_created = created
        run.opportunities_refreshed = refreshed
        run.opportunities_superseded = superseded
        run.opportunities_expired = expired
        run_id = run.id

    result = OpportunityRunResult(
        run_id=run_id,
        generated=len(candidates),
        filtered_out=len(rejected),
        created=created,
        refreshed=refreshed,
        superseded=superseded,
        expired=expired,
        capped_out=capped_out,
        skipped_filters=skipped,
    )
    logger.info("موتور فرصت‌ها: %s", result.to_dict())
    return result


# ------------------------------------------------------------------ کمکی‌ها
def _customer_ids(
    session: Session, business_id: int, candidates: list[OpportunityCandidate],
) -> dict[str, int]:
    return customer_ids_by_raw_key(
        session, business_id, (c.customer_key for c in candidates if c.customer_key),
    )


def _product_ids(
    session: Session, business_id: int, candidates: list[OpportunityCandidate],
) -> dict[str, int]:
    return product_ids_by_raw_name(
        session, business_id, (c.product_name for c in candidates if c.product_name),
    )


def _expiry_date(as_of: str, ttl_days: int = DEFAULT_TTL_DAYS) -> str:
    return (pd.Timestamp(as_of) + pd.Timedelta(days=ttl_days)).date().isoformat()


def _persist(
    session: Session,
    business_id: int,
    run_id: int,
    candidates: list[OpportunityCandidate],
    *,
    customer_ids: dict[str, int],
    product_ids: dict[str, int],
    display_currency: str,
    as_of: str,
) -> tuple[int, int, set[str]]:
    keys = [c.dedupe_key() for c in candidates]
    existing: dict[str, Opportunity] = {}
    for start in range(0, len(keys), 2000):
        rows = session.scalars(
            select(Opportunity).where(
                Opportunity.business_id == business_id,
                Opportunity.dedupe_key.in_(keys[start:start + 2000]),
            )
        ).all()
        existing.update({o.dedupe_key: o for o in rows})

    created = refreshed = 0
    seen: set[str] = set()
    for candidate in candidates:
        key = candidate.dedupe_key()
        if key in seen:
            # دو نامزد با کلید یکسان در یک اجرا (مثلاً دو مولد که به یک
            # پیشنهاد رسیده‌اند): اولی برنده است. بدون این گارد، دومی به قید
            # یکتایی می‌خورد و کل اجرا rollback می‌شد.
            continue
        seen.add(key)
        value_rial = to_rial_int(candidate.expected_value_display, display_currency) or 0
        fields = {
            "customer_id": customer_ids.get(candidate.customer_key),
            "product_id": product_ids.get(candidate.product_name) if candidate.product_name else None,
            "kind": candidate.kind,
            "generator": candidate.generator,
            "generator_version": candidate.generator_version,
            "title_fa": candidate.title_fa,
            "action_fa": candidate.action_fa,
            "reason_fa": candidate.reason_fa,
            "message_fa": candidate.message_fa,
            "expected_value_rial": value_rial,
            "score_rial": value_rial,
            "value_kind": candidate.value_kind,
            "probability_bp": to_basis_points(candidate.probability),
            "confidence": candidate.confidence,
            "owner_hint": candidate.owner_hint,
            "due_date": candidate.due_date,
            "expires_at": candidate.expires_at or _expiry_date(as_of),
            "last_seen_run_id": run_id,
            "updated_at": now_ts(),
        }

        opportunity = existing.get(key)
        if opportunity is None:
            opportunity = Opportunity(
                business_id=business_id, dedupe_key=key,
                status=STATUS_OPEN, first_seen_run_id=run_id, seen_count=1,
                **fields,
            )
            session.add(opportunity)
            session.flush()
            _add_event(session, opportunity.id, "created", None, STATUS_OPEN,
                       note="فرصت تازه توسط موتور ساخته شد.")
            created += 1
        else:
            for name, value in fields.items():
                setattr(opportunity, name, value)
            opportunity.seen_count += 1
            # وضعیت انسانی دست‌نخورده می‌ماند؛ فقط فرصتی که **موتور** خودش کنار
            # گذاشته بود دوباره باز می‌شود. شرط بر پایه‌ی «انسانی نبودن» نوشته
            # شده، نه فهرست وضعیت‌های ماشینی: افزودن وضعیت ماشینیِ تازه در
            # آینده نباید بی‌صدا تصمیم کاربر را بازنویسی کند.
            if opportunity.status not in _HUMAN_STATUSES and opportunity.status != STATUS_OPEN:
                previous = opportunity.status
                opportunity.status = STATUS_OPEN
                opportunity.status_reason_fa = None
                _add_event(session, opportunity.id, "reopened", previous, STATUS_OPEN,
                           note="این فرصت دوباره مصداق پیدا کرد.")
            _add_event(session, opportunity.id, "refreshed", opportunity.status,
                       opportunity.status, note="شواهد و ارزش با تحلیل تازه به‌روز شد.")
            refreshed += 1

        _replace_factors(session, opportunity.id, candidate)

    session.flush()
    return created, refreshed, seen


def _replace_factors(
    session: Session, opportunity_id: int, candidate: OpportunityCandidate,
) -> None:
    """شواهد همیشه بازتاب آخرین اجرا هستند، پس جایگزین می‌شوند نه انباشته."""
    session.query(OpportunityFactor).filter(
        OpportunityFactor.opportunity_id == opportunity_id
    ).delete(synchronize_session=False)
    seen_codes: set[str] = set()
    for note in candidate.factors:
        if note.code in seen_codes:
            continue
        seen_codes.add(note.code)
        session.add(OpportunityFactor(
            opportunity_id=opportunity_id,
            code=note.code,
            label_fa=note.label_fa,
            outcome=note.outcome,
            detail_fa=note.detail_fa,
            value_text=note.value_text,
        ))


def _supersede_missing(
    session: Session, business_id: int, run_id: int, seen_keys: set[str],
) -> int:
    """فرصت‌های بازی که این بار تولید نشدند → «دیگر مصداق ندارد».

    فرصتی که انسان پذیرفته یا اسنوز کرده دست‌نخورده می‌ماند: ممکن است تیم فروش
    روی آن کار کند و ناپدیدشدنش از خروجی مدل، دلیل لغو کارِ در جریان نیست.
    """
    live = session.scalars(
        select(Opportunity).where(
            Opportunity.business_id == business_id,
            Opportunity.status == STATUS_OPEN,
        )
    ).all()
    count = 0
    for opportunity in live:
        if opportunity.dedupe_key in seen_keys:
            continue
        opportunity.status = STATUS_SUPERSEDED
        opportunity.status_reason_fa = "در تحلیل تازه دیگر مصداق ندارد."
        opportunity.updated_at = now_ts()
        opportunity.last_seen_run_id = run_id
        _add_event(session, opportunity.id, "superseded", STATUS_OPEN, STATUS_SUPERSEDED,
                   note="تحلیل تازه این فرصت را دیگر تولید نکرد.")
        count += 1
    return count


def _expire_overdue(session: Session, business_id: int, as_of: str) -> int:
    overdue = session.scalars(
        select(Opportunity).where(
            Opportunity.business_id == business_id,
            Opportunity.status.in_(sorted(_LIVE_STATUSES)),
            Opportunity.expires_at.isnot(None),
            Opportunity.expires_at < as_of,
        )
    ).all()
    for opportunity in overdue:
        previous = opportunity.status
        opportunity.status = STATUS_EXPIRED
        opportunity.status_reason_fa = "از تاریخ اعتبار گذشت."
        opportunity.updated_at = now_ts()
        _add_event(session, opportunity.id, "expired", previous, STATUS_EXPIRED,
                   note=f"تاریخ اعتبار ({opportunity.expires_at}) گذشته است.")
    return len(overdue)


def _add_event(
    session: Session,
    opportunity_id: int,
    event_type: str,
    from_status: str | None,
    to_status: str | None,
    *,
    actor: str | None = None,
    note: str | None = None,
    payload: dict | None = None,
) -> None:
    session.add(OpportunityEvent(
        opportunity_id=opportunity_id,
        event_type=event_type,
        from_status=from_status,
        to_status=to_status,
        actor=actor or "system",
        note_fa=note,
        payload_json=json.dumps(payload, ensure_ascii=False) if payload else None,
    ))


__all__ = [
    "DEFAULT_TTL_DAYS",
    "ENGINE_VERSION",
    "STATUS_ACCEPTED",
    "STATUS_DISMISSED",
    "STATUS_DONE",
    "STATUS_EXPIRED",
    "STATUS_OPEN",
    "STATUS_SNOOZED",
    "STATUS_SUPERSEDED",
    "OpportunityRunResult",
    "build_context",
    "run_opportunity_engine",
]
