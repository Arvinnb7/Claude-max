"""خواندن خطوط دفتر کل به‌صورت فریم — با گاردِ زمانی در یک نقطه.

**چرا این ماژول وجود دارد.** آموزش مدل به «آنچه در تاریخ T می‌دانستیم» نیاز
دارد، ولی `customer_features` فقط یک عکس دارد (به‌ازای هر بارگذاری، با
`as_of = بیشینه‌ی تاریخ فایل`). پس ویژگی‌ها باید از خودِ دفتر کل بازسازی شوند.

**چرا گارد فقط اینجاست.** §۲۹.۲ می‌گوید هیچ ویژگی‌ای نباید اطلاعاتِ ثبت‌شده
بعد از لحظه‌ی پیش‌بینی داشته باشد. اگر این شرط در ده جا تکرار شود، یک‌جا از قلم
می‌افتد و نشتِ بی‌صدا رخ می‌دهد. پس تنها همین تابع `as_of` می‌گیرد و لایه‌ی
خالص مستقلاً بررسی می‌کند که فریمِ ورودی از آن تاریخ فراتر نرفته باشد.

**چرا برشِ اکید (`<` و نه `<=`).** `line_date` تاریخ است نه زمان؛ خریدی که
همان روز ثبت شده، دانشِ ساعت ۸ صبحِ همان روز نیست. حالتِ مبهم به‌نفع
محافظه‌کاری حل می‌شود.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd
from sqlalchemy import select

from mktcore.db.models import Order, OrderLine, Product

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

# ستون‌های فریم — ترتیبشان ثابت است تا تست‌های برابریِ فریم پایدار بمانند.
LINE_COLUMNS: tuple[str, ...] = (
    "customer_id", "order_id", "line_date", "revenue_rial", "gross_profit_rial",
    "cost_rial", "quantity_milli", "unit_price_rial", "discount_rial",
    "discount_rate_bp", "product_id", "category", "branch", "channel", "is_return",
)

# ستون‌هایی که ممکن است NULL باشند و «نامعلوم» معنا می‌دهند، نه صفر. `Int64`
# پانداس (نه `int64`) نگه‌شان می‌دارد؛ با نوعِ ساده، NULL به صفر تبدیل می‌شد.
_NULLABLE_INT = (
    "gross_profit_rial", "cost_rial", "quantity_milli", "unit_price_rial",
    "discount_rial", "discount_rate_bp", "order_id", "product_id",
)


def load_line_frame(
    session: Session,
    business_id: int,
    *,
    as_of: str | None = None,
    since: str | None = None,
) -> pd.DataFrame:
    """خطوط این کسب‌وکار تا **پیش از** `as_of`.

    `as_of` خالی یعنی «همه‌ی تاریخچه» — فقط برای مسیرهایی که خودشان برش
    می‌زنند (مثل ساختِ برچسب که به پنجره‌ی نتیجه نیاز دارد).
    """
    stmt = (
        select(
            OrderLine.customer_id,
            OrderLine.order_id,
            OrderLine.line_date,
            OrderLine.revenue_rial,
            OrderLine.gross_profit_rial,
            OrderLine.cost_rial,
            OrderLine.quantity_milli,
            OrderLine.unit_price_rial,
            OrderLine.discount_rial,
            OrderLine.discount_rate_bp,
            OrderLine.product_id,
            Product.category,
            Order.branch,
            Order.channel,
            OrderLine.is_return,
        )
        .join(Product, Product.id == OrderLine.product_id, isouter=True)
        .join(Order, Order.id == OrderLine.order_id, isouter=True)
        .where(
            OrderLine.business_id == business_id,
            OrderLine.customer_id.isnot(None),
        )
    )
    if as_of:
        stmt = stmt.where(OrderLine.line_date < as_of)
    if since:
        stmt = stmt.where(OrderLine.line_date >= since)

    rows = session.execute(stmt.order_by(OrderLine.line_date, OrderLine.id)).all()
    frame = pd.DataFrame(rows, columns=list(LINE_COLUMNS))
    if frame.empty:
        # فریمِ خالی هم باید همان ستون‌ها و نوع‌ها را داشته باشد، وگرنه
        # مصرف‌کننده باید همه‌جا حالتِ خالی را جدا مدیریت کند.
        for column in _NULLABLE_INT:
            frame[column] = frame[column].astype("Int64")
        frame["is_return"] = frame["is_return"].astype(bool)
        return frame

    frame["customer_id"] = frame["customer_id"].astype("int64")
    frame["revenue_rial"] = frame["revenue_rial"].astype("int64")
    for column in _NULLABLE_INT:
        frame[column] = frame[column].astype("Int64")
    frame["line_date"] = frame["line_date"].astype(str)
    frame["is_return"] = frame["is_return"].fillna(False).astype(bool)
    return frame


def first_order_dates(frame: pd.DataFrame) -> pd.Series:
    """نخستین تاریخ خرید هر مشتری، از **همین** فریم.

    عمداً از `Customer.first_order_date` خوانده نمی‌شود: آن ستون همیشه واقعیتِ
    امروز را می‌گوید، و اگر در بازسازیِ تاریخ T به‌کار رود، تاریخی را نشان
    می‌دهد که ممکن است بعد از T ثبت شده باشد. اینجا فریم از قبل برش خورده، پس
    کمینه‌اش همان چیزی است که در T می‌دانستیم.
    """
    if frame.empty:
        return pd.Series(dtype=object)
    return frame.groupby("customer_id")["line_date"].min()


__all__ = ["LINE_COLUMNS", "first_order_dates", "load_line_frame"]
