"""اجرای کارهای طولانی در پس‌زمینه (ThreadPool) با ثبت پیشرفت در SQLite.

هر job یک تابع `fn(progress)` است که `progress(pct, stage_fa)` را برای گزارش
مرحله صدا می‌زند و در پایان مقدار result (JSON-سریال‌پذیر) برمی‌گرداند. وضعیت در
جدول `jobs` ذخیره می‌شود تا فرانت با polling پیشرفت را دنبال کند و پس از
ری‌استارت سرور، jobهای ناتمام با پیام شفاف خطا علامت بخورند.
"""

from __future__ import annotations

import logging
import traceback
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from .persistence import store

logger = logging.getLogger("mktcore.jobs")

# دو کار همزمان کافی است؛ کارها CPU-سنگین‌اند (pandas) و تک-پروسه‌ایم.
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="job")

ProgressFn = Callable[[float, str], None]


def submit_job(kind: str, fn: Callable[[ProgressFn], Any],
               session_id: str | None = None) -> str:
    """ثبت و اجرای یک job؛ شناسه‌ی job را فوراً برمی‌گرداند."""
    jid = store.create_job(kind, session_id)

    def _progress(pct: float, stage: str) -> None:
        store.update_job(jid, status="running",
                         progress=max(0.0, min(100.0, pct)), stage=stage)

    def _run() -> None:
        store.update_job(jid, status="running", progress=1, stage="شروع پردازش")
        try:
            result = fn(_progress)
            store.update_job(jid, status="done", progress=100, stage="پایان",
                             result=result)
        except _JobError as e:
            logger.warning("job %s(%s) failed: %s", kind, jid, e)
            store.update_job(jid, status="error", error=str(e))
        except Exception as e:  # noqa: BLE001 - مرز job؛ خطا باید ثبت شود نه crash
            logger.error("job %s(%s) crashed: %s\n%s", kind, jid, e,
                         traceback.format_exc())
            store.update_job(
                jid, status="error",
                error=f"خطای غیرمنتظره ({type(e).__name__}): {e}",
            )

    _executor.submit(_run)
    return jid


class _JobError(Exception):
    """خطای کاربرپسند داخل job (پیام فارسی مستقیم به کاربر می‌رسد)."""


JobError = _JobError

__all__ = ["submit_job", "JobError", "ProgressFn"]
