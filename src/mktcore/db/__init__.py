"""لایه‌ی داده‌ی canonical — جداول رابطه‌ای پایدارِ Revenue Intelligence.

این لایه **موازی** خط لوله‌ی تحلیل موجود کار می‌کند و آن را جایگزین نمی‌کند:
تحلیل و داشبورد همچنان از `MetricsBundle` (pandas) تغذیه می‌شوند، و جداول
canonical برای چیزهایی‌اند که یک نشستِ تنها نمی‌تواند بدهد — پیوند هویت مشتری
بین بارگذاری‌ها، فرصت‌های ماندگار با چرخه‌ی حیات، و آشتی ماندگارِ هر بارگذاری.

قواعد این لایه (تصمیم‌های مستند در `docs/revenue-intelligence/TARGET_ARCHITECTURE.md`):

* موتور **SQLAlchemy 2.0** روی همان فایل `data/app.db` می‌نشیند؛ با تغییر URL
  به Postgres منتقل می‌شود.
* جداول legacy (`sessions`, `jobs`, `outbox`, `mapping_profiles`) در
  `Base.metadata` **نیستند** و مالکشان `api/persistence.py` می‌ماند؛
  `PRAGMA user_version` هم دست‌نخورده در ۲ می‌ماند.
* نسخه‌گذاری این لایه مستقل است: جدول `schema_migrations`.
"""

from .base import Base
from .engine import canonical_db_path, dispose_engine, get_engine, get_sessionmaker, session_scope
from .migrations import CANONICAL_SCHEMA_VERSION, applied_versions, ensure_schema

__all__ = [
    "CANONICAL_SCHEMA_VERSION",
    "Base",
    "applied_versions",
    "canonical_db_path",
    "dispose_engine",
    "ensure_schema",
    "get_engine",
    "get_sessionmaker",
    "session_scope",
]
