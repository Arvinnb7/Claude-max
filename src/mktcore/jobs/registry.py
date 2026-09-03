"""فهرستِ کارهای زمان‌بندی‌شده — §۲۸.

## چه چیزی اینجا هست و چه چیزی عمداً نیست

§۲۸ دوازده کار می‌خواهد. شش‌تایشان (کشف فایل، تجزیه و اعتبارسنجی، ثبت canonical
و آشتی، حلِ هویت و محصول، محاسبه‌ی افزایشیِ ویژگی‌ها) از پیش وجود دارند و
**رویدادمحور**اند: با آمدنِ فایل اجرا می‌شوند، نه سرِ ساعت. زمان‌بندی‌کردنشان
یعنی همان کار دو بار انجام شود. آنچه اینجا اضافه می‌شود، شش کارِ باقی‌مانده است
که هیچ راه‌اندازِ خودکاری نداشتند:

| کار | چرا نبودش مشکل بود |
|---|---|
| تولید روزانه‌ی فرصت | فقط با آپلودِ فایل اجرا می‌شد؛ یک هفته بدون فایل، یعنی صندوقِ ثابت |
| انقضا | فرصتِ از تاریخ‌گذشته «باز» می‌ماند و کاربر رویش وقت می‌گذاشت |
| تطبیق نتیجه | نتیجه‌ی کمپین فقط با فایلِ بعدی به‌روز می‌شد |
| تحلیل کمپین (جدول اثر) | همان |
| بازآموزی مدل | هیچ‌وقت خودکار نبود؛ مدل با گذشتِ زمان کهنه می‌شد |
| پایش انحراف | فقط وقتی کسی صفحه را باز می‌کرد سنجیده می‌شد |

## قاعده‌ای که هیچ‌کدام نمی‌شکنند

**هیچ کاری مدل را فعال نمی‌کند.** بازآموزی فقط مدعی می‌سازد؛ فعال‌سازی تصمیمِ
انسان است (`POST /api/v1/models/{id}/promote`). کارِ خودکاری که مدل را عوض کند،
همان چیزی است که قاعده‌ی قهرمان/مدعی برای جلوگیری از آن ساخته شده.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("mktcore.jobs.registry")

__all__ = [
    "SCHEDULED_JOBS",
    "JobSkipped",
    "ScheduledJob",
    "job_by_name",
    "job_names",
    "register_job",
    "unregister_job",
]


class JobSkipped(Exception):
    """شرطِ اجرا برقرار نبود. **شکست نیست** و تلاشِ دوباره نمی‌گیرد.

    مثال: هنوز هیچ تحلیلی وجود ندارد، یا هیچ مدلِ فعالی برای سنجشِ انحراف
    نیست. سه بار تلاش‌کردن برای چیزی که شرطش برقرار نیست، فقط صف مرده را با
    شکستِ دروغین پر می‌کند.
    """


@dataclass(frozen=True)
class ScheduledJob:
    name: str
    title_fa: str
    run: Callable[..., Any]
    # زمان‌بندی به‌سبک cron؛ `hour=None` یعنی با فاصله‌ی ساعتی اجرا شود
    hour: int | None = None
    interval_hours: float | None = None
    max_attempts: int = 3

    def __call__(self, **kwargs: Any) -> Any:
        return self.run(**kwargs)


# ------------------------------------------------------------------ کارها
def _latest_analysis() -> tuple[Any, Any]:
    """آخرین تحلیلِ ذخیره‌شده. نبودش «رد شدن» است، نه خطا.

    واردکردنِ درون-تابعیِ لایه‌ی نشست عمدی است و همان الگویی است که
    `opportunities/engine.py::_recently_contacted` به‌کار می‌برد: هسته در زمانِ
    import به لایه‌ی برنامه وابسته نمی‌شود.
    """
    from api.persistence import store

    session_id = store.latest_session_with_analysis()
    if session_id is None:
        raise JobSkipped("هیچ نشست تحلیل‌شده‌ای وجود ندارد؛ چیزی برای پردازش نیست.")
    bundle = store.load_bundle(session_id)
    clean = store.load_clean(session_id)
    if bundle is None or clean is None:
        raise JobSkipped(
            "داده‌ی سنگینِ آخرین نشست بایگانی شده است؛ برای اجرای دوباره فایل "
            "را دوباره تحلیل کنید."
        )
    return bundle, clean


def _job_opportunity_generation(*, correlation_id: str | None = None) -> dict:
    from mktcore.db.leases import LeaseBusyError
    from mktcore.opportunities import run_opportunity_engine

    bundle, clean = _latest_analysis()
    try:
        result = run_opportunity_engine(bundle, clean, session_id=None)
    except LeaseBusyError as busy:
        # اجرای دیگری در جریان است. تلاشِ دوباره لازم نیست: آن اجرا همین کار را
        # می‌کند.
        raise JobSkipped(busy.reason_fa) from busy
    if result is None:
        raise JobSkipped("کسب‌وکاری برای اجرا وجود ندارد.")
    return result.to_dict()


def _job_opportunity_expiration(*, correlation_id: str | None = None) -> dict:
    from mktcore.opportunities import expire_overdue_opportunities

    return expire_overdue_opportunities()


def _job_outcome_matching(*, correlation_id: str | None = None) -> dict:
    from mktcore.campaigns import compute_campaign_outcomes

    return compute_campaign_outcomes()


def _job_campaign_analysis(*, correlation_id: str | None = None) -> dict:
    from mktcore.uplift import refresh_uplift

    return refresh_uplift()


def _job_model_retraining(*, correlation_id: str | None = None) -> dict:
    """آموزشِ مدعی برای هر مدلِ ثبت‌شده. **هیچ‌کدام فعال نمی‌شوند.**"""
    from mktcore.ml.train import available_trainers, train_model

    trainers = available_trainers()
    if not trainers:
        raise JobSkipped("هیچ مدلی برای آموزش ثبت نشده است.")

    summary: dict[str, dict] = {}
    for key in trainers:
        try:
            run = train_model(key)
        except Exception as exc:  # noqa: BLE001 - شکستِ یک مدل نباید بقیه را ببندد
            logger.warning("بازآموزی «%s» شکست خورد: %s", key, exc)
            summary[key] = {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
            continue
        summary[key] = {
            "status": run.get("status"),
            "run_id": run.get("id"),
            "blocked_reason_fa": run.get("blocked_reason_fa"),
        }
    return {"trained": summary, "promoted": 0, "note_fa": "فعال‌سازی دستی است."}


def _job_drift_monitoring(*, correlation_id: str | None = None) -> dict:
    """سنجشِ انحراف برای مدل‌های **فعال**. بدون مدلِ فعال، «رد شد»."""
    import pandas as pd

    from mktcore.db.engine import session_scope
    from mktcore.db.lookup import resolve_business_id
    from mktcore.db.migrations import ensure_schema
    from mktcore.features.ledger_frame import load_line_frame
    from mktcore.features.point_in_time import (
        PointInTimeSpec,
        compute_point_in_time_features,
    )
    from mktcore.ml.drift import LEVEL_SHIFTED, LEVEL_WARN, measure_drift
    from mktcore.ml.registry import MODEL_KEYS, promoted_run, run_to_dict

    # این تنها کاری است که مستقیم به دفتر کل می‌زند بی‌آنکه از راهِ تابعی
    # برود که خودش طرح‌واره را می‌سازد؛ روی نصبِ نو، جدول هنوز وجود ندارد.
    ensure_schema()
    with session_scope() as session:
        business_id = resolve_business_id(session, "default")
        if business_id is None:
            raise JobSkipped("کسب‌وکاری وجود ندارد.")
        promoted = {
            key: run_to_dict(run, with_model=True)
            for key in MODEL_KEYS
            if (run := promoted_run(session, business_id, key)) is not None
        }
        lines = load_line_frame(session, business_id)

    if not promoted:
        raise JobSkipped("هیچ مدلِ فعالی وجود ندارد؛ انحرافی برای سنجش نیست.")
    if lines.empty:
        raise JobSkipped("دفتر کل خالی است؛ جمعیتی برای مقایسه نیست.")

    exclusive_end = (
        pd.Timestamp(str(lines["line_date"].max())) + pd.Timedelta(days=1)
    ).date().isoformat()

    report: dict[str, dict] = {}
    alerts: list[dict] = []
    for key, payload in promoted.items():
        features = compute_point_in_time_features(
            lines[lines["line_date"] < exclusive_end],
            PointInTimeSpec(
                as_of=exclusive_end,
                observation_days=(payload.get("params") or {}).get("observation_days"),
            ),
        )
        measured = measure_drift(
            baseline=payload.get("drift_baseline"),
            current_features=features,
            calibration_bins=(payload.get("calibration") or {}).get("reliability_bins"),
        )
        report[key] = {
            "run_id": payload["id"],
            "measured": measured.get("measured"),
            "level": measured.get("level"),
            "note_fa": measured.get("note_fa"),
        }
        # ⚠️ تا پیش از این، شرط با رشته‌های «زیاد»/«high» مقایسه می‌شد که هیچ‌جا
        # تولید نمی‌شوند (سطح‌ها «هشدار» و «تغییر معنادار»اند) — هشدارِ §۲۹.۷ در
        # زمان‌بند هرگز شلیک نمی‌شد. مقایسه با خودِ ثابت‌ها.
        level = measured.get("level")
        if level == LEVEL_SHIFTED:
            alerts.append({
                "model_key": key, "run_id": payload["id"], "level": level,
                "note_fa": measured.get("note_fa"),
            })
            logger.warning(
                "انحرافِ معنادار در مدل «%s» (اجرای %s): %s",
                key, payload["id"], measured.get("note_fa"),
            )
        elif level == LEVEL_WARN:
            logger.info(
                "انحرافِ هشداری در مدل «%s» (اجرای %s): %s",
                key, payload["id"], measured.get("note_fa"),
            )
    return {"models": report, "alerts": alerts}


def _job_retry_sweep(*, correlation_id: str | None = None) -> dict:
    """جاروکشِ تلاش‌های سررسیدشده + هرسِ دفترِ اجرا. خودش تلاشِ دوباره نمی‌گیرد."""
    from mktcore.jobs.runner import sweep_due_retries

    return sweep_due_retries()


SCHEDULED_JOBS: tuple[ScheduledJob, ...] = (
    ScheduledJob(
        name="opportunity_generation",
        title_fa="تولید روزانه‌ی فرصت‌ها",
        run=_job_opportunity_generation,
        hour=7,
    ),
    ScheduledJob(
        name="opportunity_expiration",
        title_fa="انقضای فرصت‌های از تاریخ‌گذشته",
        run=_job_opportunity_expiration,
        hour=6,
    ),
    ScheduledJob(
        name="outcome_matching",
        title_fa="تطبیق نتیجه‌ی کمپین‌ها",
        run=_job_outcome_matching,
        hour=5,
    ),
    ScheduledJob(
        name="campaign_analysis",
        title_fa="به‌روزرسانی جدولِ اثر آموخته‌شده",
        run=_job_campaign_analysis,
        hour=5,
    ),
    ScheduledJob(
        name="model_retraining",
        title_fa="بازآموزی مدل‌ها (فقط مدعی)",
        run=_job_model_retraining,
        hour=3,
        # آموزش گران است؛ سه بار تلاشِ پشت‌سرهم فقط CPU می‌سوزاند
        max_attempts=2,
    ),
    ScheduledJob(
        name="drift_monitoring",
        title_fa="پایش انحرافِ مدل‌های فعال",
        run=_job_drift_monitoring,
        hour=4,
    ),
    ScheduledJob(
        name="retry_sweep",
        title_fa="جاروکشِ تلاش‌ها و هرسِ دفترِ اجرا",
        run=_job_retry_sweep,
        interval_hours=0.25,
        max_attempts=1,
    ),
)

_BY_NAME: dict[str, ScheduledJob] = {job.name: job for job in SCHEDULED_JOBS}


def register_job(job: ScheduledJob) -> None:
    """ثبتِ کارِ تازه در زمانِ اجرا — مثل `register_trainer` برای مدل‌ها."""
    _BY_NAME[job.name] = job


def unregister_job(name: str) -> None:
    _BY_NAME.pop(name, None)


def job_by_name(name: str) -> ScheduledJob | None:
    return _BY_NAME.get(name)


def job_names() -> tuple[str, ...]:
    return tuple(_BY_NAME)
