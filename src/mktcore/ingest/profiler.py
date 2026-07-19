"""پروفایل کیفیت داده: درصد گمشدگی، بازه‌ی زمانی، شکاف‌ها و هشدارها."""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from .schema import ColumnRole, standard_column

_DATE = standard_column(ColumnRole.DATE)
_REVENUE = standard_column(ColumnRole.REVENUE)


@dataclass
class DataQualityReport:
    """گزارش کیفیت داده برای نمایش در UI و ارسال فشرده به مدل."""

    n_rows: int = 0
    n_cols: int = 0
    date_min: str | None = None
    date_max: str | None = None
    span_days: int | None = None
    missing_pct: dict[str, float] = field(default_factory=dict)
    dropped_invalid: int = 0
    dropped_duplicates: int = 0
    warnings: list[str] = field(default_factory=list)

    def to_compact(self) -> dict:
        """نمایش فشرده برای ارسال به مدل (بدون داده‌ی خام)."""
        return {
            "تعداد_ردیف": self.n_rows,
            "بازه_تاریخ": [self.date_min, self.date_max],
            "طول_دوره_روز": self.span_days,
            "هشدارها": self.warnings,
        }


def profile_frame(df: pd.DataFrame) -> DataQualityReport:
    """تولید گزارش کیفیت از یک DataFrame پاک‌شده."""
    rep = DataQualityReport(n_rows=len(df), n_cols=df.shape[1])
    rep.dropped_invalid = int(df.attrs.get("dropped_invalid_rows", 0))
    rep.dropped_duplicates = int(df.attrs.get("dropped_duplicate_rows", 0))

    # گمشدگی
    if len(df) > 0:
        miss = (df.isna().mean() * 100).round(1)
        rep.missing_pct = {str(k): float(v) for k, v in miss.items() if v > 0}

    # بازه‌ی زمانی و شکاف
    if _DATE in df.columns and df[_DATE].notna().any():
        dmin, dmax = df[_DATE].min(), df[_DATE].max()
        rep.date_min = dmin.date().isoformat()
        rep.date_max = dmax.date().isoformat()
        rep.span_days = int((dmax - dmin).days)
        if rep.span_days is not None and rep.span_days < 60:
            rep.warnings.append("بازه‌ی زمانی داده کوتاه است (کمتر از ۶۰ روز)؛ پیش‌بینی و تحلیل فصلی کم‌دقت‌تر خواهد بود.")

    # حجم کم
    if rep.n_rows < 100:
        rep.warnings.append("تعداد رکورد کم است؛ نتایج آماری با احتیاط تفسیر شوند.")

    # نبود ستون‌های مفید
    if _REVENUE in df.columns and df[_REVENUE].sum() == 0:
        rep.warnings.append("مجموع درآمد صفر است؛ نگاشت ستون درآمد را بررسی کنید.")

    if df.attrs.get("sign_flipped"):
        rep.warnings.append(
            "ستون‌های مبلغی با «قرارداد علامت منفی» (خروجی حسابداری) شناسایی و علامت‌شان "
            "اصلاح شد تا فروش مثبت محاسبه شود."
        )

    if rep.dropped_invalid > 0:
        rep.warnings.append(f"{rep.dropped_invalid} ردیف نامعتبر (بدون تاریخ/درآمد) حذف شد.")
    if rep.dropped_duplicates > 0:
        rep.warnings.append(f"{rep.dropped_duplicates} ردیف تکراری حذف شد.")

    n_returns = df.attrs.get("n_returns", 0)
    if n_returns:
        total = df.attrs.get("returns_total", 0.0)
        rep.warnings.append(
            f"{n_returns} ردیف برگشت از فروش شناسایی شد (مبلغ {total:,.0f})؛ "
            "در محاسبه‌ی فروش خالص لحاظ شد."
        )
    if df.attrs.get("ambiguous_sign"):
        rep.warnings.append(
            "سهم ردیف‌های با مبلغ منفی غیرعادی است (بین ۴۰٪ تا ۶۰٪)؛ قرارداد علامت "
            "مبالغ فایل را بررسی کنید — تفکیک فروش/برگشت ممکن است نادرست باشد."
        )

    validation = df.attrs.get("validation") or {}
    matrix = validation.get("doc_sign_matrix")
    if matrix:
        if matrix["sale_rows_marked_return"] > 0:
            rep.warnings.append(
                f"{matrix['sale_rows_marked_return']} ردیف با نوع سند «برگشت» مبلغ مثبت دارند؛ "
                "تفکیک برگشتی بر اساس علامت منفی است — علامت مبالغ فایل را بررسی کنید."
            )
        if matrix["return_rows_marked_sale"] > 0:
            rep.warnings.append(
                f"{matrix['return_rows_marked_sale']} ردیف با نوع سند «فروش» مبلغ منفی دارند؛ "
                "قرارداد علامت مبالغ را بررسی کنید."
            )
    recon = validation.get("amount_reconciliation")
    if recon and recon["violating_share"] > 0.05:
        rep.warnings.append(
            f"در {recon['violating_share']:.0%} ردیف‌ها مبلغ ناخالص منهای تخفیف با مبلغ "
            "قابل پرداخت هم‌خوانی ندارد؛ نگاشت ستون‌های مبلغ/تخفیف را بررسی کنید."
        )

    return rep


__all__ = ["DataQualityReport", "profile_frame"]
