"""آشتیِ کاملِ §۸.۶ — L10 (کالا)، L11 (تخفیف)، L12 (قرنطینه) و ردیفِ آشتی برای دسته‌ی مسدود.

قاعده‌ها:
* L10 نامتقارن است مثل L06: دفتر < فایل یعنی ادغامِ مترادف (OK با توضیح)، دفتر > فایل
  یعنی یک نام به چند کالا تبدیل شده (MISMATCH)، خطِ بی‌کالا WARN.
* L11 فقط وقتی ستونِ تخفیف **مبلغی** است سنجیده می‌شود؛ بدون ستون یا نسبتی ⇒ SKIPPED
  («سنجیده نشد») که برچسبِ آشتیِ دسته را عوض **نمی‌کند**.
* L12 اطلاع است: مبلغِ ردیف‌های کنارگذاشته تا «کلِ مبدأ» = دفتر + قرنطینه بازسازی‌پذیر بماند.
* دسته‌ی مسدود (§۸.۵) هم ردیف‌های L01–L12 می‌گیرد: همه WARN با سمتِ دفترِ خالی.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import func, select

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

from mktcore.analysis.kpis import compute_kpis  # noqa: E402
from mktcore.db import session_scope  # noqa: E402
from mktcore.db.models import ImportReconciliation, OrderLine, Product  # noqa: E402
from mktcore.db.repo_import import (  # noqa: E402
    BLOCKED_CHECK_DETAIL_FA,
    CHECK_SKIPPED,
    RECONCILE_BLOCKED,
    ReconcileCheck,
    _add_product_count_check,
    _quarantined_amount,
    write_import,
)
from mktcore.ingest.cleaning import (  # noqa: E402
    REASON_DUPLICATE,
    REASON_INVALID_DATE,
    clean_frame,
    get_exclusions,
)
from mktcore.ingest.mapper import SchemaMapper  # noqa: E402
from mktcore.ingest.schema import ColumnRole  # noqa: E402

_COLS = ["تاریخ", "مبلغ", "مشتری", "فاکتور", "کالا"]
_MAPPING = {
    ColumnRole.DATE: "تاریخ", ColumnRole.REVENUE: "مبلغ", ColumnRole.CUSTOMER_ID: "مشتری",
    ColumnRole.ORDER_ID: "فاکتور", ColumnRole.PRODUCT: "کالا",
}


def _clean(rows: list[tuple], columns=_COLS, mapping=None) -> pd.DataFrame:
    raw = pd.DataFrame(rows, columns=columns)
    return clean_frame(SchemaMapper().apply(raw, mapping or _MAPPING))


def _checks(db: Path, batch_id: int) -> dict[str, ImportReconciliation]:
    with session_scope(db) as session:
        rows = session.scalars(
            select(ImportReconciliation).where(ImportReconciliation.batch_id == batch_id)
        ).all()
        for row in rows:
            session.expunge(row)
    return {r.check_id: r for r in rows}


def _rows(n: int = 30, product: str = "کالا") -> list[tuple]:
    return [(f"1402/{(i % 9) + 1:02d}/05", 100_000 + i, f"C{i % 5}", f"F{i}", product)
            for i in range(n)]


# ═══════════════════════════════════════════════ L10 — شمار کالای یکتا
def test_l10_synonym_spellings_count_once_and_match_the_ledger(tmp_path):
    rows = [(f"1402/01/{i + 1:02d}", 100_000, "C1", f"F{i}", name)
            for i, name in enumerate(["کالا الف", "کالا  الف", "کالای ب", "کالا الف "])]
    clean = _clean(rows)
    db = tmp_path / "app.db"
    result = write_import(clean, kpis=compute_kpis(clean), db_path=db)

    l10 = _checks(db, result.batch_id)["L10"]
    assert (l10.status, l10.expected_text, l10.actual_text) == ("OK", "2", "2")
    with session_scope(db) as session:
        assert session.scalar(select(func.count()).select_from(Product)) == 2
    assert result.reconcile_status == "RECONCILED"


def test_l10_alias_to_existing_product_is_a_merge_not_an_error(tmp_path):
    """نامِ تازه که به کالای موجود (alias) وصل می‌شود، شمارِ دفتر را کمتر می‌کند — OK با توضیح."""
    from mktcore.db.models import ProductAlias

    db = tmp_path / "app.db"
    first = _clean(_rows(5, product="کالا الف"))
    write_import(first, kpis=compute_kpis(first), db_path=db)
    with session_scope(db) as session:
        product_id = session.scalar(select(Product.id))
        session.add(ProductAlias(
            business_id=1, product_id=product_id, alias_norm="کالای ب", alias_raw="کالای ب",
            source="test",
        ))
    second = _clean(_rows(6, product="کالای ب"))
    result = write_import(second, kpis=compute_kpis(second), db_path=db, dataset_key="b")

    l10 = _checks(db, result.batch_id)["L10"]
    assert (l10.status, l10.expected_text, l10.actual_text) == ("OK", "1", "1")


def test_l10_rules_are_asymmetric():
    checks: list[ReconcileCheck] = []
    _add_product_count_check(checks, 3, 4, 0, has_column=True)
    _add_product_count_check(checks, 3, 2, 0, has_column=True)
    _add_product_count_check(checks, 3, 3, 2, has_column=True)
    _add_product_count_check(checks, 3, 3, 0, has_column=True)
    _add_product_count_check(checks, None, None, None, has_column=False)
    _add_product_count_check(checks, 3, None, None, has_column=True)
    assert [c.status for c in checks] == ["MISMATCH", "OK", "WARN", "OK", CHECK_SKIPPED, "WARN"]
    assert "چند کالا" in checks[0].detail_fa
    assert "مترادف" in checks[1].detail_fa
    assert "2 خط" in checks[2].detail_fa
    assert all(c.check_id == "L10" for c in checks)


def test_l10_lines_without_a_product_name_warn_but_do_not_mismatch(tmp_path):
    rows = _rows(6)
    rows[2] = (rows[2][0], rows[2][1], rows[2][2], rows[2][3], "")
    clean = _clean(rows)
    db = tmp_path / "app.db"
    result = write_import(clean, kpis=compute_kpis(clean), db_path=db)

    l10 = _checks(db, result.batch_id)["L10"]
    assert l10.status == "WARN" and "1 خط" in l10.detail_fa
    assert (l10.expected_text, l10.actual_text) == ("1", "1")
    assert result.reconcile_status == "RECONCILED_WITH_WARNINGS"


# ═══════════════════════════════════════════════ L11 — جمع تخفیف
_COLS_DISC = [*_COLS, "تخفیف"]
_MAPPING_DISC = {**_MAPPING, ColumnRole.DISCOUNT: "تخفیف"}


def _discount_rows(disc_of) -> list[tuple]:
    return [(f"1402/{(i % 9) + 1:02d}/05", 400_000 + i, f"C{i % 5}", f"F{i}", "کالا", disc_of(i))
            for i in range(24)]


def test_l11_amount_discount_reconciles_in_rial(tmp_path):
    clean = _clean(_discount_rows(lambda i: 50_000 if i % 2 else 0), _COLS_DISC, _MAPPING_DISC)
    assert clean.attrs["discount_is_amount"] is True
    kpis = compute_kpis(clean)
    db = tmp_path / "app.db"
    result = write_import(clean, kpis=kpis, db_path=db, display_currency="تومان")

    l11 = _checks(db, result.batch_id)["L11"]
    assert l11.status == "OK"
    assert l11.expected_text == str(round(kpis.discount_total * 10)) == "6000000"
    with session_scope(db) as session:
        ledger_discount = sum(
            d for d in session.scalars(select(OrderLine.discount_rial)).all() if d is not None
        )
    assert l11.actual_text == str(ledger_discount) == "6000000"
    assert result.reconcile_status == "RECONCILED"


def test_l11_rate_discount_is_not_summable_so_it_is_skipped(tmp_path):
    clean = _clean(_discount_rows(lambda i: 0.1 if i % 2 else 0), _COLS_DISC, _MAPPING_DISC)
    assert clean.attrs["discount_is_amount"] is False
    db = tmp_path / "app.db"
    result = write_import(clean, kpis=compute_kpis(clean), db_path=db)

    l11 = _checks(db, result.batch_id)["L11"]
    assert l11.status == CHECK_SKIPPED and "نسبتی" in l11.detail_fa
    assert l11.expected_text is None and l11.actual_text is None
    assert result.reconcile_status == "RECONCILED", "«سنجیده نشد» برچسب را عوض نمی‌کند"


def test_l11_without_a_discount_column_is_skipped_and_label_unchanged(tmp_path):
    clean = _clean(_rows())
    db = tmp_path / "app.db"
    result = write_import(clean, kpis=compute_kpis(clean), db_path=db)

    l11 = _checks(db, result.batch_id)["L11"]
    assert l11.status == CHECK_SKIPPED and "ستون تخفیف ندارد" in l11.detail_fa
    assert result.reconcile_status == "RECONCILED"


# ═══════════════════════════════════════════════ L12 — قرنطینه
def test_l12_reports_the_amount_of_quarantined_rows(tmp_path):
    rows = _rows(10)
    rows.append(("بدون تاریخ", 7_000, "C1", "X1", "کالا"))   # تاریخ نامعتبر
    rows.append(rows[3])                                        # تکراریِ کامل
    clean = _clean(rows)
    exclusions = get_exclusions(clean)
    assert sorted(exclusions["کد دلیل"]) == sorted([REASON_INVALID_DATE, REASON_DUPLICATE])

    db = tmp_path / "app.db"
    result = write_import(clean, kpis=compute_kpis(clean), db_path=db,
                          display_currency="تومان", file_currency="تومان")

    l12 = _checks(db, result.batch_id)["L12"]
    expected_rial = (7_000 + rows[3][1]) * 10
    assert (l12.status, l12.expected_text, l12.actual_text) == ("OK", str(expected_rial), str(expected_rial))
    assert "2 ردیف" in l12.detail_fa and REASON_DUPLICATE in l12.detail_fa
    assert REASON_INVALID_DATE in l12.detail_fa
    assert result.reconcile_status == "RECONCILED"


def test_l12_quarantined_amount_uses_the_file_unit():
    """ردیف‌های کنارگذاشته با مبلغِ اصلیِ فایل می‌مانند؛ تبدیل با واحدِ **فایل** است."""
    excl = pd.DataFrame({"revenue": [1_000.0, float("nan"), 250.0], "کد دلیل": ["a", "b", "a"]})
    assert _quarantined_amount(excl, file_currency="ریال", display_currency="تومان") == (
        3, 1_250, 1, {"a": 2, "b": 1},
    )
    assert _quarantined_amount(excl, file_currency="تومان", display_currency="تومان") == (
        3, 12_500, 1, {"a": 2, "b": 1},
    )
    assert _quarantined_amount(excl, file_currency=None, display_currency="تومان")[1] == 12_500
    assert _quarantined_amount(None, file_currency=None, display_currency="تومان") == (0, 0, 0, {})
    assert _quarantined_amount(pd.DataFrame(), file_currency=None, display_currency="تومان") == (0, 0, 0, {})


# ═══════════════════════════════════════════════ دسته‌ی مسدود هم ردِ آشتی دارد
def test_blocked_batch_gets_reconciliation_rows_all_warn(tmp_path):
    clean = _clean(_rows(20))
    kpis = compute_kpis(clean)
    db = tmp_path / "app.db"
    result = write_import(
        clean, kpis=kpis, db_path=db,
        posting_blockers=[{"check_id": "C04", "title": "قرارداد علامت", "detail": "مبهم"}],
    )
    assert result.reconcile_status == RECONCILE_BLOCKED and result.posted is False
    assert {c.check_id for c in result.checks} == {f"L{i:02d}" for i in range(1, 13)}

    checks = _checks(db, result.batch_id)
    assert set(checks) == {f"L{i:02d}" for i in range(1, 13)}
    for check_id, row in checks.items():
        assert row.actual_text is None, check_id
        if check_id == "L11":
            assert row.status == CHECK_SKIPPED  # بدون ستون تخفیف: چیزی برای سنجیدن نیست
        else:
            assert row.status == "WARN", check_id
            assert row.detail_fa == BLOCKED_CHECK_DETAIL_FA
    # سمتِ «انتظار» از تحلیل ثبت شده تا ردِ آشتی بماند
    assert checks["L01"].expected_text == "20"
    assert checks["L02"].expected_text == str(round(kpis.gross_sales * 10))
    assert checks["L09"].expected_text == str(kpis.n_orders) == "20"
    assert checks["L10"].expected_text == "1"
    assert checks["L12"].expected_text == "0"
    with session_scope(db) as session:
        assert session.scalar(select(OrderLine.id)) is None


@pytest.mark.parametrize("status", ["OK", "WARN", "MISMATCH", "SKIPPED"])
def test_status_vocabulary_is_shared_with_the_frontend(status):
    """هر وضعیتی که بک‌اند می‌نویسد باید در نوعِ فرانت و نقشه‌ی نشان‌ها باشد."""
    api_ts = (_ROOT / "frontend/src/lib/apiV1.ts").read_text(encoding="utf-8")
    panel = (_ROOT / "frontend/src/components/DataQualityPanel.tsx").read_text(encoding="utf-8")
    assert f'"{status}"' in api_ts
    assert f"{status}:" in panel
