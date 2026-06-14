"""خط لوله‌ی تحلیل: از DataFrame استاندارد تا MetricsBundle (خالص، بدون AI/UI)."""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from .analysis.anomalies import AnomalyResult, detect_anomalies
from .analysis.cohorts import CohortResult, compute_cohorts
from .analysis.kpis import KPISet, compute_kpis
from .analysis.seasonality import SeasonalityResult, compute_seasonality
from .analysis.segmentation import SegmentationResult, compute_segmentation
from .analysis.trends import TrendResult, compute_trends
from .forecasting.base import ForecastResult
from .forecasting.selector import choose_and_forecast
from .ingest.profiler import DataQualityReport, profile_frame
from .targets.target_setter import TargetProposal, propose_targets


@dataclass
class MetricsBundle:
    """خروجی کامل تحلیل — ورودی لایه‌ی گزارش و هوش مصنوعی."""

    kpis: KPISet = field(default_factory=KPISet)
    trends: TrendResult = field(default_factory=TrendResult)
    segmentation: SegmentationResult = field(default_factory=SegmentationResult)
    anomalies: AnomalyResult = field(default_factory=AnomalyResult)
    cohorts: CohortResult = field(default_factory=CohortResult)
    seasonality: SeasonalityResult = field(default_factory=SeasonalityResult)
    forecast: ForecastResult | None = None
    targets: TargetProposal | None = None
    quality: DataQualityReport = field(default_factory=DataQualityReport)
    meta: dict = field(default_factory=dict)


def run_analysis(
    df: pd.DataFrame,
    *,
    horizon: int = 6,
    freq: str = "ME",
    balanced_uplift: float = 0.10,
    with_forecast: bool = True,
) -> MetricsBundle:
    """اجرای کامل تحلیل روی یک DataFrame پاک‌شده‌ی استاندارد.

    تابع خالص و قطعی است (به‌جز انتخاب مدل که خود قطعی است) و هیچ وابستگی به
    UI یا شبکه ندارد.
    """
    bundle = MetricsBundle()
    bundle.quality = profile_frame(df)
    bundle.kpis = compute_kpis(df)
    bundle.trends = compute_trends(df)
    bundle.segmentation = compute_segmentation(df)
    bundle.anomalies = detect_anomalies(df)
    bundle.cohorts = compute_cohorts(df)
    bundle.seasonality = compute_seasonality(df)

    if with_forecast and not df.empty:
        try:
            bundle.forecast = choose_and_forecast(df, horizon=horizon, freq=freq)
            bundle.targets = propose_targets(bundle.forecast, bundle.kpis, balanced_uplift=balanced_uplift)
        except Exception as e:  # pragma: no cover - مقاوم در برابر داده‌ی کم
            bundle.meta["forecast_error"] = str(e)

    return bundle


__all__ = ["MetricsBundle", "run_analysis"]
