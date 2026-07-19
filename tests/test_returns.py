"""تست‌های برگشت از فروش: جداسازی در پاک‌سازی و خالص‌سازی KPI (Design C+)."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from mktcore.analysis.kpis import compute_kpis  # noqa: E402
from mktcore.ingest.cleaning import clean_frame, get_returns  # noqa: E402
from mktcore.ingest.mapper import SchemaMapper  # noqa: E402
from mktcore.ingest.schema import ColumnRole  # noqa: E402


def _clean(raw: pd.DataFrame) -> pd.DataFrame:
    mapping = {ColumnRole.DATE: "تاریخ", ColumnRole.REVENUE: "مبلغ",
               ColumnRole.CUSTOMER_ID: "مشتری", ColumnRole.ORDER_ID: "فاکتور",
               ColumnRole.PRODUCT: "کالا"}
    return clean_frame(SchemaMapper().apply(raw, mapping))


def _fixture_with_returns() -> pd.DataFrame:
    rows = []
    # ۲۰۰ ردیف فروش عادی
    for i in range(200):
        rows.append((f"1402/{(i % 6) + 1:02d}/{(i % 27) + 1:02d}", 1000 + i,
                     f"C{i % 40}", f"F{i:04d}", f"P{i % 10}"))
    # ۱۲ برگشت (مبلغ منفی) — یکی فاکتور کاملاً برگشتی
    for j in range(11):
        rows.append(("1402/06/15", -(500 + j), f"C{j}", f"F{j:04d}R", f"P{j % 10}"))
    rows.append(("1402/06/20", -1000, "C0", "F0000", "P0"))  # برگشت کامل F0000
    df = pd.DataFrame(rows, columns=["تاریخ", "مبلغ", "مشتری", "فاکتور", "کالا"])
    return df


def test_returns_split_from_main_frame():
    clean = _clean(_fixture_with_returns())
    returns = get_returns(clean)
    assert len(returns) == 12
    assert (returns["revenue"] < 0).all()
    # فریم اصلی فقط خرید مثبت
    assert (clean["revenue"] > 0).all()
    assert len(clean) == 200
    # برگشت‌ها جزو dropped_invalid شمرده نمی‌شوند
    assert clean.attrs["dropped_invalid_rows"] == 0
    assert clean.attrs.get("n_returns") == 12


def test_kpi_netting_gross_returns_net():
    clean = _clean(_fixture_with_returns())
    k = compute_kpis(clean)
    gross = float(clean["revenue"].sum())
    returns_total = float(-get_returns(clean)["revenue"].sum())
    assert k.gross_sales == gross
    assert k.returns_total == returns_total
    assert k.returns_count == 12
    assert abs(k.net_sales - (gross - returns_total)) < 1e-6
    # سرخط = خالص
    assert k.total_revenue == k.net_sales
    assert k.return_rate is not None and 0 < k.return_rate < 1


def test_fully_returned_invoice_not_counted_as_order():
    clean = _clean(_fixture_with_returns())
    k = compute_kpis(clean)
    # F0000 (1000) کاملاً با -1000 برگشت خورده → از شمارش سفارش خارج
    assert k.n_orders == 199
    assert k.aov == k.net_sales / 199


def test_no_returns_file_unchanged():
    raw = pd.DataFrame({
        "تاریخ": ["1402/01/01", "1402/01/02"],
        "مبلغ": ["1000", "2000"],
        "مشتری": ["الف", "ب"],
        "فاکتور": ["F1", "F2"],
        "کالا": ["x", "y"],
    })
    clean = _clean(raw)
    assert get_returns(clean).empty
    k = compute_kpis(clean)
    assert k.total_revenue == 3000.0
    assert k.gross_sales == k.net_sales == 3000.0
    assert k.returns_count == 0 and k.returns_total == 0.0


def test_majority_negative_flip_then_minority_returns():
    """فایل حسابداری: فروش منفی ثبت شده؛ بعد از flip، برگشت‌ها اقلیت منفی می‌شوند."""
    rows = []
    for i in range(50):
        rows.append((f"1402/02/{(i % 28) + 1:02d}", -(1000 + i), f"C{i}", f"F{i}", "P1"))
    rows.append(("1402/02/10", 700, "C1", "FR1", "P1"))  # برگشت (مثبت در ثبت حسابداری)
    raw = pd.DataFrame(rows, columns=["تاریخ", "مبلغ", "مشتری", "فاکتور", "کالا"])
    clean = _clean(raw)
    assert "revenue" in clean.attrs["sign_flipped"]
    assert (clean["revenue"] > 0).all()
    returns = get_returns(clean)
    assert len(returns) == 1
    assert float(returns["revenue"].iloc[0]) == -700.0


def test_ambiguous_sign_share_warns():
    """سهم منفی بین ۴۰٪ و ۶۰٪ → پرچم بررسی قرارداد علامت."""
    rows = []
    for i in range(10):
        rows.append(("1402/03/01", 100, f"C{i}", f"F{i}", "P"))
    for i in range(9):
        rows.append(("1402/03/02", -100, f"D{i}", f"G{i}", "P"))
    raw = pd.DataFrame(rows, columns=["تاریخ", "مبلغ", "مشتری", "فاکتور", "کالا"])
    clean = _clean(raw)
    assert clean.attrs.get("ambiguous_sign") is True
