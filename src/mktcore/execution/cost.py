"""هزینه‌ی ارسال پیامک — قطعه‌شماری و قیمت.

## چرا قطعه‌شماری، و نه تقسیم ساده

پنل‌های پیامکی «هر ۷۰ کاراکتر» قیمت می‌دهند و برای پیام‌های کوتاه همین درست است.
ولی وقتی پیام بلندتر از یک قطعه شود، استاندارد GSM شش بایت سرآیندِ اتصال
(UDH) به **هر** قطعه اضافه می‌کند و ظرفیت هر قطعه از ۷۰ به **۶۷** کاراکتر
می‌افتد.

نتیجه‌ی عملی: پیامِ ۱۴۰ کاراکتری با تقسیم ساده «۲ قطعه» حساب می‌شود ولی پنل
**۳ قطعه** می‌گیرد — یعنی ۵۰٪ کم‌برآورد. برای پیام‌های زیر ۷۰ کاراکتر هر دو
قاعده دقیقاً یکی‌اند، پس این تفاوت فقط جایی ظاهر می‌شود که واقعاً اهمیت دارد.

کم‌برآوردِ هزینه سمتِ خطرناک است (بودجه‌ی کمپین را بیشتر از واقع نشان می‌دهد)،
پس قاعده‌ی واقعیِ پنل پیاده شده است نه تقسیم ساده.

## چرا UCS-2

هر متنِ فارسی خارج از جدول GSM-7 است، پس پیام به‌صورت UCS-2 کدگذاری می‌شود و
ظرفیت همان ۷۰/۶۷ است. پیامِ کاملاً لاتین ظرفیت ۱۶۰/۱۵۳ دارد، ولی همه‌ی
پیام‌های این سیستم فارسی‌اند؛ اگر روزی قالب لاتین اضافه شود، این ماژول جای
درستِ افزودنش است.
"""

from __future__ import annotations

import math

# ظرفیت یک پیامکِ تک‌قطعه‌ای (UCS-2)
SEGMENT_CHARS_SINGLE = 70
# ظرفیت هر قطعه وقتی پیام چندقطعه‌ای است — شش بایت سرآیندِ اتصال کم می‌کند
SEGMENT_CHARS_MULTIPART = 67

# قیمت هر قطعه به ریال. ۳۰۰ تومان = ۳۰۰۰ ریال (نرخِ اعلام‌شده‌ی کاربر).
# ریالِ صحیح، مثل بقیه‌ی پول‌های این سیستم.
DEFAULT_COST_PER_SEGMENT_RIAL = 3_000


def segment_count(text: str) -> int:
    """تعداد قطعه‌های پیامک — همان چیزی که پنل صورتحساب می‌کند."""
    length = len(text or "")
    if length == 0:
        return 0
    if length <= SEGMENT_CHARS_SINGLE:
        return 1
    return math.ceil(length / SEGMENT_CHARS_MULTIPART)


def message_cost_rial(
    text: str, *, cost_per_segment_rial: int = DEFAULT_COST_PER_SEGMENT_RIAL,
) -> int:
    """هزینه‌ی یک پیام به ریال."""
    return segment_count(text) * int(cost_per_segment_rial)


def total_cost_rial(
    texts: list[str], *, cost_per_segment_rial: int = DEFAULT_COST_PER_SEGMENT_RIAL,
) -> int:
    """هزینه‌ی یک دسته پیام."""
    return sum(
        message_cost_rial(t, cost_per_segment_rial=cost_per_segment_rial) for t in texts
    )


def cost_note_fa(
    n_messages: int, n_segments: int, cost_rial: int, *, display_text: str,
) -> str:
    """جمله‌ی هزینه برای کاربر — عدد بدون توضیح گمراه‌کننده است."""
    if n_messages == 0:
        return "پیامی برای ارسال نیست، پس هزینه‌ای هم ندارد."
    per_message = n_segments / n_messages
    return (
        f"{n_messages} پیام، مجموعاً {n_segments} قطعه "
        f"(به‌طور میانگین {per_message:.1f} قطعه برای هر پیام) — {display_text}. "
        "هزینه بر پایه‌ی قطعه‌شماری پنل محاسبه شده، نه تقسیم ساده‌ی طول متن."
    )


__all__ = [
    "DEFAULT_COST_PER_SEGMENT_RIAL",
    "SEGMENT_CHARS_MULTIPART",
    "SEGMENT_CHARS_SINGLE",
    "cost_note_fa",
    "message_cost_rial",
    "segment_count",
    "total_cost_rial",
]
