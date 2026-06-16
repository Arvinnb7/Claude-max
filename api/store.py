"""ذخیره‌ی موقت در حافظه برای نشست‌های تحلیل (تک‌فرآیندی، توسعه)."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import pandas as pd


@dataclass
class Session:
    raw_df: pd.DataFrame
    created_at: float = field(default_factory=time.time)
    clean_df: pd.DataFrame | None = None
    bundle: Any = None
    strategy: Any = None
    campaign: Any = None


class SessionStore:
    """نگه‌داری نشست‌ها با انقضای ساده."""

    def __init__(self, ttl_seconds: int = 3600, max_sessions: int = 50) -> None:
        self.ttl = ttl_seconds
        self.max_sessions = max_sessions
        self._data: dict[str, Session] = {}

    def _evict(self) -> None:
        now = time.time()
        expired = [k for k, v in self._data.items() if now - v.created_at > self.ttl]
        for k in expired:
            self._data.pop(k, None)
        # محدودیت تعداد
        if len(self._data) > self.max_sessions:
            oldest = sorted(self._data.items(), key=lambda kv: kv[1].created_at)
            for k, _ in oldest[: len(self._data) - self.max_sessions]:
                self._data.pop(k, None)

    def create(self, raw_df: pd.DataFrame) -> str:
        self._evict()
        sid = uuid.uuid4().hex
        self._data[sid] = Session(raw_df=raw_df)
        return sid

    def get(self, sid: str) -> Session | None:
        return self._data.get(sid)


store = SessionStore()

__all__ = ["store", "Session", "SessionStore"]
