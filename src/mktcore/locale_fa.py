"""ابزارهای فارسی‌سازی: برچسب‌ها، مترادف ستون‌ها، رقم فارسی و تاریخ جلالی."""

from __future__ import annotations

import datetime as _dt

# نگاشت ارقام فارسی/عربی به انگلیسی
_PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
_ARABIC_DIGITS = "٠١٢٣٤٥٦٧٨٩"
_DIGIT_MAP = {ord(p): str(i) for i, p in enumerate(_PERSIAN_DIGITS)}
_DIGIT_MAP.update({ord(a): str(i) for i, a in enumerate(_ARABIC_DIGITS)})
# جداکننده‌ی هزارگان فارسی/عربی و کاراکترهای جهت‌دهی
_DIGIT_MAP.update({ord("٬"): "", ord("،"): ",", 0x200C: "", 0x200F: "", 0x200E: ""})


def normalize_digits(text: str) -> str:
    """تبدیل ارقام فارسی/عربی به انگلیسی و حذف جداکننده‌های فارسی."""
    return str(text).translate(_DIGIT_MAP)


# برچسب‌های فارسی نقش ستون‌ها (برای نمایش در UI)
ROLE_LABELS_FA: dict[str, str] = {
    "DATE": "تاریخ",
    "REVENUE": "درآمد/مبلغ",
    "QUANTITY": "تعداد",
    "UNIT_PRICE": "قیمت واحد",
    "PRODUCT": "محصول",
    "CATEGORY": "دسته‌بندی",
    "CUSTOMER_ID": "مشتری",
    "CHANNEL": "کانال فروش",
    "REGION": "منطقه",
    "COST": "هزینه",
    "ORDER_ID": "شماره سفارش",
    "DISCOUNT": "تخفیف",
}

# مترادف‌های نام ستون‌ها (فارسی + انگلیسی) برای تشخیص خودکار نگاشت.
# کلیدها نقش‌اند؛ مقادیر فهرست واژه‌های کلیدی نرمال‌شده (lower).
COLUMN_SYNONYMS: dict[str, list[str]] = {
    "DATE": [
        "تاریخ", "زمان", "تاریخ فروش", "تاریخ سفارش", "تاریخ ثبت",
        "date", "order date", "sale date", "timestamp", "datetime", "day", "روز",
    ],
    "REVENUE": [
        "درآمد", "مبلغ", "مبلغ کل", "فروش", "مبلغ فروش", "ارزش", "جمع", "قیمت کل", "مبلغ نهایی",
        "revenue", "amount", "total", "sales", "sale amount", "value", "grand total",
        "net amount", "total price", "turnover",
    ],
    "QUANTITY": [
        "تعداد", "مقدار", "کمیت", "تعداد فروش",
        "quantity", "qty", "count", "units", "volume",
    ],
    "UNIT_PRICE": [
        "قیمت واحد", "قیمت", "قیمت تک", "فی",
        "unit price", "price", "unit cost", "rate",
    ],
    "PRODUCT": [
        "محصول", "کالا", "نام محصول", "نام کالا", "آیتم",
        "product", "item", "sku", "product name", "goods",
    ],
    "CATEGORY": [
        "دسته", "دسته‌بندی", "گروه", "گروه کالا",
        "category", "group", "type", "segment", "department",
    ],
    "CUSTOMER_ID": [
        "مشتری", "کد مشتری", "شناسه مشتری", "نام مشتری", "خریدار",
        "customer", "customer id", "client", "buyer", "user", "user id", "account",
    ],
    "CHANNEL": [
        "کانال", "کانال فروش", "روش فروش", "مبدا",
        "channel", "source", "medium", "platform",
    ],
    "REGION": [
        "منطقه", "استان", "شهر", "ناحیه", "محل",
        "region", "city", "province", "state", "area", "location", "country",
    ],
    "COST": [
        "هزینه", "بهای تمام شده", "قیمت خرید", "هزینه کالا",
        "cost", "cogs", "expense", "purchase price",
    ],
    "ORDER_ID": [
        "شماره سفارش", "کد سفارش", "شناسه سفارش", "فاکتور", "شماره فاکتور",
        "order", "order id", "invoice", "invoice id", "transaction id", "order number",
    ],
    "DISCOUNT": [
        "تخفیف", "مبلغ تخفیف", "درصد تخفیف",
        "discount", "off", "promo",
    ],
}


def to_jalali(d: _dt.date | _dt.datetime) -> str:
    """تبدیل تاریخ میلادی به رشته‌ی جلالی (YYYY/MM/DD). در نبود jdatetime به ISO برمی‌گردد."""
    try:
        import jdatetime

        if isinstance(d, _dt.datetime):
            d = d.date()
        jd = jdatetime.date.fromgregorian(date=d)
        return jd.strftime("%Y/%m/%d")
    except Exception:
        return d.isoformat()


def format_number_fa(value: float, decimals: int = 0) -> str:
    """قالب‌بندی عدد با جداکننده‌ی هزارگان (به‌صورت ارقام انگلیسی)."""
    try:
        if decimals > 0:
            return f"{value:,.{decimals}f}"
        return f"{value:,.0f}"
    except (ValueError, TypeError):
        return str(value)
