"""«لغو ۱۱» و لیستِ سیاهِ پنل: انصراف با شماره از راهِ HTTP، بدون webhook.

منطقِ شماره‌محور از قبل بود (`record_opt_out(phone=…)`)؛ چیزی که نبود، مسیرِ
ورودش بود — و دفترِ وضعیت آن را «مسدود: نیازمند webhook» می‌خواند.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

from api.main import app  # noqa: E402

from mktcore.contact.register import load_gate  # noqa: E402
from mktcore.db import session_scope  # noqa: E402
from mktcore.db.models import Customer, Opportunity  # noqa: E402

from .conftest import poll_job  # noqa: E402

client = TestClient(app)
PHONE = "0912 999 9999"


@pytest.fixture(scope="module")
def analyzed() -> None:
    r = client.post("/api/sample")
    data = r.json()
    mapping = {x["role"]: x["suggested"] for x in data["roles"] if x["suggested"]}
    r = client.post("/api/analyze", json={
        "session_id": data["session_id"], "mapping": mapping, "horizon": 3,
    })
    poll_job(client, r.json()["job_id"])


def test_opt_out_by_phone_is_recorded_with_its_source(analyzed):
    r = client.post("/api/v1/contact-suppressions", json={
        "phone": PHONE, "reason_fa": "پاسخ لغو ۱۱", "source": "provider",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] is True and body["phone_masked"].endswith("9999")
    assert "999 9999" not in r.text and "9999999" not in r.text

    listing = client.get("/api/v1/contact-suppressions").json()
    row = next(item for item in listing["items"] if (item.get("phone") or "").endswith("9999"))
    assert row["source"] == "provider"
    assert load_gate().reason_for("کسی", phone="+989129999999") == "consent"

    again = client.post("/api/v1/contact-suppressions", json={
        "phone": PHONE, "reason_fa": "دوباره", "source": "provider",
    })
    assert again.json()["created"] is False, "idempotent"


def test_provider_blacklist_import_reports_rejects_and_keeps_numbers_out_of_campaigns(analyzed):
    with session_scope() as session:
        target = session.scalar(
            select(Customer)
            .join(Opportunity, Opportunity.customer_id == Customer.id)
            .where(Customer.phone_e164.isnot(None), Opportunity.status == "open")
        )
        assert target is not None
        phone, customer_id = target.phone_e164, target.id

    r = client.post("/api/v1/contact-suppressions/import", json={
        "rows": [{"phone": phone}, {"phone": "abc"}, {"phone": phone}],
        "source": "provider",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["created"], body["unchanged"], len(body["rejected"])) == (1, 1, 1)
    assert body["rejected"][0]["reason_fa"] == "شماره‌ی نامعتبر"

    created = client.post("/api/v1/campaigns", json={"name": "لیست سیاه", "holdout_pct": 0, "limit": 500})
    if created.status_code == 200:
        members = client.get(f"/api/v1/campaigns/{created.json()['id']}").json()["members"]
        assert customer_id not in {m["customer_id"] for m in members}
        reasons = {row["دلیل"] for row in created.json()["contact_gate"]["دلایل_مسدودی"]}
        assert "رضایت تماس" in reasons
    else:
        assert created.status_code == 409 and "رضایت تماس" in created.json()["detail"]

    revoked = client.delete(f"/api/v1/contact-suppressions?phone={phone}")
    assert revoked.status_code == 200 and revoked.json()["revoked"] is True
    assert client.delete(f"/api/v1/contact-suppressions?phone={phone}").status_code == 404


# ═══════════════════════════════ یافته‌های بازبینی: اعتبارِ شماره، ماسک، گارد
def test_unparseable_phone_is_rejected_instead_of_a_silent_no_op(analyzed):
    r = client.post("/api/v1/contact-suppressions", json={"phone": "abcdefg", "reason_fa": "x"})
    assert r.status_code == 400 and "نامعتبر" in r.json()["detail"]
    from mktcore.contact.register import record_opt_out

    with pytest.raises(ValueError):
        record_opt_out(phone="abcdefg", reason_fa="x")


def test_suppression_listing_masks_phones_and_needs_the_token(analyzed, monkeypatch):
    from mktcore.config import get_settings
    from mktcore.security import HEADER_NAME

    client.post("/api/v1/contact-suppressions", json={"phone": "0912 888 8888", "reason_fa": "لغو"})
    listing = client.get("/api/v1/contact-suppressions").json()
    phones = [item["phone"] for item in listing["items"] if item.get("phone")]
    assert phones and all("*" in phone for phone in phones), "شماره‌ها در نمای API ماسک‌اند"
    assert "8888888" not in json_dumps(listing)

    monkeypatch.setattr(get_settings(), "mkt_api_token", "t-ledger", raising=False)
    assert client.get("/api/v1/contact-suppressions").status_code == 401
    assert client.get("/api/v1/contact-suppressions", headers={HEADER_NAME: "t-ledger"}).status_code == 200


def json_dumps(payload) -> str:
    import json

    return json.dumps(payload, ensure_ascii=False)
