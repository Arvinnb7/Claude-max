"""انتخاب مدل پیش‌بینی و اعتبارسنجی با backtest (rolling-origin)."""

from __future__ import annotations

import pandas as pd

from ..ingest.schema import ColumnRole, standard_column
from .base import ForecastResult, mape, rmse
from .prophet_model import ProphetForecaster
from .stats_model import StatsForecaster

_DATE = standard_column(ColumnRole.DATE)
_REVENUE = standard_column(ColumnRole.REVENUE)


def _to_series(df: pd.DataFrame, freq: str) -> pd.Series:
    return df.set_index(_DATE)[_REVENUE].resample(freq).sum().astype(float)


def _backtest(forecaster, series: pd.Series, freq: str, *, holdout: int) -> dict[str, float]:
    """اعتبارسنجی ساده: کنار گذاشتن `holdout` دوره‌ی آخر و سنجش خطا."""
    if len(series) <= holdout + 3:
        return {}
    train, test = series.iloc[:-holdout], series.iloc[-holdout:]
    try:
        fc = forecaster.fit_predict(train, holdout, freq=freq)
        pred = fc.yhat.copy()
        pred.index = test.index
        return {"MAPE": mape(test, pred), "RMSE": rmse(test, pred)}
    except Exception:
        return {}


def choose_and_forecast(
    df: pd.DataFrame,
    *,
    horizon: int = 6,
    freq: str = "ME",
    prefer_prophet: bool = True,
) -> ForecastResult:
    """انتخاب بهترین مدل بر اساس طول داده و backtest، سپس پیش‌بینی.

    اگر Prophet نصب باشد و داده کافی باشد، با ETS مقایسه می‌شود و مدل با
    کمترین MAPE در backtest انتخاب می‌گردد؛ در غیر این صورت ETS/روند خطی.
    """
    series = _to_series(df, freq)
    series = series[series.index.notna()]
    holdout = min(max(horizon, 3), max(len(series) // 4, 1))

    candidates: list = [StatsForecaster()]
    if prefer_prophet and ProphetForecaster.is_available() and len(series) >= 24:
        candidates.append(ProphetForecaster())

    best: ForecastResult | None = None
    best_mape = float("inf")
    for fc_model in candidates:
        metrics = _backtest(fc_model, series, freq, holdout=holdout)
        try:
            result = fc_model.fit_predict(series, horizon, freq=freq)
        except Exception:
            continue
        result.backtest_metrics = metrics
        m = metrics.get("MAPE", float("inf"))
        if m < best_mape or best is None:
            best_mape = m
            best = result

    if best is None:  # تضمین خروجی
        best = StatsForecaster().fit_predict(series, horizon, freq=freq)
    return best


__all__ = ["choose_and_forecast"]
