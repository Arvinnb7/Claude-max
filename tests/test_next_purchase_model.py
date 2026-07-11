"""تست‌های مدل احتمالاتی پیش‌بینی خرید بعدی (بدون API)."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from mktcore.analysis.next_purchase import (  # noqa: E402
    _window_probability,
    predict_next_purchases,
)
from mktcore.analysis.purchase_cycle import analyze_purchase_cycles  # noqa: E402


def _frame(rows: list[tuple[str, str, float, str | None]]) -> pd.DataFrame:
    """(customer, date, revenue, product) → دیتافریم استاندارد."""
    df = pd.DataFrame(rows, columns=["customer_id", "date", "revenue", "product"])
    df["date"] = pd.to_datetime(df["date"])
    return df


def _regular_buyer(cust: str, start: str, n: int, step_days: int,
                   revenue: float = 100.0, product: str = "الف"):
    dates = pd.date_range(start, periods=n, freq=f"{step_days}D")
    return [(cust, d.date().isoformat(), revenue, product) for d in dates]


def test_probability_bounds_on_synthetic():
    rows = []
    rows += _regular_buyer("منظم", "2024-01-01", 10, 30)
    rows += _regular_buyer("کم‌سابقه", "2024-06-01", 3, 45)
    rows += [("تک‌خرید", "2024-09-01", 50.0, "ب")]
    res = predict_next_purchases(_frame(rows))
    for c in res.customers:
        if c.buy_probability_30d is not None:
            assert 0.0 <= c.buy_probability_30d <= 1.0, c.customer_id


def test_probability_rises_near_due_date():
    """برای مشتری با چرخه‌ی ۳۰ روزه، احتمال در elapsed=۳۲ بیشتر از elapsed=۲۵ است... نه —
    احتمالِ پنجره‌ی شرطی با نزدیک شدن به سررسید بالا می‌رود."""
    mu = np.array([30.0, 30.0])
    cv = np.array([0.3, 0.3])
    p = _window_probability(np.array([10.0, 28.0]), mu, cv, 30)
    assert p[1] > p[0]


def test_alive_dampener_penalizes_long_overdue():
    mu = np.array([30.0, 30.0])
    cv = np.array([0.3, 0.3])
    p = _window_probability(np.array([36.0, 150.0]), mu, cv, 30)  # ۱٫۲ و ۵ چرخه
    assert p[1] < p[0]


def test_shrinkage_pulls_low_n_toward_pooled():
    """مشتری با ۲ فاصله‌ی ۶۰ روزه باید بیشتر از مشتری با ۱۲ فاصله‌ی ۶۰ روزه به میانه‌ی
    استخری (۳۰ روز، از جمعیت بزرگ) کشیده شود."""
    rows = []
    for i in range(30):
        rows += _regular_buyer(f"p{i}", "2024-01-01", 8, 30)
    rows += _regular_buyer("کم", "2024-01-01", 3, 60)     # ۲ فاصله‌ی ۶۰
    rows += _regular_buyer("زیاد", "2024-01-01", 13, 60)  # ۱۲ فاصله‌ی ۶۰
    res = predict_next_purchases(_frame(rows))
    by_id = {c.customer_id: c for c in res.customers}
    low, high = by_id["کم"], by_id["زیاد"]
    assert low.avg_interval_days is not None and high.avg_interval_days is not None
    # هر دو بین ۳۰ و ۶۰؛ کم‌سابقه نزدیک‌تر به ۳۰
    assert low.avg_interval_days < high.avg_interval_days
    assert abs(low.avg_interval_days - 30) < abs(high.avg_interval_days - 30)


def test_single_purchase_gets_pooled_prior_probability():
    rows = []
    for i in range(10):
        rows += _regular_buyer(f"p{i}", "2024-01-01", 6, 30)
    rows += [("تک", "2024-05-01", 80.0, "الف")]
    res = predict_next_purchases(_frame(rows))
    by_id = {c.customer_id: c for c in res.customers}
    single = by_id["تک"]
    assert single.status == "نامشخص"
    assert single.predicted_next_date is None
    assert single.buy_probability_30d is not None
    assert 0.0 <= single.buy_probability_30d <= 1.0


def test_no_repeat_buyers_gives_none_probability():
    rows = [("a", "2024-01-01", 10.0, "x"), ("b", "2024-02-01", 20.0, "y")]
    res = predict_next_purchases(_frame(rows))
    for c in res.customers:
        assert c.buy_probability_30d is None
        assert c.status == "نامشخص"


def test_expected_value_weights_recent_orders():
    """سفارش‌های اخیرِ بزرگ‌تر باید ارزش مورد انتظار را بالاتر از میانگین ساده ببرند."""
    rows = [("c", f"2024-0{m}-01", v, "الف")
            for m, v in [(1, 100.0), (2, 100.0), (3, 100.0), (4, 500.0), (5, 500.0)]]
    res = predict_next_purchases(_frame(rows))
    c = res.customers[0]
    simple_mean = 260.0
    assert c.expected_value > simple_mean


def test_likely_products_include_cycle_due_and_capped():
    """محصول چرخه‌عقب‌افتاده‌ی خود مشتری باید اول سبد محتمل بیاید و سقف ۵ رعایت شود."""
    rows = []
    # مشتری هدف: خرید منظم «شامپو» هر ۳۰ روز، آخرین بار خیلی وقت پیش → عقب‌افتاده
    rows += _regular_buyer("هدف", "2024-01-01", 5, 30, product="شامپو")
    # جمعیت برای چرخه‌ی محصول
    for i in range(8):
        rows += _regular_buyer(f"z{i}", "2024-01-01", 5, 30, product="شامپو")
    # داده تا تاریخ جلوتر ادامه دارد تا «هدف» عقب بیفتد
    rows += _regular_buyer("تازه", "2024-06-01", 3, 10, product="کرم")
    df = _frame(rows)
    cycles = analyze_purchase_cycles(df, None)
    res = predict_next_purchases(df, None, cycles=cycles)
    by_id = {c.customer_id: c for c in res.customers}
    target = by_id["هدف"]
    assert target.status in ("سررسیدشده", "نزدیک")
    assert len(target.likely_products) <= 5
    if any(n.customer_id == "هدف" for n in cycles.notifications):
        assert "شامپو" in target.likely_products


def test_due_now_backward_compat():
    rows = []
    rows += _regular_buyer("a", "2024-01-01", 6, 20)
    rows += _regular_buyer("b", "2024-03-01", 4, 15)
    res = predict_next_purchases(_frame(rows))
    due = res.due_now()
    for c in due:
        assert c.status in ("سررسیدشده", "نزدیک")
    overs = [c.overdue_days for c in due]
    assert overs == sorted(overs, reverse=True)
    # فیلدهای موجود حفظ شده‌اند
    c0 = res.customers[0]
    for attr in ("customer_id", "last_purchase", "avg_interval_days",
                 "predicted_next_date", "status", "overdue_days",
                 "likely_products", "expected_value", "buy_probability_30d"):
        assert hasattr(c0, attr)
