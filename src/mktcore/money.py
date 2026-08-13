"""مرز پول: تبدیل بی‌ابهام بین «واحد نمایش اعشاری» و «ریالِ عدد صحیح».

چرا این ماژول لازم است؟ چون دو دنیای متفاوت داریم و هر دو درست‌اند:

* **تحلیل** با `float64` روی pandas کار می‌کند — برای میانگین، رگرسیون و
  پیش‌بینی درست است و از قبل تست‌شده.
* **دفتر کل** باید عدد صحیح ریال باشد — تا جمع میلیون‌ها خط بی‌خطا باشد و آشتی
  اثبات‌پذیر بماند (جمع float غیرشرکت‌پذیر است: ترتیب جمع، نتیجه را عوض می‌کند).

پس تبدیل **فقط در همین مرز** و **یک بار** انجام می‌شود. قواعد سختِ این مرز:

* گرد کردن با `round-half-even` (بانکی) → سوگیریِ سیستماتیک رو به بالا ندارد.
* `None`/`NaN`/`±inf` → `None`. **هرگز صفر**، چون صفر یعنی «مبلغ صفر بود» و
  این با «نمی‌دانیم» یکی نیست؛ قاطی‌کردنشان جمع‌ها را بی‌صدا غلط می‌کند.
"""

from __future__ import annotations

import math
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation

from .ingest.currency import rial_per_unit
from .locale_fa import format_number_fa

# نسبت مقیاس تعداد. تعداد می‌تواند کسری باشد (۱٫۵ کیلو)، پس ×۱۰۰۰ ذخیره می‌شود.
QUANTITY_SCALE = 1000
# نسبت مقیاس basis point — ۱۰۰٪ = ۱۰۰۰۰
BP_SCALE = 10_000


def _finite(value: object) -> float | None:
    """عدد متناهی یا None. رشته‌ی عددی هم پذیرفته می‌شود (ستون‌های مخلوط)."""
    if value is None:
        return None
    try:
        num = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if math.isnan(num) or math.isinf(num):
        return None
    return num


def _round_half_even(num: float) -> int:
    """گرد کردن بانکی با Decimal (نه `round` پایتون روی float).

    `round(2.675, 2)` روی float نتیجه‌ی غیرمنتظره می‌دهد چون بازنمایی دودویی
    دقیق نیست؛ Decimal از رشته‌ی repr می‌سازد و همان چیزی را گرد می‌کند که
    کاربر می‌بیند.
    """
    try:
        return int(Decimal(repr(num)).quantize(Decimal(1), rounding=ROUND_HALF_EVEN))
    except (InvalidOperation, ValueError, OverflowError):
        return int(num)


def to_rial_int(value: object, display_currency: str) -> int | None:
    """مبلغِ واحدِ نمایش → ریالِ عدد صحیح. نامعلوم → `None` (نه صفر).

    >>> to_rial_int(1250.0, "تومان")
    12500
    >>> to_rial_int(1250.0, "ریال")
    1250
    >>> to_rial_int(float("nan"), "تومان") is None
    True
    """
    num = _finite(value)
    if num is None:
        return None
    return _round_half_even(num * rial_per_unit(display_currency))


def rial_to_display(rial: int | None, display_currency: str) -> float | None:
    """ریالِ عدد صحیح → مبلغِ واحدِ نمایش (برای رندر و مقایسه با تحلیل)."""
    if rial is None:
        return None
    return float(rial) / rial_per_unit(display_currency)


def to_quantity_milli(value: object) -> int | None:
    """تعداد → عدد صحیح ×۱۰۰۰. نامعلوم → `None`."""
    num = _finite(value)
    if num is None:
        return None
    return _round_half_even(num * QUANTITY_SCALE)


def quantity_from_milli(milli: int | None) -> float | None:
    if milli is None:
        return None
    return milli / QUANTITY_SCALE


def to_basis_points(ratio: object) -> int | None:
    """نسبت (۰..۱) → basis point صحیح. نامعلوم → `None`."""
    num = _finite(ratio)
    if num is None:
        return None
    return _round_half_even(num * BP_SCALE)


def basis_points_to_ratio(bp: int | None) -> float | None:
    if bp is None:
        return None
    return bp / BP_SCALE


def format_rial_fa(rial: int | None, display_currency: str = "تومان") -> str:
    """متن فارسیِ مبلغ در واحد نمایش، با جداکننده‌ی هزارگان و نام واحد.

    این تابع تنها راهِ مجازِ نمایش مبلغ در پاسخ API است. علتش یک باگ واقعیِ
    گزارش‌شده است: فرانت `compact()` را روی عدد ریالی می‌زد و مبلغ ده برابر
    نمایش داده می‌شد. با فرستادنِ متنِ آماده، آن اشتباه غیرممکن می‌شود.
    """
    if rial is None:
        return "—"
    display = rial_to_display(rial, display_currency)
    if display is None:  # pragma: no cover - rial_to_display فقط با None برمی‌گردد
        return "—"
    decimals = 0 if float(display).is_integer() else 1
    return f"{format_number_fa(display, decimals)} {display_currency}"


def money_payload(rial: int | None, display_currency: str = "تومان") -> dict:
    """شکل استانداردِ پول در پاسخ‌های `/api/v1` — همیشه صحیح + متنِ آماده.

    هرگز float در پاسخ نمی‌رود: مصرف‌کننده یا عدد صحیح ریال را می‌خواهد (محاسبه)
    یا متن را (نمایش)؛ float فقط راهِ سوم برای خطای گردکردن است.
    """
    return {
        "rial": rial,
        "display_text": format_rial_fa(rial, display_currency),
        "display_currency": display_currency,
    }


__all__ = [
    "BP_SCALE",
    "QUANTITY_SCALE",
    "basis_points_to_ratio",
    "format_rial_fa",
    "money_payload",
    "quantity_from_milli",
    "rial_to_display",
    "to_basis_points",
    "to_quantity_milli",
    "to_rial_int",
]
