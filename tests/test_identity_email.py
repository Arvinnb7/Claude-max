"""ایمیل به‌عنوان کلیدِ ذخیره‌شده‌ی هویت (§۹.۱ بند ۲) + L13 نامزدهای ادغام.

ادعاها: ایمیلِ نرمال‌شده به‌عنوان `CustomerKey(email)` نوشته می‌شود؛ ایمیلِ بدشکل
نوشته نمی‌شود؛ دو کدِ مشتری با یک ایمیل **دو** مشتری می‌مانند (بدون ادغامِ خودکار) و
L13 = ۱ با شناسه‌ها؛ پیوند با شماره دست‌نخورده است.
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

from mktcore.analysis.kpis import compute_kpis  # noqa: E402
from mktcore.db import session_scope  # noqa: E402
from mktcore.db.migrations import reset_ensure_cache  # noqa: E402
from mktcore.db.models import Customer, CustomerKey, ImportBatch, ImportReconciliation  # noqa: E402
from mktcore.db.repo_import import write_import  # noqa: E402
from mktcore.identity import normalize_email  # noqa: E402
from mktcore.ingest.cleaning import clean_frame  # noqa: E402
from mktcore.ingest.mapper import SchemaMapper  # noqa: E402
from mktcore.ingest.schema import ColumnRole  # noqa: E402

_COLS = ["تاریخ", "مبلغ", "مشتری", "فاکتور", "کالا", "ایمیل", "موبایل"]
_MAPPING = {
    ColumnRole.DATE: "تاریخ", ColumnRole.REVENUE: "مبلغ", ColumnRole.CUSTOMER_ID: "مشتری",
    ColumnRole.ORDER_ID: "فاکتور", ColumnRole.PRODUCT: "کالا", ColumnRole.EMAIL: "ایمیل",
    ColumnRole.PHONE: "موبایل",
}


@pytest.fixture(autouse=True)
def _isolate_schema_cache():
    reset_ensure_cache()
    yield
    reset_ensure_cache()


def _clean(rows: list[tuple]) -> pd.DataFrame:
    return clean_frame(SchemaMapper().apply(pd.DataFrame(rows, columns=_COLS), _MAPPING))


def _l13(db: Path, batch_id: int) -> ImportReconciliation:
    with session_scope(db) as session:
        row = session.scalar(select(ImportReconciliation).where(
            ImportReconciliation.batch_id == batch_id, ImportReconciliation.check_id == "L13",
        ))
        assert row is not None
        session.expunge(row)
        return row


@pytest.mark.parametrize(("raw", "expected"), [
    (" Ali.R@Example.COM ", "ali.r@example.com"),
    ("ali@example.ir", "ali@example.ir"),
    ("ali@example", None),
    ("not an email", None),
    ("", None),
    (None, None),
    (float("nan"), None),
    ("nan", None),
])
def test_email_normalisation_is_strict(raw, expected):
    assert normalize_email(raw) == expected


def test_email_is_written_as_a_key_and_malformed_email_is_not(tmp_path):
    rows = [
        ("1402/01/05", 100_000, "C1", "F1", "کالا", " Ali@Example.com ", ""),
        ("1402/01/06", 120_000, "C2", "F2", "کالا", "بدون‌ایمیل", ""),
    ]
    clean = _clean(rows)
    db = tmp_path / "app.db"
    result = write_import(clean, kpis=compute_kpis(clean), db_path=db)

    with session_scope(db) as session:
        keys = {(k.key_type, k.key_value): k.customer_id
                for k in session.scalars(select(CustomerKey)).all()}
        customers = {c.canonical_key: c for c in session.scalars(select(Customer)).all()}
        assert keys[("email", "ali@example.com")] == customers["C1"].id
        assert customers["C1"].email == "ali@example.com"
        assert not [k for k in keys if k[0] == "email" and k[1] != "ali@example.com"]
        assert customers["C2"].email is None
    l13 = _l13(db, result.batch_id)
    assert (l13.status, l13.expected_text, l13.actual_text, l13.detail_fa) == ("OK", "0", "0", None)


def test_two_customer_codes_with_one_email_stay_two_customers_and_become_an_l13_candidate(tmp_path):
    db = tmp_path / "app.db"
    first = _clean([("1402/01/05", 100_000, "C1", "F1", "کالا", "same@example.com", "")])
    write_import(first, kpis=compute_kpis(first), db_path=db, dataset_key="a")
    second = _clean([("1402/02/05", 150_000, "C2", "F2", "کالا", "SAME@example.com", "")])
    result = write_import(second, kpis=compute_kpis(second), db_path=db, dataset_key="b")

    with session_scope(db) as session:
        customers = {c.canonical_key: c.id for c in session.scalars(select(Customer)).all()}
        assert set(customers) == {"C1", "C2"}, "ایمیلِ مشترک ادغامِ خودکار نمی‌سازد"
        owner = session.scalar(select(CustomerKey.customer_id).where(
            CustomerKey.key_type == "email", CustomerKey.key_value == "same@example.com",
        ))
        assert owner == customers["C1"], "کلیدِ ایمیل نزدِ مشتریِ اول می‌ماند"
        assert session.scalar(select(func.count()).select_from(CustomerKey).where(
            CustomerKey.key_type == "email")) == 1
        notes = json.loads(session.get(ImportBatch, result.batch_id).notes_json)

    l13 = _l13(db, result.batch_id)
    assert (l13.status, l13.expected_text, l13.actual_text) == ("OK", "1", "1")
    assert f"#{customers['C1']}" in l13.detail_fa and f"#{customers['C2']}" in l13.detail_fa
    assert "ادغام نشد" in l13.detail_fa
    assert notes["merge_candidates"] == [{
        "key_type": "email", "resolved_customer_id": customers["C2"],
        "other_customer_id": customers["C1"],
    }]
    assert result.reconcile_status == "RECONCILED", "L13 اطلاع است؛ برچسب را عوض نمی‌کند"


def test_raw_key_pulled_to_another_customer_by_phone_is_also_a_candidate(tmp_path):
    """«C1» بی‌شماره ثبت شده؛ بعد «C1» با شماره‌ی «C2» می‌آید ⇒ به C2 می‌رسد و L13 می‌گوید."""
    db = tmp_path / "app.db"
    first = _clean([
        ("1402/01/05", 100_000, "C1", "F1", "کالا", "", ""),
        ("1402/01/06", 100_000, "C2", "F2", "کالا", "", "09121110000"),
    ])
    write_import(first, kpis=compute_kpis(first), db_path=db, dataset_key="a")
    second = _clean([("1402/02/05", 150_000, "C1", "F3", "کالا", "", "09121110000")])
    result = write_import(second, kpis=compute_kpis(second), db_path=db, dataset_key="b")

    with session_scope(db) as session:
        customers = {c.canonical_key: c.id for c in session.scalars(select(Customer)).all()}
        assert set(customers) == {"C1", "C2"}
    l13 = _l13(db, result.batch_id)
    assert l13.actual_text == "1" and "raw_key" in l13.detail_fa


def test_phone_resolution_is_unchanged_by_email_keys(tmp_path):
    """سه نوشتارِ نام با یک شماره و ایمیل‌های متفاوت ⇒ یک مشتری؛ ایمیل‌ها نامزد نمی‌سازند."""
    rows = [
        ("1402/01/01", 1000, "علی", "F1", "الف", "a@example.com", "09123456789"),
        ("1402/02/02", 2000, "علی رضایی", "F2", "ب", "b@example.com", "۰۹۱۲۳۴۵۶۷۸۹"),
        ("1402/03/03", 3000, "ALI", "F3", "ج", "", "+98 912 345 6789"),
    ]
    clean = _clean(rows)
    db = tmp_path / "app.db"
    result = write_import(clean, kpis=compute_kpis(clean), db_path=db)
    with session_scope(db) as session:
        assert session.scalar(select(func.count()).select_from(Customer)) == 1
        emails = set(session.scalars(select(CustomerKey.key_value).where(
            CustomerKey.key_type == "email")).all())
    assert emails == {"a@example.com", "b@example.com"}
    assert _l13(db, result.batch_id).actual_text == "0"
