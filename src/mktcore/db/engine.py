"""موتور و نشست SQLAlchemy روی همان فایل SQLite برنامه.

چرا همان فایل و نه دیتابیس جدا؟ چون یک پشتیبان، یک rollback و یک تراکنش‌مرزِ
واحد ساده‌تر و اثبات‌پذیرتر است. جداول این لایه با پیشوندهای مستقل زندگی می‌کنند
و جداول legacy را لمس نمی‌کنند.

نکته‌های عملیاتی که در پیاده‌سازی فعلی SQLite تجربه شده و اینجا تکرار می‌شود:

* `journal_mode=WAL` تا خواندن با نوشتن قفل نشود.
* `busy_timeout` تا نوشتن هم‌زمانِ threadها به‌جای خطا، صبر کند.
* `foreign_keys=ON` — SQLite پیش‌فرض آن را خاموش می‌گذارد و بدون این، کلید
  خارجی صرفاً یک برچسب تزئینی است.
"""

from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy import event
from sqlalchemy.engine import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from mktcore.config import get_settings

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger("mktcore.db")

_lock = threading.Lock()
# موتورها **به‌ازای URL** نگه داشته می‌شوند و هرگز به‌خاطر تغییر مسیر داده
# رها نمی‌شوند. علتش یک قفل‌شدگی واقعی است: اگر با عوض‌شدن مسیر، موتور قبلی
# `dispose` شود، اتصالی که یک thread دیگر وسط تراکنش در دست دارد از استخر
# بیرون می‌افتد ولی قفلِ نوشتنِ SQLite را همچنان نگه می‌دارد — و نوشتن‌های
# بعدی برای همیشه منتظر می‌مانند. `dispose_engine()` صریح همچنان در دسترس است.
_engines: dict[str, Engine] = {}
_sessionmakers: dict[str, sessionmaker[Session]] = {}

# قفل نوشتن در سطح پروسه. SQLite تک-نویسنده است؛ jobهای موازی (ThreadPool با ۲
# worker) بدون این قفل به `database is locked` می‌خورند حتی با busy_timeout،
# چون تراکنش‌های طولانی درج تکه‌ای هم‌زمان می‌شوند.
write_lock = threading.RLock()


def canonical_db_path() -> Path:
    """مسیر فایل دیتابیس — همان `app.db` که لایه‌ی legacy استفاده می‌کند."""
    data_dir = Path(get_settings().mkt_data_dir).expanduser()
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "app.db"


def database_url(db_path: Path | None = None) -> str:
    """URL موتور. برای مهاجرت به Postgres فقط همین تابع عوض می‌شود."""
    return f"sqlite+pysqlite:///{(db_path or canonical_db_path()).as_posix()}"


def _apply_sqlite_pragmas(dbapi_conn: Any, _record: Any) -> None:
    cur = dbapi_conn.cursor()
    try:
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=15000")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA synchronous=NORMAL")
    finally:
        cur.close()


def get_engine(db_path: Path | None = None) -> Engine:
    """موتورِ متناظر با این مسیر داده (یک نمونه به‌ازای هر URL).

    در استقرار واقعی همیشه یک URL وجود دارد؛ چند-URL فقط در تست‌ها پیش می‌آید
    که هرکدام دیتابیس موقتِ خودشان را می‌سازند. نگه‌داشتن همه، از رهاشدنِ
    اتصالِ در حال استفاده جلوگیری می‌کند.
    """
    url = database_url(db_path)
    with _lock:
        engine = _engines.get(url)
        if engine is not None:
            return engine
        engine = create_engine(
            url,
            future=True,
            # هر thread اتصال خودش را می‌گیرد؛ اتصال SQLite بین threadها امن نیست.
            connect_args={"timeout": 30, "check_same_thread": False},
            pool_pre_ping=True,
        )
        if url.startswith("sqlite"):
            event.listen(engine, "connect", _apply_sqlite_pragmas)
        _engines[url] = engine
        _sessionmakers[url] = sessionmaker(bind=engine, expire_on_commit=False, future=True)
        logger.info("موتور canonical آماده شد: %s", url)
        return engine


def get_sessionmaker(db_path: Path | None = None) -> sessionmaker[Session]:
    """سازنده‌ی نشست متناظر با همان مسیر داده."""
    get_engine(db_path)
    maker = _sessionmakers.get(database_url(db_path))
    if maker is None:  # pragma: no cover - get_engine همیشه می‌سازد
        raise RuntimeError("سازنده‌ی نشست canonical ساخته نشد.")
    return maker


@contextmanager
def session_scope(db_path: Path | None = None) -> Iterator[Session]:
    """مدیر متن تراکنش: commit در موفقیت، rollback در خطا، بستن در هر حال."""
    session = get_sessionmaker(db_path)()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def dispose_engine(db_path: Path | None = None, *, all_engines: bool = False) -> None:
    """رهاکردن موتور (بستن برنامه) — استخر اتصال را می‌بندد.

    فقط جایی صدا زده می‌شود که مطمئنیم هیچ تراکنشی در جریان نیست؛ در مسیر
    عادی هرگز خودکار اجرا نمی‌شود.
    """
    with _lock:
        urls = list(_engines) if all_engines else [database_url(db_path)]
        for url in urls:
            engine = _engines.pop(url, None)
            _sessionmakers.pop(url, None)
            if engine is not None:
                engine.dispose()


__all__ = [
    "canonical_db_path",
    "database_url",
    "dispose_engine",
    "get_engine",
    "get_sessionmaker",
    "session_scope",
    "write_lock",
]
