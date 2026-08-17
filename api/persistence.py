"""لایه‌ی ماندگاری: SQLite برای متادیتا + دیسک برای دیتافریم‌ها و باندل تحلیل.

جایگزین ذخیره‌ی درون‌حافظه‌ای قبلی؛ نشست‌ها، jobها و outbox پس از ری‌استارت سرور
زنده می‌مانند. دیتافریم‌ها به‌صورت pickle/parquet در `data/sessions/{sid}/` ذخیره
می‌شوند و یک کش کوچک درون‌حافظه‌ای از بازخوانی مکرر فایل‌های بزرگ جلوگیری می‌کند.

نکته: طراحی برای استقرار تک-پروسه است (uvicorn بدون --workers). SQLite در حالت
WAL همزمانی threadها را تحمل می‌کند؛ چند پروسه هم fail-safe است (داده روی دیسک
مشترک است) ولی کش حافظه بین پروسه‌ها همگام نیست.
"""

from __future__ import annotations

import json
import logging
import pickle
import shutil
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pandas as pd

from mktcore.config import get_settings

logger = logging.getLogger("mktcore.persistence")

if TYPE_CHECKING:
    from mktcore.pipeline import MetricsBundle

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    created_at REAL NOT NULL,
    filename TEXT,
    columns_json TEXT,
    mapping_json TEXT,
    analysis_json TEXT,
    strategy_json TEXT,
    campaign_json TEXT
);
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    session_id TEXT,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    progress REAL NOT NULL DEFAULT 0,
    stage TEXT DEFAULT '',
    error TEXT,
    result_json TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at REAL NOT NULL,
    session_id TEXT,
    kind TEXT NOT NULL,
    audience TEXT,
    customer_id TEXT,
    phone TEXT,
    message TEXT,
    status TEXT NOT NULL,
    provider TEXT,
    dry_run INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS app_meta (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS mapping_profiles (
    signature TEXT PRIMARY KEY,
    columns_json TEXT NOT NULL,
    mapping_json TEXT NOT NULL,
    file_currency TEXT,
    display_currency TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    use_count INTEGER NOT NULL DEFAULT 1
);
"""

_SCHEMA_VERSION = 2

# ستون‌های افزوده‌شده به جدول موجود — با PRAGMA table_info محافظت می‌شوند تا
# دیتابیس فعلی کاربر (۸ ستون) بدون از دست رفتن ردیف مهاجرت کند.
_ADDED_COLUMNS = (
    ("sessions", "label", "TEXT"),
    ("sessions", "archived_at", "REAL"),
    ("sessions", "summary_json", "TEXT"),
    ("sessions", "last_opened_at", "REAL"),
)

_INDICES = (
    "CREATE INDEX IF NOT EXISTS idx_sessions_created ON sessions(created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_jobs_session ON jobs(session_id, status)",
    # بدون این، هر بررسی «آیا اخیراً به این مشتری پیام داده‌ایم؟» یک پیمایش کامل
    # جدول بود — به‌ازای **هر** گیرنده در هر اسکن.
    "CREATE INDEX IF NOT EXISTS idx_outbox_customer ON outbox(customer_id, created_at DESC)",
)


def _summary_from_analysis(payload: dict) -> dict:
    """خلاصه‌ی سبک برای فهرست نشست‌ها (تا هرگز analysis_json بزرگ پارس نشود)."""
    q = payload.get("quality") or {}
    k = payload.get("kpis") or {}
    m = payload.get("manifest") or {}
    return {
        "n_rows": q.get("n_rows") or m.get("clean_rows"),
        "date_min": q.get("date_min"),
        "date_max": q.get("date_max"),
        "total_revenue": k.get("total_revenue"),
        "currency": payload.get("currency"),
        "validation_status": (payload.get("validation") or {}).get("status"),
        "analyzed_at": m.get("analyzed_at"),
        "pipeline_version": m.get("pipeline_version"),
    }


def _summary_from_columns(payload: dict) -> dict:
    """خلاصه‌ی نشست‌های تحلیل‌نشده (فایل آپلود شده ولی تحلیل نشده)."""
    return {
        "n_rows": payload.get("n_rows"),
        "n_columns": len(payload.get("columns") or []),
        "header_signature": payload.get("header_signature"),
    }


@dataclass
class SessionRecord:
    """متادیتای یک نشست (بدون دیتافریم‌ها؛ آن‌ها lazy از دیسک می‌آیند)."""

    id: str
    created_at: float
    filename: str | None = None
    columns_payload: dict | None = None
    mapping: dict | None = None
    analysis: dict | None = None
    strategy: dict | None = None
    campaign: dict | None = None
    label: str | None = None
    archived_at: float | None = None

    @property
    def has_analysis(self) -> bool:
        return self.analysis is not None


@dataclass
class JobRecord:
    id: str
    session_id: str | None
    kind: str
    status: str  # queued | running | done | error
    progress: float
    stage: str
    error: str | None
    result: Any | None
    created_at: float
    updated_at: float


def _j(value) -> str | None:
    return None if value is None else json.dumps(value, ensure_ascii=False)


def _uj(text) -> Any | None:
    return None if text is None else json.loads(text)


class PersistentStore:
    """ذخیره‌ی ماندگار نشست‌ها/جاب‌ها/outbox با کش حافظه‌ای کوچک برای فریم‌ها."""

    def __init__(self, data_dir: Path | None = None) -> None:
        settings = get_settings()
        self.data_dir = Path(data_dir or settings.mkt_data_dir).expanduser()
        self.sessions_dir = self.data_dir / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "app.db"
        self.retention = settings.retention_policy
        self._lock = threading.Lock()
        self._frame_cache: dict[tuple[str, str], Any] = {}
        self._init_db()
        # «حافظه کجاست؟» باید در لاگ صریح باشد — مسیر نسبی + mkdir بی‌صدا
        # باعث می‌شد اجرای سرور از پوشه‌ی دیگر مثل «پاک شدن همه‌چیز» به‌نظر برسد.
        logger.info(
            "ذخیره‌گاه داده: %s (دیتابیس: %s، موجود: %s) — نگه‌داری: %s",
            self.data_dir.resolve(), self.db_path.name, self.db_path.exists(),
            self.retention["policy_fa"],
        )
        if settings.mkt_session_ttl_hours is not None:
            logger.warning(
                "MKT_SESSION_TTL_HOURS=%s منسوخ است و دیگر نشست‌ها را حذف نمی‌کند؛ "
                "از کلیدهای MKT_RETENTION_* استفاده کنید.",
                settings.mkt_session_ttl_hours,
            )

    # ---------------------------------------------------------------- پایه
    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=15000")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._conn() as c:
            c.executescript(_SCHEMA)  # executescript خودش commit می‌کند
            for table, col, decl in _ADDED_COLUMNS:
                have = {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}
                if col not in have:
                    c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
                    logger.info("مهاجرت: ستون %s.%s اضافه شد", table, col)
            for ddl in _INDICES:
                c.execute(ddl)
            version = c.execute("PRAGMA user_version").fetchone()[0]
            if version < _SCHEMA_VERSION:
                self._backfill_summaries(c)
                c.execute(f"PRAGMA user_version = {int(_SCHEMA_VERSION)}")
                logger.info("مهاجرت طرح‌واره: %s → %s", version, _SCHEMA_VERSION)

    def _backfill_summaries(self, c: sqlite3.Connection) -> None:
        """پر کردن summary_json نشست‌های قبلی (idempotent؛ فقط ردیف‌های NULL)."""
        rows = c.execute(
            "SELECT id, analysis_json, columns_json FROM sessions WHERE summary_json IS NULL"
        ).fetchall()
        for r in rows:
            try:
                summary: dict = {}
                if r["columns_json"]:
                    summary.update(_summary_from_columns(json.loads(r["columns_json"])))
                if r["analysis_json"]:
                    summary.update(_summary_from_analysis(json.loads(r["analysis_json"])))
                if summary:
                    c.execute("UPDATE sessions SET summary_json = ? WHERE id = ?",
                              (_j(summary), r["id"]))
            except Exception:  # noqa: BLE001 - یک ردیف خراب نباید بالا آمدن API را بشکند
                logger.exception("backfill خلاصه‌ی نشست %s ناموفق بود", r["id"])

    def _sdir(self, sid: str) -> Path:
        return self.sessions_dir / sid

    def _cache_put(self, sid: str, key: str, value: Any) -> None:
        with self._lock:
            self._frame_cache[(sid, key)] = value
            # سقف ساده برای مصرف حافظه
            while len(self._frame_cache) > 6:
                self._frame_cache.pop(next(iter(self._frame_cache)))

    def _cache_get(self, sid: str, key: str) -> Any | None:
        with self._lock:
            return self._frame_cache.get((sid, key))

    def _cache_drop(self, sid: str) -> None:
        with self._lock:
            for k in [k for k in self._frame_cache if k[0] == sid]:
                self._frame_cache.pop(k, None)

    # ------------------------------------------------------------- نشست‌ها
    def create_session(self, filename: str | None = None) -> str:
        sid = uuid.uuid4().hex
        self._sdir(sid).mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.execute(
                "INSERT INTO sessions (id, created_at, filename) VALUES (?, ?, ?)",
                (sid, time.time(), filename),
            )
        return sid

    def get_session(self, sid: str) -> SessionRecord | None:
        """بازیابی نشست با اعمال TTL هنگام خواندن."""
        with self._conn() as c:
            row = c.execute("SELECT * FROM sessions WHERE id = ?", (sid,)).fetchone()
        if row is None:
            return None
        # هیچ حذفی هنگام خواندن انجام نمی‌شود: پیش‌تر نشستِ گذشته از TTL دقیقاً
        # در لحظه‌ی بازکردن پاک می‌شد و کاربر «حافظه ندارد» را تجربه می‌کرد.
        return SessionRecord(
            id=row["id"],
            created_at=row["created_at"],
            filename=row["filename"],
            columns_payload=_uj(row["columns_json"]),
            mapping=_uj(row["mapping_json"]),
            analysis=_uj(row["analysis_json"]),
            strategy=_uj(row["strategy_json"]),
            campaign=_uj(row["campaign_json"]),
            label=row["label"],
            archived_at=row["archived_at"],
        )

    def delete_session(self, sid: str) -> bool:
        """حذف کامل نشست (فقط با درخواست صریح کاربر یا سیاست delete_days)."""
        with self._conn() as c:
            cur = c.execute("DELETE FROM sessions WHERE id = ?", (sid,))
            existed = cur.rowcount > 0
        self._cache_drop(sid)
        sdir = self._sdir(sid)
        shutil.rmtree(sdir, ignore_errors=True)
        if sdir.exists():  # روی ویندوز قفل فایل ممکن است مانع شود
            logger.warning("پوشه‌ی نشست %s حذف نشد: %s", sid, sdir)
        return existed

    # -------------------------------------------------- سیاست نگه‌داری (هرس)
    _HEAVY_FILES = ("clean.parquet", "clean.pkl", "bundle.pkl",
                    "returns.parquet", "returns.pkl",
                    "exclusions.parquet", "exclusions.pkl")

    def _busy_sessions(self) -> set[str]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT DISTINCT session_id FROM jobs "
                "WHERE status IN ('queued','running') AND session_id IS NOT NULL"
            ).fetchall()
        return {r["session_id"] for r in rows}

    def run_retention(
        self,
        *,
        raw_days: int | None = None,
        heavy_days: int | None = None,
        delete_days: int | None = None,
        jobs_days: int | None = None,
    ) -> dict:
        """هرس فایل‌های سنگین طبق سیاست؛ نتیجه‌ی تحلیل هرگز خودکار حذف نمی‌شود.

        در همه‌ی پارامترها ۰ (یا None با پیش‌فرض ۰) به‌معنی «هرگز» است. نشستِ
        «آخرین تحلیل» و نشست‌های دارای job در حال اجرا هرس نمی‌شوند.
        """
        pol = self.retention
        raw_days = pol["raw_days"] if raw_days is None else raw_days
        heavy_days = pol["heavy_days"] if heavy_days is None else heavy_days
        delete_days = pol["delete_days"] if delete_days is None else delete_days
        jobs_days = pol["jobs_days"] if jobs_days is None else jobs_days

        now = time.time()
        protected = {s for s in (self.latest_session_with_analysis(),) if s}
        protected |= self._busy_sessions()
        result = {"raw_pruned": 0, "archived": 0, "deleted": 0, "jobs_pruned": 0}

        with self._conn() as c:
            rows = c.execute("SELECT id, created_at, archived_at FROM sessions").fetchall()
        for row in rows:
            sid, age_days = row["id"], (now - row["created_at"]) / 86400.0
            if delete_days > 0 and age_days > delete_days and sid not in protected:
                if self.delete_session(sid):
                    result["deleted"] += 1
                continue
            if sid in protected:
                continue
            if raw_days > 0 and age_days > raw_days:
                raw = self._sdir(sid) / "raw.pkl"
                if raw.exists():
                    raw.unlink(missing_ok=True)
                    self._cache_drop(sid)
                    result["raw_pruned"] += 1
            if heavy_days > 0 and age_days > heavy_days and row["archived_at"] is None:
                removed = False
                for name in self._HEAVY_FILES:
                    p = self._sdir(sid) / name
                    if p.exists():
                        p.unlink(missing_ok=True)
                        removed = True
                if removed:
                    self._cache_drop(sid)  # کش نباید فایل بایگانی‌شده را سرو کند
                    with self._conn() as c:
                        c.execute("UPDATE sessions SET archived_at = ? WHERE id = ?",
                                  (now, sid))
                    result["archived"] += 1

        if jobs_days > 0:
            cutoff = now - jobs_days * 86400.0
            with self._conn() as c:
                cur = c.execute(
                    "DELETE FROM jobs WHERE status IN ('done','error') AND updated_at < ?",
                    (cutoff,),
                )
                result["jobs_pruned"] = cur.rowcount or 0

        if any(result.values()):
            logger.info("هرس نگه‌داری: %s", result)
        return result

    def cleanup_expired(self) -> int:
        """سازگاری با فراخوان‌های قدیمی: اجرای سیاست نگه‌داری."""
        r = self.run_retention()
        return r["deleted"]

    def latest_session_with_analysis(self) -> str | None:
        """جدیدترین نشستی که تحلیل کامل دارد (برای زمان‌بند و بازیابی خودکار)."""
        with self._conn() as c:
            row = c.execute(
                "SELECT id FROM sessions WHERE analysis_json IS NOT NULL "
                "ORDER BY COALESCE(last_opened_at, created_at) DESC LIMIT 1"
            ).fetchone()
        return None if row is None else row["id"]

    def _set_field(self, sid: str, column: str, value) -> None:
        with self._conn() as c:
            c.execute(f"UPDATE sessions SET {column} = ? WHERE id = ?", (_j(value), sid))

    def _merge_summary(self, sid: str, extra: dict) -> None:
        """به‌روزرسانی summary_json (خلاصه‌ی سبک فهرست) بدون دست‌زدن به بقیه."""
        with self._conn() as c:
            row = c.execute("SELECT summary_json FROM sessions WHERE id = ?",
                            (sid,)).fetchone()
            current = _uj(row["summary_json"]) if row and row["summary_json"] else {}
            current.update({k: v for k, v in extra.items() if v is not None})
            c.execute("UPDATE sessions SET summary_json = ? WHERE id = ?",
                      (_j(current), sid))

    def set_columns_payload(self, sid: str, payload: dict) -> None:
        self._set_field(sid, "columns_json", payload)
        self._merge_summary(sid, _summary_from_columns(payload))

    def set_mapping(self, sid: str, mapping: dict) -> None:
        self._set_field(sid, "mapping_json", mapping)

    def set_analysis(self, sid: str, analysis_payload: dict) -> None:
        self._set_field(sid, "analysis_json", analysis_payload)
        self._merge_summary(sid, _summary_from_analysis(analysis_payload))
        # تحلیل تازه = فایل‌های سنگین دوباره موجودند
        with self._conn() as c:
            c.execute("UPDATE sessions SET archived_at = NULL WHERE id = ?", (sid,))

    # ------------------------------------------------- فهرست و مدیریت نشست‌ها
    def session_files(self, sid: str) -> dict:
        d = self._sdir(sid)
        return {
            "raw": (d / "raw.pkl").exists(),
            "heavy": (d / "bundle.pkl").exists() and any(
                (d / n).exists() for n in ("clean.parquet", "clean.pkl")),
        }

    def list_sessions(self, *, limit: int = 20, offset: int = 0,
                      analyzed_only: bool = False) -> tuple[list[dict], int]:
        """فهرست نشست‌ها بدون پارس کردن analysis_json (فقط summary_json سبک)."""
        where = "WHERE analysis_json IS NOT NULL" if analyzed_only else ""
        with self._conn() as c:
            total = c.execute(f"SELECT COUNT(*) FROM sessions {where}").fetchone()[0]
            rows = c.execute(
                "SELECT id, created_at, filename, label, archived_at, summary_json, "
                "last_opened_at, analysis_json IS NOT NULL AS has_analysis, "
                "strategy_json IS NOT NULL AS has_strategy, "
                "campaign_json IS NOT NULL AS has_campaign, "
                "columns_json IS NOT NULL AS has_columns "
                f"FROM sessions {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()

        items: list[dict] = []
        for r in rows:
            summary = _uj(r["summary_json"]) or {}
            if not summary and r["has_analysis"]:  # خودترمیمی برای ردیف‌های قدیمی
                try:
                    with self._conn() as c:
                        raw = c.execute("SELECT analysis_json FROM sessions WHERE id = ?",
                                        (r["id"],)).fetchone()["analysis_json"]
                    summary = _summary_from_analysis(json.loads(raw))
                    self._merge_summary(r["id"], summary)
                except Exception:  # noqa: BLE001
                    logger.exception("ساخت خلاصه‌ی نشست %s ناموفق بود", r["id"])
            files = self.session_files(r["id"])
            items.append({
                "id": r["id"],
                "created_at": r["created_at"],
                "filename": r["filename"],
                "label": r["label"],
                "title": r["label"] or r["filename"] or "بدون نام",
                "has_analysis": bool(r["has_analysis"]),
                "has_strategy": bool(r["has_strategy"]),
                "has_campaign": bool(r["has_campaign"]),
                "has_columns": bool(r["has_columns"]),
                "archived": bool(r["archived_at"]) or (r["has_analysis"] and not files["heavy"]),
                "archived_at": r["archived_at"],
                "last_opened_at": r["last_opened_at"],
                "files": files,
                **{k: summary.get(k) for k in
                   ("n_rows", "date_min", "date_max", "total_revenue", "currency",
                    "validation_status")},
            })
        return items, int(total)

    def set_label(self, sid: str, label: str | None) -> bool:
        with self._conn() as c:
            cur = c.execute("UPDATE sessions SET label = ? WHERE id = ?", (label, sid))
            return cur.rowcount > 0

    def touch_opened(self, sid: str) -> None:
        with self._conn() as c:
            c.execute("UPDATE sessions SET last_opened_at = ? WHERE id = ?",
                      (time.time(), sid))

    def is_archived(self, sid: str) -> bool:
        with self._conn() as c:
            row = c.execute("SELECT archived_at FROM sessions WHERE id = ?",
                            (sid,)).fetchone()
        return bool(row and row["archived_at"])

    # ------------------------------------------------ پروفایل نگاشت ستون‌ها
    def get_mapping_profile(self, signature: str) -> dict | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM mapping_profiles WHERE signature = ?",
                            (signature,)).fetchone()
        if row is None:
            return None
        return {
            "signature": row["signature"],
            "columns": _uj(row["columns_json"]) or [],
            "mapping": _uj(row["mapping_json"]) or {},
            "file_currency": row["file_currency"],
            "display_currency": row["display_currency"],
            "updated_at": row["updated_at"],
            "use_count": row["use_count"],
        }

    def upsert_mapping_profile(self, signature: str, *, columns: list[str],
                               mapping: dict, file_currency: str | None = None,
                               display_currency: str | None = None) -> None:
        now = time.time()
        with self._conn() as c:
            c.execute(
                "INSERT INTO mapping_profiles (signature, columns_json, mapping_json, "
                "file_currency, display_currency, created_at, updated_at, use_count) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 1) "
                "ON CONFLICT(signature) DO UPDATE SET "
                "columns_json=excluded.columns_json, mapping_json=excluded.mapping_json, "
                "file_currency=excluded.file_currency, "
                "display_currency=excluded.display_currency, "
                "updated_at=excluded.updated_at, use_count=use_count+1",
                (signature, _j(columns), _j(mapping), file_currency, display_currency,
                 now, now),
            )

    def set_strategy(self, sid: str, strategy_dict: dict) -> None:
        self._set_field(sid, "strategy_json", strategy_dict)

    def set_campaign(self, sid: str, campaign_dict: dict) -> None:
        self._set_field(sid, "campaign_json", campaign_dict)

    # ------------------------------------------------- دیتافریم‌ها و باندل
    def save_raw(self, sid: str, df: pd.DataFrame) -> None:
        # raw ممکن است ستون‌های object با نوع مختلط داشته باشد → pickle امن‌تر از parquet
        df.to_pickle(self._sdir(sid) / "raw.pkl")
        self._cache_put(sid, "raw", df)

    def load_raw(self, sid: str) -> pd.DataFrame | None:
        cached = self._cache_get(sid, "raw")
        if cached is not None:
            return cached
        path = self._sdir(sid) / "raw.pkl"
        if not path.exists():
            return None
        df = pd.read_pickle(path)
        self._cache_put(sid, "raw", df)
        return df

    def save_clean(self, sid: str, df: pd.DataFrame) -> None:
        path = self._sdir(sid) / "clean.parquet"
        # attrs (فریم‌های جانبی ممیزی) در parquet ذخیره نمی‌شوند؛ جداگانه save می‌شوند
        to_write = df.copy()
        to_write.attrs = {}
        try:
            to_write.to_parquet(path)
        except Exception:
            # fallback در برابر نوع‌های خاص
            df.to_pickle(self._sdir(sid) / "clean.pkl")
        self._cache_put(sid, "clean", df)

    def save_side_frame(self, sid: str, name: str, df: pd.DataFrame) -> None:
        """ذخیره‌ی فریم‌های جانبی ممیزی (returns / exclusions) کنار clean."""
        path = self._sdir(sid) / f"{name}.parquet"
        try:
            df.to_parquet(path)
        except Exception:
            df.to_pickle(self._sdir(sid) / f"{name}.pkl")

    def load_side_frame(self, sid: str, name: str) -> pd.DataFrame | None:
        pq = self._sdir(sid) / f"{name}.parquet"
        pk = self._sdir(sid) / f"{name}.pkl"
        if pq.exists():
            return pd.read_parquet(pq)
        if pk.exists():
            return pd.read_pickle(pk)
        return None

    def load_clean(self, sid: str) -> pd.DataFrame | None:
        cached = self._cache_get(sid, "clean")
        if cached is not None:
            return cached
        pq = self._sdir(sid) / "clean.parquet"
        pk = self._sdir(sid) / "clean.pkl"
        if pq.exists():
            df = pd.read_parquet(pq)
        elif pk.exists():
            df = pd.read_pickle(pk)
        else:
            return None
        self._cache_put(sid, "clean", df)
        return df

    def save_bundle(self, sid: str, bundle: MetricsBundle) -> None:
        with open(self._sdir(sid) / "bundle.pkl", "wb") as f:
            pickle.dump(bundle, f)
        self._cache_put(sid, "bundle", bundle)

    def load_bundle(self, sid: str) -> MetricsBundle | None:
        cached = self._cache_get(sid, "bundle")
        if cached is not None:
            return cached
        path = self._sdir(sid) / "bundle.pkl"
        if not path.exists():
            return None
        with open(path, "rb") as f:
            bundle = pickle.load(f)
        self._cache_put(sid, "bundle", bundle)
        return bundle

    # ----------------------------------------------------------------- job
    def create_job(self, kind: str, session_id: str | None = None) -> str:
        jid = uuid.uuid4().hex
        now = time.time()
        with self._conn() as c:
            c.execute(
                "INSERT INTO jobs (id, session_id, kind, status, progress, stage, "
                "created_at, updated_at) VALUES (?, ?, ?, 'queued', 0, '', ?, ?)",
                (jid, session_id, kind, now, now),
            )
        return jid

    def update_job(self, jid: str, *, status: str | None = None,
                   progress: float | None = None, stage: str | None = None,
                   error: str | None = None, result: Any | None = None) -> None:
        sets, vals = ["updated_at = ?"], [time.time()]
        updates = {"status": status, "progress": progress, "stage": stage,
                   "error": error}
        for col, val in updates.items():
            if val is not None:
                sets.append(f"{col} = ?")
                vals.append(float(val) if col == "progress" else val)
        if result is not None:
            sets.append("result_json = ?")
            vals.append(_j(result))
        vals.append(jid)
        with self._conn() as c:
            c.execute(f"UPDATE jobs SET {', '.join(sets)} WHERE id = ?", vals)

    def get_job(self, jid: str) -> JobRecord | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM jobs WHERE id = ?", (jid,)).fetchone()
        if row is None:
            return None
        return JobRecord(
            id=row["id"], session_id=row["session_id"], kind=row["kind"],
            status=row["status"], progress=row["progress"], stage=row["stage"] or "",
            error=row["error"], result=_uj(row["result_json"]),
            created_at=row["created_at"], updated_at=row["updated_at"],
        )

    def mark_stale_job(self, jid: str, message: str) -> bool:
        """اگر job هنوز غیرنهایی است آن را خطا علامت بزن (race-safe با شرط status)."""
        with self._conn() as c:
            cur = c.execute(
                "UPDATE jobs SET status='error', error=?, updated_at=? "
                "WHERE id=? AND status IN ('queued','running')",
                (message, time.time(), jid),
            )
            return cur.rowcount > 0

    def recover_stale_jobs(self) -> int:
        """jobهایی که هنگام ری‌استارت سرور queued/running مانده‌اند → خطای شفاف."""
        with self._conn() as c:
            cur = c.execute(
                "UPDATE jobs SET status='error', "
                "error='سرور در میانه‌ی پردازش ری‌استارت شد؛ لطفاً دوباره تلاش کنید.', "
                "updated_at=? WHERE status IN ('queued','running')",
                (time.time(),),
            )
            return cur.rowcount

    # -------------------------------------------------------------- outbox
    def add_outbox(self, *, kind: str, status: str, session_id: str | None = None,
                   audience: str | None = None, customer_id: str | None = None,
                   phone: str | None = None, message: str | None = None,
                   provider: str | None = None, dry_run: bool = True) -> int:
        """ثبت یک ردیف در outbox و برگرداندن شناسه‌ی آن.

        شناسه برای الگوی «ادعا سپس ارسال» لازم است: اول ردیف با وضعیت «در حال
        ارسال» ثبت می‌شود، بعد ارسال انجام می‌شود، بعد وضعیت به‌روز می‌شود.
        """
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO outbox (created_at, session_id, kind, audience, "
                "customer_id, phone, message, status, provider, dry_run) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (time.time(), session_id, kind, audience, customer_id, phone,
                 message, status, provider, int(dry_run)),
            )
            return int(cur.lastrowid or 0)

    def update_outbox_status(self, outbox_id: int, *, status: str,
                             provider: str | None = None) -> None:
        """به‌روزرسانی وضعیت یک ردیف outbox پس از تلاش برای ارسال."""
        with self._conn() as c:
            if provider is None:
                c.execute("UPDATE outbox SET status = ? WHERE id = ?", (status, outbox_id))
            else:
                c.execute("UPDATE outbox SET status = ?, provider = ? WHERE id = ?",
                          (status, provider, outbox_id))

    def list_outbox(self, limit: int = 50) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM outbox ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def outbox_exists_recent(self, *, kind: str, customer_id: str,
                             within_days: float = 7.0,
                             audience: str | None = None) -> bool:
        """جلوگیری از ثبت/ارسال تکراری برای یک مشتری در بازه‌ی اخیر."""
        cutoff = time.time() - within_days * 86400
        q = ("SELECT 1 FROM outbox WHERE kind=? AND customer_id=? AND created_at>? ")
        vals: list = [kind, customer_id, cutoff]
        if audience is not None:
            q += "AND audience=? "
            vals.append(audience)
        with self._conn() as c:
            return c.execute(q + "LIMIT 1", vals).fetchone() is not None

    # ------------------------------------------------ کلید/مقدارِ کوچکِ برنامه
    def get_meta(self, key: str) -> str | None:
        """مقدار یک کلید متادیتا (مثل «آخرین اجرای موفق زمان‌بند»)."""
        with self._conn() as c:
            row = c.execute("SELECT value FROM app_meta WHERE key = ?", (key,)).fetchone()
        return None if row is None else row["value"]

    def set_meta(self, key: str, value: str) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO app_meta (key, value, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
                "updated_at = excluded.updated_at",
                (key, value, time.time()),
            )

    def recent_contact_customer_ids(self, within_days: float = 14.0) -> set[str]:
        """مشتریانی که در بازه‌ی اخیر **واقعاً** پیامی گرفته‌اند.

        `outbox_exists_recent` برای بررسی تک‌نفره است؛ فیلتر «خستگی تماس» در
        موتور فرصت‌ها باید هزاران مشتری را یک‌جا بررسی کند و صدا زدن آن در حلقه
        یعنی هزاران رفت‌وبرگشت.

        **`dry_run = 0` شرطِ لازم است.** پیش‌تر این شرط نبود و باگ می‌ساخت: یک
        پیش‌نمایشِ آزمایشی هم ردیف outbox می‌نویسد، پس گرفتنِ یک پیش‌نمایش کافی
        بود تا مشتری ۱۴ روز «خسته از تماس» شمرده شود و فرصت‌هایش ساخته نشود —
        در حالی که هیچ پیامی برایش نرفته بود.

        این پرسش با پرسشِ `outbox_exists_recent` تفاوت دارد و عمداً پاسخش هم
        متفاوت است: آن یکی می‌پرسد «آیا این یادآوری را قبلاً ثبت کرده‌ایم؟»
        (ثبتِ آزمایشی هم ثبت است و باید مانع ثبت دوباره شود)، این یکی می‌پرسد
        «آیا این مشتری چیزی دریافت کرده؟».
        """
        cutoff = time.time() - within_days * 86400
        with self._conn() as c:
            rows = c.execute(
                "SELECT DISTINCT customer_id FROM outbox "
                "WHERE customer_id IS NOT NULL AND created_at > ? AND dry_run = 0",
                (cutoff,),
            ).fetchall()
        return {str(r["customer_id"]) for r in rows}


# نمونه‌ی سراسری (تک-پروسه)
store = PersistentStore()

__all__ = ["PersistentStore", "SessionRecord", "JobRecord", "store"]
