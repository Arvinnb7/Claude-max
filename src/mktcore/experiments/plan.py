"""خواندن عرضه‌ی سلول‌ها از دفتر کل و ساختنِ برنامه‌ی آزمایش.

`design.py` تابع خالص است؛ این ماژول تنها جایی است که به دیتابیس دست می‌زند.

**عرضه** = فرصت‌های بازِ صندوق، گروه‌بندی‌شده بر پایه‌ی (نوع اقدام × حالت چرخه‌ی
عمر). عمداً از همان `Opportunity`ها خوانده می‌شود که کمپین از آن‌ها ساخته می‌شود
(`campaigns_api.create_campaign`)، وگرنه برنامه چیزی را پیشنهاد می‌داد که در
عمل قابل کمپین‌کردن نیست.

مشتریانی که دروازه‌ی مجوز تماس کنارشان گذاشته (منصرف، یا عضوِ گروه کنترلِ کمپینِ
باز) از شمارش **حذف** می‌شوند: آن‌ها در عمل تماس نمی‌گیرند، پس شمردنشان به‌عنوان
«ظرفیت آزمایش» یک وعده‌ی توخالی است.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from mktcore.contact.register import build_gate
from mktcore.db.engine import session_scope
from mktcore.db.migrations import ensure_schema
from mktcore.db.models import Business, CustomerFeature, Opportunity

from .design import (
    DEFAULT_HOLDOUT_PCT,
    DEFAULT_TARGET_EFFECT,
    CellSupply,
    ExperimentPlan,
    build_plan,
)

if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.orm import Session

logger = logging.getLogger("mktcore.experiments.plan")

# حالتِ نامعلوم با همان نشانه‌ای ثبت می‌شود که جدولِ اثر به‌کار می‌برد، وگرنه
# سلول‌ها به هم وصل نمی‌شوند.
UNKNOWN_STATE = "—"

# فرصتی که «باز» نیست، در دسترسِ کمپین نیست. همان وضعیتی که `create_campaign`
# پیش‌فرض می‌گیرد.
OPEN_STATUS = "open"


def collect_supply(
    session: Session, business_id: int, *, exclude_blocked: bool = True,
) -> list[CellSupply]:
    """چند مشتریِ یکتا در هر سلول آماده‌ی تماس است."""
    latest = session.scalar(
        select(func.max(CustomerFeature.as_of_date))
        .where(CustomerFeature.business_id == business_id)
    )

    state_of: dict[int, str] = {}
    if latest is not None:
        rows = session.execute(
            select(CustomerFeature.customer_id, CustomerFeature.lifecycle_state).where(
                CustomerFeature.business_id == business_id,
                CustomerFeature.as_of_date == latest,
            )
        ).all()
        state_of = {int(cid): (state or UNKNOWN_STATE) for cid, state in rows}

    gate = build_gate(session, business_id) if exclude_blocked else None

    rows = session.execute(
        select(Opportunity.kind, Opportunity.customer_id).where(
            Opportunity.business_id == business_id,
            Opportunity.status == OPEN_STATUS,
            Opportunity.customer_id.isnot(None),
        )
    ).all()

    # مشتریِ یکتا در هر سلول: یک مشتری ممکن است چند فرصت از یک نوع داشته باشد و
    # دو بار شمردنش ظرفیتِ آزمایش را بیش‌برآورد می‌کند.
    buckets: dict[tuple[str, str], set[int]] = {}
    for kind, customer_id in rows:
        cid = int(customer_id)
        if gate is not None and gate.reason_for(str(cid)) is not None:
            continue
        key = (str(kind), state_of.get(cid, UNKNOWN_STATE))
        buckets.setdefault(key, set()).add(cid)

    return [
        CellSupply(kind=kind, lifecycle_state=state, available=len(members))
        for (kind, state), members in buckets.items()
    ]


def build_experiment_plan(
    *,
    business_slug: str = "default",
    db_path: Path | None = None,
    target_effect: float = DEFAULT_TARGET_EFFECT,
    holdout_pct: int = DEFAULT_HOLDOUT_PCT,
) -> ExperimentPlan:
    """نقطه‌ی ورود. جدولِ اثر اگر خوانده نشود `None` می‌ماند، نه اینکه خطا بدهد."""
    ensure_schema(db_path)
    with session_scope(db_path) as session:
        business_id = session.scalar(
            select(Business.id).where(Business.slug == business_slug)
        )
        if business_id is None:
            return build_plan([], None, target_effect=target_effect,
                              holdout_pct=holdout_pct)
        supplies = collect_supply(session, business_id)

    table = None
    try:
        from mktcore.uplift import build_uplift_table

        table = build_uplift_table(business_slug=business_slug, db_path=db_path)
        if not table.available:
            table = None
    except Exception:  # noqa: BLE001 - نبودِ یادگیری نباید برنامه را بخواباند
        logger.warning("جدولِ اثر خوانده نشد؛ همه‌ی سلول‌ها «بدون آزمایش» فرض شدند",
                       exc_info=True)

    return build_plan(supplies, table, target_effect=target_effect,
                      holdout_pct=holdout_pct)


__all__ = ["OPEN_STATUS", "UNKNOWN_STATE", "build_experiment_plan", "collect_supply"]
