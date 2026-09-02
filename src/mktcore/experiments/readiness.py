"""سنجه‌ی آمادگیِ فاز ۵ — «چقدر تا دروازه مانده»، نه مدلِ بی‌پشتوانه.

## چرا این ماژول وجود دارد

سند بالای فاز ۵ نوشته «Deliver only when data gates pass». تا امروز آمادگی
فقط **سلولی** بود (`experiment-plan`: در هر سلولِ نوع × حالت چند نفر لازم است)
و `GET /uplift` فقط شمارِ خامِ مشاهده‌ها را می‌داد. هیچ‌جا یک عددِ سراسری
نمی‌گفت «برای مدلِ uplift به‌ازای مشتری (§۲۰.۴) یا کششِ قیمت (§۲۱) چقدر مانده».

## قاعده‌ی این ماژول

عددی که مبنایش وجود ندارد `None` است، نه صفر. «هیچ کمپینِ دوبازویی نداریم» با
«صفر مشاهده داریم» یکی نیست: اولی می‌گوید هنوز شروع نکرده‌ایم، دومی می‌گوید
شروع کرده‌ایم و چیزی یاد نگرفته‌ایم.
"""

from __future__ import annotations

import statistics
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from mktcore.db.engine import session_scope
from mktcore.db.lookup import resolve_business_id
from mktcore.db.migrations import ensure_schema
from mktcore.db.models import (
    Campaign,
    CampaignMember,
    CampaignOpportunity,
    CampaignOutcome,
    Opportunity,
    OrderLine,
)

if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.orm import Session

__all__ = ["phase5_readiness"]

# آمادگیِ تنوعِ قیمت: کالایی که دست‌کم این تعداد نقطه‌ی قیمتِ متمایز دارد و
# ضریب تغییراتش از این حد بیشتر است، «تنوعِ قیمت» دارد. اعدادِ محافظه‌کارانه؛
# کششِ قیمت بدون تنوعِ عامدانه اصلاً برآوردشدنی نیست (§۲۱.۱).
MIN_PRICE_POINTS = 3
MIN_PRICE_CV = 0.05
MIN_PRODUCTS_WITH_VARIATION = 5


def phase5_readiness(*, business_slug: str = "default", db_path: Path | None = None) -> dict:
    ensure_schema(db_path)
    from mktcore.settings_store import data_gate_thresholds

    with session_scope(db_path) as session:
        business_id = resolve_business_id(session, business_slug)
        if business_id is None:
            return {
                "available": False,
                "note_fa": "هنوز تحلیلی در دفتر کل ثبت نشده است.",
            }
        gates = data_gate_thresholds(session, business_id)
        cells, two_armed = _offer_cells(session, business_id)
        price = _price_variation(session, business_id)

    minimum = int(gates["min_cell_observations"])
    for cell in cells:
        cell["required_per_arm"] = minimum
        cell["ready"] = cell["n_treatment"] >= minimum and cell["n_control"] >= minimum
    ready_cells = sum(1 for c in cells if c["ready"])
    with_offer = [c for c in cells if c["offer_bp"]]
    total_obs = sum(c["n_treatment"] + c["n_control"] for c in cells)

    if not two_armed:
        uplift_note = (
            "هیچ کمپینِ دوبازویی (با گروه کنترل) بسته نشده است؛ مدلِ uplift به‌ازای "
            "مشتری (§۲۰.۴) هنوز هیچ داده‌ای برای یادگیری ندارد."
        )
    elif not with_offer:
        uplift_note = (
            f"{len(two_armed)} کمپینِ دوبازویی و {total_obs} مشاهده هست، ولی هیچ‌کدام "
            "با سطحِ آفرِ تأییدشده نبوده؛ حساسیت به تخفیف هنوز قابل اندازه‌گیری نیست."
        )
    else:
        uplift_note = (
            f"{ready_cells} از {len(cells)} سلول به آستانه‌ی {minimum} مشاهده در هر بازو "
            "رسیده‌اند."
        )

    return {
        "available": True,
        "thresholds": gates,
        "uplift": {
            "two_armed_campaigns": len(two_armed),
            "observations_total": total_obs,
            "cells_total": len(cells),
            "cells_ready": ready_cells,
            "cells_with_offer": len(with_offer),
            "cells": sorted(cells, key=lambda c: (-c["n_treatment"], c["kind"], c["offer_bp"])),
            "ready": bool(with_offer) and ready_cells > 0,
            "note_fa": uplift_note,
        },
        "price_variation": price,
        "overall": {
            # آماده یعنی هر دو دروازه؛ تا آن روز، مدل‌های فاز ۵ ساخته نمی‌شوند.
            "ready": bool(with_offer) and ready_cells > 0 and bool(price.get("ready")),
            "note_fa": (
                "دروازه‌ی داده‌ی فاز ۵ باز نیست؛ آنچه ساخته شده سنجه‌ی آمادگی است، "
                "نه مدل. با ارسالِ واقعیِ کمپین‌های آفردار و بستنِ پنجره‌ی سنجش، "
                "این اعداد بالا می‌روند."
            ),
        },
    }


def _offer_cells(session: Session, business_id: int) -> tuple[list[dict], list[int]]:
    """سلول‌های (نوع × سطحِ آفر) با شمارِ تیمار/کنترل از کمپین‌های دوبازویی."""
    arms_per_campaign = session.execute(
        select(CampaignOutcome.campaign_id, func.count(func.distinct(CampaignOutcome.arm)))
        .join(Campaign, Campaign.id == CampaignOutcome.campaign_id)
        .where(Campaign.business_id == business_id)
        .group_by(CampaignOutcome.campaign_id)
    ).all()
    two_armed = [int(cid) for cid, n_arms in arms_per_campaign if int(n_arms) >= 2]
    if not two_armed:
        return [], []

    kind_rows = session.execute(
        select(
            CampaignOpportunity.campaign_id, CampaignOpportunity.customer_id,
            Opportunity.kind, Opportunity.expected_value_rial,
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

    offer_of = {
        (int(c), int(cu)): int(bp or 0)
        for c, cu, bp in session.execute(
            select(CampaignMember.campaign_id, CampaignMember.customer_id,
                   CampaignMember.offer_discount_bp)
            .where(CampaignMember.campaign_id.in_(two_armed))
        ).all()
    }

    counts: dict[tuple[str, int], dict] = {}
    for campaign_id, customer_id, arm in session.execute(
        select(CampaignOutcome.campaign_id, CampaignOutcome.customer_id, CampaignOutcome.arm)
        .where(CampaignOutcome.campaign_id.in_(two_armed))
    ).all():
        key = (int(campaign_id), int(customer_id))
        entry = kind_of.get(key)
        if entry is None:
            continue
        cell = counts.setdefault(
            (entry[0], offer_of.get(key, 0)),
            {"kind": entry[0], "offer_bp": offer_of.get(key, 0), "n_treatment": 0, "n_control": 0},
        )
        if str(arm) == "control":
            cell["n_control"] += 1
        else:
            cell["n_treatment"] += 1
    return list(counts.values()), two_armed


def _price_variation(session: Session, business_id: int) -> dict:
    """آمادگیِ کششِ قیمت (§۲۱): آیا اصلاً قیمتِ یک کالا تغییر کرده که اثرش سنجیدنی باشد؟"""
    total, priced = session.execute(
        select(func.count(OrderLine.id), func.count(OrderLine.unit_price_rial))
        .where(OrderLine.business_id == business_id, OrderLine.is_return.is_(False))
    ).one()
    total, priced = int(total or 0), int(priced or 0)
    if not total or not priced:
        return {
            "coverage": None if not total else 0.0,
            "products": 0,
            "products_with_variation": 0,
            "median_cv": None,
            "ready": None if not total else False,
            "note_fa": (
                "دفتر کل خالی است." if not total else
                "ستون قیمت واحد در داده نیست؛ تنوعِ قیمت سنجیده نشد."
            ),
        }

    rows = session.execute(
        select(OrderLine.product_id, OrderLine.unit_price_rial)
        .where(
            OrderLine.business_id == business_id,
            OrderLine.is_return.is_(False),
            OrderLine.product_id.isnot(None),
            OrderLine.unit_price_rial.isnot(None),
        )
    ).all()
    prices: dict[int, list[int]] = {}
    for product_id, price in rows:
        prices.setdefault(int(product_id), []).append(int(price))

    cvs: list[float] = []
    with_variation = 0
    for values in prices.values():
        if len(values) < 2:
            continue
        mean = statistics.fmean(values)
        if mean <= 0:
            continue
        cv = statistics.pstdev(values) / mean
        cvs.append(cv)
        if len(set(values)) >= MIN_PRICE_POINTS and cv >= MIN_PRICE_CV:
            with_variation += 1

    coverage = round(priced / total, 4)
    median_cv = round(statistics.median(cvs), 4) if cvs else None
    ready = with_variation >= MIN_PRODUCTS_WITH_VARIATION
    return {
        "coverage": coverage,
        "products": len(prices),
        "products_with_variation": with_variation,
        "median_cv": median_cv,
        "ready": ready,
        "note_fa": (
            f"{with_variation} کالا دست‌کم {MIN_PRICE_POINTS} نقطه‌ی قیمتِ متمایز با پراکندگیِ "
            f"معنادار دارند (لازم: {MIN_PRODUCTS_WITH_VARIATION}). "
            + (
                "تنوعِ قیمتِ طبیعی هست، ولی کشش فقط با تنوعِ **عامدانه** و کنترلِ "
                "موجودی/پروموشن برآوردشدنی است (§۲۱.۱)."
                if ready else
                "بدون تنوعِ قیمت، کششِ قیمت (§۲۱) برآوردشدنی نیست — و عددِ حدسی هم "
                "ساخته نمی‌شود."
            )
        ),
    }
