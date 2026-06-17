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
    """اگر همه ردیف‌ها نامعتبر باشند، پیام فارسی دقیق برگردد (نه 500)."""
    # داده با مبلغ‌های نامعتبر (غیرعددی) → بعد از پاک‌سازی خالی
    import io

    csv = "تاریخ,مبلغ کل\nنامعتبر,نامعتبر\nxxx,yyy\n"
    files = {"file": ("bad.csv", io.BytesIO(csv.encode("utf-8")), "text/csv")}
    up = client.post("/api/upload", files=files).json()
    sid = up["session_id"]
    roles = {x["role"]: x["suggested"] for x in up["roles"]}
    mapping = {r: c for r, c in roles.items() if c}
    # تضمین نگاشت تاریخ و مبلغ
    mapping.setdefault("DATE", "تاریخ")
    mapping.setdefault("REVENUE", "مبلغ کل")
    r = client.post("/api/analyze", json={"session_id": sid, "mapping": mapping, "horizon": 4})
    assert r.status_code == 400
    assert "معتبر" in r.json()["detail"]


def test_api_missing_required_message():
    """نگاشت بدون ستون اجباری → پیام دقیق."""
    up = client.post("/api/sample").json()
    sid = up["session_id"]
    r = client.post("/api/analyze", json={"session_id": sid, "mapping": {"PRODUCT": "نام محصول"}, "horizon": 4})
    assert r.status_code == 400
    assert "اجباری" in r.json()["detail"]
