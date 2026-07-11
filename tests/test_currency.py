"""تست‌های انتخاب و تبدیل واحد پول (تومان/ریال)."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

from api.main import app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from mktcore.ingest.currency import (  # noqa: E402
    conversion_factor,
    convert_monetary_columns,
)

from .conftest import poll_job  # noqa: E402

client = TestClient(app)


def test_conversion_factors():
    assert conversion_factor("تومان", "ریال") == 10.0
    assert conversion_factor("ریال", "تومان") == 0.1
    assert conversion_factor("تومان", "تومان") == 1.0
    assert conversion_factor("ریال", "ریال") == 1.0
    # رفت‌وبرگشت
    assert conversion_factor("تومان", "ریال") * conversion_factor("ریال", "تومان") == 1.0


def test_conversion_factor_invalid():
    with pytest.raises(ValueError, match="نامعتبر"):
        conversion_factor("دلار", "تومان")
    with pytest.raises(ValueError, match="نامعتبر"):
        conversion_factor("تومان", "")


def test_convert_monetary_columns_targets_only_money():
    df = pd.DataFrame({
        "revenue": [100.0, 200.0],
        "cost": [50.0, 60.0],
        "unit_price": [10.0, 20.0],
        "discount": [0.1, 0.2],   # نسبت — نباید تبدیل شود
        "quantity": [1, 2],        # شمارشی — نباید تبدیل شود
        "customer_id": ["a", "b"],
    })
    out = convert_monetary_columns(df, 0.1)
    assert out["revenue"].tolist() == [10.0, 20.0]
    assert out["cost"].tolist() == [5.0, 6.0]
    assert out["unit_price"].tolist() == [1.0, 2.0]
    assert out["discount"].tolist() == [0.1, 0.2]
    assert out["quantity"].tolist() == [1, 2]
    # ضریب ۱ → همان شیء (بدون کپی)
    assert convert_monetary_columns(df, 1.0) is df


def _analyze_sample(extra: dict | None = None) -> dict:
    r = client.post("/api/sample")
    assert r.status_code == 200
    data = r.json()
    roles = {x["role"]: x["suggested"] for x in data["roles"]}
    mapping = {role: col for role, col in roles.items() if col}
    body = {"session_id": data["session_id"], "mapping": mapping, "horizon": 4}
    body.update(extra or {})
    r = client.post("/api/analyze", json=body)
    assert r.status_code == 200, r.text
    return poll_job(client, r.json()["job_id"])


def test_api_rial_file_displayed_as_toman():
    base = _analyze_sample()
    conv = _analyze_sample({"file_currency": "ریال", "display_currency": "تومان"})
    assert conv["currency"] == "تومان"
    assert conv["kpis"]["total_revenue"] == pytest.approx(
        0.1 * base["kpis"]["total_revenue"], rel=1e-9,
    )


def test_api_display_rial():
    base = _analyze_sample()
    conv = _analyze_sample({"file_currency": "تومان", "display_currency": "ریال"})
    assert conv["currency"] == "ریال"
    assert conv["kpis"]["total_revenue"] == pytest.approx(
        10 * base["kpis"]["total_revenue"], rel=1e-9,
    )


def test_api_invalid_currency_rejected():
    r = client.post("/api/sample")
    data = r.json()
    roles = {x["role"]: x["suggested"] for x in data["roles"]}
    mapping = {role: col for role, col in roles.items() if col}
    r = client.post("/api/analyze", json={
        "session_id": data["session_id"], "mapping": mapping,
        "file_currency": "دلار", "display_currency": "تومان",
    })
    assert r.status_code == 400
    assert "واحد پول" in r.json()["detail"]
