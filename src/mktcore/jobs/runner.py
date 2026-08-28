"""اجرای کارِ زمان‌بندی‌شده با تلاشِ دوباره، فاصله‌ی فزاینده، و صف مرده.

## سه قاعده‌ی این ماژول

1. **شکستِ گذرا نباید کار را بکُشد.** شبکه‌ی پنل پیامکی، قفلِ لحظه‌ای دیتابیس،
   یا فایلِ نیمه‌نوشته — همه‌شان با تلاشِ دوباره حل می‌شوند.
2. **شکستِ نهایی نباید ناپدید شود.** بعد از تمام‌شدن تلاش‌ها، ردیف در وضعیت
   `dead_letter` می‌ماند تا در فهرست **دیده** شود. شکستی که کسی نبیند، تکرار
   می‌شود.
3. **«شرطش برقرار نبود» شکست نیست.** اگر هنوز هیچ تحلیلی وجود ندارد، بازآموزی
   مدل نباید سه بار تلاش کند و بعد بمیرد؛ باید بگوید «رد شد» و دلیلش را
   بنویسد.

## چرا تلاشِ دوباره با `sleep` انجام نمی‌شود

`time.sleep(240)` درونِ thread زمان‌بند، همان thread را برای چهار دقیقه
می‌بندد و با ری‌استارتِ سرور هم از بین می‌رود. به‌جایش زمانِ تلاشِ بعدی در
`next_retry_at` **نوشته** می‌شود و یک کارِ جاروکش آن را برمی‌دارد — پس
تلاشِ دوباره از ری‌استارت هم جان سالم به‌در می‌برد (§۲۸: «Safe restart»).
"""

from __future__ import annotations

import json
import logging
import traceback
import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from mktcore.db.base import now_ts
from mktcore.db.engine import session_scope, write_lock
from mktcore.db.migrations import ensure_schema
from mktcore.db.models import JobRun
from mktcore.jobs.registry import JobSkipped, job_by_name

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger("mktcore.jobs")

# ۶۰ ثانیه، بعد ۱۲۰، بعد ۲۴۰. عمداً بدون تصادفی‌سازی تا تست بتواند دقیقاً
# همین عددها را ادعا کند؛ در این مقیاس، هجومِ هم‌زمان مسئله نیست.
BACKOFF_BASE_SECONDS = 60.0

__all__ = [
    "BACKOFF_BASE_SECONDS",
    "backoff_seconds",
    "dead_letter_runs",
    "recent_runs",
    "retry_run",
    "run_job",
    "sweep_due_retries",
]


def backoff_seconds(attempt: int) -> float:
    """فاصله‌ی تلاشِ بعدی. `attempt` شماره‌ی تلاشی است که **شکست خورد**."""
    return BACKOFF_BASE_SECONDS * (2 ** max(0, attempt - 1))


def new_correlation_id() -> str:
    return uuid.uuid4().hex[:16]


def run_job(
    job_name: str,
    *,
    correlation_id: str | None = None,
    attempt: int = 1,
    run_id: int | None = None,
    db_path: Path | None = None,
) -> dict:
    """یک تلاشِ اجرا. همیشه خلاصه برمی‌گرداند؛ هرگز خطا پرت نمی‌کند.

    خطا پرت‌نکردن عمدی است: فراخوانِ این تابع معمولاً thread زمان‌بند است و
    خطای فرارکرده آنجا فقط یک stack trace در لاگ می‌گذارد و هیچ ردی در دفتر.
    """
    ensure_schema(db_path)
    job = job_by_name(job_name)
    cid = correlation_id or new_correlation_id()

    if job is None:
        logger.error("کارِ ناشناخته: %s", job_name)
        return {"status": "unknown_job", "job_name": job_name, "correlation_id": cid}

    row_id = _open_run(
        job_name, cid, attempt=attempt, max_attempts=job.max_attempts,
        run_id=run_id, db_path=db_path,
    )
    logger.info(
        "کار «%s» تلاش %s/%s آغاز شد [cid=%s]",
        job_name, attempt, job.max_attempts, cid,
    )

    try:
        result = job.run(correlation_id=cid)
    except JobSkipped as skip:
        # «شرطش برقرار نبود» نتیجه است، نه خطا — و نباید تلاشِ دوباره بگیرد.
        return _finish(
            row_id, JobRun.STATUS_SKIPPED, note_fa=str(skip), db_path=db_path,
        )
    except Exception as exc:  # noqa: BLE001 - مرزِ کار؛ خطا باید ثبت شود نه crash
        return _fail(
            row_id, job_name, cid, exc,
            attempt=attempt, max_attempts=job.max_attempts, db_path=db_path,
        )

    return _finish(
        row_id, JobRun.STATUS_SUCCEEDED, result=result, db_path=db_path,
    )


def sweep_due_retries(*, now: float | None = None, db_path: Path | None = None) -> dict:
    """تلاش‌های سررسیدشده را دوباره اجرا می‌کند.

    خودش یک کارِ زمان‌بندی‌شده است. اگر خالی باشد، هیچ ردیفی نمی‌نویسد.
    """
    ensure_schema(db_path)
    moment = now_ts() if now is None else now

    with session_scope(db_path) as session:
        due = session.scalars(
            select(JobRun).where(
                JobRun.status == JobRun.STATUS_RETRY_SCHEDULED,
                JobRun.next_retry_at.isnot(None),
                JobRun.next_retry_at <= moment,
            ).order_by(JobRun.next_retry_at)
        ).all()
        pending = [
            (row.id, row.job_name, row.correlation_id, row.attempt + 1) for row in due
        ]

    outcomes: list[dict] = []
    for row_id, job_name, cid, attempt in pending:
        outcomes.append(
            run_job(
                job_name, correlation_id=cid, attempt=attempt,
                run_id=row_id, db_path=db_path,
            )
        )
    return {"retried": len(outcomes), "outcomes": outcomes}


def retry_run(run_id: int, *, db_path: Path | None = None) -> dict:
    """تلاشِ دستی روی یک ردیفِ صفِ مرده — شمارنده از نو شروع می‌شود.

    اپراتوری که علت را رفع کرده، نباید منتظرِ همان سه تلاشِ تمام‌شده بماند.
    """
    ensure_schema(db_path)
    with session_scope(db_path) as session:
        row = session.get(JobRun, run_id)
        if row is None:
            return {"status": "not_found", "id": run_id}
        job_name, cid = row.job_name, row.correlation_id
    return run_job(job_name, correlation_id=cid, attempt=1, run_id=run_id, db_path=db_path)


def recent_runs(*, limit: int = 50, db_path: Path | None = None) -> list[dict]:
    ensure_schema(db_path)
    with session_scope(db_path) as session:
        rows = session.scalars(
            select(JobRun).order_by(JobRun.started_at.desc()).limit(limit)
        ).all()
        return [_to_dict(row) for row in rows]


def dead_letter_runs(*, limit: int = 50, db_path: Path | None = None) -> list[dict]:
    """کارهایی که تلاش‌هایشان تمام شد. این فهرست، همان «دیده‌شدن» است."""
    ensure_schema(db_path)
    with session_scope(db_path) as session:
        rows = session.scalars(
            select(JobRun)
            .where(JobRun.status == JobRun.STATUS_DEAD_LETTER)
            .order_by(JobRun.started_at.desc())
            .limit(limit)
        ).all()
        return [_to_dict(row) for row in rows]


# ------------------------------------------------------------------ داخلی
def _open_run(
    job_name: str,
    correlation_id: str,
    *,
    attempt: int,
    max_attempts: int,
    run_id: int | None,
    db_path: Path | None,
) -> int:
    """ردیفِ اجرا را باز می‌کند. تلاشِ دوباره **همان ردیف** را به‌کار می‌برد.

    ردیفِ تازه به‌ازای هر تلاش، فهرست را با سه ردیفِ یک شکست پر می‌کند و
    «چند بار تلاش شد» را از دست می‌دهد.
    """
    with write_lock, session_scope(db_path) as session:
        row = session.get(JobRun, run_id) if run_id is not None else None
        if row is None:
            row = JobRun(job_name=job_name, correlation_id=correlation_id)
            session.add(row)
        row.status = JobRun.STATUS_RUNNING
        row.attempt = attempt
        row.max_attempts = max_attempts
        row.started_at = now_ts()
        row.finished_at = None
        row.next_retry_at = None
        session.flush()
        return row.id


def _finish(
    row_id: int,
    status: str,
    *,
    result: Any = None,
    note_fa: str | None = None,
    db_path: Path | None = None,
) -> dict:
    with write_lock, session_scope(db_path) as session:
        row = session.get(JobRun, row_id)
        row.status = status
        row.finished_at = now_ts()
        row.next_retry_at = None
        row.error_type = None
        row.error_text = None
        row.note_fa = note_fa
        row.result_json = _as_json(result)
        return _to_dict(row)


def _fail(
    row_id: int,
    job_name: str,
    correlation_id: str,
    exc: Exception,
    *,
    attempt: int,
    max_attempts: int,
    db_path: Path | None,
) -> dict:
    exhausted = attempt >= max_attempts
    delay = backoff_seconds(attempt)
    detail = f"{type(exc).__name__}: {exc}"

    with write_lock, session_scope(db_path) as session:
        row = session.get(JobRun, row_id)
        row.finished_at = now_ts()
        row.error_type = type(exc).__name__
        row.error_text = f"{detail}\n{traceback.format_exc()}"[:8000]
        if exhausted:
            row.status = JobRun.STATUS_DEAD_LETTER
            row.next_retry_at = None
            row.note_fa = (
                f"بعد از {attempt} تلاش شکست خورد و در صف مرده نشست. "
                f"آخرین خطا: {detail}"
            )
        else:
            row.status = JobRun.STATUS_RETRY_SCHEDULED
            row.next_retry_at = now_ts() + delay
            row.note_fa = (
                f"تلاش {attempt} از {max_attempts} شکست خورد؛ تلاش بعدی تا "
                f"{int(delay)} ثانیه‌ی دیگر. آخرین خطا: {detail}"
            )
        payload = _to_dict(row)

    if exhausted:
        logger.error(
            "کار «%s» بعد از %s تلاش در صف مرده نشست [cid=%s]: %s",
            job_name, attempt, correlation_id, detail,
        )
    else:
        logger.warning(
            "کار «%s» تلاش %s شکست خورد؛ تلاش بعدی تا %ss [cid=%s]: %s",
            job_name, attempt, int(delay), correlation_id, detail,
        )
    return payload


def _as_json(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return json.dumps({"repr": repr(value)[:2000]}, ensure_ascii=False)


def _to_dict(row: JobRun) -> dict:
    return {
        "id": row.id,
        "job_name": row.job_name,
        "correlation_id": row.correlation_id,
        "status": row.status,
        "attempt": row.attempt,
        "max_attempts": row.max_attempts,
        "started_at": row.started_at,
        "finished_at": row.finished_at,
        "next_retry_at": row.next_retry_at,
        "error_type": row.error_type,
        # متنِ کاملِ traceback در پاسخِ API نمی‌آید؛ خط اولش برای تشخیص کافی است
        "error_first_line": (row.error_text or "").splitlines()[0] if row.error_text else None,
        "note_fa": row.note_fa,
        "result": json.loads(row.result_json) if row.result_json else None,
    }
