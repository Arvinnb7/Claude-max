"""نوشتن یک بارگذاری در دفتر کل canonical — idempotent و آشتی‌پذیر.

این ماژول تنها نویسنده‌ی جداول فروش است. سه ضمانت می‌دهد:

1. **Idempotency**: کلید هر خط `sha256(business|dataset|sheet|source_row)` است.
   `source_row` از قبل در فریم تمیز وجود دارد و از تعریف «تکراری» مستثناست، پس
   تحلیل دوباره‌ی همان فایل جمع‌ها را دو برابر نمی‌کند؛ تصحیح نگاشت ستون هم
   مقدارِ همان خط را به‌روز می‌کند، نه اینکه خط تازه بسازد.
2. **کاملیت دفتر**: هم خرید و هم **برگشت از فروش** نوشته می‌شوند
   (`is_return`). فروش خالص = جمع همه‌ی خطوط، پس دفتر با KPI آشتی می‌دهد و
   برگشت‌ها بی‌صدا گم نمی‌شوند.
3. **آشتی اثبات‌پذیر**: بعد از نوشتن، جمع‌ها و شمارش‌ها با آنچه تحلیل گفته
   مقایسه و در `import_reconciliation` ثبت می‌شود.

نوشتن هرگز فریم ورودی را تغییر نمی‌دهد و هرگز روی مسیر تحلیل اثر نمی‌گذارد.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd
from sqlalchemy import case, func, insert, select, update

from mktcore.catalog import normalize_product_name, parse_pack_size
from mktcore.identity import normalize_phone
from mktcore.ingest.currency import rial_per_unit
from mktcore.ingest.schema import SOURCE_ROW
from mktcore.locale_fa import normalize_digits
from mktcore.money import to_basis_points, to_quantity_milli, to_rial_int

from .base import now_ts
from .engine import session_scope, write_lock
from .migrations import ensure_schema
from .models import (
    Business,
    Customer,
    CustomerKey,
    ImportBatch,
    ImportQuarantine,
    ImportReconciliation,
    ImportRowRaw,
    Order,
    OrderLine,
    Product,
    ProductAlias,
)

if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.orm import Session

logger = logging.getLogger("mktcore.db.repo_import")

DEFAULT_BUSINESS_SLUG = "default"
# داده‌ی نمونه در کسب‌وکارِ جدا می‌نشیند، وگرنه مشتریانِ مصنوعی برای همیشه با
# مشتریانِ واقعی در یک صندوق فرصت، یک جدول اثر و یک استخر کمپین قاطی می‌شوند —
# و هیچ راهِ درون‌برنامه‌ای برای جداکردنشان وجود ندارد.
SAMPLE_BUSINESS_SLUG = "sample"
# اندازه‌ی تکه‌ی درج. بزرگ‌تر یعنی تراکنش طولانی‌تر و قفل بیشتر؛ کوچک‌تر یعنی
# round-trip بیشتر. ۵۰۰۰ روی فایل‌های ۴۰۰ هزار ردیفی آزموده شده است.
CHUNK = 5000

# تلرانس آشتی — مستند در FINANCIAL_CALCULATION_RULES.md
TOLERANCE_PER_LINE_RIAL = 1


@dataclass
class ReconcileCheck:
    check_id: str
    label_fa: str
    expected: float | int | None
    actual: float | int | None
    tolerance: float
    status: str  # OK / WARN / MISMATCH
    detail_fa: str | None = None


@dataclass
class ImportWriteResult:
    """نتیجه‌ی نوشتن، برای نمایش در پاسخ job و ثبت در لاگ."""

    batch_id: int
    business_id: int
    dataset_key: str
    revision: int
    lines_inserted: int
    lines_updated: int
    customers_created: int
    products_created: int
    orders_written: int
    reconcile_status: str
    checks: list[ReconcileCheck] = field(default_factory=list)
    # §۸.۵ — `False` یعنی دسته ثبت شد ولی هیچ خطی به دفتر کل نرفت؛ دلیلش در
    # `blocked_by` است و همان در `ImportBatch.notes_json` هم می‌ماند.
    posted: bool = True
    blocked_by: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "batch_id": self.batch_id,
            "posted": self.posted,
            "blocked_by": list(self.blocked_by),
            "business_id": self.business_id,
            "dataset_key": self.dataset_key,
            "revision": self.revision,
            "lines_inserted": self.lines_inserted,
            "lines_updated": self.lines_updated,
            "customers_created": self.customers_created,
            "products_created": self.products_created,
            "orders_written": self.orders_written,
            "reconcile_status": self.reconcile_status,
            "checks": [
                {
                    "id": c.check_id,
                    "label": c.label_fa,
                    "expected": c.expected,
                    "actual": c.actual,
                    "tolerance": c.tolerance,
                    "status": c.status,
                    "detail": c.detail_fa,
                }
                for c in self.checks
            ],
        }


# ------------------------------------------------------------------ کلیدها
def frame_dataset_key(df: pd.DataFrame) -> str:
    """کلید دسته وقتی بایت فایل در دسترس نیست (مثلاً مسیر «داده‌ی نمونه»).

    از محتوای شناسه‌ای فریم ساخته می‌شود، نه از زمان؛ پس همان داده همان کلید را
    می‌گیرد و تحلیل دوباره‌اش دسته‌ی جدید نمی‌سازد.
    """
    hasher = hashlib.sha256()
    hasher.update(str(sorted(map(str, df.columns))).encode("utf-8"))
    hasher.update(str(len(df)).encode("utf-8"))
    for col in ("date", "revenue", "customer_id", "order_id", "product"):
        if col in df.columns:
            hasher.update(pd.util.hash_pandas_object(df[col], index=False).values.tobytes())
    return hasher.hexdigest()


def line_uid(business_id: int, dataset_key: str, sheet: str, source_row: object) -> str:
    """هویتِ خطِ **بی‌شماره‌فاکتور**: فقط با همان فایل و همان ردیف یکی است."""
    raw = f"{business_id}|{dataset_key}|{sheet}|{source_row}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


LINE_IDENTITY_VERSION = "v3"


def normalize_order_key(raw: object) -> str | None:
    """شماره‌ی فاکتور به شکلِ قطعی: ارقامِ لاتین، بدون فاصله‌ی اضافه، بدون «.0»ِ اکسل.

    همان شماره در دو صادرات می‌تواند «۱۲۳۴»، «1234» یا «1234.0» بیاید؛ اگر کلیدِ
    هویت روی رشته‌ی خام بنشیند، همان فاکتور دوبار شمرده می‌شود.
    """
    text = _text_or_none(raw)
    if text is None:
        return None
    text = normalize_digits(text)
    text = re.sub(r"\s+", " ", text).strip()
    if re.fullmatch(r"\d+\.0+", text):
        text = text.split(".", 1)[0]
    return text or None


def line_uid_for_order(
    business_id: int, order_key: str, product_norm: str, is_return: bool, ordinal: int,
    *, period: str = "",
) -> str:
    """هویتِ پایدارِ خطِ فاکتور (§۸.۴ لایه‌های ۲–۴).

    کلید = کسب‌وکار + دوره (سالِ تاریخِ خط) + شماره‌ی فاکتورِ نرمال‌شده + کالای
    نرمال‌شده + نوع (فروش/برگشت) + ترتیبِ خط در همین گروه. **مبلغ و مقدار عمداً
    در کلید نیستند**: صادراتِ دوباره‌ی همان دوره با یک مبلغِ اصلاح‌شده باید همان
    خط را به‌روز کند، نه اینکه خطِ تازه بسازد و قدیمی را کنارش بگذارد. «دوره»
    برای ERPهایی است که شماره‌ی فاکتور را هر سال از نو شروع می‌کنند: فاکتورِ ۱۲
    امسال نباید روی فاکتورِ ۱۲ پارسال بنویسد.
    """
    raw = (
        f"{LINE_IDENTITY_VERSION}|{business_id}|o|{period}|{order_key}|{product_norm}"
        f"|{int(bool(is_return))}|{ordinal}"
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def identity_period(iso_date: str | None) -> str:
    """دوره‌ی هویتِ خط: سالِ میلادیِ تاریخِ خط (ISO). بدون تاریخ، خالی."""
    return (iso_date or "")[:4]


def order_header_key(period: str, order_number: str) -> str:
    """کلیدِ یکتای سرِ فاکتور: «دوره/شماره» — همان دوره‌ای که خطِ فاکتور دارد."""
    return f"{period}/{order_number}"


# ------------------------------------------------------------- کمکی‌های داده
def _text_or_none(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    text = str(value).strip()
    return text or None


def _iso_date(value: object) -> str | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    try:
        stamp = pd.Timestamp(value)
    except (ValueError, TypeError):
        return None
    if pd.isna(stamp):
        return None
    return stamp.date().isoformat()


def _combined_frame(clean: pd.DataFrame) -> pd.DataFrame:
    """خرید + برگشت در یک فریم، با ستون `__is_return`.

    برگشت‌ها در `attrs` نگه داشته می‌شوند تا تحلیل آن‌ها را با درآمد مثبت قاطی
    نکند؛ ولی **دفتر کل** باید هر دو را داشته باشد وگرنه فروش خالصِ دفتر با KPI
    نمی‌خواند.
    """
    from mktcore.ingest.cleaning import get_returns

    purchases = clean.copy()
    purchases["__is_return"] = False
    returns = get_returns(clean)
    if len(returns):
        ret = pd.DataFrame(returns).copy()
        ret["__is_return"] = True
        common = [c for c in purchases.columns if c in ret.columns]
        combined = pd.concat([purchases[common], ret[common]], ignore_index=True)
    else:
        combined = purchases
    return combined


# --------------------------------------------------------------- کسب‌وکار
def _get_or_create_business(session: Session, slug: str, display_currency: str) -> Business:
    business = session.scalar(select(Business).where(Business.slug == slug))
    if business is None:
        business = Business(slug=slug, name=slug, display_currency=display_currency)
        session.add(business)
        session.flush()
        logger.info("کسب‌وکار «%s» ساخته شد (id=%s)", slug, business.id)
    return business


# ------------------------------------------------------------- حل هویت مشتری
def _resolve_customers(
    session: Session, business_id: int, frame: pd.DataFrame,
) -> tuple[dict[str, int], int]:
    """کلید خام مشتری → شناسه‌ی پایدار. فقط تطبیق قطعی.

    ترتیب: موبایل نرمال‌شده (قوی‌ترین شاهد) و سپس کلید خامِ فایل. تطبیق فازیِ
    نام عمداً انجام نمی‌شود؛ ادغام غلط دو مشتری واقعی برگشت‌ناپذیرتر از
    نپیوستن است.
    """
    if "customer_id" not in frame.columns:
        return {}, 0

    profile: dict[str, dict[str, Any]] = {}
    phone_series = frame["phone"] if "phone" in frame.columns else None
    email_series = frame["email"] if "email" in frame.columns else None
    date_series = frame["date"] if "date" in frame.columns else None

    for pos, raw in enumerate(frame["customer_id"].to_numpy()):
        key = _text_or_none(raw)
        if key is None:
            continue
        entry = profile.setdefault(key, {"phone": None, "email": None,
                                         "first": None, "last": None})
        if entry["phone"] is None and phone_series is not None:
            entry["phone"] = normalize_phone(phone_series.iat[pos])
        if entry["email"] is None and email_series is not None:
            email = _text_or_none(email_series.iat[pos])
            entry["email"] = email.lower() if email else None
        if date_series is not None:
            iso = _iso_date(date_series.iat[pos])
            if iso:
                entry["first"] = iso if entry["first"] is None else min(entry["first"], iso)
                entry["last"] = iso if entry["last"] is None else max(entry["last"], iso)

    if not profile:
        return {}, 0

    # کلیدهای موجود را یک‌جا می‌خوانیم (نه یک query به‌ازای مشتری)
    wanted_values = set(profile)
    wanted_values |= {v["phone"] for v in profile.values() if v["phone"]}
    existing: dict[tuple[str, str], int] = {}
    values = sorted(wanted_values)
    for start in range(0, len(values), CHUNK):
        rows = session.execute(
            select(CustomerKey.key_type, CustomerKey.key_value, CustomerKey.customer_id)
            .where(
                CustomerKey.business_id == business_id,
                CustomerKey.key_value.in_(values[start:start + CHUNK]),
            )
        ).all()
        for key_type, key_value, customer_id in rows:
            existing[(key_type, key_value)] = customer_id

    mapping: dict[str, int] = {}
    created = 0
    for raw_key, info in profile.items():
        phone = info["phone"]
        customer_id = None
        if phone:
            customer_id = existing.get(("phone", phone))
        if customer_id is None:
            customer_id = existing.get(("raw_key", raw_key))

        if customer_id is None:
            customer = Customer(
                business_id=business_id,
                canonical_key=raw_key,
                display_name=raw_key,
                phone_e164=phone,
                email=info["email"],
                first_order_date=info["first"],
                last_order_date=info["last"],
                resolution_method="phone" if phone else "raw_key",
            )
            session.add(customer)
            session.flush()
            customer_id = customer.id
            created += 1
        else:
            customer = session.get(Customer, customer_id)
            if customer is not None:
                if phone and not customer.phone_e164:
                    customer.phone_e164 = phone
                if info["email"] and not customer.email:
                    customer.email = info["email"]
                if info["first"] and (customer.first_order_date is None
                                      or info["first"] < customer.first_order_date):
                    customer.first_order_date = info["first"]
                if info["last"] and (customer.last_order_date is None
                                     or info["last"] > customer.last_order_date):
                    customer.last_order_date = info["last"]

        for key_type, key_value in (("raw_key", raw_key), ("phone", phone)):
            if key_value and (key_type, key_value) not in existing:
                session.add(CustomerKey(
                    business_id=business_id, customer_id=customer_id,
                    key_type=key_type, key_value=key_value,
                ))
                existing[(key_type, key_value)] = customer_id

        mapping[raw_key] = customer_id

    session.flush()
    return mapping, created


# ----------------------------------------------------------- حل هویت محصول
def _resolve_products(
    session: Session, business_id: int, frame: pd.DataFrame,
) -> tuple[dict[str, int], int]:
    """نام خام محصول → شناسه‌ی پایدار، از راه نامِ نرمال‌شده (alias)."""
    if "product" not in frame.columns:
        return {}, 0

    raw_names: dict[str, str] = {}
    category_of: dict[str, str | None] = {}
    categories = frame["category"] if "category" in frame.columns else None
    for pos, raw in enumerate(frame["product"].to_numpy()):
        name = _text_or_none(raw)
        if name is None:
            continue
        norm = normalize_product_name(name)
        if not norm:
            continue
        raw_names.setdefault(norm, name)
        if categories is not None and norm not in category_of:
            category_of[norm] = _text_or_none(categories.iat[pos])

    if not raw_names:
        return {}, 0

    norms = sorted(raw_names)
    known: dict[str, int] = {}
    for start in range(0, len(norms), CHUNK):
        rows = session.execute(
            select(ProductAlias.alias_norm, ProductAlias.product_id).where(
                ProductAlias.business_id == business_id,
                ProductAlias.alias_norm.in_(norms[start:start + CHUNK]),
            )
        ).all()
        known.update(dict(rows))

    created = 0
    for norm in norms:
        if norm in known:
            continue
        display = raw_names[norm]
        size = parse_pack_size(display)
        product = Product(
            business_id=business_id,
            canonical_name=norm,
            display_name=display,
            category=category_of.get(norm),
            pack_size_milli=size.value_milli if size else None,
            pack_unit=size.unit if size else None,
        )
        session.add(product)
        session.flush()
        session.add(ProductAlias(
            business_id=business_id, product_id=product.id,
            alias_norm=norm, alias_raw=display,
        ))
        known[norm] = product.id
        created += 1

    session.flush()
    # کلید نگاشت **نام نرمال‌شده** است؛ نوشتن خط هم با همان کلید جستجو می‌کند.
    return {norm: known[norm] for norm in norms}, created


# ------------------------------------------------------------------- دسته
def _next_revision(session: Session, business_id: int, dataset_key: str) -> int:
    rows = session.execute(
        select(ImportBatch.revision).where(
            ImportBatch.business_id == business_id,
            ImportBatch.dataset_key == dataset_key,
        )
    ).all()
    return (max((r[0] for r in rows), default=0)) + 1


def _build_line_payloads(
    frame: pd.DataFrame,
    *,
    business_id: int,
    batch_id: int,
    dataset_key: str,
    sheet: str,
    revision: int,
    display_currency: str,
    discount_is_amount: bool,
    customer_ids: dict[str, int],
    product_ids: dict[str, int],
) -> list[dict]:
    """ساخت دیکشنری هر خط. همه‌ی تبدیل‌های پولی **فقط اینجا** انجام می‌شوند."""
    columns = set(frame.columns)

    def col(name: str) -> np.ndarray | None:
        return frame[name].to_numpy() if name in columns else None

    dates = col("date")
    revenues = col("revenue")
    quantities = col("quantity")
    unit_prices = col("unit_price")
    gross_amounts = col("gross_amount")
    discounts = col("discount")
    costs = col("cost")
    products = col("product")
    customers = col("customer_id")
    orders = col("order_id")
    branches = col("branch")
    salespeople = col("salesperson")
    channels = col("channel")
    regions = col("region")
    source_rows = col("source_row")
    is_returns = col("__is_return")

    payloads: list[dict] = []
    # ترتیبِ خط درونِ گروهِ (فاکتور، کالا، نوع) — به ترتیبِ ردیفِ فایل. دو خطِ
    # هم‌کالا در یک فاکتور با همین عدد از هم جدا می‌شوند.
    ordinals: dict[tuple[str, str, str, bool], int] = {}
    for i in range(len(frame)):
        iso = _iso_date(dates[i]) if dates is not None else None
        if iso is None:
            continue  # بدون تاریخ، خط در هیچ سری زمانی جا نمی‌گیرد
        revenue_rial = to_rial_int(revenues[i], display_currency) if revenues is not None else None
        if revenue_rial is None:
            continue  # خط بدون مبلغ در دفتر کل معنا ندارد
        cost_rial = to_rial_int(costs[i], display_currency) if costs is not None else None

        source_row = None
        if source_rows is not None and not pd.isna(source_rows[i]):
            source_row = int(source_rows[i])

        raw_customer = _text_or_none(customers[i]) if customers is not None else None
        raw_product = _text_or_none(products[i]) if products is not None else None
        product_norm = normalize_product_name(raw_product) if raw_product else None

        raw_order = normalize_order_key(orders[i]) if orders is not None else None
        is_return_flag = bool(is_returns[i]) if is_returns is not None else False
        period = identity_period(iso)
        if raw_order is not None:
            group = (period, raw_order, product_norm or "", is_return_flag)
            ordinal = ordinals.get(group, 0)
            ordinals[group] = ordinal + 1
            uid = line_uid_for_order(
                business_id, raw_order, product_norm or "", is_return_flag, ordinal,
                period=period,
            )
        else:
            uid = line_uid(business_id, dataset_key, sheet,
                           source_row if source_row is not None else f"i{i}")

        discount_rial = None
        discount_bp = None
        if discounts is not None:
            if discount_is_amount:
                discount_rial = to_rial_int(discounts[i], display_currency)
            else:
                discount_bp = to_basis_points(discounts[i])

        payloads.append({
            "line_uid": uid,
            "business_id": business_id,
            "batch_id": batch_id,
            # سرِ فاکتور دوره‌دار است: «دوره/شماره». شماره‌ی خام برای نمایش و
            # برای آشتیِ شمارِ سفارش (همان تعریفِ KPI که دوره نمی‌شناسد).
            "order_key": order_header_key(period, raw_order) if raw_order else "",
            "order_period": period,
            "order_number": raw_order or "",
            "has_order_key": raw_order is not None,
            "customer_id": customer_ids.get(raw_customer) if raw_customer else None,
            "product_id": product_ids.get(product_norm) if product_norm else None,
            "line_date": iso,
            "quantity_milli": (
                to_quantity_milli(quantities[i]) if quantities is not None else None
            ),
            "unit_price_rial": (
                to_rial_int(unit_prices[i], display_currency)
                if unit_prices is not None else None
            ),
            "revenue_rial": revenue_rial,
            "gross_amount_rial": (
                to_rial_int(gross_amounts[i], display_currency)
                if gross_amounts is not None else None
            ),
            "discount_rial": discount_rial,
            "discount_rate_bp": discount_bp,
            "cost_rial": cost_rial,
            "cost_confidence": "from_file" if cost_rial is not None else None,
            # سود همان‌جا که بها نوشته می‌شود حساب می‌شود، نه در گامی جدا —
            # وگرنه خطی که بها **دارد** بی‌سود می‌ماند تا کسی گام بعد را بزند.
            "gross_profit_rial": (
                None if cost_rial is None else int(revenue_rial) - int(cost_rial)
            ),
            "is_return": is_return_flag,
            "source_row": source_row,
            "sheet_name": sheet,
            "raw_customer_key": raw_customer,
            "raw_product_name": raw_product,
            "revision": revision,
            "branch": _text_or_none(branches[i]) if branches is not None else None,
            "salesperson": _text_or_none(salespeople[i]) if salespeople is not None else None,
            "channel": _text_or_none(channels[i]) if channels is not None else None,
            "region": _text_or_none(regions[i]) if regions is not None else None,
        })
    return payloads


_LINE_FIELDS = (
    "business_id", "batch_id", "customer_id", "product_id", "line_date",
    "quantity_milli", "unit_price_rial", "revenue_rial", "gross_amount_rial",
    "discount_rial", "discount_rate_bp", "cost_rial", "cost_confidence",
    "gross_profit_rial", "is_return",
    "source_row", "sheet_name", "raw_customer_key", "raw_product_name", "revision",
)


def _existing_line_ids(session: Session, uids: list[str]) -> dict[str, int]:
    return {
        uid: row_id
        for uid, row_id in session.execute(
            select(OrderLine.line_uid, OrderLine.id).where(OrderLine.line_uid.in_(uids))
        ).all()
    }


def _upsert_lines(session: Session, payloads: list[dict]) -> tuple[int, int]:
    """درج/به‌روزرسانی خطوط بر پایه‌ی `line_uid` — بدون وابستگی به دیالکت.

    عمداً از `ON CONFLICT` خاصِ SQLite استفاده نمی‌شود: همین کد باید روی
    Postgres هم بدون تغییر کار کند. تکه‌تکه بودن هم برای همین است — یک
    `IN (...)` با ۴۰۰ هزار عضو در هیچ دیتابیسی خوش‌رفتار نیست.
    """
    inserted = updated = 0
    for start in range(0, len(payloads), CHUNK):
        chunk = payloads[start:start + CHUNK]
        existing = _existing_line_ids(session, [p["line_uid"] for p in chunk])
        to_insert: list[dict] = []
        to_update: list[dict] = []
        for payload in chunk:
            row = {k: payload[k] for k in _LINE_FIELDS}
            row["updated_at"] = now_ts()
            if payload["line_uid"] in existing:
                row["id"] = existing[payload["line_uid"]]
                to_update.append(row)
            else:
                row["line_uid"] = payload["line_uid"]
                to_insert.append(row)
        if to_insert:
            session.execute(insert(OrderLine), to_insert)
            inserted += len(to_insert)
        if to_update:
            session.execute(update(OrderLine), to_update)
            updated += len(to_update)
        session.flush()
    return inserted, updated


def _overlap_with_other_uploads(
    session: Session, payloads: list[dict], *, dataset_key: str,
) -> int:
    """چند خطِ این فایل قبلاً از **فایلِ دیگری** وارد شده بود؟ (کنترل L08)

    این خطوط به‌روز می‌شوند نه دوبار شمرده؛ ولی عددش باید دیده شود تا کاربر
    بداند دو صادراتش هم‌پوشانی دارند.
    """
    uids = [p["line_uid"] for p in payloads if p["has_order_key"]]
    count = 0
    for start in range(0, len(uids), CHUNK):
        rows = session.execute(
            select(OrderLine.line_uid, ImportBatch.dataset_key)
            .join(ImportBatch, ImportBatch.id == OrderLine.batch_id)
            .where(OrderLine.line_uid.in_(uids[start:start + CHUNK]))
        ).all()
        count += sum(1 for _uid, key in rows if key != dataset_key)
    return count


def _recompute_order_headers(session: Session, order_ids: list[int]) -> None:
    """جمع‌ها و شمارِ خطوطِ سرِ فاکتور از **همه‌ی** خطوطِ وصل‌شده.

    وقتی خطوطِ یک فاکتور از چند بارگذاری می‌آیند، جمعِ «همین دسته» ناقص است؛
    سرِ فاکتور باید با آنچه واقعاً زیرش نشسته یکی باشد.
    """
    for start in range(0, len(order_ids), CHUNK):
        chunk = order_ids[start:start + CHUNK]
        rows = session.execute(
            select(
                OrderLine.order_id,
                func.sum(case((OrderLine.is_return.is_(False), OrderLine.revenue_rial), else_=0)),
                func.sum(case((OrderLine.is_return.is_(True), -OrderLine.revenue_rial), else_=0)),
                func.count(OrderLine.id),
                func.sum(OrderLine.discount_rial),
                func.count(OrderLine.discount_rial),
                func.min(OrderLine.line_date),
            )
            .where(OrderLine.order_id.in_(chunk))
            .group_by(OrderLine.order_id)
        ).all()
        updates = []
        for order_id, gross, returns, n_lines, discount, n_discount, first_date in rows:
            gross_i, returns_i = int(gross or 0), int(returns or 0)
            updates.append({
                "id": order_id,
                "gross_rial": gross_i,
                "returns_rial": returns_i,
                "net_rial": gross_i - returns_i,
                "line_count": int(n_lines or 0),
                "discount_rial": int(discount) if n_discount else None,
                "order_date": first_date,
                "updated_at": now_ts(),
            })
        if updates:
            session.execute(update(Order), updates)
    session.flush()


def _write_orders(
    session: Session, business_id: int, batch_id: int, payloads: list[dict],
) -> int:
    """ساخت/به‌روزرسانی سرِ فاکتور از جمع خطوط، سپس اتصال خطوط به آن.

    وقتی فایل ستون شماره‌ی فاکتور ندارد، سرِ فاکتور ساخته **نمی‌شود**: هر خط یک
    «فاکتور» جعلی می‌شد که نه اطلاعاتی اضافه می‌کند نه درست است. تحلیل هم در آن
    حالت هر خط را یک سفارش می‌شمارد، پس چیزی از دست نمی‌رود.
    """
    real_orders = [p for p in payloads if p["has_order_key"]]
    if not real_orders:
        return 0

    grouped: dict[str, dict[str, Any]] = {}
    for payload in real_orders:
        agg = grouped.setdefault(payload["order_key"], {
            "gross": 0, "returns": 0, "lines": 0, "date": payload["line_date"],
            "customer_id": payload["customer_id"], "branch": payload["branch"],
            "salesperson": payload["salesperson"], "channel": payload["channel"],
            "region": payload["region"], "discount": 0, "has_discount": False,
            "period": payload["order_period"], "number": payload["order_number"],
        })
        if payload["is_return"]:
            agg["returns"] += -payload["revenue_rial"]
        else:
            agg["gross"] += payload["revenue_rial"]
        agg["lines"] += 1
        agg["date"] = min(agg["date"], payload["line_date"])
        if agg["customer_id"] is None:
            agg["customer_id"] = payload["customer_id"]
        if payload["discount_rial"] is not None:
            agg["discount"] += payload["discount_rial"]
            agg["has_discount"] = True

    keys = sorted(grouped)
    existing: dict[str, int] = {}
    for start in range(0, len(keys), CHUNK):
        rows = session.execute(
            select(Order.order_key, Order.id).where(
                Order.business_id == business_id,
                Order.order_key.in_(keys[start:start + CHUNK]),
            )
        ).all()
        existing.update(dict(rows))

    to_insert: list[dict] = []
    to_update: list[dict] = []
    for key in keys:
        agg = grouped[key]
        row = {
            "customer_id": agg["customer_id"],
            "order_date": agg["date"],
            "gross_rial": agg["gross"],
            "returns_rial": agg["returns"],
            "net_rial": agg["gross"] - agg["returns"],
            "discount_rial": agg["discount"] if agg["has_discount"] else None,
            "line_count": agg["lines"],
            "branch": agg["branch"],
            "salesperson": agg["salesperson"],
            "channel": agg["channel"],
            "region": agg["region"],
            "batch_id": batch_id,
            "updated_at": now_ts(),
        }
        if key in existing:
            to_update.append({**row, "id": existing[key]})
        else:
            to_insert.append({
                **row, "business_id": business_id, "order_key": key,
                "order_period": agg["period"], "order_number": agg["number"],
            })

    if to_insert:
        session.execute(insert(Order), to_insert)
    if to_update:
        session.execute(update(Order), to_update)
    session.flush()

    # شناسه‌ی ردیف‌های تازه‌درج‌شده را دوباره می‌خوانیم (executemany آن را برنمی‌گرداند)
    missing = [k for k in keys if k not in existing]
    for start in range(0, len(missing), CHUNK):
        rows = session.execute(
            select(Order.order_key, Order.id).where(
                Order.business_id == business_id,
                Order.order_key.in_(missing[start:start + CHUNK]),
            )
        ).all()
        existing.update(dict(rows))

    # اتصال خطوط به سرِ فاکتور — تکه‌ای، نه یک UPDATE به‌ازای هر خط
    for start in range(0, len(real_orders), CHUNK):
        chunk = real_orders[start:start + CHUNK]
        ids = _existing_line_ids(session, [p["line_uid"] for p in chunk])
        updates = [
            {"id": ids[p["line_uid"]], "order_id": existing[p["order_key"]]}
            for p in chunk if p["line_uid"] in ids and p["order_key"] in existing
        ]
        if updates:
            session.execute(update(OrderLine), updates)
    session.flush()
    # سرِ فاکتور از همه‌ی خطوطِ وصل‌شده — نه فقط خطوطِ همین دسته
    _recompute_order_headers(session, sorted(existing.values()))

    return len(keys)


# ------------------------------------------------------------------- آشتی
def _add_customer_count_check(
    checks: list[ReconcileCheck], expected: int | None, actual: int | None,
) -> None:
    """کنترل شمار مشتری — با تفکیک «ادغام» از «خطا».

    این کنترل نمی‌تواند مثل بقیه برابری بخواهد: **ادغام هویت نتیجه‌ی مطلوب
    است**، نه اشکال. اگر «علی» و «کد-۱۲» با یک شماره یک نفر شوند، شمار دفتر
    کمتر از شمار تحلیل می‌شود و این درست است. تنها حالت واقعاً خراب، بیشتر
    بودنِ شمار دفتر است: یک کلید خام نباید به دو مشتری تبدیل شود.
    """
    label = "شمار مشتریان یکتا"
    if expected is None or actual is None:
        checks.append(ReconcileCheck(
            "L06", label, expected, actual, 0, "WARN",
            "مرجعی برای مقایسه‌ی شمار مشتری وجود نداشت.",
        ))
        return
    if actual == expected:
        status, detail = "OK", "شمار مشتری دفتر با تحلیل یکی است."
    elif actual < expected:
        status = "OK"
        detail = (
            f"{expected - actual} کلید خام به هویت‌های موجود وصل شدند (ادغام هویت) — "
            "این نتیجه‌ی مطلوبِ تشخیص مشتری تکراری است، نه اشکال."
        )
    else:
        status = "MISMATCH"
        detail = "شمار دفتر بیش از تحلیل است؛ یک کلید خام به چند مشتری تبدیل شده."
    checks.append(ReconcileCheck("L06", label, expected, actual, 0, status, detail))


def _reconcile(
    session: Session,
    *,
    batch_id: int,
    business_id: int,
    payloads: list[dict],
    n_source_rows: int,
    display_currency: str,
    kpis: Any | None,
    overlap_lines: int = 0,
) -> tuple[str, list[ReconcileCheck]]:
    """مقایسه‌ی «آنچه تحلیل گفت» با «آنچه در دفتر نشست».

    نتیجه عمداً به `bundle.validation.checks` اضافه **نمی‌شود**: آن دروازه
    درباره‌ی کیفیت داده‌ی ورودی است و بستنش تولید استراتژی را مسدود می‌کند.
    این‌ها شواهد نوشتن‌اند.
    """
    checks: list[ReconcileCheck] = []
    n_lines = len(payloads)
    tolerance = max(TOLERANCE_PER_LINE_RIAL, math.ceil(n_lines / 2))

    ledger = session.execute(
        select(OrderLine.is_return, OrderLine.revenue_rial).where(
            OrderLine.batch_id == batch_id, OrderLine.business_id == business_id,
        )
    ).all()
    ledger_gross = sum(r for is_ret, r in ledger if not is_ret)
    ledger_returns = -sum(r for is_ret, r in ledger if is_ret)
    ledger_net = ledger_gross - ledger_returns
    ledger_lines = len(ledger)

    def add(check_id: str, label: str, expected, actual, tol: float, detail: str | None = None):
        if expected is None or actual is None:
            status = "WARN"
        elif abs(float(actual) - float(expected)) <= tol:
            status = "OK"
        else:
            status = "MISMATCH"
        checks.append(ReconcileCheck(check_id, label, expected, actual, tol, status, detail))

    add("L01", "تعداد خطوط نوشته‌شده برابر خطوط آماده‌شده", n_lines, ledger_lines, 0)

    if kpis is not None:
        expected_gross = to_rial_int(getattr(kpis, "gross_sales", None), display_currency)
        expected_returns = to_rial_int(getattr(kpis, "returns_total", None), display_currency)
        expected_net = to_rial_int(getattr(kpis, "net_sales", None), display_currency)
        add("L02", "فروش ناخالص دفتر با KPI", expected_gross, ledger_gross, tolerance)
        add("L03", "جمع برگشت‌ها با KPI", expected_returns, ledger_returns, tolerance)
        add("L04", "فروش خالص دفتر با KPI", expected_net, ledger_net, tolerance)

        expected_returns_count = getattr(kpis, "returns_count", None)
        actual_returns_count = sum(1 for is_ret, _ in ledger if is_ret)
        add("L05", "شمار خطوط برگشتی", expected_returns_count, actual_returns_count, 0)

        actual_customers = session.scalar(
            select(func.count(func.distinct(OrderLine.customer_id))).where(
                OrderLine.batch_id == batch_id,
                OrderLine.customer_id.isnot(None),
            )
        )
        _add_customer_count_check(checks, getattr(kpis, "n_customers", None), actual_customers)

    add("L07", "هیچ ردیفی در مسیر نوشتن گم نشده است", n_source_rows, n_lines, 0,
        "اختلاف یعنی خطی به دفتر کل نرسیده است (تاریخ یا مبلغ نامعتبر)")

    # L08 — هم‌پوشانی با فایل‌های پیشین: اطلاع است، نه خطا. خطِ هم‌پوشان به‌روز
    # می‌شود نه دوبار شمرده؛ ولی عددش باید دیده شود.
    checks.append(ReconcileCheck(
        "L08", "هم‌پوشانی با بارگذاری‌های پیشین", overlap_lines, overlap_lines, 0, "OK",
        None if not overlap_lines else (
            f"{overlap_lines} خطِ این فایل قبلاً از فایلِ دیگری وارد شده بود و به‌روز شد، "
            "نه دوبار شمرده (هویتِ خط = فاکتور + کالا + ترتیب)."
        ),
    ))

    # L09 — شمار سفارش (§۸.۶): همان تعریفِ KPI — فاکتورهای با جمعِ خالصِ مثبت.
    if kpis is not None:
        expected_orders = getattr(kpis, "n_orders", None)
        if any(p["has_order_key"] for p in payloads):
            # با **شماره‌ی خام** شمرده می‌شود نه کلیدِ دوره‌دار — همان تعریفِ KPI
            # (kpis.n_orders دوره نمی‌شناسد)؛ وگرنه شماره‌ی بازاستفاده‌شده در دو سال
            # اینجا دو و در KPI یک شمرده می‌شد.
            net_by_order: dict[str, int] = {}
            for p in payloads:
                if p["has_order_key"]:
                    net_by_order[p["order_number"]] = (
                        net_by_order.get(p["order_number"], 0) + int(p["revenue_rial"])
                    )
            actual_orders = sum(1 for net in net_by_order.values() if net > 0)
            add("L09", "شمار سفارش با KPI", expected_orders, actual_orders, 0)
        else:
            checks.append(ReconcileCheck(
                "L09", "شمار سفارش با KPI", expected_orders, None, 0, "WARN",
                "فایل ستون فاکتور ندارد؛ تحلیل هر خط را یک سفارش می‌شمارد.",
            ))

    for check in checks:
        session.add(ImportReconciliation(
            batch_id=batch_id,
            check_id=check.check_id,
            label_fa=check.label_fa,
            expected_text=None if check.expected is None else str(check.expected),
            actual_text=None if check.actual is None else str(check.actual),
            delta_text=(
                None if check.expected is None or check.actual is None
                else str(float(check.actual) - float(check.expected))
            ),
            tolerance_text=str(check.tolerance),
            status=check.status,
            detail_fa=check.detail_fa,
        ))

    if any(c.status == "MISMATCH" for c in checks):
        status = "MISMATCH"
    elif any(c.status == "WARN" for c in checks):
        status = "RECONCILED_WITH_WARNINGS"
    else:
        status = "RECONCILED"
    return status, checks


# ------------------------------------------------------------------ نوشتن
def write_import(
    clean: pd.DataFrame,
    *,
    dataset_key: str | None = None,
    session_id: str | None = None,
    filename: str | None = None,
    sheet_name: str = "",
    display_currency: str = "تومان",
    file_currency: str | None = None,
    kpis: Any | None = None,
    validation_status: str | None = None,
    posting_blockers: list[dict] | None = None,
    business_slug: str = DEFAULT_BUSINESS_SLUG,
    db_path: Path | None = None,
) -> ImportWriteResult:
    """نوشتن یک فریم تمیز در دفتر کل و برگرداندن نتیجه‌ی آشتی.

    `clean` همان فریمی است که تحلیل دیده — **بعد از** تبدیل واحد پول — پس
    مبالغ در واحد نمایش‌اند و اینجا یک بار به ریال صحیح تبدیل می‌شوند.

    `posting_blockers` (§۸.۵): اگر ناخالی باشد، فقط ردیفِ دسته با وضعیتِ
    `BLOCKED` و دلیل‌ها ثبت می‌شود — به‌علاوه‌ی ردیف‌های خام و قرنطینه تا
    اپراتور ببیند چه چیزی رد شد — و **هیچ** خط، سفارش، مشتری یا کالایی نوشته
    نمی‌شود. تحلیل و داشبوردِ همان نشست دست‌نخورده می‌مانند.
    """
    ensure_schema(db_path)
    key = dataset_key or frame_dataset_key(clean)
    discount_is_amount = bool(clean.attrs.get("discount_is_amount"))
    combined = _combined_frame(clean)

    with write_lock, session_scope(db_path) as session:
        business = _get_or_create_business(session, business_slug, display_currency)
        revision = _next_revision(session, business.id, key)

        batch = ImportBatch(
            business_id=business.id,
            dataset_key=key,
            revision=revision,
            session_id=session_id,
            filename=filename,
            sheet_name=sheet_name or None,
            file_currency=file_currency,
            display_currency=display_currency,
            rial_per_file_unit=rial_per_unit(file_currency) if file_currency else None,
            rows_clean=int(len(clean)),
            rows_invalid=int(clean.attrs.get("dropped_invalid_rows", 0) or 0),
            rows_duplicate=int(clean.attrs.get("dropped_duplicate_rows", 0) or 0),
            rows_returns=int(clean.attrs.get("n_returns", 0) or 0),
            validation_status=validation_status,
        )
        batch.rows_total = (
            (batch.rows_clean or 0) + (batch.rows_invalid or 0)
            + (batch.rows_duplicate or 0) + (batch.rows_returns or 0)
        )
        session.add(batch)
        session.flush()

        if posting_blockers:
            return _record_blocked_batch(
                session, batch, clean, blockers=list(posting_blockers),
                key=key, revision=revision,
            )

        customer_ids, customers_created = _resolve_customers(session, business.id, combined)
        product_ids, products_created = _resolve_products(session, business.id, combined)

        payloads = _build_line_payloads(
            combined,
            business_id=business.id,
            batch_id=batch.id,
            dataset_key=key,
            sheet=sheet_name,
            revision=revision,
            display_currency=display_currency,
            discount_is_amount=discount_is_amount,
            customer_ids=customer_ids,
            product_ids=product_ids,
        )
        overlap_lines = _overlap_with_other_uploads(session, payloads, dataset_key=key)
        inserted, updated = _upsert_lines(session, payloads)
        orders_written = _write_orders(session, business.id, batch.id, payloads)

        reconcile_status, checks = _reconcile(
            session,
            batch_id=batch.id,
            business_id=business.id,
            payloads=payloads,
            n_source_rows=len(combined),
            display_currency=display_currency,
            kpis=kpis,
            overlap_lines=overlap_lines,
        )

        batch.lines_inserted = inserted
        batch.lines_updated = updated
        batch.reconcile_status = reconcile_status
        if payloads:
            dates = [p["line_date"] for p in payloads]
            batch.date_min = min(dates)
            batch.date_max = max(dates)
            # خطوط برگشتی از قبل منفی ذخیره شده‌اند، پس جمع ساده = فروش خالص
            batch.net_sales_rial = sum(p["revenue_rial"] for p in payloads)
        # §۷.۱ — پیش از هر چیز، ردیف‌هایی که وارد دفتر کل نشدند نگه داشته
        # می‌شوند. این تنها جایی بود که داده فعالانه از بین می‌رفت.
        from mktcore.config import get_settings
        from mktcore.ingest.cleaning import get_exclusions

        exclusions = get_exclusions(clean)
        rejected_total = 0 if exclusions is None or exclusions.empty else len(exclusions)
        quarantined = _write_quarantine(session, business.id, batch.id, exclusions)
        raw_capture = _write_raw_rows(
            session, business.id, batch.id, clean, exclusions,
            cap=get_settings().mkt_raw_rows_cap,
        )

        batch.notes_json = json.dumps(
            {
                "quarantined_rows": quarantined,
                # اگر جزئیات بریده شده باشد، همین‌جا گفته می‌شود؛ شمارِ کل
                # در `rows_invalid` و `rows_duplicate` دست‌نخورده است.
                "quarantine_detail_truncated": quarantined < rejected_total,
                "rejected_rows_total": rejected_total,
                "raw_rows_captured": raw_capture["captured"],
                "raw_rows_skipped": raw_capture["skipped"],
                "raw_capture_note_fa": raw_capture["note_fa"],
                "customers_created": customers_created,
                "products_created": products_created,
                # ستون‌هایی که واقعاً در فایل بودند — لازمِ سنجه‌های §۸.۵.
                # بدون این، «شفافیتِ برگشتی» بعداً قابل بازسازی نیست: فریمِ خام
                # دیگر در دسترس نخواهد بود.
                "has_doc_type_column": "doc_type" in clean.columns,
                "has_branch_column": "branch" in clean.columns,
                "n_returns": int(clean.attrs.get("n_returns") or 0),
            },
            ensure_ascii=False,
        )

        result = ImportWriteResult(
            batch_id=batch.id,
            business_id=business.id,
            dataset_key=key,
            revision=revision,
            lines_inserted=inserted,
            lines_updated=updated,
            customers_created=customers_created,
            products_created=products_created,
            orders_written=orders_written,
            reconcile_status=reconcile_status,
            checks=checks,
        )

    logger.info(
        "دفتر کل: دسته %s (نسخه %s) — %s خط جدید، %s به‌روز، آشتی: %s",
        result.batch_id, revision, inserted, updated, reconcile_status,
    )
    return result


RECONCILE_BLOCKED = "BLOCKED"


def _record_blocked_batch(
    session: Session, batch: ImportBatch, clean: pd.DataFrame, *,
    blockers: list[dict], key: str, revision: int,
) -> ImportWriteResult:
    """دسته‌ی مسدود (§۸.۵): شواهد می‌ماند، دفتر کل دست نمی‌خورد."""
    from mktcore.config import get_settings
    from mktcore.ingest.cleaning import get_exclusions

    exclusions = get_exclusions(clean)
    rejected_total = 0 if exclusions is None or exclusions.empty else len(exclusions)
    quarantined = _write_quarantine(session, batch.business_id, batch.id, exclusions)
    raw_capture = _write_raw_rows(
        session, batch.business_id, batch.id, clean, exclusions,
        cap=get_settings().mkt_raw_rows_cap,
    )
    batch.lines_inserted = 0
    batch.lines_updated = 0
    batch.reconcile_status = RECONCILE_BLOCKED
    batch.notes_json = json.dumps(
        {
            "posted": False,
            "blocked_by": blockers,
            "quarantined_rows": quarantined,
            "quarantine_detail_truncated": quarantined < rejected_total,
            "rejected_rows_total": rejected_total,
            "raw_rows_captured": raw_capture["captured"],
            "raw_rows_skipped": raw_capture["skipped"],
            "raw_capture_note_fa": raw_capture["note_fa"],
            "has_doc_type_column": "doc_type" in clean.columns,
            "has_branch_column": "branch" in clean.columns,
            "n_returns": int(clean.attrs.get("n_returns") or 0),
        },
        ensure_ascii=False,
    )
    logger.warning(
        "دفتر کل: دسته %s (نسخه %s) مسدود شد — %s",
        batch.id, revision, "، ".join(b.get("check_id", "?") for b in blockers),
    )
    return ImportWriteResult(
        batch_id=batch.id,
        business_id=batch.business_id,
        dataset_key=key,
        revision=revision,
        lines_inserted=0,
        lines_updated=0,
        customers_created=0,
        products_created=0,
        orders_written=0,
        reconcile_status=RECONCILE_BLOCKED,
        checks=[],
        posted=False,
        blocked_by=blockers,
    )


__all__ = [
    "DEFAULT_BUSINESS_SLUG",
    "RECONCILE_BLOCKED",
    "SAMPLE_BUSINESS_SLUG",
    "ImportWriteResult",
    "ReconcileCheck",
    "frame_dataset_key",
    "line_uid",
    "line_uid_for_order",
    "normalize_order_key",
    "order_header_key",
    "write_import",
]


# ------------------------------------------------------ ردیف خام و قرنطینه
def _json_row(row: pd.Series) -> str:
    """یک ردیف به JSON، با مقادیرِ غیرِ JSONی به رشته.

    `default=str` عمدی است: تاریخ‌های pandas و `Decimal` وگرنه کلِ نوشتن را
    می‌شکنند — و شکستنِ نوشتن به‌خاطر **ثبتِ ممیزی** یعنی همان داده‌ای که
    می‌خواستیم نگه داریم از دست برود.
    """
    payload = {
        str(key): (None if pd.isna(value) else value)
        for key, value in row.items()
    }
    return json.dumps(payload, ensure_ascii=False, default=str)


# سقفِ جزئیاتِ قرنطینه در هر بارگذاری. **شمارِ کلِ** ردیف‌های ردشده در
# `ImportBatch.rows_invalid` و `rows_duplicate` می‌ماند و از بین نمی‌رود؛ این
# سقف فقط جلوی ذخیره‌ی ده‌ها هزار JSON را می‌گیرد وقتی فایل به‌کل خراب است.
QUARANTINE_ROW_CAP = 10_000


def _write_quarantine(
    session: Session, business_id: int, batch_id: int, exclusions: pd.DataFrame,
) -> int:
    """ردیف‌های ردشده را در دفتر کل می‌نویسد.

    تا پیش از این، این ردیف‌ها فقط در `exclusions.parquet` کنارِ نشست بودند و
    سیاست نگه‌داری بعد از ۱۸۰ روز پاکشان می‌کرد — تنها جایی که داده فعالانه از
    بین می‌رفت.
    """
    if exclusions is None or exclusions.empty:
        return 0
    if len(exclusions) > QUARANTINE_ROW_CAP:
        logger.warning(
            "%s ردیف ردشده بیشتر از سقفِ جزئیاتِ قرنطینه (%s) است؛ فقط "
            "پرارزش‌ترین بخش با جزئیات ذخیره می‌شود. شمارِ کل در خودِ بارگذاری "
            "ثبت شده است.",
            len(exclusions), QUARANTINE_ROW_CAP,
        )
        exclusions = exclusions.head(QUARANTINE_ROW_CAP)

    from mktcore.ingest.cleaning import (
        EXCLUSION_REASONS_FA,
        EXCLUSION_RESOLUTIONS_FA,
    )

    written = 0
    for _, row in exclusions.iterrows():
        code = str(row.get("کد دلیل") or "unknown")
        detail = str(row.get("دلیل") or EXCLUSION_REASONS_FA.get(code, "دلیل ثبت نشده"))
        raw_row_number = row.get(SOURCE_ROW)
        row_number = (
            None if raw_row_number is None or pd.isna(raw_row_number)
            else int(raw_row_number)
        )
        session.add(ImportQuarantine(
            business_id=business_id,
            batch_id=batch_id,
            row_number=row_number,
            raw_payload_json=_json_row(row),
            reason_code=code,
            reason_detail_fa=detail,
            suggested_resolution_fa=EXCLUSION_RESOLUTIONS_FA.get(code),
        ))
        written += 1
    session.flush()
    return written


def _write_raw_rows(
    session: Session,
    business_id: int,
    batch_id: int,
    clean: pd.DataFrame,
    exclusions: pd.DataFrame,
    *,
    cap: int,
) -> dict:
    """نگه‌داشتنِ نمایشِ خامِ ردیف‌ها، تا سقفِ تعیین‌شده.

    بالاتر از سقف، ردیف‌های **پذیرفته‌شده** ذخیره نمی‌شوند و همین در یادداشتِ
    بارگذاری ثبت می‌شود — «ذخیره نشد» باید گفته شود، وگرنه کاربر گمان می‌کند
    ممیزیِ کامل دارد.
    """
    rejected = 0 if exclusions is None or exclusions.empty else len(exclusions)
    total = len(clean) + rejected
    if total > cap:
        return {
            "captured": 0,
            "skipped": total,
            "note_fa": (
                f"{total} ردیف بیشتر از سقفِ {cap} ردیف است، پس نمایشِ خامِ "
                "ردیف‌های پذیرفته‌شده ذخیره نشد. ردیف‌های ردشده مثل همیشه در "
                "قرنطینه هستند."
            ),
        }

    seen: set[int] = set()
    captured = 0
    for _, row in clean.iterrows():
        raw_row_number = row.get(SOURCE_ROW)
        row_number = (
            None if raw_row_number is None or pd.isna(raw_row_number)
            else int(raw_row_number)
        )
        # قیدِ یکتاییِ (batch, row_number) اجازه‌ی ردیفِ تکراری نمی‌دهد؛ ردیفِ
        # بی‌شماره هم فقط یک‌بار جا دارد.
        if row_number in seen:
            continue
        seen.add(row_number)
        payload = _json_row(row)
        session.add(ImportRowRaw(
            business_id=business_id,
            batch_id=batch_id,
            row_number=row_number,
            raw_payload_json=payload,
            row_hash=hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32],
            parse_status=ImportRowRaw.PARSE_OK,
        ))
        captured += 1
    session.flush()
    return {"captured": captured, "skipped": 0, "note_fa": None}
