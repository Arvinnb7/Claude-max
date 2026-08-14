"""مشاهده‌ی نتیجه از دفتر کل — اینجاست که فاز ۱ ارزشش را نشان می‌دهد.

کاربر فایل ماه بعد را بارگذاری می‌کند؛ خطوط فروش در دفتر کل می‌نشینند؛ و ما
دقیقاً می‌دانیم هر مشتری **در پنجره‌ی سنجش** چه خریده است. بدون دفتر کلِ
هویت‌دار، این پرسش پاسخ نداشت: فایل ماه بعد مشتریان را با کلیدهای دیگری
می‌شناسد و «همان آدم» قابل ردیابی نبود.

## پنجره‌ی سنجش

برای گروه آزمایش از **لحظه‌ی تماس** شروع می‌شود، و برای گروه کنترل از
**لحظه‌ی تخصیص** — چون تماسی در کار نبوده. اگر برای کنترل هم از تاریخ تماسِ
گروه دیگر استفاده می‌شد، دو گروه پنجره‌های متفاوتی می‌گرفتند و مقایسه
بی‌معنا می‌شد.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pandas as pd
from sqlalchemy import func, select

from mktcore.db.base import now_ts
from mktcore.db.engine import session_scope, write_lock
from mktcore.db.migrations import ensure_schema
from mktcore.db.models import (
    Business,
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

logger = logging.getLogger("mktcore.campaigns.outcomes")

CHUNK = 1000


def _window(member: CampaignMember, window_days: int) -> tuple[str, str]:
    """بازه‌ی سنجش این عضو، به‌صورت تاریخ ISO.

    مبنا برای گروه آزمایش **تاریخ تماس** است و برای گروه کنترل **تاریخ
    تخصیص** — چون تماسی در کار نبوده. اگر برای کنترل هم از تاریخ تماسِ گروه
    دیگر استفاده می‌شد، دو گروه پنجره‌های متفاوتی می‌گرفتند و مقایسه بی‌معنا
    می‌شد.
    """
    start = pd.Timestamp(member.exposure_date or member.assigned_date)
    end = start + pd.Timedelta(days=window_days)
    return start.date().isoformat(), end.date().isoformat()


def compute_campaign_outcomes(
    *,
    business_slug: str = "default",
    batch_id: int | None = None,
    db_path: Path | None = None,
) -> dict:
    """به‌روزرسانی عکسِ نتیجه برای همه‌ی کمپین‌های در جریان.

    idempotent است: اجرای دوباره همان عکس را بازنویسی می‌کند، نه ردیف تازه.
    """
    ensure_schema(db_path)
    summary = {"campaigns": 0, "members": 0, "converters": 0}

    with write_lock, session_scope(db_path) as session:
        business_id = session.scalar(
            select(Business.id).where(Business.slug == business_slug)
        )
        if business_id is None:
            return summary
        campaigns = session.scalars(
            select(Campaign).where(
                Campaign.business_id == business_id,
                Campaign.status != "closed",
            )
        ).all()
        if not campaigns:
            return summary

        for campaign in campaigns:
            members = session.scalars(
                select(CampaignMember).where(CampaignMember.campaign_id == campaign.id)
            ).all()
            if not members:
                continue
            # فقط اعضایی که پنجره‌شان شروع شده — گروه آزمایشِ بدون تماس هنوز
            # در آزمایش شرکت نکرده و نباید در مخرج بیاید.
            active = [m for m in members if m.exposure_at or m.arm == "control"]
            if not active:
                continue

            promised = _promised_products(session, campaign.id)
            written = 0
            converters = 0
            for start in range(0, len(active), CHUNK):
                chunk = active[start:start + CHUNK]
                rows = _outcome_rows(
                    session, campaign, chunk, promised=promised, batch_id=batch_id,
                )
                written += _upsert_outcomes(session, campaign.id, rows)
                converters += sum(1 for r in rows if r["orders_count"] > 0)

            summary["campaigns"] += 1
            summary["members"] += written
            summary["converters"] += converters

    logger.info("نتیجه‌ی کمپین‌ها به‌روز شد: %s", summary)
    return summary


def _promised_products(session: Session, campaign_id: int) -> dict[int, set[int]]:
    """کالاهایی که به هر مشتری وعده داده شده — برای سنجه‌ی «خریدِ همان کالا»."""
    rows = session.execute(
        select(CampaignOpportunity.customer_id, Opportunity.product_id)
        .join(Opportunity, Opportunity.id == CampaignOpportunity.opportunity_id)
        .where(CampaignOpportunity.campaign_id == campaign_id)
    ).all()
    out: dict[int, set[int]] = {}
    for customer_id, product_id in rows:
        if product_id is not None:
            out.setdefault(int(customer_id), set()).add(int(product_id))
    return out


def _outcome_rows(
    session: Session,
    campaign: Campaign,
    members: list[CampaignMember],
    *,
    promised: dict[int, set[int]],
    batch_id: int | None,
) -> list[dict]:
    by_customer = {m.customer_id: m for m in members}
    windows = {
        m.customer_id: _window(m, campaign.analysis_window_days) for m in members
    }

    # یک پرس‌وجو برای همه‌ی اعضای این تکه؛ پنجره‌ها بعداً در پایتون اعمال می‌شوند
    # چون هر عضو پنجره‌ی خودش را دارد.
    lines = session.execute(
        select(
            OrderLine.customer_id, OrderLine.line_date, OrderLine.order_id,
            OrderLine.product_id, OrderLine.revenue_rial, OrderLine.is_return,
        ).where(
            OrderLine.customer_id.in_(sorted(by_customer)),
            OrderLine.line_date >= min(w[0] for w in windows.values()),
            OrderLine.line_date < max(w[1] for w in windows.values()),
        )
    ).all()

    buckets: dict[int, dict] = {
        customer_id: {
            "orders": set(), "loose_lines": 0, "lines": 0,
            "revenue": 0, "matched": False,
        }
        for customer_id in by_customer
    }
    for customer_id, line_date, order_id, product_id, revenue, is_return in lines:
        window_start, window_end = windows[customer_id]
        if not (window_start <= line_date < window_end):
            continue
        bucket = buckets[customer_id]
        bucket["revenue"] += int(revenue or 0)
        if is_return:
            continue  # برگشت درآمد را کم می‌کند ولی «خرید» شمرده نمی‌شود
        bucket["lines"] += 1
        if order_id is not None:
            bucket["orders"].add(order_id)
        else:
            bucket["loose_lines"] += 1
        if product_id and product_id in promised.get(customer_id, set()):
            bucket["matched"] = True

    rows = []
    for customer_id, member in by_customer.items():
        bucket = buckets[customer_id]
        window_start, window_end = windows[customer_id]
        # فاکتورهای یکتا + خطوطی که اصلاً شماره‌ی فاکتور ندارند. وقتی فایل ستون
        # فاکتور ندارد، هر خط یک خرید است — همان قراردادی که `kpis.n_orders`
        # دارد؛ جمع‌کردن همه‌ی آن‌ها در «یک سفارش» خرید را کم‌شمار می‌کرد.
        orders = len(bucket["orders"]) + bucket["loose_lines"]
        rows.append({
            "campaign_id": member.campaign_id,
            "customer_id": customer_id,
            "arm": member.arm,
            "window_start": window_start,
            "window_end": window_end,
            "orders_count": orders,
            "lines_count": bucket["lines"],
            "revenue_rial": bucket["revenue"],
            "matched_product": bucket["matched"],
            "source_batch_id": batch_id,
            "computed_at": now_ts(),
        })
    return rows


def _upsert_outcomes(session: Session, campaign_id: int, rows: list[dict]) -> int:
    from sqlalchemy import insert, update

    if not rows:
        return 0
    existing = {
        customer_id: row_id
        for customer_id, row_id in session.execute(
            select(CampaignOutcome.customer_id, CampaignOutcome.id).where(
                CampaignOutcome.campaign_id == campaign_id,
                CampaignOutcome.customer_id.in_([r["customer_id"] for r in rows]),
            )
        ).all()
    }
    to_insert = [r for r in rows if r["customer_id"] not in existing]
    to_update = [
        {**r, "id": existing[r["customer_id"]]}
        for r in rows if r["customer_id"] in existing
    ]
    if to_insert:
        session.execute(insert(CampaignOutcome), to_insert)
    if to_update:
        session.execute(update(CampaignOutcome), to_update)
    session.flush()
    return len(rows)


def arm_stats(session: Session, campaign_id: int) -> dict[str, dict]:
    """جمع‌بندی هر بازو از عکس‌های ثبت‌شده — ورودی گزارش اثر."""
    rows = session.execute(
        select(
            CampaignOutcome.arm,
            func.count(CampaignOutcome.id),
            func.sum(func.iif(CampaignOutcome.orders_count > 0, 1, 0)),
            func.sum(CampaignOutcome.orders_count),
            func.sum(CampaignOutcome.revenue_rial),
        ).where(CampaignOutcome.campaign_id == campaign_id)
        .group_by(CampaignOutcome.arm)
    ).all()
    return {
        str(arm): {
            "size": int(size or 0),
            "converters": int(converters or 0),
            "orders": int(orders or 0),
            "revenue_rial": int(revenue or 0),
        }
        for arm, size, converters, orders, revenue in rows
    }


__all__ = ["arm_stats", "compute_campaign_outcomes"]
