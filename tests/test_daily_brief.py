"""§۳۸ خروجیِ اجراییِ روزانه و بارِ اپراتورها.

قاعده‌ای که این فایل پین می‌کند: «پیش‌بینی» و «اثبات‌شده» دو بلوکِ جدا با دو
منبعِ جدا هستند و هرگز جمع نمی‌شوند؛ چیزی که داده‌اش نیست `None` است، نه صفر.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from sqlalchemy import delete, func, select

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

from api import brief_api  # noqa: E402
from api.main import app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from mktcore.analysis.validation import posting_block_reasons  # noqa: E402
from mktcore.campaigns.assign import ARM_CONTROL, ARM_TREATMENT  # noqa: E402
from mktcore.db import session_scope  # noqa: E402
from mktcore.db.base import now_ts  # noqa: E402
from mktcore.db.models import (  # noqa: E402
    Campaign,
    CampaignMember,
    CampaignOutcome,
    Customer,
    CustomerLifecycleEvent,
    ImportBatch,
    Opportunity,
)
from mktcore.lifecycle.states import STATE_AT_RISK, STATE_VIP  # noqa: E402
from mktcore.opportunities.contract import VALUE_RELATIONSHIP  # noqa: E402
from mktcore.opportunities.engine import STATUS_OPEN  # noqa: E402

from .conftest import poll_job  # noqa: E402

client = TestClient(app)
_MONEY_KEYS = {"rial", "display_text", "display_currency"}
_cache: dict[str, dict] = {}


def _analyzed() -> dict:
    if "payload" not in _cache:
        r = client.post("/api/sample")
        assert r.status_code == 200
        data = r.json()
        roles = {x["role"]: x["suggested"] for x in data["roles"]}
        mapping = {role: col for role, col in roles.items() if col}
        r = client.post("/api/analyze", json={
            "session_id": data["session_id"], "mapping": mapping, "horizon": 3,
        })
        assert r.status_code == 200, r.text
        _cache["payload"] = poll_job(client, r.json()["job_id"])
    return _cache["payload"]


def _monetary_total(business_id: int, statuses: tuple[str, ...]) -> tuple[int, int]:
    with session_scope() as session:
        count, total = session.execute(
            select(func.count(Opportunity.id), func.sum(Opportunity.expected_value_rial)).where(
                Opportunity.business_id == business_id,
                Opportunity.status.in_(statuses),
                Opportunity.value_kind != VALUE_RELATIONSHIP,
            )
        ).one()
    return int(count or 0), int(total or 0)


def _business_id() -> int:
    with session_scope() as session:
        bid = brief_api._business_id(session)
    assert bid is not None
    return bid


def _seed_proven_campaign(business_id: int) -> tuple[int, int]:
    """کمپینی با اثرِ روشن: ۱۵۰ در هر بازو، تبدیلِ ۳۰٪ در برابر ۱۰٪ — حکمِ «اثبات‌شده»."""
    with session_scope() as session:
        customer_ids = session.scalars(
            select(Customer.id).where(Customer.business_id == business_id)
            .order_by(Customer.id).limit(300)
        ).all()
        assert len(customer_ids) >= 300, "داده‌ی نمونه باید دست‌کم ۳۰۰ مشتری داشته باشد"
        campaign = Campaign(
            business_id=business_id, name="کمپینِ اثبات‌شده‌ی تست", status="closed",
            holdout_pct=50, closed_at=now_ts(),
        )
        session.add(campaign)
        session.flush()
        for i, cid in enumerate(customer_ids):
            arm = ARM_TREATMENT if i < 150 else ARM_CONTROL
            rank = i if arm == ARM_TREATMENT else i - 150
            converted = rank < (45 if arm == ARM_TREATMENT else 15)
            session.add(CampaignMember(
                campaign_id=campaign.id, customer_id=cid, arm=arm,
                assigned_date="2024-01-01", exposure_date="2024-01-02",
            ))
            session.add(CampaignOutcome(
                campaign_id=campaign.id, customer_id=cid, arm=arm,
                window_start="2024-01-02", window_end="2024-02-01",
                orders_count=1 if converted else 0,
                lines_count=1 if converted else 0,
                revenue_rial=1_000_000 if converted else 0,
                cost_rial=None, lines_with_cost=0,
            ))
        session.flush()
        report = brief_api._campaign_report(session, campaign.id)
        assert report["verdict"] == "proven", report["verdict_reason_fa"]
        return campaign.id, int(report["incremental_revenue_rial"])


def _delete_campaign(campaign_id: int) -> None:
    with session_scope() as session:
        session.execute(delete(Campaign).where(Campaign.id == campaign_id))


# ------------------------------------------------------------ خلاصه‌ی روزانه
def test_brief_forecast_comes_from_live_opportunities_and_is_labelled_non_causal():
    payload = _analyzed()
    assert payload["canonical"]["ok"] is True
    business_id = _business_id()

    body = client.get("/api/v1/daily-brief").json()
    assert body["available"] is True
    assert body["as_of"] and body["data_through"]
    count, total = _monetary_total(business_id, (STATUS_OPEN,))
    assert body["valid_opportunities"] == count
    assert body["forecast"]["count"] == count
    assert body["forecast"]["revenue"]["rial"] == total
    # همان عددِ صندوق: دو عددِ متفاوت برای «ارزشِ فهرست» روی یک صفحه ممنوع
    inbox = client.get("/api/v1/opportunities", params={"status": "open", "limit": 1}).json()
    assert body["forecast"]["revenue"]["rial"] == inbox["open_pipeline"]["rial"]
    assert body["forecast"]["statuses"] == [STATUS_OPEN]
    assert set(body["forecast"]["revenue"]) == _MONEY_KEYS
    assert "غیرعلّی" in body["forecast"]["label_fa"]
    # سودِ هر فرصت محاسبه نمی‌شود ⇒ «بررسی نشد»، نه صفر
    assert body["forecast"]["gross_profit"]["rial"] is None
    assert "بررسی نشد" in body["forecast"]["gross_profit_note_fa"]
    # «سنجیده‌نشده» همان پیش‌بینی است با برچسبِ خودش — نه تفاضلی با اثبات‌شده
    assert body["not_validated"]["revenue"]["rial"] == total
    assert "جمع نکنید" in body["not_validated"]["label_fa"]
    assert "جمع نمی‌شوند" in body["separation_note_fa"]


def test_brief_proven_block_is_none_until_a_campaign_is_proven_then_sums_only_proven():
    _analyzed()
    business_id = _business_id()
    before = client.get("/api/v1/daily-brief").json()
    baseline_ids = set(before["proven"]["proven_campaign_ids"])
    baseline_rial = before["proven"]["incremental_revenue"]["rial"] or 0
    if not baseline_ids:
        assert before["proven"]["incremental_revenue"]["rial"] is None
        assert "اثبات‌شده‌ای نیست" in before["proven"]["gross_profit_note_fa"]

    campaign_id, incremental = _seed_proven_campaign(business_id)
    try:
        after = client.get("/api/v1/daily-brief").json()
        assert campaign_id in after["proven"]["proven_campaign_ids"]
        assert after["proven"]["incremental_revenue"]["rial"] == baseline_rial + incremental
        assert incremental > 0
        # بدون پوششِ بها، سودِ افزوده جمع نمی‌شود — ناقص را کامل جا نمی‌زنیم
        assert after["proven"]["incremental_gross_profit"]["rial"] is None
        assert "پوششِ بها" in after["proven"]["gross_profit_note_fa"]
        assert after["proven"]["campaigns_by_verdict"]["proven"]["count"] >= 1
        # پیش‌بینی با اثبات‌شده تکان نمی‌خورد: دو منبعِ جدا
        assert after["forecast"]["revenue"]["rial"] == before["forecast"]["revenue"]["rial"]
        assert after["not_validated"]["revenue"]["rial"] == before["not_validated"]["revenue"]["rial"]
        assert "اثبات‌شده" in after["text_fa"] and "پیش‌بینی" in after["text_fa"]
    finally:
        _delete_campaign(campaign_id)


def test_brief_groups_are_sorted_by_value_with_relationship_groups_counted_not_priced():
    _analyzed()
    body = client.get("/api/v1/daily-brief").json()
    groups = body["groups"]
    assert groups
    monetary = [g for g in groups if g["value_kind"] != VALUE_RELATIONSHIP]
    relational = [g for g in groups if g["value_kind"] == VALUE_RELATIONSHIP]
    values = [g["forecast_revenue"]["rial"] for g in monetary]
    assert values == sorted(values, reverse=True)
    assert groups[: len(monetary)] == monetary, "گروه‌های رابطه‌ای در انتها می‌آیند"
    for g in relational:
        assert g["forecast_revenue"]["rial"] is None
        assert g["customers"] > 0
    for g in groups:
        assert g["forecast_gross_profit"]["rial"] is None
        assert g["customers"] <= g["opportunities"]
    assert sum(g["opportunities"] for g in monetary) == body["forecast"]["count"]


def test_brief_urgent_block_reports_transitions_and_never_guesses_stock():
    _analyzed()
    business_id = _business_id()
    before = client.get("/api/v1/daily-brief").json()
    urgent = before["urgent"]
    assert urgent["suppressed_by_stock"] is None
    assert "بررسی نشد" in urgent["suppressed_by_stock_note_fa"]
    assert urgent["expiring_today"] <= urgent["expiring_soon"]
    assert isinstance(urgent["dead_letter_runs"], int)
    assert isinstance(urgent["financial_unit_review_needed"], bool)
    assert "ویژه" in urgent["vip_entered_at_risk_label_fa"]

    with session_scope() as session:
        cid = session.scalar(
            select(Customer.id).where(Customer.business_id == business_id)
            .order_by(Customer.id.desc()).limit(1)
        )
        session.add(CustomerLifecycleEvent(
            business_id=business_id, customer_id=cid, as_of_date=before["as_of"],
            from_state=STATE_VIP, to_state=STATE_AT_RISK, reason_fa="تست", basis="personal",
        ))
        session.flush()
        event_id = session.scalar(
            select(func.max(CustomerLifecycleEvent.id)).where(
                CustomerLifecycleEvent.customer_id == cid,
                CustomerLifecycleEvent.as_of_date == before["as_of"],
            )
        )
    try:
        after = client.get("/api/v1/daily-brief").json()
        assert after["urgent"]["vip_entered_at_risk"] == urgent["vip_entered_at_risk"] + 1
        assert "به «در خطر ریزش» رفت" in after["text_fa"]
    finally:
        with session_scope() as session:
            session.execute(
                delete(CustomerLifecycleEvent).where(CustomerLifecycleEvent.id == event_id)
            )


def test_brief_reads_blocking_codes_the_way_the_importer_writes_them():
    """`blocked_by` با `check_id` نوشته می‌شود؛ واحدِ نامعلوم = C00، نه رشته‌ای که وجود ندارد."""
    _analyzed()
    business_id = _business_id()
    reasons = posting_block_reasons(None, file_currency="دلار")
    assert [r["check_id"] for r in reasons] == ["C00"]
    with session_scope() as session:
        batch = ImportBatch(
            business_id=business_id, dataset_key="test", filename="blocked-unit.xlsx", reconcile_status="BLOCKED",
            notes_json=json.dumps({"posted": False, "blocked_by": reasons}, ensure_ascii=False),
        )
        session.add(batch)
        session.flush()
        batch_id = batch.id
    try:
        body = client.get("/api/v1/daily-brief").json()
        urgent = body["urgent"]
        assert urgent["latest_import_blocked"] is True
        assert urgent["latest_import_blocked_by"] == ["C00"]
        assert urgent["financial_unit_review_needed"] is True
        assert "واحدِ مالیِ نامعلوم" in body["text_fa"] and "C00" in body["text_fa"]
    finally:
        with session_scope() as session:
            session.execute(delete(ImportBatch).where(ImportBatch.id == batch_id))

    # C04/C05 مسدود می‌کنند ولی «واحدِ مالی» نیستند — با نامِ خودشان گزارش می‌شوند
    with session_scope() as session:
        batch = ImportBatch(
            business_id=business_id, dataset_key="test", filename="blocked-sign.xlsx", reconcile_status="BLOCKED",
            notes_json=json.dumps({"posted": False, "blocked_by": [
                {"check_id": "C04", "title": "علامت", "detail": "وارونه"},
            ]}, ensure_ascii=False),
        )
        session.add(batch)
        session.flush()
        batch_id = batch.id
    try:
        body = client.get("/api/v1/daily-brief").json()
        assert body["urgent"]["latest_import_blocked_by"] == ["C04"]
        assert body["urgent"]["financial_unit_review_needed"] is False
        assert "خطای مالیِ مسدودکننده" in body["text_fa"] and "C04" in body["text_fa"]
    finally:
        with session_scope() as session:
            session.execute(delete(ImportBatch).where(ImportBatch.id == batch_id))


def test_brief_without_an_engine_run_says_so_instead_of_reporting_zeros(monkeypatch):
    _analyzed()
    monkeypatch.setattr(brief_api, "_latest_as_of", lambda session, business_id: None)
    body = client.get("/api/v1/daily-brief").json()
    assert body == {"available": False, "reason_fa": brief_api.NO_RUN_FA}


def test_brief_contract_keys_are_pinned():
    _analyzed()
    body = client.get("/api/v1/daily-brief").json()
    assert set(body) == {
        "available", "as_of", "data_through", "generated_at", "valid_opportunities",
        "forecast", "proven", "not_validated", "groups", "urgent", "economics_note_fa",
        "cost_coverage_bp", "separation_note_fa", "text_fa",
    }
    assert set(body["urgent"]) == {
        "expiring_today", "expiring_soon", "expiring_soon_days", "vip_entered_at_risk",
        "vip_entered_at_risk_label_fa", "quarantine_open_rows", "latest_import_blocked",
        "latest_import_blocked_by", "financial_unit_review_needed", "dead_letter_runs",
        "suppressed_by_stock", "suppressed_by_stock_note_fa",
    }


# ------------------------------------------------------------ بارِ اپراتورها
def test_operator_load_buckets_partition_the_live_opportunities():
    _analyzed()
    business_id = _business_id()
    items = client.get("/api/v1/opportunities", params={"status": "open", "limit": 3}).json()["items"]
    assert len(items) >= 3
    ids = [i["id"] for i in items]
    for oid, who in zip(ids[:2], ("زهرا", "رضا"), strict=True):
        r = client.post(f"/api/v1/opportunities/{oid}/accept", json={"actor": who, "assigned_to": who})
        assert r.status_code == 200, r.text
    try:
        body = client.get("/api/v1/operator-load").json()
        assert body["available"] is True
        count, _ = _monetary_total(business_id, brief_api.LIVE_STATUSES)
        with session_scope() as session:
            relational = session.scalar(
                select(func.count(Opportunity.id)).where(
                    Opportunity.business_id == business_id,
                    Opportunity.status.in_(brief_api.LIVE_STATUSES),
                    Opportunity.value_kind == VALUE_RELATIONSHIP,
                )
            ) or 0
        assert body["total"] == count + relational
        assert sum(b["count"] for b in body["operators"]) == body["total"]
        names = {b["assigned_to"] for b in body["operators"]}
        assert {"زهرا", "رضا"} <= names
        unassigned = [b for b in body["operators"] if b["unassigned"]]
        assert len(unassigned) == 1 and unassigned[0]["count"] == body["unassigned_count"]
        assert body["operators"][-1]["unassigned"] is True, "سطلِ بی‌مسئول همیشه آخر است"
        zahra = next(b for b in body["operators"] if b["assigned_to"] == "زهرا")
        assert zahra["by_status"].get("accepted", 0) >= 1
        assert set(zahra["value"]) == _MONEY_KEYS
        # ظرفیتِ هر اپراتور تنظیمی ندارد ⇒ «تنظیم نشد»، نه تقسیمِ حدسی
        assert body["per_operator_capacity"] is None
        assert "حدس" in body["per_operator_capacity_note_fa"]
    finally:
        for oid in ids[:2]:
            client.post(f"/api/v1/opportunities/{oid}/reopen", json={})
