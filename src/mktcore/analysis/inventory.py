"""پیشنهاد تأمین کالا: افزایش، کاهش، حفظ یا قطع تأمین بر اساس داده.

ترکیبی از سرعت فروش (velocity)، روند (رشد/افت)، سهم درآمد و حاشیه‌ی سود برای هر
محصول، یک توصیه‌ی تأمین تولید می‌کند.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from ..ingest.schema import ColumnRole, standard_column

_DATE = standard_column(ColumnRole.DATE)
_REVENUE = standard_column(ColumnRole.REVENUE)
_QUANTITY = standard_column(ColumnRole.QUANTITY)
_PRODUCT = standard_column(ColumnRole.PRODUCT)
_COST = standard_column(ColumnRole.COST)

# سیگنال‌های فروش‌محور؛ بدون داده‌ی موجودی «توصیه‌ی عملیاتی قطعی» نیستند
SUPPLY_CAVEAT = ("بر اساس داده‌ی فروش (بدون موجودی انبار، lead time و بهای خرید)؛ "
                 "پیش از اقدام عملیاتی، موجودی و تأمین بررسی شود.")

# توصیه‌ها
RESTOCK_MORE = "نامزد افزایش تأمین"
RESTOCK_KEEP = "حفظ تأمین"
RESTOCK_LESS = "نامزد کاهش تأمین"
RESTOCK_STOP = "نامزد بررسی برای حذف"


@dataclass
class InventoryAdvice:
    product: str
    recommendation: str
    recent_units_per_week: float
    growth: float | None
    revenue_share: float
    margin: float | None
    reason: str


@dataclass
class InventoryAnalysis:
    items: list[InventoryAdvice] = field(default_factory=list)

    @property
    def available(self) -> bool:
        return bool(self.items)

    def compact(self) -> list[dict]:
        return [
            {"محصول": i.product, "توصیه": i.recommendation,
             "رشد": None if i.growth is None else round(i.growth * 100, 1),
             "سهم_درآمد": round(i.revenue_share * 100, 1),
             "حاشیه": None if i.margin is None else round(i.margin * 100, 1),
             "دلیل": i.reason}
            for i in self.items
        ]


def analyze_inventory(df: pd.DataFrame, *, recent_weeks: int = 8) -> InventoryAnalysis:
    """تولید توصیه‌ی تأمین برای هر محصول."""
    res = InventoryAnalysis()
    if _PRODUCT not in df.columns or df.empty:
        return res

    qty_col = _QUANTITY if _QUANTITY in df.columns else None
    data_max = df[_DATE].max()
    recent_cut = data_max - pd.Timedelta(weeks=recent_weeks)
    recent = df[df[_DATE] > recent_cut]

    grand_total = df[_REVENUE].sum()
    mid = df[_DATE].min() + (df[_DATE].max() - df[_DATE].min()) / 2
    first = df[df[_DATE] <= mid].groupby(_PRODUCT)[_REVENUE].sum()
    second = df[df[_DATE] > mid].groupby(_PRODUCT)[_REVENUE].sum()

    for prod, g in df.groupby(_PRODUCT):
        revenue = float(g[_REVENUE].sum())
        share = revenue / grand_total if grand_total else 0.0
        f, s = float(first.get(prod, 0)), float(second.get(prod, 0))
        growth = (s - f) / f if f > 0 else None

        rec_g = recent[recent[_PRODUCT] == prod]
        units = float(rec_g[qty_col].sum()) if qty_col else float(len(rec_g))
        upw = units / recent_weeks

        margin = None
        if _COST in g.columns and g[_COST].notna().any() and revenue > 0:
            margin = (revenue - float(g[_COST].sum())) / revenue

        # منطق توصیه
        if upw < 0.5 and (growth is None or growth < -0.4):
            rec, reason = RESTOCK_STOP, "فروش بسیار کم و روند نزولی شدید؛ کاندیدای حذف از سبد."
        elif growth is not None and growth > 0.25 and share > 0.05:
            rec, reason = RESTOCK_MORE, "روند صعودی و سهم درآمد قابل‌توجه؛ ریسک کمبود موجودی."
        elif growth is not None and growth < -0.2:
            rec, reason = RESTOCK_LESS, "روند نزولی؛ کاهش تأمین برای جلوگیری از انباشت موجودی."
        elif margin is not None and margin > 0.45 and (growth is None or growth >= 0):
            rec, reason = RESTOCK_MORE, "حاشیه‌ی سود بالا و فروش پایدار؛ تقویت موجودی توجیه‌پذیر است."
        else:
            rec, reason = RESTOCK_KEEP, "فروش و روند متعادل؛ سطح تأمین فعلی حفظ شود."

        res.items.append(InventoryAdvice(
            product=str(prod), recommendation=rec, recent_units_per_week=upw,
            growth=growth, revenue_share=share, margin=margin, reason=reason,
        ))

    res.items.sort(key=lambda i: -i.revenue_share)
    return res


__all__ = ["InventoryAnalysis", "InventoryAdvice", "analyze_inventory",
           "RESTOCK_MORE", "RESTOCK_KEEP", "RESTOCK_LESS", "RESTOCK_STOP"]
