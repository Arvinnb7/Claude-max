"""سنجش اثر — و مهم‌تر از آن، مرزِ صریحِ «نمی‌دانیم».

بیشترِ این تست‌ها درباره‌ی **خودداری** از ادعا هستند: گروه کوچک، بازه‌ای که
صفر را در بر می‌گیرد، و نبود گروه کنترل. عددِ اثرِ بی‌پایه از نبودِ عدد بدتر
است، چون تصمیم‌گیرنده روی نویز خرج می‌کند.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from mktcore.campaigns.analysis import (  # noqa: E402
    VERDICT_ATTRIBUTION_ONLY,
    VERDICT_INCONCLUSIVE,
    VERDICT_NOT_READY,
    VERDICT_PROVEN,
    ArmStats,
    analyze_campaign,
)


def _arm(name: str, size: int, converters: int, revenue: int = 0) -> ArmStats:
    return ArmStats(
        arm=name, size=size, converters=converters,
        orders=converters, revenue_rial=revenue or converters * 1_000_000,
    )


# ------------------------------------------------------ خودداری از ادعا
def test_no_control_group_means_attribution_only():
    report = analyze_campaign(_arm("treatment", 500, 100), _arm("control", 0, 0))
    assert report.verdict == VERDICT_ATTRIBUTION_ONLY
    assert not report.is_causal
    assert "گروه کنترل ندارد" in report.verdict_reason_fa


def test_small_groups_are_inconclusive_even_with_a_big_gap():
    """۱۰ در برابر ۱۰ نفر: حتی اختلاف بزرگ هم می‌تواند نویز باشد."""
    report = analyze_campaign(_arm("treatment", 10, 6), _arm("control", 10, 1))
    assert report.verdict == VERDICT_INCONCLUSIVE
    assert not report.is_causal
    assert "اندازه‌ی گروه‌ها کم است" in report.verdict_reason_fa
    # عدد محاسبه می‌شود ولی به‌عنوان اثبات ارائه نمی‌شود
    assert report.absolute_lift is not None


def test_overlapping_confidence_interval_is_inconclusive():
    """اختلاف کوچک در گروه بزرگ: بازه صفر را در بر می‌گیرد."""
    report = analyze_campaign(_arm("treatment", 1000, 201), _arm("control", 1000, 200))
    assert report.verdict == VERDICT_INCONCLUSIVE
    assert report.lift_ci[0] <= 0 <= report.lift_ci[1]
    assert "صفر را در بر می‌گیرد" in report.verdict_reason_fa


def test_no_exposed_members_is_not_ready():
    report = analyze_campaign(_arm("treatment", 0, 0), _arm("control", 50, 5))
    assert report.verdict == VERDICT_NOT_READY


# ------------------------------------------------------------ اثر واقعی
def test_clear_effect_in_large_groups_is_proven():
    report = analyze_campaign(_arm("treatment", 500, 150), _arm("control", 500, 50))
    assert report.verdict == VERDICT_PROVEN
    assert report.is_causal
    assert report.absolute_lift == pytest.approx(0.2)
    assert report.relative_lift == pytest.approx(2.0)
    assert report.lift_ci[0] > 0


def test_incremental_revenue_subtracts_the_control_baseline():
    """درآمد افزوده = درآمد گروه آزمایش منهای آنچه به‌هرحال اتفاق می‌افتاد."""
    treatment = ArmStats("treatment", size=500, converters=150,
                         orders=150, revenue_rial=150_000_000)
    control = ArmStats("control", size=500, converters=50,
                       orders=50, revenue_rial=50_000_000)
    report = analyze_campaign(treatment, control)

    # سرانه: ۳۰۰٬۰۰۰ در برابر ۱۰۰٬۰۰۰ → افزوده‌ی سرانه ۲۰۰٬۰۰۰ × ۵۰۰ نفر
    assert report.incremental_revenue_rial == 100_000_000
    assert report.incremental_revenue_rial < treatment.revenue_rial


def test_negative_effect_is_reported_honestly():
    """اگر تماس نتیجه‌ی بدتری داد، باید دیده شود — نه پنهان."""
    report = analyze_campaign(_arm("treatment", 500, 50), _arm("control", 500, 150))
    assert report.verdict == VERDICT_PROVEN
    assert report.absolute_lift < 0
    assert "منفی" in report.verdict_reason_fa


# --------------------------------------------------- سنجه‌های مسدود
def test_blocked_metrics_are_listed_explicitly_in_every_report():
    """نبودِ سنجه باید دیده شود، نه اینکه بی‌صدا غایب باشد."""
    for report in (
        analyze_campaign(_arm("treatment", 500, 150), _arm("control", 500, 50)),
        analyze_campaign(_arm("treatment", 10, 5), _arm("control", 10, 1)),
        analyze_campaign(_arm("treatment", 50, 5), _arm("control", 0, 0)),
    ):
        blocked = report.blocked_metrics
        assert "incremental_gross_profit" in blocked
        assert "بهای تمام‌شده" in blocked["incremental_gross_profit"]
        assert "delivered" in blocked
        assert "cost_per_incremental_order" in blocked


def test_report_dict_always_carries_a_verdict_label():
    payload = analyze_campaign(_arm("treatment", 500, 150), _arm("control", 500, 50)).to_dict()
    assert payload["verdict_label"]
    assert payload["is_causal"] is True
    assert payload["arms"]["control"]["size"] == 500
    assert payload["blocked_metrics"]


# ------------------------------------------------- قدرت تفکیک (MDE)
def test_report_states_what_it_could_not_have_seen():
    """«شواهد کافی نیست» بدون گفتنِ حدِ تفکیک، مبهم است."""
    report = analyze_campaign(_arm("treatment", 320, 96), _arm("control", 80, 24))
    assert report.detectable_effect is not None
    assert 0.10 < report.detectable_effect < 0.13  # با کنترل ۸۰ نفره ≈ ۱۱ واحد درصد
    assert "قابل تشخیص" in report.power_note_fa
    assert "گروه کنترل باید" in report.power_note_fa  # راهنمای عملی


def test_bigger_groups_detect_smaller_effects():
    small = analyze_campaign(_arm("treatment", 320, 96), _arm("control", 80, 24))
    large = analyze_campaign(_arm("treatment", 3200, 960), _arm("control", 800, 240))
    assert large.detectable_effect < small.detectable_effect / 2


def test_required_control_size_grows_quadratically_as_effect_shrinks():
    """نصف‌کردن اثرِ هدف، اندازه‌ی لازم را چهار برابر می‌کند."""
    from mktcore.campaigns.analysis import required_control_size

    at_10 = required_control_size(0.10)
    at_5 = required_control_size(0.05)
    assert 3.5 < at_5 / at_10 < 4.5


def test_larger_holdout_needs_a_smaller_total_campaign():
    """یافته‌ی غیرشهودی ولی درست: گروه کنترل بزرگ‌تر، آماری کاراتر است.

    با کنترل ۲۰٪ کل کمپین حدود نصفِ حالتِ کنترل ۱۰٪ است، برای همان قدرت تفکیک.
    """
    from mktcore.campaigns.analysis import required_control_size

    total_at_10 = required_control_size(0.05, holdout_pct=10) * 100 / 10
    total_at_20 = required_control_size(0.05, holdout_pct=20) * 100 / 20
    assert total_at_20 < total_at_10 * 0.65


def test_detectable_effect_is_none_without_both_arms():
    assert analyze_campaign(_arm("treatment", 50, 5), _arm("control", 0, 0)).detectable_effect is None


def test_zero_conversion_control_does_not_crash_relative_lift():
    report = analyze_campaign(_arm("treatment", 500, 100), _arm("control", 500, 0))
    assert report.relative_lift is None  # تقسیم بر صفر معنا ندارد
    assert report.absolute_lift == pytest.approx(0.2)


# ═══════════════════ سود ناخالص افزوده — شمالِ‌ستاره‌ی سند (§۴)
def test_incremental_gross_profit_needs_full_cost_coverage():
    """مهم‌ترین گاردِ صداقت: جمعِ ناقصِ بها سود را **بیشتر** از واقع نشان می‌دهد.

    اگر بهای بعضی خطوط حساب نشده باشد، «درآمد منهای بها» بزرگ‌تر درمی‌آید و
    هیچ نشانه‌ای هم همراهش نیست. پس عدد اصلاً گزارش نمی‌شود.
    """
    treatment = ArmStats(arm="treatment", size=200, converters=60, orders=60,
                         revenue_rial=6_000_000, cost_rial=None)
    control = ArmStats(arm="control", size=200, converters=40, orders=40,
                       revenue_rial=4_000_000, cost_rial=2_400_000)

    report = analyze_campaign(treatment, control)
    assert report.incremental_gross_profit_rial is None
    assert "incremental_gross_profit" in report.blocked_metrics
    assert "عددِ ناقص" in report.gross_profit_note_fa


def test_incremental_gross_profit_is_computed_with_full_coverage():
    """با پوشش کامل، سنجه‌ای که سند شمالِ‌ستاره می‌نامد باز می‌شود."""
    treatment = ArmStats(arm="treatment", size=200, converters=60, orders=60,
                         revenue_rial=6_000_000, cost_rial=3_600_000)
    control = ArmStats(arm="control", size=200, converters=40, orders=40,
                       revenue_rial=4_000_000, cost_rial=2_400_000)

    report = analyze_campaign(treatment, control)
    # سودِ سرانه: آزمایش (۶M−۳٫۶M)/۲۰۰ = ۱۲۰۰۰ · کنترل (۴M−۲٫۴M)/۲۰۰ = ۸۰۰۰
    # افزوده = (۱۲۰۰۰ − ۸۰۰۰) × ۲۰۰ = ۸۰۰٬۰۰۰
    assert report.incremental_gross_profit_rial == 800_000
    assert "incremental_gross_profit" not in report.blocked_metrics


def test_gross_profit_uses_profit_not_revenue():
    """اگر اشتباهاً درآمد به‌جای سود استفاده شود، عدد ۲٫۵ برابر بزرگ‌تر می‌شود."""
    treatment = ArmStats(arm="treatment", size=100, converters=30, orders=30,
                         revenue_rial=1_000_000, cost_rial=600_000)
    control = ArmStats(arm="control", size=100, converters=20, orders=20,
                       revenue_rial=500_000, cost_rial=300_000)

    report = analyze_campaign(treatment, control)
    revenue_based = round(
        (1_000_000 / 100 - 500_000 / 100) * 100
    )
    assert report.incremental_gross_profit_rial == 200_000
    assert report.incremental_gross_profit_rial != revenue_based


def test_gross_profit_can_be_negative_and_is_not_hidden():
    """کمپینی که سود را کم کرده باید همان را نشان دهد."""
    treatment = ArmStats(arm="treatment", size=100, converters=30, orders=30,
                         revenue_rial=1_000_000, cost_rial=900_000)
    control = ArmStats(arm="control", size=100, converters=20, orders=20,
                       revenue_rial=500_000, cost_rial=200_000)

    report = analyze_campaign(treatment, control)
    assert report.incremental_gross_profit_rial < 0


def test_arm_without_cost_reports_none_profit_not_zero():
    arm = ArmStats(arm="treatment", size=10, revenue_rial=1_000, cost_rial=None)
    assert arm.gross_profit_rial is None
    assert arm.profit_per_customer is None


def test_empty_arm_does_not_divide_by_zero():
    arm = ArmStats(arm="control", size=0, revenue_rial=0, cost_rial=0)
    assert arm.profit_per_customer is None


def test_gross_profit_survives_in_the_payload():
    treatment = ArmStats(arm="treatment", size=200, converters=60, orders=60,
                         revenue_rial=6_000_000, cost_rial=3_600_000)
    control = ArmStats(arm="control", size=200, converters=40, orders=40,
                       revenue_rial=4_000_000, cost_rial=2_400_000)
    payload = analyze_campaign(treatment, control).to_dict()
    assert payload["incremental_gross_profit_rial"] == 800_000
    assert payload["gross_profit_note_fa"]
