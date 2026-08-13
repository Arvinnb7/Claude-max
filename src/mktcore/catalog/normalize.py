"""نرمال‌سازی نام محصول و استخراج اندازه‌ی بسته — بدون هیچ فرضِ دامنه‌ای.

سه کارِ مشخص:

1. `normalize_product_name` — یک نامِ قطعی برای تطبیق. تفاوت‌های نوشتاری فارسی
   (ي/ك عربی، نیم‌فاصله، ارقام فارسی، فاصله‌ی چندتایی، کاراکترهای جهت‌دهی) از
   یک محصولِ واحد چند محصول می‌سازند و تحلیل سبد و پیشنهاد را رقیق می‌کنند.
2. `parse_pack_size` — استخراج «۱٫۵ کیلوگرم» / «500ml» / «۱۲ عددی» از خودِ نام.
3. `product_family_key` — نامِ بدونِ اندازه، تا «همان کالا در بسته‌بندی دیگر»
   یک خانواده حساب شود (در پیشنهاد نباید به‌عنوان «کالای جدید» عرضه شود).

هیچ‌کدام واژه‌نامه‌ی دامنه‌ای ندارند: همه از الگوی عددی+واحد کار می‌کنند که در
هر صنعتی یکسان است.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from mktcore.locale_fa import normalize_digits

# کاراکترهای نامرئی که از کپی‌پیست اکسل/وب می‌آیند و تطبیق را بی‌صدا می‌شکنند.
_INVISIBLE = dict.fromkeys(
    [0x200B, 0x200C, 0x200D, 0x200E, 0x200F, 0x202A, 0x202B, 0x202C, 0x202D,
     0x202E, 0x2066, 0x2067, 0x2068, 0x2069, 0xFEFF],
    " ",
)

# یکسان‌سازی حروف عربی/فارسی که در صفحه‌کلیدهای مختلف قاطی می‌شوند.
_LETTER_FOLD = str.maketrans({
    "ي": "ی", "ى": "ی", "ﻯ": "ی", "ﻰ": "ی",
    "ك": "ک", "ﻙ": "ک", "ﻚ": "ک",
    "ة": "ه", "ۀ": "ه",
    "أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا",
    "ؤ": "و", "ئ": "ی",
})

# اعرابِ اختیاری — در نام کالا معنا ندارد ولی تطبیق را می‌شکند.
_DIACRITICS = re.compile(r"[ً-ْٰـ]")

# ممیزِ اعشاری در نگارش‌های مختلف، فقط وقتی بین دو رقم باشد. بدون این قید،
# «۱٫۵ کیلو» به «۱ ۵ کیلو» تبدیل می‌شد و اندازه‌ی بسته پنج برابر خوانده می‌شد.
_DECIMAL_SEP = re.compile(r"(?<=\d)\s*[.,٫،]\s*(?=\d)")
# جداکننده‌ی هزارگان بین ارقام («۱,۵۰۰ گرم») حذف می‌شود، نه تبدیل به ممیز.
_THOUSANDS_SEP = re.compile(r"(?<=\d)[,٬](?=\d{3}(?!\d))")
# هرچه حرف/رقم/فاصله/نقطه نیست (نشان تجاری ®، براکت، گیومه، اسلش…) → فاصله.
# `\w` در پایتون یونیکدآگاه است، پس حروف فارسی حفظ می‌شوند.
_NON_WORD = re.compile(r"[^\w\s.]+")
# نقطه‌ای که ممیز نیست (پسوند فایل، جداکننده‌ی نام) → فاصله.
_LONE_DOT = re.compile(r"(?<!\d)\.|\.(?!\d)")
_SPACES = re.compile(r"\s+")


def normalize_product_name(raw: object) -> str:
    """نام خام → نامِ قطعیِ تطبیق (حروف کوچک، بدون نویز نوشتاری).

    >>> normalize_product_name("غذاي  خشك ۱٫۵ كيلويي")
    'غذای خشک 1.5 کیلویی'
    >>> normalize_product_name("  Royal   Canin® 2Kg ")
    'royal canin 2kg'
    """
    if raw is None:
        return ""
    text = str(raw)
    text = unicodedata.normalize("NFKC", text)
    text = text.translate(_INVISIBLE)
    text = text.translate(_LETTER_FOLD)
    text = _DIACRITICS.sub("", text)
    text = normalize_digits(text)
    text = _THOUSANDS_SEP.sub("", text)
    text = _DECIMAL_SEP.sub(".", text)
    text = _NON_WORD.sub(" ", text)
    text = text.replace("_", " ")
    text = _LONE_DOT.sub(" ", text)
    text = _SPACES.sub(" ", text)
    return text.strip().lower()


# ------------------------------------------------------------ اندازه‌ی بسته
# واحدها به یک واحدِ پایه در هر بعد نرمال می‌شوند تا مقایسه‌پذیر باشند:
# جرم → گرم، حجم → میلی‌لیتر، شمارش → عدد، طول → سانتی‌متر.
#
# نکته‌ی مهم: نیم‌فاصله در نرمال‌سازی به **فاصله** تبدیل می‌شود، پس واحدهای
# مرکب باید شکل فاصله‌دار هم داشته باشند؛ وگرنه «۵۰۰ میلی‌لیتر» به «۵۰۰ میلی» +
# «لیتر» تکه می‌شود و حجم هزار برابر کوچک خوانده می‌شود.
_UNIT_GROUPS: tuple[tuple[str, float, tuple[str, ...]], ...] = (
    # جرم (پایه: گرم)
    ("g", 1.0, ("گرم", "گرمی", "g", "gr", "gram", "grams")),
    ("g", 1000.0, ("کیلو", "کیلویی", "کیلوگرم", "کیلوگرمی", "کیلو گرم",
                   "کیلو گرمی", "kg", "kgs", "kilo", "kilogram")),
    ("g", 0.001, ("میلی‌گرم", "میلیگرم", "میلی گرم", "میلی گرمی", "mg")),
    # حجم (پایه: میلی‌لیتر)
    ("ml", 1.0, ("میلی‌لیتر", "میلیلیتر", "میلی لیتر", "میلی لیتری",
                 "میلی‌لیتری", "ml", "cc", "سی‌سی", "سی سی")),
    ("ml", 1000.0, ("لیتر", "لیتری", "l", "lt", "ltr", "liter", "litre")),
    # شمارش (پایه: عدد)
    ("pcs", 1.0, ("عدد", "عددی", "تایی", "تا", "بسته", "بسته‌ای", "بسته ای",
                  "pcs", "pc", "pack", "count", "ct", "x")),
    # طول (پایه: سانتی‌متر)
    ("cm", 1.0, ("سانت", "سانتی‌متر", "سانتیمتر", "سانتی متر", "سانتی متری",
                 "cm")),
    ("cm", 100.0, ("متر", "متری", "m")),
    ("cm", 0.1, ("میلی‌متر", "میلیمتر", "میلی متر", "mm")),
)

_UNIT_ALIASES: dict[str, tuple[str, float]] = {
    # نام مستعار نرمال‌شده ذخیره می‌شود تا با متنِ نرمال‌شده تطبیق بخورد
    normalize_product_name(alias): (base, factor)
    for base, factor, aliases in _UNIT_GROUPS
    for alias in aliases
}

# طولانی‌ترین‌ها اول، وگرنه «کیلو» جلوی «کیلو گرم» را می‌گیرد.
_UNIT_PATTERN = "|".join(
    re.escape(u) for u in sorted(_UNIT_ALIASES, key=len, reverse=True)
)
_SIZE_RE = re.compile(rf"(?<![\d.])(\d+(?:\.\d+)?)\s*({_UNIT_PATTERN})(?!\w)")

# عددِ تنها (بدون واحد) هرگز «اندازه» تفسیر نمی‌شود — ابهامش بیش از حد است
# («کد ۱۲۳۴» اندازه نیست). «۱۲ تایی» چون واحد شمارشی صریح دارد پذیرفته است.


@dataclass(frozen=True)
class PackSize:
    """اندازه‌ی بسته‌ی استخراج‌شده از نام کالا.

    `value` در واحدِ پایه است (گرم/میلی‌لیتر/عدد/سانتی‌متر)، پس دو نامِ
    «۱٫۵ کیلویی» و «1500 گرم» یک مقدار می‌دهند.
    """

    value: float
    unit: str
    raw_text: str

    @property
    def value_milli(self) -> int:
        """مقدار ×۱۰۰۰ برای ذخیره‌ی صحیح در دفتر کل."""
        return int(round(self.value * 1000))


def parse_pack_size(raw: object) -> PackSize | None:
    """استخراج اندازه‌ی بسته از نام کالا؛ نبود/ابهام → `None`.

    وقتی چند اندازه در یک نام باشد (مثل «۱۲ عددی ۵۰۰ میلی‌لیتر») بزرگ‌ترین
    مقدارِ **غیرشمارشی** انتخاب می‌شود، چون آن است که مصرف را تعیین می‌کند؛
    شمارش فقط وقتی برمی‌گردد که تنها اطلاعات موجود باشد.

    >>> parse_pack_size("غذای خشک ۱٫۵ کیلویی").value
    1500.0
    >>> parse_pack_size("شامپو 500ml").unit
    'ml'
    >>> parse_pack_size("کالای بدون اندازه") is None
    True
    """
    text = normalize_product_name(raw)
    if not text:
        return None
    matches = _SIZE_RE.findall(text)
    if not matches:
        return None

    parsed: list[PackSize] = []
    for number, unit_token in matches:
        try:
            amount = float(number)
        except ValueError:  # pragma: no cover - الگو فقط عدد معتبر می‌دهد
            continue
        if amount <= 0:
            continue
        base_unit, factor = _UNIT_ALIASES[unit_token]
        parsed.append(PackSize(amount * factor, base_unit, f"{number} {unit_token}"))

    if not parsed:
        return None
    non_count = [p for p in parsed if p.unit != "pcs"]
    pool = non_count or parsed
    return max(pool, key=lambda p: p.value)


def product_family_key(raw: object) -> str:
    """نامِ نرمال‌شده **بدون** بخش اندازه — کلید «همان کالا، بسته‌ی دیگر».

    >>> product_family_key("غذای خشک گربه ۱٫۵ کیلویی")
    'غذای خشک گربه'
    >>> product_family_key("غذای خشک گربه 3kg")
    'غذای خشک گربه'
    """
    text = normalize_product_name(raw)
    if not text:
        return ""
    stripped = _SPACES.sub(" ", _SIZE_RE.sub(" ", text)).strip()
    # اگر نام چیزی جز اندازه نداشت، حذف اندازه کلید را خالی می‌کرد و همه‌ی
    # چنین کالاهایی در یک خانواده‌ی جعلی جمع می‌شدند → نامِ کامل برمی‌گردد.
    return stripped or text


__all__ = [
    "PackSize",
    "normalize_product_name",
    "parse_pack_size",
    "product_family_key",
]
