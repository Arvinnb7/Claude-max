"""اجاره‌ی اجرا: تضمینِ «یک اجرا برای هر (کسب‌وکار، تاریخ)» — §۲۸.

## قاعده‌ای که این ماژول پین می‌کند

اجرای دومِ هم‌زمان **صریحاً رد می‌شود**. نه بی‌صدا رد می‌شود، نه هر دو
می‌نویسند. کدِ فراخوان می‌تواند تصمیم بگیرد که خطا بدهد یا رد را گزارش کند،
ولی نمی‌تواند نداند.

## چرا اینجا و نه در `write_lock`

`write_lock` قفلِ درون-پروسه‌ای است و مسئله‌اش چیز دیگری است (جلوگیری از
`database is locked`). این اجاره **بین پروسه‌ها** کار می‌کند و مسئله‌اش
یکتاییِ *منطقیِ* اجراست، نه دسترسیِ همزمان به فایل.
"""

from __future__ import annotations

import logging
import os
import threading
from contextlib import contextmanager
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from mktcore.db.base import now_ts
from mktcore.db.engine import session_scope, write_lock
from mktcore.db.models import JobLease

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

logger = logging.getLogger("mktcore.db.leases")

# اجاره‌ی پیش‌فرض یک ساعت است: از طولانی‌ترین اجرای واقعیِ موتور خیلی بلندتر،
# و از «تا ابد قفل» خیلی کوتاه‌تر.
DEFAULT_TTL_SECONDS = 3600.0

__all__ = [
    "DEFAULT_TTL_SECONDS",
    "LeaseBusyError",
    "LeaseInfo",
    "acquire_lease",
    "job_lease",
    "release_lease",
]


class LeaseInfo:
    """عکسِ همان چیزی که گرفته شد — بعد از بسته‌شدن session هم قابل خواندن."""

    __slots__ = ("expires_at", "holder", "id", "job_name", "scope_key", "took_over")

    def __init__(
        self, *, id: int, job_name: str, scope_key: str, holder: str,
        expires_at: float, took_over: bool,
    ) -> None:
        self.id = id
        self.job_name = job_name
        self.scope_key = scope_key
        self.holder = holder
        self.expires_at = expires_at
        self.took_over = took_over


class LeaseBusyError(RuntimeError):
    """این کار برای این دامنه همین حالا دستِ یکی دیگر است."""

    def __init__(self, *, job_name: str, scope_key: str, holder: str, expires_at: float):
        self.job_name = job_name
        self.scope_key = scope_key
        self.holder = holder
        self.expires_at = expires_at
        super().__init__(
            f"اجرای «{job_name}» برای «{scope_key}» همین حالا در جریان است "
            f"(دارنده: {holder}). این اجرا رد شد تا دو نتیجه‌ی نیمه روی هم "
            f"نوشته نشود."
        )

    @property
    def reason_fa(self) -> str:
        return str(self)


def current_holder() -> str:
    """شناسه‌ی دارنده: پروسه و thread. برای انسان خواندنی باشد، نه یکتا-به‌هر-قیمت."""
    return f"pid:{os.getpid()}/thread:{threading.get_ident()}"[:128]


def acquire_lease(
    job_name: str,
    scope_key: str,
    *,
    ttl_seconds: float = DEFAULT_TTL_SECONDS,
    holder: str | None = None,
    db_path: Path | None = None,
) -> LeaseInfo:
    """اجاره را می‌گیرد یا `LeaseBusyError` می‌اندازد."""
    who = holder or current_holder()
    now = now_ts()
    expires = now + ttl_seconds

    # `write_lock` اینجا فقط برای جلوگیری از `database is locked` است؛ یکتایی
    # را قیدِ دیتابیس تضمین می‌کند نه این قفل.
    with write_lock, session_scope(db_path) as session:
        existing = session.scalars(
            select(JobLease).where(
                JobLease.job_name == job_name, JobLease.scope_key == scope_key,
            )
        ).one_or_none()

        if existing is not None:
            if existing.is_held(now=now):
                raise LeaseBusyError(
                    job_name=job_name, scope_key=scope_key,
                    holder=existing.holder, expires_at=existing.expires_at,
                )
            took_over = existing.released_at is None
            if took_over:
                # اجاره‌ای که آزاد نشده ولی منقضی شده = پروسه‌ای که سقوط کرده
                existing.takeovers += 1
                logger.warning(
                    "اجاره‌ی منقضیِ «%s/%s» از دارنده‌ی قبلی (%s) تصاحب شد؛ "
                    "احتمالاً آن اجرا نیمه‌کاره مانده است.",
                    job_name, scope_key, existing.holder,
                )
            existing.holder = who
            existing.acquired_at = now
            existing.expires_at = expires
            existing.released_at = None
            session.flush()
            return LeaseInfo(
                id=existing.id, job_name=job_name, scope_key=scope_key,
                holder=who, expires_at=expires, took_over=took_over,
            )

        lease = JobLease(
            job_name=job_name, scope_key=scope_key, holder=who,
            acquired_at=now, expires_at=expires,
        )
        session.add(lease)
        try:
            session.flush()
        except IntegrityError as exc:
            # مسابقه: بین `SELECT` و `INSERT` یکی دیگر ردیف را ساخت. قیدِ
            # یکتایی دقیقاً برای همین لحظه هست.
            raise LeaseBusyError(
                job_name=job_name, scope_key=scope_key,
                holder="اجرای هم‌زمان", expires_at=expires,
            ) from exc
        return LeaseInfo(
            id=lease.id, job_name=job_name, scope_key=scope_key,
            holder=who, expires_at=expires, took_over=False,
        )


def release_lease(lease: LeaseInfo, *, db_path: Path | None = None) -> None:
    """آزادکردن. ردیف پاک نمی‌شود تا تاریخچه‌ی تصاحب‌ها بماند."""
    with write_lock, session_scope(db_path) as session:
        row = session.get(JobLease, lease.id)
        if row is None:
            return
        # اگر بین این دو، اجاره منقضی و تصاحب شده باشد، دارنده عوض شده است و
        # آزادکردنش یعنی قفلِ یک اجرای زنده را باز کنیم.
        if row.holder == lease.holder:
            row.released_at = now_ts()


@contextmanager
def job_lease(
    job_name: str,
    scope_key: str,
    *,
    ttl_seconds: float = DEFAULT_TTL_SECONDS,
    db_path: Path | None = None,
) -> Iterator[LeaseInfo]:
    """`with job_lease(...)` — آزادسازی در هر حالت، حتی با خطا."""
    lease = acquire_lease(
        job_name, scope_key, ttl_seconds=ttl_seconds, db_path=db_path,
    )
    try:
        yield lease
    finally:
        release_lease(lease, db_path=db_path)
