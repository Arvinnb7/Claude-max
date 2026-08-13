"""عکس‌برداری ماندگار از ویژگی‌های مشتری در یک لحظه‌ی مشخص.

چرا لازم است؟ چون بدون آن نمی‌شود صادقانه گفت «آن‌موقع چه می‌دانستیم». اگر
ویژگی‌ها فقط لحظه‌ای محاسبه شوند، هر ارزیابیِ بعدی با داده‌ی آینده آلوده می‌شود
(leakage) و هر ادعایی درباره‌ی اثرِ یک اقدام بی‌پایه است.

**محاسبه‌ای اینجا انجام نمی‌شود.** ریاضی همان‌جا می‌ماند که هست — ماژول‌های
`analysis/*` روی pandas که تست‌شده و درست‌اند. این ماژول فقط نتیجه را با
`as_of` و شماره‌ی نسخه می‌نویسد.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import pandas as pd
from sqlalchemy import select

from mktcore.money import to_basis_points, to_rial_int

from .base import now_ts
from .engine import session_scope, write_lock
from .lookup import customer_ids_by_raw_key
from .migrations import ensure_schema
from .models import Business, CustomerFeature

if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.orm import Session

logger = logging.getLogger("mktcore.db.repo_features")

# با تغییر معنای هر ویژگی این عدد بالا می‌رود؛ عکس‌های قدیمی بازنویسی نمی‌شوند
# تا مقایسه‌ی «قبل/بعد» با تعریف‌های متفاوت قاطی نشود.
FEATURE_VERSION = 1

CHUNK = 2000


def _as_of_date(clean: pd.DataFrame) -> str:
    """آخرین روزِ داده — نه «امروز». معیار همان چیزی است که داده نشان می‌دهد."""
    if "date" in clean.columns and len(clean):
        stamp = pd.Timestamp(clean["date"].max())
        if not pd.isna(stamp):
            return stamp.date().isoformat()
    return pd.Timestamp.now().date().isoformat()


def _segment_lookup(bundle: Any) -> dict[str, str]:
    seg = getattr(bundle, "segments", None)
    table = getattr(seg, "rfm_table", None)
    if table is None or not len(table) or "segment_fa" not in table.columns:
        return {}
    return {str(idx): str(value) for idx, value in table["segment_fa"].items()}


def _next_purchase_lookup(bundle: Any) -> dict[str, Any]:
    analysis = getattr(bundle, "next_purchase", None)
    customers = getattr(analysis, "customers", None) or []
    return {str(c.customer_id): c for c in customers}


_CYCLE_PRIORITY = {"عقب‌افتاده": 0, "نزدیک": 1, "در مسیر": 2}


def _cycle_status_lookup(bundle: Any) -> dict[str, str]:
    """وضعیت چرخه‌ی هر مشتری — فوری‌ترین وضعیت بین کالاهای او.

    یک مشتری می‌تواند برای یک کالا عقب‌افتاده و برای دیگری در مسیر باشد؛ آنچه
    باید در پرونده دیده شود، فوری‌ترین است.
    """
    cycle = getattr(bundle, "purchase_cycle", None)
    notifications = getattr(cycle, "notifications", None) or []
    out: dict[str, str] = {}
    for note in notifications:
        key = str(getattr(note, "customer_id", "") or "")
        status = getattr(note, "status", None)
        if not key or not status:
            continue
        current = out.get(key)
        if current is None or _CYCLE_PRIORITY.get(status, 9) < _CYCLE_PRIORITY.get(current, 9):
            out[key] = str(status)
    return out


def _per_customer_frame(clean: pd.DataFrame) -> pd.DataFrame:
    """جمع‌های پایه‌ی هر مشتری از فریم تمیز (برگشت‌ها اینجا نیستند — مثل تحلیل)."""
    if "customer_id" not in clean.columns or not len(clean):
        return pd.DataFrame()
    grouped = clean.groupby("customer_id")
    frame = pd.DataFrame({
        "n_lines": grouped.size(),
        "monetary": grouped["revenue"].sum(),
        "first_date": grouped["date"].min(),
        "last_date": grouped["date"].max(),
    })
    if "order_id" in clean.columns:
        frame["n_orders"] = grouped["order_id"].nunique()
    else:
        frame["n_orders"] = frame["n_lines"]
    if "product" in clean.columns:
        top = (
            clean.groupby(["customer_id", "product"])["revenue"].sum()
            .reset_index().sort_values("revenue", ascending=False)
            .drop_duplicates("customer_id").set_index("customer_id")["product"]
        )
        frame["top_product"] = top
    return frame


def write_customer_features(
    clean: pd.DataFrame,
    bundle: Any,
    *,
    display_currency: str = "تومان",
    business_slug: str = "default",
    db_path: Path | None = None,
) -> int:
    """نوشتن عکسِ ویژگی‌ها برای همه‌ی مشتریانِ شناخته‌شده. تعداد ردیف را برمی‌گرداند.

    اجرای دوباره روی همان `as_of` بی‌خطر است: ردیف موجود به‌روز می‌شود
    (یکتاییِ business+customer+as_of+version).
    """
    ensure_schema(db_path)
    per_customer = _per_customer_frame(clean)
    if not len(per_customer):
        return 0

    as_of = _as_of_date(clean)
    segments = _segment_lookup(bundle)
    predictions = _next_purchase_lookup(bundle)
    cycles = _cycle_status_lookup(bundle)
    reference = pd.Timestamp(clean["date"].max())

    with write_lock, session_scope(db_path) as session:
        business = session.scalar(select(Business).where(Business.slug == business_slug))
        if business is None:
            logger.warning("کسب‌وکار «%s» وجود ندارد؛ عکس ویژگی نوشته نشد.", business_slug)
            return 0

        key_to_id = customer_ids_by_raw_key(
            session, business.id, (str(k) for k in per_customer.index),
        )
        if not key_to_id:
            return 0

        existing = _existing_snapshots(session, business.id, as_of, set(key_to_id.values()))
        grouped = _group_by_resolved_customer(per_customer, key_to_id)

        to_insert: list[dict] = []
        to_update: list[dict] = []
        for customer_id, (row, dominant_key) in grouped.items():
            payload = _feature_payload(
                business_id=business.id,
                customer_id=customer_id,
                as_of=as_of,
                row=row,
                reference=reference,
                prediction=predictions.get(dominant_key),
                segment=segments.get(dominant_key),
                cycle_status=cycles.get(dominant_key),
                display_currency=display_currency,
            )
            if customer_id in existing:
                to_update.append({**payload, "id": existing[customer_id]})
            else:
                to_insert.append(payload)

        _bulk_write(session, to_insert, to_update)

    written = len(to_insert) + len(to_update)
    logger.info("عکس ویژگی مشتری (%s): %s ردیف", as_of, written)
    return written


def _group_by_resolved_customer(
    per_customer: pd.DataFrame, key_to_id: dict[str, int],
) -> dict[int, tuple[pd.Series, str]]:
    """جمع‌کردن ردیف‌های چند کلیدِ خام که به **یک** مشتری حل شده‌اند.

    این دقیقاً نتیجه‌ی مطلوبِ حل هویت است: «C1» و «کد۱» با یک شماره موبایل یک
    نفرند، پس باید یک پرونده با جمعِ خریدهای هر دو داشته باشند. بدون این
    جمع‌بندی، دو ردیف با کلید یکتای یکسان درج می‌شد و کل نوشتن rollback می‌شد.

    خروجی: `customer_id → (ردیف جمع‌شده، کلیدِ خامِ غالب)`. کلید غالب آن است که
    بیشترین خرید را دارد؛ سگمنت و پیش‌بینیِ همان استفاده می‌شود، چون تحلیل
    آن‌ها را به‌ازای کلید خام تولید کرده است.
    """
    # مقدارِ خریدِ کلیدِ غالب کنار خودش نگه داشته می‌شود؛ جستجوی دوباره در
    # ایندکس با کلیدِ رشته‌ای‌شده روی شناسه‌های عددی می‌شکست.
    grouped: dict[int, tuple[pd.Series, str, float]] = {}
    for raw_key, row in per_customer.iterrows():
        key = str(raw_key)
        customer_id = key_to_id.get(key)
        if customer_id is None:
            continue
        monetary = float(row["monetary"])
        if customer_id not in grouped:
            grouped[customer_id] = (row.copy(), key, monetary)
            continue
        merged, dominant, dominant_value = grouped[customer_id]
        merged["n_lines"] += row["n_lines"]
        merged["n_orders"] += row["n_orders"]
        merged["monetary"] += row["monetary"]
        merged["first_date"] = min(merged["first_date"], row["first_date"])
        merged["last_date"] = max(merged["last_date"], row["last_date"])
        if monetary > dominant_value:
            dominant, dominant_value = key, monetary
            if "top_product" in row:
                merged["top_product"] = row["top_product"]
        grouped[customer_id] = (merged, dominant, dominant_value)
    return {cid: (row, key) for cid, (row, key, _value) in grouped.items()}


def _existing_snapshots(
    session: Session, business_id: int, as_of: str, customer_ids: set[int],
) -> dict[int, int]:
    ids = sorted(customer_ids)
    out: dict[int, int] = {}
    for start in range(0, len(ids), CHUNK):
        rows = session.execute(
            select(CustomerFeature.customer_id, CustomerFeature.id).where(
                CustomerFeature.business_id == business_id,
                CustomerFeature.as_of_date == as_of,
                CustomerFeature.feature_version == FEATURE_VERSION,
                CustomerFeature.customer_id.in_(ids[start:start + CHUNK]),
            )
        ).all()
        out.update(dict(rows))
    return out


def _feature_payload(
    *,
    business_id: int,
    customer_id: int,
    as_of: str,
    row: pd.Series,
    reference: pd.Timestamp,
    prediction: Any | None,
    segment: str | None,
    cycle_status: str | None,
    display_currency: str,
) -> dict:
    n_orders = int(row["n_orders"])
    monetary = float(row["monetary"])
    aov = monetary / n_orders if n_orders else None
    recency = int((reference - pd.Timestamp(row["last_date"])).days)
    tenure = int((reference - pd.Timestamp(row["first_date"])).days)

    p_alive = getattr(prediction, "alive_probability", None) if prediction else None
    clv = getattr(prediction, "clv_12m", None) if prediction else None
    avg_gap = getattr(prediction, "avg_interval_days", None) if prediction else None
    # «ارزش در معرض خطر» درآمدی است، نه سود — نام ستون همین را می‌گوید
    at_risk = getattr(prediction, "expected_value_30d", None) if prediction else None

    return {
        "business_id": business_id,
        "customer_id": customer_id,
        "as_of_date": as_of,
        "feature_version": FEATURE_VERSION,
        "n_orders": n_orders,
        "n_lines": int(row["n_lines"]),
        "monetary_rial": to_rial_int(monetary, display_currency),
        "aov_rial": to_rial_int(aov, display_currency),
        "recency_days": recency,
        "tenure_days": tenure,
        "avg_gap_days": float(avg_gap) if avg_gap is not None else None,
        "expected_gap_days": float(avg_gap) if avg_gap is not None else None,
        "overdue_days": (
            float(recency - avg_gap) if avg_gap else None
        ),
        "p_alive_bp": to_basis_points(p_alive),
        "clv_rial": to_rial_int(clv, display_currency),
        "segment": segment,
        "lifecycle_state": None,  # در گام بعد از ماشین حالت چرخه‌ی عمر پر می‌شود
        "cycle_status": cycle_status,
        "top_product": (
            str(row["top_product"]) if "top_product" in row and pd.notna(row.get("top_product"))
            else None
        ),
        "value_at_risk_rial": to_rial_int(at_risk, display_currency),
        "created_at": now_ts(),
    }


def _bulk_write(session: Session, to_insert: list[dict], to_update: list[dict]) -> None:
    from sqlalchemy import insert, update

    for start in range(0, len(to_insert), CHUNK):
        session.execute(insert(CustomerFeature), to_insert[start:start + CHUNK])
        session.flush()
    for start in range(0, len(to_update), CHUNK):
        session.execute(update(CustomerFeature), to_update[start:start + CHUNK])
        session.flush()


__all__ = ["FEATURE_VERSION", "write_customer_features"]
