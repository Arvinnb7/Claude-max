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
"""


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
        self.data_dir = Path(data_dir or settings.mkt_data_dir)
        self.sessions_dir = self.data_dir / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "app.db"
        self.ttl_seconds = settings.mkt_session_ttl_hours * 3600
        self._lock = threading.Lock()
        self._frame_cache: dict[tuple[str, str], Any] = {}
        self._init_db()

    # ---------------------------------------------------------------- پایه
    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=15000")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._conn() as c:
            c.executescript(_SCHEMA)

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
        if time.time() - row["created_at"] > self.ttl_seconds:
            self.delete_session(sid)
            return None
        return SessionRecord(
            id=row["id"],
            created_at=row["created_at"],
            filename=row["filename"],
            columns_payload=_uj(row["columns_json"]),
            mapping=_uj(row["mapping_json"]),
            analysis=_uj(row["analysis_json"]),
            strategy=_uj(row["strategy_json"]),
            campaign=_uj(row["campaign_json"]),
        )

    def delete_session(self, sid: str) -> None:
        self._cache_drop(sid)
        with self._conn() as c:
            c.execute("DELETE FROM sessions WHERE id = ?", (sid,))
        shutil.rmtree(self._sdir(sid), ignore_errors=True)

    def cleanup_expired(self) -> int:
        """حذف نشست‌های منقضی؛ تعداد حذف‌شده را برمی‌گرداند."""
        cutoff = time.time() - self.ttl_seconds
        with self._conn() as c:
            rows = c.execute(
                "SELECT id FROM sessions WHERE created_at < ?", (cutoff,)
            ).fetchall()
        for r in rows:
            self.delete_session(r["id"])
        return len(rows)

    def latest_session_with_analysis(self) -> str | None:
        """جدیدترین نشستی که تحلیل کامل دارد (برای زمان‌بند)."""
        with self._conn() as c:
            row = c.execute(
                "SELECT id, created_at FROM sessions "
                "WHERE analysis_json IS NOT NULL ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        if row is None or time.time() - row["created_at"] > self.ttl_seconds:
            return None
        return row["id"]

    def _set_field(self, sid: str, column: str, value) -> None:
        with self._conn() as c:
            c.execute(f"UPDATE sessions SET {column} = ? WHERE id = ?", (_j(value), sid))

    def set_columns_payload(self, sid: str, payload: dict) -> None:
        self._set_field(sid, "columns_json", payload)

    def set_mapping(self, sid: str, mapping: dict) -> None:
        self._set_field(sid, "mapping_json", mapping)

    def set_analysis(self, sid: str, analysis_payload: dict) -> None:
        self._set_field(sid, "analysis_json", analysis_payload)

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
                   provider: str | None = None, dry_run: bool = True) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO outbox (created_at, session_id, kind, audience, "
                "customer_id, phone, message, status, provider, dry_run) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (time.time(), session_id, kind, audience, customer_id, phone,
                 message, status, provider, int(dry_run)),
            )

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


# نمونه‌ی سراسری (تک-پروسه)
store = PersistentStore()

__all__ = ["PersistentStore", "SessionRecord", "JobRecord", "store"]
