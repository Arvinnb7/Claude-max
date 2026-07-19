"""تست ماه ناقص (MTD/nowcast/رشد فقط بین ماه‌های کامل) و سطل «بدون شعبه»."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from mktcore.analysis.diagnostics import diagnose  # noqa: E402
from mktcore.analysis.kpis import compute_kpis  # noqa: E402
from mktcore.analysis.performance import (  # noqa: E402
    UNASSIGNED_BRANCH,
    analyze_performance,
)
from mktcore.analysis.trends import compute_trends  # noqa: E402


def _frame(end: str) -> pd.DataFrame:
    """درآمد روزانه ثابت ۱۰۰ از اول ژانویه تا تاریخ داده‌شده."""
    dates = pd.date_range("2024-01-01", end, freq="D")
    return pd.DataFrame({"date": dates, "revenue": 100.0,
                         "customer_id": [f"c{i % 30}" for i in range(len(dates))]})


def test_partial_month_detected_and_nowcast():
    df = _frame("2024-04-12")  # آوریل ناقص (۱۲ از ۳۰ روز)
    t = compute_trends(df)
    assert t.partial_month is not None
    pm = t.partial_month
    assert pm["label"] == "2024-04"
    assert pm["days_covered"] == 12 and pm["days_in_month"] == 30
    assert pm["mtd_actual"] == 1200.0
    # درآمد ثابت → برآورد پایان ماه ~۳۰۰۰
    assert abs(pm["nowcast"] - 3000.0) < 150.0
    # رشد ماهانه فقط بین ماه‌های کامل (ژانویه..مارس) → آخرین رشد مارس/فوریه
    assert len(t.monthly_growth.dropna()) == 2


def test_complete_month_no_partial_flag():
    df = _frame("2024-03-31")
    t = compute_trends(df)
    assert t.partial_month is None
    # درآمد ثابت روزانه → mom مارس/فوریه = 31/29 - 1
    k = compute_kpis(df)
    assert k.mom_growth is not None
    assert abs(k.mom_growth - (31 / 29 - 1)) < 1e-9


def test_kpi_mom_ignores_partial_tail():
    k_partial = compute_kpis(_frame("2024-04-03"))
    k_complete = compute_kpis(_frame("2024-03-31"))
    # ماه ناقص آوریل نباید رشد ماهانه را به سقوط قلابی ببرد
    assert k_partial.mom_growth == k_complete.mom_growth


def test_diagnose_skips_partial_month():
    df = _frame("2024-04-05")
    df["product"] = "کالا"
    rep = diagnose(df)
    # مقایسه باید مارس نسبت به فوریه باشد نه آوریل ناقص نسبت به مارس
    assert "2024-03-31" in rep.period_label and "2024-02-29" in rep.period_label
    assert rep.overall_delta > 0  # مارس ۳۱ روز > فوریه ۲۹ روز


def test_unassigned_branch_bucket_and_share_reconciles():
    rng = np.random.default_rng(5)
    n = 300
    df = pd.DataFrame({
        "date": pd.to_datetime("2024-01-01") + pd.to_timedelta(rng.integers(0, 90, n), "D"),
        "revenue": rng.uniform(10, 100, n),
        "branch": ["الف"] * 100 + ["ب"] * 100 + [None] * 100,
    })
    perf = analyze_performance(df)
    names = {e.name for e in perf.by_branch}
    assert UNASSIGNED_BRANCH in names
    assert abs(sum(e.share for e in perf.by_branch) - 1.0) < 1e-9
