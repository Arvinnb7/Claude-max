"""خط لوله‌ی تحلیل: از DataFrame استاندارد تا MetricsBundle (خالص، بدون AI/UI)."""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from .analysis.anomalies import AnomalyResult, detect_anomalies
from .analysis.cohorts import CohortResult, compute_cohorts
from .analysis.diagnostics import DiagnosticsReport, diagnose
from .analysis.inventory import InventoryAnalysis, analyze_inventory
from .analysis.kpis import KPISet, compute_kpis
from .analysis.market_basket import BasketAnalysis, analyze_basket
from .analysis.next_purchase import NextPurchaseAnalysis, predict_next_purchases
from .analysis.performance import PerformanceAnalysis, analyze_performance
from .analysis.products import ProductAnalysis, analyze_products
from .analysis.purchase_cycle import PurchaseCycleAnalysis, analyze_purchase_cycles
from .analysis.recommender import build_recommender
from .analysis.recommender_eval import BasketEvaluation, tune_and_evaluate
from .analysis.seasonality import SeasonalityResult, compute_seasonality
from .analysis.segmentation import SegmentationResult, compute_segmentation
from .analysis.sequence import SequenceAnalysis, analyze_sequences
from .analysis.trends import TrendResult, compute_trends
from .analysis.validation import ValidationReport, run_validation
from .forecasting.base import ForecastResult
from .forecasting.selector import choose_and_forecast
from .ingest.profiler import DataQualityReport, profile_frame
from .targets.allocation import TargetAllocation, allocate_targets
from .targets.pacing import PacingPlan, build_pacing_plan
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
    products: ProductAnalysis = field(default_factory=ProductAnalysis)
    basket: BasketAnalysis = field(default_factory=BasketAnalysis)
    sequences: SequenceAnalysis = field(default_factory=SequenceAnalysis)
    next_purchase: NextPurchaseAnalysis = field(default_factory=NextPurchaseAnalysis)
    purchase_cycle: PurchaseCycleAnalysis = field(default_factory=PurchaseCycleAnalysis)
    performance: PerformanceAnalysis = field(default_factory=PerformanceAnalysis)
    inventory: InventoryAnalysis = field(default_factory=InventoryAnalysis)
    diagnostics: DiagnosticsReport = field(default_factory=DiagnosticsReport)
    forecast: ForecastResult | None = None
    targets: TargetProposal | None = None
    branch_targets: TargetAllocation | None = None
    salesperson_targets: TargetAllocation | None = None
    pacing: PacingPlan | None = None
    validation: ValidationReport | None = None
    basket_eval: BasketEvaluation | None = None
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
    bundle.products = analyze_products(df)
    bundle.basket = analyze_basket(df)
    bundle.sequences = analyze_sequences(df)
    bundle.purchase_cycle = analyze_purchase_cycles(df, bundle.basket)
    # خودتنظیمی: بهترین وزن سیگنال‌ها روی holdout داده‌ی همین کاربر انتخاب می‌شود
    best_weights = None
    try:
        best_weights, bundle.basket_eval = tune_and_evaluate(df)
    except Exception as e:  # noqa: BLE001 - سنجش دقت نباید تحلیل را بشکند
        bundle.meta["basket_eval_error"] = str(e)
    recommender = build_recommender(df, cycles=bundle.purchase_cycle,
                                    basket=bundle.basket, weights=best_weights)
    bundle.next_purchase = predict_next_purchases(df, bundle.basket,
                                                  cycles=bundle.purchase_cycle,
                                                  recommender=recommender)
    if bundle.basket_eval is not None:
        bundle.basket_eval.coverage = sum(
            1 for c in bundle.next_purchase.customers if c.recommendations)
    bundle.performance = analyze_performance(df)
    bundle.inventory = analyze_inventory(df)
    bundle.diagnostics = diagnose(df)

    if with_forecast and not df.empty:
        try:
            bundle.forecast = choose_and_forecast(df, horizon=horizon, freq=freq)
            bundle.targets = propose_targets(bundle.forecast, bundle.kpis, balanced_uplift=balanced_uplift)
            _allocate_entity_targets(bundle, df)
            _build_pacing(bundle, df)
        except Exception as e:  # pragma: no cover - مقاوم در برابر داده‌ی کم
            bundle.meta["forecast_error"] = str(e)

    try:
        bundle.validation = run_validation(bundle, df)
    except Exception as e:  # noqa: BLE001 - دروازه نباید تحلیل را بشکند
        bundle.meta["validation_error"] = str(e)

    return bundle


def _allocate_entity_targets(bundle: MetricsBundle, df: pd.DataFrame) -> None:
    """تخصیص تارگت دوره‌ی پیش‌بینی به شعب و فروشنده‌ها."""
    if bundle.targets is None:
        return
    # تارگت سناریوی متعادل به‌عنوان مبنای تخصیص
    total_target = bundle.targets.scenarios["balanced"].total
    baseline_total = bundle.targets.forecast_total
    perf = bundle.performance
    # سطل «بدون شعبه/فروشنده» تارگت نمی‌گیرد؛ سهمش بین بقیه بازتوزیع می‌شود
    from .analysis.performance import UNASSIGNED_BRANCH, UNASSIGNED_SALESPERSON

    branches = [e for e in perf.by_branch if e.name != UNASSIGNED_BRANCH]
    salespeople = [e for e in perf.by_salesperson if e.name != UNASSIGNED_SALESPERSON]
    if branches:
        bundle.branch_targets = allocate_targets(
            branches, total_target, dimension="شعبه", baseline_total=baseline_total,
        )
    if salespeople:
        bundle.salesperson_targets = allocate_targets(
            salespeople, total_target, dimension="فروشنده", baseline_total=baseline_total,
        )


def _build_pacing(bundle: MetricsBundle, df: pd.DataFrame) -> None:
    """برنامه‌ی pacing ماه جاری بر اساس تارگت ماهانه‌ی متعادل."""
    if bundle.targets is None or bundle.forecast is None:
        return
    horizon = max(bundle.forecast.horizon, 1)
    monthly_target = bundle.targets.scenarios["balanced"].total / horizon
    bundle.pacing = build_pacing_plan(df, monthly_target, bundle.seasonality)


__all__ = ["MetricsBundle", "run_analysis"]
