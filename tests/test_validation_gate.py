"""تست دروازه‌ی انتشار: وضعیت PASS/WARN/FAIL و کنترل‌های آشتی."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from mktcore.ingest.cleaning import clean_frame  # noqa: E402
from mktcore.ingest.mapper import SchemaMapper  # noqa: E402
from mktcore.ingest.schema import ColumnRole  # noqa: E402
from mktcore.pipeline import run_analysis  # noqa: E402


def _analyze(raw: pd.DataFrame):
    mapping = {ColumnRole.DATE: "تاریخ", ColumnRole.REVENUE: "مبلغ",
               ColumnRole.CUSTOMER_ID: "مشتری", ColumnRole.ORDER_ID: "فاکتور",
               ColumnRole.PRODUCT: "کالا", ColumnRole.BRANCH: "شعبه"}
    clean = clean_frame(SchemaMapper().apply(raw, mapping))
    return run_analysis(clean, with_forecast=False)


def _rows(n=120, branch="الف"):
    return [(f"1402/{(i % 12) + 1:02d}/{(i % 27) + 1:02d}", 1000 + i,
             f"C{i % 25}", f"F{i}", f"P{i % 8}", branch) for i in range(n)]


def test_validation_pass_on_clean_data():
    raw = pd.DataFrame(_rows(), columns=["تاریخ", "مبلغ", "مشتری", "فاکتور", "کالا", "شعبه"])
    b = _analyze(raw)
    assert b.validation is not None
    assert b.validation.status in ("PASS", "PASS_WITH_WARNINGS")
    ids = {c.check_id for c in b.validation.checks}
    assert {"C04", "C05", "C06", "C08", "C09", "C10"} <= ids
    # همه‌ی کنترل‌های آشتی بحرانی پاس
    assert all(c.status == "PASS" for c in b.validation.checks
               if c.check_id in ("C05", "C06", "C08", "C09", "C10"))


def test_validation_fail_on_ambiguous_sign():
    rows = _rows(60)
    rows += [(f"1402/01/{(i % 27) + 1:02d}", -(500 + i), f"D{i}", f"G{i}", "P", "الف")
             for i in range(55)]
    raw = pd.DataFrame(rows, columns=["تاریخ", "مبلغ", "مشتری", "فاکتور", "کالا", "شعبه"])
    b = _analyze(raw)
    assert b.validation is not None
    assert b.validation.status == "FAIL"
    c04 = next(c for c in b.validation.checks if c.check_id == "C04")
    assert c04.status == "FAIL"


def test_validation_serialized():
    from api.serialize import bundle_to_dict

    raw = pd.DataFrame(_rows(), columns=["تاریخ", "مبلغ", "مشتری", "فاکتور", "کالا", "شعبه"])
    data = bundle_to_dict(_analyze(raw))
    assert "validation" in data
    assert data["validation"]["status"] in ("PASS", "PASS_WITH_WARNINGS")
    assert data["validation"]["checks"]
