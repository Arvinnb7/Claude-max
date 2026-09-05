"""حل هویت — تبدیل شناسه‌های خامِ فایل به موجودیت پایدار.

قاعده‌ی سختِ این لایه: **فقط تطبیق قطعی (deterministic)**. تطبیق فازیِ نام
مشتری عمداً پیاده نشده است، چون هزینه‌ی خطای آن نامتقارن است: ادغام غلطِ دو
مشتری واقعی، تاریخِ خرید هر دو را خراب می‌کند و برگشتش دستی است؛ در حالی که
جانمانده‌ی یک پیوند فقط یعنی «هنوز وصل نشده».
"""

from .email import normalize_email
from .phone import (
    is_mobile,
    mask_phone,
    normalize_phone,
    phone_identity_key,
)

__all__ = ["is_mobile", "mask_phone", "normalize_email", "normalize_phone", "phone_identity_key"]
