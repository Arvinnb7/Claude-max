"""جداسازی داده‌ی نمونه از داده‌ی واقعی.

دکمه‌ی «بارگذاری داده‌ی نمونه» در صفحه‌ی اول برجسته است و طبیعی‌ترین کارِ یک
کاربر تازه، امتحان‌کردن آن **پیش از** فایل واقعی است. پیش از این رفع، مشتریانِ
مصنوعی برای همیشه با مشتریانِ واقعی در یک صندوق فرصت، یک جدول اثر و یک استخر
کمپین قاطی می‌شدند و هیچ راهِ درون‌برنامه‌ای برای جداکردنشان نبود.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

from api.main import app  # noqa: E402

from mktcore.db import session_scope  # noqa: E402
from mktcore.db.models import Business, Customer, ImportBatch  # noqa: E402
from mktcore.db.repo_import import (  # noqa: E402
    DEFAULT_BUSINESS_SLUG,
    SAMPLE_BUSINESS_SLUG,
)

from .conftest import poll_job  # noqa: E402

client = TestClient(app)

_REAL_CUSTOMER = "مشتریِ واقعیِ آزمون"


def _analyze(data: dict) -> None:
    mapping = {x["role"]: x["suggested"] for x in data["roles"] if x["suggested"]}
    r = client.post("/api/analyze", json={
        "session_id": data["session_id"], "mapping": mapping, "horizon": 3,
    })
    assert r.status_code == 200, r.text
    poll_job(client, r.json()["job_id"])


def _run_sample() -> None:
    r = client.post("/api/sample")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("is_sample") is True, "نشستِ نمونه باید علامت بخورد"
    _analyze(body)


def _real_rows() -> pd.DataFrame:
    rows = []
    for i in range(40):
        for month in ("01", "02", "03"):
            rows.append({
                "تاریخ": f"1402/{month}/{(i % 28) + 1:02d}",
                "مبلغ": 700_000 + i * 1000,
                "مشتری": f"{_REAL_CUSTOMER}-{i}",
                "فاکتور": f"R{month}{i}",
                "کالا": "کالای واقعی",
                "موبایل": f"0912111{i:04d}",
            })
    return pd.DataFrame(rows)


def _run_real() -> None:
    buffer = io.BytesIO()
    _real_rows().to_csv(buffer, index=False)
    r = client.post(
        "/api/upload",
        files={"file": ("real.csv", buffer.getvalue(), "text/csv")},
    )
    assert r.status_code == 200, r.text
    # آپلود job پس‌زمینه است؛ payload ستون‌ها نتیجه‌ی همان job است.
    columns = poll_job(client, r.json()["job_id"])
    _analyze(columns)


@pytest.fixture(scope="module", autouse=True)
def both_datasets():
    """اول نمونه، بعد واقعی — همان ترتیبی که یک کاربر تازه طی می‌کند."""
    _run_sample()
    _run_real()


# ═══════════════════════════════════════ جداسازی در دفتر کل
def test_sample_and_real_live_in_separate_businesses():
    with session_scope() as session:
        slugs = set(session.scalars(select(Business.slug)).all())
    assert SAMPLE_BUSINESS_SLUG in slugs
    assert DEFAULT_BUSINESS_SLUG in slugs


def test_sample_customers_never_land_in_the_real_business():
    with session_scope() as session:
        real_id = session.scalar(
            select(Business.id).where(Business.slug == DEFAULT_BUSINESS_SLUG)
        )
        sample_id = session.scalar(
            select(Business.id).where(Business.slug == SAMPLE_BUSINESS_SLUG)
        )
        real_keys = set(session.scalars(
            select(Customer.canonical_key).where(Customer.business_id == real_id)
        ).all())
        sample_keys = set(session.scalars(
            select(Customer.canonical_key).where(Customer.business_id == sample_id)
        ).all())

    assert sample_keys, "داده‌ی نمونه باید مشتری ساخته باشد"
    assert real_keys, "داده‌ی واقعی باید مشتری ساخته باشد"
    assert not (real_keys & sample_keys), "هیچ مشتری‌ای نباید در هر دو باشد"
    assert any(_REAL_CUSTOMER in k for k in real_keys)
    assert not any(_REAL_CUSTOMER in k for k in sample_keys)


def test_imports_are_attributed_to_the_right_business():
    with session_scope() as session:
        sample_id = session.scalar(
            select(Business.id).where(Business.slug == SAMPLE_BUSINESS_SLUG)
        )
        sample_batches = session.scalars(
            select(ImportBatch.filename).where(ImportBatch.business_id == sample_id)
        ).all()
    assert sample_batches, "بارگذاری نمونه باید در کسب‌وکار نمونه ثبت شده باشد"
    assert all("real.csv" != (f or "") for f in sample_batches)


# ═══════════════════════════════ خواندن: آخرین تحلیل ملاک است
def test_inbox_shows_only_the_most_recently_analysed_dataset():
    """آخرین تحلیل، فایل واقعی بود — پس صندوق نباید مشتریِ نمونه نشان دهد."""
    body = client.get("/api/v1/customers?limit=200").json()
    assert body["available"] is True
    names = [str(item.get("key") or "") for item in body["items"]]
    assert names, "پس از تحلیل واقعی، فهرست نباید خالی باشد"
    assert any(_REAL_CUSTOMER in n for n in names)


def test_running_the_sample_again_shows_the_sample_not_a_mixture():
    """دمو باید کار کند: بعد از اجرای نمونه، همان دیده شود — نه مخلوط."""
    _run_sample()
    try:
        body = client.get("/api/v1/customers?limit=200").json()
        names = [str(item.get("key") or "") for item in body["items"]]
        assert names, "بعد از تحلیل نمونه، صندوق نباید خالی باشد"
        assert not any(_REAL_CUSTOMER in n for n in names), (
            "مشتریِ واقعی نباید در نمای داده‌ی نمونه ظاهر شود"
        )
    finally:
        _run_real()  # بازگرداندن وضعیت برای تست‌های بعدی


def test_opportunities_follow_the_same_business():
    body = client.get("/api/v1/opportunities?limit=200").json()
    if not body.get("available"):
        pytest.skip("فرصتی ساخته نشد")
    # هیچ فرصتی از کسب‌وکار دیگری نشت نکرده باشد
    with session_scope() as session:
        sample_id = session.scalar(
            select(Business.id).where(Business.slug == SAMPLE_BUSINESS_SLUG)
        )
        sample_customer_ids = set(session.scalars(
            select(Customer.id).where(Customer.business_id == sample_id)
        ).all())
    shown_ids = {item.get("customer_id") for item in body["items"]}
    assert not (shown_ids & sample_customer_ids)
