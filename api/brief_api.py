"""خروجیِ اجراییِ روزانه (§۳۸) و بارِ اپراتورها — فقط خواندن از دفتر کل.

## قاعده‌ای که این فایل پین می‌کند

§۳۸: «مقدارِ پیش‌بینی‌شده و مقدارِ افزوده‌ی اثبات‌شده هرگز بدون برچسبِ روشن
کنار هم گذاشته نمی‌شوند.» این‌جا آن دو **دو بلوکِ جدا** با منبعِ جدا هستند:

* پیش‌بینی = جمعِ ارزشِ مورد انتظارِ فرصت‌های زنده (غیرعلّی، از موتورِ قاعده‌محور).
* اثبات‌شده = جمعِ «افزوده»ی کمپین‌هایی که حکمِ `proven` گرفته‌اند (با گروه کنترل).

هیچ‌کدام از دیگری کم یا به دیگری اضافه نمی‌شود. چیزی که داده‌اش نیست
(سودِ هر فرصت، موجودی) `None` است و یادداشت می‌گوید چرا — نه صفر.
"""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi import APIRouter
from sqlalchemy import func, select

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

from mktcore.campaigns.analysis import VERDICT_LABELS_FA, VERDICT_PROVEN  # noqa: E402
from mktcore.db.base import now_ts  # noqa: E402
from mktcore.db.engine import session_scope  # noqa: E402
from mktcore.db.migrations import ensure_schema  # noqa: E402
from mktcore.db.models import (  # noqa: E402
    Campaign,
    CustomerLifecycleEvent,
    ImportBatch,
    ImportQuarantine,
    JobRun,
    Opportunity,
    OrderLine,
)
from mktcore.lifecycle import STATE_LABELS_FA  # noqa: E402
from mktcore.lifecycle.states import STATE_AT_RISK, STATE_VIP  # noqa: E402
from mktcore.money import format_rial_fa  # noqa: E402
from mktcore.opportunities.contract import VALUE_RELATIONSHIP  # noqa: E402
from mktcore.opportunities.engine import (  # noqa: E402
    STATUS_ACCEPTED,
    STATUS_OPEN,
    STATUS_SNOOZED,
)
from mktcore.settings_store import daily_capacity  # noqa: E402

from .campaigns_api import _report as _campaign_report  # noqa: E402
from .v1 import (  # noqa: E402
    EXPIRING_SOON_DAYS,
    _batch_notes,
    _business_id,
    _cost_coverage,
    _display_currency,
    _economics_note,
    _latest_as_of,
    _money,
    _plus_days,
)

router = APIRouter(prefix="/api/v1", tags=["daily-brief"])

# فرصت‌هایی که «زنده» حساب می‌شوند: هنوز کسی رویشان کار می‌کند یا می‌تواند بکند.
LIVE_STATUSES: tuple[str, ...] = (STATUS_OPEN, STATUS_ACCEPTED, STATUS_SNOOZED)

FORECAST_LABEL_FA = "پیش‌بینیِ درآمد از فرصت‌های زنده — غیرعلّی، هنوز اثبات نشده"
PROVEN_LABEL_FA = "افزوده‌ی اثبات‌شده — از کمپین‌های با گروه کنترل و حکمِ «اثبات‌شده»"
NOT_VALIDATED_LABEL_FA = (
    "پیش‌بینیِ قاعده‌محور که هنوز با آزمایش سنجیده نشده — با «اثبات‌شده» جمع نکنید"
)
GROSS_PROFIT_UNCHECKED_FA = (
    "بررسی نشد: ارزشِ هر فرصت درآمدی است و سودِ به‌ازای فرصت هنوز محاسبه نمی‌شود "
    "(§۲۳.۱ در دورهای بعد)."
)
STOCK_UNCHECKED_FA = "بررسی نشد: داده‌ی موجودی به سیستم داده نشده است."
NO_RUN_FA = "موتورِ فرصت هنوز اجرا نشده است؛ خروجیِ روزانه بدون اجرا معنا ندارد."
NO_LEDGER_FA = "هنوز بارگذاری‌ای در دفتر کل ثبت نشده است."
UNIT_REVIEW_CODES: tuple[str, ...] = ("C04", "C05", "unknown_currency")


# ---------------------------------------------------------------- خلاصه‌ی روزانه
@router.get("/daily-brief")
def daily_brief() -> dict:
    """خروجیِ اجراییِ روزانه‌ی §۳۸ — از دفتر کل، بدون اجرای موتور."""
    ensure_schema()
    with session_scope() as session:
        business_id = _business_id(session)
        if business_id is None:
            return {"available": False, "reason_fa": NO_LEDGER_FA}
        as_of = _latest_as_of(session, business_id)
        if as_of is None:
            return {"available": False, "reason_fa": NO_RUN_FA}

        data_through = session.scalar(
            select(func.max(OrderLine.line_date)).where(OrderLine.business_id == business_id)
        )
        coverage = _cost_coverage(session, business_id)
        forecast = _forecast_block(session, business_id)
        proven = _proven_block(session, business_id)
        groups = _groups(session, business_id)
        urgent = _urgent_block(session, business_id, as_of)

    payload = {
        "available": True,
        "as_of": as_of,
        "data_through": data_through,
        "generated_at": now_ts(),
        "valid_opportunities": forecast["count"],
        "forecast": forecast,
        "proven": proven,
        "not_validated": {
            "label_fa": NOT_VALIDATED_LABEL_FA,
            "count": forecast["count"],
            "revenue": forecast["revenue"],
            "gross_profit": _money(None),
            "gross_profit_note_fa": GROSS_PROFIT_UNCHECKED_FA,
        },
        "groups": groups,
        "urgent": urgent,
        "economics_note_fa": _economics_note(coverage),
        "cost_coverage_bp": int(round(coverage * 10_000)),
        "separation_note_fa": (
            "«پیش‌بینی» و «اثبات‌شده» دو منبعِ جدا دارند و هرگز جمع نمی‌شوند؛ "
            "«اثبات‌شده» فقط از آزمایشِ با گروه کنترل می‌آید (§۳۸)."
        ),
    }
    payload["text_fa"] = _render_text(payload)
    return payload


def _forecast_block(session, business_id: int) -> dict:
    """جمعِ ارزشِ مورد انتظارِ فرصت‌های زنده‌ی ریالی — همان قاعده‌ی `open_pipeline`."""
    count, total = session.execute(
        select(func.count(Opportunity.id), func.sum(Opportunity.expected_value_rial)).where(
            Opportunity.business_id == business_id,
            Opportunity.status.in_(LIVE_STATUSES),
            Opportunity.value_kind != VALUE_RELATIONSHIP,
        )
    ).one()
    accepted_count, accepted_total = session.execute(
        select(func.count(Opportunity.id), func.sum(Opportunity.expected_value_rial)).where(
            Opportunity.business_id == business_id,
            Opportunity.status == STATUS_ACCEPTED,
            Opportunity.value_kind != VALUE_RELATIONSHIP,
        )
    ).one()
    relationship = session.scalar(
        select(func.count(Opportunity.id)).where(
            Opportunity.business_id == business_id,
            Opportunity.status.in_(LIVE_STATUSES),
            Opportunity.value_kind == VALUE_RELATIONSHIP,
        )
    ) or 0
    return {
        "label_fa": FORECAST_LABEL_FA,
        "statuses": list(LIVE_STATUSES),
        "count": int(count or 0),
        "revenue": _money(int(total or 0)),
        "accepted_count": int(accepted_count or 0),
        "accepted_revenue": _money(int(accepted_total or 0)),
        "relationship_count": int(relationship),
        "relationship_value_kind": VALUE_RELATIONSHIP,
        # سودِ هر فرصت محاسبه نمی‌شود؛ عددِ حدسی از حاشیه‌ی میانگین، سود نیست.
        "gross_profit": _money(None),
        "gross_profit_note_fa": GROSS_PROFIT_UNCHECKED_FA,
    }


def _proven_block(session, business_id: int) -> dict:
    """جمعِ «افزوده»ی کمپین‌های اثبات‌شده. هر کمپین با همان گزارشِ مسیرِ کمپین."""
    campaigns = session.scalars(
        select(Campaign).where(Campaign.business_id == business_id)
        .order_by(Campaign.created_at.desc())
    ).all()
    by_verdict: dict[str, int] = {}
    proven_ids: list[int] = []
    revenue = 0
    gross_profit: int | None = 0
    gp_missing = 0
    for campaign in campaigns:
        report = _campaign_report(session, campaign.id)
        verdict = report["verdict"]
        by_verdict[verdict] = by_verdict.get(verdict, 0) + 1
        if verdict != VERDICT_PROVEN:
            continue
        proven_ids.append(campaign.id)
        revenue += int(report["incremental_revenue_rial"] or 0)
        gp = report.get("incremental_gross_profit_rial")
        if gp is None:
            gp_missing += 1
        elif gross_profit is not None:
            gross_profit += int(gp)
    if gp_missing:
        # یک کمپینِ بی‌بها یعنی جمعِ سود ناقص است؛ ناقص را کامل جا نمی‌زنیم.
        gross_profit = None
    return {
        "label_fa": PROVEN_LABEL_FA,
        "campaigns_total": len(campaigns),
        "campaigns_by_verdict": {
            code: {"count": n, "label_fa": VERDICT_LABELS_FA.get(code, code)}
            for code, n in sorted(by_verdict.items())
        },
        "proven_campaign_ids": proven_ids,
        "incremental_revenue": _money(revenue if proven_ids else None),
        "incremental_gross_profit": _money(gross_profit if proven_ids else None),
        "gross_profit_note_fa": (
            None if proven_ids and gp_missing == 0 else (
                "هنوز کمپینِ اثبات‌شده‌ای نیست." if not proven_ids else
                f"در {gp_missing} کمپینِ اثبات‌شده پوششِ بها کامل نبود؛ جمعِ سود گزارش نمی‌شود."
            )
        ),
    }


def _groups(session, business_id: int) -> list[dict]:
    """گروه‌های فرصت به‌ازای نوع — مرتب بر ارزش؛ گروهِ رابطه‌ای فقط با تعداد و در انتها."""
    rows = session.execute(
        select(
            Opportunity.kind,
            Opportunity.value_kind,
            func.count(Opportunity.id),
            func.count(func.distinct(Opportunity.customer_id)),
            func.sum(Opportunity.expected_value_rial),
        )
        .where(
            Opportunity.business_id == business_id,
            Opportunity.status.in_(LIVE_STATUSES),
        )
        .group_by(Opportunity.kind, Opportunity.value_kind)
    ).all()
    monetary: list[dict] = []
    relational: list[dict] = []
    for kind, value_kind, count, customers, total in rows:
        is_relationship = value_kind == VALUE_RELATIONSHIP
        entry = {
            "kind": kind,
            "opportunities": int(count or 0),
            "customers": int(customers or 0),
            "value_kind": value_kind,
            "forecast_revenue": _money(None if is_relationship else int(total or 0)),
            "forecast_gross_profit": _money(None),
            "gross_profit_note_fa": GROSS_PROFIT_UNCHECKED_FA,
        }
        (relational if is_relationship else monetary).append(entry)
    monetary.sort(key=lambda g: (-(g["forecast_revenue"]["rial"] or 0), g["kind"]))
    relational.sort(key=lambda g: (-g["customers"], g["kind"]))
    return monetary + relational


def _urgent_block(session, business_id: int, as_of: str) -> dict:
    open_rows = (
        Opportunity.business_id == business_id,
        Opportunity.status == STATUS_OPEN,
        Opportunity.expires_at.isnot(None),
    )
    expiring_today = session.scalar(
        select(func.count(Opportunity.id)).where(*open_rows, Opportunity.expires_at <= as_of)
    ) or 0
    expiring_soon = session.scalar(
        select(func.count(Opportunity.id)).where(
            *open_rows, Opportunity.expires_at <= _plus_days(as_of, EXPIRING_SOON_DAYS),
        )
    ) or 0
    # گذارِ «ویژه → در خطر ریزش» در همان تاریخِ مرجع — از رویدادهای ماندگارِ چرخه‌ی عمر.
    vip_at_risk = session.scalar(
        select(func.count(CustomerLifecycleEvent.id)).where(
            CustomerLifecycleEvent.business_id == business_id,
            CustomerLifecycleEvent.as_of_date == as_of,
            CustomerLifecycleEvent.from_state == STATE_VIP,
            CustomerLifecycleEvent.to_state == STATE_AT_RISK,
        )
    ) or 0
    quarantine_open = session.scalar(
        select(func.count(ImportQuarantine.id)).where(
            ImportQuarantine.business_id == business_id,
            ImportQuarantine.resolved_at.is_(None),
        )
    ) or 0
    dead_letter = session.scalar(
        select(func.count(JobRun.id)).where(JobRun.status == JobRun.STATUS_DEAD_LETTER)
    ) or 0
    newest = session.scalars(
        select(ImportBatch).where(ImportBatch.business_id == business_id)
        .order_by(ImportBatch.created_at.desc()).limit(1)
    ).first()
    blocked_by = list(_batch_notes(newest).get("blocked_by") or []) if newest is not None else []
    blocked_codes = sorted({str(b.get("code") if isinstance(b, dict) else b) for b in blocked_by})
    unit_review = any(code in UNIT_REVIEW_CODES for code in blocked_codes)
    return {
        "expiring_today": int(expiring_today),
        "expiring_soon": int(expiring_soon),
        "expiring_soon_days": EXPIRING_SOON_DAYS,
        "vip_entered_at_risk": int(vip_at_risk),
        "vip_entered_at_risk_label_fa": (
            f"{STATE_LABELS_FA[STATE_VIP]} → {STATE_LABELS_FA[STATE_AT_RISK]}"
        ),
        "quarantine_open_rows": int(quarantine_open),
        "latest_import_blocked": newest is not None and newest.reconcile_status == "BLOCKED",
        "latest_import_blocked_by": blocked_codes,
        "financial_unit_review_needed": unit_review,
        "dead_letter_runs": int(dead_letter),
        # §۳۸ «suppressed due to insufficient stock» — بدون داده‌ی موجودی سنجیده نمی‌شود.
        "suppressed_by_stock": None,
        "suppressed_by_stock_note_fa": STOCK_UNCHECKED_FA,
    }


def _fmt(money: dict) -> str:
    return money["display_text"] if money["rial"] is not None else "بررسی نشد"


def _render_text(p: dict) -> str:
    """همان ساختار، به‌صورت متن — برای لاگ، ایمیل یا چاپ. هیچ عددِ تازه‌ای نمی‌سازد."""
    lines = [
        f"تاریخِ مرجع: {p['as_of']}",
        f"داده تا: {p['data_through'] or 'نامشخص'}",
        "",
        f"فرصت‌های زنده: {p['valid_opportunities']}",
        f"پیش‌بینیِ درآمد (غیرعلّی): {_fmt(p['forecast']['revenue'])}",
        f"پیش‌بینیِ سود ناخالص: {_fmt(p['forecast']['gross_profit'])}",
        f"افزوده‌ی اثبات‌شده (با گروه کنترل): {_fmt(p['proven']['incremental_revenue'])}",
        f"سودِ افزوده‌ی اثبات‌شده: {_fmt(p['proven']['incremental_gross_profit'])}",
        f"پیش‌بینیِ هنوز سنجیده‌نشده: {_fmt(p['not_validated']['revenue'])}",
        "",
        "گروه‌های پرارزش:",
    ]
    for i, g in enumerate(p["groups"], start=1):
        if g["value_kind"] == VALUE_RELATIONSHIP:
            lines.append(f"{i}. {g['kind']}: {g['customers']} مشتری (بدون عدد ریالی)")
        else:
            lines.append(f"{i}. {g['kind']}: {g['customers']} مشتری، {_fmt(g['forecast_revenue'])}")
    u = p["urgent"]
    lines += [
        "",
        "فوری:",
        f"- {u['expiring_today']} فرصت امروز منقضی می‌شود ({u['expiring_soon']} تا {u['expiring_soon_days']} روز).",
        f"- {u['vip_entered_at_risk']} مشتریِ ویژه به «در خطر ریزش» رفت.",
        f"- سرکوب به‌خاطر موجودی: {u['suppressed_by_stock_note_fa']}",
        f"- {u['quarantine_open_rows']} ردیفِ قرنطینه‌ی باز"
        + ("؛ آخرین بارگذاری به‌خاطر واحدِ مالی مسدود است." if u["financial_unit_review_needed"] else "."),
        f"- {u['dead_letter_runs']} کارِ زمان‌بندی‌شده در صفِ مرده.",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------- بارِ اپراتورها
UNASSIGNED_KEY = "__unassigned__"


@router.get("/operator-load")
def operator_load() -> dict:
    """فرصت‌های زنده به‌ازای مسئول؛ بی‌مسئول‌ها در سطلِ جدا.

    ظرفیت فقط **کلی** تنظیم می‌شود (§۲۸ «ظرفیتِ روزانه‌ی تیم»)؛ ظرفیتِ هر
    اپراتور تنظیمی ندارد و «تنظیم نشد» گزارش می‌شود — نه تقسیمِ مساویِ حدسی.
    """
    ensure_schema()
    with session_scope() as session:
        business_id = _business_id(session)
        if business_id is None:
            return {"available": False, "reason_fa": NO_LEDGER_FA, "operators": []}
        as_of = _latest_as_of(session, business_id)
        soon = _plus_days(as_of, EXPIRING_SOON_DAYS) if as_of else None
        rows = session.execute(
            select(
                Opportunity.assigned_to,
                Opportunity.status,
                func.count(Opportunity.id),
                func.sum(
                    func.iif(
                        Opportunity.value_kind != VALUE_RELATIONSHIP,
                        Opportunity.expected_value_rial, 0,
                    )
                ),
                func.sum(
                    func.iif(
                        (Opportunity.expires_at.isnot(None))
                        & (Opportunity.expires_at <= (soon or "")),
                        1, 0,
                    )
                ),
            )
            .where(
                Opportunity.business_id == business_id,
                Opportunity.status.in_(LIVE_STATUSES),
            )
            .group_by(Opportunity.assigned_to, Opportunity.status)
        ).all()
        capacity = daily_capacity(session, business_id)

    buckets: dict[str, dict] = {}
    for assigned_to, status, count, value, expiring in rows:
        key = assigned_to or UNASSIGNED_KEY
        bucket = buckets.setdefault(key, {
            "assigned_to": assigned_to,
            "unassigned": assigned_to is None,
            "count": 0, "by_status": {}, "value_rial": 0, "expiring_soon": 0,
        })
        bucket["count"] += int(count or 0)
        bucket["by_status"][status] = bucket["by_status"].get(status, 0) + int(count or 0)
        bucket["value_rial"] += int(value or 0)
        bucket["expiring_soon"] += int(expiring or 0) if soon else 0
    operators = []
    for bucket in buckets.values():
        bucket["value"] = _money(bucket.pop("value_rial"))
        operators.append(bucket)
    operators.sort(key=lambda b: (b["unassigned"], -b["count"], b["assigned_to"] or ""))
    total = sum(b["count"] for b in operators)
    return {
        "available": True,
        "as_of": as_of,
        "statuses": list(LIVE_STATUSES),
        "total": total,
        "operators": operators,
        "unassigned_count": next((b["count"] for b in operators if b["unassigned"]), 0),
        "team_daily_capacity": capacity,
        "team_capacity_note_fa": (
            None if capacity is not None else "ظرفیتِ روزانه‌ی تیم تنظیم نشده است (بررسی نشد)."
        ),
        "per_operator_capacity": None,
        "per_operator_capacity_note_fa": (
            "ظرفیتِ هر اپراتور تنظیم نشده است؛ تقسیمِ مساویِ ظرفیتِ تیم حدس است و گزارش نمی‌شود."
        ),
        "display_currency": _display_currency(),
        "currency_format": format_rial_fa(0, _display_currency()),
    }
