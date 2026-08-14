"""ماشین حالت چرخه‌ی عمر — تابع خالص، بدون دیتابیس.

ادعای مرکزی: **همان تعداد روز بی‌خریدی، برای دو مشتری با آهنگ متفاوت، دو حالت
متفاوت می‌دهد.** اگر این بشکند، سیستم به قاعده‌ی سراسری ۳۰/۶۰/۹۰ برگشته است.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from mktcore.lifecycle import (  # noqa: E402
    LIFECYCLE_STATES,
    STATE_LABELS_FA,
    LifecycleInput,
    classify_lifecycle,
)
from mktcore.lifecycle.states import population_gap, vip_threshold  # noqa: E402


def _customer(**kwargs) -> LifecycleInput:
    base = {"n_orders": 5, "recency_days": 10, "tenure_days": 400,
            "avg_gap_days": 30.0, "p_alive": 0.9}
    base.update(kwargs)
    return LifecycleInput(**base)


# ------------------------------------------------- ادعای مرکزی: شخصی‌سازی
def test_same_gap_different_cadence_gives_different_state():
    """۴۵ روز بی‌خریدی: برای مشتری ماهانه لغزش، برای مشتری فصلی عادی."""
    monthly = classify_lifecycle(_customer(avg_gap_days=30.0, recency_days=45))
    quarterly = classify_lifecycle(_customer(avg_gap_days=90.0, recency_days=45))

    assert monthly.state == "slipping"
    assert quarterly.state != "slipping"
    assert quarterly.state in ("loyal", "established", "growing")


@pytest.mark.parametrize(("recency", "expected"), [
    (20, "loyal"),        # هنوز سر وقت
    (40, "slipping"),     # ۱.۳ برابر
    (60, "at_risk"),      # ۲ برابر
    (120, "dormant"),     # ۴ برابر
    (200, "lost"),        # بیش از ۵ برابر
])
def test_overdue_ladder_on_a_thirty_day_cadence(recency: int, expected: str):
    verdict = classify_lifecycle(_customer(avg_gap_days=30.0, recency_days=recency))
    assert verdict.state == expected


def test_overdue_ratio_is_reported():
    verdict = classify_lifecycle(_customer(avg_gap_days=30.0, recency_days=60))
    assert verdict.overdue_ratio == pytest.approx(2.0)
    assert "برابر" in verdict.reason_fa


# ------------------------------------------------------- حالت‌های تعدادی
def test_single_order_is_new():
    verdict = classify_lifecycle(LifecycleInput(n_orders=1, recency_days=5, tenure_days=5))
    assert verdict.state == "new"
    assert verdict.basis == "count_only"  # با یک خرید، آهنگی وجود ندارد


def test_second_order_activates():
    verdict = classify_lifecycle(
        LifecycleInput(n_orders=2, recency_days=5, tenure_days=40, avg_gap_days=35.0)
    )
    assert verdict.state == "activated"


def test_no_orders_is_prospect():
    assert classify_lifecycle(LifecycleInput(n_orders=0)).state == "prospect"


def test_loyalty_is_measured_in_cycles_not_calendar_days():
    """مشتریِ دوروزه با ۵ خرید همان‌قدر وفادار است که مشتریِ ماهانه با ۵ خرید.

    «یک هفته برای وفاداری کم است» یک قضاوت تقویمی است، و دقیقاً همان چیزی که
    سند رد می‌کند: معیار باید آهنگ خودِ مشتری باشد، نه تقویم.
    """
    fast = classify_lifecycle(
        LifecycleInput(n_orders=5, recency_days=2, tenure_days=8, avg_gap_days=2.0)
    )
    slow = classify_lifecycle(_customer(n_orders=5, tenure_days=400, avg_gap_days=30.0))
    assert fast.state == slow.state == "loyal"


def test_loyalty_requires_a_known_personal_cadence():
    """با تکیه بر میانه‌ی جامعه، «منظم بودن» ادعای اثبات‌نشده است."""
    verdict = classify_lifecycle(LifecycleInput(
        n_orders=5, recency_days=5, tenure_days=100, population_gap_days=30.0,
    ))
    assert verdict.basis == "population"
    assert verdict.state != "loyal"


# -------------------------------------------------------------- ویژه (VIP)
def test_vip_is_based_on_future_value_not_past_revenue():
    """سند تصریح می‌کند «ویژه» یعنی ارزش آینده، نه درآمد گذشته."""
    verdict = classify_lifecycle(_customer(clv_rial=50_000_000,
                                           vip_clv_threshold_rial=30_000_000))
    assert verdict.state == "vip"
    assert "آینده" in verdict.reason_fa


def test_vip_below_threshold_falls_back_to_normal_state():
    verdict = classify_lifecycle(_customer(clv_rial=10_000_000,
                                           vip_clv_threshold_rial=30_000_000))
    assert verdict.state != "vip"


def test_lapsed_vip_is_not_labelled_vip():
    """مشتری ویژه‌ای که سه برابر آهنگش نیامده، «خفته» است نه «ویژه».

    برچسب خوش‌بینانه دقیقاً جلوی اقدام نجات را می‌گیرد.
    """
    verdict = classify_lifecycle(_customer(
        recency_days=120, avg_gap_days=30.0,
        clv_rial=50_000_000, vip_clv_threshold_rial=30_000_000,
    ))
    assert verdict.state == "dormant"


# ----------------------------------------------------------------- احیا
def test_returning_customer_is_reactivated():
    verdict = classify_lifecycle(_customer(
        recency_days=5, previous_state="dormant", purchased_since_previous=True,
    ))
    assert verdict.state == "reactivated"
    assert "خفته" in verdict.reason_fa


def test_reactivation_requires_an_actual_purchase():
    verdict = classify_lifecycle(_customer(
        recency_days=120, previous_state="dormant", purchased_since_previous=False,
    ))
    assert verdict.state == "dormant"


# ------------------------------------------------------- احتمال فعال‌بودن
def test_near_zero_alive_probability_is_lost():
    verdict = classify_lifecycle(_customer(recency_days=5, p_alive=0.01))
    assert verdict.state == "lost"
    assert "احتمال فعال‌بودن" in verdict.reason_fa


# --------------------------------------------------------- پایه‌ی قضاوت
def test_population_fallback_is_labelled_as_such():
    """وقتی آهنگ شخصی نیست، UI باید بداند قضاوت روی میانه‌ی جامعه بوده."""
    verdict = classify_lifecycle(LifecycleInput(
        n_orders=1, recency_days=140, tenure_days=140, population_gap_days=20.0,
    ))
    assert verdict.basis == "population"
    assert verdict.state == "lost"  # ۷ برابر میانه‌ی جامعه


def test_boundary_is_conservative():
    """دقیقاً روی آستانه، حالتِ ملایم‌تر انتخاب می‌شود — نه شدیدتر."""
    exactly_five = classify_lifecycle(_customer(avg_gap_days=20.0, recency_days=100))
    assert exactly_five.overdue_ratio == pytest.approx(5.0)
    assert exactly_five.state == "dormant"  # نه «ازدست‌رفته»


def test_personal_cadence_wins_over_population():
    verdict = classify_lifecycle(_customer(avg_gap_days=90.0, recency_days=100,
                                           population_gap_days=10.0))
    assert verdict.basis == "personal"
    assert verdict.state == "slipping"  # ۱.۱ برابر آهنگ خودش، نه ۱۰ برابر جامعه


def test_every_state_has_a_persian_label():
    for state in LIFECYCLE_STATES:
        assert STATE_LABELS_FA.get(state), state


def test_verdict_always_has_a_reason():
    for recency in (5, 45, 60, 120, 400):
        verdict = classify_lifecycle(_customer(recency_days=recency))
        assert verdict.reason_fa
        assert verdict.state in LIFECYCLE_STATES


# ------------------------------------------------------------ کمکی‌ها
def test_population_gap_uses_median_not_mean():
    """یک مشتریِ ده‌ساله نباید معیار بقیه را جابه‌جا کند."""
    assert population_gap([10, 20, 30, 40, 3650]) == 30
    assert population_gap([]) is None
    assert population_gap([0, -5]) is None


def test_vip_threshold_needs_enough_customers():
    assert vip_threshold([1, 2, 3]) is None  # با سه مشتری «دهک بالا» بی‌معناست
    values = list(range(1, 101))
    assert vip_threshold(values) == 91  # صدک ۹۰
