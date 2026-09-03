"""گاردِ ثبت در دفتر کل (§۸.۵): خطای مالیِ خطرناک ⇒ هیچ خطی نوشته نمی‌شود.

سند: «واحدِ پولِ نامعلوم، علامتِ وارونه و جمعِ ناممکن باید ثبت در دفتر کل را تا
رفع متوقف کنند.» تا پیش از این، `record_analysis` وضعیتِ FAIL را فقط روی ردیفِ
دسته می‌نوشت و خطوط، مشتریان، ویژگی‌ها و فرصت‌ها از همان فایلِ مشکوک ساخته
می‌شدند. تصمیمِ کاربر: فقط همین سه (C04، C05، واحد پول)؛ بقیه هشدار می‌مانند.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import func, select

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

from api.canonical_hook import record_analysis  # noqa: E402
from api.v1 import _batch_summary  # noqa: E402

from mktcore.analysis.validation import (  # noqa: E402
    POSTING_BLOCKERS,
    UNKNOWN_MONEY_UNIT_ID,
    ValidationReport,
    posting_block_reasons,
)
from mktcore.db import session_scope  # noqa: E402
from mktcore.db.migrations import reset_ensure_cache  # noqa: E402
from mktcore.db.models import (  # noqa: E402
    Customer,
    CustomerFeature,
    ImportBatch,
    ImportRowRaw,
    Opportunity,
    Order,
    OrderLine,
    Product,
)
from mktcore.db.repo_import import RECONCILE_BLOCKED  # noqa: E402

from .test_validation_gate import _rows  # noqa: E402

COLS = ["تاریخ", "مبلغ", "مشتری", "فاکتور", "کالا", "شعبه"]


@pytest.fixture
def isolated_ledger(tmp_path, monkeypatch):
    """دفتر کلِ جدا برای هر تست — همان الگوی test_canonical_hook."""
    from mktcore.config import get_settings

    reset_ensure_cache()
    monkeypatch.setenv("MKT_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()
    reset_ensure_cache()


def _ambiguous_bundle():
    """۶۰ فروش + ۵۵ ردیفِ منفی ⇒ C04 (قراردادِ علامت) FAIL — همان داده‌ی دروازه‌ی اعتبارسنجی."""
    rows = _rows(60)
    rows += [(f"1402/01/{(i % 27) + 1:02d}", -(500 + i), f"D{i}", f"G{i}", "P", "الف")
             for i in range(55)]
    raw = pd.DataFrame(rows, columns=COLS)
    return _analyze_with_frame(raw)


def _analyze_with_frame(raw: pd.DataFrame):
    from mktcore.ingest.cleaning import clean_frame
    from mktcore.ingest.mapper import SchemaMapper
    from mktcore.ingest.schema import ColumnRole
    from mktcore.pipeline import run_analysis

    mapping = {ColumnRole.DATE: "تاریخ", ColumnRole.REVENUE: "مبلغ",
               ColumnRole.CUSTOMER_ID: "مشتری", ColumnRole.ORDER_ID: "فاکتور",
               ColumnRole.PRODUCT: "کالا", ColumnRole.BRANCH: "شعبه"}
    clean = clean_frame(SchemaMapper().apply(raw, mapping))
    return clean, run_analysis(clean, with_forecast=False)


def _count(session, model) -> int:
    return int(session.scalar(select(func.count(model.id))) or 0)


# ═══════════════════════════════════════════ واحد: کدام کنترل‌ها مسدود می‌کنند
def test_only_financially_dangerous_checks_block():
    assert POSTING_BLOCKERS == {"C04", "C05"}

    report = ValidationReport()
    report.add("C04", "قرارداد علامت", False, "مبهم")
    report.add("C06", "آشتی شعب", False, "اختلاف")          # FAIL ولی مسدودکننده نیست
    report.add("C05", "خالص = ناخالص − برگشت", True)
    report.finalize()

    reasons = posting_block_reasons(report, file_currency="تومان")
    assert [r["check_id"] for r in reasons] == ["C04"]
    assert reasons[0]["detail"] == "مبهم"


def test_unknown_money_unit_blocks_even_with_a_clean_report():
    clean = ValidationReport()
    clean.add("C04", "قرارداد علامت", True)
    clean.finalize()

    assert posting_block_reasons(clean, file_currency="تومان") == []
    assert posting_block_reasons(clean, file_currency="ریال") == []
    reasons = posting_block_reasons(clean, file_currency="دلار")
    assert [r["check_id"] for r in reasons] == [UNKNOWN_MONEY_UNIT_ID]
    assert posting_block_reasons(None, file_currency=None) == []


# ═══════════════════════════════════════════ مسیر واقعی: هوک ⇒ دفتر کل
def test_ambiguous_sign_blocks_canonical_posting(isolated_ledger):
    clean, bundle = _ambiguous_bundle()
    assert bundle.validation.status == "FAIL"

    out = record_analysis(
        clean, bundle, session_id="s-blocked", filename="مشکوک.xlsx",
        dataset_key="blocked-1", display_currency="تومان", file_currency="تومان",
    )

    assert out is not None and out["ok"] is True
    assert out["posted"] is False
    assert "C04" in [b["check_id"] for b in out["blocked_by"]]
    assert "متوقف" in out["note_fa"] and "نوع سند" in out["note_fa"]
    assert out["features_written"] == 0 and out["opportunities"] is None

    with session_scope() as session:
        batch = session.get(ImportBatch, out["batch_id"])
        assert batch.reconcile_status == RECONCILE_BLOCKED
        assert batch.validation_status == "FAIL"
        assert batch.lines_inserted == 0
        notes = json.loads(batch.notes_json)
        assert notes["posted"] is False
        assert [b["check_id"] for b in notes["blocked_by"]] == ["C04"]
        # هیچ چیزی از فایلِ مشکوک به دفتر کل نرفته …
        for model in (OrderLine, Order, Customer, Product, CustomerFeature, Opportunity):
            assert _count(session, model) == 0, model.__name__
        # … ولی شواهدِ ورود (ردیف خام) برای رسیدگیِ اپراتور مانده
        assert _count(session, ImportRowRaw) > 0
        summary = _batch_summary(batch)
    assert summary["posted"] is False
    assert summary["blocked_by"][0]["check_id"] == "C04"


def test_a_clean_file_still_posts(isolated_ledger):
    clean, bundle = _analyze_with_frame(pd.DataFrame(_rows(120), columns=COLS))

    out = record_analysis(
        clean, bundle, session_id="s-clean", filename="سالم.xlsx",
        dataset_key="clean-1", display_currency="تومان", file_currency="تومان",
    )

    assert out["posted"] is True and out["blocked_by"] == []
    assert out["lines_inserted"] > 0
    with session_scope() as session:
        batch = session.get(ImportBatch, out["batch_id"])
        assert batch.reconcile_status != RECONCILE_BLOCKED
        assert _batch_summary(batch)["posted"] is True
        assert _count(session, OrderLine) > 0


def test_fixing_the_mapping_lets_the_same_file_post(isolated_ledger):
    """راهِ رفع باز است: بعد از اصلاح، همان فایل ثبت می‌شود (نسخه‌ی بعدیِ همان dataset)."""
    clean, bundle = _ambiguous_bundle()
    blocked = record_analysis(
        clean, bundle, session_id="s-1", dataset_key="same-file",
        display_currency="تومان", file_currency="تومان",
    )
    assert blocked["posted"] is False

    fixed_rows = [(d, abs(amount), c, f, p, b) for d, amount, c, f, p, b in
                  [*_rows(60), *[(f"1402/01/{(i % 27) + 1:02d}", -(500 + i), f"D{i}", f"G{i}", "P", "الف")
                                 for i in range(55)]]]
    clean2, bundle2 = _analyze_with_frame(pd.DataFrame(fixed_rows, columns=COLS))
    assert bundle2.validation.status != "FAIL"
    posted = record_analysis(
        clean2, bundle2, session_id="s-2", dataset_key="same-file",
        display_currency="تومان", file_currency="تومان",
    )

    assert posted["posted"] is True and posted["revision"] == blocked["revision"] + 1
    with session_scope() as session:
        assert _count(session, OrderLine) == 115
