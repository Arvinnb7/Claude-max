"""تخصیص بازوی آزمایش — قطعی، طبقه‌بندی‌شده، در سطح مشتری."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from mktcore.campaigns.assign import (  # noqa: E402
    ARM_CONTROL,
    ARM_TREATMENT,
    assign_arms,
    control_share,
)


def _customers(n: int, strata: int = 1) -> dict[str, str]:
    return {f"C{i}": f"گروه{i % strata}" for i in range(n)}


def test_assignment_is_reproducible():
    """اجرای دوباره نباید بازوها را عوض کند — کمپینِ در جریان خراب می‌شد."""
    customers = _customers(200)
    first = assign_arms(customers, campaign_key="camp-1", holdout_pct=10)
    second = assign_arms(customers, campaign_key="camp-1", holdout_pct=10)
    assert {(a.customer_key, a.arm) for a in first} == {
        (a.customer_key, a.arm) for a in second
    }


def test_assignment_ignores_input_order():
    """ترتیب ورودی نباید در نتیجه اثر داشته باشد."""
    customers = _customers(100)
    forward = assign_arms(customers, campaign_key="c", holdout_pct=20)
    backward = assign_arms(dict(reversed(list(customers.items()))),
                           campaign_key="c", holdout_pct=20)
    assert {(a.customer_key, a.arm) for a in forward} == {
        (a.customer_key, a.arm) for a in backward
    }


def test_different_campaigns_pick_different_controls():
    """یک نفر نباید برای همیشه از همه‌ی تماس‌ها محروم بماند."""
    customers = _customers(300)
    a = {x.customer_key for x in assign_arms(customers, campaign_key="A") if x.is_control}
    b = {x.customer_key for x in assign_arms(customers, campaign_key="B") if x.is_control}
    assert a != b
    assert a & b != a  # همپوشانی کامل نیست


def test_holdout_share_is_close_to_requested():
    customers = _customers(1000)
    for pct in (5, 10, 20, 50):
        assignments = assign_arms(customers, campaign_key="c", holdout_pct=pct)
        assert abs(control_share(assignments) - pct / 100) < 0.02


def test_zero_holdout_puts_everyone_in_treatment():
    assignments = assign_arms(_customers(50), campaign_key="c", holdout_pct=0)
    assert all(a.arm == ARM_TREATMENT for a in assignments)
    assert control_share(assignments) == 0.0


def test_strata_each_get_a_control_group():
    """گروه کنترل نباید تصادفاً همه‌اش از یک طبقه دربیاید."""
    customers = _customers(400, strata=4)
    assignments = assign_arms(customers, campaign_key="c", holdout_pct=10)
    control_strata = {a.stratum for a in assignments if a.is_control}
    assert len(control_strata) == 4


def test_small_stratum_still_keeps_someone_in_treatment():
    """با گروه دو نفره، هر دو نباید کنترل شوند."""
    assignments = assign_arms({"A": "s", "B": "s"}, campaign_key="c", holdout_pct=50)
    arms = {a.arm for a in assignments}
    assert ARM_TREATMENT in arms


def test_single_customer_goes_to_treatment():
    assignments = assign_arms({"A": "s"}, campaign_key="c", holdout_pct=10)
    assert assignments[0].arm == ARM_TREATMENT


def test_every_customer_gets_exactly_one_arm():
    customers = _customers(250, strata=3)
    assignments = assign_arms(customers, campaign_key="c", holdout_pct=15)
    keys = [a.customer_key for a in assignments]
    assert len(keys) == len(set(keys)) == len(customers)
    assert all(a.arm in (ARM_TREATMENT, ARM_CONTROL) for a in assignments)


def test_empty_input_is_safe():
    assert assign_arms({}, campaign_key="c") == []
    assert control_share([]) == 0.0
