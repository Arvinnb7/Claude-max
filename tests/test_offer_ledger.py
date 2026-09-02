"""مهاجرت ۱۵: دفترِ آفر روی دیتابیسِ **موجود**، بدون دست‌خوردنِ ردیف‌ها.

## چرا تستِ ارتقا و نه فقط «جدول هست»

CI هیچ بررسیِ مهاجرتی ندارد (فقط `ruff` و `pytest`). یعنی مهاجرتی که روی
دیتابیسِ نو کار می‌کند ولی روی دیتابیسِ v14ِ یک نصبِ واقعی می‌شکند، تا لحظه‌ی
ارتقای همان نصب پنهان می‌ماند. این تست دیتابیسی می‌سازد که دقیقاً تا مهاجرت ۱۴
جلو رفته و ردیف دارد، بعد ارتقا می‌دهد.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import text

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

from mktcore.db.engine import get_engine  # noqa: E402
from mktcore.db.migrations import (  # noqa: E402
    _MIGRATION_TABLE,
    _MIGRATION_TABLE_DDL,
    _MIGRATIONS,
    CANONICAL_SCHEMA_VERSION,
    applied_versions,
    ensure_schema,
    reset_ensure_cache,
)

NEW_COLUMNS = (
    ("customer_features", "full_price_share_bp"),
    ("campaign_members", "offer_discount_bp"),
    ("campaign_sends", "offer_discount_bp"),
    # مهاجرت ۱۶
    ("customer_features", "full_price_lines"),
)
OFFER_COLUMNS_16 = ("margin_basis", "margin_key")


@pytest.fixture(autouse=True)
def _isolate():
    reset_ensure_cache()
    yield
    reset_ensure_cache()


def _columns(conn, table: str) -> dict[str, dict]:
    rows = conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
    # (cid, name, type, notnull, dflt_value, pk)
    return {r[1]: {"type": r[2], "notnull": r[3], "default": r[4], "pk": r[5]} for r in rows}


def _filler(col_type: str):
    upper = (col_type or "").upper()
    if "INT" in upper:
        return 1
    if "REAL" in upper or "FLOAT" in upper or "NUMERIC" in upper:
        return 0.0
    if "BOOL" in upper:
        return 0
    return "x"


def _insert_minimal(conn, table: str, **explicit) -> None:
    """ردیفی که فقط ستون‌های NOT NULL را پر می‌کند — مقدارش مهم نیست، بقایش مهم است."""
    values = {}
    for name, meta in _columns(conn, table).items():
        if meta["pk"]:
            continue
        if name in explicit:
            values[name] = explicit[name]
        elif meta["notnull"] and meta["default"] is None:
            values[name] = _filler(meta["type"])
    cols = ", ".join(values)
    params = ", ".join(f":{k}" for k in values)
    conn.execute(text(f"INSERT INTO {table} ({cols}) VALUES ({params})"), values)


def _build_v14(db: Path) -> None:
    engine = get_engine(db)
    with engine.begin() as conn:
        conn.execute(text(_MIGRATION_TABLE_DDL))
        for version, name, fn in _MIGRATIONS:
            if version > 14:
                break
            fn(conn)
            conn.execute(
                text(f"INSERT INTO {_MIGRATION_TABLE} (version, name, applied_at) "
                     "VALUES (:v, :n, :t)"),
                {"v": version, "n": name, "t": 0.0},
            )
        # ⚠️ create_all در مهاجرت‌های قبلی، همه‌ی جدول‌های metadata (از جمله
        # opportunity_offers) را می‌سازد؛ برای شبیه‌سازیِ v14 واقعی باید
        # جدولِ تازه و ستون‌های تازه‌ای که هنوز وجود نداشتند برداشته شوند.
        conn.exec_driver_sql("DROP TABLE IF EXISTS opportunity_offers")
        for table, column in NEW_COLUMNS:
            if column in _columns(conn, table):
                conn.exec_driver_sql(f"ALTER TABLE {table} DROP COLUMN {column}")
        _insert_minimal(conn, "businesses", slug="default", name="آزمون",
                        display_currency="تومان", created_at=0.0)
        _insert_minimal(conn, "customers", business_id=1, canonical_key="C1",
                        resolution_method="raw_key", created_at=0.0, updated_at=0.0)
        _insert_minimal(conn, "customer_features", business_id=1, customer_id=1,
                        as_of_date="2026-01-01", feature_version=1, created_at=0.0)
        _insert_minimal(conn, "opportunities", business_id=1, customer_id=1,
                        dedupe_key="k1", status="open", created_at=0.0, updated_at=0.0)


def test_migration_15_upgrades_a_v14_db_without_touching_rows(tmp_path):
    db = tmp_path / "v14.db"
    _build_v14(db)
    with get_engine(db).begin() as conn:
        assert "full_price_share_bp" not in _columns(conn, "customer_features")
        assert not conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE name='opportunity_offers'"
        ).fetchall()

    reset_ensure_cache()
    assert ensure_schema(db) == CANONICAL_SCHEMA_VERSION
    assert CANONICAL_SCHEMA_VERSION >= 16
    assert {15, 16} <= set(applied_versions(get_engine(db)))

    with get_engine(db).begin() as conn:
        for table, column in NEW_COLUMNS:
            assert column in _columns(conn, table), f"{table}.{column} اضافه نشد"
        assert conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE name='opportunity_offers'"
        ).fetchall()
        for column in OFFER_COLUMNS_16:
            assert column in _columns(conn, "opportunity_offers"), column
        # ردیف‌های قبلی سرِ جایشان و ستونِ تازه NULL — نه صفر
        rows = conn.exec_driver_sql(
            "SELECT id, full_price_share_bp FROM customer_features"
        ).fetchall()
        assert rows == [(1, None)]
        assert conn.exec_driver_sql("SELECT COUNT(*) FROM opportunities").scalar() == 1


def test_migrations_15_and_16_are_idempotent(tmp_path):
    db = tmp_path / "app.db"
    ensure_schema(db)
    reset_ensure_cache()
    ensure_schema(db, force=True)
    versions = applied_versions(get_engine(db))
    assert versions.count(15) == 1 and versions.count(16) == 1


def test_offer_row_is_unique_per_opportunity(tmp_path):
    """دو پیشنهاد برای یک فرصت یعنی دو تصمیمِ متناقض؛ قیدِ یکتایی جلویش را می‌گیرد."""
    from sqlalchemy.exc import IntegrityError

    from mktcore.db.engine import session_scope
    from mktcore.db.models import Business, Customer, Opportunity, OpportunityOffer

    db = tmp_path / "app.db"
    ensure_schema(db)
    with session_scope(db) as session:
        business = Business(slug="default", name="آزمون")
        session.add(business)
        session.flush()
        customer = Customer(business_id=business.id, canonical_key="C1")
        session.add(customer)
        session.flush()
        opportunity = Opportunity(
            business_id=business.id, customer_id=customer.id, dedupe_key="k",
            kind="یادآوری چرخه‌ی مصرف", generator="t", generator_version=1,
            title_fa="t", action_fa="a", reason_fa="r", value_kind="ارزش فرصت",
        )
        session.add(opportunity)
        session.flush()
        session.add(OpportunityOffer(
            business_id=business.id, opportunity_id=opportunity.id, suggested_discount_bp=500,
        ))
        session.flush()
        session.add(OpportunityOffer(
            business_id=business.id, opportunity_id=opportunity.id, suggested_discount_bp=1000,
        ))
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()
