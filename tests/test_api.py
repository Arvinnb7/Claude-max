"""تست‌های API با قرارداد job پس‌زمینه (TestClient، بدون شبکه)."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from api.main import app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from .conftest import poll_job  # noqa: E402

client = TestClient(app)


def _sample_ready() -> dict:
    """داده‌ی نمونه (سینک) → payload ستون‌ها با session_id."""
    r = client.post("/api/sample")
    assert r.status_code == 200, r.text
    return r.json()


def _analyze(data: dict, horizon: int = 4) -> dict:
    roles = {x["role"]: x["suggested"] for x in data["roles"]}
    mapping = {role: col for role, col in roles.items() if col}
    r = client.post("/api/analyze", json={
        "session_id": data["session_id"], "mapping": mapping, "horizon": horizon,
    })
    assert r.status_code == 200, r.text
    return poll_job(client, r.json()["job_id"])


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "sms_enabled" in body


def test_sample_then_analyze_via_jobs():
    data = _sample_ready()
    assert data["n_rows"] > 0
    roles = {x["role"]: x["suggested"] for x in data["roles"]}
    assert roles["DATE"] and roles["REVENUE"]

    payload = _analyze(data)
    assert payload["kpis"]["total_revenue"] > 0
    assert len(payload["forecast"]["yhat"]) == 4
    assert len(payload["targets"]["scenarios"]) == 3


def test_session_restore_and_persistence():
    """نشست بعد از تحلیل باید از طریق GET /api/session کاملاً بازیابی شود."""
    data = _sample_ready()
    sid = data["session_id"]
    _analyze(data)

    r = client.get(f"/api/session/{sid}")
    assert r.status_code == 200
    info = r.json()
    assert info["exists"] is True
    assert info["columns_payload"]["n_rows"] == data["n_rows"]
    assert info["analysis"]["kpis"]["total_revenue"] > 0

    # شبیه‌سازی «پروسه‌ی تازه»: store جدید روی همان دیسک باید نشست را ببیند
    from api.persistence import PersistentStore

    fresh = PersistentStore()
    rec = fresh.get_session(sid)
    assert rec is not None and rec.has_analysis
    assert fresh.load_clean(sid) is not None
    assert fresh.load_bundle(sid) is not None


def test_advanced_sections_present():
    data = _sample_ready()
    payload = _analyze(data)
    for key in ("products", "basket", "performance", "inventory",
                "branch_targets", "pacing", "purchase_cycle"):
        assert key in payload, key


def test_analyze_missing_session():
    r = client.post("/api/analyze", json={"session_id": "nope", "mapping": {"DATE": "x", "REVENUE": "y"}})
    assert r.status_code == 404


def test_strategy_without_analysis():
    r = client.post("/api/strategy", json={"session_id": "nope"})
    assert r.status_code == 404


def test_job_not_found():
    r = client.get("/api/jobs/does-not-exist")
    assert r.status_code == 404


def test_sms_dry_run_and_outbox():
    data = _sample_ready()
    sid = data["session_id"]
    _analyze(data)

    r = client.post("/api/sms/send", json={
        "session_id": sid, "kind": "سررسیدشده",
        "template": "سلام {نام}، پیشنهاد: {سبد_پیشنهادی}", "limit": 20,
        "dry_run": True,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["حالت_آزمایشی"] is True
    assert body["audience_size"] >= 1

    # ارسال‌ها باید در outbox لاگ شده باشند
    ob = client.get("/api/outbox?limit=10").json()["items"]
    assert any(row["kind"] == "campaign_sms" and row["session_id"] == sid for row in ob)


def test_sms_real_send_gated_without_config():
    """بدون پیکربندی پنل، درخواست ارسال واقعی باید امن به آزمایشی برگردد."""
    data = _sample_ready()
    sid = data["session_id"]
    _analyze(data)

    r = client.post("/api/sms/send", json={
        "session_id": sid, "kind": "سررسیدشده", "template": "سلام {نام}",
        "limit": 5, "dry_run": False, "confirm": True,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["حالت_آزمایشی"] is True
    assert "توضیح" in body


def test_report_endpoints():
    data = _sample_ready()
    sid = data["session_id"]
    _analyze(data)

    r_html = client.get(f"/api/report?session_id={sid}&fmt=html")
    assert r_html.status_code == 200
    assert "گزارش جامع" in r_html.text

    r_pdf = client.get(f"/api/report?session_id={sid}&fmt=pdf")
    assert r_pdf.status_code == 200
    assert r_pdf.content[:4] in (b"%PDF", b"<!DO")


def test_scheduler_run_now_creates_outbox():
    data = _sample_ready()
    _analyze(data)

    r = client.post("/api/scheduler/run-now")
    assert r.status_code == 200, r.text
    summary = r.json()
    assert summary["status"] == "ok"
    assert summary["حالت"] == "آزمایشی (بدون ارسال)"

    ob = client.get("/api/outbox?limit=200").json()["items"]
    assert any(row["kind"] == "cycle_notification" for row in ob)

    # اجرای دوباره نباید برای همان مشتریان دوباره ثبت کند (dedupe)
    r2 = client.post("/api/scheduler/run-now")
    assert r2.json()["ثبت‌شده"] == 0


def test_scheduler_status_endpoint():
    r = client.get("/api/scheduler/status")
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is False  # در تست‌ها خاموش است
    assert body["running"] is False
