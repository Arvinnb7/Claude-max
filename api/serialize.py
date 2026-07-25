"""سریال‌سازی MetricsBundle و StrategyReport به JSON مناسب فرانت‌اند.

برخلاف payload فشرده‌ی لایه‌ی هوش مصنوعی، این خروجی شامل سری‌های کامل برای رسم
نمودار و جدول‌هاست (با کلیدهای انگلیسی برای مصرف در React).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pandas as pd

if TYPE_CHECKING:
    from mktcore.ai.schemas import StrategyReport
from mktcore.analysis.inventory import SUPPLY_CAVEAT
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
        "gross_sales": getattr(k, "gross_sales", k.total_revenue),
        "returns_total": getattr(k, "returns_total", 0.0),
        "returns_count": getattr(k, "returns_count", 0),
        "return_rate": getattr(k, "return_rate", None),
        "net_sales": getattr(k, "net_sales", k.total_revenue),
        "discount_total": getattr(k, "discount_total", None),
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
            "partial_month": getattr(bundle.trends, "partial_month", None),
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

    # --- تحلیل‌های پیشرفته ---
    if bundle.products.available:
        data["products"] = [
            {"product": p.product, "revenue": p.revenue, "quantity": p.quantity,
             "orders": p.orders, "share": p.share, "abc_class": p.abc_class, "growth": p.growth}
            for p in bundle.products.top(15)
        ]

    if bundle.basket.available:
        data["basket"] = {
            "avg_basket_size": bundle.basket.avg_basket_size,
            "rules": [
                {"antecedent": r.antecedent, "consequent": r.consequent,
                 "confidence": r.confidence, "lift": r.lift, "support": r.support,
                 "pair_count": r.pair_count}
                for r in bundle.basket.top(12)
            ],
        }

    if bundle.sequences.available:
        data["sequences"] = [
            {"antecedent": p.antecedent, "consequent": p.consequent,
             "completion_rate": p.completion_rate, "median_lag_days": p.median_lag_days,
             "n_antecedent_buyers": p.n_antecedent_buyers,
             "incomplete_count": len(p.incomplete_customers)}
            for p in bundle.sequences.top(8)
        ]

    if bundle.next_purchase.available:
        data["next_purchase"] = [
            {"customer_id": c.customer_id, "predicted_next_date": c.predicted_next_date,
             "status": c.status, "overdue_days": c.overdue_days,
             "likely_products": c.likely_products, "expected_value": c.expected_value,
             "buy_probability_30d": c.buy_probability_30d,
             "churn_risk": getattr(c, "churn_risk", None),
             "expected_value_30d": getattr(c, "expected_value_30d", None),
             "clv_12m": getattr(c, "clv_12m", None),
             "value_confidence": getattr(c, "value_confidence", None),
             "recommendations": [{"product": r.product, "reason": r.reason}
                                 for r in c.recommendations]}
            for c in bundle.next_purchase.due_now(30)
        ]

    if bundle.basket_eval is not None:
        ev = bundle.basket_eval
        data["basket_eval"] = {
            "n_eval": ev.n_eval,
            "hitrate_at_5": ev.hitrate_at_5,
            "recall_at_5": ev.recall_at_5,
            "popularity_hitrate_at_5": ev.popularity_hitrate_at_5,
            "heuristic_hitrate_at_5": ev.heuristic_hitrate_at_5,
            "best_config": ev.best_config,
            "coverage": ev.coverage,
        }

    pc = bundle.purchase_cycle
    if pc.available:
        data["purchase_cycle"] = {
            "products": [
                {"product": c.product, "product_type": c.product_type,
                 "repurchase_rate": c.repurchase_rate, "median_cycle_days": c.median_cycle_days,
                 "n_buyers": c.n_buyers}
                for c in pc.product_cycles[:150]
            ],
            "notifications": [
                {"customer_id": n.customer_id, "product": n.product, "cycle_days": n.cycle_days,
                 "days_offset": n.days_offset, "status": n.status, "message": n.message()}
                for n in pc.overdue(40)
            ],
            "onetime_targets": [
                {"product": t.product, "gateway_products": t.gateway_products,
                 "potential_count": len(t.potential_customers), "existing_buyers": t.existing_buyers}
                for t in pc.onetime_targets
            ],
        }

    perf = bundle.performance
    if perf.has_branch or perf.has_salesperson:
        def _ent(items):
            return [
                {"name": e.name, "revenue": e.revenue, "orders": e.orders,
                 "customers": e.customers, "aov": e.aov, "share": e.share,
                 "growth": e.growth, "rank": e.rank}
                for e in items
            ]
        data["performance"] = {
            "branches": _ent(perf.by_branch) if perf.has_branch else [],
            "salespeople": _ent(perf.by_salesperson) if perf.has_salesperson else [],
        }

    if bundle.inventory.available:
        data["inventory_caveat"] = SUPPLY_CAVEAT
        data["inventory"] = [
            {"product": i.product, "recommendation": i.recommendation,
             "growth": i.growth, "revenue_share": i.revenue_share,
             "margin": i.margin, "reason": i.reason}
            for i in bundle.inventory.items[:150]
        ]

    if bundle.diagnostics.period_label:
        d = bundle.diagnostics
        data["diagnostics"] = {
            "overall_pct": d.overall_pct,
            "period_label": d.period_label,
            "is_declining": d.is_declining,
            "drivers": [
                {"dimension": dr.dimension, "label": dr.label, "pct_change": dr.pct_change,
                 "contribution": dr.contribution_to_decline}
                for dr in d.drivers
            ],
        }

    def _alloc(a):
        return {
            "dimension": a.dimension, "total_target": a.total_target,
            "entities": [
                {"name": e.name, "target": e.target, "growth_required": e.growth_required,
                 "reward_tiers": e.reward_tiers}
                for e in a.entities
            ],
        }
    if bundle.branch_targets is not None:
        data["branch_targets"] = _alloc(bundle.branch_targets)
    if bundle.salesperson_targets is not None:
        data["salesperson_targets"] = _alloc(bundle.salesperson_targets)

    if bundle.pacing is not None:
        p = bundle.pacing
        data["pacing"] = {
            "monthly_target": p.monthly_target, "achieved": p.achieved, "gap": p.gap,
            "days_remaining": p.days_remaining, "required_daily": p.required_daily,
            "on_track": p.on_track, "pace_ratio": p.pace_ratio,
            "week_plan": [
                {"date": d.date, "weekday": d.weekday, "target_revenue": d.target_revenue,
                 "emphasis": d.emphasis}
                for d in p.week_plan
            ],
        }

    if getattr(bundle, "validation", None) is not None:
        v = bundle.validation
        data["validation"] = {
            "status": v.status,
            "checks": [{"id": c.check_id, "title": c.title,
                        "status": c.status, "detail": c.detail} for c in v.checks],
        }

    ap = getattr(bundle, "actions", None)
    if ap is not None and ap.available:
        data["actions"] = {
            "total_value": ap.total_value,
            "summary": ap.summary,
            "items": [
                {"rank": a.rank, "kind": a.kind, "customer_id": a.customer_id,
                 "product": a.product, "action": a.action_fa, "reason": a.reason_fa,
                 "value_rial": a.value_rial, "value_kind": a.value_kind,
                 "confidence": a.confidence, "probability": a.probability,
                 "owner": a.owner, "last_purchase": a.last_purchase}
                for a in ap.top(50)
            ],
        }

    cal = getattr(bundle, "probability_calibration", None)
    if cal is not None:
        data["probability_calibration"] = {
            "n_eval": cal.n_eval,
            "window_days": cal.window_days,
            "brier": cal.brier,
            "baseline_brier": cal.baseline_brier,
            "beats_baseline": cal.beats_baseline,
            "actual_rate": cal.actual_rate,
            "mean_predicted": cal.mean_predicted,
            "bias": round(cal.bias, 4),
            "bins": cal.bins,
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


def campaign_to_dict(plan) -> dict:
    """تبدیل CampaignPlan به دیکشنری برای فرانت."""
    return {
        "summary": plan.summary,
        "audiences": [
            {
                "segment_name": a.segment_name,
                "audience_definition": a.audience_definition,
                "objective": a.objective,
                "offer": a.offer,
                "success_kpi": a.success_kpi,
                "channels": [
                    {"channel": c.channel, "subject": c.subject, "body": c.body,
                     "call_script": c.call_script, "timing": c.timing,
                     "personalization_vars": c.personalization_vars}
                    for c in a.channels
                ],
            }
            for a in plan.audiences
        ],
        "weekly_actions": [
            {"day": w.day, "focus": w.focus, "actions": w.actions}
            for w in plan.weekly_actions
        ],
    }


__all__ = ["bundle_to_dict", "strategy_to_dict", "kpis_to_dict", "campaign_to_dict"]
