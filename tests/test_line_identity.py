"""هویتِ پایدارِ خطِ فاکتور (§۸.۴ لایه‌های ۲–۴): صادراتِ هم‌پوشان دوبار شمرده نمی‌شود.

تا این دور `line_uid` از هشِ فایل + شماره‌ی ردیف ساخته می‌شد؛ دو صادراتِ «۶۰ روز
اخیر» از ERP در دو ماهِ پیاپی همان فاکتورها را دوبار به دفتر کل می‌بردند. حالا
کلیدِ خطِ فاکتوردار = فاکتور + کالا + نوع + ترتیب؛ مبلغ عمداً در کلید نیست تا
مبلغِ اصلاح‌شده همان خط را به‌روز کند. هیچ خطی حذف نمی‌شود (تصمیمِ کاربر).
"""

from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import func, select, text

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

from mktcore.db import session_scope  # noqa: E402
from mktcore.db.engine import get_engine  # noqa: E402
from mktcore.db.migrations import (  # noqa: E402
    _MIGRATION_TABLE,
    _MIGRATION_TABLE_DDL,
    _MIGRATIONS,
    CANONICAL_SCHEMA_VERSION,
    applied_versions,
    ensure_schema,
)
from mktcore.db.models import ImportReconciliation, Order, OrderLine  # noqa: E402
from mktcore.db.repo_import import frame_dataset_key, line_uid_for_order  # noqa: E402

from .test_golden_scenarios import _clean, _ingest  # noqa: E402
from .test_offer_ledger import _insert_minimal  # noqa: E402


def _rows(n: int = 40) -> list[tuple]:
    return [(f"1402/0{(i % 9) + 1}/05", 250_000, 2, f"C{i % 7}", f"F{i}", "کالا", "")
            for i in range(n)]


def _ledger_totals(db: Path) -> tuple[int, int]:
    with session_scope(db) as session:
        return (
            int(session.scalar(select(func.count()).select_from(OrderLine))),
            int(session.scalar(select(func.sum(OrderLine.revenue_rial))) or 0),
        )


def _orders_agree_with_lines(db: Path) -> None:
    with session_scope(db) as session:
        for order in session.scalars(select(Order)).all():
            lines = session.scalars(
                select(OrderLine).where(OrderLine.order_id == order.id)
            ).all()
            gross = sum(line.revenue_rial for line in lines if not line.is_return)
            returns = -sum(line.revenue_rial for line in lines if line.is_return)
            assert (order.gross_rial, order.returns_rial, order.net_rial, order.line_count) == (
                gross, returns, gross - returns, len(lines),
            ), order.order_key


def _check(db: Path, batch_id: int, check_id: str) -> ImportReconciliation:
    with session_scope(db) as session:
        row = session.scalar(
            select(ImportReconciliation).where(
                ImportReconciliation.batch_id == batch_id,
                ImportReconciliation.check_id == check_id,
            )
        )
        assert row is not None, check_id
        session.expunge(row)
        return row


# ═══════════════════════════════════ سناریوی طلایی: صادراتِ دوباره‌ی همان دوره
def test_reexport_of_same_period_with_one_corrected_row_does_not_double_count(tmp_path):
    db = tmp_path / "app.db"
    rows_a = _rows(40)
    clean_a = _clean(rows_a)
    first = _ingest(clean_a, db, dataset_key=frame_dataset_key(clean_a))
    assert first.lines_inserted == 40 and _ledger_totals(db) == (40, 40 * 250_000 * 10)

    # همان دوره از ERP دوباره صادر شد: یک مبلغ اصلاح شده، یک فاکتورِ تازه اضافه شده
    rows_b = list(rows_a)
    rows_b[5] = (rows_b[5][0], 300_000, *rows_b[5][2:])
    rows_b.append(("1402/09/20", 250_000, 2, "C1", "F40", "کالا", ""))
    clean_b = _clean(rows_b)
    assert frame_dataset_key(clean_b) != frame_dataset_key(clean_a)
    second = _ingest(clean_b, db, dataset_key=frame_dataset_key(clean_b))

    assert (second.lines_inserted, second.lines_updated) == (1, 40)
    assert _ledger_totals(db) == (41, (39 * 250_000 + 300_000 + 250_000) * 10)
    assert second.reconcile_status.startswith("RECONCILED")
    overlap = _check(db, second.batch_id, "L08")
    assert (overlap.status, overlap.actual_text) == ("OK", "40")
    assert "به‌روز شد" in (overlap.detail_fa or "")
    _orders_agree_with_lines(db)

    # و بارِ سوم همان فایلِ دوم: هیچ چیز دو برابر نمی‌شود
    third = _ingest(clean_b, db, dataset_key=frame_dataset_key(clean_b))
    assert (third.lines_inserted, third.lines_updated) == (0, 41)
    assert _ledger_totals(db) == (41, (39 * 250_000 + 300_000 + 250_000) * 10)


def test_two_lines_of_the_same_product_in_one_invoice_stay_distinct(tmp_path):
    db = tmp_path / "app.db"
    rows = [
        ("1402/01/05", 100_000, 1, "C1", "F1", "کالا", ""),
        ("1402/01/05", 400_000, 4, "C1", "F1", "کالا", ""),   # همان کالا، خطِ دوم
        ("1402/01/06", 150_000, 1, "C2", "F2", "کالا", ""),
    ]
    clean = _clean(rows)
    _ingest(clean, db, dataset_key="a")
    again = _ingest(clean, db, dataset_key="b")   # صادراتِ دوباره از فایلی دیگر

    assert (again.lines_inserted, again.lines_updated) == (0, 3)
    with session_scope(db) as session:
        amounts = sorted(session.scalars(select(OrderLine.revenue_rial)).all())
    assert amounts == [1_000_000, 1_500_000, 4_000_000]
    _orders_agree_with_lines(db)


def test_order_count_is_reconciled_like_the_kpi(tmp_path):
    db = tmp_path / "app.db"
    clean = _clean(_rows(12))
    result = _ingest(clean, db, dataset_key="k")
    l09 = _check(db, result.batch_id, "L09")
    assert (l09.status, l09.expected_text, l09.actual_text) == ("OK", "12", "12")


def test_lines_without_an_invoice_keep_the_per_file_identity(tmp_path):
    from mktcore.ingest.schema import ColumnRole

    db = tmp_path / "app.db"
    cols = ["تاریخ", "مبلغ", "مشتری", "کالا"]
    mapping = {ColumnRole.DATE: "تاریخ", ColumnRole.REVENUE: "مبلغ",
               ColumnRole.CUSTOMER_ID: "مشتری", ColumnRole.PRODUCT: "کالا"}
    rows = [(f"1402/01/{i + 1:02d}", 100_000 + i, f"C{i}", "کالا") for i in range(5)]
    clean = _clean(rows, cols, mapping)
    key = frame_dataset_key(clean)
    _ingest(clean, db, dataset_key=key)
    again = _ingest(clean, db, dataset_key=key)      # همان فایل ⇒ به‌روز
    other = _ingest(clean, db, dataset_key="other")  # فایلِ دیگر بدون فاکتور ⇒ قابل تشخیص نیست

    assert (again.lines_inserted, again.lines_updated) == (0, 5)
    assert (other.lines_inserted, other.lines_updated) == (5, 0)
    l09 = _check(db, other.batch_id, "L09")
    assert l09.status == "WARN" and "ستون فاکتور" in (l09.detail_fa or "")


# ═══════════════════════════════════ مهاجرت ۱۷ روی دفترِ v16 با تکراری‌های قدیمی
def _build_v16_with_duplicates(db: Path) -> None:
    engine = get_engine(db)
    with engine.begin() as conn:
        conn.execute(text(_MIGRATION_TABLE_DDL))
        for version, name, fn in _MIGRATIONS:
            if version > 16:
                break
            fn(conn)
            conn.execute(
                text(f"INSERT INTO {_MIGRATION_TABLE} (version, name, applied_at) "
                     "VALUES (:v, :n, :t)"),
                {"v": version, "n": name, "t": 0.0},
            )
        _insert_minimal(conn, "businesses", slug="default", name="آزمون",
                        display_currency="تومان", created_at=0.0)
        for key in ("A", "B"):
            _insert_minimal(conn, "import_batches", business_id=1, dataset_key=key,
                            revision=1, created_at=0.0)
        _insert_minimal(conn, "orders", business_id=1, order_key="F1", order_date="2024-01-05",
                        gross_rial=0, returns_rial=0, net_rial=0, line_count=0, batch_id=1,
                        created_at=0.0, updated_at=0.0)
        lines = [
            # (uid, batch, order, product, revenue, qty, source_row) — دو خطِ اول تکراریِ میان‌دسته‌ای‌اند
            ("old-1", 1, 1, "کالا", 1_000_000, 1000, 1),
            ("old-2", 2, 1, "کالا", 1_000_000, 1000, 1),
            ("old-3", 1, 1, "کالا", 2_500_000, 2000, 2),   # خطِ دومِ واقعیِ همان کالا
            ("old-4", 1, None, "کالا", 700_000, 1000, 3),   # بی‌فاکتور: دست نمی‌خورد
        ]
        for uid, batch, order, product, revenue, qty, src in lines:
            _insert_minimal(
                conn, "order_lines", line_uid=uid, business_id=1, batch_id=batch,
                order_id=order, raw_product_name=product, revenue_rial=revenue,
                quantity_milli=qty, source_row=src, line_date="2024-01-05", is_return=0,
                revision=1, created_at=0.0, updated_at=0.0,
            )


def test_migration_17_rekeys_lines_and_merges_cross_batch_duplicates(tmp_path):
    db = tmp_path / "v16.db"
    _build_v16_with_duplicates(db)

    assert ensure_schema(db, force=True) == CANONICAL_SCHEMA_VERSION == 17
    with session_scope(db) as session:
        lines = {line.line_uid: line for line in session.scalars(select(OrderLine)).all()}
        order = session.scalar(select(Order).where(Order.order_key == "F1"))
        assert order is not None
        assert len(lines) == 3, "تکراریِ میان‌دسته‌ای ادغام شد، خطِ واقعی و خطِ بی‌فاکتور ماندند"
        assert "old-4" in lines, "خطِ بی‌فاکتور با کلیدِ قدیمی می‌ماند"
        expected = {
            line_uid_for_order(1, "F1", "کالا", False, 0): (1_000_000, 2),  # جدیدترین دسته ماند
            line_uid_for_order(1, "F1", "کالا", False, 1): (2_500_000, 1),
        }
        for uid, (revenue, batch_id) in expected.items():
            assert uid in lines, "کلیدِ تازه با همان قاعده‌ی نوشتن ساخته می‌شود"
            assert (lines[uid].revenue_rial, lines[uid].batch_id) == (revenue, batch_id)
        assert (order.gross_rial, order.net_rial, order.line_count) == (3_500_000, 3_500_000, 2)
    assert applied_versions(get_engine(db)) == list(range(1, CANONICAL_SCHEMA_VERSION + 1))

    # اجرای دوباره چیزی عوض نمی‌کند
    ensure_schema(db, force=True)
    assert _ledger_totals(db) == (3, 4_200_000)
