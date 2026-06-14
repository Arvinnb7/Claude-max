"""پیش‌بینی با statsmodels (Exponential Smoothing / ETS) — همیشه در دسترس."""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd

from .base import Forecaster, ForecastResult


class StatsForecaster(Forecaster):
    """ETS (Holt-Winters) با fallback به روند خطی برای سری‌های کوتاه."""

    name = "ETS (statsmodels)"

    def fit_predict(self, series: pd.Series, horizon: int, *, freq: str = "ME") -> ForecastResult:
        series = series.astype(float).asfreq(freq) if series.index.freq is None else series
        series = series.fillna(0.0)
        idx_future = pd.date_range(series.index[-1], periods=horizon + 1, freq=freq)[1:]

        seasonal_periods = 12 if freq in ("M", "ME") else (7 if freq == "D" else None)
        use_seasonal = seasonal_periods is not None and len(series) >= 2 * seasonal_periods

        try:
            from statsmodels.tsa.holtwinters import ExponentialSmoothing

            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                model = ExponentialSmoothing(
                    series,
                    trend="add",
                    seasonal="add" if use_seasonal else None,
                    seasonal_periods=seasonal_periods if use_seasonal else None,
                    initialization_method="estimated",
                ).fit()
            yhat = model.forecast(horizon)
            resid_std = float(np.nanstd(model.resid)) if hasattr(model, "resid") else 0.0
            model_name = self.name + (" فصلی" if use_seasonal else "")
        except Exception:
            # fallback: روند خطی ساده
            yhat, resid_std = self._linear_fallback(series, idx_future)
            model_name = "روند خطی"

        yhat.index = idx_future
        margin = 1.28 * resid_std  # تقریباً بازه‌ی ۸۰٪
        lower = (yhat - margin).clip(lower=0)
        upper = yhat + margin

        return ForecastResult(
            yhat=yhat,
            lower=lower,
            upper=upper,
            model_name=model_name,
            freq=freq,
            history=series,
        )

    @staticmethod
    def _linear_fallback(series: pd.Series, idx_future: pd.DatetimeIndex) -> tuple[pd.Series, float]:
        y = series.values.astype(float)
        x = np.arange(len(y))
        if len(y) >= 2:
            coef = np.polyfit(x, y, 1)
            fitted = np.polyval(coef, x)
            resid_std = float(np.std(y - fitted))
            future_x = np.arange(len(y), len(y) + len(idx_future))
            pred = np.polyval(coef, future_x)
        else:
            pred = np.repeat(y[-1] if len(y) else 0.0, len(idx_future))
            resid_std = 0.0
        return pd.Series(np.clip(pred, 0, None), index=idx_future), resid_std


__all__ = ["StatsForecaster"]
