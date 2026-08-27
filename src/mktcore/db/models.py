"""مدل‌های canonical — دفتر کل پایدارِ فروش، هویت و کیفیت داده.

این جداول **جایگزین** خط لوله‌ی تحلیل نیستند؛ چیزی را نگه می‌دارند که یک نشستِ
تنها نمی‌تواند بدهد:

* **هویت پایدار مشتری و محصول** بین بارگذاری‌های مختلف (تحلیل امروز فقط داخل یک
  فایل مشتری را می‌شناسد؛ فایل ماه بعد همان مشتری را غریبه می‌بیند).
* **دفتر خطوط فروش با کلید idempotent** تا تحلیل دوباره‌ی یک فایل، جمع‌ها را دو
  برابر نکند و تصحیح نگاشت ستون به‌جای ردیف تکراری، مقدار را به‌روز کند.
* **آشتی ماندگار هر بارگذاری** تا «آیا این بارگذاری قابل انتشار بود؟» ماه‌ها بعد
  هم قابل اثبات باشد.

`business_id` روی همه‌ی جداول است (سند §۳۳): امروز یک business پیش‌فرض ساخته
می‌شود، ولی جداکردنِ بعدیِ داده‌ی چند کسب‌وکار به مهاجرت داده نیاز ندارد.

**بهای تمام‌شده**: ستون‌های `*cost*` ساخته می‌شوند ولی تا وقتی داده‌ی بهای خرید
وجود ندارد **NULL می‌مانند**. هیچ عدد درآمدی «سود» نامیده نمی‌شود.
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, now_ts

# ---------------------------------------------------------------- کسب‌وکار


class Business(Base):
    """واحد جداسازی داده. امروز یکی است؛ فردا چند مستأجر."""

    __tablename__ = "businesses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    # واحد نمایشِ ترجیحی این کسب‌وکار. مبالغ ذخیره‌شده همیشه ریال‌اند؛ این فقط
    # برای برگرداندن عدد به واحدی است که کاربر انتظار دارد.
    display_currency: Mapped[str] = mapped_column(String(16), default="تومان")
    created_at: Mapped[float] = mapped_column(Float, default=now_ts)


# ---------------------------------------------------------------- بارگذاری


class ImportBatch(Base):
    """یک بارگذاری فایل. `dataset_key` هشِ محتوای فایل است، پس یک فایل یکسان
    همیشه همان دسته را می‌گیرد و تحلیل دوباره‌اش `revision` را بالا می‌برد."""

    __tablename__ = "import_batches"
    __table_args__ = (
        UniqueConstraint("business_id", "dataset_key", "revision"),
        Index("ix_import_batches_business_created", "business_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), index=True)
    dataset_key: Mapped[str] = mapped_column(String(64), index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    # نشستِ تحلیلی که این بارگذاری را ساخت (پیوند به لایه‌ی legacy، بدون FK چون
    # مالک آن جدول `api/persistence.py` است و این لایه نباید قیدی رویش بگذارد).
    session_id: Mapped[str | None] = mapped_column(String(64), index=True)
    filename: Mapped[str | None] = mapped_column(String(255))
    sheet_name: Mapped[str | None] = mapped_column(String(255))

    file_currency: Mapped[str | None] = mapped_column(String(16))
    display_currency: Mapped[str | None] = mapped_column(String(16))
    # چند ریال در یک واحدِ فایل — تبدیل انجام‌شده در مرز نوشتن، برای ممیزی
    rial_per_file_unit: Mapped[int | None] = mapped_column(Integer)

    # حسابرسی ردیف: خام = تمیز + حذفی + تکراری + برگشتی
    rows_total: Mapped[int | None] = mapped_column(Integer)
    rows_clean: Mapped[int | None] = mapped_column(Integer)
    rows_invalid: Mapped[int | None] = mapped_column(Integer)
    rows_duplicate: Mapped[int | None] = mapped_column(Integer)
    rows_returns: Mapped[int | None] = mapped_column(Integer)

    lines_inserted: Mapped[int] = mapped_column(Integer, default=0)
    lines_updated: Mapped[int] = mapped_column(Integer, default=0)

    date_min: Mapped[str | None] = mapped_column(String(10))
    date_max: Mapped[str | None] = mapped_column(String(10))
    net_sales_rial: Mapped[int | None] = mapped_column(BigInteger)

    # PASS / PASS_WITH_WARNINGS / FAIL — همان دروازه‌ی تحلیل، کپی‌شده برای ممیزی
    validation_status: Mapped[str | None] = mapped_column(String(32))
    # OK / RECONCILED / MISMATCH — نتیجه‌ی آشتی نوشتن (مستقل از دروازه‌ی تحلیل)
    reconcile_status: Mapped[str | None] = mapped_column(String(32))
    notes_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[float] = mapped_column(Float, default=now_ts, index=True)


class ImportReconciliation(Base):
    """آشتی هر بارگذاری: «آنچه تحلیل گفت» در برابر «آنچه در دفتر کل نشست».

    این جدول عمداً از `bundle.validation.checks` جداست: افزودن به آن‌ها دروازه‌ی
    انتشار (`_require_publishable`) را می‌بست و تولید استراتژی را بی‌دلیل مسدود
    می‌کرد. اینجا شواهد نوشتن ثبت می‌شود، نه صحتِ داده‌ی ورودی.
    """

    __tablename__ = "import_reconciliation"
    __table_args__ = (
        UniqueConstraint("batch_id", "check_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(
        ForeignKey("import_batches.id", ondelete="CASCADE"), index=True
    )
    check_id: Mapped[str] = mapped_column(String(32))
    label_fa: Mapped[str] = mapped_column(String(255))
    expected_text: Mapped[str | None] = mapped_column(String(64))
    actual_text: Mapped[str | None] = mapped_column(String(64))
    delta_text: Mapped[str | None] = mapped_column(String(64))
    tolerance_text: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))  # OK / WARN / MISMATCH
    detail_fa: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[float] = mapped_column(Float, default=now_ts)


# ------------------------------------------------------------------ هویت


class Customer(Base):
    """مشتری پایدار. `canonical_key` کلیدی است که تحلیل با آن کار می‌کند، پس
    اعداد داشبورد و دفتر کل روی یک تعریف از «مشتری» می‌ایستند."""

    __tablename__ = "customers"
    __table_args__ = (
        UniqueConstraint("business_id", "canonical_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), index=True)
    canonical_key: Mapped[str] = mapped_column(String(128), index=True)
    display_name: Mapped[str | None] = mapped_column(String(255))
    phone_e164: Mapped[str | None] = mapped_column(String(20), index=True)
    email: Mapped[str | None] = mapped_column(String(255))
    first_order_date: Mapped[str | None] = mapped_column(String(10))
    last_order_date: Mapped[str | None] = mapped_column(String(10))
    # «چطور این مشتری شناسایی شد» — deterministic تنها روش مجازِ فعلی است؛
    # تطبیق فازیِ نام عمداً پیاده نشده (ریسک ادغام دو مشتری واقعی).
    resolution_method: Mapped[str] = mapped_column(String(32), default="raw_key")
    created_at: Mapped[float] = mapped_column(Float, default=now_ts)
    updated_at: Mapped[float] = mapped_column(Float, default=now_ts)


class CustomerKey(Base):
    """شناسه‌های یک مشتری (کلید خام فایل، موبایل نرمال‌شده، ایمیل).

    یکتاییِ (business, key_type, key_value) همان چیزی است که اجازه می‌دهد فایل
    ماه بعد به همان مشتری وصل شود.
    """

    __tablename__ = "customer_keys"
    __table_args__ = (
        UniqueConstraint("business_id", "key_type", "key_value"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), index=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), index=True
    )
    key_type: Mapped[str] = mapped_column(String(16))  # raw_key / phone / email
    key_value: Mapped[str] = mapped_column(String(255))
    # فقط پیوندهای قطعی نوشته می‌شوند؛ عدد برای ممیزی و فیلترهای آینده است.
    confidence_bp: Mapped[int] = mapped_column(Integer, default=10000)
    first_seen_at: Mapped[float] = mapped_column(Float, default=now_ts)


# ----------------------------------------------------------------- کاتالوگ


class Product(Base):
    """محصول پایدار با نامِ نرمال‌شده. ویژگی‌ها **از داده** استخراج می‌شوند
    (اندازه/واحد بسته)؛ هیچ فرضِ دامنه‌ای hardcode نشده چون کسب‌وکار چنددامنه است."""

    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("business_id", "canonical_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), index=True)
    canonical_name: Mapped[str] = mapped_column(String(255), index=True)
    display_name: Mapped[str] = mapped_column(String(255))
    category: Mapped[str | None] = mapped_column(String(255))
    brand: Mapped[str | None] = mapped_column(String(255))
    # اندازه‌ی بسته: مقدار ×۱۰۰۰ + واحدِ نرمال‌شده (g/kg/ml/l/عدد) — مبنای
    # «تعدیل مقدار» در چرخه‌ی خرید. استخراج‌نشده → NULL، نه صفر.
    pack_size_milli: Mapped[int | None] = mapped_column(BigInteger)
    pack_unit: Mapped[str | None] = mapped_column(String(16))
    # بهای تمام‌شده در دست نیست → این ستون‌ها NULL می‌مانند (مسدود، نه فراموش‌شده)
    last_unit_cost_rial: Mapped[int | None] = mapped_column(BigInteger)
    cost_confidence: Mapped[str | None] = mapped_column(String(16))
    created_at: Mapped[float] = mapped_column(Float, default=now_ts)
    updated_at: Mapped[float] = mapped_column(Float, default=now_ts)


class ProductAlias(Base):
    """نام‌های خامی که به یک محصول اشاره می‌کنند (فاصله/نیم‌فاصله/ی‌وک متفاوت)."""

    __tablename__ = "product_aliases"
    __table_args__ = (
        UniqueConstraint("business_id", "alias_norm"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), index=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), index=True
    )
    alias_norm: Mapped[str] = mapped_column(String(255), index=True)
    alias_raw: Mapped[str] = mapped_column(String(255))
    source: Mapped[str] = mapped_column(String(32), default="import")
    created_at: Mapped[float] = mapped_column(Float, default=now_ts)


# ------------------------------------------------------------------ فروش


class Order(Base):
    """سرِ فاکتور. جمع‌ها از خطوط ساخته می‌شوند، پس همیشه با آن‌ها آشتی‌اند."""

    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("business_id", "order_key"),
        Index("ix_orders_business_date", "business_id", "order_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), index=True)
    order_key: Mapped[str] = mapped_column(String(128), index=True)
    customer_id: Mapped[int | None] = mapped_column(
        ForeignKey("customers.id", ondelete="SET NULL"), index=True
    )
    order_date: Mapped[str] = mapped_column(String(10), index=True)  # ISO میلادی
    gross_rial: Mapped[int] = mapped_column(BigInteger, default=0)
    returns_rial: Mapped[int] = mapped_column(BigInteger, default=0)
    net_rial: Mapped[int] = mapped_column(BigInteger, default=0)
    discount_rial: Mapped[int | None] = mapped_column(BigInteger)
    line_count: Mapped[int] = mapped_column(Integer, default=0)
    branch: Mapped[str | None] = mapped_column(String(255))
    salesperson: Mapped[str | None] = mapped_column(String(255))
    channel: Mapped[str | None] = mapped_column(String(255))
    region: Mapped[str | None] = mapped_column(String(255))
    batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("import_batches.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[float] = mapped_column(Float, default=now_ts)
    updated_at: Mapped[float] = mapped_column(Float, default=now_ts)


class OrderLine(Base):
    """قلم فروش — دانه‌بندی پایه‌ی همه‌چیز.

    `line_uid = sha256(business|dataset|sheet|source_row)`: `source_row` از قبل
    در فریم تمیز وجود دارد و از تعریف «تکراری» مستثناست، پس یک ردیفِ مشخص در یک
    فایلِ مشخص همیشه همان کلید را می‌گیرد → درج دوباره upsert است نه ردیف نو.
    """

    __tablename__ = "order_lines"
    __table_args__ = (
        UniqueConstraint("line_uid"),
        Index("ix_order_lines_business_date", "business_id", "line_date"),
        Index("ix_order_lines_customer_date", "customer_id", "line_date"),
        Index("ix_order_lines_product_date", "product_id", "line_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    line_uid: Mapped[str] = mapped_column(String(64), index=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), index=True)
    batch_id: Mapped[int] = mapped_column(
        ForeignKey("import_batches.id", ondelete="CASCADE"), index=True
    )
    order_id: Mapped[int | None] = mapped_column(
        ForeignKey("orders.id", ondelete="SET NULL"), index=True
    )
    customer_id: Mapped[int | None] = mapped_column(
        ForeignKey("customers.id", ondelete="SET NULL"), index=True
    )
    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("products.id", ondelete="SET NULL"), index=True
    )

    line_date: Mapped[str] = mapped_column(String(10), index=True)
    quantity_milli: Mapped[int | None] = mapped_column(BigInteger)
    unit_price_rial: Mapped[int | None] = mapped_column(BigInteger)
    revenue_rial: Mapped[int] = mapped_column(BigInteger)
    gross_amount_rial: Mapped[int | None] = mapped_column(BigInteger)
    # تخفیف مبلغی و نسبتی هرگز هم‌زمان پر نمی‌شوند؛ تفسیر در پاک‌سازی تعیین شده
    discount_rial: Mapped[int | None] = mapped_column(BigInteger)
    discount_rate_bp: Mapped[int | None] = mapped_column(Integer)
    # بهای تمام‌شده‌ی همین خط (نه واحد). اگر فایل ستون بها نداشته باشد NULL
    # می‌ماند — هرگز صفر، چون صفر یعنی «رایگان» و سود را جعلی می‌کند.
    cost_rial: Mapped[int | None] = mapped_column(BigInteger)
    # `from_file` | `history_exact` | `history_imputed` — سطح سوم یعنی بها از
    # تاریخچه به عقب تعمیم داده شده (§۳.۴: «هر بهای تخمینی باید تخمینی برچسب
    # بخورد و سطح اطمینان داشته باشد»).
    cost_confidence: Mapped[str | None] = mapped_column(String(24))
    # سود ناخالصِ همین خط = درآمد − بها. **بها NULL ⇒ این هم NULL**، هرگز صفر:
    # صفر یعنی «سودی نداشت» در حالی که واقعیت «نمی‌دانیم» است.
    gross_profit_rial: Mapped[int | None] = mapped_column(BigInteger)

    is_return: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    # provenance: با این دو ستون می‌شود از هر عددِ گزارش به ردیف فایل رسید
    source_row: Mapped[int | None] = mapped_column(Integer)
    sheet_name: Mapped[str | None] = mapped_column(String(255))
    raw_customer_key: Mapped[str | None] = mapped_column(String(255))
    raw_product_name: Mapped[str | None] = mapped_column(String(255))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[float] = mapped_column(Float, default=now_ts)
    updated_at: Mapped[float] = mapped_column(Float, default=now_ts)


# ------------------------------------------------------------ ویژگی مشتری


class CustomerFeature(Base):
    """عکس ماندگارِ ویژگی‌های مشتری در یک زمان مشخص.

    محاسبه همان‌جایی می‌ماند که هست (`analysis/*` روی pandas — تست‌شده و درست)؛
    اینجا فقط **نتیجه** با `as_of` و نسخه ثبت می‌شود تا «آن‌موقع چه می‌دانستیم»
    قابل بازسازی باشد — پیش‌نیازِ سنجش صادقانه‌ی اثر.
    """

    __tablename__ = "customer_features"
    __table_args__ = (
        UniqueConstraint("business_id", "customer_id", "as_of_date", "feature_version"),
        Index("ix_customer_features_business_asof", "business_id", "as_of_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), index=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), index=True
    )
    as_of_date: Mapped[str] = mapped_column(String(10), index=True)
    feature_version: Mapped[int] = mapped_column(Integer, default=1)

    n_orders: Mapped[int | None] = mapped_column(Integer)
    n_lines: Mapped[int | None] = mapped_column(Integer)
    monetary_rial: Mapped[int | None] = mapped_column(BigInteger)
    aov_rial: Mapped[int | None] = mapped_column(BigInteger)
    recency_days: Mapped[int | None] = mapped_column(Integer)
    tenure_days: Mapped[int | None] = mapped_column(Integer)
    avg_gap_days: Mapped[float | None] = mapped_column(Float)
    expected_gap_days: Mapped[float | None] = mapped_column(Float)
    overdue_days: Mapped[float | None] = mapped_column(Float)
    p_alive_bp: Mapped[int | None] = mapped_column(Integer)
    clv_rial: Mapped[int | None] = mapped_column(BigInteger)
    segment: Mapped[str | None] = mapped_column(String(64))
    lifecycle_state: Mapped[str | None] = mapped_column(String(64))
    cycle_status: Mapped[str | None] = mapped_column(String(64))
    top_product: Mapped[str | None] = mapped_column(String(255))
    # درآمدمحور است، نه سودمحور — نام ستون همین را می‌گوید تا کسی اشتباه نکند
    value_at_risk_rial: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[float] = mapped_column(Float, default=now_ts)


class CustomerLifecycleEvent(Base):
    """گذارهای حالت چرخه‌ی عمر — فقط افزودنی.

    حالت جاری روی `customer_features` است؛ این جدول «کِی و چرا عوض شد» را نگه
    می‌دارد. بدون آن، «این مشتری از وفادار به در خطر ریزش رفت» قابل دیدن نیست
    و همین گذار، مهم‌ترین لحظه‌ی اقدام است.
    """

    __tablename__ = "customer_lifecycle_events"
    __table_args__ = (
        Index("ix_lifecycle_events_customer_date", "customer_id", "as_of_date"),
        UniqueConstraint("business_id", "customer_id", "as_of_date", "to_state"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), index=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), index=True
    )
    as_of_date: Mapped[str] = mapped_column(String(10), index=True)
    from_state: Mapped[str | None] = mapped_column(String(32))
    to_state: Mapped[str] = mapped_column(String(32), index=True)
    reason_fa: Mapped[str | None] = mapped_column(Text)
    # personal / population / count_only — پایه‌ی قضاوت، برای شفافیت در UI
    basis: Mapped[str | None] = mapped_column(String(16))
    overdue_ratio: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[float] = mapped_column(Float, default=now_ts, index=True)


# -------------------------------------------------------------------- فرصت


class OpportunityRun(Base):
    """یک اجرای موتور فرصت‌ها. بدون این، نمی‌شود گفت یک فرصت از کجا آمده."""

    __tablename__ = "opportunity_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), index=True)
    session_id: Mapped[str | None] = mapped_column(String(64), index=True)
    as_of_date: Mapped[str] = mapped_column(String(10), index=True)
    engine_version: Mapped[int] = mapped_column(Integer, default=1)
    candidates_generated: Mapped[int] = mapped_column(Integer, default=0)
    candidates_filtered: Mapped[int] = mapped_column(Integer, default=0)
    opportunities_created: Mapped[int] = mapped_column(Integer, default=0)
    opportunities_refreshed: Mapped[int] = mapped_column(Integer, default=0)
    opportunities_superseded: Mapped[int] = mapped_column(Integer, default=0)
    opportunities_expired: Mapped[int] = mapped_column(Integer, default=0)
    notes_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[float] = mapped_column(Float, default=now_ts, index=True)


class Opportunity(Base):
    """فرصت ماندگار با چرخه‌ی حیات.

    تفاوت با «فهرست اقدام» فعلی: آن یک خروجی لحظه‌ای است که با هر تحلیل از نو
    ساخته می‌شود. این یک **موجودیت** است — پذیرفته می‌شود، به کسی سپرده می‌شود،
    نتیجه می‌گیرد، و تاریخچه‌اش می‌ماند. بدون آن، حلقه‌ی «پیشنهاد → اقدام →
    نتیجه» بسته نمی‌شود.

    `dedupe_key` تضمین می‌کند اجرای دوباره‌ی موتور، همان فرصت را دوباره نسازد؛
    فرصتِ موجود **تازه‌سازی** می‌شود و وضعیت انسانی‌اش (پذیرفته/رد شده)
    بازنویسی نمی‌شود.
    """

    __tablename__ = "opportunities"
    __table_args__ = (
        UniqueConstraint("business_id", "dedupe_key"),
        Index("ix_opportunities_business_status", "business_id", "status"),
        Index("ix_opportunities_business_score", "business_id", "score_rial"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), index=True)
    dedupe_key: Mapped[str] = mapped_column(String(128), index=True)

    customer_id: Mapped[int | None] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), index=True
    )
    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("products.id", ondelete="SET NULL"), index=True
    )
    kind: Mapped[str] = mapped_column(String(64), index=True)
    generator: Mapped[str] = mapped_column(String(64))
    generator_version: Mapped[int] = mapped_column(Integer, default=1)

    title_fa: Mapped[str] = mapped_column(String(255))
    action_fa: Mapped[str] = mapped_column(Text)
    reason_fa: Mapped[str] = mapped_column(Text)
    message_fa: Mapped[str | None] = mapped_column(Text)

    # ارزشِ مورد انتظار، **درآمدی** — نه سود. نام فیلد عمداً «سود» نیست.
    expected_value_rial: Mapped[int] = mapped_column(BigInteger, default=0)
    # همان عدد است که برای رتبه‌بندی به‌کار می‌رود؛ جدا نگه داشته می‌شود تا
    # تغییر فرمول رتبه‌بندی، ارزشِ گزارش‌شده را دستکاری نکند.
    score_rial: Mapped[int] = mapped_column(BigInteger, default=0, index=True)
    value_kind: Mapped[str] = mapped_column(String(32))  # ارزش فرصت / ارزش در معرض خطر
    probability_bp: Mapped[int | None] = mapped_column(Integer)
    confidence: Mapped[str | None] = mapped_column(String(32))

    # علّیت: این‌ها تا وجود شواهد آزمایشی **NULL می‌مانند**. پرکردنشان با عدد
    # مشاهده‌ای یعنی ادعای اثر بدون آزمایش.
    attributed_revenue_rial: Mapped[int | None] = mapped_column(BigInteger)
    incremental_revenue_rial: Mapped[int | None] = mapped_column(BigInteger)
    experiment_id: Mapped[str | None] = mapped_column(String(64))

    # open / accepted / dismissed / snoozed / done / expired / superseded
    status: Mapped[str] = mapped_column(String(32), default="open", index=True)
    status_reason_fa: Mapped[str | None] = mapped_column(Text)
    assigned_to: Mapped[str | None] = mapped_column(String(255), index=True)
    owner_hint: Mapped[str | None] = mapped_column(String(255))
    snooze_until: Mapped[str | None] = mapped_column(String(10))
    due_date: Mapped[str | None] = mapped_column(String(10), index=True)
    expires_at: Mapped[str | None] = mapped_column(String(10), index=True)

    first_seen_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("opportunity_runs.id", ondelete="SET NULL")
    )
    last_seen_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("opportunity_runs.id", ondelete="SET NULL")
    )
    seen_count: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[float] = mapped_column(Float, default=now_ts, index=True)
    updated_at: Mapped[float] = mapped_column(Float, default=now_ts)


class OpportunityFactor(Base):
    """شواهد یک فرصت — چرا ساخته شد و از کدام فیلترها گذشت.

    قاعده‌ی «هر فرصت شواهد دارد» اینجا اجرا می‌شود: فیلترهایی که به دلیل نبود
    داده کاری نمی‌کنند (موجودی، حاشیه) هم **صریح** ثبت می‌شوند، تا کسی گمان
    نکند بررسی شده‌اند.
    """

    __tablename__ = "opportunity_factors"
    __table_args__ = (
        UniqueConstraint("opportunity_id", "code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    opportunity_id: Mapped[int] = mapped_column(
        ForeignKey("opportunities.id", ondelete="CASCADE"), index=True
    )
    code: Mapped[str] = mapped_column(String(64))
    label_fa: Mapped[str] = mapped_column(String(255))
    # evidence / filter_pass / filter_skip / filter_block
    outcome: Mapped[str] = mapped_column(String(32))
    detail_fa: Mapped[str | None] = mapped_column(Text)
    value_text: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[float] = mapped_column(Float, default=now_ts)


class OpportunityEvent(Base):
    """رخدادهای چرخه‌ی حیات — فقط افزودنی (append-only).

    وضعیتِ جاری روی خود فرصت است؛ این جدول «چه کسی، کِی، چه کرد» را نگه می‌دارد
    که برای ممیزی و برای سنجش اثر لازم است.
    """

    __tablename__ = "opportunity_events"
    __table_args__ = (
        Index("ix_opportunity_events_opportunity_created", "opportunity_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    opportunity_id: Mapped[int] = mapped_column(
        ForeignKey("opportunities.id", ondelete="CASCADE"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(32))
    from_status: Mapped[str | None] = mapped_column(String(32))
    to_status: Mapped[str | None] = mapped_column(String(32))
    actor: Mapped[str | None] = mapped_column(String(255))
    note_fa: Mapped[str | None] = mapped_column(Text)
    payload_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[float] = mapped_column(Float, default=now_ts, index=True)


class UpliftSnapshot(Base):
    """عکسِ جدولِ اثرِ آموخته‌شده در یک لحظه — به‌جای رجیستری کاملِ مدل.

    سند §۲۹ رجیستری با promotion/rollback/drift می‌خواهد. برای این دامنه، نسخه‌ی
    متناسب همین است: هر بار که اثر محاسبه می‌شود یک عکس ثبت می‌شود. نتیجه:

    * **بازتولیدپذیری**: «چرا این فرصت آن روز صدر فهرست بود؟» پاسخ دارد.
    * **drift**: تغییر اثرِ یک گروه در طول زمان با مقایسه‌ی عکس‌ها دیده می‌شود.
    * **rollback**: استفاده از عکس قبلی، بدون تغییر کد.

    رجیستری کاملِ ML (ثبت وزن‌ها، محیط، وابستگی‌ها) برای یک تخمینِ نسبتِ ساده
    سربار است و ساخته نشده.
    """

    __tablename__ = "uplift_snapshots"
    __table_args__ = (
        UniqueConstraint("business_id", "as_of_date", "cell_kind", "cell_state"),
        Index("ix_uplift_snapshots_business_asof", "business_id", "as_of_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), index=True)
    as_of_date: Mapped[str] = mapped_column(String(10), index=True)
    # سلول: نوع اقدام × حالت چرخه‌ی عمر. ردیفِ جمعیِ هر نوع با state='*' و
    # ردیفِ کل با kind='*' ذخیره می‌شود تا سلسله‌مراتب کامل بازتولید شود.
    cell_kind: Mapped[str] = mapped_column(String(64))
    cell_state: Mapped[str] = mapped_column(String(64))

    n_treatment: Mapped[int] = mapped_column(Integer, default=0)
    n_control: Mapped[int] = mapped_column(Integer, default=0)
    conv_treatment: Mapped[int] = mapped_column(Integer, default=0)
    conv_control: Mapped[int] = mapped_column(Integer, default=0)
    # نسبت‌ها در basis point صحیح — قاعده‌ی «بدون float در دفتر کل»
    raw_uplift_bp: Mapped[int | None] = mapped_column(Integer)
    uplift_bp: Mapped[int | None] = mapped_column(Integer)
    ci_low_bp: Mapped[int | None] = mapped_column(Integer)
    ci_high_bp: Mapped[int | None] = mapped_column(Integer)
    basis: Mapped[str] = mapped_column(String(16))
    is_useless: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[float] = mapped_column(Float, default=now_ts, index=True)


# ------------------------------------------------------------------ کمپین


class Campaign(Base):
    """یک کمپین = یک آزمایش.

    تفاوت بنیادی با «فهرست تماس»: کمپین از روز اول گروه کنترل دارد. بدون آن،
    هر عددی که بعداً گزارش شود فقط می‌گوید «این مشتریان خرید کردند» — نه
    «به‌خاطر تماس ما خرید کردند». آن دو یکی نیستند و خلط‌کردنشان بودجه را
    به سمت کارهای بی‌اثر می‌برد.
    """

    __tablename__ = "campaigns"
    __table_args__ = (
        Index("ix_campaigns_business_created", "business_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str | None] = mapped_column(String(64))
    # draft / running / closed
    status: Mapped[str] = mapped_column(String(32), default="running", index=True)
    # درصد گروه کنترل. صفر یعنی «فقط انتساب، بدون ادعای اثر».
    holdout_pct: Mapped[int] = mapped_column(Integer, default=10)
    primary_metric: Mapped[str] = mapped_column(String(64), default="revenue")
    analysis_window_days: Mapped[int] = mapped_column(Integer, default=30)
    created_at: Mapped[float] = mapped_column(Float, default=now_ts, index=True)
    exported_at: Mapped[float | None] = mapped_column(Float)
    closed_at: Mapped[float | None] = mapped_column(Float)
    notes_json: Mapped[str | None] = mapped_column(Text)


class CampaignMember(Base):
    """عضویت یک مشتری در یک کمپین، با بازوی تصادفی‌شده‌اش.

    واحد تصادفی‌سازی **مشتری** است نه پیام (§۲۲.۱): اگر یک مشتری هم‌زمان در
    گروه آزمایش یک فرصت و گروه کنترل فرصت دیگری باشد، اندازه‌گیری آلوده
    می‌شود و هیچ‌کدام از دو عدد معنا ندارند.
    """

    __tablename__ = "campaign_members"
    __table_args__ = (
        UniqueConstraint("campaign_id", "customer_id"),
        # نام باید با ایندکسِ خودکارِ ستون `arm` فرق کند، وگرنه دو ایندکس
        # هم‌نام ساخته می‌شود و مهاجرت روی نصب‌های موجود می‌شکند.
        Index("ix_campaign_members_campaign_arm", "campaign_id", "arm"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE"), index=True
    )
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), index=True
    )
    # treatment | control — ایندکسِ مرکبِ بالا این ستون را پوشش می‌دهد
    arm: Mapped[str] = mapped_column(String(16))
    # طبقه‌ای که تصادفی‌سازی درونش انجام شده (سگمنت/حالت) — برای ممیزی توازن
    stratum: Mapped[str | None] = mapped_column(String(64))
    assigned_at: Mapped[float] = mapped_column(Float, default=now_ts)
    assigned_date: Mapped[str] = mapped_column(String(10), index=True)
    # لحظه‌ی تماس. تا وقتی NULL باشد، این عضو هنوز در معرض قرار نگرفته است.
    exposure_at: Mapped[float | None] = mapped_column(Float)
    exposure_date: Mapped[str | None] = mapped_column(String(10), index=True)
    exposure_channel: Mapped[str | None] = mapped_column(String(32))
    # جمعِ ارزش فرصت‌های این مشتری در این کمپین (برای گزارش، نه برای سنجش اثر)
    expected_value_rial: Mapped[int | None] = mapped_column(BigInteger)


class CampaignOpportunity(Base):
    """پیوند عضو کمپین با فرصت‌هایی که باعث انتخابش شدند."""

    __tablename__ = "campaign_opportunities"
    __table_args__ = (
        UniqueConstraint("campaign_id", "opportunity_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE"), index=True
    )
    opportunity_id: Mapped[int] = mapped_column(
        ForeignKey("opportunities.id", ondelete="CASCADE"), index=True
    )
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[float] = mapped_column(Float, default=now_ts)


class CampaignOutcome(Base):
    """آنچه در پنجره‌ی سنجش واقعاً اتفاق افتاد — عکسِ ماندگار.

    محاسبه‌ی درجا هم ممکن بود، ولی عکس‌گرفتن یعنی گزارشِ امروز و شش ماه بعد
    یکی است، حتی اگر داده‌ی تازه‌ای اضافه شود.
    """

    __tablename__ = "campaign_outcomes"
    __table_args__ = (
        UniqueConstraint("campaign_id", "customer_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE"), index=True
    )
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), index=True
    )
    arm: Mapped[str] = mapped_column(String(16), index=True)
    window_start: Mapped[str] = mapped_column(String(10))
    window_end: Mapped[str] = mapped_column(String(10))
    orders_count: Mapped[int] = mapped_column(Integer, default=0)
    lines_count: Mapped[int] = mapped_column(Integer, default=0)
    revenue_rial: Mapped[int] = mapped_column(BigInteger, default=0)
    # بهای خطوطِ همین پنجره. `NULL` یعنی پوشش کامل نبود — نه اینکه بها صفر بوده.
    cost_rial: Mapped[int | None] = mapped_column(BigInteger)
    # چند خط از چند خط بها داشتند؛ مبنای تصمیمِ «سود را گزارش کنیم یا نه»
    lines_with_cost: Mapped[int] = mapped_column(Integer, default=0)
    # آیا دقیقاً همان کالایی که پیشنهاد شده بود خریداری شد؟
    matched_product: Mapped[bool] = mapped_column(Boolean, default=False)
    # آخرین بارگذاری‌ای که این عکس از آن ساخته شد
    source_batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("import_batches.id", ondelete="SET NULL")
    )
    computed_at: Mapped[float] = mapped_column(Float, default=now_ts)


class CampaignSend(Base):
    """هر پیامی که برای یک کمپین فرستاده شد — دفترِ ارسال.

    چرا جدولِ تازه و نه ستون روی `outbox` قدیمی: `outbox` جدولِ legacy است و
    قرارداد صفر-رگرسیون دست‌زدن به آن را ممنوع کرده. ضمناً این دفتر چیزهایی
    نگه می‌دارد که آن‌جا جا ندارند: قطعه‌شماری، هزینه‌ی ریالی، شناسه‌ی پیام نزد
    پنل، و وضعیت تحویل.

    وجود این جدول یک سنجه‌ی مسدود را باز می‌کند: **هزینه به‌ازای سفارش افزوده**.
    تا پیش از این، هزینه‌ی تماس هیچ‌جا ثبت نمی‌شد.

    `provider_message_id` شناسه‌ای است که پنل هنگام پذیرش پیام برمی‌گرداند و از
    پاسخِ ارسال استخراج می‌شود. وقتی webhook تحویلِ پنل وصل شود، همین شناسه تنها
    راهِ وصل‌کردنِ callback به ردیفِ درست است — بدون آن، وضعیت تحویل قابل نسبت‌دادن
    نیست. ارسال آزمایشی شناسه ندارد و `NULL` می‌ماند.
    """

    __tablename__ = "campaign_sends"
    __table_args__ = (
        # یک پیام به هر عضو در هر کمپین — گاردِ ارسالِ دوباره در سطح دیتابیس
        UniqueConstraint("campaign_id", "customer_id"),
        Index("ix_campaign_sends_campaign_status", "campaign_id", "status"),
    )

    STATUS_SENT = "sent"
    STATUS_FAILED = "failed"
    STATUS_SKIPPED = "skipped"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), index=True)
    campaign_id: Mapped[int] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE"), index=True
    )
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), index=True
    )
    phone_e164: Mapped[str | None] = mapped_column(String(20))
    message_text: Mapped[str | None] = mapped_column(Text)
    segments: Mapped[int] = mapped_column(Integer, default=0)
    cost_rial: Mapped[int] = mapped_column(BigInteger, default=0)
    provider: Mapped[str] = mapped_column(String(32), default="dry-run")
    # ارسالِ آزمایشی هم ثبت می‌شود، ولی با این پرچم از ارسالِ واقعی جدا می‌ماند
    dry_run: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(32), default=STATUS_SENT, index=True)
    status_detail_fa: Mapped[str | None] = mapped_column(Text)
    provider_message_id: Mapped[str | None] = mapped_column(String(128))
    sent_at: Mapped[float] = mapped_column(Float, default=now_ts, index=True)


class ProductCostHistory(Base):
    """بهای هر کالا در طول زمان — منبعِ محاسبه‌ی سود ناخالص.

    **چرا جدولِ جدا و نه یک ستون روی `products`.** §۳.۴ سند صریح است: بهای هر
    معامله باید بهای **زمانِ همان معامله** باشد، نه آخرین قیمت خرید. یک ستونِ
    اسکالر روی کالا فقط «امروز» را می‌داند و سودِ سالِ گذشته را با قیمتِ امروز
    حساب می‌کند — که در تورم، عددِ کاملاً غلط می‌دهد.

    **چرا نامش `supplier_cost_history` نیست.** سند (§۷.۵) این نام را با بُعدِ
    تأمین‌کننده و tier مقدار و کرایه می‌خواهد. داده‌ی تأمین‌کننده در دست نیست، پس
    نامی که آن را وعده بدهد گمراه‌کننده است. همان قاعده‌ی پروژه که
    `value_at_risk_rial` را «درآمدمحور» نامید تا کسی سود نپندارد.

    `effective_to` خالی یعنی «تا اطلاع ثانوی معتبر است». بازه‌ها برای یک کالا
    نباید هم‌پوشانی داشته باشند؛ ورودِ تازه بازه‌ی قبلی را می‌بندد.
    """

    __tablename__ = "product_cost_history"
    __table_args__ = (
        UniqueConstraint("business_id", "product_id", "effective_from"),
        Index("ix_product_cost_lookup", "business_id", "product_id", "effective_from"),
    )

    SOURCE_FILE = "file"
    SOURCE_MANUAL = "manual"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), index=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), index=True
    )
    # بهای **یک واحد**، نه کل خط — تا با هر مقداری قابل ضرب باشد
    unit_cost_rial: Mapped[int] = mapped_column(BigInteger)
    effective_from: Mapped[str] = mapped_column(String(10), index=True)
    effective_to: Mapped[str | None] = mapped_column(String(10))
    source: Mapped[str] = mapped_column(String(16), default=SOURCE_FILE)
    note_fa: Mapped[str | None] = mapped_column(Text)
    raw_product_name: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[float] = mapped_column(Float, default=now_ts)


class AppSetting(Base):
    """تنظیمِ سیاست که **کاربر** می‌گذارد، نه سیستم حدس می‌زند.

    چرا جدول و نه متغیر محیطی: کف حاشیه یک عددِ کسب‌وکاری است که ممکن است
    ماهانه عوض شود؛ متغیر محیطی یعنی راه‌اندازی دوباره‌ی سرور برای هر تغییر، و
    یعنی هیچ ردی از «چه‌کسی چه‌زمانی عوضش کرد» باقی نمی‌ماند.

    چرا کلید/مقدارِ عمومی و نه ستونِ اختصاصی: تنظیم‌های سیاست کم‌اند ولی
    یکی‌یکی اضافه می‌شوند؛ ستونِ تازه یعنی مهاجرت تازه برای هر عدد. مقدار
    به‌صورت متن ذخیره می‌شود و لایه‌ی بالاتر تفسیرش می‌کند — هیچ تفسیرِ ضمنی
    اینجا انجام نمی‌شود.
    """

    __tablename__ = "app_settings"
    __table_args__ = (UniqueConstraint("business_id", "key"),)

    # کف حاشیه‌ی سود به پایه‌ی هزارم (۲۰۰۰ = ۲۰٪). نبودنش یعنی «کاربر تعیین
    # نکرده» و آن‌وقت `filter_margin_floor` صادقانه «بررسی نشد» ثبت می‌کند.
    KEY_MARGIN_FLOOR_BP = "margin_floor_bp"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), index=True)
    key: Mapped[str] = mapped_column(String(64), index=True)
    value_text: Mapped[str] = mapped_column(Text)
    note_fa: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[float] = mapped_column(Float, default=now_ts)


class ContactSuppression(Base):
    """دفترِ «با این مشتری تماس نگیر».

    چرا جدول جدا و نه یک ستون بولی روی `customers`:

    * انصراف به **چه کسی، چه زمانی، با چه دلیلی، از کجا** نیاز دارد. یک بولی
      هیچ‌کدام را نمی‌دهد و بعداً «چرا به او پیام ندادیم؟» بی‌پاسخ می‌ماند.
    * ردیف‌های `customers` را حل هویت می‌سازد و به‌روز می‌کند؛ انصراف باید از
      بارگذاری دوباره و ادغام هویت جان سالم ببرد.
    * بازگردانی (`revoked_at`) باید ثبت شود، نه اینکه ردیف پاک شود.

    **هم `customer_id` و هم `phone_e164`**، دست‌کم یکی: لیست سیاهِ پنل پیامکی و
    پاسخ «لغو ۱۱» فقط شماره می‌شناسند، ولی دروازه باید پیش از حل هویت هم کار کند.

    `scope` یعنی انصراف از چه چیزی: `"all"` همه‌ی تماس‌ها، یا یک نوع اقدام خاص.
    """

    __tablename__ = "contact_suppressions"
    __table_args__ = (
        UniqueConstraint("business_id", "customer_id", "scope"),
        UniqueConstraint("business_id", "phone_e164", "scope"),
    )

    SCOPE_ALL = "all"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), index=True)
    customer_id: Mapped[int | None] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), index=True
    )
    phone_e164: Mapped[str | None] = mapped_column(String(20), index=True)
    scope: Mapped[str] = mapped_column(String(64), default=SCOPE_ALL)
    # از کجا آمد: دستیِ کاربر، همگام‌سازی با پنل، یا ستون فایل ورودی
    source: Mapped[str] = mapped_column(String(32), default="manual")
    reason_code: Mapped[str | None] = mapped_column(String(64))
    reason_fa: Mapped[str | None] = mapped_column(Text)
    opted_out_at: Mapped[float] = mapped_column(Float, default=now_ts)
    # پرشده یعنی انصراف پس گرفته شده؛ ردیف پاک نمی‌شود تا تاریخ بماند
    revoked_at: Mapped[float | None] = mapped_column(Float)
    created_by: Mapped[str | None] = mapped_column(String(128))
    updated_at: Mapped[float] = mapped_column(Float, default=now_ts)

    @property
    def is_active(self) -> bool:
        return self.opted_out_at is not None and self.revoked_at is None


__all__ = [
    "AppSetting",
    "Business",
    "Campaign",
    "CampaignMember",
    "CampaignOpportunity",
    "CampaignOutcome",
    "CampaignSend",
    "ContactSuppression",
    "Customer",
    "CustomerFeature",
    "CustomerKey",
    "CustomerLifecycleEvent",
    "ImportBatch",
    "ImportReconciliation",
    "Opportunity",
    "OpportunityEvent",
    "OpportunityFactor",
    "OpportunityRun",
    "Order",
    "OrderLine",
    "Product",
    "ProductAlias",
    "ProductCostHistory",
    "UpliftSnapshot",
]
