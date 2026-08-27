"""ساخت جدول اثر از دفتر کل، و ذخیره‌ی عکسِ ماندگارش.

این ماژول پل بین دو چیز است: مشاهده‌های آزمایشی که در `campaign_outcomes`
نشسته‌اند، و تابع خالصِ `compute_uplift_table` که ریاضی را انجام می‌دهد.

نکته‌ی طراحی: مشاهده‌ها فقط از کمپین‌هایی خوانده می‌شوند که **هر دو بازو** را
دارند. کمپینِ بدون گروه کنترل هیچ چیزی درباره‌ی اثر نمی‌گوید، پس داده‌اش وارد
یادگیری نمی‌شود — وگرنه «نرخ خرید» به‌جای «اثر» یاد گرفته می‌شد و دقیقاً همان
خطایی تکرار می‌شد که این فاز برای رفعش ساخته شده.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pandas as pd
from sqlalchemy import func, insert, select

from mktcore.db.base import now_ts
from mktcore.db.engine import session_scope, write_lock
from mktcore.db.lookup import resolve_business_id
from mktcore.db.migrations import ensure_schema
from mktcore.db.models import (
    Campaign,
    CampaignMember,
    CampaignOpportunity,
    CampaignOutcome,
    CustomerFeature,
    Opportunity,
    UpliftSnapshot,
)

from .empirical import Observation, UpliftTable, compute_uplift_table

if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.orm import Session

logger = logging.getLogger("mktcore.uplift.snapshots")

# ردیف‌های جمعی در عکس با این نشانه ذخیره می‌شوند تا سلسله‌مراتب کامل بازتولید شود
AGGREGATE = "*"


def collect_observations(
    session: Session, business_id: int,
) -> list[Observation]:
    """استخراج مشاهده‌های آزمایشی از دفتر کل.

    هر عضوِ سنجیده‌شده‌ی یک کمپینِ دوبازویی، یک مشاهده است: در کدام بازو بود،
    چه نوع فرصتی داشت، در چه حالتی از چرخه‌ی عمر بود، و خرید کرد یا نه.
    """
    # کمپین‌هایی که هر دو بازو را دارند
    arms_per_campaign = session.execute(
        select(
            CampaignOutcome.campaign_id,
            func.count(func.distinct(CampaignOutcome.arm)),
        )
        .join(Campaign, Campaign.id == CampaignOutcome.campaign_id)
        .where(Campaign.business_id == business_id)
        .group_by(CampaignOutcome.campaign_id)
    ).all()
    two_armed = [int(cid) for cid, n_arms in arms_per_campaign if int(n_arms) >= 2]
    if not two_armed:
        return []

    # نوع فرصتِ هر (کمپین، مشتری). اگر مشتری چند فرصت دارد، پرارزش‌ترین ملاک است
    # چون همان چیزی است که رتبه‌بندی رویش تصمیم می‌گیرد.
    kind_rows = session.execute(
        select(
            CampaignOpportunity.campaign_id,
            CampaignOpportunity.customer_id,
            Opportunity.kind,
            Opportunity.expected_value_rial,
        )
        .join(Opportunity, Opportunity.id == CampaignOpportunity.opportunity_id)
        .where(CampaignOpportunity.campaign_id.in_(two_armed))
    ).all()
    kind_of: dict[tuple[int, int], tuple[str, int]] = {}
    for campaign_id, customer_id, kind, value in kind_rows:
        key = (int(campaign_id), int(customer_id))
        best = kind_of.get(key)
        if best is None or int(value or 0) > best[1]:
            kind_of[key] = (str(kind), int(value or 0))

    # حالت چرخه‌ی عمرِ هر مشتری در **زمان تخصیص** — نه امروز.
    # استفاده از حالت امروز نشت اطلاعات آینده بود: مشتری‌ای که بعد از تماس
    # «بازگشته» شده، در آموزش به‌عنوان «بازگشته» دیده می‌شد و اثر را بیش‌برآورد
    # می‌کرد.
    state_of = _states_at_assignment(session, business_id, two_armed)

    outcomes = session.execute(
        select(
            CampaignOutcome.campaign_id,
            CampaignOutcome.customer_id,
            CampaignOutcome.arm,
            CampaignOutcome.orders_count,
            CampaignOutcome.revenue_rial,
        ).where(CampaignOutcome.campaign_id.in_(two_armed))
    ).all()

    observations: list[Observation] = []
    for campaign_id, customer_id, arm, orders, revenue in outcomes:
        key = (int(campaign_id), int(customer_id))
        kind_entry = kind_of.get(key)
        if kind_entry is None:
            continue  # عضوی که فرصتی به آن نسبت داده نشده — چیزی نمی‌آموزد
        observations.append(Observation(
            kind=kind_entry[0],
            lifecycle_state=state_of.get(key),
            arm=str(arm),
            converted=int(orders or 0) > 0,
            revenue_rial=int(revenue or 0),
        ))
    return observations


def _states_at_assignment(
    session: Session, business_id: int, campaign_ids: list[int],
) -> dict[tuple[int, int], str | None]:
    """حالت چرخه‌ی عمر هر عضو در نزدیک‌ترین عکسِ **پیش از** تاریخ تخصیص."""
    members = session.execute(
        select(
            CampaignMember.campaign_id,
            CampaignMember.customer_id,
            CampaignMember.assigned_date,
        ).where(CampaignMember.campaign_id.in_(campaign_ids))
    ).all()
    if not members:
        return {}

    snapshots = session.execute(
        select(
            CustomerFeature.customer_id,
            CustomerFeature.as_of_date,
            CustomerFeature.lifecycle_state,
        ).where(
            CustomerFeature.business_id == business_id,
            CustomerFeature.lifecycle_state.isnot(None),
        ).order_by(CustomerFeature.customer_id, CustomerFeature.as_of_date)
    ).all()
    by_customer: dict[int, list[tuple[str, str]]] = {}
    for customer_id, as_of, state in snapshots:
        by_customer.setdefault(int(customer_id), []).append((str(as_of), str(state)))

    out: dict[tuple[int, int], str | None] = {}
    for campaign_id, customer_id, assigned_date in members:
        history = by_customer.get(int(customer_id), [])
        chosen = None
        for as_of, state in history:
            if as_of <= str(assigned_date):
                chosen = state
            else:
                break
        # اگر عکسی پیش از تخصیص نبود، نزدیک‌ترین عکسِ موجود بهتر از هیچ است —
        # ولی فقط وقتی هیچ گزینه‌ی «قبل» وجود ندارد.
        if chosen is None and history:
            chosen = history[0][1]
        out[(int(campaign_id), int(customer_id))] = chosen
    return out


def build_uplift_table(
    *, business_slug: str = "default", db_path: Path | None = None,
) -> UpliftTable:
    """ساخت جدول اثر از داده‌ی موجود (بدون ذخیره)."""
    ensure_schema(db_path)
    with session_scope(db_path) as session:
        business_id = resolve_business_id(session, business_slug)
        if business_id is None:
            return UpliftTable()
        observations = collect_observations(session, business_id)
    return compute_uplift_table(observations)


def _to_bp(value: float | None) -> int | None:
    """نسبت → basis point صحیح (قاعده‌ی «بدون float در دفتر کل»)."""
    return None if value is None else round(value * 10_000)


def save_snapshot(
    table: UpliftTable,
    *,
    as_of: str | None = None,
    business_slug: str = "default",
    db_path: Path | None = None,
) -> int:
    """ذخیره‌ی عکسِ جدول. اجرای دوباره روی همان تاریخ، عکس را بازنویسی می‌کند."""
    if not table.available:
        return 0
    ensure_schema(db_path)
    stamp = as_of or pd.Timestamp.now().date().isoformat()

    with write_lock, session_scope(db_path) as session:
        business_id = resolve_business_id(session, business_slug)
        if business_id is None:
            return 0

        session.query(UpliftSnapshot).filter(
            UpliftSnapshot.business_id == business_id,
            UpliftSnapshot.as_of_date == stamp,
        ).delete(synchronize_session=False)

        rows: list[dict] = []
        for cell in table.cells.values():
            rows.append({
                "business_id": business_id, "as_of_date": stamp,
                "cell_kind": cell.kind, "cell_state": cell.lifecycle_state,
                "n_treatment": cell.n_treatment, "n_control": cell.n_control,
                "conv_treatment": cell.conv_treatment,
                "conv_control": cell.conv_control,
                "raw_uplift_bp": _to_bp(cell.raw_uplift),
                "uplift_bp": _to_bp(cell.shrunk_uplift),
                "ci_low_bp": _to_bp(cell.ci[0]) if cell.ci else None,
                "ci_high_bp": _to_bp(cell.ci[1]) if cell.ci else None,
                "basis": cell.basis,
                "is_useless": cell.significantly_useless,
                "created_at": now_ts(),
            })
        # ردیف‌های جمعی: به‌ازای هر نوع، و کل
        for kind, value in table.by_kind.items():
            rows.append({
                "business_id": business_id, "as_of_date": stamp,
                "cell_kind": kind, "cell_state": AGGREGATE,
                "uplift_bp": _to_bp(value), "basis": "kind",
                "is_useless": False, "created_at": now_ts(),
            })
        if table.global_uplift is not None:
            rows.append({
                "business_id": business_id, "as_of_date": stamp,
                "cell_kind": AGGREGATE, "cell_state": AGGREGATE,
                "uplift_bp": _to_bp(table.global_uplift), "basis": "global",
                "is_useless": False, "created_at": now_ts(),
            })

        if rows:
            session.execute(insert(UpliftSnapshot), rows)
            session.flush()

    logger.info("عکس اثر (%s): %s ردیف", stamp, len(rows))
    return len(rows)


def refresh_uplift(
    *, business_slug: str = "default", db_path: Path | None = None,
) -> dict:
    """ساخت جدول اثر و ذخیره‌ی عکسش — نقطه‌ی ورودِ هوکِ تحلیل."""
    table = build_uplift_table(business_slug=business_slug, db_path=db_path)
    saved = save_snapshot(table, business_slug=business_slug, db_path=db_path)
    useless = sum(1 for c in table.cells.values() if c.significantly_useless)
    return {
        "observations": table.n_observations,
        "cells": len(table.cells),
        "snapshot_rows": saved,
        "useless_cells": useless,
        "global_uplift": table.global_uplift,
    }


__all__ = [
    "AGGREGATE",
    "build_uplift_table",
    "collect_observations",
    "refresh_uplift",
    "save_snapshot",
]
