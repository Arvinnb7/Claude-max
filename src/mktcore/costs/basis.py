"""انتخابِ بهای **زمانِ معامله** — تابع خالص، بدون دیتابیس.

## چرا این کار بدیهی نیست

ساده‌ترین کار این بود که آخرین بهای هر کالا را در یک ستون بگذاریم و همه‌ی سودها
را با آن حساب کنیم. §۳.۴ سند دقیقاً همین را ممنوع می‌کند:

> Historical cost must be based on the best available cost basis at transaction
> time, not blindly on the latest supplier price.

دلیلش در اقتصادِ تورمی آشکار است: کالایی که پارسال ۱۰۰ خریده و ۱۵۰ فروخته شده،
با بهای امروزِ ۲۰۰ «زیان‌ده» به‌نظر می‌رسد. آن عدد نه‌فقط غلط است، بلکه تصمیمِ
غلط می‌سازد — سیستم کالایی را کنار می‌گذارد که واقعاً سودده بوده.

## سه سطح اطمینان

| سطح | یعنی |
|---|---|
| `history_exact` | بازه‌ی اثرِ یک ردیف، تاریخ معامله را **در بر می‌گیرد** |
| `history_imputed` | فقط بهای **بعد از** معامله موجود است و به عقب تعمیم داده شده |
| `None` | هیچ بهایی برای این کالا نیست ⇒ بها و سود هر دو `NULL` می‌مانند |

سطح دوم عمداً برچسبِ جدا دارد، نه اینکه بی‌صدا مثل سطح اول رفتار کند — §۳.۴:
«Any imputed cost must be identified as imputed and assigned a confidence
level.»
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass

CONFIDENCE_FROM_FILE = "from_file"
CONFIDENCE_HISTORY_EXACT = "history_exact"
CONFIDENCE_HISTORY_IMPUTED = "history_imputed"

CONFIDENCE_LABELS_FA = {
    CONFIDENCE_FROM_FILE: "بها در خودِ فایل فروش بود",
    CONFIDENCE_HISTORY_EXACT: "بهای همان بازه‌ی زمانی",
    CONFIDENCE_HISTORY_IMPUTED: "بهای دوره‌ی بعد، تعمیم‌یافته به عقب (تخمینی)",
}


@dataclass(frozen=True)
class CostPoint:
    """یک بهای واحد که از تاریخِ مشخصی معتبر شده است."""

    effective_from: str      # ISO میلادی
    unit_cost_rial: int


@dataclass(frozen=True)
class CostLookup:
    """بهای یک کالا در طول زمان، آماده‌ی پرس‌وجوی سریع.

    نقاط **مرتب** نگه داشته می‌شوند تا جستجوی هر خط `O(log n)` باشد؛ با ده‌ها
    هزار خطِ فروش، جستجوی خطی در هر خط هزینه‌ی واقعی دارد.
    """

    points: tuple[CostPoint, ...]

    @classmethod
    def from_points(cls, points: list[CostPoint]) -> CostLookup:
        return cls(points=tuple(sorted(points, key=lambda p: p.effective_from)))

    def at(self, line_date: str) -> tuple[int, str] | None:
        """(بهای واحد، سطح اطمینان) برای این تاریخ — یا `None` اگر بهایی نیست."""
        if not self.points:
            return None
        dates = [p.effective_from for p in self.points]
        index = bisect_right(dates, line_date) - 1
        if index >= 0:
            return self.points[index].unit_cost_rial, CONFIDENCE_HISTORY_EXACT
        # همه‌ی بهاها **بعد از** این معامله‌اند: نزدیک‌ترینِ بعدی تعمیم داده
        # می‌شود، ولی صریحاً «تخمینی» برچسب می‌خورد.
        return self.points[0].unit_cost_rial, CONFIDENCE_HISTORY_IMPUTED


def line_cost_rial(
    lookup: CostLookup | None,
    line_date: str,
    quantity_milli: int | None,
) -> tuple[int, str] | None:
    """بهای **کل خط** = بهای واحد × مقدار.

    مقدار به‌صورت هزارم ذخیره می‌شود (`quantity_milli`). نبودِ مقدار یعنی یک
    واحد فرض می‌شود — همان قاعده‌ای که بقیه‌ی سیستم دارد.
    """
    if lookup is None:
        return None
    found = lookup.at(line_date)
    if found is None:
        return None
    unit_cost, confidence = found
    units = (quantity_milli / 1000.0) if quantity_milli is not None else 1.0
    return round(unit_cost * units), confidence


def gross_profit_rial(revenue_rial: int | None, cost_rial: int | None) -> int | None:
    """سود ناخالص = درآمد − بها.

    **بها `None` ⇒ سود `None`.** هرگز صفر: صفر یعنی «سودی نداشت» در حالی که
    واقعیت «نمی‌دانیم» است، و آن دو در تصمیم‌گیری زمین تا آسمان فرق دارند.

    خطِ برگشتی هم درست کار می‌کند: درآمدش منفی است و بهایش هم منفی می‌شود، پس
    سودِ منفیِ همان خط، سودِ خطِ اصلی را خنثی می‌کند.
    """
    if revenue_rial is None or cost_rial is None:
        return None
    return int(revenue_rial) - int(cost_rial)


def coverage_ratio(total_lines: int, lines_with_cost: int) -> float:
    """نسبت خطوطی که بها دارند. مبنای تصمیمِ «محاسبه کنیم یا نه»."""
    if total_lines <= 0:
        return 0.0
    return lines_with_cost / total_lines


def is_computable(coverage: float) -> bool:
    """آیا سودِ **جمعی** قابل گزارش است؟

    فقط با پوشش کامل. جمعِ سود روی داده‌ی ناقص، عددی می‌دهد که از واقعیت کمتر
    است و هیچ نشانه‌ای هم همراه ندارد — همان چیزی که `api/v1.py` درباره‌اش
    می‌گوید «عدد ناقص بدتر از نبودِ عدد است».
    """
    return coverage >= 0.999


def coverage_note_fa(coverage: float) -> str:
    percent = round(coverage * 100, 1)
    if is_computable(coverage):
        return "بهای تمام‌شده برای همه‌ی خطوط موجود است؛ سود ناخالص محاسبه شد."
    if coverage <= 0:
        return "هیچ بهای تمام‌شده‌ای ثبت نشده است؛ سود ناخالص محاسبه نشد."
    return (
        f"بهای تمام‌شده فقط برای {percent}٪ خطوط موجود است. سود ناخالص محاسبه "
        "نشد، چون جمعِ ناقص کمتر از واقع نشان می‌دهد بدون اینکه معلوم باشد."
    )


__all__ = [
    "CONFIDENCE_FROM_FILE",
    "CONFIDENCE_HISTORY_EXACT",
    "CONFIDENCE_HISTORY_IMPUTED",
    "CONFIDENCE_LABELS_FA",
    "CostLookup",
    "CostPoint",
    "coverage_note_fa",
    "coverage_ratio",
    "gross_profit_rial",
    "is_computable",
    "line_cost_rial",
]
