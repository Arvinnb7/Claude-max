"""سریال‌سازی MetricsBundle و StrategyReport به JSON مناسب فرانت‌اند.

برخلاف payload فشرده‌ی لایه‌ی هوش مصنوعی، این خروجی شامل سری‌های کامل برای رسم
نمودار و جدول‌هاست (با کلیدهای انگلیسی برای مصرف در React).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pandas as pd

if TYPE_CHECKING:
    from mktcore.ai.schemas import StrategyReport
    from mktcore.pipeline import MetricsBundle


def _series_points(s: pd.Series) -> list[dict[str, Any]]:
    """تبدیل سری زمانی به فهرست نقاط {date, value}."""
    out = []
    for idx, val in s.items():
        try:
            date = idx.date().isoformat()
        except AttributeError:
            date = str(idx)
        out.append({"date": date, "value": None if pd.isna(val) else float(val)})
    return out


def kpis_to_dict(k) -> dict:
    return {
        "total_revenue": k.total_revenue,
        "n_orders": k.n_orders,
        "n_customers": k.n_customers,
        "aov": k.aov,
        "avg_daily_revenue": k.avg_daily_revenue,
        "mom_growth": k.mom_growth,
        "yoy_growth": k.yoy_growth,
        "repeat_rate": k.repeat_rate,
        "gross_margin": k.gross_margin,
        "revenue_per_customer": k.revenue_per_customer,
        "flags": k.flags,
    }


def bundle_to_dict(bundle: MetricsBundle, *, currency: str = "تومان") -> dict:
    """تبدیل کامل bundle به دیکشنری قابل‌مصرف در فرانت."""
    seg = bundle.segmentation
    breakdowns: dict[str, list[dict]] = {}
    for dim, table in seg.breakdowns.items():
        first_col = table.columns[0]
        breakdowns[dim] = [
            {
                "label": str(r[first_col]),
                "revenue": float(r["revenue"]),
                "share": float(r["share"]),
                "cumulative_share": float(r["cumulative_share"]),
            }
            for _, r in table.iterrows()
        ]

    data: dict = {
        "currency": currency,
        "kpis": kpis_to_dict(bundle.kpis),
        "trends": {
            "daily": _series_points(bundle.trends.daily),
            "monthly": _series_points(bundle.trends.monthly),
            "moving_avg_30": _series_points(bundle.trends.moving_avg_30),
            "overall_trend_pct": bundle.trends.overall_trend_pct,
        },
        "segmentation": {
            "segments": [
                {"name": name, "size": seg.segment_sizes[name],
                 "revenue": seg.segment_revenue.get(name, 0.0)}
                for name in seg.segment_sizes
            ],
            "breakdowns": breakdowns,
        },
        "anomalies": [
            {"date": a.date, "value": a.value, "expected": a.expected,
             "z_score": a.z_score, "direction": a.direction}
            for a in bundle.anomalies.anomalies
        ],
        "seasonality": {
            "weekday_index": bundle.seasonality.weekday_index,
            "strength": bundle.seasonality.seasonality_strength,
            "peak_day": (max(bundle.seasonality.weekday_index, key=bundle.seasonality.weekday_index.get)
                         if bundle.seasonality.weekday_index else None),
        },
        "quality": {
            "n_rows": bundle.quality.n_rows,
            "date_min": bundle.quality.date_min,
            "date_max": bundle.quality.date_max,
            "span_days": bundle.quality.span_days,
            "warnings": bundle.quality.warnings,
        },
    }

    if bundle.forecast is not None:
        fc = bundle.forecast
        data["forecast"] = {
            "model_name": fc.model_name,
            "horizon": fc.horizon,
            "total": fc.total_forecast,
            "history": _series_points(fc.history),
            "yhat": _series_points(fc.yhat),
            "lower": _series_points(fc.lower),
            "upper": _series_points(fc.upper),
            "backtest": fc.backtest_metrics,
        }

    if bundle.targets is not None:
        tp = bundle.targets
        data["targets"] = {
            "horizon": tp.horizon,
            "forecast_total": tp.forecast_total,
            "recommended": tp.recommended,
            "scenarios": [
                {
                    "key": sc.name,
                    "name_fa": sc.name_fa,
                    "total": sc.total,
                    "uplift_vs_forecast": sc.uplift_vs_forecast,
                    "rationale": sc.rationale,
                    "per_period": [{"date": d, "value": v} for d, v in sc.per_period.items()],
                }
                for sc in tp.scenarios.values()
            ],
        }

    return data


def strategy_to_dict(report: StrategyReport) -> dict:
    """تبدیل گزارش استراتژی به دیکشنری."""
    return {
        "executive_summary": report.executive_summary,
        "factor_analysis": [
            {"factor": f.factor, "finding": f.finding, "impact": f.impact}
            for f in report.factor_analysis
        ],
        "target_rationale": report.target_rationale,
        "recommendations": [
            {"title": r.title, "priority": r.priority, "rationale": r.rationale,
             "expected_impact": r.expected_impact, "effort": r.effort}
            for r in report.recommendations
        ],
        "risks": report.risks,
    }


__all__ = ["bundle_to_dict", "strategy_to_dict", "kpis_to_dict"]
