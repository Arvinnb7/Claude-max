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
