"""قرارداد پایه‌ی پیش‌بینی‌کننده‌ها و ساختار نتیجه."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import pandas as pd


@dataclass
class ForecastResult:
    """نتیجه‌ی پیش‌بینی: مقدار، بازه‌ی اطمینان و سنجه‌های اعتبارسنجی."""

    yhat: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    lower: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    upper: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    model_name: str = ""
    freq: str = "ME"
    backtest_metrics: dict[str, float] = field(default_factory=dict)
    history: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))

    @property
    def horizon(self) -> int:
        return len(self.yhat)

    @property
    def total_forecast(self) -> float:
        return float(self.yhat.sum())

    def compact(self) -> dict:
        """نمایش فشرده برای ارسال به مدل."""
        return {
            "مدل": self.model_name,
            "افق": self.horizon,
            "پیش‌بینی": {str(k.date()): round(float(v)) for k, v in self.yhat.items()},
            "کف_اطمینان": {str(k.date()): round(float(v)) for k, v in self.lower.items()},
            "سقف_اطمینان": {str(k.date()): round(float(v)) for k, v in self.upper.items()},
            "اعتبارسنجی": {k: round(v, 2) for k, v in self.backtest_metrics.items()},
        }


class Forecaster(ABC):
    """رابط مشترک پیش‌بینی‌کننده‌ها."""

    name: str = "base"

    @abstractmethod
    def fit_predict(self, series: pd.Series, horizon: int, *, freq: str = "ME") -> ForecastResult:
        """آموزش روی سری تاریخی و پیش‌بینی `horizon` دوره‌ی آینده."""


def mape(actual: pd.Series, predicted: pd.Series) -> float:
    """میانگین خطای نسبی مطلق (درصد)."""
    a, p = actual.align(predicted, join="inner")
    mask = a != 0
    if mask.sum() == 0:
        return float("nan")
    return float((abs((a[mask] - p[mask]) / a[mask])).mean() * 100)


def rmse(actual: pd.Series, predicted: pd.Series) -> float:
    """ریشه‌ی میانگین مربعات خطا."""
    a, p = actual.align(predicted, join="inner")
    if len(a) == 0:
        return float("nan")
    return float((((a - p) ** 2).mean()) ** 0.5)
