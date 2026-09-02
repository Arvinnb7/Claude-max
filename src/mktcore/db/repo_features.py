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
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import pandas as pd
from sqlalchemy import func, insert, select

from mktcore.analysis.clv import gross_profit_per_order_rial, horizon_clv
from mktcore.lifecycle import LifecycleInput, LifecycleVerdict, classify_lifecycle
from mktcore.lifecycle.states import population_gap, vip_threshold
from mktcore.money import to_basis_points, to_rial_int

from .base import now_ts
from .engine import session_scope, write_lock
from .lookup import customer_ids_by_raw_key, resolve_business_id
from .migrations import ensure_schema
from .models import Business, CustomerFeature, CustomerLifecycleEvent, OrderLine

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
        business_id = resolve_business_id(session, business_slug)
        business = session.get(Business, business_id) if business_id else None
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

        # آستانه‌های جامعه یک بار برای همه محاسبه می‌شوند: میانه‌ی آهنگ خرید
        # (تکیه‌گاه مشتریانِ تک‌خرید) و آستانه‌ی «ویژه» از توزیع همین کسب‌وکار.
        pop_gap = population_gap([
            float(getattr(p, "avg_interval_days", None) or 0) for p in predictions.values()
        ])
        vip_floor = vip_threshold([
            to_rial_int(getattr(p, "clv_12m", None), display_currency) or 0
            for p in predictions.values()
        ])
        previous_states = _previous_states(session, business.id, as_of, set(grouped))
        profits = _profit_lookup(session, business.id, set(grouped))
        full_price = _full_price_lookup(session, business.id)

        to_insert: list[dict] = []
        to_update: list[dict] = []
        verdicts: dict[int, LifecycleVerdict] = {}
        for customer_id, (row, dominant_key) in grouped.items():
            prediction = predictions.get(dominant_key)
            verdict = _classify(
                row=row, reference=reference, prediction=prediction,
                display_currency=display_currency, population_gap_days=pop_gap,
                vip_floor=vip_floor, previous=previous_states.get(customer_id),
            )
            verdicts[customer_id] = verdict
            payload = _feature_payload(
                business_id=business.id,
                customer_id=customer_id,
                as_of=as_of,
                row=row,
                reference=reference,
                prediction=prediction,
                segment=segments.get(dominant_key),
                cycle_status=cycles.get(dominant_key),
                display_currency=display_currency,
                lifecycle=verdict,
                profit=profits.get(customer_id),
                full_price_share_bp=full_price.get(customer_id),
            )
            if customer_id in existing:
                to_update.append({**payload, "id": existing[customer_id]})
            else:
                to_insert.append(payload)

        _bulk_write(session, to_insert, to_update)
        _record_transitions(session, business.id, as_of, verdicts, previous_states)

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


def _full_price_lookup(session: Session, business_id: int) -> dict[int, int]:
    """سهمِ خریدِ تمام‌قیمتِ هر مشتری از دفتر کل (§۲۰.۳ بند ۱).

    مشتریِ بدونِ عدد (فایل بدون ستون تخفیف) در خروجی **نیست** تا ستونش NULL
    بماند — نه صفر، نه ۱۰۰٪.
    """
    from mktcore.features.discount import full_price_share_bp
    from mktcore.features.ledger_frame import load_line_frame

    try:
        lines = load_line_frame(session, business_id)
    except Exception:  # noqa: BLE001 - نبودِ این عدد نباید نوشتنِ ویژگی را بخواباند
        logger.exception("سهم خرید تمام‌قیمت خوانده نشد")
        return {}
    share = full_price_share_bp(lines)
    return {
        int(customer_id): int(value)
        for customer_id, value in share.items()
        if value == value  # NaN را کنار می‌گذارد
    }


def _profit_lookup(
    session: Session, business_id: int, customer_ids: set[int],
) -> dict[int, dict]:
    """سودِ ناخالصِ هر مشتری از **دفتر کل** — نه از فریمِ تحلیل.

    چرا از دفتر کل: بها ممکن است از فایل فروش نیامده باشد و با
    `POST /api/v1/costs` وارد شده باشد؛ آن بها فقط در دفتر کل هست.

    قاعده‌ی پوشش همان قاعده‌ی همیشگی است: اگر **یک** خط بها نداشته باشد، سودِ
    این مشتری `None` می‌ماند. جمعِ ناقص سود را کمتر از واقع نشان می‌دهد بدون
    اینکه معلوم باشد.
    """
    if not customer_ids:
        return {}
    out: dict[int, dict] = {}
    ids = sorted(customer_ids)
    for start in range(0, len(ids), CHUNK):
        rows = session.execute(
            select(
                OrderLine.customer_id,
                func.count(OrderLine.id),
                func.count(OrderLine.gross_profit_rial),
                func.sum(OrderLine.gross_profit_rial),
                func.count(func.distinct(OrderLine.order_id)),
            )
            .where(
                OrderLine.business_id == business_id,
                OrderLine.customer_id.in_(ids[start:start + CHUNK]),
            )
            .group_by(OrderLine.customer_id)
        ).all()
        for customer_id, n_lines, n_with_profit, profit, n_orders in rows:
            covered = int(n_with_profit or 0) == int(n_lines or 0) and int(n_lines or 0) > 0
            out[int(customer_id)] = {
                "gross_profit_rial": int(profit or 0) if covered else None,
                "n_orders": int(n_orders or 0) or int(n_lines or 0),
                "covered": covered,
                "n_lines": int(n_lines or 0),
                "n_lines_with_profit": int(n_with_profit or 0),
            }
    return out


def _clv_profit_fields(
    *, profit: dict | None, prediction: Any | None, as_of: str,
) -> dict:
    """CLV سودمحور برای سه افق + بازه‌ی ۳۶۵ روزه (§۱۹).

    نبودِ سود یا آهنگ خرید ⇒ همه‌ی ستون‌ها `None` و `clv_gp_basis` خالی؛ لایه‌ی
    API دلیلش را به کاربر می‌گوید. صفر نوشتن یعنی «این مشتری سودی ندارد» که
    ادعایی است نداریم.
    """
    empty = {
        "clv_gp_90d_rial": None, "clv_gp_180d_rial": None, "clv_gp_365d_rial": None,
        "clv_gp_365d_low_rial": None, "clv_gp_365d_high_rial": None,
        "clv_gp_basis": None, "clv_model_version": None,
    }
    if not profit:
        return empty

    per_order = gross_profit_per_order_rial(
        gross_profit_rial=profit.get("gross_profit_rial"),
        n_orders=profit.get("n_orders"),
    )
    horizons = horizon_clv(
        gp_per_order_rial=per_order,
        mu_days=getattr(prediction, "avg_interval_days", None) if prediction else None,
        p_alive=getattr(prediction, "alive_probability", None) if prediction else None,
        n_orders=profit.get("n_orders"),
        as_of=as_of,
    )
    by_days = {item.horizon_days: item for item in horizons}
    year = by_days.get(365)
    if year is None or year.value_rial is None:
        return empty
    return {
        "clv_gp_90d_rial": by_days[90].value_rial,
        "clv_gp_180d_rial": by_days[180].value_rial,
        "clv_gp_365d_rial": year.value_rial,
        "clv_gp_365d_low_rial": year.low_rial,
        "clv_gp_365d_high_rial": year.high_rial,
        "clv_gp_basis": year.basis,
        "clv_model_version": year.model_version,
    }


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
    lifecycle: LifecycleVerdict | None = None,
    profit: dict | None = None,
    full_price_share_bp: int | None = None,
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
        # §۲۰.۳ بند ۱ — همبستگیِ مشاهده‌ای؛ NULL یعنی فایل ستون تخفیف نداشت
        "full_price_share_bp": full_price_share_bp,
        "clv_rial": to_rial_int(clv, display_currency),
        "segment": segment,
        "lifecycle_state": lifecycle.state if lifecycle else None,
        "cycle_status": cycle_status,
        "top_product": (
            str(row["top_product"]) if "top_product" in row and pd.notna(row.get("top_product"))
            else None
        ),
        "value_at_risk_rial": to_rial_int(at_risk, display_currency),
        **_clv_profit_fields(profit=profit, prediction=prediction, as_of=as_of),
        "created_at": now_ts(),
    }


@dataclass(frozen=True)
class _PreviousState:
    """آخرین حالتِ ثبت‌شده‌ی مشتری، پیش از عکس جاری."""

    state: str
    as_of: str
    last_order_date: str | None


def _previous_states(
    session: Session, business_id: int, as_of: str, customer_ids: set[int],
) -> dict[int, _PreviousState]:
    """آخرین عکسِ **قبل از** تاریخ جاری — مبنای تشخیص گذار و احیا.

    عکس‌های با همان `as_of` کنار گذاشته می‌شوند: اجرای دوباره‌ی تحلیل روی همان
    داده نباید گذارِ ساختگی بسازد.
    """
    ids = sorted(customer_ids)
    out: dict[int, _PreviousState] = {}
    for start in range(0, len(ids), CHUNK):
        rows = session.execute(
            select(
                CustomerFeature.customer_id,
                CustomerFeature.lifecycle_state,
                CustomerFeature.as_of_date,
            ).where(
                CustomerFeature.business_id == business_id,
                CustomerFeature.as_of_date < as_of,
                CustomerFeature.lifecycle_state.isnot(None),
                CustomerFeature.customer_id.in_(ids[start:start + CHUNK]),
            ).order_by(CustomerFeature.customer_id, CustomerFeature.as_of_date)
        ).all()
        for customer_id, state, snapshot_date in rows:
            out[customer_id] = _PreviousState(str(state), str(snapshot_date), None)
    return out


def _classify(
    *,
    row: pd.Series,
    reference: pd.Timestamp,
    prediction: Any | None,
    display_currency: str,
    population_gap_days: float | None,
    vip_floor: int | None,
    previous: _PreviousState | None,
) -> LifecycleVerdict:
    """ترجمه‌ی ویژگی‌ها به ورودی ماشین حالت و گرفتن حکم.

    هیچ ریاضی تازه‌ای اینجا نیست؛ همه‌ی اعداد از قبل محاسبه شده‌اند.
    """
    recency = int((reference - pd.Timestamp(row["last_date"])).days)
    tenure = int((reference - pd.Timestamp(row["first_date"])).days)
    # «از عکس قبلی تا حالا خرید کرده؟» — آخرین خریدش بعد از تاریخ آن عکس باشد
    purchased_since = bool(
        previous and pd.Timestamp(row["last_date"]) > pd.Timestamp(previous.as_of)
    )
    return classify_lifecycle(LifecycleInput(
        n_orders=int(row["n_orders"]),
        recency_days=recency,
        tenure_days=tenure,
        avg_gap_days=getattr(prediction, "avg_interval_days", None) if prediction else None,
        p_alive=getattr(prediction, "alive_probability", None) if prediction else None,
        clv_rial=to_rial_int(
            getattr(prediction, "clv_12m", None) if prediction else None, display_currency,
        ),
        population_gap_days=population_gap_days,
        vip_clv_threshold_rial=vip_floor,
        previous_state=previous.state if previous else None,
        purchased_since_previous=purchased_since,
    ))


def _record_transitions(
    session: Session,
    business_id: int,
    as_of: str,
    verdicts: dict[int, LifecycleVerdict],
    previous: dict[int, _PreviousState],
) -> None:
    """ثبت گذارها — فقط وقتی حالت **واقعاً** عوض شده باشد.

    نوشتن ردیف برای حالتِ بدون تغییر، تایم‌لاین را از نویز پر می‌کند و گذارِ
    واقعی را دفن می‌کند.
    """
    events = []
    for customer_id, verdict in verdicts.items():
        before = previous.get(customer_id)
        if before is not None and before.state == verdict.state:
            continue
        events.append({
            "business_id": business_id,
            "customer_id": customer_id,
            "as_of_date": as_of,
            "from_state": before.state if before else None,
            "to_state": verdict.state,
            "reason_fa": verdict.reason_fa,
            "basis": verdict.basis,
            "overdue_ratio": verdict.overdue_ratio,
            "created_at": now_ts(),
        })
    if not events:
        return
    # اجرای دوباره روی همان تاریخ نباید ردیف تکراری بسازد
    existing = {
        (cid, state)
        for cid, state in session.execute(
            select(
                CustomerLifecycleEvent.customer_id, CustomerLifecycleEvent.to_state,
            ).where(
                CustomerLifecycleEvent.business_id == business_id,
                CustomerLifecycleEvent.as_of_date == as_of,
            )
        ).all()
    }
    fresh = [e for e in events if (e["customer_id"], e["to_state"]) not in existing]
    for start in range(0, len(fresh), CHUNK):
        session.execute(insert(CustomerLifecycleEvent), fresh[start:start + CHUNK])
        session.flush()


def _bulk_write(session: Session, to_insert: list[dict], to_update: list[dict]) -> None:
    from sqlalchemy import insert, update

    for start in range(0, len(to_insert), CHUNK):
        session.execute(insert(CustomerFeature), to_insert[start:start + CHUNK])
        session.flush()
    for start in range(0, len(to_update), CHUNK):
        session.execute(update(CustomerFeature), to_update[start:start + CHUNK])
        session.flush()


__all__ = ["FEATURE_VERSION", "write_customer_features"]
