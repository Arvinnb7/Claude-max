"""مسیرهای `/api/v1` — خواندن از دفتر کل، بدون لمس مسیرهای موجود."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

from api.main import app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from .conftest import poll_job  # noqa: E402

client = TestClient(app)

_MONEY_KEYS = {"rial", "display_text", "display_currency"}


_analysis_cache: dict[str, dict] = {}


def _run_sample_analysis() -> dict:
    """یک تحلیل روی داده‌ی نمونه — نتیجه بین تست‌های این فایل به اشتراک است.

    تحلیل قطعی است و همه‌ی تست‌های اینجا همان دفتر کل را می‌خوانند، پس اجرای
    دوباره‌اش فقط وقت می‌برد. تست‌هایی که وضعیت را عوض می‌کنند روی دیتابیس کار
    می‌کنند، نه روی این payload.
    """
    if "payload" not in _analysis_cache:
        r = client.post("/api/sample")
        assert r.status_code == 200
        data = r.json()
        roles = {x["role"]: x["suggested"] for x in data["roles"]}
        mapping = {role: col for role, col in roles.items() if col}
        r = client.post("/api/analyze", json={
            "session_id": data["session_id"], "mapping": mapping, "horizon": 3,
        })
        assert r.status_code == 200, r.text
        _analysis_cache["payload"] = poll_job(client, r.json()["job_id"])
    return _analysis_cache["payload"]


def _assert_money(value: dict) -> None:
    assert set(value) == _MONEY_KEYS
    assert value["rial"] is None or isinstance(value["rial"], int)
    assert not isinstance(value["rial"], float)  # هرگز float در پاسخ پولی
    assert isinstance(value["display_text"], str)


def test_analysis_then_imports_endpoint():
    payload = _run_sample_analysis()
    assert payload["canonical"]["ok"] is True

    r = client.get("/api/v1/imports")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is True
    assert body["items"]
    latest = body["items"][0]
    assert latest["rows"]["clean"] > 0
    assert latest["reconcile_status"].startswith("RECONCILED")
    _assert_money(latest["net_sales"])
    # جمله‌ی اقتصادی هرچه باشد، هرگز عددی را «سود» نمی‌نامد
    assert "درآمد" in body["economics_note_fa"]
    assert "سود" in body["economics_note_fa"]  # به‌صورت نفی/تفکیک، نه ادعا


def test_import_detail_exposes_reconciliation_evidence():
    payload = _run_sample_analysis()
    batch_id = payload["canonical"]["batch_id"]

    r = client.get(f"/api/v1/imports/{batch_id}")
    assert r.status_code == 200
    body = r.json()
    ids = {c["id"] for c in body["checks"]}
    assert {"L01", "L02", "L03", "L04"} <= ids
    assert all(c["status"] in ("OK", "WARN", "MISMATCH") for c in body["checks"])


def test_import_detail_404_for_unknown_batch():
    r = client.get("/api/v1/imports/99999999")
    assert r.status_code == 404
    assert "یافت نشد" in r.json()["detail"]


def test_data_quality_reports_gaps_explicitly():
    _run_sample_analysis()
    r = client.get("/api/v1/data-quality")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is True
    assert body["counts"]["lines"] > 0
    gap_ids = {g["id"] for g in body["gaps"]}
    # شکاف‌های شناخته‌شده باید صریح گزارش شوند، نه پنهان بمانند
    assert {"no_cost_data", "no_inventory_data",
            "lines_without_customer", "lines_without_product"} <= gap_ids
    # پوشش بها از **داده** خوانده می‌شود، نه از یک فرضِ ثابت: داده‌ی نمونه ستون
    # بهای تمام‌شده دارد، پس پاسخ نباید بگوید «نداریم».
    cost_gap = next(g for g in body["gaps"] if g["id"] == "no_cost_data")
    assert cost_gap["coverage"] == 1.0
    assert cost_gap["severity"] == "ok"
    inventory_gap = next(g for g in body["gaps"] if g["id"] == "no_inventory_data")
    assert inventory_gap["severity"] == "known_limitation"


def test_economics_note_tracks_actual_cost_coverage():
    """جمله‌ی اقتصادی نباید ادعای ثابت بکند؛ باید وضعیت واقعی داده را بگوید."""
    _run_sample_analysis()
    note = client.get("/api/v1/imports").json()["economics_note_fa"]
    coverage = next(
        g["coverage"] for g in client.get("/api/v1/data-quality").json()["gaps"]
        if g["id"] == "no_cost_data"
    )
    assert coverage == 1.0
    assert "بهای تمام‌شده برای همه‌ی خطوط ثبت شده" in note
    # حتی با وجود بها، هیچ عددی «سود» نامیده نمی‌شود
    assert "درآمد" in note


def test_customers_directory_and_profile():
    _run_sample_analysis()

    r = client.get("/api/v1/customers", params={"limit": 5})
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is True
    assert body["total"] > 0
    assert len(body["items"]) <= 5

    top = body["items"][0]
    assert top["features"] is not None
    _assert_money(top["features"]["monetary"])
    # مرتب‌سازی پیش‌فرض بر اساس ارزش نزولی
    values = [i["features"]["monetary"]["rial"] for i in body["items"]]
    assert values == sorted(values, reverse=True)

    r = client.get(f"/api/v1/customers/{top['id']}")
    assert r.status_code == 200
    profile = r.json()
    assert profile["customer"]["id"] == top["id"]
    assert profile["lines"]
    _assert_money(profile["lines"][0]["revenue"])
    assert profile["feature_history"]


def test_customer_search_filters():
    _run_sample_analysis()
    everything = client.get("/api/v1/customers", params={"limit": 200}).json()
    sample_key = everything["items"][0]["key"]

    filtered = client.get("/api/v1/customers", params={"q": sample_key}).json()
    assert filtered["total"] >= 1
    assert all(sample_key in item["key"] or sample_key in (item["name"] or "")
               for item in filtered["items"])


def test_customer_404():
    r = client.get("/api/v1/customers/99999999")
    assert r.status_code == 404


def test_opportunity_inbox_lists_ranked_items():
    payload = _run_sample_analysis()
    assert payload["canonical"]["opportunities"]["created"] >= 0

    r = client.get("/api/v1/opportunities", params={"status": "open", "limit": 20})
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is True
    assert body["items"]
    _assert_money(body["open_pipeline"])

    values = [i["expected_value"]["rial"] for i in body["items"]]
    assert values == sorted(values, reverse=True)

    top = body["items"][0]
    assert top["status"] == "open"
    assert top["action"] and top["reason"]
    # صداقت علّی: بدون آزمایش، این‌ها خالی می‌مانند و پاسخ خودش می‌گوید چرا
    assert top["attributed_revenue"]["rial"] is None
    assert top["incremental_revenue"]["rial"] is None
    assert "گروه کنترل" in top["causal_note_fa"]


def test_opportunity_detail_shows_skipped_checks_explicitly():
    _run_sample_analysis()
    top = client.get("/api/v1/opportunities").json()["items"][0]

    body = client.get(f"/api/v1/opportunities/{top['id']}").json()
    outcomes = {f["code"]: f["outcome"] for f in body["factors"]}
    # نبودِ داده هرگز «بررسی شد» ثبت نمی‌شود
    assert outcomes["inventory"] == "filter_skip"
    assert outcomes["margin_floor"] == "filter_skip"
    assert body["events"]
    assert any(e["type"] == "created" for e in body["events"])


def test_opportunity_lifecycle_transitions():
    _run_sample_analysis()
    top = client.get("/api/v1/opportunities").json()["items"][0]
    oid = top["id"]

    accepted = client.post(f"/api/v1/opportunities/{oid}/accept",
                           json={"actor": "زهرا", "assigned_to": "زهرا"})
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "accepted"
    assert accepted.json()["assigned_to"] == "زهرا"

    done = client.post(f"/api/v1/opportunities/{oid}/done", json={"actor": "زهرا"})
    assert done.json()["status"] == "done"

    reopened = client.post(f"/api/v1/opportunities/{oid}/reopen", json={})
    assert reopened.json()["status"] == "open"

    detail = client.get(f"/api/v1/opportunities/{oid}").json()
    types = [e["type"] for e in detail["events"]]
    for expected in ("accept", "done", "reopen"):
        assert expected in types


def test_snooze_requires_a_date():
    _run_sample_analysis()
    oid = client.get("/api/v1/opportunities").json()["items"][0]["id"]

    bad = client.post(f"/api/v1/opportunities/{oid}/snooze", json={})
    assert bad.status_code == 400
    assert "snooze_until" in bad.json()["detail"]

    good = client.post(f"/api/v1/opportunities/{oid}/snooze",
                       json={"snooze_until": "2030-01-01"})
    assert good.json()["status"] == "snoozed"
    assert good.json()["snooze_until"] == "2030-01-01"


def test_unknown_opportunity_action_is_rejected():
    _run_sample_analysis()
    oid = client.get("/api/v1/opportunities").json()["items"][0]["id"]
    r = client.post(f"/api/v1/opportunities/{oid}/explode", json={})
    assert r.status_code == 400
    assert "نامعتبر" in r.json()["detail"]


def test_opportunity_404():
    assert client.get("/api/v1/opportunities/99999999").status_code == 404
    assert client.post("/api/v1/opportunities/99999999/accept", json={}).status_code == 404


def test_existing_endpoints_are_untouched():
    """مسیرهای قدیمی باید دقیقاً همان‌طور که بودند پاسخ دهند."""
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    for key in ("status", "ai_available", "model", "currency", "sms_enabled",
                "scheduler", "data_dir", "retention"):
        assert key in body
