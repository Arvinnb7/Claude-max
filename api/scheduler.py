"""زمان‌بند خودکار: اسکن روزانه‌ی چرخه‌ی خرید و ثبت/ارسال یادآوری‌ها.

منطق اصلی (`run_cycle_scan`) تابعی خالص و تست‌پذیر است؛ APScheduler فقط آن را
سر ساعت مقرر صدا می‌زند. ارسال واقعی پیامک تنها وقتی انجام می‌شود که هم
`MKT_AUTO_SMS=1` و هم پنل پیامکی پیکربندی شده باشد؛ در غیر این صورت یادآوری‌ها
به‌صورت «آزمایشی/آماده» در outbox ثبت می‌شوند.
"""

from __future__ import annotations

import logging
from typing import Any

from mktcore.config import get_settings
from mktcore.execution import render_messages, send_campaign
from mktcore.execution.audience import build_audience

from .persistence import store

logger = logging.getLogger("mktcore.scheduler")

_scheduler: Any | None = None  # گارد double-start

CYCLE_KIND = "cycle_notification"
AUDIENCE_KEY = "چرخه_عقب‌افتاده"


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
    # حذف مواردی که اخیراً برایشان یادآوری ثبت شده (جلوگیری از اسپم روزانه)
    fresh = [r for r in recipients
             if not store.outbox_exists_recent(kind=CYCLE_KIND, customer_id=r.customer_id,
                                               within_days=dedupe_days)]

    real_send = settings.mkt_auto_sms and settings.sms_configured
    messages = render_messages(settings.mkt_cycle_sms_template, fresh)

    sent = 0
    if real_send and messages:
        result = send_campaign(
            messages, provider=settings.mkt_sms_provider,
            api_key=settings.kavenegar_api_key, sender=settings.mkt_sms_sender,
            dry_run=False,
        )
        sent = result.sent
        status_of = {d.get("مشتری"): d.get("وضعیت", "") for d in result.details}
    else:
        status_of = {}

    for m in messages:
        store.add_outbox(
            kind=CYCLE_KIND, session_id=sid, audience=AUDIENCE_KEY,
            customer_id=m.customer_id, phone=m.phone, message=m.text,
            status=(status_of.get(m.customer_id) or ("ارسال شد" if real_send else "آماده (آزمایشی)")),
            provider=settings.mkt_sms_provider if real_send else "dry-run",
            dry_run=not real_send,
        )

    summary = {
        "status": "ok", "session_id": sid,
        "بررسی‌شده": len(recipients), "ثبت‌شده": len(fresh), "ارسال_واقعی": sent,
        "حالت": "ارسال واقعی" if real_send else "آزمایشی (بدون ارسال)",
    }
    logger.info("cycle scan: %s", summary)
    return summary


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
    sched.add_job(store.cleanup_expired, "interval", hours=6, id="session-cleanup",
                  replace_existing=True)
    sched.start()
    _scheduler = sched
    logger.info("scheduler started (cycle scan @ %02d:00 Tehran)", settings.mkt_schedule_hour)
    return True


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
    }


__all__ = ["run_cycle_scan", "start_scheduler", "stop_scheduler", "scheduler_status"]
