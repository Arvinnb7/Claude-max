"""مسیرِ قرنطینه: ردیفِ خامِ فایلِ فروش است — پس گارد دارد و شماره را ماسک می‌کند.

`GET /api/v1/quarantine` سطرِ فایل را همان‌طور که بود برمی‌گرداند (ستونِ موبایل و
نام). بازبینیِ دورِ قبل این را بست: `/api/outbox` و `/api/export` بسته بودند ولی
همان شماره‌ها از این مسیر بی‌توکن و بی‌ماسک بیرون می‌آمدند.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

from api.main import app  # noqa: E402

from mktcore.config import get_settings  # noqa: E402
from mktcore.db import session_scope  # noqa: E402
from mktcore.db.models import ImportBatch, ImportQuarantine  # noqa: E402
from mktcore.security import HEADER_NAME  # noqa: E402

from .conftest import poll_job  # noqa: E402

client = TestClient(app)
TOKEN = "quarantine-test-token"
RAW_PHONE = "09121234567"


@pytest.fixture(scope="module")
def quarantined_row() -> int:
    """یک ردیفِ قرنطینه با ستونِ موبایل، روی دفتر کلِ داده‌ی نمونه."""
    r = client.post("/api/sample")
    data = r.json()
    mapping = {x["role"]: x["suggested"] for x in data["roles"] if x["suggested"]}
    r = client.post("/api/analyze", json={
        "session_id": data["session_id"], "mapping": mapping, "horizon": 3,
    })
    poll_job(client, r.json()["job_id"])
    with session_scope() as session:
        batch = session.scalars(select(ImportBatch).order_by(ImportBatch.id.desc())).first()
        assert batch is not None
        row = ImportQuarantine(
            business_id=batch.business_id,
            batch_id=batch.id,
            row_number=7,
            raw_payload_json=json.dumps(
                {"تاریخ": "1403/01/01", "موبایل": RAW_PHONE, "مشتری": "آزمون", "مبلغ": None},
                ensure_ascii=False,
            ),
            reason_code="invalid_amount",
            reason_detail_fa="مبلغ نامعتبر",
        )
        session.add(row)
        session.flush()
        return int(row.id)


def test_quarantine_listing_masks_phone_numbers(quarantined_row):
    r = client.get("/api/v1/quarantine?limit=200")
    assert r.status_code == 200, r.text
    rows = {row["id"]: row for row in r.json()["rows"]}
    raw = rows[quarantined_row]["raw"]

    assert raw["موبایل"] != RAW_PHONE
    assert raw["موبایل"].endswith("4567") and "*" in raw["موبایل"]
    assert raw["مشتری"] == "آزمون", "مقدارِ غیرِ شماره دست نمی‌خورد"
    assert raw["مبلغ"] is None
    assert RAW_PHONE not in r.text


def test_quarantine_listing_requires_the_token_when_one_is_configured(quarantined_row, monkeypatch):
    monkeypatch.setattr(get_settings(), "mkt_api_token", TOKEN, raising=False)

    assert client.get("/api/v1/quarantine").status_code == 401
    ok = client.get("/api/v1/quarantine", headers={HEADER_NAME: TOKEN})
    assert ok.status_code == 200


def test_phone_shaped_values_are_masked_even_under_other_keys(quarantined_row):
    """نگاشت شماره را در ستونِ customer_id هم کپی می‌کند؛ شماره‌ی بدشکل/غیرایرانی هم شکلِ شماره دارد."""
    from api.v1 import _mask_raw_row

    masked = _mask_raw_row({"customer_id": 9121234567, "order_id": "F12", "note": "0044 7700 900123",
                            "amount": 1250000, "qty": 3, "date": "1402/01/05",
                            "amount_text": "1,250,000", "iso": "2024-01-05"})
    assert masked["customer_id"] != 9121234567 and str(masked["customer_id"]).endswith("4567")
    assert masked["note"] != "0044 7700 900123" and "*" in masked["note"]
    assert masked["order_id"] == "F12", "شناسه‌ی کوتاهِ غیرشماره‌ای دست نمی‌خورد"
    assert masked["amount"] == 1250000 and masked["qty"] == 3, "مبلغ زیرِ ستونِ غیرشناسه ماسک نمی‌شود"
    assert masked["date"] == "1402/01/05" and masked["iso"] == "2024-01-05"
    assert masked["amount_text"] == "1,250,000", "مبلغِ با جداکننده‌ی هزارگان شماره نیست"
