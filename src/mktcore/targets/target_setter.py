"""تارگت‌گذاری خودکار بر اساس پیش‌بینی و عملکرد تاریخی.

سه سناریو تولید می‌شود: محافظه‌کار (کف بازه‌ی اطمینان)، متعادل (پیش‌بینی + رشد
ملایم) و جسورانه (کشش متصل به بهترین رشد تاریخی). منطق آماری هر سناریو ثبت
می‌شود تا مدل بتواند آن را به زبان مدیر مارکتینگ توجیه کند.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from ..analysis.kpis import KPISet
from ..forecasting.base import ForecastResult


@dataclass
class TargetScenario:
    name: str  # کلید: conservative/balanced/ambitious
    name_fa: str
    per_period: dict[str, float] = field(default_factory=dict)
    total: float = 0.0
    uplift_vs_forecast: float = 0.0  # نسبت به مجموع پیش‌بینی
    rationale: str = ""


@dataclass
class TargetProposal:
    horizon: int
    forecast_total: float
    scenarios: dict[str, TargetScenario] = field(default_factory=dict)
    recommended: str = "balanced"

    def compact(self) -> dict:
        return {
            "افق": self.horizon,
            "مجموع_پیش‌بینی": round(self.forecast_total),
            "سناریوها": {
                s.name_fa: {
                    "مجموع_هدف": round(s.total),
                    "رشد_نسبت_به_پیش‌بینی": round(s.uplift_vs_forecast * 100, 1),
                    "منطق": s.rationale,
                }
                for s in self.scenarios.values()
            },
            "پیشنهادی": self.scenarios[self.recommended].name_fa if self.recommended in self.scenarios else None,
        }


def _series_to_dict(s: pd.Series) -> dict[str, float]:
    return {str(k.date()): round(float(v)) for k, v in s.items()}


def propose_targets(
    forecast: ForecastResult,
    kpis: KPISet,
    *,
    balanced_uplift: float = 0.10,
) -> TargetProposal:
    """تولید سه سناریوی تارگت بر اساس پیش‌بینی و KPIها."""
    yhat = forecast.yhat
    forecast_total = float(yhat.sum())
    prop = TargetProposal(horizon=forecast.horizon, forecast_total=forecast_total)

    # کشش جسورانه: بیشینه‌ی بین رشد تاریخی YoY و یک حد پایه
    historical_growth = kpis.yoy_growth if (kpis.yoy_growth and kpis.yoy_growth > 0) else 0.0
    ambitious_uplift = max(historical_growth, balanced_uplift + 0.15)

    # محافظه‌کار: کف بازه‌ی اطمینان
    conservative = forecast.lower
    s_cons = TargetScenario(
        name="conservative",
        name_fa="محافظه‌کار",
        per_period=_series_to_dict(conservative),
        total=float(conservative.sum()),
        rationale="بر پایه‌ی کف بازه‌ی اطمینان پیش‌بینی؛ هدفی کم‌ریسک و تقریباً تضمینی.",
    )

    # متعادل: پیش‌بینی + رشد ملایم
    balanced = yhat * (1 + balanced_uplift)
    s_bal = TargetScenario(
        name="balanced",
        name_fa="متعادل",
        per_period=_series_to_dict(balanced),
        total=float(balanced.sum()),
        rationale=f"پیش‌بینی پایه به‌علاوه‌ی {round(balanced_uplift*100)}٪ رشد قابل‌دستیابی با بهبود عملکرد.",
    )

    # جسورانه: کشش متصل به بهترین رشد تاریخی
    ambitious = yhat * (1 + ambitious_uplift)
    s_amb = TargetScenario(
        name="ambitious",
        name_fa="جسورانه",
        per_period=_series_to_dict(ambitious),
        total=float(ambitious.sum()),
        rationale=(
            f"کشش {round(ambitious_uplift*100)}٪ متصل به بهترین نرخ رشد تاریخی؛ "
            "نیازمند سرمایه‌گذاری فعال در بازاریابی و کانال‌ها."
        ),
    )

    for s in (s_cons, s_bal, s_amb):
        s.uplift_vs_forecast = (s.total - forecast_total) / forecast_total if forecast_total else 0.0
        prop.scenarios[s.name] = s

    return prop


__all__ = ["propose_targets", "TargetProposal", "TargetScenario"]
