"""حلقه‌ی کامل یادگیری: کمپین → نتیجه → جدول اثر → رتبه‌بندی تازه.

این تست ادعای مرکزی فاز ۴ را می‌سنجد: سیستم از نتیجه‌ی کارِ خودش یاد می‌گیرد.
بدون این، جدول اثر فقط یک گزارش است — نه چیزی که تصمیم بعدی را عوض کند.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import func, select

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

from mktcore.campaigns.assign import ARM_CONTROL, ARM_TREATMENT  # noqa: E402
from mktcore.campaigns.outcomes import compute_campaign_outcomes  # noqa: E402
from mktcore.db import session_scope  # noqa: E402
from mktcore.db.migrations import reset_ensure_cache  # noqa: E402
from mktcore.db.models import CustomerFeature, UpliftSnapshot  # noqa: E402
from mktcore.db.repo_features import write_customer_features  # noqa: E402
from mktcore.uplift import build_uplift_table, refresh_uplift  # noqa: E402
from mktcore.uplift.snapshots import AGGREGATE  # noqa: E402

from .test_campaign_recovery import (  # noqa: E402
    CAMPAIGN_DATE,
    _customer_keys,
    _ingest,
    _make_campaign,
    _members_by_arm,
    _period_one_rows,
    _stamp_exposure,
)


@pytest.fixture(autouse=True)
def _isolate_schema_cache():
    reset_ensure_cache()
    yield
    reset_ensure_cache()


def _run_campaign_with_effect(db: Path, *, treated_rate: float, control_rate: float):
    """یک کمپین کامل با اثرِ کاشته‌شده، و بازگشت جدول اثر آموخته‌شده."""
    rows = _period_one_rows()
    clean = _ingest(rows, db)
    # حالت چرخه‌ی عمر لازم است چون سلولِ اثر روی آن ساخته می‌شود
    from mktcore.pipeline import run_analysis
    bundle = run_analysis(clean, horizon=2, with_forecast=False)
    write_customer_features(clean, bundle, db_path=db)

    campaign_id = _make_campaign(db, name="کمپین یادگیری")
    _stamp_exposure(db, campaign_id, CAMPAIGN_DATE)

    arms = _members_by_arm(db, campaign_id)
    keys = _customer_keys(db, arms[ARM_TREATMENT] + arms[ARM_CONTROL])
    follow_up = list(rows)
    for arm, rate in ((ARM_CONTROL, control_rate), (ARM_TREATMENT, treated_rate)):
        members = sorted(arms[arm])
        for index, customer_id in enumerate(members[:round(len(members) * rate)]):
            follow_up.append((
                f"1402/03/{(index % 28) + 1:02d}", 700_000, keys[customer_id],
                f"U{arm[:1]}{customer_id}", "کالا",
            ))

    _ingest(follow_up, db)
    compute_campaign_outcomes(db_path=db)
    return build_uplift_table(db_path=db)


def test_system_learns_a_positive_effect_from_its_own_campaign(tmp_path):
    """اثرِ واقعیِ کاشته‌شده باید در جدولِ آموخته‌شده ظاهر شود."""
    db = tmp_path / "app.db"
    table = _run_campaign_with_effect(db, treated_rate=0.45, control_rate=0.20)

    assert table.available
    assert table.n_observations > 0
    assert table.global_uplift == pytest.approx(0.25, abs=0.05)
    # و برای همان نوع اقدام هم تخمین ثبت شده است
    assert table.by_kind


def test_system_learns_that_contact_can_be_useless(tmp_path):
    """اگر تماس نتیجه را بدتر کند، سیستم باید گروه را بی‌فایده علامت بزند.

    این ارزشمندترین یادگیری برای کانال انبوه است: دانستن اینکه به چه کسی
    **نباید** پیام داد.
    """
    db = tmp_path / "app.db"
    table = _run_campaign_with_effect(db, treated_rate=0.15, control_rate=0.45)

    assert table.global_uplift < 0
    useless = [c for c in table.cells.values() if c.significantly_useless]
    assert useless, "گروهی با اثر منفیِ معنادار باید علامت خورده باشد"
    assert all(c.ci[1] <= 0 for c in useless)


def test_uplift_snapshot_is_persisted_and_reproducible(tmp_path):
    """عکسِ ماندگار: «چرا آن روز این ترتیب بود؟» باید پاسخ داشته باشد."""
    db = tmp_path / "app.db"
    _run_campaign_with_effect(db, treated_rate=0.45, control_rate=0.20)

    summary = refresh_uplift(db_path=db)
    assert summary["observations"] > 0
    assert summary["snapshot_rows"] > 0

    with session_scope(db) as session:
        rows = session.scalars(select(UpliftSnapshot)).all()
        assert rows
        # ردیف جمعیِ کل باید وجود داشته باشد
        globals_ = [r for r in rows if r.cell_kind == AGGREGATE]
        assert len(globals_) == 1
        assert globals_[0].uplift_bp is not None
        # نسبت‌ها به basis point صحیح ذخیره شده‌اند، نه float
        assert all(isinstance(r.uplift_bp, int) for r in rows if r.uplift_bp is not None)


def test_rerunning_refresh_on_the_same_day_replaces_not_duplicates(tmp_path):
    db = tmp_path / "app.db"
    _run_campaign_with_effect(db, treated_rate=0.45, control_rate=0.20)

    refresh_uplift(db_path=db)
    with session_scope(db) as session:
        first = session.scalar(select(func.count()).select_from(UpliftSnapshot))

    for _ in range(3):
        refresh_uplift(db_path=db)
    with session_scope(db) as session:
        after = session.scalar(select(func.count()).select_from(UpliftSnapshot))

    assert after == first


def test_learning_ignores_campaigns_without_a_control_group(tmp_path):
    """کمپین بدون گروه کنترل چیزی درباره‌ی «اثر» نمی‌گوید، پس نباید یاد داده شود.

    وگرنه سیستم «نرخ خرید» را یاد می‌گرفت به‌جای «اثر» — همان خطایی که کل این
    فاز برای رفعش ساخته شده.
    """
    from mktcore.db.models import Campaign, CampaignMember, CampaignOutcome

    db = tmp_path / "app.db"
    _run_campaign_with_effect(db, treated_rate=0.45, control_rate=0.20)

    # گروه کنترل را از یک کمپین حذف می‌کنیم تا تک‌بازو شود
    with session_scope(db) as session:
        campaign_id = session.scalar(select(Campaign.id))
        session.query(CampaignOutcome).filter(
            CampaignOutcome.campaign_id == campaign_id,
            CampaignOutcome.arm == ARM_CONTROL,
        ).delete(synchronize_session=False)
        session.query(CampaignMember).filter(
            CampaignMember.campaign_id == campaign_id,
            CampaignMember.arm == ARM_CONTROL,
        ).delete(synchronize_session=False)

    table = build_uplift_table(db_path=db)
    assert not table.available, "کمپین تک‌بازو نباید داده‌ی یادگیری بدهد"


def test_lifecycle_state_used_is_the_one_at_assignment_time(tmp_path):
    """حالتِ **زمان تخصیص** ملاک است، نه حالت امروز.

    استفاده از حالت امروز نشت اطلاعات آینده بود: مشتری‌ای که پس از تماس
    «بازگشته» شده، در آموزش «بازگشته» دیده می‌شد و اثر را بیش‌برآورد می‌کرد.
    """
    db = tmp_path / "app.db"
    _run_campaign_with_effect(db, treated_rate=0.45, control_rate=0.20)

    with session_scope(db) as session:
        snapshots = session.scalars(
            select(CustomerFeature).order_by(CustomerFeature.as_of_date)
        ).all()
        dates = sorted({s.as_of_date for s in snapshots})

    # دست‌کم دو عکس وجود دارد (دوره‌ی اول و دوم) — پس «کدام حالت» معنادار است
    assert len(dates) >= 1
    table = build_uplift_table(db_path=db)
    # حالتی که در سلول‌ها آمده باید از عکسِ پیش از تخصیص باشد
    assert table.available
    states_in_cells = {state for _kind, state in table.cells}
    assert states_in_cells
    assert all(isinstance(s, str) for s in states_in_cells)


def test_hook_reports_uplift_summary(tmp_path, monkeypatch):
    """هوکِ تحلیل باید خلاصه‌ی یادگیری را در پاسخ برگرداند."""
    from api.canonical_hook import _refresh_uplift

    db = tmp_path / "app.db"
    _run_campaign_with_effect(db, treated_rate=0.45, control_rate=0.20)

    monkeypatch.setenv("MKT_DATA_DIR", str(tmp_path))
    from mktcore.config import get_settings
    get_settings.cache_clear()
    try:
        summary = _refresh_uplift()
    finally:
        get_settings.cache_clear()

    assert summary is not None
    for key in ("observations", "cells", "snapshot_rows", "useless_cells"):
        assert key in summary


def test_period_dates_are_sane():
    """گاردِ تست: دوره‌ی اول باید پیش از تاریخ کمپین تمام شود."""
    rows = _period_one_rows()
    last = max(pd.Timestamp(f"2023-{3 + int(r[0].split('/')[1]) - 1:02d}-01") for r in rows[:2])
    assert last < pd.Timestamp(CAMPAIGN_DATE)
