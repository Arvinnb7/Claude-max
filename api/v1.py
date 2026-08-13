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

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, or_, select

from mktcore.config import get_settings
from mktcore.db.engine import session_scope
from mktcore.db.migrations import ensure_schema
from mktcore.db.models import (
    Business,
    Customer,
    CustomerFeature,
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
from mktcore.money import money_payload

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


def _business_id(session, slug: str = _DEFAULT_SLUG) -> int | None:
    return session.scalar(select(Business.id).where(Business.slug == slug))


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
            ).where(OrderLine.business_id == business_id)
        ).one()
        n_lines, with_customer, with_product, with_cost = (int(x or 0) for x in totals)

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
                "زیرساخت سود موجود است؛ محاسبه‌ی سود در فاز بعد فعال می‌شود."
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

    return {
        "available": True,
        "counts": counts,
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

        payload = {
            "available": True,
            "customer": _customer_row(customer, snapshots[0] if snapshots else None),
            "feature_history": [
                {
                    "as_of": s.as_of_date,
                    "n_orders": s.n_orders,
                    "monetary": _money(s.monetary_rial),
                    "recency_days": s.recency_days,
                    "segment": s.segment,
                    "cycle_status": s.cycle_status,
                }
                for s in snapshots
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
        "cycle_status": feature.cycle_status,
        "top_product": feature.top_product,
    }
    return row


# ------------------------------------------------------------------- فرصت‌ها
class OpportunityAction(BaseModel):
    """درخواست تغییر وضعیت یک فرصت."""

    actor: str | None = None
    note: str | None = None
    assigned_to: str | None = None
    snooze_until: str | None = None  # ISO میلادی


@router.get("/opportunities")
def list_opportunities(
    status: str = Query("open"),
    kind: str | None = Query(None),
    assigned_to: str | None = Query(None),
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
        pipeline_rial = session.scalar(
            select(func.sum(Opportunity.expected_value_rial)).where(
                Opportunity.business_id == business_id,
                Opportunity.status == "open",
            )
        ) or 0
        note = _economics_note(_cost_coverage(session, business_id))

    return {
        "available": True,
        "items": items,
        "total": total,
        "status_counts": counts,
        "open_pipeline": _money(int(pipeline_rial)),
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


_TRANSITIONS = {
    "accept": ("accepted", "پذیرفته شد و در دستور کار قرار گرفت."),
    "dismiss": ("dismissed", "رد شد."),
    "snooze": ("snoozed", "به تعویق افتاد."),
    "done": ("done", "انجام شد."),
    "reopen": ("open", "دوباره باز شد."),
}


@router.post("/opportunities/{opportunity_id}/{action}")
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

    ensure_schema()
    with session_scope() as session:
        opportunity = session.get(Opportunity, opportunity_id)
        if opportunity is None:
            raise HTTPException(status_code=404, detail="این فرصت یافت نشد.")

        previous = opportunity.status
        opportunity.status = new_status
        opportunity.status_reason_fa = payload.note or default_note
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
            note_fa=payload.note or default_note,
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
