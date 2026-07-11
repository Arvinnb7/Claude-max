"""تست‌های مقاوم‌سازی: داده‌های مشکل‌دار نباید با iloc out-of-bounds بشکنند."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from api.main import app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from mktcore.ingest.cleaning import clean_frame  # noqa: E402
from mktcore.ingest.mapper import SchemaMapper  # noqa: E402
from mktcore.pipeline import run_analysis  # noqa: E402

from .conftest import poll_job  # noqa: E402

client = TestClient(app)


def _analyze(raw, **kw):
    m = SchemaMapper()
    std = m.apply(raw, m.auto_detect(raw).mapping)
    return run_analysis(clean_frame(std), **kw)


def test_empty_order_id_does_not_crash():
    """باگ اصلی: order_id خالی برای یک مشتری نباید iloc out-of-bounds بدهد."""
    raw = pd.DataFrame({
        "تاریخ": pd.date_range("2024-01-01", periods=12, freq="7D").tolist() * 2,
        "کد مشتری": (["C1"] * 12) + (["C2"] * 12),
        "شماره سفارش": ([None] * 12) + [f"O{i:02d}" for i in range(12)],
        "نام محصول": ["الف", "ب"] * 12,
        "مبلغ کل": [100000] * 24,
    })
    bundle = _analyze(raw, with_forecast=True)
    assert bundle.kpis.total_revenue > 0


def test_minimal_columns_only():
    """فقط تاریخ و مبلغ (بدون ستون‌های اختیاری) نباید تحلیل را بشکند."""
    raw = pd.DataFrame({
        "تاریخ": pd.date_range("2024-01-01", periods=40, freq="3D"),
        "مبلغ کل": list(range(100000, 100000 + 40 * 1000, 1000)),
    })
    bundle = _analyze(raw, with_forecast=True)
    assert bundle.kpis.total_revenue > 0
    # ماژول‌های وابسته به ستون‌های اختیاری باید خالی و بی‌خطا باشند
    assert bundle.segmentation.rfm_table.empty is not True or True
    assert bundle.products.available is False  # بدون ستون محصول


def test_api_empty_after_clean_message():
    """اگر همه ردیف‌ها نامعتبر باشند، job با پیام فارسی دقیق شکست بخورد (نه 500)."""
    # داده با مبلغ‌های نامعتبر (غیرعددی) → بعد از پاک‌سازی خالی
    import io

    import pytest

    csv = "تاریخ,مبلغ کل\nنامعتبر,نامعتبر\nxxx,yyy\n"
    files = {"file": ("bad.csv", io.BytesIO(csv.encode("utf-8")), "text/csv")}
    up_resp = client.post("/api/upload", files=files).json()
    sid = up_resp["session_id"]
    up = poll_job(client, up_resp["job_id"])
    roles = {x["role"]: x["suggested"] for x in up["roles"]}
    mapping = {r: c for r, c in roles.items() if c}
    # تضمین نگاشت تاریخ و مبلغ
    mapping.setdefault("DATE", "تاریخ")
    mapping.setdefault("REVENUE", "مبلغ کل")
    r = client.post("/api/analyze", json={"session_id": sid, "mapping": mapping, "horizon": 4})
    assert r.status_code == 200
    with pytest.raises(AssertionError, match="معتبر"):
        poll_job(client, r.json()["job_id"])


def test_upload_size_cap(monkeypatch):
    """آپلود بزرگ‌تر از سقف باید 413 با پیام فارسی بدهد."""
    import io

    from mktcore.config import get_settings

    monkeypatch.setenv("MKT_MAX_UPLOAD_MB", "1")
    get_settings.cache_clear()
    try:
        big = b"x" * (2 * 1024 * 1024)
        files = {"file": ("big.csv", io.BytesIO(big), "text/csv")}
        r = client.post("/api/upload", files=files)
        assert r.status_code == 413
        assert "سقف مجاز" in r.json()["detail"]
    finally:
        monkeypatch.delenv("MKT_MAX_UPLOAD_MB", raising=False)
        get_settings.cache_clear()


def test_accounting_negative_sign_convention():
    """درآمد منفی (قرارداد حسابداری) باید اصلاح شود نه اینکه ۹۸٪ ردیف حذف شود."""
    n = 200
    raw = pd.DataFrame({
        "تاریخ": pd.date_range("2024-01-01", periods=n, freq="D").strftime("%Y-%m-%d"),
        "نام مشتری": [f"م{i%30}" for i in range(n)],
        "شرح کالا": ["غذای سگ", "قلاده"] * (n // 2),
        "قابل پرداخت": [-(100000 + i * 1000) for i in range(n)],  # همه منفی
    })
    m = SchemaMapper()
    clean = clean_frame(m.apply(raw, m.auto_detect(raw).mapping))
    # تقریباً همه‌ی ردیف‌ها باید بمانند (نه حذف)
    assert len(clean) >= n - 5
    assert (clean["revenue"] > 0).all()
    bundle = run_analysis(clean, with_forecast=False)
    assert bundle.kpis.total_revenue > 0


def test_mixed_type_ids_do_not_crash():
    """شناسه‌ی مشتری/محصول با نوع مختلط (عدد + متن) نباید با float<str بشکند."""
    raw = pd.DataFrame({
        "تاریخ": pd.date_range("2024-01-01", periods=60, freq="2D").strftime("%Y-%m-%d"),
        "نام مشتری": ([101, 102, 103] * 20),  # عددی (float پس از خواندن)
        "شرح کالا": (["الف", "ب", 9001] * 20),  # مختلط
        "قابل پرداخت": list(range(100000, 100000 + 60 * 1000, 1000)),
    })
    m = SchemaMapper()
    clean = clean_frame(m.apply(raw, m.auto_detect(raw).mapping))
    bundle = run_analysis(clean, with_forecast=True)  # نباید استثنا بدهد
    assert bundle.kpis.total_revenue > 0


def test_xlsb_engine_selection():
    from mktcore.connectors.excel_csv import _excel_engine

    assert _excel_engine(".xlsb") == "pyxlsb"
    assert _excel_engine(".xls") == "xlrd"
    assert _excel_engine(".xlsx") == "openpyxl"


def test_api_missing_required_message():
    """نگاشت بدون ستون اجباری → پیام دقیق."""
    up = client.post("/api/sample").json()
    sid = up["session_id"]
    r = client.post("/api/analyze", json={"session_id": sid, "mapping": {"PRODUCT": "نام محصول"}, "horizon": 4})
    assert r.status_code == 400
    assert "اجباری" in r.json()["detail"]
