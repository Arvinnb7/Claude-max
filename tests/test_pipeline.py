"""تست‌های تحلیل، پیش‌بینی، تارگت و خط لوله‌ی کامل."""

from __future__ import annotations

import pandas as pd

from mktcore.ingest.cleaning import clean_frame
from mktcore.ingest.mapper import SchemaMapper
from mktcore.pipeline import run_analysis


def _standard(raw: pd.DataFrame) -> pd.DataFrame:
    mapper = SchemaMapper()
    std = mapper.apply(raw, mapper.auto_detect(raw).mapping)
    return clean_frame(std)


def test_full_pipeline(raw_sales):
    df = _standard(raw_sales)
    bundle = run_analysis(df, horizon=6)

    # KPI
    assert bundle.kpis.total_revenue > 0
    assert bundle.kpis.n_orders > 0
    assert bundle.kpis.n_customers > 0
    assert bundle.kpis.aov > 0
    # هزینه موجود است → حاشیه‌ی سود محاسبه شده
    assert bundle.kpis.gross_margin is not None
    assert 0 < bundle.kpis.gross_margin < 1

    # روند
    assert len(bundle.trends.monthly) >= 12

    # سگمنت‌بندی RFM
    assert not bundle.segmentation.rfm_table.empty
    assert sum(bundle.segmentation.segment_sizes.values()) == df["customer_id"].nunique()

    # ناهنجاری تزریق‌شده باید شناسایی شود
    assert len(bundle.anomalies.anomalies) >= 1

    # فصلی‌بودن: قوی‌ترین روز پنجشنبه یا جمعه (طبق داده‌ی مصنوعی)
    peak = max(bundle.seasonality.weekday_index, key=bundle.seasonality.weekday_index.get)
    assert peak in ("پنجشنبه", "جمعه")


def test_forecast_and_targets(raw_sales):
    df = _standard(raw_sales)
    bundle = run_analysis(df, horizon=6)

    fc = bundle.forecast
    assert fc is not None
    assert fc.horizon == 6
    # کف ≤ پیش‌بینی ≤ سقف
    assert (fc.lower <= fc.yhat + 1e-6).all()
    assert (fc.yhat <= fc.upper + 1e-6).all()

    tp = bundle.targets
    assert tp is not None
    cons = tp.scenarios["conservative"].total
    bal = tp.scenarios["balanced"].total
    amb = tp.scenarios["ambitious"].total
    # ترتیب سناریوها: محافظه‌کار ≤ متعادل ≤ جسورانه
    assert cons <= bal <= amb


def test_pipeline_handles_minimal_data():
    raw = pd.DataFrame({
        "تاریخ": pd.date_range("2024-01-01", periods=10, freq="D"),
        "مبلغ کل": [100, 120, 90, 110, 130, 95, 105, 115, 125, 100],
    })
    df = _standard(raw)
    bundle = run_analysis(df, horizon=3)
    assert bundle.kpis.total_revenue == 1090
    # داده‌ی کم → هشدار کیفیت
    assert any("کم" in w or "کوتاه" in w for w in bundle.quality.warnings)
