"""اعتبارسنجی ابزار سنجش اثر — دو آزمون که هر ابزار اندازه‌گیری باید بگذراند.

یک ترازو را این‌طور آزمایش می‌کنند: خالی که باشد باید صفر نشان دهد، و با وزنه‌ی
یک‌کیلویی باید یک کیلو نشان دهد. سنجش اثر کمپین هم همین دو آزمون را لازم دارد:

**آزمون تهی:** وقتی هیچ‌کس واقعاً تماس نگرفته، سیستم نباید اثری اعلام کند. اگر
اعلام کند، همه‌ی گزارش‌های بعدی بی‌ارزش‌اند — چون نمی‌شود فهمید کدام عدد واقعی
است و کدام توهم.

**آزمون بازیابی:** وقتی اثری **به‌عمد** در داده کاشته می‌شود، سیستم باید همان
اندازه را پیدا کند، نه بیشتر و نه کمتر.

بدون این دو، «اثر افزوده» فقط یک عدد است که کسی صحتش را نسنجیده.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import select

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

from mktcore.analysis.kpis import compute_kpis  # noqa: E402
from mktcore.campaigns.analysis import (  # noqa: E402
    VERDICT_INCONCLUSIVE,
    VERDICT_PROVEN,
    ArmStats,
    analyze_campaign,
)
from mktcore.campaigns.assign import ARM_CONTROL, ARM_TREATMENT, assign_arms  # noqa: E402
from mktcore.campaigns.outcomes import arm_stats, compute_campaign_outcomes  # noqa: E402
from mktcore.db import session_scope  # noqa: E402
from mktcore.db.migrations import reset_ensure_cache  # noqa: E402
from mktcore.db.models import (  # noqa: E402
    Campaign,
    CampaignMember,
    CampaignOpportunity,
    Customer,
    Opportunity,
)
from mktcore.db.repo_import import write_import  # noqa: E402
from mktcore.ingest.cleaning import clean_frame  # noqa: E402
from mktcore.ingest.mapper import SchemaMapper  # noqa: E402
from mktcore.ingest.schema import ColumnRole  # noqa: E402

_COLS = ["تاریخ", "مبلغ", "مشتری", "فاکتور", "کالا"]
_MAPPING = {
    ColumnRole.DATE: "تاریخ",
    ColumnRole.REVENUE: "مبلغ",
    ColumnRole.CUSTOMER_ID: "مشتری",
    ColumnRole.ORDER_ID: "فاکتور",
    ColumnRole.PRODUCT: "کالا",
}

# اندازه‌ی جمعیت آزمایش. باید از `MIN_CONTROL_SIZE=30` به‌قدر کافی بزرگ‌تر باشد
# که با گروه کنترل ۲۰٪ هم آستانه‌ی توان آماری رد شود.
N_CUSTOMERS = 400
HOLDOUT_PCT = 20
# اثری که به‌عمد کاشته می‌شود (واحد درصد)
INJECTED_LIFT = 0.15

# تاریخ تخصیص و تماس — **باید بعد از پایان دوره‌ی اول باشد**.
# دوره‌ی اول تا ۱۴۰۲/۰۲/۲۸ (≈ ۲۰۲۳-۰۵-۱۸) است؛ اگر تخصیص زودتر باشد، پنجره‌ی
# سنجشِ گروه کنترل با خریدهای **گذشته** همپوشانی پیدا می‌کند و آن‌ها به‌اشتباه
# «نتیجه‌ی کمپین» شمرده می‌شوند. در واقعیت این اتفاق نمی‌افتد (تخصیص همیشه
# «امروز» است و داده مربوط به گذشته)، ولی در تست باید صریح باشد.
CAMPAIGN_DATE = "2023-05-22"


@pytest.fixture(autouse=True)
def _isolate_schema_cache():
    reset_ensure_cache()
    yield
    reset_ensure_cache()


def _clean(rows: list[tuple]) -> pd.DataFrame:
    raw = pd.DataFrame(rows, columns=_COLS)
    return clean_frame(SchemaMapper().apply(raw, _MAPPING))


def _period_one_rows() -> list[tuple]:
    """دوره‌ی اول: همه‌ی مشتریان دو خرید منظم دارند.

    دو خرید لازم است تا آهنگ خرید شخصی شکل بگیرد و مشتری در تحلیل «شناخته» شود.
    """
    rows = []
    for i in range(N_CUSTOMERS):
        rows.append((f"1402/01/{(i % 28) + 1:02d}", 500_000 + i * 100,
                     f"C{i}", f"A{i}", "کالا"))
        rows.append((f"1402/02/{(i % 28) + 1:02d}", 500_000 + i * 100,
                     f"C{i}", f"B{i}", "کالا"))
    return rows


def _ingest(rows: list[tuple], db: Path) -> pd.DataFrame:
    clean = _clean(rows)
    write_import(clean, kpis=compute_kpis(clean), db_path=db)
    return clean


def _make_campaign(db: Path, *, name: str, window_days: int = 30) -> int:
    """ساخت کمپین مستقیم روی دیتابیس، با همان منطق تخصیصِ API.

    از API استفاده نمی‌شود چون این تست به دیتابیس موقتِ خودش نیاز دارد و
    `TestClient` روی مسیر داده‌ی پیش‌فرض کار می‌کند.
    """
    with session_scope(db) as session:
        business_id = session.scalar(select(Customer.business_id).limit(1))
        customers = session.scalars(select(Customer)).all()
        campaign = Campaign(
            business_id=business_id, name=name, status="running",
            holdout_pct=HOLDOUT_PCT, analysis_window_days=window_days,
        )
        session.add(campaign)
        session.flush()

        # هر مشتری یک فرصت می‌گیرد تا کمپین چیزی برای عرضه داشته باشد
        for customer in customers:
            opportunity = Opportunity(
                business_id=business_id, dedupe_key=f"{campaign.id}-{customer.id}",
                customer_id=customer.id, kind="یادآوری چرخه‌ی مصرف",
                generator="test", generator_version=1,
                title_fa="آزمون", action_fa="تماس", reason_fa="آزمون",
                expected_value_rial=1_000_000, score_rial=1_000_000,
                value_kind="ارزش فرصت", status="open",
            )
            session.add(opportunity)
            session.flush()
            session.add(CampaignOpportunity(
                campaign_id=campaign.id, opportunity_id=opportunity.id,
                customer_id=customer.id,
            ))

        assignments = assign_arms(
            {str(c.id): "همه" for c in customers},
            campaign_key=f"campaign-{campaign.id}", holdout_pct=HOLDOUT_PCT,
        )
        for assignment in assignments:
            session.add(CampaignMember(
                campaign_id=campaign.id, customer_id=int(assignment.customer_key),
                arm=assignment.arm, stratum=assignment.stratum,
                assigned_date=CAMPAIGN_DATE,
            ))
        session.flush()
        return campaign.id


def _stamp_exposure(db: Path, campaign_id: int, exposure_date: str) -> None:
    """مهر تماس روی بازوی آزمایش — همان کاری که خروجی اکسل می‌کند."""
    with session_scope(db) as session:
        members = session.scalars(
            select(CampaignMember).where(
                CampaignMember.campaign_id == campaign_id,
                CampaignMember.arm == ARM_TREATMENT,
            )
        ).all()
        for member in members:
            member.exposure_at = pd.Timestamp(exposure_date).timestamp()
            member.exposure_date = exposure_date
            member.exposure_channel = "excel_export"


def _arms(db: Path, campaign_id: int) -> tuple[ArmStats, ArmStats]:
    with session_scope(db) as session:
        stats = arm_stats(session, campaign_id)
    return (
        ArmStats(arm=ARM_TREATMENT, **stats.get(ARM_TREATMENT, {})),
        ArmStats(arm=ARM_CONTROL, **stats.get(ARM_CONTROL, {})),
    )


def _members_by_arm(db: Path, campaign_id: int) -> dict[str, list[int]]:
    with session_scope(db) as session:
        rows = session.execute(
            select(CampaignMember.arm, CampaignMember.customer_id)
            .where(CampaignMember.campaign_id == campaign_id)
        ).all()
    out: dict[str, list[int]] = {ARM_TREATMENT: [], ARM_CONTROL: []}
    for arm, customer_id in rows:
        out[str(arm)].append(int(customer_id))
    return out


def _customer_keys(db: Path, customer_ids: list[int]) -> dict[int, str]:
    with session_scope(db) as session:
        rows = session.execute(
            select(Customer.id, Customer.canonical_key)
            .where(Customer.id.in_(sorted(customer_ids)))
        ).all()
    return {int(cid): str(key) for cid, key in rows}


# ═══════════════════════════════════════════════ آزمون الف: تهی
def test_null_campaign_reports_no_proven_effect(tmp_path):
    """هیچ‌کس واقعاً تماس نگرفته → سیستم نباید اثری اعلام کند.

    این مهم‌ترین تست کل فاز ۳ است. اگر سیستم اینجا «اثر اثبات‌شده» بدهد، یعنی
    هر عددی که در آینده گزارش کند ممکن است توهم باشد.
    """
    db = tmp_path / "app.db"
    rows = _period_one_rows()
    _ingest(rows, db)

    campaign_id = _make_campaign(db, name="آزمون تهی")
    _stamp_exposure(db, campaign_id, CAMPAIGN_DATE)

    arms = _members_by_arm(db, campaign_id)
    keys = _customer_keys(db, arms[ARM_TREATMENT] + arms[ARM_CONTROL])

    # دوره‌ی دوم: هر دو بازو با **نرخ یکسانِ جزئی** خرید می‌کنند.
    # نرخ جزئی (نه ۱۰۰٪) عمدی است: اگر همه خرید کنند واریانس صفر می‌شود و بازه‌ی
    # اطمینان به‌طور تصنعی [۰،۰] درمی‌آید — تست به دلیل غلط پاس می‌شد.
    same_rate = 0.30
    follow_up = list(rows)
    for arm in (ARM_CONTROL, ARM_TREATMENT):
        members = sorted(arms[arm])
        for index, customer_id in enumerate(members[:round(len(members) * same_rate)]):
            follow_up.append((
                f"1402/03/{(index % 28) + 1:02d}", 400_000, keys[customer_id],
                f"F{arm[:1]}{customer_id}", "کالا",
            ))

    _ingest(follow_up, db)
    compute_campaign_outcomes(db_path=db)

    treatment, control = _arms(db, campaign_id)
    report = analyze_campaign(treatment, control)

    assert treatment.size > 0 and control.size > 0
    # هر دو بازو نرخ واقعی و یکسانی دارند — نه صفر و نه صد
    assert 0.2 < treatment.conversion_rate < 0.4
    assert 0.2 < control.conversion_rate < 0.4
    # بازه‌ی اطمینان باید **واقعی** باشد (پهنای غیرصفر) و صفر را در بر بگیرد
    assert report.lift_ci[1] - report.lift_ci[0] > 0.01
    assert report.lift_ci[0] <= 0 <= report.lift_ci[1]
    assert report.verdict == VERDICT_INCONCLUSIVE
    assert report.is_causal is False
    assert abs(report.absolute_lift) < 0.05


# ═══════════════════════════════════════ آزمون ب: بازیابی اثر معلوم
def test_injected_lift_is_recovered_with_the_right_magnitude(tmp_path):
    """اثرِ کاشته‌شده‌ی ۱۵ واحد درصد باید با همان اندازه بازیابی شود."""
    db = tmp_path / "app.db"
    rows = _period_one_rows()
    _ingest(rows, db)

    campaign_id = _make_campaign(db, name="آزمون بازیابی")
    _stamp_exposure(db, campaign_id, CAMPAIGN_DATE)

    arms = _members_by_arm(db, campaign_id)
    keys = _customer_keys(db, arms[ARM_TREATMENT] + arms[ARM_CONTROL])

    # نرخ خرید پایه‌ی گروه کنترل، و نرخ بالاتر برای گروه آزمایش
    base_rate = 0.30
    treatment_rate = base_rate + INJECTED_LIFT

    follow_up = list(rows)
    for arm, rate in ((ARM_CONTROL, base_rate), (ARM_TREATMENT, treatment_rate)):
        members = sorted(arms[arm])
        n_buyers = round(len(members) * rate)
        # انتخاب قطعی (نه تصادفی) تا تست تکرارپذیر بماند
        for index, customer_id in enumerate(members[:n_buyers]):
            key = keys[customer_id]
            follow_up.append((
                f"1402/03/{(index % 28) + 1:02d}", 700_000, key,
                f"X{arm[:1]}{customer_id}", "کالا",
            ))

    _ingest(follow_up, db)
    compute_campaign_outcomes(db_path=db)

    treatment, control = _arms(db, campaign_id)
    report = analyze_campaign(treatment, control)

    # نرخ‌ها باید نزدیک آنچه کاشته شد باشند (خطای گِرد کردن کوچک)
    assert treatment.conversion_rate == pytest.approx(treatment_rate, abs=0.02)
    assert control.conversion_rate == pytest.approx(base_rate, abs=0.02)

    # و اثر باید اثبات‌شده و به‌اندازه‌ی درست باشد
    assert report.verdict == VERDICT_PROVEN
    assert report.is_causal is True
    assert report.absolute_lift == pytest.approx(INJECTED_LIFT, abs=0.03)
    assert report.lift_ci[0] > 0, "بازه‌ی اطمینان باید کاملاً بالای صفر باشد"
    assert report.lift_ci[0] <= INJECTED_LIFT <= report.lift_ci[1], (
        "بازه‌ی اطمینان باید مقدار واقعی را در بر بگیرد"
    )


def test_injected_negative_effect_is_also_recovered(tmp_path):
    """اگر تماس نتیجه را **بدتر** کند، باید دیده شود — نه پنهان.

    این حالت واقعی است: پیام بی‌موقع می‌تواند مشتری را دلسرد کند. سیستمی که فقط
    اثر مثبت را می‌بیند، خطرناک است.
    """
    db = tmp_path / "app.db"
    rows = _period_one_rows()
    _ingest(rows, db)

    campaign_id = _make_campaign(db, name="آزمون اثر منفی")
    _stamp_exposure(db, campaign_id, CAMPAIGN_DATE)

    arms = _members_by_arm(db, campaign_id)
    keys = _customer_keys(db, arms[ARM_TREATMENT] + arms[ARM_CONTROL])

    follow_up = list(rows)
    for arm, rate in ((ARM_CONTROL, 0.45), (ARM_TREATMENT, 0.25)):
        members = sorted(arms[arm])
        for index, customer_id in enumerate(members[:round(len(members) * rate)]):
            follow_up.append((
                f"1402/03/{(index % 28) + 1:02d}", 700_000, keys[customer_id],
                f"N{arm[:1]}{customer_id}", "کالا",
            ))

    _ingest(follow_up, db)
    compute_campaign_outcomes(db_path=db)

    report = analyze_campaign(*_arms(db, campaign_id))
    assert report.verdict == VERDICT_PROVEN
    assert report.absolute_lift < 0
    assert "منفی" in report.verdict_reason_fa
    assert report.lift_ci[1] < 0, "بازه باید کاملاً زیر صفر باشد"


def test_measurement_window_excludes_purchases_after_it_closes(tmp_path):
    """خریدِ بعد از بسته‌شدن پنجره نباید به حساب کمپین نوشته شود.

    بدون این، هر کمپین با گذشت زمان «موفق‌تر» به‌نظر می‌رسید — چون خریدهای
    طبیعیِ ماه‌های بعد هم به آن نسبت داده می‌شد.
    """
    db = tmp_path / "app.db"
    rows = _period_one_rows()
    _ingest(rows, db)

    campaign_id = _make_campaign(db, name="آزمون پنجره", window_days=14)
    _stamp_exposure(db, campaign_id, CAMPAIGN_DATE)

    arms = _members_by_arm(db, campaign_id)
    keys = _customer_keys(db, arms[ARM_TREATMENT])
    treated = sorted(arms[ARM_TREATMENT])

    # همه‌ی خریدها **خارج** از پنجره‌ی ۱۴ روزه (سه ماه بعد)
    follow_up = rows + [
        (f"1402/06/{(i % 28) + 1:02d}", 900_000, keys[cid], f"L{cid}", "کالا")
        for i, cid in enumerate(treated)
    ]
    _ingest(follow_up, db)
    compute_campaign_outcomes(db_path=db)

    treatment, _control = _arms(db, campaign_id)
    assert treatment.converters == 0, "خرید خارج از پنجره نباید شمرده شود"
