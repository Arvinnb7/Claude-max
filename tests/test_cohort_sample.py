"""داده‌ی نمونه‌ی کوهورت‌دار — و اثباتِ اینکه مولد قدیمی دست‌نخورده مانده.

چرا این fixture لازم شد: مولدِ فعلی مشتری‌ها را از استخر ثابت انتخاب می‌کند، پس
«مشتری تازه» ندارد و §۱۸.۴ («اعتبارسنجی روی کوهورت‌های بعدی») رویش اجراشدنی
نیست. بدون کوهورتِ متأخر، مدلِ نهنگ را نمی‌شود صادقانه اعتبارسنجی کرد.

تستِ اولِ این فایل به‌اندازه‌ی بقیه مهم است: مولدِ قدیمی باید **بیت‌به‌بیت** همان
بماند، چون اعداد خروجی‌اش در تست‌های طلایی پین شده‌اند.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

from mktcore.analysis.kpis import compute_kpis  # noqa: E402
from mktcore.ingest.cleaning import clean_frame  # noqa: E402
from mktcore.ingest.mapper import SchemaMapper  # noqa: E402
from mktcore.synthetic import (  # noqa: E402
    cohort_quality,
    generate_cohort_sales,
    generate_synthetic_sales,
)

_OBSERVATION_DAYS = 90
_OUTCOME_DAYS = 365


def test_the_original_generator_is_untouched():
    """قرارداد صفر-رگرسیون: دکمه‌ی «داده‌ی نمونه» همان داده را می‌دهد."""
    frame = generate_synthetic_sales(seed=7, days=540)

    assert len(frame) == 15_578
    assert frame["کد مشتری"].nunique() == 370
    assert int(frame["مبلغ کل"].sum()) == 69_479_903_336


def test_cohort_sample_has_many_monthly_cohorts():
    frame = generate_cohort_sales()
    first = frame.groupby("کد مشتری")["تاریخ"].min()

    assert first.dt.to_period("M").nunique() >= 24, "کوهورت متأخر باید وجود داشته باشد"
    assert frame["کد مشتری"].nunique() >= 500


def test_cohort_sample_keeps_the_same_column_contract():
    """همان ستون‌ها یعنی همان مسیر ورود — دیتاستِ دیگر، نه طرح‌واره‌ی دیگر."""
    original = set(generate_synthetic_sales(days=60).columns)
    cohort = set(generate_cohort_sales(days=200).columns)

    assert cohort == original


def test_cohort_sample_flows_through_the_normal_ingest_path():
    frame = generate_cohort_sales(days=400)
    mapper = SchemaMapper()
    clean = clean_frame(mapper.apply(frame, mapper.auto_detect(frame).mapping))
    kpis = compute_kpis(clean)

    assert kpis.total_revenue > 0
    assert clean["cost"].notna().all(), "پوشش بها باید کامل باشد"


def test_early_behaviour_predicts_future_profit():
    """اگر رفتارِ اولیه با سودِ آینده همبسته نباشد، این fixture چیزی یاد نمی‌دهد.

    مدل هرگز «کیفیت» پنهان را نمی‌بیند؛ فقط رفتارِ پنجره‌ی اولیه را می‌بیند. این
    تست می‌سنجد که همان رفتار واقعاً سیگنال دارد — وگرنه تستِ «مدل خط پایه را
    برد» چیزی اثبات نمی‌کرد.
    """
    frame = generate_cohort_sales()
    frame = frame.assign(سود=frame["مبلغ کل"] - frame["بهای تمام شده"])
    first = frame.groupby("کد مشتری")["تاریخ"].min()
    anchor = first + pd.Timedelta(days=_OBSERVATION_DAYS)
    end = anchor + pd.Timedelta(days=_OUTCOME_DAYS)
    mature = end[end <= frame["تاریخ"].max()].index

    stamps = frame["کد مشتری"].map(anchor)
    early = frame[(frame["کد مشتری"].isin(mature)) & (frame["تاریخ"] < stamps)]
    later = frame[
        (frame["کد مشتری"].isin(mature))
        & (frame["تاریخ"] >= stamps)
        & (frame["تاریخ"] < frame["کد مشتری"].map(end))
    ]

    early_profit = early.groupby("کد مشتری")["سود"].sum()
    future_profit = later.groupby("کد مشتری")["سود"].sum().reindex(mature).fillna(0)
    breadth = early.groupby("کد مشتری")["دسته‌بندی"].nunique().reindex(mature).fillna(0)
    margin = (
        early.groupby("کد مشتری")["سود"].sum()
        / early.groupby("کد مشتری")["مبلغ کل"].sum()
    ).reindex(mature)

    assert len(mature) >= 200, "کوهورت بالغ باید برای آموزش کافی باشد"
    assert _spearman(early_profit.reindex(mature).fillna(0), future_profit) > 0.3
    assert _spearman(breadth, future_profit) > 0.1
    assert _spearman(margin.fillna(margin.median()), future_profit) > 0.1


def test_hidden_quality_is_not_a_column_of_the_frame():
    """کیفیت پنهان نباید در داده نشت کند؛ فقط تست به آن دسترسی دارد."""
    frame = generate_cohort_sales(days=200)

    assert "کیفیت" not in frame.columns
    assert set(cohort_quality(frame)) <= set(frame["کد مشتری"])


def _spearman(left: pd.Series, right: pd.Series) -> float:
    joined = pd.DataFrame({"l": left, "r": right}).dropna()
    if len(joined) < 3:
        return 0.0
    return float(np.corrcoef(joined["l"].rank(), joined["r"].rank())[0, 1])
