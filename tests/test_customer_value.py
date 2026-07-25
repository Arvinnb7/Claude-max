"""تست ارزش مشتری: احتمال فعال‌بودن، ارزش مورد انتظار ۳۰ روز و CLV."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from mktcore.analysis.next_purchase import (  # noqa: E402
    alive_probability,
    predict_next_purchases,
    window_components,
)


def _regular_buyers(n_customers: int = 40, gap_days: int = 30, n_buys: int = 5,
                    value: float = 100.0, last_extra_days: int = 0) -> pd.DataFrame:
    rows = []
    for i in range(n_customers):
        for b in range(n_buys):
            day = b * gap_days + (i % 5)
            rows.append((f"c{i}", pd.Timestamp("2024-01-01") + pd.Timedelta(days=day),
                         value + i, "P"))
    # ساعت داده: یک ردیف آخر برای جلو بردن data_max
    rows.append(("clock", pd.Timestamp("2024-01-01")
                 + pd.Timedelta(days=(n_buys - 1) * gap_days + last_extra_days), 10.0, "P"))
    return pd.DataFrame(rows, columns=["customer_id", "date", "revenue", "product"])


def test_alive_probability_monotone_decreasing():
    mu = np.array([30.0, 30.0, 30.0, 30.0])
    elapsed = np.array([0.0, 30.0, 60.0, 150.0])
    p = alive_probability(elapsed, mu)
    assert p[0] == 1.0 and p[1] == 1.0  # تا یک چرخه افتی نیست
    assert p[2] < p[1] and p[3] < p[2]  # بعد از آن یکنوا کاهشی
    assert (p >= 0).all() and (p <= 1).all()


def test_window_components_split():
    p_win, p_alive = window_components(np.array([40.0]), np.array([30.0]),
                                       np.array([0.5]), 30)
    assert 0.0 <= p_win[0] <= 1.0
    assert 0.0 <= p_alive[0] <= 1.0
    assert p_alive[0] < 1.0  # بیش از یک چرخه تأخیر → افت زنده‌بودن


def test_value_fields_exposed_and_consistent():
    df = _regular_buyers()
    res = predict_next_purchases(df)
    by = {c.customer_id: c for c in res.customers}
    c = by["c0"]
    assert c.alive_probability is not None
    assert c.churn_risk is not None
    assert abs(c.churn_risk - (1 - c.alive_probability)) < 1e-6
    assert c.value_confidence == "بالا"  # ۵ خرید
    # ارزش ۳۰ روز = EV × احتمال، پس هرگز از EV بیشتر نیست
    assert c.expected_value_30d is not None
    assert 0 <= c.expected_value_30d <= c.expected_value + 1
    assert c.clv_12m is not None and c.clv_12m > 0


def test_clv_lower_for_more_overdue_customer():
    """مشتری‌ای که بیشتر از چرخه‌اش گذشته، ارزش عمر کمتری دارد."""
    fresh = predict_next_purchases(_regular_buyers(last_extra_days=0))
    stale = predict_next_purchases(_regular_buyers(last_extra_days=200))
    f = next(c for c in fresh.customers if c.customer_id == "c0")
    s = next(c for c in stale.customers if c.customer_id == "c0")
    assert s.alive_probability < f.alive_probability
    assert s.clv_12m < f.clv_12m


def test_single_purchase_customer_marked_insufficient():
    df = _regular_buyers()
    extra = pd.DataFrame([("solo", pd.Timestamp("2024-02-01"), 500.0, "P")],
                         columns=["customer_id", "date", "revenue", "product"])
    res = predict_next_purchases(pd.concat([df, extra], ignore_index=True))
    solo = next(c for c in res.customers if c.customer_id == "solo")
    assert solo.value_confidence == "کم (نمونه ناکافی)"
    assert solo.status == "نامشخص"


def test_no_repeat_data_leaves_values_none():
    df = pd.DataFrame({
        "customer_id": [f"c{i}" for i in range(30)],
        "date": pd.to_datetime(["2024-01-05"] * 30),
        "revenue": [100.0] * 30,
        "product": ["P"] * 30,
    })
    res = predict_next_purchases(df)
    for c in res.customers:
        assert c.buy_probability_30d is None
        assert c.alive_probability is None
        assert c.expected_value_30d is None
        assert c.clv_12m is None
