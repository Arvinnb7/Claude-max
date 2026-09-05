"""نوشتن دفتر کل canonical — idempotency، هویت پایدار و آشتی با KPI."""

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
from mktcore.db import get_engine, session_scope  # noqa: E402
from mktcore.db.migrations import reset_ensure_cache  # noqa: E402
from mktcore.db.models import (  # noqa: E402
    Business,
    Customer,
    CustomerKey,
    ImportBatch,
    ImportReconciliation,
    Order,
    OrderLine,
    Product,
)
from mktcore.db.repo_import import frame_dataset_key, write_import  # noqa: E402
from mktcore.ingest.cleaning import clean_frame  # noqa: E402
from mktcore.ingest.mapper import SchemaMapper  # noqa: E402
from mktcore.ingest.schema import ColumnRole  # noqa: E402
from mktcore.synthetic import generate_synthetic_sales  # noqa: E402

_MAPPING = {
    ColumnRole.DATE: "تاریخ",
    ColumnRole.REVENUE: "مبلغ",
    ColumnRole.CUSTOMER_ID: "مشتری",
    ColumnRole.ORDER_ID: "فاکتور",
    ColumnRole.PRODUCT: "کالا",
    ColumnRole.PHONE: "موبایل",
}


@pytest.fixture(autouse=True)
def _isolate_schema_cache():
    reset_ensure_cache()
    yield
    reset_ensure_cache()


def _sample_raw() -> pd.DataFrame:
    """۶۰ خرید + ۵ برگشت، با شماره‌ی موبایل در نگارش‌های مختلف."""
    rows = []
    for i in range(60):
        rows.append((
            f"1402/{(i % 11) + 1:02d}/{(i % 27) + 1:02d}",
            10_000 + i * 100,
            f"C{i % 10}",
            f"F{i}",
            f"کالای {i % 7}",
            ["0912345678" + str(i % 10), f"۰۹۱۲۳۴۵۶۷۸{i % 10}", ""][i % 3],
        ))
    for j in range(5):
        rows.append((
            "1402/06/10", -(2_000 + j), f"C{j}", f"R{j}", f"کالای {j}", "",
        ))
    return pd.DataFrame(
        rows, columns=["تاریخ", "مبلغ", "مشتری", "فاکتور", "کالا", "موبایل"],
    )


def _clean_sample() -> pd.DataFrame:
    return clean_frame(SchemaMapper().apply(_sample_raw(), _MAPPING))


def test_write_import_creates_full_ledger(tmp_path: Path):
    clean = _clean_sample()
    kpis = compute_kpis(clean)
    db = tmp_path / "app.db"

    result = write_import(
        clean, session_id="s1", filename="نمونه.xlsx",
        display_currency="تومان", file_currency="تومان",
        kpis=kpis, db_path=db,
    )

    assert result.revision == 1
    assert result.lines_inserted == len(clean) + clean.attrs["n_returns"]
    assert result.lines_updated == 0
    assert result.reconcile_status.startswith("RECONCILED")

    with session_scope(db) as session:
        assert session.scalar(select(func.count()).select_from(Business)) == 1
        assert session.scalar(select(func.count()).select_from(OrderLine)) == 65
        assert session.scalar(
            select(func.count()).select_from(OrderLine).where(OrderLine.is_return)
        ) == 5


def test_returns_are_in_the_ledger_not_dropped(tmp_path: Path):
    """برگشت‌ها باید در دفتر باشند وگرنه فروش خالص دفتر با KPI نمی‌خواند."""
    clean = _clean_sample()
    kpis = compute_kpis(clean)
    db = tmp_path / "app.db"
    write_import(clean, kpis=kpis, display_currency="تومان", db_path=db)

    with session_scope(db) as session:
        gross = session.scalar(
            select(func.sum(OrderLine.revenue_rial)).where(~OrderLine.is_return)
        )
        returns = -session.scalar(
            select(func.sum(OrderLine.revenue_rial)).where(OrderLine.is_return)
        )
    # مبالغ تومان بودند → ریال ده برابر
    assert gross == round(kpis.gross_sales * 10)
    assert returns == round(kpis.returns_total * 10)
    assert gross - returns == round(kpis.net_sales * 10)


def test_reimport_is_idempotent(tmp_path: Path):
    """همان فایل دو بار: جمع و تعداد ثابت، فقط نسخه بالا می‌رود."""
    clean = _clean_sample()
    kpis = compute_kpis(clean)
    db = tmp_path / "app.db"
    key = frame_dataset_key(clean)

    first = write_import(clean, dataset_key=key, kpis=kpis, db_path=db)
    with session_scope(db) as session:
        count_1 = session.scalar(select(func.count()).select_from(OrderLine))
        sum_1 = session.scalar(select(func.sum(OrderLine.revenue_rial)))

    second = write_import(clean, dataset_key=key, kpis=kpis, db_path=db)
    with session_scope(db) as session:
        count_2 = session.scalar(select(func.count()).select_from(OrderLine))
        sum_2 = session.scalar(select(func.sum(OrderLine.revenue_rial)))

    assert (first.revision, second.revision) == (1, 2)
    assert second.lines_inserted == 0
    assert second.lines_updated == first.lines_inserted
    assert (count_2, sum_2) == (count_1, sum_1)


def test_corrected_mapping_updates_values_without_duplicating_rows(tmp_path: Path):
    """تصحیح نگاشت → مقدارِ همان خط به‌روز می‌شود، نه ردیف تازه."""
    db = tmp_path / "app.db"
    clean = _clean_sample()
    key = frame_dataset_key(clean)
    write_import(clean, dataset_key=key, kpis=compute_kpis(clean), db_path=db)

    doubled = clean.copy()
    doubled.attrs = dict(clean.attrs)
    doubled["revenue"] = doubled["revenue"] * 2
    write_import(doubled, dataset_key=key, kpis=compute_kpis(doubled), db_path=db)

    with session_scope(db) as session:
        assert session.scalar(select(func.count()).select_from(OrderLine)) == 65
        purchases = session.scalar(
            select(func.sum(OrderLine.revenue_rial)).where(~OrderLine.is_return)
        )
    assert purchases == round(compute_kpis(doubled).gross_sales * 10)


def test_phone_variants_resolve_to_one_customer(tmp_path: Path):
    """۰۹۱۲... و ۰۹۱۲... با ارقام فارسی باید یک مشتری باشند."""
    raw = pd.DataFrame({
        "تاریخ": ["1402/01/01", "1402/02/02", "1402/03/03"],
        "مبلغ": [1000, 2000, 3000],
        "مشتری": ["علی", "علی رضایی", "ALI"],
        "فاکتور": ["F1", "F2", "F3"],
        "کالا": ["الف", "ب", "ج"],
        "موبایل": ["09123456789", "۰۹۱۲۳۴۵۶۷۸۹", "+98 912 345 6789"],
    })
    clean = clean_frame(SchemaMapper().apply(raw, _MAPPING))
    db = tmp_path / "app.db"
    write_import(clean, kpis=compute_kpis(clean), db_path=db)

    with session_scope(db) as session:
        customers = session.scalars(select(Customer)).all()
        phones = {c.phone_e164 for c in customers}
        keys = session.scalars(select(CustomerKey.key_value)).all()

    # سه نوشتار متفاوتِ نام، ولی یک شماره → یک هویت
    assert len(customers) == 1
    assert phones == {"+989123456789"}
    assert "+989123456789" in keys


def test_customers_persist_across_two_files(tmp_path: Path):
    """همان مشتری در فایل ماه بعد باید همان شناسه را بگیرد — قابلیت اصلیِ نبود."""
    db = tmp_path / "app.db"
    base_cols = ["تاریخ", "مبلغ", "مشتری", "فاکتور", "کالا", "موبایل"]
    first = pd.DataFrame(
        [("1402/01/01", 1000, "C1", "F1", "الف", "09121111111"),
         ("1402/01/02", 2000, "C2", "F2", "ب", "09122222222")],
        columns=base_cols,
    )
    second = pd.DataFrame(
        [("1402/02/01", 3000, "کد۱", "F3", "الف", "۰۹۱۲۱۱۱۱۱۱۱"),
         ("1402/02/02", 4000, "C9", "F4", "ج", "09129999999")],
        columns=base_cols,
    )
    mapper = SchemaMapper()
    for raw in (first, second):
        clean = clean_frame(mapper.apply(raw, _MAPPING))
        write_import(clean, kpis=compute_kpis(clean), db_path=db)

    with session_scope(db) as session:
        customers = session.scalars(select(Customer)).all()
        by_phone = {c.phone_e164: c for c in customers}
        returning = by_phone["+989121111111"]
        lines = session.scalars(
            select(OrderLine).where(OrderLine.customer_id == returning.id)
        ).all()

    assert len(customers) == 3  # نه ۴ — «C1» و «کد۱» یک نفرند
    assert len(lines) == 2  # خرید هر دو فایل به همان هویت وصل شده است
    # بازه‌ی خرید از هر دو فایل ساخته می‌شود، نه فقط آخرین بارگذاری
    assert returning.first_order_date < returning.last_order_date
    assert returning.first_order_date.startswith("2023-03")  # ۱۴۰۲/۰۱/۰۱ میلادی


def test_products_are_deduplicated_by_normalized_name(tmp_path: Path):
    raw = pd.DataFrame({
        "تاریخ": ["1402/01/01", "1402/01/02", "1402/01/03"],
        "مبلغ": [1000, 2000, 3000],
        "مشتری": ["C1", "C2", "C3"],
        "فاکتور": ["F1", "F2", "F3"],
        "کالا": ["غذای خشک ۱٫۵ کیلویی", "غذاي خشك ۱٫۵ كيلويي", "غذای‌خشک ۱٫۵ کیلویی"],
        "موبایل": ["", "", ""],
    })
    clean = clean_frame(SchemaMapper().apply(raw, _MAPPING))
    db = tmp_path / "app.db"
    write_import(clean, kpis=compute_kpis(clean), db_path=db)

    with session_scope(db) as session:
        products = session.scalars(select(Product)).all()

    assert len(products) == 1
    assert products[0].pack_size_milli == 1_500_000
    assert products[0].pack_unit == "g"


def test_orders_are_built_from_lines(tmp_path: Path):
    clean = _clean_sample()
    db = tmp_path / "app.db"
    write_import(clean, kpis=compute_kpis(clean), db_path=db)

    with session_scope(db) as session:
        orders = session.scalars(select(Order)).all()
        for order in orders:
            lines = session.scalars(
                select(OrderLine).where(OrderLine.order_id == order.id)
            ).all()
            gross = sum(line.revenue_rial for line in lines if not line.is_return)
            returns = -sum(line.revenue_rial for line in lines if line.is_return)
            assert order.gross_rial == gross
            assert order.returns_rial == returns
            assert order.net_rial == gross - returns
            assert order.line_count == len(lines)


def test_no_orders_table_rows_when_file_lacks_order_id(tmp_path: Path):
    """فاکتور جعلی به‌ازای هر خط ساخته نمی‌شود — نه اطلاعاتی می‌افزاید نه درست است."""
    raw = pd.DataFrame({
        "تاریخ": ["1402/01/01", "1402/01/02"],
        "مبلغ": [1000, 2000],
        "مشتری": ["C1", "C2"],
    })
    mapping = {ColumnRole.DATE: "تاریخ", ColumnRole.REVENUE: "مبلغ",
               ColumnRole.CUSTOMER_ID: "مشتری"}
    clean = clean_frame(SchemaMapper().apply(raw, mapping))
    db = tmp_path / "app.db"
    result = write_import(clean, kpis=compute_kpis(clean), db_path=db)

    assert result.orders_written == 0
    with session_scope(db) as session:
        assert session.scalar(select(func.count()).select_from(Order)) == 0
        assert session.scalar(select(func.count()).select_from(OrderLine)) == 2


def test_currency_conversion_happens_once_at_the_boundary(tmp_path: Path):
    """مبالغ ریالی دفتر باید دقیقاً ده برابر مبالغ تومانی تحلیل باشند."""
    clean = _clean_sample()
    db = tmp_path / "app.db"
    write_import(clean, display_currency="تومان", kpis=compute_kpis(clean), db_path=db)
    with session_scope(db) as session:
        first = session.scalars(
            select(OrderLine).where(~OrderLine.is_return).order_by(OrderLine.source_row)
        ).first()
    expected = round(float(clean.sort_values("source_row")["revenue"].iloc[0]) * 10)
    assert first.revenue_rial == expected


def test_reconciliation_rows_are_persisted(tmp_path: Path):
    clean = _clean_sample()
    db = tmp_path / "app.db"
    result = write_import(clean, kpis=compute_kpis(clean), db_path=db)

    with session_scope(db) as session:
        rows = session.scalars(
            select(ImportReconciliation).where(
                ImportReconciliation.batch_id == result.batch_id
            )
        ).all()
    ids = {r.check_id for r in rows}
    assert {f"L{i:02d}" for i in range(1, 14)} <= ids, "§۸.۶: هر شش مورد + کنترل‌های نوشتن"
    assert all(r.status in ("OK", "WARN", "MISMATCH", "SKIPPED") for r in rows)
    assert not [r for r in rows if r.status == "MISMATCH"]
    by_id = {r.check_id: r for r in rows}
    # نمونه ستون تخفیف ندارد ⇒ L11 «سنجیده نشد» و برچسبِ دسته دست‌نخورده می‌ماند
    assert by_id["L11"].status == "SKIPPED" and by_id["L11"].actual_text is None
    assert by_id["L10"].status == "OK" and by_id["L10"].expected_text == by_id["L10"].actual_text
    assert by_id["L12"].status == "OK"
    assert result.reconcile_status == "RECONCILED"


def test_batch_row_accounting_matches_frame_attrs(tmp_path: Path):
    clean = _clean_sample()
    db = tmp_path / "app.db"
    result = write_import(clean, kpis=compute_kpis(clean), db_path=db)

    with session_scope(db) as session:
        batch = session.get(ImportBatch, result.batch_id)
        assert batch.rows_clean == len(clean)
        assert batch.rows_returns == clean.attrs["n_returns"]
        assert batch.rows_invalid == clean.attrs["dropped_invalid_rows"]
        assert batch.rows_duplicate == clean.attrs["dropped_duplicate_rows"]
        assert batch.net_sales_rial == round(compute_kpis(clean).net_sales * 10)


def test_cost_stays_null_when_file_has_no_cost_column(tmp_path: Path):
    """بدون داده‌ی بها، ستون بها باید NULL بماند — صفر یعنی «رایگان»."""
    clean = _clean_sample()
    db = tmp_path / "app.db"
    write_import(clean, kpis=compute_kpis(clean), db_path=db)
    with session_scope(db) as session:
        non_null = session.scalar(
            select(func.count()).select_from(OrderLine).where(OrderLine.cost_rial.isnot(None))
        )
    assert non_null == 0


def test_large_frame_writes_in_chunks(tmp_path: Path):
    """بیش از یک تکه (۵۰۰۰) — مسیر تکه‌ای باید همان نتیجه بدهد."""
    raw = generate_synthetic_sales(seed=11, days=400)
    mapper = SchemaMapper()
    clean = clean_frame(mapper.apply(raw, mapper.auto_detect(raw).mapping))
    assert len(clean) > 5000
    db = tmp_path / "app.db"
    result = write_import(clean, kpis=compute_kpis(clean), db_path=db)

    with session_scope(db) as session:
        assert session.scalar(select(func.count()).select_from(OrderLine)) == result.lines_inserted
    assert result.reconcile_status.startswith("RECONCILED")


def test_engine_is_rebound_per_database(tmp_path: Path):
    """دو مسیر داده در یک پروسه نباید داده‌ی هم را ببینند."""
    clean = _clean_sample()
    for name in ("a", "b"):
        db = tmp_path / name / "app.db"
        db.parent.mkdir()
        write_import(clean, kpis=compute_kpis(clean), db_path=db)
        reset_ensure_cache()
    for name in ("a", "b"):
        engine = get_engine(tmp_path / name / "app.db")
        with engine.connect() as conn:
            count = conn.execute(select(func.count()).select_from(OrderLine.__table__)).scalar()
        assert count == 65
