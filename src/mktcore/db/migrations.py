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
CANONICAL_SCHEMA_VERSION = 19

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


def _migration_0016_offer_margin_basis(conn: Connection) -> None:
    """مبنای حاشیه‌ی پیشنهاد و شمارِ خطوطِ سهمِ تمام‌قیمت — سه ستونِ nullable.

    بازبینیِ خصمانه نشان داد تأییدِ آفر حاشیه را با مبنایی جز مبنای موتور
    بازخوانی می‌کرد (فرصتِ «شکاف دسته» `product_id` ندارد ولی نامِ دسته دارد).
    مبنا حالا روی خودِ ردیف می‌ماند.
    """
    added_columns = (
        ("opportunity_offers", "margin_basis", "VARCHAR(16)"),
        ("opportunity_offers", "margin_key", "VARCHAR(255)"),
        ("customer_features", "full_price_lines", "INTEGER"),
    )
    for table, column, ddl_type in added_columns:
        existing = {
            row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")
        }
        if column not in existing:
            conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}")


def _migration_0017_order_line_identity(conn: Connection) -> None:
    """هویتِ پایدارِ خطِ فاکتور (§۸.۴ لایه‌های ۲–۴).

    تا این نسخه `line_uid` از هشِ فایل + شماره‌ی ردیف ساخته می‌شد؛ پس دو صادراتِ
    هم‌پوشان از ERP همان خط را دوبار می‌نوشتند. حالا کلیدِ خطِ فاکتوردار =
    فاکتور + کالا + نوع + ترتیب است (`line_uid_for_order`). این مهاجرت:

    1. تکراری‌های ازقبل‌ایجادشده را ادغام می‌کند: خطوطِ یک گروهِ (فاکتور، کالا،
       نوع) که از **دسته‌های متفاوت** آمده‌اند و مبلغ و مقدارِ یکسان دارند، یک
       خط‌اند؛ جدیدترین می‌ماند. (خطِ اصلاح‌شده‌ی تاریخی قابل تشخیص نیست و
       می‌ماند — مستند در FINANCIAL_CALCULATION_RULES.)
    2. `line_uid` بازماندگان را با قاعده‌ی تازه بازنویسی می‌کند.
    3. سرِ فاکتورهای لمس‌شده را از خطوطِ واقعی‌شان بازمحاسبه می‌کند.
    """
    from mktcore.catalog import normalize_product_name
    from mktcore.db.repo_import import (
        identity_period,
        line_uid_for_order,
        normalize_order_key,
    )

    # ۰) شماره‌ی فاکتورِ سرِ سفارش نرمال می‌شود (ارقام، فاصله، «.0»)؛ اگر دو سفارش
    # به یک کلید برسند، هر دو دست‌نخورده می‌مانند و لاگ می‌شود (نادر).
    orders = conn.exec_driver_sql(
        "SELECT id, business_id, order_key FROM orders"
    ).fetchall()
    normalized: dict[int, str] = {}
    taken: set[tuple[int, str]] = {(b, k) for _i, b, k in orders}
    for order_id, business_id, key in orders:
        norm = normalize_order_key(key) or key
        if norm == key:
            continue
        if (business_id, norm) in taken:
            logger.warning("مهاجرت ۱۷: فاکتور «%s» بعد از نرمال‌سازی با «%s» یکی می‌شد؛ دست نخورد", key, norm)
            continue
        taken.add((business_id, norm))
        normalized[order_id] = norm
    for order_id, norm in normalized.items():
        conn.execute(text("UPDATE orders SET order_key = :k WHERE id = :i"), {"k": norm, "i": order_id})

    rows = conn.exec_driver_sql(
        "SELECT ol.id, ol.business_id, o.order_key, ol.raw_product_name, ol.is_return, "
        "ol.source_row, ol.batch_id, ol.order_id, ol.revenue_rial, ol.quantity_milli, ol.line_date "
        "FROM order_lines ol JOIN orders o ON o.id = ol.order_id "
        "WHERE ol.order_id IS NOT NULL "
        "ORDER BY ol.business_id, ol.order_id, ol.source_row, ol.id"
    ).fetchall()

    groups: dict[tuple, list[tuple]] = {}
    for row in rows:
        (_line_id, business_id, order_key, raw_product, is_return, *_rest) = row
        key = (
            business_id, identity_period(row[10]), order_key,
            normalize_product_name(raw_product) if raw_product else "", bool(is_return),
        )
        groups.setdefault(key, []).append(row)

    to_delete: list[int] = []
    uid_updates: list[dict] = []
    touched_orders: set[int] = set()
    for key, members in groups.items():
        business_id, period, order_key, product_norm, is_return = key
        # ادغامِ تکراری‌های میان‌دسته‌ای — **مستقل از ترتیب**: به‌ازای هر اثرِ
        # انگشت (مبلغ، مقدار)، دسته‌ی جدیدتر با همه‌ی تکرارهایش می‌ماند و ردیف‌های
        # دسته‌های دیگر با همان اثر انگشت حذف می‌شوند. مقایسه‌ی جفت‌جفت (نسخه‌ی
        # قبلی) بسته به جای‌گیریِ source_row، یک تکراری را زنده می‌گذاشت.
        by_fp: dict[tuple, dict[int, list[tuple]]] = {}
        for row in members:
            fingerprint = (row[8], row[9])
            by_fp.setdefault(fingerprint, {}).setdefault(row[6], []).append(row)
        survivors: list[tuple] = []
        for _fp, per_batch in by_fp.items():
            winner = max(per_batch)
            survivors.extend(per_batch[winner])
            for batch_id, batch_rows in per_batch.items():
                if batch_id == winner:
                    continue
                for row in batch_rows:
                    to_delete.append(row[0])
                    touched_orders.add(row[7])
        survivors.sort(key=lambda r: ((r[5] if r[5] is not None else 1 << 60), r[0]))
        for ordinal, row in enumerate(survivors):
            uid_updates.append({
                "id": row[0],
                "uid": line_uid_for_order(
                    business_id, order_key, product_norm, is_return, ordinal, period=period,
                ),
            })

    for start in range(0, len(to_delete), 500):
        chunk = to_delete[start:start + 500]
        conn.exec_driver_sql(
            f"DELETE FROM order_lines WHERE id IN ({','.join(str(i) for i in chunk)})"
        )
    for start in range(0, len(uid_updates), 500):
        chunk = uid_updates[start:start + 500]
        conn.execute(
            text("UPDATE order_lines SET line_uid = :uid WHERE id = :id"), chunk,
        )
    for order_id in sorted(touched_orders):
        conn.execute(text(
            "UPDATE orders SET "
            "gross_rial = (SELECT COALESCE(SUM(CASE WHEN is_return = 0 THEN revenue_rial ELSE 0 END), 0) "
            "  FROM order_lines WHERE order_id = :oid), "
            "returns_rial = (SELECT COALESCE(SUM(CASE WHEN is_return = 1 THEN -revenue_rial ELSE 0 END), 0) "
            "  FROM order_lines WHERE order_id = :oid), "
            "line_count = (SELECT COUNT(*) FROM order_lines WHERE order_id = :oid) "
            "WHERE id = :oid"
        ), {"oid": order_id})
        conn.execute(text(
            "UPDATE orders SET net_rial = gross_rial - returns_rial WHERE id = :oid"
        ), {"oid": order_id})
    if rows:
        logger.info(
            "مهاجرت ۱۷: %s خطِ فاکتوردار بازکلیدگذاری شد، %s تکراریِ میان‌دسته‌ای ادغام شد، "
            "%s سرِ فاکتور بازمحاسبه شد",
            len(uid_updates), len(to_delete), len(touched_orders),
        )


def _migration_0018_order_header_period(conn: Connection) -> None:
    """سرِ فاکتورِ دوره‌دار (§۸.۴ / §۷.۴).

    از مهاجرت ۱۷ خطِ فاکتور دوره دارد ولی سرِ فاکتور فقط با شماره یکتا بود؛ شماره‌ای
    که ERP هر سال از نو می‌زند، خطوطِ دو سال را زیرِ **یک** سر جمع می‌کرد (شمارِ
    سفارش کم، AOV متورم، تاریخِ سفارش سالِ قبل). این مهاجرت:

    1. ستون‌های `order_period` و `order_number` را اضافه می‌کند.
    2. هر سر را با دوره‌ی خطوطش کلیدگذاری می‌کند: `order_key = "{دوره}/{شماره}"`.
    3. سری که خطوطِ چند دوره دارد **تفکیک** می‌شود: سرِ موجود دوره‌ی قدیمی‌تر را
       نگه می‌دارد و برای هر دوره‌ی دیگر سرِ تازه ساخته و خطوط به آن وصل می‌شوند؛
       سپس همه‌ی سرهای لمس‌شده از خطوطشان بازمحاسبه می‌شوند.
    """
    existing = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(orders)")}
    if "order_period" not in existing:
        conn.exec_driver_sql("ALTER TABLE orders ADD COLUMN order_period VARCHAR(4)")
    if "order_number" not in existing:
        conn.exec_driver_sql("ALTER TABLE orders ADD COLUMN order_number VARCHAR(128)")
        conn.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_orders_order_number ON orders (order_number)"
        )

    orders = conn.exec_driver_sql(
        "SELECT id, business_id, order_key, order_date, customer_id, branch, salesperson, "
        "channel, region, batch_id, created_at FROM orders WHERE order_number IS NULL"
    ).fetchall()
    if not orders:
        return

    periods_by_order: dict[int, list[str]] = {}
    for order_id, period in conn.exec_driver_sql(
        "SELECT order_id, substr(line_date, 1, 4) AS p FROM order_lines "
        "WHERE order_id IS NOT NULL GROUP BY order_id, p ORDER BY order_id, p"
    ).fetchall():
        periods_by_order.setdefault(int(order_id), []).append(str(period or ""))

    taken: set[tuple[int, str]] = {
        (b, k) for b, k in conn.exec_driver_sql("SELECT business_id, order_key FROM orders")
    }
    touched: set[int] = set()
    split = 0
    for (order_id, business_id, key, order_date, customer_id, branch, salesperson,
         channel, region, batch_id, created_at) in orders:
        number = key
        periods = periods_by_order.get(order_id) or [str(order_date or "")[:4]]
        first, rest = periods[0], periods[1:]
        for period in rest:
            new_key = f"{period}/{number}"
            if (business_id, new_key) in taken:
                logger.warning("مهاجرت ۱۸: کلیدِ «%s» از قبل وجود دارد؛ تفکیکِ سرِ %s برای این دوره انجام نشد", new_key, order_id)
                continue
            taken.add((business_id, new_key))
            conn.execute(text(
                "INSERT INTO orders (business_id, order_key, order_period, order_number, customer_id, "
                "order_date, gross_rial, returns_rial, net_rial, line_count, branch, salesperson, "
                "channel, region, batch_id, created_at, updated_at) VALUES "
                "(:b, :k, :p, :n, :c, :d, 0, 0, 0, 0, :br, :sp, :ch, :rg, :bt, :ca, :ca)"
            ), {"b": business_id, "k": new_key, "p": period, "n": number, "c": customer_id,
                "d": f"{period}-01-01", "br": branch, "sp": salesperson, "ch": channel,
                "rg": region, "bt": batch_id, "ca": created_at})
            new_id = conn.exec_driver_sql(
                "SELECT id FROM orders WHERE business_id = ? AND order_key = ?",
                (business_id, new_key),
            ).scalar()
            conn.execute(text(
                "UPDATE order_lines SET order_id = :new WHERE order_id = :old "
                "AND substr(line_date, 1, 4) = :p"
            ), {"new": new_id, "old": order_id, "p": period})
            touched.add(int(new_id))
            split += 1
        first_key = f"{first}/{number}"
        if (business_id, first_key) in taken and first_key != key:
            logger.warning("مهاجرت ۱۸: کلیدِ «%s» از قبل وجود دارد؛ سرِ %s با کلیدِ قدیمی ماند", first_key, order_id)
            first_key = key
        taken.add((business_id, first_key))
        conn.execute(text(
            "UPDATE orders SET order_key = :k, order_period = :p, order_number = :n WHERE id = :i"
        ), {"k": first_key, "p": first, "n": number, "i": order_id})
        if rest:
            touched.add(int(order_id))

    for order_id in sorted(touched):
        conn.execute(text(
            "UPDATE orders SET "
            "gross_rial = (SELECT COALESCE(SUM(CASE WHEN is_return = 0 THEN revenue_rial ELSE 0 END), 0) "
            "  FROM order_lines WHERE order_id = :oid), "
            "returns_rial = (SELECT COALESCE(SUM(CASE WHEN is_return = 1 THEN -revenue_rial ELSE 0 END), 0) "
            "  FROM order_lines WHERE order_id = :oid), "
            "line_count = (SELECT COUNT(*) FROM order_lines WHERE order_id = :oid), "
            "order_date = COALESCE((SELECT MIN(line_date) FROM order_lines WHERE order_id = :oid), order_date) "
            "WHERE id = :oid"
        ), {"oid": order_id})
        conn.execute(text(
            "UPDATE orders SET net_rial = gross_rial - returns_rial WHERE id = :oid"
        ), {"oid": order_id})
    logger.info("مهاجرت ۱۸: %s سرِ فاکتور دوره‌دار شد، %s سرِ ادغام‌شده تفکیک شد", len(orders), split)


def _migration_0019_mapping_profile_versions(conn: Connection) -> None:
    """نگاشتِ نسخه‌دار §۸.۲ (برشِ اول): جدولِ تازه + دو ستونِ nullable روی دسته.

    جدولِ legacy `mapping_profiles` دست نمی‌خورد (پیش‌فرضِ خودکارِ نگاشت همان می‌ماند).
    """
    from mktcore.db import models  # noqa: F401 - ثبت مدل‌ها در metadata

    Base.metadata.create_all(bind=conn, checkfirst=True)
    added_columns = (
        ("import_batches", "mapping_signature", "VARCHAR(64)"),
        ("import_batches", "mapping_version", "INTEGER"),
    )
    for table, column, ddl_type in added_columns:
        existing = {
            row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")
        }
        if column not in existing:
            conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}")
    conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_import_batches_mapping_signature "
        "ON import_batches (mapping_signature)"
    )


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
    (16, "offer_margin_basis", _migration_0016_offer_margin_basis),
    (17, "order_line_identity", _migration_0017_order_line_identity),
    (18, "order_header_period", _migration_0018_order_header_period),
    (19, "mapping_profile_versions", _migration_0019_mapping_profile_versions),
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
