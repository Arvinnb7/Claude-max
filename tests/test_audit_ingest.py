"""تست‌های ممیزی ingest: پارس پرانتز حسابداری، provenance ردیف و ثبت حذف‌ها."""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from mktcore.ingest.cleaning import _to_number, clean_frame, get_exclusions  # noqa: E402
from mktcore.ingest.mapper import SchemaMapper  # noqa: E402
from mktcore.ingest.schema import SOURCE_ROW, ColumnRole  # noqa: E402


def test_paren_accounting_negative():
    assert _to_number("(1,250)") == -1250.0
    assert _to_number("(۱٬۲۵۰)") == -1250.0
    assert _to_number("(1250.5)") == -1250.5
    assert _to_number("1,250") == 1250.0
    assert _to_number("-1250") == -1250.0
    assert math.isnan(_to_number("()"))
    assert math.isnan(_to_number("(تومان)"))


def _mapped_frame(raw: pd.DataFrame) -> pd.DataFrame:
    m = SchemaMapper()
    mapping = {ColumnRole.DATE: "تاریخ", ColumnRole.REVENUE: "مبلغ",
               ColumnRole.CUSTOMER_ID: "مشتری"}
    return m.apply(raw, mapping)


def test_source_row_provenance_and_exclusions():
    raw = pd.DataFrame({
        "تاریخ": ["1402/01/01", "بدون‌تاریخ", "1402/01/03", "1402/01/03", "1402/01/05"],
        "مبلغ": ["1000", "2000", "abc", "3000", "3000"],
        "مشتری": ["الف", "ب", "ج", "د", "د"],
    })
    # ردیف ۵ را عمداً تکرارِ کامل ردیف ۴ می‌کنیم (به‌جز تاریخ که یکسان شود)
    raw.loc[4, "تاریخ"] = "1402/01/03"

    std = _mapped_frame(raw)
    assert SOURCE_ROW in std.columns
    assert list(std[SOURCE_ROW]) == [0, 1, 2, 3, 4]

    clean = clean_frame(std)
    # ردیف‌های سالم: 0 و 3 (ردیف 4 تکرار 3 است)
    assert set(clean[SOURCE_ROW]) == {0, 3}
    assert clean.attrs["dropped_invalid_rows"] == 2
    assert clean.attrs["dropped_duplicate_rows"] == 1

    excl = get_exclusions(clean)
    assert len(excl) == 3
    reasons = dict(zip(excl[SOURCE_ROW], excl["دلیل"], strict=True))
    assert reasons[1] == "تاریخ نامعتبر"
    assert reasons[2] == "مبلغ نامعتبر"
    assert reasons[4] == "ردیف تکراری"


def test_exclusions_empty_for_clean_data():
    raw = pd.DataFrame({
        "تاریخ": ["1402/01/01", "1402/01/02"],
        "مبلغ": ["1000", "2000"],
        "مشتری": ["الف", "ب"],
    })
    clean = clean_frame(_mapped_frame(raw))
    assert get_exclusions(clean).empty
    assert clean.attrs["dropped_invalid_rows"] == 0


def test_source_row_does_not_leak_into_numeric_aggregations():
    """ستون فنی نباید در جمع‌های ستون-صریح تحلیل‌ها اثر بگذارد (KPI smoke)."""
    from mktcore.analysis.kpis import compute_kpis

    raw = pd.DataFrame({
        "تاریخ": ["1402/01/01", "1402/01/02", "1402/01/03"],
        "مبلغ": ["100", "200", "300"],
        "مشتری": ["الف", "ب", "ج"],
    })
    clean = clean_frame(_mapped_frame(raw))
    k = compute_kpis(clean)
    assert k.total_revenue == 600.0
