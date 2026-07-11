"""فیکسچرهای مشترک تست."""

from __future__ import annotations

import os
import tempfile
import time

# پیش از هر importِ api/config: دایرکتوری داده‌ی ایزوله + زمان‌بند خاموش در تست
os.environ.setdefault("MKT_DATA_DIR", tempfile.mkdtemp(prefix="mkt-test-"))
os.environ.setdefault("MKT_SCHEDULER_ENABLE", "0")

import pandas as pd  # noqa: E402
import pytest  # noqa: E402

from mktcore.synthetic import generate_synthetic_sales  # noqa: E402


@pytest.fixture(scope="session")
def raw_sales() -> pd.DataFrame:
    """داده‌ی فروش خام مصنوعی (ستون‌های فارسی)."""
    return generate_synthetic_sales(seed=7, days=540)


@pytest.fixture
def messy_frame() -> pd.DataFrame:
    """داده‌ی کثیف: رقم فارسی، تاریخ جلالی، جداکننده‌ی ارز، تکراری، درآمد گم‌شده."""
    return pd.DataFrame(
        {
            "تاریخ": ["1403/01/05", "1403/01/06", "1403/01/06", "2024-03-28"],
            "شماره سفارش": ["A-1", "A-2", "A-2", "A-3"],
            "کد مشتری": ["C1", "C2", "C2", "C3"],
            "نام محصول": ["الف", "ب", "ب", "ج"],
            "تعداد": ["۲", "۱", "۱", "۳"],
            "قیمت واحد": ["۱٬۲۰۰٬۰۰۰", "۸۰۰,۰۰۰", "۸۰۰,۰۰۰", "۵۰۰۰۰۰"],
            "مبلغ کل": ["۲٬۴۰۰٬۰۰۰", "", "", "۱٬۵۰۰٬۰۰۰"],
        }
    )


def poll_job(client, job_id: str, *, timeout: float = 180.0) -> dict:
    """poll کردن یک job تا اتمام؛ نتیجه (یا AssertionError روی خطا/timeout)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = client.get(f"/api/jobs/{job_id}")
        assert r.status_code == 200, r.text
        body = r.json()
        if body["status"] == "done":
            return body["result"]
        if body["status"] == "error":
            raise AssertionError(f"job failed: {body.get('error')}")
        time.sleep(0.25)
    raise AssertionError("job timed out")
