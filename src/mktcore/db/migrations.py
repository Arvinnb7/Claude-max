"""مهاجرت لایه‌ی canonical — نسخه‌گذاری مستقل، بدون Alembic.

چرا Alembic نه؟ Alembic نصب نیست، و برای یک فایل SQLite تک‌کاربره سربارِ
پوشه‌ی versions + env.py + پیکربندی می‌آورد بدون منفعتی که مکانیزم فعلی ندهد.
اینجا هر مهاجرت یک تابع شماره‌دار است که در جدول `schema_migrations` ثبت می‌شود.

**استقلال از لایه‌ی legacy** (قاعده‌ی سختِ این ارتقا):
`PRAGMA user_version` در ۲ می‌ماند و مالکش `api/persistence.py` است؛ این لایه
هرگز آن را نمی‌خواند و نمی‌نویسد. پس دو مکانیزم مهاجرت مستقل و اثبات‌پذیر داریم و
هیچ‌کدام دیگری را عقب/جلو نمی‌برد.

**تنبل بودن** ضروری است: تست‌ها `TestClient(app)` را بیرون از `with` می‌سازند و
lifespan اجرا نمی‌شود؛ پس طرح‌واره باید در اولین استفاده‌ی واقعی ساخته شود، نه
فقط در بالا آمدن برنامه.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import text

from .base import Base, now_ts
from .engine import get_engine, write_lock

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.engine import Connection, Engine

logger = logging.getLogger("mktcore.db.migrations")

# نسخه‌ی جاری طرح‌واره‌ی canonical. با افزودن هر مهاجرت، یک عدد بالا می‌رود.
CANONICAL_SCHEMA_VERSION = 15

_MIGRATION_TABLE = "schema_migrations"

_MIGRATION_TABLE_DDL = f"""
CREATE TABLE IF NOT EXISTS {_MIGRATION_TABLE} (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at REAL NOT NULL
)
"""

# طرح‌واره‌ی canonical در همین پروسه فقط یک بار بررسی می‌شود؛ بررسی مجدد برای هر
# فراخوانی یعنی یک round-trip اضافه روی هر نوشتن.
_ensured_lock = threading.Lock()
_ensured_for: set[str] = set()


def applied_versions(engine: Engine | None = None) -> list[int]:
    """نسخه‌های مهاجرتِ اعمال‌شده (صعودی). جدول نبود → فهرست خالی."""
    eng = engine or get_engine()
    with eng.connect() as conn:
        if not _table_exists(conn, _MIGRATION_TABLE):
            return []
        rows = conn.execute(
            text(f"SELECT version FROM {_MIGRATION_TABLE} ORDER BY version")
        ).fetchall()
    return [int(r[0]) for r in rows]


def _table_exists(conn: Connection, name: str) -> bool:
    row = conn.execute(
        text("SELECT 1 FROM sqlite_master WHERE type='table' AND name = :n"),
        {"n": name},
    ).fetchone()
    return row is not None


# --------------------------------------------------------------- مهاجرت‌ها
def _migration_0001_create_canonical_tables(conn: Connection) -> None:
    """ساخت جداول canonical.

    `create_all` روی همان اتصال اجرا می‌شود تا با ثبت نسخه در یک تراکنش باشد.
    `checkfirst=True` است، پس اجرای دوباره بی‌خطر است. `Base.metadata` تنها
    جداول این لایه را می‌شناسد → جداول legacy در امان‌اند.
    """
    from mktcore.db import models  # noqa: F401 - ثبت مدل‌ها در metadata

    Base.metadata.create_all(bind=conn, checkfirst=True)


def _migration_0002_create_opportunity_tables(conn: Connection) -> None:
    """جداول فرصت.

    همان `create_all` با `checkfirst` است: جداول گام قبل دوباره ساخته نمی‌شوند
    و فقط جداول تازه اضافه می‌شوند. مهاجرت جدا نگه داشته شده تا نصب‌هایی که
    نسخه‌ی ۱ را دارند، رد پای روشنی از افزودن این بخش داشته باشند.
    """
    from mktcore.db import models  # noqa: F401 - ثبت مدل‌ها در metadata

    Base.metadata.create_all(bind=conn, checkfirst=True)


def _migration_0003_create_lifecycle_events(conn: Connection) -> None:
    """جدول گذارهای چرخه‌ی عمر (§۱۱ — «گذارها و دلیلشان باید ماندگار شوند»)."""
    from mktcore.db import models  # noqa: F401 - ثبت مدل‌ها در metadata

    Base.metadata.create_all(bind=conn, checkfirst=True)


def _migration_0004_create_campaign_tables(conn: Connection) -> None:
    """جداول کمپین و آزمایش (فاز ۳ — حلقه‌ی بسته‌ی سنجش اثر)."""
    from mktcore.db import models  # noqa: F401 - ثبت مدل‌ها در metadata

    Base.metadata.create_all(bind=conn, checkfirst=True)


def _migration_0005_create_uplift_snapshots(conn: Connection) -> None:
    """جدول عکسِ اثر آموخته‌شده (فاز ۴ — رتبه‌بندی مبتنی بر اثر)."""
    from mktcore.db import models  # noqa: F401 - ثبت مدل‌ها در metadata

    Base.metadata.create_all(bind=conn, checkfirst=True)


def _migration_0006_create_contact_suppressions(conn: Connection) -> None:
    """دفترِ انصراف از تماس (فاز ۵ — دروازه‌ی مجوز تماس).

    عمداً جدولِ تازه است و نه ستونی روی `customers`: مهاجرت هم‌شکلِ پنج مهاجرتِ
    قبلی می‌ماند (`create_all` با `checkfirst`) و به `ALTER TABLE` نیازی نیست.
    """
    from mktcore.db import models  # noqa: F401 - ثبت مدل‌ها در metadata

    Base.metadata.create_all(bind=conn, checkfirst=True)


def _migration_0007_create_campaign_sends(conn: Connection) -> None:
    """دفترِ ارسال کمپین (فاز ۵ — ارسال مستقیم و اقتصاد تماس)."""
    from mktcore.db import models  # noqa: F401 - ثبت مدل‌ها در metadata

    Base.metadata.create_all(bind=conn, checkfirst=True)


def _migration_0008_create_product_cost_history(conn: Connection) -> None:
    """تاریخچه‌ی بهای کالا + ستون سود روی خط (سود ناخالص).

    ستونِ تازه روی جدولِ موجود است، پس برخلاف مهاجرت‌های قبلی `create_all` تنها
    کافی نیست و یک `ALTER TABLE` هم لازم است. با `checkfirst` روی ستون انجام
    می‌شود تا اجرای دوباره بی‌خطر بماند.
    """
    from mktcore.db import models  # noqa: F401 - ثبت مدل‌ها در metadata

    Base.metadata.create_all(bind=conn, checkfirst=True)

    # `create_all` ستونِ تازه روی جدولِ **موجود** اضافه نمی‌کند، پس ستون‌های تازه
    # صریحاً افزوده می‌شوند. روی نصبِ تازه این حلقه چیزی پیدا نمی‌کند و رد می‌شود.
    added_columns = (
        ("order_lines", "gross_profit_rial", "BIGINT"),
        ("campaign_outcomes", "cost_rial", "BIGINT"),
        ("campaign_outcomes", "lines_with_cost", "INTEGER DEFAULT 0"),
    )
    for table, column, ddl_type in added_columns:
        existing = {
            row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")
        }
        if column not in existing:
            conn.exec_driver_sql(
                f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}"
            )


def _migration_0009_create_app_settings(conn: Connection) -> None:
    """جدولِ تنظیمِ سیاست (کف حاشیه) — جدولِ تازه، پس `create_all` کافی است."""
    from mktcore.db import models  # noqa: F401 - ثبت مدل‌ها در metadata

    Base.metadata.create_all(bind=conn, checkfirst=True)


def _migration_0010_create_model_runs(conn: Connection) -> None:
    """رجیستری مدل + ستون‌های امتیاز روی عکس ویژگی (فاز ۴).

    جدولِ تازه با `create_all` می‌آید، ولی ستون‌های امتیاز روی جدولِ **موجود**
    می‌نشینند، پس مثل مهاجرت ۸ یک حلقه‌ی `ALTER TABLE` هم لازم است.
    """
    from mktcore.db import models  # noqa: F401 - ثبت مدل‌ها در metadata

    Base.metadata.create_all(bind=conn, checkfirst=True)

    added_columns = (
        ("customer_features", "whale_probability_bp", "INTEGER"),
        ("customer_features", "whale_model_run_id", "INTEGER"),
        ("customer_features", "churn_probability_bp", "INTEGER"),
        ("customer_features", "churn_model_run_id", "INTEGER"),
        ("customer_features", "replenish_probability_bp", "INTEGER"),
        ("customer_features", "replenish_model_run_id", "INTEGER"),
        ("customer_features", "scored_at", "REAL"),
    )
    for table, column, ddl_type in added_columns:
        existing = {
            row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")
        }
        if column not in existing:
            conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}")


def _migration_0011_create_gross_profit_clv(conn: Connection) -> None:
    """ستون‌های CLV سودمحور روی عکس ویژگی (§۱۹).

    فقط `ALTER TABLE`: جدولِ تازه‌ای در کار نیست و `create_all` هم چیزی اضافه
    نمی‌کند، چون جدول از قبل وجود دارد.
    """
    added_columns = (
        ("customer_features", "clv_gp_90d_rial", "BIGINT"),
        ("customer_features", "clv_gp_180d_rial", "BIGINT"),
        ("customer_features", "clv_gp_365d_rial", "BIGINT"),
        ("customer_features", "clv_gp_365d_low_rial", "BIGINT"),
        ("customer_features", "clv_gp_365d_high_rial", "BIGINT"),
        ("customer_features", "clv_gp_basis", "VARCHAR(16)"),
        ("customer_features", "clv_model_version", "INTEGER"),
    )
    for table, column, ddl_type in added_columns:
        existing = {
            row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")
        }
        if column not in existing:
            conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}")


def _migration_0012_create_audit_events(conn: Connection) -> None:
    """جدولِ ممیزی (§۳۱) و اجاره‌ی اجرا (§۲۸) — هر دو تازه‌اند."""
    from mktcore.db import models  # noqa: F401 - ثبت مدل‌ها در metadata

    Base.metadata.create_all(bind=conn, checkfirst=True)


def _migration_0013_create_job_runs(conn: Connection) -> None:
    """دفترِ اجرای کارهای زمان‌بندی‌شده (§۲۸) — جدولِ تازه."""
    from mktcore.db import models  # noqa: F401 - ثبت مدل‌ها در metadata

    Base.metadata.create_all(bind=conn, checkfirst=True)


def _migration_0014_create_import_quarantine(conn: Connection) -> None:
    """ردیف خام و قرنطینه (§۷.۱) — جدول‌های تازه."""
    from mktcore.db import models  # noqa: F401 - ثبت مدل‌ها در metadata

    Base.metadata.create_all(bind=conn, checkfirst=True)


def _migration_0015_create_offer_ledger(conn: Connection) -> None:
    """دفترِ آفر (§۲۰.۳) + ستون‌های لاگِ آفر (§۲۰.۲).

    جدولِ تازه با `create_all` می‌آید؛ سه ستون روی جدول‌های **موجود** با همان
    حلقه‌ی `ALTER TABLE` مهاجرت ۸ و ۱۰ اضافه می‌شوند.
    """
    from mktcore.db import models  # noqa: F401 - ثبت مدل‌ها در metadata

    Base.metadata.create_all(bind=conn, checkfirst=True)

    added_columns = (
        ("customer_features", "full_price_share_bp", "INTEGER"),
        ("campaign_members", "offer_discount_bp", "INTEGER"),
        ("campaign_sends", "offer_discount_bp", "INTEGER"),
    )
    for table, column, ddl_type in added_columns:
        existing = {
            row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")
        }
        if column not in existing:
            conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}")


_MIGRATIONS: tuple[tuple[int, str, Callable[[Connection], None]], ...] = (
    (1, "create_canonical_tables", _migration_0001_create_canonical_tables),
    (2, "create_opportunity_tables", _migration_0002_create_opportunity_tables),
    (3, "create_lifecycle_events", _migration_0003_create_lifecycle_events),
    (4, "create_campaign_tables", _migration_0004_create_campaign_tables),
    (5, "create_uplift_snapshots", _migration_0005_create_uplift_snapshots),
    (6, "create_contact_suppressions", _migration_0006_create_contact_suppressions),
    (7, "create_campaign_sends", _migration_0007_create_campaign_sends),
    (8, "create_product_cost_history", _migration_0008_create_product_cost_history),
    (9, "create_app_settings", _migration_0009_create_app_settings),
    (10, "create_model_runs", _migration_0010_create_model_runs),
    (11, "create_gross_profit_clv", _migration_0011_create_gross_profit_clv),
    (12, "create_audit_events_and_leases", _migration_0012_create_audit_events),
    (13, "create_job_runs", _migration_0013_create_job_runs),
    (14, "create_import_quarantine", _migration_0014_create_import_quarantine),
    (15, "create_offer_ledger", _migration_0015_create_offer_ledger),
)


def ensure_schema(db_path: Path | None = None, *, force: bool = False) -> int:
    """اعمال مهاجرت‌های نااعمال‌شده و برگرداندن نسخه‌ی نهایی.

    idempotent است و می‌شود در هر مسیری صدا زد. تحت `write_lock` اجرا می‌شود تا
    دو thread هم‌زمان `create_all` نزنند.
    """
    engine = get_engine(db_path)
    key = str(engine.url)
    if not force:
        with _ensured_lock:
            if key in _ensured_for:
                return CANONICAL_SCHEMA_VERSION

    with write_lock, engine.begin() as conn:
        conn.execute(text(_MIGRATION_TABLE_DDL))
        done = {
            int(r[0])
            for r in conn.execute(text(f"SELECT version FROM {_MIGRATION_TABLE}")).fetchall()
        }
        for version, name, fn in _MIGRATIONS:
            if version in done:
                continue
            fn(conn)
            conn.execute(
                text(
                    f"INSERT INTO {_MIGRATION_TABLE} (version, name, applied_at) "
                    "VALUES (:v, :n, :t)"
                ),
                {"v": version, "n": name, "t": now_ts()},
            )
            logger.info("مهاجرت canonical %s (%s) اعمال شد", version, name)

    with _ensured_lock:
        _ensured_for.add(key)
    return CANONICAL_SCHEMA_VERSION


def reset_ensure_cache() -> None:
    """فراموش‌کردن کشِ «طرح‌واره ساخته شده» — فقط برای تست‌ها."""
    with _ensured_lock:
        _ensured_for.clear()


__all__ = [
    "CANONICAL_SCHEMA_VERSION",
    "applied_versions",
    "ensure_schema",
    "reset_ensure_cache",
]
