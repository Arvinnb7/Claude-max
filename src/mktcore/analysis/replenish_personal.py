"""آهنگِ خریدِ **شخصی** به‌ازای جفتِ (مشتری، کالا) — §۱۳.۲ پله‌ی ۱، §۱۳.۳، §۱۳.۴.

قهرمان (`analysis/purchase_cycle.py`) فاصله‌های شخصی را می‌سازد و همان‌جا در میانه‌ی
کالا حل می‌کند؛ کارتِ یادآوری «آهنگِ مشتری» را می‌گوید ولی عددِ جمعیت را نشان می‌دهد.
این ماژول همان جفت‌ها را نگه می‌دارد و برای هر کدام، **فقط با شواهدِ کافی**:

* فاصله‌ی موردانتظار = میانه‌ی وزنیِ فاصله‌های خرید (وزنِ تازگی ۰٫۷۵ — همان قراردادِ
  `next_purchase` و `features/point_in_time`)؛
* عدم‌قطعیت = MAD ÷ فاصله؛ نسبتِ عقب‌افتادگی = گذشته ÷ فاصله (§۱۳.۳)؛
* تعدیلِ اندازه‌ی بسته با مقدارِ آخرین خرید نسبت به مقدارِ معمولِ خودِ مشتری (§۱۳.۴).

**خالص** است (بدون دیتابیس)، روی هر فریمی با ستون‌های نام‌گذاری‌شده کار می‌کند (فریمِ
تحلیل یا فریمِ دفتر کل)، و روی داده‌ی بعد از `as_of` استثنا می‌دهد (نشتِ زمانی).
جفتی که کمتر از `min_gaps` فاصله دارد **غایب** است، نه پرشده با عددِ جامعه.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from mktcore.analysis.cadence_robust import (
    MIN_GAPS_PERSONAL,
    dispersion_ratio,
    evidence_level,
    mad,
    pack_adjusted_gap,
    weighted_median,
)
from mktcore.features.point_in_time import LeakageError

RECENCY_DECAY = 0.75

COLUMNS = (
    "n_purchases", "n_gaps", "gaps_days", "expected_interval_days", "mad_days",
    "uncertainty", "last_purchase", "elapsed_days", "overdue_ratio",
    "last_quantity_milli", "typical_quantity_milli", "pack_adjusted_interval_days",
    "pack_reason_fa", "evidence_level_fa", "confidence_fa", "median_spend",
)


@dataclass(frozen=True)
class PairColumns:
    """نامِ ستون‌های فریمِ ورودی — فریمِ تحلیل و فریمِ دفتر کل نام‌های متفاوتی دارند."""

    customer: str = "customer_id"
    product: str = "product"
    date: str = "date"
    quantity: str | None = None
    pack_size: str | None = None
    revenue: str | None = None
    is_return: str | None = None


# فریمِ تحلیل (خروجیِ clean_frame) — پیش‌فرض
ANALYSIS_COLUMNS = PairColumns(
    customer="customer_id", product="product", date="date", quantity="quantity",
    revenue="revenue",
)
# فریمِ دفتر کل (`features/ledger_frame.load_line_frame`)
LEDGER_COLUMNS = PairColumns(
    customer="customer_id", product="product_id", date="line_date",
    quantity="quantity_milli", pack_size="pack_size_milli", revenue="revenue_rial",
    is_return="is_return",
)


def personal_cadence_table(
    frame: pd.DataFrame,
    *,
    as_of: str,
    columns: PairColumns | None = None,
    min_gaps: int = MIN_GAPS_PERSONAL,
    decay: float = RECENCY_DECAY,
) -> pd.DataFrame:
    """جدولِ آهنگِ شخصی، ایندکس `(customer, product)`، فقط برای جفت‌های واجد.

    * تاریخ‌های خرید به‌ازای هر جفت یکتا می‌شوند (دو خط از یک کالا در یک روز، یک خرید است).
    * برگشت‌ها (اگر ستونش هست) بیرون‌اند؛ فاصله‌ی «برگشت تا خرید» آهنگ نیست.
    * `elapsed_days` از آخرین خرید تا **شاملِ** `as_of` (همان قراردادِ قهرمان).
    """
    columns = columns or ANALYSIS_COLUMNS
    reference = pd.Timestamp(as_of).normalize()
    if frame is None or frame.empty:
        return _empty()
    needed = [columns.customer, columns.product, columns.date]
    missing = [c for c in needed if c not in frame.columns]
    if missing:
        return _empty()

    work = frame[[c for c in frame.columns if c in {
        columns.customer, columns.product, columns.date, columns.quantity,
        columns.pack_size, columns.revenue, columns.is_return,
    }]].copy()
    if columns.is_return and columns.is_return in work.columns:
        work = work[~work[columns.is_return].astype(bool)]
    work = work.rename(columns={
        columns.customer: "_customer", columns.product: "_product", columns.date: "_date",
    })
    # مقایسه روی **روز** است: فریمِ تحلیل ممکن است ساعت داشته باشد و `as_of` تاریخِ روز؛
    # خریدِ ساعت ۱۴ همان روز نشت نیست.
    work["_date"] = pd.to_datetime(work["_date"], errors="coerce").dt.normalize()
    work = work.dropna(subset=["_customer", "_product", "_date"])
    work = work[work["_product"].astype(str).str.strip() != ""]
    if work.empty:
        return _empty()
    if (work["_date"] > reference).any():
        raise LeakageError(
            f"فریم داده‌ای بعد از {as_of} دارد؛ آهنگِ شخصی با نشتِ زمانی ساخته نمی‌شود."
        )

    quantity = columns.quantity if columns.quantity in work.columns else None
    revenue = columns.revenue if columns.revenue in work.columns else None

    rows: list[dict] = []
    for (customer, product), group in work.groupby(["_customer", "_product"], sort=True):
        # یک روز = یک خرید؛ مقدار و مبلغِ همان روز جمع می‌شود
        agg: dict[str, str] = {}
        if quantity:
            agg[quantity] = "sum"
        if revenue:
            agg[revenue] = "sum"
        daily = (
            group.groupby("_date").agg(agg).sort_index() if agg
            else group[["_date"]].drop_duplicates().set_index("_date").sort_index()
        )
        dates = list(daily.index)
        gaps = [float((b - a).days) for a, b in zip(dates, dates[1:], strict=False)]
        gaps = [g for g in gaps if g > 0]
        if len(gaps) < min_gaps:
            continue
        weights = [decay ** k for k in range(len(gaps) - 1, -1, -1)]
        interval = weighted_median(gaps, weights)
        if not interval or interval <= 0:
            continue
        spread = mad(gaps)
        uncertainty = dispersion_ratio(spread, interval)
        last = dates[-1]
        elapsed = float((reference - last).days)

        last_qty = typical_qty = None
        if quantity:
            qty_series = pd.to_numeric(daily[quantity], errors="coerce")
            if qty_series.notna().any():
                last_qty = float(qty_series.iloc[-1]) if pd.notna(qty_series.iloc[-1]) else None
                typical_qty = float(qty_series.iloc[:-1].median()) if len(qty_series) > 1 else None
                if typical_qty is None or not np.isfinite(typical_qty) or typical_qty <= 0:
                    typical_qty = float(qty_series.median())
        # مبنا مقدارِ معمولِ **خودِ** مشتری برای همین کالاست، در همان واحدِ آخرین خرید؛ نسبتِ
        # last/typical از واحد مستقل است، پس اندازه‌ی بسته به `pack_adjusted_gap` داده
        # نمی‌شود (وگرنه فقط یک طرف به «چند بسته» تبدیل می‌شد و فاصله به صفر می‌رسید).
        adjusted, pack_reason = pack_adjusted_gap(
            interval, quantity_milli=last_qty,
            baseline_quantity_milli=typical_qty, pack_size_milli=None,
        )
        expected = float(adjusted if adjusted is not None else interval)
        level, confidence = evidence_level(personal_product_gaps=len(gaps))
        spend = None
        if revenue:
            rev = pd.to_numeric(daily[revenue], errors="coerce").dropna()
            spend = float(rev.median()) if len(rev) else None

        rows.append({
            "customer": customer,
            "product": product,
            "n_purchases": len(dates),
            "n_gaps": len(gaps),
            "gaps_days": [int(g) for g in gaps],
            "expected_interval_days": float(interval),
            "mad_days": None if spread is None else float(spread),
            "uncertainty": None if uncertainty is None else float(uncertainty),
            "last_purchase": last.date().isoformat(),
            "elapsed_days": elapsed,
            "overdue_ratio": elapsed / expected if expected else None,
            "last_quantity_milli": last_qty,
            "typical_quantity_milli": typical_qty,
            "pack_adjusted_interval_days": expected,
            "pack_reason_fa": pack_reason,
            "evidence_level_fa": level,
            "confidence_fa": confidence,
            "median_spend": spend,
        })
    if not rows:
        return _empty()
    return pd.DataFrame(rows).set_index(["customer", "product"])[list(COLUMNS)]


def _empty() -> pd.DataFrame:
    return pd.DataFrame(
        columns=list(COLUMNS),
        index=pd.MultiIndex.from_tuples([], names=["customer", "product"]),
    )


__all__ = [
    "ANALYSIS_COLUMNS", "COLUMNS", "LEDGER_COLUMNS", "RECENCY_DECAY", "PairColumns",
    "personal_cadence_table",
]
