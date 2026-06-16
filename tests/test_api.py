"""تست‌های API بدون فراخوانی شبکه (TestClient)."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from api.main import app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

client = TestClient(app)


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_sample_then_analyze():
    r = client.post("/api/sample")
    assert r.status_code == 200
    data = r.json()
    sid = data["session_id"]
    assert data["n_rows"] > 0
    # نقش‌های پیشنهادی باید تاریخ و درآمد را داشته باشند
    roles = {x["role"]: x["suggested"] for x in data["roles"]}
    assert roles["DATE"] is not None
    assert roles["REVENUE"] is not None

    mapping = {role: col for role, col in roles.items() if col}
    r2 = client.post("/api/analyze", json={"session_id": sid, "mapping": mapping, "horizon": 4})
    assert r2.status_code == 200, r2.text
    payload = r2.json()
    assert payload["kpis"]["total_revenue"] > 0
    assert len(payload["forecast"]["yhat"]) == 4
    assert len(payload["targets"]["scenarios"]) == 3
    assert payload["trends"]["monthly"]


def test_analyze_missing_session():
    r = client.post("/api/analyze", json={"session_id": "nope", "mapping": {}, "horizon": 4})
    assert r.status_code == 404


def test_strategy_without_key_or_analysis():
    # بدون تحلیل قبلی → 404
    r = client.post("/api/strategy", json={"session_id": "nope"})
    assert r.status_code == 404


def test_analyze_includes_advanced_sections():
    data = client.post("/api/sample").json()
    sid = data["session_id"]
    roles = {x["role"]: x["suggested"] for x in data["roles"]}
    mapping = {role: col for role, col in roles.items() if col}
    payload = client.post(
        "/api/analyze", json={"session_id": sid, "mapping": mapping, "horizon": 4}
    ).json()
    # بخش‌های پیشرفته باید در خروجی باشند
    assert "products" in payload
    assert "basket" in payload
    assert "performance" in payload
    assert "inventory" in payload
    assert "branch_targets" in payload
    assert "pacing" in payload


def test_audience_kinds_and_sms_dry_run():
    kinds = client.get("/api/audience-kinds").json()
    assert any(k["key"] == "سررسیدشده" for k in kinds["kinds"])

    data = client.post("/api/sample").json()
    sid = data["session_id"]
    roles = {x["role"]: x["suggested"] for x in data["roles"]}
    mapping = {role: col for role, col in roles.items() if col}
    client.post("/api/analyze", json={"session_id": sid, "mapping": mapping, "horizon": 4})

    r = client.post("/api/sms/send", json={
        "session_id": sid, "kind": "سررسیدشده",
        "template": "سلام {نام}، پیشنهاد: {سبد_پیشنهادی}", "limit": 30, "dry_run": True,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["حالت_آزمایشی"] is True
    assert body["audience_size"] >= 1


def test_report_pdf_endpoint():
    data = client.post("/api/sample").json()
    sid = data["session_id"]
    roles = {x["role"]: x["suggested"] for x in data["roles"]}
    mapping = {role: col for role, col in roles.items() if col}
    client.post("/api/analyze", json={"session_id": sid, "mapping": mapping, "horizon": 4})

    # HTML همیشه کار می‌کند
    r_html = client.get(f"/api/report?session_id={sid}&fmt=html")
    assert r_html.status_code == 200
    assert "گزارش جامع" in r_html.text

    # PDF (در صورت نصب WeasyPrint)
    r_pdf = client.get(f"/api/report?session_id={sid}&fmt=pdf")
    assert r_pdf.status_code == 200
    assert r_pdf.content[:4] in (b"%PDF", b"<!DO")  # PDF یا fallback HTML


def test_purchase_cycle_in_analyze():
    data = client.post("/api/sample").json()
    sid = data["session_id"]
    roles = {x["role"]: x["suggested"] for x in data["roles"]}
    mapping = {role: col for role, col in roles.items() if col}
    payload = client.post(
        "/api/analyze", json={"session_id": sid, "mapping": mapping, "horizon": 4}
    ).json()
    assert "purchase_cycle" in payload
    types = {p["product"]: p["product_type"] for p in payload["purchase_cycle"]["products"]}
    assert types.get("باکس حمل") == "تک‌خریدی"
