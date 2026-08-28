"""نُه بُعدِ کیفیت داده — §۸.۵.

## چرا این ماژول ساخته شد

تا امروز فقط چهار چیز گزارش می‌شد: پوششِ بها، خطوط بی‌مشتری، خطوط بی‌کالا، و
«موجودی نداریم». پنج بُعدِ دیگر یا اصلاً محاسبه نمی‌شدند یا — بدتر — محاسبه
می‌شدند و **دور ریخته می‌شدند**: `profile_frame` درصدِ خالی‌بودنِ هر ستون را
حساب می‌کند و هیچ‌کس آن را نمی‌بیند.

## قاعده‌ای که همه‌ی این ابعاد رعایت می‌کنند

عددی که مبنایش وجود ندارد، **صفر گزارش نمی‌شود**. `value=None` یعنی «سنجیده
نشد» و دلیلش نوشته می‌شود. صفرِ دروغین بدترین حالت است: مثل یک سنجشِ واقعی
به‌نظر می‌رسد و کاربر بر پایه‌اش تصمیم می‌گیرد.

## «شفافیتِ برگشتی» چه چیزی را می‌سنجد

نه تعداد برگشتی‌ها را — بلکه اینکه **از کجا می‌دانیم برگشتی است**. اگر ستونِ
نوع سند در فایل باشد، برگشتی اعلام‌شده است. اگر نباشد، برگشتی فقط از منفی‌بودنِ
مبلغ حدس زده می‌شود — و آن یک حدس است، نه یک واقعیت. این تفاوت باید دیده شود.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "DIMENSION_LABELS_FA",
    "QualityDimension",
    "build_quality_dimensions",
    "overall_quality",
]

DIMENSION_LABELS_FA = {
    "completeness": "کاملی (خالی‌نبودنِ فیلدهای کلیدی)",
    "validity": "اعتبار (ردیف‌هایی که از پاک‌سازی گذشتند)",
    "uniqueness": "یکتایی (نبودِ ردیف تکراری)",
    "product_match_rate": "نرخ تطبیق کالا",
    "customer_identifier_rate": "نرخ شناساییِ مشتری",
    "cost_coverage": "پوشش بهای تمام‌شده",
    "branch_coverage": "پوشش شعبه",
    "return_clarity": "شفافیتِ برگشتی (اعلام‌شده یا حدس‌زده)",
    "date_range_consistency": "سازگاریِ بازه‌ی تاریخ",
}

# آستانه‌ها. عمداً محافظه‌کارانه‌اند و در متن گفته می‌شوند تا کسی عددِ زردِ
# ۹۵٪ را با «خراب» اشتباه نگیرد.
_GOOD = 0.99
_WARN = 0.90


@dataclass(frozen=True)
class QualityDimension:
    key: str
    label_fa: str
    value: float | None          # None یعنی سنجیده نشد
    severity: str                # ok / warning / blocking / not_measured
    note_fa: str

    def to_dict(self) -> dict:
        return {
            "id": self.key,
            "label_fa": self.label_fa,
            "value": self.value,
            "severity": self.severity,
            "note_fa": self.note_fa,
        }


def _ratio(part: int | None, whole: int | None) -> float | None:
    if not whole:
        return None
    return round(max(0, int(part or 0)) / whole, 4)


def _severity(value: float | None, *, blocking_at_zero: bool = False) -> str:
    if value is None:
        return "not_measured"
    if blocking_at_zero and value == 0:
        return "blocking"
    if value >= _GOOD:
        return "ok"
    if value >= _WARN:
        return "warning"
    return "blocking" if blocking_at_zero else "warning"


def build_quality_dimensions(
    *,
    n_lines: int,
    lines_with_customer: int,
    lines_with_product: int,
    lines_with_cost: int,
    lines_with_date: int,
    lines_in_declared_range: int | None,
    n_orders: int,
    orders_with_branch: int,
    rows_total: int | None,
    rows_clean: int | None,
    rows_duplicate: int | None,
    has_doc_type_column: bool,
    n_returns: int,
) -> list[QualityDimension]:
    """نُه بُعدِ §۸.۵ از شمارش‌هایی که فراخوان از دفتر کل می‌آورد.

    این تابع **خالص** است: هیچ اتصالی به دیتابیس ندارد، پس با عددهای ساختگی
    هم تست‌شدنی است.
    """
    completeness = _ratio(lines_with_date, n_lines)
    validity = _ratio(rows_clean, rows_total)
    uniqueness = (
        None if not rows_total
        else round(1 - (rows_duplicate or 0) / rows_total, 4)
    )
    product_rate = _ratio(lines_with_product, n_lines)
    customer_rate = _ratio(lines_with_customer, n_lines)
    cost = _ratio(lines_with_cost, n_lines)
    branch = _ratio(orders_with_branch, n_orders)
    date_consistency = (
        None if lines_in_declared_range is None else _ratio(lines_in_declared_range, n_lines)
    )

    return [
        QualityDimension(
            "completeness", DIMENSION_LABELS_FA["completeness"], completeness,
            _severity(completeness, blocking_at_zero=True),
            "خطی که تاریخ ندارد در هیچ تحلیل زمانی شرکت نمی‌کند."
            if completeness is None or completeness < _GOOD else
            "همه‌ی خطوط تاریخ دارند.",
        ),
        QualityDimension(
            "validity", DIMENSION_LABELS_FA["validity"], validity,
            _severity(validity),
            "شمارِ ردیف‌های خام ثبت نشده است، پس نسبتِ اعتبار سنجیده نشد."
            if validity is None else
            f"از هر ۱۰۰ ردیفِ فایل، {round(validity * 100)} ردیف وارد دفتر کل شد؛ "
            "بقیه در پاک‌سازی کنار رفتند.",
        ),
        QualityDimension(
            "uniqueness", DIMENSION_LABELS_FA["uniqueness"], uniqueness,
            _severity(uniqueness),
            "شمارِ ردیف‌های خام ثبت نشده است، پس یکتایی سنجیده نشد."
            if uniqueness is None else
            "ردیف تکراری پیدا نشد." if uniqueness >= _GOOD else
            f"{round((1 - uniqueness) * 100)}٪ از ردیف‌های فایل تکراری بودند و "
            "یک‌بار شمرده شدند.",
        ),
        QualityDimension(
            "product_match_rate", DIMENSION_LABELS_FA["product_match_rate"], product_rate,
            _severity(product_rate),
            "خطوطِ بدون کالا در تحلیل سبد و پیشنهاد کالا شرکت نمی‌کنند.",
        ),
        QualityDimension(
            "customer_identifier_rate",
            DIMENSION_LABELS_FA["customer_identifier_rate"], customer_rate,
            _severity(customer_rate),
            "خطوطِ بدون مشتری در پرونده‌ی مشتری و پیوند بین بارگذاری‌ها دیده نمی‌شوند.",
        ),
        QualityDimension(
            "cost_coverage", DIMENSION_LABELS_FA["cost_coverage"], cost,
            "blocking" if (cost or 0) == 0 else _severity(cost),
            "بهای تمام‌شده وجود ندارد؛ سود ناخالص، حاشیه و سود افزوده محاسبه "
            "نمی‌شوند و همه‌ی اعداد درآمدی‌اند."
            if (cost or 0) == 0 else
            "سود ناخالص روی خطوطِ دارای بها محاسبه می‌شود.",
        ),
        QualityDimension(
            "branch_coverage", DIMENSION_LABELS_FA["branch_coverage"], branch,
            "not_measured" if branch is None else
            "known_limitation" if branch == 0 else _severity(branch),
            "سفارشی ثبت نشده است." if branch is None else
            "ستون شعبه در فایل نبود؛ «شعبه‌ی محتملِ مشتری» تعیین نمی‌شود."
            if branch == 0 else
            f"{round(branch * 100)}٪ سفارش‌ها شعبه دارند.",
        ),
        QualityDimension(
            "return_clarity", DIMENSION_LABELS_FA["return_clarity"],
            1.0 if has_doc_type_column else 0.0,
            "ok" if has_doc_type_column else "warning",
            "نوع سند در فایل هست، پس برگشتی‌ها **اعلام‌شده**اند."
            if has_doc_type_column else
            f"ستون نوع سند در فایل نبود؛ {n_returns} ردیف فقط به‌خاطر منفی‌بودنِ "
            "مبلغ «برگشتی» شمرده شده‌اند — این حدس است، نه اعلام.",
        ),
        QualityDimension(
            "date_range_consistency",
            DIMENSION_LABELS_FA["date_range_consistency"], date_consistency,
            _severity(date_consistency),
            "بازه‌ی تاریخِ اعلام‌شده‌ی بارگذاری ثبت نشده است، پس سازگاری سنجیده نشد."
            if date_consistency is None else
            "همه‌ی خطوط داخل بازه‌ی تاریخِ اعلام‌شده‌ی همان بارگذاری‌اند."
            if date_consistency >= _GOOD else
            "بخشی از خطوط بیرون از بازه‌ی تاریخِ اعلام‌شده‌ی بارگذاری‌اند؛ "
            "احتمال اشتباهِ تبدیل تاریخ.",
        ),
    ]


def overall_quality(dimensions: list[QualityDimension]) -> dict:
    """خلاصه‌ی صادقانه: چند بُعد سنجیده شد و چندتا مشکل دارند."""
    measured = [d for d in dimensions if d.value is not None]
    blocking = [d for d in dimensions if d.severity == "blocking"]
    warning = [d for d in dimensions if d.severity == "warning"]
    return {
        "dimensions_total": len(dimensions),
        "dimensions_measured": len(measured),
        "blocking": [d.key for d in blocking],
        "warning": [d.key for d in warning],
        # میانگین **فقط روی سنجیده‌شده‌ها**؛ حساب‌کردنِ سنجیده‌نشده به‌عنوان صفر
        # یعنی جریمه‌کردنِ کاربر برای ستونی که اصلاً نداشته.
        "score": (
            round(sum(d.value for d in measured) / len(measured), 4) if measured else None
        ),
        "note_fa": (
            f"{len(measured)} بُعد از {len(dimensions)} بُعدِ §۸.۵ سنجیده شد. "
            + (
                f"{len(blocking)} مورد جدی و {len(warning)} مورد هشدار دارد."
                if blocking or warning else "هیچ مشکل جدی‌ای پیدا نشد."
            )
        ),
    }
