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

    assert ensure_schema(db, force=True) == CANONICAL_SCHEMA_VERSION == 19
    with session_scope(db) as session:
        lines = {line.line_uid: line for line in session.scalars(select(OrderLine)).all()}
        order = session.scalar(select(Order).where(Order.order_number == "F1"))
        assert order is not None
        assert (order.order_key, order.order_period) == ("2024/F1", "2024"), "مهاجرت ۱۸ سر را دوره‌دار کرد"
        assert len(lines) == 3, "تکراریِ میان‌دسته‌ای ادغام شد، خطِ واقعی و خطِ بی‌فاکتور ماندند"
        assert "old-4" in lines, "خطِ بی‌فاکتور با کلیدِ قدیمی می‌ماند"
        expected = {
            line_uid_for_order(1, "F1", "کالا", False, 0, period="2024"): (1_000_000, 2),  # جدیدترین دسته ماند
            line_uid_for_order(1, "F1", "کالا", False, 1, period="2024"): (2_500_000, 1),
        }
        for uid, (revenue, batch_id) in expected.items():
            assert uid in lines, "کلیدِ تازه با همان قاعده‌ی نوشتن ساخته می‌شود"
            assert (lines[uid].revenue_rial, lines[uid].batch_id) == (revenue, batch_id)
        assert (order.gross_rial, order.net_rial, order.line_count) == (3_500_000, 3_500_000, 2)
    assert applied_versions(get_engine(db)) == list(range(1, CANONICAL_SCHEMA_VERSION + 1))

    # اجرای دوباره چیزی عوض نمی‌کند
    ensure_schema(db, force=True)
    assert _ledger_totals(db) == (3, 4_200_000)


# ═══════════════════════════════ یافته‌های بازبینی: ترتیب، دوره، نرمال‌سازی
def test_migration_17_merge_is_order_independent_with_repeated_lines(tmp_path):
    """دو خطِ واقعیِ هم‌مبلغ در یک فاکتور، از دو صادرات: باید دقیقاً دو خط بماند —
    مستقل از اینکه کدام صادرات شماره‌ی ردیفِ کوچک‌تری دارد."""
    db = tmp_path / "v16.db"
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
        # صادراتِ قدیمی (دسته ۱) ردیف‌های ۱۰ و ۱۱؛ صادراتِ تازه (دسته ۲) همان دو خط در ۵۱۰ و ۵۱۱
        for uid, batch, src in (("o-1", 1, 10), ("o-2", 1, 11), ("n-1", 2, 510), ("n-2", 2, 511)):
            _insert_minimal(
                conn, "order_lines", line_uid=uid, business_id=1, batch_id=batch, order_id=1,
                raw_product_name="کالا", revenue_rial=1_000_000, quantity_milli=1000,
                source_row=src, line_date="2024-01-05", is_return=0, revision=1,
                created_at=0.0, updated_at=0.0,
            )

    ensure_schema(db, force=True)
    with session_scope(db) as session:
        lines = session.scalars(select(OrderLine)).all()
        order = session.scalar(select(Order).where(Order.order_number == "F1"))
        assert sorted(line.batch_id for line in lines) == [2, 2], "دسته‌ی جدیدتر با هر دو تکرارش می‌ماند"
        assert {line.line_uid for line in lines} == {
            line_uid_for_order(1, "F1", "کالا", False, 0, period="2024"),
            line_uid_for_order(1, "F1", "کالا", False, 1, period="2024"),
        }
        assert (order.gross_rial, order.line_count) == (2_000_000, 2)


def test_reused_invoice_number_in_another_year_is_a_different_line(tmp_path):
    db = tmp_path / "app.db"
    year1 = _clean([("1402/01/05", 100_000, 1, "C1", "F1", "کالا", "")])
    year2 = _clean([("1403/01/05", 250_000, 1, "C1", "F1", "کالا", "")])
    _ingest(year1, db, dataset_key="y1")
    second = _ingest(year2, db, dataset_key="y2")

    assert (second.lines_inserted, second.lines_updated) == (1, 0)
    assert _ledger_totals(db) == (2, (100_000 + 250_000) * 10)
    # سرِ فاکتور هم دوره‌دار است: دو سر، هر کدام در سالِ خودش و برابرِ Σ خطوطِ خودش
    with session_scope(db) as session:
        orders = session.scalars(select(Order).order_by(Order.order_key)).all()
        assert [(o.order_key, o.order_period, o.order_number) for o in orders] == [
            ("2023/F1", "2023", "F1"), ("2024/F1", "2024", "F1"),
        ]
        assert [o.order_date[:4] for o in orders] == ["2023", "2024"]
        assert [o.net_rial for o in orders] == [1_000_000, 2_500_000]
    _orders_agree_with_lines(db)


def test_order_key_is_normalised_before_identity(tmp_path):
    """«۱۲۳۴»، «1234» و «1234.0» یک فاکتورند."""
    from mktcore.db.repo_import import normalize_order_key

    assert normalize_order_key("۱۲۳۴") == normalize_order_key(" 1234 ") == normalize_order_key("1234.0") == "1234"
    assert normalize_order_key(None) is None

    db = tmp_path / "app.db"
    a = _clean([("1402/01/05", 100_000, 1, "C1", "۱۲۳۴", "کالا", "")])
    b = _clean([("1402/01/05", 120_000, 1, "C1", "1234.0", "کالا", "")])
    _ingest(a, db, dataset_key="a")
    second = _ingest(b, db, dataset_key="b")

    assert (second.lines_inserted, second.lines_updated) == (0, 1)
    with session_scope(db) as session:
        assert session.scalar(select(func.count()).select_from(Order)) == 1
        assert session.scalar(select(Order.order_number)) == "1234"
        assert session.scalar(select(Order.order_key)) == "2023/1234"


# ═══════════════════════════════════ مهاجرت ۱۸ روی دفترِ v17 با سرِ ادغام‌شده
def _build_v17_with_merged_header(db: Path) -> None:
    """دفترِ v17: شماره‌ی «F1» در دو سال زیرِ **یک** سر (شکلِ خرابی که مهاجرت ۱۸ درست می‌کند)،
    به‌علاوه‌ی یک سرِ تک‌دوره که فقط باید کلیدِ دوره‌دار بگیرد."""
    engine = get_engine(db)
    with engine.begin() as conn:
        conn.execute(text(_MIGRATION_TABLE_DDL))
        for version, name, fn in _MIGRATIONS:
            if version > 17:
                break
            fn(conn)
            conn.execute(
                text(f"INSERT INTO {_MIGRATION_TABLE} (version, name, applied_at) "
                     "VALUES (:v, :n, :t)"),
                {"v": version, "n": name, "t": 0.0},
            )
        _insert_minimal(conn, "businesses", slug="default", name="آزمون",
                        display_currency="تومان", created_at=0.0)
        _insert_minimal(conn, "import_batches", business_id=1, dataset_key="A",
                        revision=1, created_at=0.0)
        # سرِ ادغام‌شده: تاریخش سالِ قبل است و جمعش هر دو سال را دارد
        _insert_minimal(conn, "orders", business_id=1, order_key="F1", order_date="2023-03-01",
                        gross_rial=3_500_000, returns_rial=300_000, net_rial=3_200_000, line_count=3,
                        batch_id=1, created_at=0.0, updated_at=0.0)
        _insert_minimal(conn, "orders", business_id=1, order_key="F2", order_date="2024-02-01",
                        gross_rial=400_000, returns_rial=0, net_rial=400_000, line_count=1,
                        batch_id=1, created_at=0.0, updated_at=0.0)
        lines = [
            # (number, product, revenue, is_return, ordinal, period, date, source_row)
            ("F1", "کالا", 1_000_000, 0, 0, "2023", "2023-03-01", 1),
            ("F1", "کالا", 2_500_000, 0, 0, "2024", "2024-03-01", 2),
            ("F1", "کالا", -300_000, 1, 0, "2024", "2024-03-02", 3),   # برگشت: مبلغِ منفی
            ("F2", "کالا", 400_000, 0, 0, "2024", "2024-02-01", 4),
        ]
        for number, product, revenue, is_return, ordinal, period, date, src in lines:
            _insert_minimal(
                conn, "order_lines",
                line_uid=line_uid_for_order(1, number, product, bool(is_return), ordinal, period=period),
                business_id=1, batch_id=1, order_id=1 if number == "F1" else 2,
                raw_product_name=product, revenue_rial=revenue, quantity_milli=1000,
                source_row=src, line_date=date, is_return=is_return, revision=1,
                created_at=0.0, updated_at=0.0,
            )


def test_migration_18_splits_merged_multi_year_headers(tmp_path):
    db = tmp_path / "v17.db"
    _build_v17_with_merged_header(db)

    assert ensure_schema(db, force=True) == CANONICAL_SCHEMA_VERSION == 19
    with session_scope(db) as session:
        orders = {o.order_key: o for o in session.scalars(select(Order)).all()}
        assert set(orders) == {"2023/F1", "2024/F1", "2024/F2"}, "سرِ ادغام‌شده به دو سرِ دوره‌دار تفکیک شد"
        assert {o.order_number for o in orders.values()} == {"F1", "F2"}
        assert {k: o.order_period for k, o in orders.items()} == {
            "2023/F1": "2023", "2024/F1": "2024", "2024/F2": "2024",
        }
        # سرِ موجود دوره‌ی قدیمی‌تر را نگه داشت؛ سرِ تازه دوره‌ی بعد را گرفت
        assert orders["2023/F1"].id == 1
        assert (orders["2023/F1"].gross_rial, orders["2023/F1"].returns_rial,
                orders["2023/F1"].net_rial, orders["2023/F1"].line_count,
                orders["2023/F1"].order_date) == (1_000_000, 0, 1_000_000, 1, "2023-03-01")
        assert (orders["2024/F1"].gross_rial, orders["2024/F1"].returns_rial,
                orders["2024/F1"].net_rial, orders["2024/F1"].line_count,
                orders["2024/F1"].order_date) == (2_500_000, 300_000, 2_200_000, 2, "2024-03-01")
        assert (orders["2024/F2"].net_rial, orders["2024/F2"].line_count) == (400_000, 1)
        # خطوط به سرِ سالِ خودشان وصل شدند
        by_order = {}
        for line in session.scalars(select(OrderLine)).all():
            by_order.setdefault(line.order_id, []).append(line.line_date[:4])
        assert by_order[orders["2023/F1"].id] == ["2023"]
        assert sorted(by_order[orders["2024/F1"].id]) == ["2024", "2024"]
    _orders_agree_with_lines(db)
    assert _ledger_totals(db) == (4, 3_600_000), "هیچ خطی حذف یا دوباره شمرده نشد"
    assert applied_versions(get_engine(db)) == list(range(1, CANONICAL_SCHEMA_VERSION + 1))

    # اجرای دوباره چیزی عوض نمی‌کند
    ensure_schema(db, force=True)
    with session_scope(db) as session:
        assert session.scalar(select(func.count()).select_from(Order)) == 3
    _orders_agree_with_lines(db)


def test_migration_18_is_a_no_op_on_a_fresh_period_scoped_ledger(tmp_path):
    """دفتری که با کدِ تازه نوشته شده، از مهاجرت ۱۸ بی‌تغییر می‌گذرد (ناورداییِ نمونه)."""
    db = tmp_path / "app.db"
    _ingest(_clean(_rows(30)), db, dataset_key="a")
    before = _ledger_totals(db)
    with session_scope(db) as session:
        snapshot = sorted(
            (o.order_key, o.order_period, o.order_number, o.net_rial, o.line_count, o.order_date)
            for o in session.scalars(select(Order)).all()
        )
    assert snapshot and all(k == f"{p}/{n}" for k, p, n, *_ in snapshot)
    ensure_schema(db, force=True)
    with session_scope(db) as session:
        after = sorted(
            (o.order_key, o.order_period, o.order_number, o.net_rial, o.line_count, o.order_date)
            for o in session.scalars(select(Order)).all()
        )
    assert after == snapshot
    assert _ledger_totals(db) == before
