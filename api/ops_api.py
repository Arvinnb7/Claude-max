"""مسیرهای عملیاتی: دیدنِ کارهای زمان‌بندی‌شده و صفِ مرده (§۲۸).

## چرا این مسیرها لازم‌اند

§۲۸ می‌گوید «Dead-letter/failure visibility» و «Expose job status in the
UI/API». صفِ مرده‌ای که فقط در دیتابیس باشد، دیده نمی‌شود — و شکستی که دیده
نشود، تکرار می‌شود. این فایل همان دیده‌شدن است.
"""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

from mktcore.jobs import (  # noqa: E402
    SCHEDULED_JOBS,
    dead_letter_runs,
    job_by_name,
    recent_runs,
    retry_run,
    run_job,
)
from mktcore.security import require_token  # noqa: E402

from .observability import current_request_id, metrics_snapshot  # noqa: E402

router = APIRouter(prefix="/api/v1/ops", tags=["ops"])


@router.get("/jobs")
def list_jobs(limit: int = Query(default=50, ge=1, le=200)) -> dict:
    """فهرستِ کارها و آخرین اجراهایشان."""
    runs = recent_runs(limit=limit)
    latest: dict[str, dict] = {}
    for run in runs:
        latest.setdefault(run["job_name"], run)

    return {
        "jobs": [
            {
                "name": job.name,
                "title_fa": job.title_fa,
                "hour": job.hour,
                "interval_hours": job.interval_hours,
                "max_attempts": job.max_attempts,
                "last_run": latest.get(job.name),
            }
            for job in SCHEDULED_JOBS
        ],
        "recent_runs": runs,
    }


@router.get("/jobs/dead-letter")
def list_dead_letter(limit: int = Query(default=50, ge=1, le=200)) -> dict:
    """کارهایی که تلاش‌هایشان تمام شد و کسی باید ببیندشان."""
    rows = dead_letter_runs(limit=limit)
    return {
        "count": len(rows),
        "runs": rows,
        "note_fa": (
            "این کارها بعد از تمام‌شدنِ تلاش‌ها شکست خوردند و **خودبه‌خود دوباره "
            "اجرا نمی‌شوند**. علت را رفع کنید و بعد «تلاش دوباره» را بزنید."
        ) if rows else "صفِ مرده خالی است.",
    }


@router.post("/jobs/{job_name}/run", dependencies=[Depends(require_token)])
def run_now(job_name: str) -> dict:
    """اجرای دستیِ یک کار — برای راه‌اندازی و رفعِ اشکال.

    شناسه‌ی همبستگی **همان شناسه‌ی این درخواست** است، پس لاگِ درخواست و لاگِ
    کارِ پایین‌دستی با یک رشته به هم وصل می‌شوند (§۳۲).
    """
    if job_by_name(job_name) is None:
        raise HTTPException(
            status_code=404,
            detail=f"کاری با نام «{job_name}» ثبت نشده است.",
        )
    return run_job(job_name, correlation_id=current_request_id())


@router.post("/jobs/runs/{run_id}/retry", dependencies=[Depends(require_token)])
def retry(run_id: int) -> dict:
    """تلاشِ دوباره روی یک ردیفِ صفِ مرده. شمارنده از نو شروع می‌شود."""
    result = retry_run(run_id)
    if result.get("status") == "not_found":
        raise HTTPException(status_code=404, detail="چنین اجرایی ثبت نشده است.")
    return result


@router.get("/metrics")
def metrics() -> dict:
    """شمارنده‌های سبکِ درخواست‌ها (§۳۲).

    عمداً JSON است نه قالبِ Prometheus: اینجا هیچ Prometheusی نصب نیست و
    افزودنِ وابستگی برای چیزی که کسی جمعش نمی‌کند، سربارِ بی‌مصرف است. اگر
    روزی لازم شد، ترجمه‌ی این ساختار به قالبِ متنی چند خط است.
    """
    return metrics_snapshot()
