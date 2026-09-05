"""طرح‌واره‌ی canonical روی همان دیتابیس — بدون لمس‌کردن لایه‌ی legacy.

مهم‌ترین ادعای این فایل: افزودن این لایه هیچ اثری روی جداول و نسخه‌ی طرح‌واره‌ی
موجود ندارد. اگر این تست‌ها بشکنند، ارتقا داده‌ی واقعی کاربر را به خطر انداخته.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import inspect, text

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

from api.persistence import PersistentStore  # noqa: E402

from mktcore.db import Base, applied_versions, ensure_schema, get_engine  # noqa: E402
from mktcore.db.migrations import CANONICAL_SCHEMA_VERSION, reset_ensure_cache  # noqa: E402

_LEGACY_TABLES = {"sessions", "jobs", "outbox", "mapping_profiles"}
_CANONICAL_TABLES = {
    "businesses", "import_batches", "import_reconciliation",
    "customers", "customer_keys", "products", "product_aliases",
    "orders", "order_lines", "customer_features",
    "opportunities", "opportunity_factors", "opportunity_events", "opportunity_runs",
    "customer_lifecycle_events", "mapping_profile_versions",
    "campaigns", "campaign_members", "campaign_opportunities", "campaign_outcomes",
}


@pytest.fixture
def fresh_db(tmp_path: Path) -> Path:
    """دیتابیس ایزوله برای هر تست + پاک‌کردن کشِ «طرح‌واره ساخته شده»."""
    reset_ensure_cache()
    db = tmp_path / "app.db"
    yield db
    reset_ensure_cache()


def test_ensure_schema_creates_canonical_tables(fresh_db: Path):
    assert ensure_schema(fresh_db) == CANONICAL_SCHEMA_VERSION
    names = set(inspect(get_engine(fresh_db)).get_table_names())
    assert _CANONICAL_TABLES <= names
    assert "schema_migrations" in names


def test_ensure_schema_is_idempotent(fresh_db: Path):
    ensure_schema(fresh_db)
    before = set(inspect(get_engine(fresh_db)).get_table_names())
    reset_ensure_cache()
    ensure_schema(fresh_db)  # بار دوم نباید چیزی عوض کند یا خطا بدهد
    assert set(inspect(get_engine(fresh_db)).get_table_names()) == before
    assert applied_versions(get_engine(fresh_db)) == list(
        range(1, CANONICAL_SCHEMA_VERSION + 1)
    )


def test_metadata_never_knows_legacy_tables():
    """قید سختِ ارتقا: `create_all`/`drop_all` نباید بتواند جداول قدیمی را ببیند."""
    assert _LEGACY_TABLES.isdisjoint(set(Base.metadata.tables))


def test_legacy_store_and_canonical_coexist(tmp_path: Path):
    """هر دو لایه روی یک فایل: جداول هر دو هست و `user_version` همان ۲ می‌ماند."""
    reset_ensure_cache()
    store = PersistentStore(tmp_path)
    sid = store.create_session(filename="نمونه.xlsx")

    ensure_schema(store.db_path)

    names = set(inspect(get_engine(store.db_path)).get_table_names())
    assert _LEGACY_TABLES <= names
    assert _CANONICAL_TABLES <= names

    # نسخه‌ی legacy دست‌نخورده (پین تست‌های موجود)
    with get_engine(store.db_path).connect() as conn:
        assert conn.execute(text("PRAGMA user_version")).scalar() == 2

    # و رکورد قبلی سالم مانده است
    assert store.get_session(sid) is not None
    reset_ensure_cache()


def test_canonical_migration_does_not_bump_user_version(tmp_path: Path):
    """نسخه‌گذاری دو لایه مستقل است؛ هیچ‌کدام دیگری را جلو نمی‌برد."""
    reset_ensure_cache()
    store = PersistentStore(tmp_path)
    with get_engine(store.db_path).connect() as conn:
        before = conn.execute(text("PRAGMA user_version")).scalar()
    ensure_schema(store.db_path)
    with get_engine(store.db_path).connect() as conn:
        assert conn.execute(text("PRAGMA user_version")).scalar() == before
    assert applied_versions(get_engine(store.db_path)) == list(
        range(1, CANONICAL_SCHEMA_VERSION + 1)
    )
    reset_ensure_cache()


def test_no_two_indexes_share_a_name():
    """دو ایندکس هم‌نام، مهاجرت را روی نصب‌های موجود می‌شکند.

    این حالت وقتی پیش می‌آید که ستونی `index=True` داشته باشد و ایندکس مرکبی
    هم دستی با همان نام تعریف شود — خطایش فقط موقع اجرای واقعی مهاجرت دیده
    می‌شود، نه موقع تعریف مدل.
    """
    from mktcore.db import models  # noqa: F401

    seen: dict[str, str] = {}
    duplicates = []
    for table in Base.metadata.tables.values():
        for index in table.indexes:
            if index.name in seen:
                duplicates.append(f"{index.name} ({seen[index.name]} و {table.name})")
            seen[index.name] = table.name
    assert duplicates == []


def test_money_columns_are_integers_not_floats():
    """قاعده‌ی §۳.۴: هیچ ستون پولی float نیست."""
    from mktcore.db import models  # noqa: F401 - ثبت مدل‌ها

    offenders = []
    for table in Base.metadata.tables.values():
        for column in table.columns:
            if column.name.endswith(("_rial", "_milli", "_bp")):
                type_name = type(column.type).__name__
                if "Float" in type_name or "Numeric" in type_name:
                    offenders.append(f"{table.name}.{column.name} ({type_name})")
    assert offenders == []


def test_every_canonical_table_carries_business_id():
    """چندمستأجری ارزان است اگر از روز اول باشد؛ افزودن بعدی مهاجرت داده می‌خواهد."""
    from mktcore.db import models  # noqa: F401

    # جداول فرزند از راه والدشان به business وصل‌اند
    exempt = {
        "businesses",
        "import_reconciliation",     # از راه import_batches
        "opportunity_factors",       # از راه opportunities
        "opportunity_events",        # از راه opportunities
        "campaign_members",          # از راه campaigns
        "campaign_opportunities",    # از راه campaigns
        "campaign_outcomes",         # از راه campaigns
        # اجاره‌ی اجرا داده‌ی کسب‌وکار نیست؛ ردیفِ هماهنگیِ زمانِ اجراست و
        # دامنه‌اش در `scope_key` است — که برای jobهای غیرکسب‌وکاری هم کار کند.
        "job_leases",
        # دفترِ اجرای کارها هم داده‌ی کسب‌وکار نیست؛ کارهای سراسری (مثل
        # جاروکشِ تلاش‌ها) اصلاً کسب‌وکاری ندارند که به آن نسبت داده شوند.
        "job_runs",
    }
    missing = [
        name for name, table in Base.metadata.tables.items()
        if name not in exempt and "business_id" not in table.columns
    ]
    assert missing == []


def test_cost_columns_exist_but_are_nullable():
    """زیرساخت بهای تمام‌شده ساخته می‌شود، ولی بدون داده NULL می‌ماند — نه صفر."""
    from mktcore.db.models import OrderLine, Product

    assert OrderLine.__table__.c.cost_rial.nullable
    assert Product.__table__.c.last_unit_cost_rial.nullable


def test_line_uid_is_unique():
    """کلید idempotency: تحلیل دوباره‌ی یک فایل نباید خط تکراری بسازد."""
    from mktcore.db.models import OrderLine

    unique_cols = {
        tuple(c.name for c in constraint.columns)
        for constraint in OrderLine.__table__.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert ("line_uid",) in unique_cols
