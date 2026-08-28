"""§۲۸: برای هر «(کسب‌وکار، تاریخ)» فقط **یک** اجرا.

## چرا این تست وجود دارد

`write_lock` یک قفلِ درون-پروسه‌ای است. تا امروز تنها چیزی بود که مانعِ دو
اجرای هم‌زمانِ موتور فرصت‌ها می‌شد — یعنی در استقرارِ چند-پروسه‌ای اصلاً مانعی
نبود. نتیجه‌ی دو اجرای هم‌زمان بی‌صدا و بد است: هرکدام فرصت‌هایی را که دیگری
هنوز ننوشته «ناپدید» اعلام می‌کند و بعد دوباره می‌سازدشان.

قاعده‌ای که اینجا پین می‌شود: **دومی صریحاً رد می‌شود.**
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

from mktcore.db.base import now_ts  # noqa: E402
from mktcore.db.engine import session_scope  # noqa: E402
from mktcore.db.leases import (  # noqa: E402
    LeaseBusyError,
    acquire_lease,
    job_lease,
    release_lease,
)
from mktcore.db.migrations import ensure_schema, reset_ensure_cache  # noqa: E402
from mktcore.db.models import JobLease  # noqa: E402

JOB = JobLease.JOB_OPPORTUNITY_ENGINE
SCOPE = "default|1405-06-06"


@pytest.fixture
def db(tmp_path) -> Path:
    reset_ensure_cache()
    path = tmp_path / "app.db"
    ensure_schema(path)
    yield path
    reset_ensure_cache()


def test_the_second_run_is_refused_with_a_persian_reason(db):
    with job_lease(JOB, SCOPE, db_path=db):
        with pytest.raises(LeaseBusyError) as caught:
            acquire_lease(JOB, SCOPE, db_path=db)

    assert "در جریان است" in caught.value.reason_fa
    assert SCOPE in caught.value.reason_fa


def test_a_different_date_is_not_blocked(db):
    """قفل روی «همه‌ی اجراها» نیست؛ روی همان دامنه است."""
    with job_lease(JOB, SCOPE, db_path=db):
        other = acquire_lease(JOB, "default|1405-06-07", db_path=db)
        release_lease(other, db_path=db)


def test_the_lease_is_released_even_when_the_run_explodes(db):
    """اجاره‌ای که با خطا آزاد نشود، آن تاریخ را برای همیشه قفل می‌کند."""
    with pytest.raises(ValueError, match="شبیه‌سازی"):
        with job_lease(JOB, SCOPE, db_path=db):
            raise ValueError("شبیه‌سازی سقوطِ وسطِ اجرا")

    again = acquire_lease(JOB, SCOPE, db_path=db)
    release_lease(again, db_path=db)


def test_an_expired_lease_can_be_taken_over_and_the_takeover_is_recorded(db):
    """پروسه‌ای که کشته شود ردیف را آزاد نمی‌کند — نباید ابد قفل بماند."""
    acquire_lease(JOB, SCOPE, ttl_seconds=-1.0, db_path=db)  # از قبل منقضی

    taken = acquire_lease(JOB, SCOPE, db_path=db)

    assert taken.took_over is True
    with session_scope(db) as session:
        row = session.get(JobLease, taken.id)
        assert row.takeovers == 1
        assert row.is_held(now=now_ts())


def test_releasing_a_stolen_lease_does_not_unlock_the_live_one(db):
    """دارنده‌ی قدیمیِ منقضی نباید قفلِ دارنده‌ی تازه را باز کند."""
    stale = acquire_lease(JOB, SCOPE, ttl_seconds=-1.0, holder="قدیمی", db_path=db)
    live = acquire_lease(JOB, SCOPE, holder="تازه", db_path=db)

    release_lease(stale, db_path=db)  # دارنده عوض شده؛ باید بی‌اثر باشد

    with pytest.raises(LeaseBusyError):
        acquire_lease(JOB, SCOPE, db_path=db)
    release_lease(live, db_path=db)


def test_a_race_produces_exactly_one_holder(db):
    """مسابقه‌ی واقعی: همه هم‌زمان تلاش می‌کنند و برنده اجاره را **نگه می‌دارد**.

    نسخه‌ی اولِ این تست برنده را وادار می‌کرد فوراً آزاد کند، و آن‌وقت هر شش
    thread موفق می‌شدند — که درست هم بود، چون هیچ‌وقت هم‌پوشانی نداشتند. تستی
    که هم‌پوشانی نسازد، انحصار را نمی‌سنجد.
    """
    start = threading.Barrier(6)
    attempts_done = threading.Barrier(7)  # شش thread + خودِ تست
    outcomes: list[str] = []
    guard = threading.Lock()

    def attempt() -> None:
        start.wait()
        try:
            lease = acquire_lease(JOB, SCOPE, db_path=db)
        except LeaseBusyError:
            with guard:
                outcomes.append("refused")
            attempts_done.wait()
            return
        with guard:
            outcomes.append("acquired")
        # اجاره تا وقتی همه تلاش کرده‌اند نگه داشته می‌شود
        attempts_done.wait()
        release_lease(lease, db_path=db)

    threads = [threading.Thread(target=attempt) for _ in range(6)]
    for thread in threads:
        thread.start()
    attempts_done.wait(timeout=30)
    for thread in threads:
        thread.join(timeout=30)

    assert outcomes.count("acquired") == 1, outcomes
    assert outcomes.count("refused") == 5, outcomes
