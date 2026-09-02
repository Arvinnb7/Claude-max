"""سیاستِ آفر (§۲۰.۳): نردبان و آستانه‌ها — تصمیمِ کاربر، نه حدسِ سیستم.

## قاعده‌ای که این فایل پین می‌کند

نردبانِ **تنظیم‌نشده** یعنی رفتارِ امروز (هیچ تخفیفی پیشنهاد نمی‌شود و «بررسی
نشد» ثبت می‌شود). و سنجه‌ی پاسخ باید صادقانه بگوید نردبان روی چند فرصت اصلاً
می‌تواند اثر بگذارد — نردبان بدون بها ایمن ولی بی‌اثر است.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

from api.main import app  # noqa: E402

from .conftest import poll_job  # noqa: E402

client = TestClient(app)


@pytest.fixture(scope="module")
def analyzed() -> str:
    r = client.post("/api/sample")
    data = r.json()
    mapping = {x["role"]: x["suggested"] for x in data["roles"] if x["suggested"]}
    r = client.post("/api/analyze", json={
        "session_id": data["session_id"], "mapping": mapping, "horizon": 3,
    })
    poll_job(client, r.json()["job_id"])
    return data["session_id"]


@pytest.fixture(autouse=True)
def _reset_policy(analyzed):
    """هر تست با نردبانِ برداشته‌شده شروع می‌شود و همان‌طور تمام می‌شود."""
    client.put("/api/v1/offer-policy", json={"ladder_bp": []})
    yield
    client.put("/api/v1/offer-policy", json={"ladder_bp": []})


def test_unset_ladder_is_reported_as_not_checked(analyzed):
    body = client.get("/api/v1/offer-policy").json()

    assert body["available"] is True
    assert body["ladder_bp"] is None
    assert "تعیین نشده" in body["note_fa"]
    assert set(body["thresholds"]) >= {"high_bp", "low_bp", "min_lines", "configured"}
    assert body["thresholds"]["configured"] is False


def test_ladder_round_trips_sorted_and_deduplicated(analyzed):
    r = client.put("/api/v1/offer-policy", json={"ladder_bp": [1500, 500, 1000, 500]})

    assert r.status_code == 200, r.text
    assert r.json()["ladder_bp"] == [500, 1000, 1500]
    assert client.get("/api/v1/offer-policy").json()["ladder_bp"] == [500, 1000, 1500]


def test_a_rung_above_fifty_percent_is_refused(analyzed):
    """احتمالاً اشتباهِ واحد است (۵۰۰۰ به‌جای ۵۰۰)؛ بی‌صدا پذیرفتنش خطرناک است."""
    r = client.put("/api/v1/offer-policy", json={"ladder_bp": [500, 6000]})

    assert r.status_code == 409
    assert "پله" in r.json()["detail"]
    assert client.get("/api/v1/offer-policy").json()["ladder_bp"] is None


def test_an_empty_ladder_removes_the_setting(analyzed):
    client.put("/api/v1/offer-policy", json={"ladder_bp": [500]})
    r = client.put("/api/v1/offer-policy", json={"ladder_bp": []})

    assert r.status_code == 200
    assert r.json()["ladder_bp"] is None


def test_thresholds_must_keep_low_below_high(analyzed):
    r = client.put("/api/v1/offer-policy", json={
        "full_price_high_bp": 5000, "full_price_low_bp": 6000,
    })
    assert r.status_code == 409


def test_configured_thresholds_reach_the_customer_file(analyzed):
    r = client.put("/api/v1/offer-policy", json={
        "full_price_high_bp": 9500, "full_price_low_bp": 4000, "full_price_min_lines": 2,
    })
    assert r.status_code == 200, r.text
    assert r.json()["thresholds"]["configured"] is True

    customer_id = client.get("/api/v1/customers?limit=1").json()["items"][0]["id"]
    block = client.get(f"/api/v1/customers/{customer_id}").json()["customer"]["features"]["full_price"]
    assert block["thresholds"]["high_bp"] == 9500
    assert block["thresholds"]["low_bp"] == 4000
    assert block["thresholds"]["configured"] is True


def test_the_gauge_never_claims_more_reach_than_open_opportunities(analyzed):
    client.put("/api/v1/offer-policy", json={"ladder_bp": [500, 1000]})
    body = client.get("/api/v1/offer-policy").json()

    assert 0 <= body["reachable_by_ladder"] <= body["open_opportunities"]
    assert body["with_product_margin"] <= body["open_opportunities"]
    assert body["with_known_tier"] <= body["open_opportunities"]
    assert body["note_fa"]


def test_every_opportunity_row_carries_the_offer_contract(analyzed):
    """قراردادِ UI: هر ردیف `offer` و `offer_status` دارد؛ آفر همیشه `sendable` می‌گوید."""
    body = client.get("/api/v1/opportunities?limit=50").json()
    assert body.get("items"), "دفتر کل باید فرصت داشته باشد"
    for row in body["items"]:
        assert "offer" in row and "offer_status" in row
        if row["offer"] is not None:
            assert set(row["offer"]) >= {
                "suggested_discount_bp", "suggested_discount_text", "status", "sendable",
            }
            assert row["offer"]["sendable"] is (row["offer"]["status"] == "approved")
            assert row["offer_status"] == row["offer"]["status"]
