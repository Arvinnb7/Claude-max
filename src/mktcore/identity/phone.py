"""نرمال‌سازی شماره‌ی تلفن ایرانی به شکل قطعی و یکتا.

چرا لازم است؟ چون همان یک مشتری در فایل‌های مختلف این‌طور نوشته می‌شود:
`09123456789`، `+989123456789`، `۰۹۱۲-۳۴۵-۶۷۸۹`، `9123456789`،
`0912 345 67 89`، `0098912...`. بدون نرمال‌سازی، هرکدام یک «مشتری» جدا می‌شود؛
شمارش مشتری غلط می‌شود و پیامک به یک نفر چند بار می‌رود.

خروجی همیشه **E.164** است (`+989123456789`) — یکتا، مرتب‌شدنی، و همان چیزی که
پنل‌های پیامکی می‌پذیرند.

محافظه‌کاری عامدانه: هر چیزی که مطمئن نیستیم شماره‌ی معتبر ایرانی است → `None`.
یک شماره‌ی حل‌نشده فقط یعنی «وصل نشد»؛ یک شماره‌ی غلطِ حل‌شده یعنی پیامک به
آدم اشتباه.
"""

from __future__ import annotations

import re

from mktcore.locale_fa import normalize_digits

# فقط رقم‌ها و علامت + باقی می‌مانند؛ بقیه (فاصله، خط تیره، پرانتز، نقطه،
# نیم‌فاصله، کاراکترهای جهت‌دهی راست‌به‌چپ) حذف می‌شوند.
_KEEP = re.compile(r"[^\d+]")
_ALL_DIGITS = re.compile(r"^\d+$")

IRAN_COUNTRY_CODE = "98"

# اپراتورهای موبایل ایران: بعد از ۰۹ یک رقم و سپس ۸ رقم → مجموعاً ۱۰ رقم ملی.
_MOBILE_NATIONAL = re.compile(r"^9\d{9}$")
# تلفن ثابت: کد استان (۲ یا ۳ رقم، شروع با ۱..۹) + شماره → ۱۰ رقم ملی
_LANDLINE_NATIONAL = re.compile(r"^[1-8]\d{9}$")

# کدهای استانی که در ایران معتبرند (پیشوند دو رقمی بعد از صفر).
# فهرست بسته است تا رشته‌ی عددیِ بی‌ربط (مثل شناسه‌ی فاکتور ۱۰ رقمی) به‌اشتباه
# «تلفن ثابت» شناخته نشود.
_AREA_CODES = frozenset({
    "11", "13", "17", "21", "23", "24", "25", "26", "28", "31", "34", "35",
    "38", "41", "44", "45", "51", "54", "56", "58", "61", "66", "71", "74",
    "76", "77", "81", "83", "84", "86", "87",
})


def _digits_only(raw: object) -> str:
    """رشته‌ی ورودی → فقط ارقام انگلیسی (با حفظ + ابتدایی به‌صورت جدا)."""
    if raw is None:
        return ""
    text = normalize_digits(str(raw)).strip()
    # پرانتزِ کد استان و پسوندهای داخلی («داخلی ۲۳») حذف می‌شوند
    text = text.split("داخلی")[0].split("ext")[0]
    return _KEEP.sub("", text)


def _to_national(cleaned: str) -> str | None:
    """حذف پیشوند بین‌المللی/صفرِ ملی → ۱۰ رقمِ ملی، یا None اگر بی‌معنا بود."""
    if not cleaned:
        return None
    if cleaned.startswith("+"):
        digits = cleaned[1:]
        if not digits.startswith(IRAN_COUNTRY_CODE):
            return None  # شماره‌ی خارجی — این ماژول ادعای پوشش آن را ندارد
        digits = digits[len(IRAN_COUNTRY_CODE):]
    else:
        digits = cleaned
        if digits.startswith("00" + IRAN_COUNTRY_CODE):
            digits = digits[2 + len(IRAN_COUNTRY_CODE):]
        elif digits.startswith("0"):
            digits = digits[1:]
        elif len(digits) == 12 and digits.startswith(IRAN_COUNTRY_CODE):
            # «989123456789» بدون + و بدون ۰۰
            digits = digits[len(IRAN_COUNTRY_CODE):]
    if not _ALL_DIGITS.match(digits):
        return None
    return digits


def normalize_phone(raw: object) -> str | None:
    """شماره‌ی خام → E.164 ایرانی (`+98...`)، یا `None` اگر معتبر نبود.

    >>> normalize_phone("0912 345 6789")
    '+989123456789'
    >>> normalize_phone("۰۹۱۲۳۴۵۶۷۸۹")
    '+989123456789'
    >>> normalize_phone("+98 912 345 6789")
    '+989123456789'
    >>> normalize_phone("021-88776655")
    '+982188776655'
    >>> normalize_phone("12345") is None
    True
    """
    national = _to_national(_digits_only(raw))
    if national is None or len(national) != 10:
        return None
    if _MOBILE_NATIONAL.match(national):
        return f"+{IRAN_COUNTRY_CODE}{national}"
    if _LANDLINE_NATIONAL.match(national) and national[:2] in _AREA_CODES:
        return f"+{IRAN_COUNTRY_CODE}{national}"
    return None


def is_mobile(phone: object) -> bool:
    """آیا شماره موبایل ایرانی است؟ (فقط موبایل پیامک‌پذیر است)"""
    normalized = normalize_phone(phone)
    return bool(normalized and normalized.startswith(f"+{IRAN_COUNTRY_CODE}9"))


def phone_identity_key(raw: object) -> str | None:
    """کلید هویتِ قابل‌ذخیره در `customer_keys` — همان E.164 نرمال‌شده."""
    return normalize_phone(raw)


def mask_phone(raw: object, *, keep_tail: int = 4) -> str:
    """نمایش ماسک‌شده برای لاگ و UI: `+98912***6789`.

    شماره‌ی مشتری داده‌ی شخصی است؛ لاگ کامل آن در فایل لاگِ سرور می‌ماند و
    نشتِ بی‌دلیل است. برای همین همه‌ی مسیرهای تشخیصی این تابع را صدا می‌زنند.
    """
    normalized = normalize_phone(raw)
    if normalized is None:
        digits = _digits_only(raw)
        if not digits:
            return "—"
        tail = digits[-keep_tail:] if len(digits) > keep_tail else digits
        return "*" * max(0, len(digits) - len(tail)) + tail
    head = normalized[: len(f"+{IRAN_COUNTRY_CODE}") + 3]
    tail = normalized[-keep_tail:]
    hidden = len(normalized) - len(head) - len(tail)
    return f"{head}{'*' * max(1, hidden)}{tail}"


__all__ = [
    "IRAN_COUNTRY_CODE",
    "is_mobile",
    "mask_phone",
    "normalize_phone",
    "phone_identity_key",
]
