"""فضای نام `/api/v1` — خواندن از دفتر کل canonical.

این مسیرها **در کنار** مسیرهای فعلی می‌نشینند، نه به‌جای آن‌ها. هیچ endpoint
موجودی تغییر نمی‌کند؛ داشبورد همچنان از همان `/api/analyze` تغذیه می‌شود.

چیزی که اینجا هست و آنجا نبود: پرسش‌هایی که فراتر از یک بارگذاری‌اند —
«این مشتری در طول همه‌ی فایل‌ها چه کرده؟»، «کیفیت بارگذاری‌های قبلی چه بود؟».

قواعد پاسخ:

* **پول همیشه دوشکلی**: `{"rial": int, "display_text": "…"}`. هرگز float،
  و هرگز عددِ خام که سمت کلاینت با ضریب اشتباه رندر شود.
* **هر پاسخ پولی `economics_note_fa` دارد**: اعداد درآمدی‌اند، نه سود. متن این
  جمله از **پوشش واقعی بهای تمام‌شده** ساخته می‌شود، نه از یک فرض ثابت — بعضی
  فایل‌ها ستون بها دارند و گفتنِ «نداریم» به داده‌ی کاربر دروغ می‌گفت.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select

from mktcore.analysis.branch import likely_branch
from mktcore.config import get_settings
from mktcore.db.engine import session_scope
from mktcore.db.lookup import active_business_id
from mktcore.db.migrations import ensure_schema
from mktcore.db.models import (
    Business,
    ContactSuppression,
    Customer,
    CustomerFeature,
    CustomerLifecycleEvent,
    ImportBatch,
    ImportReconciliation,
    Opportunity,
    OpportunityEvent,
    OpportunityFactor,
    Order,
    OrderLine,
    Product,
)
from mktcore.identity import mask_phone
from mktcore.ingest.quality import build_quality_dimensions, overall_quality
from mktcore.lifecycle import STATE_LABELS_FA
from mktcore.money import money_payload
from mktcore.opportunities.contract import VALUE_RELATIONSHIP
from mktcore.security import require_token

logger = logging.getLogger("mktcore.api.v1")

router = APIRouter(prefix="/api/v1", tags=["revenue-intelligence"])

ECONOMICS_NOTE_FA = (
    "همه‌ی مبالغ «درآمد» هستند. چون بهای تمام‌شده در داده‌ی ورودی وجود ندارد، "
    "سود ناخالص محاسبه نشده و هیچ عددی در این پاسخ «سود» نیست."
)
_ECONOMICS_NOTE_PARTIAL_FA = (
    "همه‌ی مبالغ «درآمد» هستند. بهای تمام‌شده فقط برای بخشی از خطوط موجود است، "
    "پس سود ناخالص محاسبه نشده — عدد ناقص بدتر از نبودِ عدد است."
)
_ECONOMICS_NOTE_FULL_FA = (
    "همه‌ی مبالغ این پاسخ «درآمد» هستند. بهای تمام‌شده برای همه‌ی خطوط ثبت شده و "
    "در دفتر کل موجود است، ولی اعداد این پاسخ درآمدی‌اند نه سود."
)

_DEFAULT_SLUG = "default"

# پایه‌ی قضاوتِ حالت — تا کاربر بداند این برچسب چقدر شخصی است
_BASIS_LABELS_FA = {
    "personal": "بر پایه‌ی آهنگ خرید خودِ مشتری",
    "population": "بر پایه‌ی میانه‌ی آهنگ خرید سایر مشتریان",
    "count_only": "بر پایه‌ی تعداد خرید (هنوز آهنگی شکل نگرفته)",
}


def _cost_coverage(session, business_id: int | None) -> float:
    """نسبت خطوطی که بهای تمام‌شده دارند (۰ تا ۱).

    این عدد تعیین می‌کند پاسخ چه ادعایی درباره‌ی سود بکند. ثابتِ hardcode‌شده
    غلط بود: بعضی فایل‌ها ستون بها **دارند** و گفتن «نداریم» به داده‌ی کاربر
    دروغ می‌گفت.
    """
    if business_id is None:
        return 0.0
    total, with_cost = session.execute(
        select(func.count(OrderLine.id), func.count(OrderLine.cost_rial))
        .where(OrderLine.business_id == business_id)
    ).one()
    return (int(with_cost or 0) / int(total)) if total else 0.0


def _economics_note(coverage: float) -> str:
    if coverage >= 0.999:
        return _ECONOMICS_NOTE_FULL_FA
    if coverage > 0:
        return _ECONOMICS_NOTE_PARTIAL_FA
    return ECONOMICS_NOTE_FA


def _display_currency() -> str:
    return get_settings().mkt_currency


def _money(rial: int | None) -> dict:
    return money_payload(rial, _display_currency())


def _business_id(session, slug: str | None = None) -> int | None:
    """کسب‌وکارِ فعال. `slug` صریح فقط برای مواردی که واقعاً یک کسب‌وکار خاص لازم است."""
    if slug is not None:
        return session.scalar(select(Business.id).where(Business.slug == slug))
    return active_business_id(session, fallback_slug=_DEFAULT_SLUG)


def _no_ledger_yet() -> dict:
    """پاسخ صادقانه وقتی هنوز هیچ تحلیلی در دفتر کل ثبت نشده است."""
    return {
        "available": False,
        "note_fa": (
            "هنوز تحلیلی در دفتر کل ثبت نشده است. یک فایل را تحلیل کنید تا "
            "مشتریان و کالاها بین بارگذاری‌ها به هم وصل شوند."
        ),
    }


# ------------------------------------------------------------- بارگذاری‌ها
@router.get("/imports")
def list_imports(limit: int = Query(50, ge=1, le=200)) -> dict:
    """فهرست بارگذاری‌های ثبت‌شده، تازه‌ترین اول."""
    ensure_schema()
    with session_scope() as session:
        business_id = _business_id(session)
        if business_id is None:
            return {**_no_ledger_yet(), "items": []}
        batches = session.scalars(
            select(ImportBatch)
            .where(ImportBatch.business_id == business_id)
            .order_by(ImportBatch.created_at.desc())
            .limit(limit)
        ).all()
        items = [_batch_summary(b) for b in batches]
        note = _economics_note(_cost_coverage(session, business_id))
    return {"available": True, "items": items, "economics_note_fa": note}


@router.get("/imports/{batch_id}")
def get_import(batch_id: int) -> dict:
    """جزئیات یک بارگذاری همراه با شواهد آشتی."""
    ensure_schema()
    with session_scope() as session:
        batch = session.get(ImportBatch, batch_id)
        if batch is None:
            raise HTTPException(status_code=404, detail="این بارگذاری یافت نشد.")
        checks = session.scalars(
            select(ImportReconciliation)
            .where(ImportReconciliation.batch_id == batch_id)
            .order_by(ImportReconciliation.check_id)
        ).all()
        payload = _batch_summary(batch)
        payload["checks"] = [
            {
                "id": c.check_id,
                "label": c.label_fa,
                "expected": c.expected_text,
                "actual": c.actual_text,
                "delta": c.delta_text,
                "tolerance": c.tolerance_text,
                "status": c.status,
                "detail": c.detail_fa,
            }
            for c in checks
        ]
        payload["economics_note_fa"] = _economics_note(
            _cost_coverage(session, batch.business_id)
        )
    return payload


def _batch_notes(batch: ImportBatch | None) -> dict:
    """یادداشت‌های بارگذاری. JSONِ خراب یعنی «نمی‌دانیم»، نه خطای ۵۰۰."""
    if batch is None or not batch.notes_json:
        return {}
    try:
        parsed = json.loads(batch.notes_json)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _batch_summary(batch: ImportBatch) -> dict:
    return {
        "id": batch.id,
        "dataset_key": batch.dataset_key,
        "revision": batch.revision,
        "session_id": batch.session_id,
        "filename": batch.filename,
        "sheet": batch.sheet_name,
        "created_at": batch.created_at,
        "date_min": batch.date_min,
        "date_max": batch.date_max,
        "rows": {
            "total": batch.rows_total,
            "clean": batch.rows_clean,
            "invalid": batch.rows_invalid,
            "duplicate": batch.rows_duplicate,
            "returns": batch.rows_returns,
        },
        "lines_inserted": batch.lines_inserted,
        "lines_updated": batch.lines_updated,
        "net_sales": _money(batch.net_sales_rial),
        "file_currency": batch.file_currency,
        "display_currency": batch.display_currency,
        "validation_status": batch.validation_status,
        "reconcile_status": batch.reconcile_status,
    }


# ---------------------------------------------------------------- کیفیت داده
@router.get("/data-quality")
def data_quality() -> dict:
    """تصویر کیفیت دفتر کل: آشتی آخرین بارگذاری + شکاف‌های شناخته‌شده.

    شکاف‌ها صریح گزارش می‌شوند (نه پنهان): خطِ بدون مشتری، بدون کالا، و
    نبودِ داده‌ی بهای تمام‌شده.
    """
    ensure_schema()
    with session_scope() as session:
        business_id = _business_id(session)
        if business_id is None:
            return _no_ledger_yet()

        latest = session.scalars(
            select(ImportBatch)
            .where(ImportBatch.business_id == business_id)
            .order_by(ImportBatch.created_at.desc())
            .limit(1)
        ).first()

        totals = session.execute(
            select(
                func.count(OrderLine.id),
                func.count(OrderLine.customer_id),
                func.count(OrderLine.product_id),
                func.count(OrderLine.cost_rial),
                func.count(OrderLine.line_date),
            ).where(OrderLine.business_id == business_id)
        ).one()
        n_lines, with_customer, with_product, with_cost, with_date = (
            int(x or 0) for x in totals
        )

        # ابعادِ §۸.۵ — شمارش‌های تازه‌ای که تا امروز محاسبه نمی‌شدند
        orders_with_branch = int(session.scalar(
            select(func.count(Order.id)).where(
                Order.business_id == business_id,
                Order.branch.isnot(None),
                Order.branch != "",
            )
        ) or 0)
        n_returns = int(session.scalar(
            select(func.count(OrderLine.id)).where(
                OrderLine.business_id == business_id,
                OrderLine.is_return.is_(True),
            )
        ) or 0)
        # سازگاریِ تاریخ فقط نسبت به بازه‌ی **اعلام‌شده‌ی همان بارگذاری** معنا
        # دارد؛ مقایسه با کلِ دفتر کل همیشه ۱۰۰٪ می‌دهد و هیچ‌چیز نمی‌گوید.
        in_range = None
        if latest is not None and latest.date_min and latest.date_max:
            in_range = int(session.scalar(
                select(func.count(OrderLine.id)).where(
                    OrderLine.batch_id == latest.id,
                    OrderLine.line_date >= latest.date_min,
                    OrderLine.line_date <= latest.date_max,
                )
            ) or 0)
            batch_lines = int(session.scalar(
                select(func.count(OrderLine.id)).where(OrderLine.batch_id == latest.id)
            ) or 0)
        else:
            batch_lines = 0
        batch_notes = _batch_notes(latest)

        counts = {
            "customers": session.scalar(
                select(func.count()).select_from(Customer)
                .where(Customer.business_id == business_id)
            ),
            "products": session.scalar(
                select(func.count()).select_from(Product)
                .where(Product.business_id == business_id)
            ),
            "orders": session.scalar(
                select(func.count()).select_from(Order)
                .where(Order.business_id == business_id)
            ),
            "lines": n_lines,
            "batches": session.scalar(
                select(func.count()).select_from(ImportBatch)
                .where(ImportBatch.business_id == business_id)
            ),
        }
        mismatches = session.scalars(
            select(ImportReconciliation)
            .where(
                ImportReconciliation.batch_id == (latest.id if latest else -1),
                ImportReconciliation.status == "MISMATCH",
            )
        ).all() if latest else []

    def _ratio(part: int) -> float:
        return round(part / n_lines, 4) if n_lines else 0.0

    cost_coverage = _ratio(with_cost)
    gaps = [
        {
            "id": "no_cost_data",
            "label_fa": (
                "بهای تمام‌شده در داده وجود ندارد" if cost_coverage == 0
                else "بهای تمام‌شده فقط برای بخشی از خطوط موجود است" if cost_coverage < 0.999
                else "بهای تمام‌شده برای همه‌ی خطوط ثبت شده است"
            ),
            "impact_fa": (
                "سود ناخالص، حاشیه و سود افزوده محاسبه نمی‌شوند؛ همه‌ی اعداد درآمدی‌اند."
                if cost_coverage < 0.999 else
                "سود ناخالص محاسبه می‌شود: روی هر خط، در CLV سودمحور، و در سود افزوده‌ی کمپین."
            ),
            "coverage": cost_coverage,
            "severity": (
                "blocking_for_profit_metrics" if cost_coverage == 0
                else "partial" if cost_coverage < 0.999 else "ok"
            ),
        },
        {
            "id": "lines_without_customer",
            "label_fa": "خطوط بدون مشتریِ قابل‌شناسایی",
            "impact_fa": "این خطوط در پرونده‌ی مشتری و پیوند بین بارگذاری‌ها دیده نمی‌شوند.",
            "coverage": _ratio(with_customer),
            "severity": "warning" if with_customer < n_lines else "ok",
        },
        {
            "id": "lines_without_product",
            "label_fa": "خطوط بدون کالای قابل‌شناسایی",
            "impact_fa": "این خطوط در تحلیل سبد و پیشنهاد کالا شرکت نمی‌کنند.",
            "coverage": _ratio(with_product),
            "severity": "warning" if with_product < n_lines else "ok",
        },
        {
            "id": "no_inventory_data",
            "label_fa": "داده‌ی موجودی انبار وجود ندارد",
            "impact_fa": "فیلتر «قابلیت تأمین» اعمال نمی‌شود؛ پیشنهادها موجودی را بررسی نکرده‌اند.",
            "coverage": 0.0,
            "severity": "known_limitation",
        },
    ]

    # نُه بُعدِ §۸.۵ — کنارِ `gaps` می‌نشیند، نه به‌جایش: `gaps` قرارداد فعلیِ
    # UI است و شکستنش یعنی پنل کیفیت خالی شود.
    dimensions = build_quality_dimensions(
        n_lines=n_lines,
        lines_with_customer=with_customer,
        lines_with_product=with_product,
        lines_with_cost=with_cost,
        lines_with_date=with_date,
        lines_in_declared_range=in_range,
        n_orders=int(counts["orders"] or 0),
        orders_with_branch=orders_with_branch,
        rows_total=latest.rows_total if latest else None,
        rows_clean=latest.rows_clean if latest else None,
        rows_duplicate=latest.rows_duplicate if latest else None,
        has_doc_type_column=bool(batch_notes.get("has_doc_type_column")),
        n_returns=n_returns,
    )
    if in_range is not None and batch_lines and in_range > batch_lines:
        in_range = batch_lines

    return {
        "available": True,
        "counts": counts,
        "dimensions": [d.to_dict() for d in dimensions],
        "quality_summary": overall_quality(dimensions),
        "latest_batch": _batch_summary(latest) if latest else None,
        "mismatches": [
            {"id": m.check_id, "label": m.label_fa, "expected": m.expected_text,
             "actual": m.actual_text, "detail": m.detail_fa}
            for m in mismatches
        ],
        "gaps": gaps,
        "economics_note_fa": ECONOMICS_NOTE_FA,
    }


# -------------------------------------------------------------------- مشتری
@router.get("/customers")
def list_customers(
    q: str | None = Query(None, description="جستجو در نام، کلید یا شماره"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    order_by: str = Query("monetary", pattern="^(monetary|recency|orders|name)$"),
) -> dict:
    """فهرست مشتریان با آخرین عکسِ ویژگی‌های هرکدام."""
    ensure_schema()
    with session_scope() as session:
        business_id = _business_id(session)
        if business_id is None:
            return {**_no_ledger_yet(), "items": [], "total": 0}

        latest_as_of = session.scalar(
            select(func.max(CustomerFeature.as_of_date))
            .where(CustomerFeature.business_id == business_id)
        )

        stmt = select(Customer, CustomerFeature).outerjoin(
            CustomerFeature,
            (CustomerFeature.customer_id == Customer.id)
            & (CustomerFeature.as_of_date == latest_as_of),
        ).where(Customer.business_id == business_id)

        if q:
            pattern = f"%{q.strip()}%"
            stmt = stmt.where(or_(
                Customer.display_name.like(pattern),
                Customer.canonical_key.like(pattern),
                Customer.phone_e164.like(pattern),
            ))

        total = session.scalar(
            select(func.count()).select_from(stmt.subquery())
        ) or 0

        ordering = {
            "monetary": CustomerFeature.monetary_rial.desc(),
            "recency": CustomerFeature.recency_days.asc(),
            "orders": CustomerFeature.n_orders.desc(),
            "name": Customer.display_name.asc(),
        }[order_by]

        rows = session.execute(
            stmt.order_by(ordering).limit(limit).offset(offset)
        ).all()
        items = [_customer_row(customer, feature) for customer, feature in rows]

    return {
        "available": True,
        "items": items,
        "total": total,
        "as_of": latest_as_of,
        "economics_note_fa": ECONOMICS_NOTE_FA,
    }


@router.get("/customers/{customer_id}")
def get_customer(customer_id: int, history_limit: int = Query(200, ge=1, le=2000)) -> dict:
    """پرونده‌ی مشتری: هویت، آخرین ویژگی‌ها، روند ویژگی و تاریخچه‌ی خرید."""
    ensure_schema()
    with session_scope() as session:
        customer = session.get(Customer, customer_id)
        if customer is None:
            raise HTTPException(status_code=404, detail="این مشتری یافت نشد.")

        snapshots = session.scalars(
            select(CustomerFeature)
            .where(CustomerFeature.customer_id == customer_id)
            .order_by(CustomerFeature.as_of_date.desc())
            .limit(24)
        ).all()

        lines = session.scalars(
            select(OrderLine)
            .where(OrderLine.customer_id == customer_id)
            .order_by(OrderLine.line_date.desc())
            .limit(history_limit)
        ).all()

        product_names = _product_names(session, {ln.product_id for ln in lines if ln.product_id})

        transitions = session.scalars(
            select(CustomerLifecycleEvent)
            .where(CustomerLifecycleEvent.customer_id == customer_id)
            .order_by(CustomerLifecycleEvent.as_of_date.desc())
            .limit(50)
        ).all()

        # وضعیت انصراف از تماس — کلیدِ افزودنی. `None` یعنی انصرافی ثبت نشده.
        suppression = session.scalar(
            select(ContactSuppression).where(
                ContactSuppression.customer_id == customer_id,
                ContactSuppression.revoked_at.is_(None),
            )
        )

        # شعبه‌ی محتمل (§۲۴.۵): از خودِ سفارش‌ها، نه از یک حدس. بدون ستون
        # شعبه، `None` با دلیل برمی‌گردد — نه «نامشخص» که مثل یک شعبه به‌نظر
        # برسد.
        order_branches = list(session.scalars(
            select(Order.branch).where(Order.customer_id == customer_id)
        ).all())

        payload = {
            "available": True,
            "customer": _customer_row(customer, snapshots[0] if snapshots else None),
            "likely_branch": likely_branch(order_branches).to_dict(),
            "contact_opt_out": None if suppression is None else {
                "reason_fa": suppression.reason_fa,
                "scope": suppression.scope,
                "source": suppression.source,
                "opted_out_at": suppression.opted_out_at,
            },
            "feature_history": [
                {
                    "as_of": s.as_of_date,
                    "n_orders": s.n_orders,
                    "monetary": _money(s.monetary_rial),
                    "recency_days": s.recency_days,
                    "segment": s.segment,
                    "lifecycle_state": s.lifecycle_state,
                    "cycle_status": s.cycle_status,
                }
                for s in snapshots
            ],
            # تایم‌لاین گذارها (§۱۱) — مهم‌ترین لحظه‌ی اقدام، همان لحظه‌ی گذار است
            "lifecycle_timeline": [
                {
                    "as_of": t.as_of_date,
                    "from": t.from_state,
                    "from_label": STATE_LABELS_FA.get(t.from_state or "", None),
                    "to": t.to_state,
                    "to_label": STATE_LABELS_FA.get(t.to_state, t.to_state),
                    "reason": t.reason_fa,
                    "basis": t.basis,
                    "basis_label": _BASIS_LABELS_FA.get(t.basis or "", t.basis),
                    "overdue_ratio": t.overdue_ratio,
                }
                for t in transitions
            ],
            "lines": [
                {
                    "date": ln.line_date,
                    "product": product_names.get(ln.product_id) or ln.raw_product_name,
                    "quantity": (
                        None if ln.quantity_milli is None else ln.quantity_milli / 1000
                    ),
                    "revenue": _money(ln.revenue_rial),
                    "is_return": ln.is_return,
                    "source_row": ln.source_row,
                    "sheet": ln.sheet_name,
                }
                for ln in lines
            ],
            "economics_note_fa": ECONOMICS_NOTE_FA,
        }
    return payload


def _product_names(session, product_ids: set[int]) -> dict[int, str]:
    if not product_ids:
        return {}
    rows = session.execute(
        select(Product.id, Product.display_name).where(Product.id.in_(sorted(product_ids)))
    ).all()
    return dict(rows)


def _customer_row(customer: Customer, feature: Any | None) -> dict:
    row = {
        "id": customer.id,
        "key": customer.canonical_key,
        "name": customer.display_name,
        # شماره‌ی کامل عمداً برنمی‌گردد؛ نمایش فهرست به آن نیاز ندارد.
        "phone_masked": mask_phone(customer.phone_e164) if customer.phone_e164 else None,
        "has_phone": bool(customer.phone_e164),
        "first_order_date": customer.first_order_date,
        "last_order_date": customer.last_order_date,
        "resolution_method": customer.resolution_method,
    }
    if feature is None:
        row["features"] = None
        return row
    row["features"] = {
        "as_of": feature.as_of_date,
        "n_orders": feature.n_orders,
        "n_lines": feature.n_lines,
        "monetary": _money(feature.monetary_rial),
        "aov": _money(feature.aov_rial),
        "clv_12m": _money(feature.clv_rial),
        "value_at_risk": _money(feature.value_at_risk_rial),
        "recency_days": feature.recency_days,
        "tenure_days": feature.tenure_days,
        "avg_gap_days": feature.avg_gap_days,
        "overdue_days": feature.overdue_days,
        "p_alive": (
            None if feature.p_alive_bp is None else round(feature.p_alive_bp / 10_000, 4)
        ),
        "segment": feature.segment,
        "lifecycle_state": feature.lifecycle_state,
        "lifecycle_label": STATE_LABELS_FA.get(
            feature.lifecycle_state or "", feature.lifecycle_state,
        ),
        "cycle_status": feature.cycle_status,
        "top_product": feature.top_product,
        # CLV سودمحور — **افزودنی**؛ `clv_12m` بالا دست‌نخورده و درآمدی می‌ماند.
        "clv_gross_profit": _clv_profit_payload(feature),
        # امتیازهای مدل. `None` یعنی مدلی فعال نیست، نه «احتمال صفر».
        "whale_probability": (
            None if feature.whale_probability_bp is None
            else round(feature.whale_probability_bp / 10_000, 4)
        ),
        "whale_model_run_id": feature.whale_model_run_id,
        "churn_probability_model": (
            None if feature.churn_probability_bp is None
            else round(feature.churn_probability_bp / 10_000, 4)
        ),
        # §۱۳.۵ «مدل پیشرفته‌ی تکرار خرید» و §۱۶.۳ «مدل ریزش» دو نمای یک چیزند:
        # احتمالِ خرید در افق = ۱ − احتمالِ ریزش در همان افق. ستونِ دومی ذخیره
        # نمی‌شود تا دو عددِ همیشه‌مکمل در دیتابیس از هم جدا نیفتند.
        "replenish_probability_model": (
            None if feature.churn_probability_bp is None
            else round(1 - feature.churn_probability_bp / 10_000, 4)
        ),
        "churn_model_run_id": feature.churn_model_run_id,
        "scored_at": feature.scored_at,
    }
    return row


def _clv_profit_payload(feature: Any) -> dict:
    """CLV سودمحور با افق‌ها و بازه — یا دلیلِ صریحِ نبودش.

    نبودِ عدد هرگز به صفر ترجمه نمی‌شود: «سودِ آینده‌اش صفر است» ادعایی است که
    نداریم؛ آنچه داریم این است که «بها کامل نیست، پس سود محاسبه نشد».
    """
    if not feature.clv_gp_basis:
        return {
            "available": False,
            "basis": None,
            "note_fa": (
                "سود ناخالصِ آینده محاسبه نشد: یا بهای همه‌ی خطوط این مشتری ثبت "
                "نشده، یا آهنگ خریدش (با کمتر از دو خرید) معلوم نیست."
            ),
        }
    return {
        "available": True,
        "basis": feature.clv_gp_basis,
        "model_version": feature.clv_model_version,
        "as_of": feature.as_of_date,
        "90d": _money(feature.clv_gp_90d_rial),
        "180d": _money(feature.clv_gp_180d_rial),
        "365d": _money(feature.clv_gp_365d_rial),
        "365d_low": _money(feature.clv_gp_365d_low_rial),
        "365d_high": _money(feature.clv_gp_365d_high_rial),
        "note_fa": (
            "این عدد **سود** است نه درآمد؛ عددِ «ارزش ۱۲ ماه آینده» درآمدی است. "
            "تصمیم خرج‌کردن باید روی سود گرفته شود."
        ),
    }


# ------------------------------------------------------------------- فرصت‌ها
# دلایل رد، از فهرست بسته‌ی §۳۰. متن آزاد قابل تجمیع نیست و سیگنال کیفیتِ
# مولدها را از دست می‌دهد؛ فهرست بسته را می‌شود شمرد و روند گرفت.
DISMISS_REASONS: dict[str, str] = {
    "not_relevant": "مشتری مرتبط نیست",
    "product_incompatible": "کالا برای این مشتری مناسب نیست",
    "bought_elsewhere": "از جای دیگری خریده است",
    "bad_contact": "اطلاعات تماس خراب است",
    "out_of_stock": "کالا موجود نیست",
    "value_too_low": "ارزشش کم است",
    "duplicate": "تکراری است",
    "other": "دلیل دیگر",
}


class OpportunityAction(BaseModel):
    """درخواست تغییر وضعیت یک فرصت."""

    actor: str | None = None
    note: str | None = None
    assigned_to: str | None = None
    snooze_until: str | None = None  # ISO میلادی
    # فقط برای «رد» — کلیدی از `DISMISS_REASONS`
    reason_code: str | None = None


@router.get("/dismiss-reasons")
def dismiss_reasons() -> dict:
    """فهرست دلایل رد — تا UI و گزارش روی یک واژگان بایستند."""
    return {
        "items": [{"code": k, "label": v} for k, v in DISMISS_REASONS.items()],
        "note_fa": (
            "بازخورد اپراتور سیگنال کیفیت است، نه حقیقت بی‌طرف: ممکن است خودِ "
            "بازخورد سوگیری داشته باشد و در تفسیر باید همین‌طور دیده شود."
        ),
    }


@router.get("/opportunities")
def list_opportunities(
    status: str = Query("open"),
    kind: str | None = Query(None),
    assigned_to: str | None = Query(None),
    # «بدون عدد ریالی» گروهِ اقدام‌های رابطه‌ای است؛ جدا خواندنش لازم است چون
    # در UI هم جدا و **بدون مبلغ** نمایش داده می‌شود (§۳۸).
    value_kind: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict:
    """صندوق فرصت‌ها — به ترتیب ارزش مورد انتظار نزولی."""
    ensure_schema()
    with session_scope() as session:
        business_id = _business_id(session)
        if business_id is None:
            return {**_no_ledger_yet(), "items": [], "total": 0}

        stmt = select(Opportunity).where(Opportunity.business_id == business_id)
        if status != "all":
            stmt = stmt.where(Opportunity.status == status)
        if kind:
            stmt = stmt.where(Opportunity.kind == kind)
        if assigned_to:
            stmt = stmt.where(Opportunity.assigned_to == assigned_to)
        if value_kind:
            stmt = stmt.where(Opportunity.value_kind == value_kind)

        total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = session.scalars(
            stmt.order_by(Opportunity.score_rial.desc()).limit(limit).offset(offset)
        ).all()

        customer_names = _customer_names(session, {o.customer_id for o in rows if o.customer_id})
        items = [_opportunity_row(o, customer_names) for o in rows]

        counts = dict(session.execute(
            select(Opportunity.status, func.count())
            .where(Opportunity.business_id == business_id)
            .group_by(Opportunity.status)
        ).all())
        # ارزشِ فهرست فقط از فرصت‌های **ریالی** جمع می‌شود؛ اقدام رابطه‌ای عمداً
        # عدد ندارد و افزودنِ صفرش به جمع، فقط توهمِ «حساب‌شده بودن» می‌سازد.
        pipeline_rial = session.scalar(
            select(func.sum(Opportunity.expected_value_rial)).where(
                Opportunity.business_id == business_id,
                Opportunity.status == "open",
                Opportunity.value_kind != VALUE_RELATIONSHIP,
            )
        ) or 0
        relationship_open = session.scalar(
            select(func.count()).select_from(Opportunity).where(
                Opportunity.business_id == business_id,
                Opportunity.status == "open",
                Opportunity.value_kind == VALUE_RELATIONSHIP,
            )
        ) or 0
        note = _economics_note(_cost_coverage(session, business_id))

    return {
        "available": True,
        "items": items,
        "total": total,
        "status_counts": counts,
        "open_pipeline": _money(int(pipeline_rial)),
        # §۳۸: این گروه با **تعداد مشتری** گزارش می‌شود، نه با مبلغ.
        "relationship_open_count": int(relationship_open),
        "relationship_value_kind": VALUE_RELATIONSHIP,
        "relationship_note_fa": (
            "اقدام‌های رابطه‌ای عمداً عدد ریالی ندارند؛ ارزششان رابطه‌ی بلندمدت "
            "است و گذاشتنِ مبلغِ حدسی رویشان، عددِ ساختگی می‌ساخت."
        ),
        "economics_note_fa": note,
    }


@router.get("/opportunities/{opportunity_id}")
def get_opportunity(opportunity_id: int) -> dict:
    """جزئیات یک فرصت با همه‌ی شواهد و تاریخچه‌ی وضعیت."""
    ensure_schema()
    with session_scope() as session:
        opportunity = session.get(Opportunity, opportunity_id)
        if opportunity is None:
            raise HTTPException(status_code=404, detail="این فرصت یافت نشد.")

        factors = session.scalars(
            select(OpportunityFactor)
            .where(OpportunityFactor.opportunity_id == opportunity_id)
            .order_by(OpportunityFactor.id)
        ).all()
        events = session.scalars(
            select(OpportunityEvent)
            .where(OpportunityEvent.opportunity_id == opportunity_id)
            .order_by(OpportunityEvent.created_at.desc())
            .limit(50)
        ).all()
        names = _customer_names(
            session, {opportunity.customer_id} if opportunity.customer_id else set()
        )
        payload = _opportunity_row(opportunity, names)
        payload["factors"] = [
            {
                "code": f.code,
                "label": f.label_fa,
                "outcome": f.outcome,
                "detail": f.detail_fa,
                "value": f.value_text,
            }
            for f in factors
        ]
        payload["events"] = [
            {
                "type": e.event_type,
                "from": e.from_status,
                "to": e.to_status,
                "actor": e.actor,
                "note": e.note_fa,
                "at": e.created_at,
            }
            for e in events
        ]
        payload["economics_note_fa"] = _economics_note(
            _cost_coverage(session, opportunity.business_id)
        )
    return payload


@router.get("/uplift")
def learned_uplift() -> dict:
    """آنچه سیستم از کمپین‌های خودش یاد گرفته است.

    برای هر ترکیبِ «نوع اقدام × حالت مشتری»: تماس چقدر اثر داشت، با چه اندازه‌ی
    نمونه، و با چه عدم‌قطعیتی. گروه‌هایی که اندازه‌گیری نشان داده تماس با آن‌ها
    بی‌فایده است، صریح علامت می‌خورند.
    """
    ensure_schema()
    try:
        from mktcore.uplift import build_uplift_table
        from mktcore.uplift.empirical import UPLIFT_REFERENCE_NOTE_FA

        table = build_uplift_table()
    except Exception:  # noqa: BLE001 - نبودِ یادگیری نباید API را بشکند
        logger.exception("ساخت جدول اثر ناموفق بود")
        return {
            "available": False,
            "note_fa": "خواندن جدول اثر ناموفق بود؛ رتبه‌بندی مثل قبل کار می‌کند.",
        }

    if not table.available:
        return {
            "available": False,
            "note_fa": (
                "هنوز داده‌ی آزمایشی وجود ندارد. برای یادگیری، کمپینی با گروه "
                "کنترل بسازید، فهرست تماس را بگیرید، و فایل دوره‌ی بعد را تحلیل "
                "کنید. تا آن زمان رتبه‌بندی دقیقاً مثل قبل کار می‌کند."
            ),
        }

    payload = table.to_dict()
    payload["reference_note_fa"] = UPLIFT_REFERENCE_NOTE_FA
    payload["method_note_fa"] = (
        "اثر هر گروه از تفاضل نرخ خرید گروه تماس‌گرفته و گروه کنترل می‌آید. "
        "گروه‌های کم‌نمونه به‌سمت میانگینِ والد منقبض می‌شوند تا نوفه رتبه‌بندی "
        "را تکان ندهد."
    )
    return payload


class OptOutRequest(BaseModel):
    """ثبت انصراف از تماس. دلیل اجباری است تا بعداً «چرا؟» پاسخ داشته باشد."""

    reason_fa: str = Field(min_length=1, max_length=500)
    scope: str = "all"
    actor: str | None = None


@router.get("/contact-suppressions")
def contact_suppressions(active_only: bool = Query(True)) -> dict:
    """دفترِ «با این‌ها تماس نگیر».

    این دفتر می‌گوید چه کسی **صریحاً رد کرده** — نه اینکه چه کسی رضایت داده.
    نبودنِ نام کسی در این فهرست «رضایت» نیست، و سیستم هم چنین ادعایی نمی‌کند.
    """
    ensure_schema()
    try:
        from mktcore.contact.register import list_suppressions

        items = list_suppressions(active_only=active_only)
    except Exception:  # noqa: BLE001 - نبودِ دفتر نباید API را بشکند
        logger.exception("خواندن دفترِ انصراف ناموفق بود")
        return {"items": [], "total": 0, "note_fa": "خواندن دفترِ انصراف ناموفق بود."}

    return {
        "items": items,
        "total": len(items),
        "note_fa": (
            "این فهرست از هر مسیر تماس احترام می‌شود: ساخت کمپین، خروجی اکسل و "
            "ارسال پیامک. حذف از فهرست تماس هرگز بی‌صدا نیست و تعدادش گزارش می‌شود."
        ),
    }


@router.post("/customers/{customer_id}/opt-out", dependencies=[Depends(require_token)])
def opt_out_customer(customer_id: int, payload: OptOutRequest) -> dict:
    """ثبت انصراف یک مشتری از تماس بازاریابی."""
    ensure_schema()
    from mktcore.contact.register import record_opt_out

    try:
        result = record_opt_out(
            customer_id=customer_id, reason_fa=payload.reason_fa,
            scope=payload.scope, created_by=payload.actor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        **result,
        "customer_id": customer_id,
        "note_fa": "از این پس هیچ مسیر تماسی این مشتری را پیشنهاد یا ارسال نمی‌کند.",
    }


@router.delete("/customers/{customer_id}/opt-out", dependencies=[Depends(require_token)])
def revoke_customer_opt_out(customer_id: int, scope: str = Query("all")) -> dict:
    """پس گرفتن انصراف. ردیف پاک نمی‌شود تا تاریخش بماند."""
    ensure_schema()
    from mktcore.contact.register import revoke_opt_out

    revoked = revoke_opt_out(customer_id=customer_id, scope=scope)
    if not revoked:
        raise HTTPException(
            status_code=404, detail="انصراف فعالی برای این مشتری ثبت نشده است.",
        )
    return {
        "customer_id": customer_id,
        "revoked": True,
        "note_fa": "انصراف پس گرفته شد؛ سابقه‌اش برای پیگیری باقی می‌ماند.",
    }


class CostRow(BaseModel):
    """یک ردیف از فایل بها."""

    product: str = Field(min_length=1, max_length=255)
    cost: float = Field(gt=0)
    # تاریخ اثر (ISO). نبودش یعنی «از همیشه» — و آن‌وقت خطوطِ قدیمی‌تر برچسب
    # «تخمینی» می‌گیرند، نه «دقیق».
    date: str | None = None


class CostImportRequest(BaseModel):
    rows: list[CostRow] = Field(min_length=1, max_length=20_000)
    display_currency: str = "تومان"


@router.post("/costs", dependencies=[Depends(require_token)])
def import_product_costs(payload: CostImportRequest) -> dict:
    """ثبت بهای کالاها — منبعِ محاسبه‌ی سود ناخالص.

    بهای تمام‌شده در فایل فروش نیست و از سیستم دیگری می‌آید، پس مسیر ورودِ جدا
    دارد. کالاهایی که به هیچ محصولی وصل نشوند **صریح گزارش می‌شوند**، نه بی‌صدا
    حذف — وگرنه پوشش بها ناقص می‌ماند و کسی نمی‌فهمد چرا.
    """
    ensure_schema()
    from mktcore.costs.register import apply_costs, import_costs

    try:
        result = import_costs(
            [r.model_dump() for r in payload.rows],
            display_currency=payload.display_currency,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    # انتساب بلافاصله انجام می‌شود تا کاربر نتیجه را همان لحظه ببیند
    result["applied"] = apply_costs()
    with session_scope() as session:
        business_id = _business_id(session)
        result["coverage"] = _cost_coverage(session, business_id)
    result["coverage_note_fa"] = _economics_note(result["coverage"])
    return result


@router.get("/cost-coverage")
def cost_coverage_report() -> dict:
    """پوشش بها — پاسخِ «چرا سود محاسبه نشد؟»."""
    ensure_schema()
    from mktcore.costs.basis import coverage_note_fa
    from mktcore.costs.register import cost_coverage

    with session_scope() as session:
        business_id = _business_id(session)
        if business_id is None:
            return {**_no_ledger_yet(), "coverage": 0.0}
        total, with_cost, ratio = cost_coverage(session, business_id)
    return {
        "available": True,
        "lines_total": total,
        "lines_with_cost": with_cost,
        "coverage": round(ratio, 4),
        "note_fa": coverage_note_fa(ratio),
    }


class MarginFloorRequest(BaseModel):
    """کف حاشیه به پایه‌ی هزارم (۲۰۰۰ = ۲۰٪). `None` یعنی برداشتنِ کف."""

    margin_floor_bp: int | None = Field(default=None, ge=0, le=10_000)


@router.get("/margin-floor")
def read_margin_floor() -> dict:
    """کف حاشیه‌ی تعیین‌شده + اینکه با این کف چه چیزی کنار گذاشته می‌شود.

    عددِ تنها کافی نیست: کاربر باید پیش از تصمیم ببیند این کف کدام کالاها را
    حذف می‌کند، وگرنه کفِ محافظه‌کارانه بی‌صدا نیمی از پیشنهادها را می‌بلعد.
    """
    ensure_schema()
    from mktcore.costs.register import margin_by_product
    from mktcore.settings_store import margin_floor_bp

    with session_scope() as session:
        business_id = _business_id(session)
        if business_id is None:
            return {**_no_ledger_yet(), "margin_floor_bp": None}
        floor = margin_floor_bp(session, business_id)
        margins = margin_by_product(session, business_id)

    below = sorted(
        (name for name, value in margins.items() if floor is not None and value < floor)
    )
    return {
        "available": True,
        "margin_floor_bp": floor,
        "products_with_margin": len(margins),
        "products_below_floor": below,
        "note_fa": (
            "کف حاشیه تعیین نشده است؛ فیلترِ حاشیه هیچ پیشنهادی را رد نمی‌کند و "
            "در گزارش «بررسی نشد» ثبت می‌شود."
            if floor is None else
            f"با کف {floor / 100:.1f}٪، {len(below)} کالا از "
            f"{len(margins)} کالای دارای حاشیه رد می‌شوند."
        ),
    }


@router.put("/margin-floor", dependencies=[Depends(require_token)])
def write_margin_floor(payload: MarginFloorRequest) -> dict:
    """ثبت کف حاشیه — تصمیمِ کاربر است، نه حدسِ سیستم.

    تا وقتی این عدد تعیین نشود `filter_margin_floor` صادقانه «بررسی نشد» ثبت
    می‌کند؛ حدس‌زدنِ کف یعنی رد کردن پیشنهاد بر پایه‌ی معیاری که کسی نگفته.
    """
    ensure_schema()
    from mktcore.settings_store import set_margin_floor_bp

    try:
        set_margin_floor_bp(payload.margin_floor_bp)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return read_margin_floor()


class CapacityRequest(BaseModel):
    """ظرفیت روزانه‌ی پیگیری تیم. `None` یعنی برداشتنش."""

    daily_capacity: int | None = Field(default=None, ge=1, le=100_000)


@router.get("/operator-capacity")
def read_operator_capacity() -> dict:
    """ظرفیت پیگیری تیم + اینکه با این عدد چه چیزی کنار می‌ماند (§۲۵).

    مثل کف حاشیه، عددِ تنها کافی نیست: کاربر باید ببیند این ظرفیت چند فرصتِ
    باز را بیرون می‌گذارد، وگرنه عددِ محافظه‌کارانه بی‌صدا صندوق را می‌بُرد.
    """
    ensure_schema()
    from mktcore.settings_store import daily_capacity

    with session_scope() as session:
        business_id = _business_id(session)
        if business_id is None:
            return {**_no_ledger_yet(), "daily_capacity": None}
        capacity = daily_capacity(session, business_id)
        open_count = session.scalar(
            select(func.count(Opportunity.id)).where(
                Opportunity.business_id == business_id,
                Opportunity.status == "open",
            )
        ) or 0

    return {
        "available": True,
        "daily_capacity": capacity,
        "open_opportunities": open_count,
        "note_fa": (
            "ظرفیت پیگیری تیم تعیین نشده است؛ فیلترِ ظرفیت هیچ فرصتی را کنار "
            "نمی‌گذارد و در گزارش «بررسی نشد» ثبت می‌شود."
            if capacity is None else
            f"با ظرفیت {capacity} مورد، از {open_count} فرصتِ باز "
            f"{max(0, open_count - capacity)} مورد بیرون از ظرفیت می‌مانند."
        ),
    }


@router.put("/operator-capacity", dependencies=[Depends(require_token)])
def write_operator_capacity(payload: CapacityRequest) -> dict:
    """ثبت ظرفیت — تصمیمِ کاربر است، نه حدسِ سیستم."""
    ensure_schema()
    from mktcore.settings_store import set_daily_capacity

    try:
        set_daily_capacity(payload.daily_capacity)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return read_operator_capacity()


@router.get("/experiment-plan")
def experiment_plan(
    target_effect: float = Query(0.05, gt=0.0, lt=1.0),
    holdout_pct: int = Query(20, ge=5, le=50),
) -> dict:
    """کمپین بعدی را روی چه گروهی، و با چه اندازه‌ای؟

    جدولِ اثر (فاز ۴) منتظر است: تا کمپینی اجرا نشود چیزی یاد نمی‌گیرد. و
    کمپین‌ها به‌ترتیبِ اتفاق ساخته می‌شوند، نه به‌ترتیبِ آنچه نمی‌دانیم. این
    پاسخ ترتیب را برمی‌گرداند: گروه‌ها به‌ترتیبِ **تماسِ اندازه‌گیری‌نشده** —
    یعنی جایی که بیشترین پیام فرستاده می‌شود و کم‌ترین شواهد پشتش است.
    """
    ensure_schema()
    try:
        from mktcore.experiments import build_experiment_plan

        plan = build_experiment_plan(
            target_effect=target_effect, holdout_pct=holdout_pct,
        )
    except Exception:  # noqa: BLE001 - نبودِ برنامه نباید API را بشکند
        logger.exception("ساخت برنامه‌ی آزمایش ناموفق بود")
        return {
            "available": False,
            "note_fa": "ساخت برنامه‌ی آزمایش ناموفق بود؛ بقیه‌ی سیستم مثل قبل کار می‌کند.",
        }

    payload = plan.to_dict()
    payload["method_note_fa"] = (
        "اولویت بر پایه‌ی «تماسِ اندازه‌گیری‌نشده» است: فرصت‌های تماس در گروهی "
        "که شواهدش قطعی نیست. گروهی که اثرش (یا بی‌فایدگی‌اش) اثبات شده، دوباره "
        "پیشنهاد نمی‌شود. واحدِ شمارش «فرصتِ تماس» است نه «نفر»: یک مشتری می‌تواند "
        "در دو نوع اقدام حاضر باشد و آن دو تماسِ جداست."
    )
    payload["holdout_note_fa"] = (
        "گروه کنترل ۲۰٪ پیشنهاد می‌شود چون آماری کاراتر از ۱۰٪ است: برای همان "
        "قدرت تفکیک، کل کمپین حدود نصف می‌شود."
    )
    if not payload.get("cells"):
        payload["note_fa"] = (
            "هنوز فرصت بازی در صندوق نیست تا برنامه‌ی آزمایش ساخته شود. "
            "اول یک فایل فروش را تحلیل کنید."
        )
    return payload


@router.get("/opportunity-quality")
def opportunity_quality() -> dict:
    """کیفیت مولدها از دید اپراتور — کدام مولد بیشتر رد می‌شود و چرا.

    این سیگنالِ بهبود است، نه داوریِ نهایی: ممکن است اپراتور یک نوع پیشنهاد را
    به‌دلیل ناآشنایی رد کند، نه به‌دلیل غلط بودنش.
    """
    ensure_schema()
    with session_scope() as session:
        business_id = _business_id(session)
        if business_id is None:
            return _no_ledger_yet()

        rows = session.execute(
            select(Opportunity.generator, Opportunity.status, func.count())
            .where(Opportunity.business_id == business_id)
            .group_by(Opportunity.generator, Opportunity.status)
        ).all()
        by_generator: dict[str, dict[str, int]] = {}
        for generator, status, count in rows:
            by_generator.setdefault(str(generator), {})[str(status)] = int(count)

        events = session.execute(
            select(Opportunity.generator, OpportunityEvent.payload_json, func.count())
            .join(OpportunityEvent, OpportunityEvent.opportunity_id == Opportunity.id)
            .where(
                Opportunity.business_id == business_id,
                OpportunityEvent.event_type == "dismiss",
                OpportunityEvent.payload_json.isnot(None),
            )
            .group_by(Opportunity.generator, OpportunityEvent.payload_json)
        ).all()

    reasons: dict[str, dict[str, int]] = {}
    for generator, payload_json, count in events:
        try:
            code = (json.loads(payload_json) or {}).get("reason_code")
        except (TypeError, ValueError):
            continue
        if code:
            label = DISMISS_REASONS.get(code, code)
            reasons.setdefault(str(generator), {})[label] = (
                reasons.setdefault(str(generator), {}).get(label, 0) + int(count)
            )

    items = []
    for generator, statuses in sorted(by_generator.items()):
        total = sum(statuses.values())
        acted = statuses.get("accepted", 0) + statuses.get("done", 0)
        dismissed = statuses.get("dismissed", 0)
        decided = acted + dismissed
        items.append({
            "generator": generator,
            "total": total,
            "accepted": acted,
            "dismissed": dismissed,
            # نرخ فقط روی فرصت‌هایی که کاربر واقعاً درباره‌شان تصمیم گرفته
            "acceptance_rate": round(acted / decided, 3) if decided else None,
            "undecided": total - decided,
            "dismiss_reasons": reasons.get(generator, {}),
        })

    return {
        "available": True,
        "items": items,
        "note_fa": (
            "بازخورد اپراتور سیگنال کیفیت است، نه حقیقت بی‌طرف. نرخ پذیرش فقط روی "
            "فرصت‌هایی محاسبه می‌شود که درباره‌شان تصمیمی گرفته شده است."
        ),
    }


_TRANSITIONS = {
    "accept": ("accepted", "پذیرفته شد و در دستور کار قرار گرفت."),
    "dismiss": ("dismissed", "رد شد."),
    "snooze": ("snoozed", "به تعویق افتاد."),
    "done": ("done", "انجام شد."),
    "reopen": ("open", "دوباره باز شد."),
}


@router.post(
    "/opportunities/{opportunity_id}/{action}",
    dependencies=[Depends(require_token)],
)
def act_on_opportunity(
    opportunity_id: int, action: str, body: OpportunityAction | None = None,
) -> dict:
    """تغییر وضعیت یک فرصت. هر تغییر یک رخداد ماندگار ثبت می‌کند."""
    if action not in _TRANSITIONS:
        raise HTTPException(
            status_code=400,
            detail=f"اقدام نامعتبر است؛ مجاز: {'، '.join(_TRANSITIONS)}",
        )
    payload = body or OpportunityAction()
    new_status, default_note = _TRANSITIONS[action]
    if action == "snooze" and not payload.snooze_until:
        raise HTTPException(
            status_code=400, detail="برای تعویق، تاریخ «snooze_until» لازم است.",
        )
    if payload.reason_code and payload.reason_code not in DISMISS_REASONS:
        raise HTTPException(
            status_code=400,
            detail=f"دلیل نامعتبر است؛ مجاز: {'، '.join(DISMISS_REASONS)}",
        )
    reason_label = DISMISS_REASONS.get(payload.reason_code or "")

    ensure_schema()
    with session_scope() as session:
        opportunity = session.get(Opportunity, opportunity_id)
        if opportunity is None:
            raise HTTPException(status_code=404, detail="این فرصت یافت نشد.")

        previous = opportunity.status
        opportunity.status = new_status
        opportunity.status_reason_fa = reason_label or payload.note or default_note
        opportunity.updated_at = _now()
        if payload.assigned_to is not None:
            opportunity.assigned_to = payload.assigned_to
        if action == "snooze":
            opportunity.snooze_until = payload.snooze_until
        if action == "reopen":
            opportunity.snooze_until = None

        session.add(OpportunityEvent(
            opportunity_id=opportunity_id,
            event_type=action,
            from_status=previous,
            to_status=new_status,
            actor=payload.actor or "user",
            note_fa=reason_label or payload.note or default_note,
            # کد دلیل جدا از متن ذخیره می‌شود تا قابل شمارش و تجمیع بماند
            payload_json=(
                json.dumps({"reason_code": payload.reason_code}, ensure_ascii=False)
                if payload.reason_code else None
            ),
        ))
        names = _customer_names(
            session, {opportunity.customer_id} if opportunity.customer_id else set()
        )
        result = _opportunity_row(opportunity, names)
    return result


def _now() -> float:
    from mktcore.db.base import now_ts

    return now_ts()


def _customer_names(session, customer_ids: set[int]) -> dict[int, str]:
    if not customer_ids:
        return {}
    rows = session.execute(
        select(Customer.id, Customer.display_name).where(Customer.id.in_(sorted(customer_ids)))
    ).all()
    return {cid: name for cid, name in rows if name}


def _opportunity_row(opportunity: Opportunity, customer_names: dict[int, str]) -> dict:
    return {
        "id": opportunity.id,
        "kind": opportunity.kind,
        "title": opportunity.title_fa,
        "action": opportunity.action_fa,
        "reason": opportunity.reason_fa,
        "message": opportunity.message_fa,
        "customer_id": opportunity.customer_id,
        "customer_name": customer_names.get(opportunity.customer_id or -1),
        "product_id": opportunity.product_id,
        "expected_value": _money(opportunity.expected_value_rial),
        "value_kind": opportunity.value_kind,
        "probability": (
            None if opportunity.probability_bp is None
            else round(opportunity.probability_bp / 10_000, 4)
        ),
        "confidence": opportunity.confidence,
        "status": opportunity.status,
        "status_reason": opportunity.status_reason_fa,
        "assigned_to": opportunity.assigned_to,
        "owner_hint": opportunity.owner_hint,
        "due_date": opportunity.due_date,
        "expires_at": opportunity.expires_at,
        "snooze_until": opportunity.snooze_until,
        "seen_count": opportunity.seen_count,
        "generator": opportunity.generator,
        "generator_version": opportunity.generator_version,
        # صداقت علّی: این‌ها بدون شواهد آزمایشی NULL می‌مانند و UI هم همین را می‌گوید.
        "attributed_revenue": _money(opportunity.attributed_revenue_rial),
        "incremental_revenue": _money(opportunity.incremental_revenue_rial),
        "causal_note_fa": (
            "اثر علّی این فرصت اندازه‌گیری نشده است؛ برای آن به گروه کنترل نیاز است."
        ),
        "created_at": opportunity.created_at,
        "updated_at": opportunity.updated_at,
    }


__all__ = ["ECONOMICS_NOTE_FA", "router"]
