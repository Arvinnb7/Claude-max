"""پیش‌بینی با Prophet (اختیاری — نیازمند گروه `forecast`)."""

from __future__ import annotations

import pandas as pd

from .base import Forecaster, ForecastResult


class ProphetForecaster(Forecaster):
    """پیش‌بینی‌کننده‌ی Prophet با بازه‌ی اطمینان ۸۰٪."""

    name = "Prophet"

    @staticmethod
    def is_available() -> bool:
        try:
            import prophet  # noqa: F401

            return True
        except ImportError:
            return False

    def fit_predict(self, series: pd.Series, horizon: int, *, freq: str = "ME") -> ForecastResult:  # pragma: no cover - اختیاری
        from prophet import Prophet

        dfp = pd.DataFrame({"ds": series.index, "y": series.values.astype(float)})
        m = Prophet(interval_width=0.8, yearly_seasonality=True, weekly_seasonality=(freq == "D"))
        m.fit(dfp)
        future = m.make_future_dataframe(periods=horizon, freq=freq)
        fc = m.predict(future).set_index("ds").tail(horizon)

        return ForecastResult(
            yhat=fc["yhat"].clip(lower=0),
            lower=fc["yhat_lower"].clip(lower=0),
            upper=fc["yhat_upper"],
            model_name=self.name,
            freq=freq,
            history=series,
        )


__all__ = ["ProphetForecaster"]
