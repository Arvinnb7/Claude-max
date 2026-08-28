"""زمان‌بند خودکار: اسکن روزانه‌ی چرخه‌ی خرید و ثبت/ارسال یادآوری‌ها.

منطق اصلی (`run_cycle_scan`) تابعی خالص و تست‌پذیر است؛ APScheduler فقط آن را
سر ساعت مقرر صدا می‌زند. ارسال واقعی پیامک تنها وقتی انجام می‌شود که هم
`MKT_AUTO_SMS=1` و هم پنل پیامکی پیکربندی شده باشد؛ در غیر این صورت یادآوری‌ها
به‌صورت «آزمایشی/آماده» در outbox ثبت می‌شوند.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from mktcore.config import get_settings
from mktcore.contact.register import load_gate
from mktcore.execution import render_messages, send_campaign
from mktcore.execution.audience import build_audience
from mktcore.jobs import SCHEDULED_JOBS, run_job

from .persistence import store

logger = logging.getLogger("mktcore.scheduler")

_scheduler: Any | None = None  # گارد double-start

CYCLE_KIND = "cycle_notification"
AUDIENCE_KEY = "چرخه_عقب‌افتاده"
# کلید «آخرین اجرای موفق» — مبنای جبران اجرای ازدست‌رفته پس از ری‌استارت
LAST_SCAN_KEY = "scheduler.cycle_scan.last_run_date"


def run_cycle_scan(*, limit: int = 200, dedupe_days: float = 7.0) -> dict:
    """اسکن اعلان‌های چرخه روی جدیدترین نشستِ تحلیل‌شده و ثبت در outbox.

    Returns:
        خلاصه‌ی فارسی‌پذیر: نشست، تعداد بررسی/ثبت/ارسال و حالت ارسال.
    """
    settings = get_settings()
    sid = store.latest_session_with_analysis()
    if sid is None:
        return {"status": "no_session", "پیام": "هیچ نشست تحلیل‌شده‌ای برای اسکن وجود ندارد."}

    bundle = store.load_bundle(sid)
    clean = store.load_clean(sid)
    if bundle is None or clean is None:
        return {"status": "no_data", "پیام": "داده‌ی تحلیل نشست یافت نشد."}

    recipients = build_audience(bundle, AUDIENCE_KEY, df=clean, limit=limit)
    # حذف مواردی که اخیراً برایشان یادآوری ثبت شده (جلوگیری از اسپم روزانه).
    # این dedupe عمداً `dry_run` را هم می‌شمارد: پرسشش «آیا قبلاً ثبت کرده‌ایم؟»
    # است، نه «آیا مشتری چیزی گرفته؟».
    fresh = [r for r in recipients
             if not store.outbox_exists_recent(kind=CYCLE_KIND, customer_id=r.customer_id,
                                               within_days=dedupe_days)]

    # دروازه‌ی مجوز تماس: انصراف و عضویت در گروه کنترل. خستگی تماس اینجا داده
    # نمی‌شود چون همان dedupe بالا کارش را می‌کند و دو بار حساب کردنش یعنی
    # پنجره‌ی مؤثر ۱۴ روز شود، نه ۷ روزِ مستند.
    gate = load_gate()
    screened = gate.partition(
        fresh, key=lambda r: r.customer_id, phone=lambda r: r.phone,
    )
    fresh = screened.allowed

    real_send = settings.mkt_auto_sms and settings.sms_configured
    messages = render_messages(settings.mkt_cycle_sms_template, fresh)

    # الگوی «ادعا سپس ارسال»: پیش‌تر اول ارسال می‌شد و بعد ثبت؛ مرگ پروسه بین آن
    # دو یعنی پیامک رفته ولی ثبت نشده، و اجرای فردا **دوباره** می‌فرستاد. حالا
    # ردیف با وضعیت «در حال ارسال» ادعا می‌شود، پس dedupe اجرای بعدی آن را
    # می‌بیند حتی اگر به‌روزرسانی وضعیت هرگز انجام نشود.
    claimed: list[tuple[int, str]] = []
    for m in messages:
        outbox_id = store.add_outbox(
            kind=CYCLE_KIND, session_id=sid, audience=AUDIENCE_KEY,
            customer_id=m.customer_id, phone=m.phone, message=m.text,
            status="در حال ارسال" if real_send else "آماده (آزمایشی)",
            provider=settings.mkt_sms_provider if real_send else "dry-run",
            dry_run=not real_send,
        )
        claimed.append((outbox_id, m.customer_id))

    sent = 0
    if real_send and messages:
        result = send_campaign(
            messages, provider=settings.mkt_sms_provider,
            api_key=settings.kavenegar_api_key, sender=settings.mkt_sms_sender,
            dry_run=False,
        )
        sent = result.sent
        status_of = {d.get("مشتری"): d.get("وضعیت", "") for d in result.details}
        for outbox_id, customer_id in claimed:
            store.update_outbox_status(
                outbox_id, status=status_of.get(customer_id) or "ارسال شد",
            )

    store.set_meta(LAST_SCAN_KEY, _today_tehran().isoformat())
    summary = {
        "status": "ok", "session_id": sid,
        "بررسی‌شده": len(recipients), "ثبت‌شده": len(fresh), "ارسال_واقعی": sent,
        "حالت": "ارسال واقعی" if real_send else "آزمایشی (بدون ارسال)",
        **screened.to_dict(),
    }
    logger.info("cycle scan: %s", summary)
    return summary


def catch_up_missed_scan() -> dict:
    """اجرای جبرانیِ اسکنِ ازدست‌رفته پس از ری‌استارت.

    زمان‌بند روی `MemoryJobStore` است، پس اگر سرور در ساعت اجرا خاموش باشد آن
    نوبت **بی‌صدا** حذف می‌شود و کسی خبردار نمی‌شود. اینجا آخرین اجرای موفق
    خوانده می‌شود و اگر امروز اجرا نشده و ساعتِ برنامه گذشته، همان‌جا جبران
    می‌شود. اجرای اضافه بی‌ضرر است چون dedupe اجازه‌ی پیام تکراری نمی‌دهد.
    """
    settings = get_settings()
    if not settings.mkt_scheduler_enable:
        return {"status": "disabled"}

    today = _today_tehran()
    last = store.get_meta(LAST_SCAN_KEY)
    if last == today.isoformat():
        return {"status": "already_ran", "تاریخ": last}
    if _now_tehran().hour < settings.mkt_schedule_hour:
        return {"status": "not_due_yet", "ساعت_برنامه": settings.mkt_schedule_hour}

    logger.info("اجرای جبرانی اسکن چرخه (آخرین اجرا: %s)", last or "هرگز")
    return run_cycle_scan()


def _now_tehran() -> datetime:
    try:
        return datetime.now(ZoneInfo("Asia/Tehran"))
    except Exception:  # noqa: BLE001 - نبود tzdata نباید زمان‌بند را بشکند
        return datetime.now()


def _today_tehran() -> date:
    return _now_tehran().date()


def start_scheduler() -> bool:
    """راه‌اندازی زمان‌بند (یک‌بار در هر پروسه). True اگر فعال شد."""
    global _scheduler
    settings = get_settings()
    if not settings.mkt_scheduler_enable or _scheduler is not None:
        return _scheduler is not None
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
    except ImportError:
        logger.warning("apscheduler نصب نیست؛ زمان‌بند غیرفعال است.")
        return False

    sched = BackgroundScheduler(timezone="Asia/Tehran")
    sched.add_job(
        lambda: run_cycle_scan(), "cron", hour=settings.mkt_schedule_hour, minute=0,
        id="cycle-scan", replace_existing=True,
    )
    sched.add_job(store.run_retention, "interval", hours=6, id="session-cleanup",
                  replace_existing=True)
    _register_pipeline_jobs(sched)
    sched.start()
    _scheduler = sched
    logger.info(
        "scheduler started (cycle scan @ %02d:00 Tehran, %s کار خط لوله)",
        settings.mkt_schedule_hour, len(SCHEDULED_JOBS),
    )
    return True


def _register_pipeline_jobs(sched: Any) -> None:
    """ثبتِ شش کارِ §۲۸ روی زمان‌بند.

    هر کار از راهِ `run_job` صدا زده می‌شود، نه مستقیم — یعنی همان‌جا ردیفِ
    اجرا، تلاشِ دوباره و صف مرده را می‌گیرد. صدا زدنِ مستقیمِ تابع یعنی شکستش
    فقط یک خط لاگ باشد، که دقیقاً مشکلِ امروز است.

    دقیقه‌ها عمداً پخش شده‌اند: پنج کار سرِ دقیقه‌ی صفر یعنی پنج تراکنشِ سنگین
    روی یک فایل SQLite در یک لحظه.
    """
    for index, job in enumerate(SCHEDULED_JOBS):
        name = job.name
        if job.interval_hours is not None:
            sched.add_job(
                _make_runner(name), "interval", hours=job.interval_hours,
                id=f"job-{name}", replace_existing=True,
            )
            continue
        sched.add_job(
            _make_runner(name), "cron", hour=job.hour, minute=(index * 7) % 60,
            id=f"job-{name}", replace_existing=True,
        )


def _make_runner(name: str):
    """بستنِ نامِ کار در یک closure. بدون این، همه‌ی jobها آخرین نام را می‌گیرند."""
    return lambda: run_job(name)


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def scheduler_status() -> dict:
    settings = get_settings()
    next_run = None
    if _scheduler is not None:
        job = _scheduler.get_job("cycle-scan")
        if job and job.next_run_time:
            next_run = job.next_run_time.isoformat()
    return {
        "enabled": settings.mkt_scheduler_enable,
        "running": _scheduler is not None,
        "next_run": next_run,
        "schedule_hour": settings.mkt_schedule_hour,
        "auto_sms": settings.mkt_auto_sms,
        "sms_configured": settings.sms_configured,
        "last_run_date": store.get_meta(LAST_SCAN_KEY),
        "pipeline_jobs": [
            {
                "name": job.name,
                "title_fa": job.title_fa,
                "hour": job.hour,
                "interval_hours": job.interval_hours,
                "max_attempts": job.max_attempts,
                "next_run": _next_run(f"job-{job.name}"),
            }
            for job in SCHEDULED_JOBS
        ],
    }


def _next_run(job_id: str) -> str | None:
    if _scheduler is None:
        return None
    job = _scheduler.get_job(job_id)
    return job.next_run_time.isoformat() if job and job.next_run_time else None


__all__ = [
    "catch_up_missed_scan",
    "run_cycle_scan",
    "scheduler_status",
    "start_scheduler",
    "stop_scheduler",
]
