"""خودسنجی احتمال خرید: کالیبراسیون روی داده‌ی خود کاربر (بدون نشت).

برش زمانی در `data_max − window` → مدل فقط با داده‌ی تا آن نقطه بازساخته می‌شود →
احتمال خرید پیش‌بینی می‌شود → با خرید واقعی در پنجره مقایسه می‌شود.
معیار: Brier score در برابر baseline «نرخ پایه» + جدول قابلیت‌اعتماد (reliability).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..ingest.schema import ColumnRole, standard_column

_DATE = standard_column(ColumnRole.DATE)
_CUSTOMER = standard_column(ColumnRole.CUSTOMER_ID)

# سطل‌های ثابت جدول قابلیت‌اعتماد
_BINS = [0.0, 0.1, 0.3, 0.5, 0.7, 1.0001]


@dataclass
class ProbabilityCalibration:
    n_eval: int
    window_days: int
    brier: float  # خطای مدل (کمتر = بهتر)
    baseline_brier: float  # خطای حدس «نرخ پایه» برای همه
    actual_rate: float  # نسبت مشتریانی که واقعاً خرید کردند
    mean_predicted: float  # میانگین احتمال پیش‌بینی‌شده
    bins: list[dict] = field(default_factory=list)  # {از، تا، تعداد، پیش‌بینی، واقعی}

    @property
    def beats_baseline(self) -> bool:
        return self.brier < self.baseline_brier

    @property
    def bias(self) -> float:
        """اختلاف میانگین پیش‌بینی و واقعیت (منفی = کم‌برآورد)."""
        return self.mean_predicted - self.actual_rate


def evaluate_probability(
    df: pd.DataFrame,
    *,
    window_days: int = 30,
    min_customers: int = 50,
) -> ProbabilityCalibration | None:
    """کالیبراسیون احتمال خرید؛ None اگر داده برای آزمون بی‌نشت کافی نباشد."""
    if _CUSTOMER not in df.columns or _DATE not in df.columns or df.empty:
        return None
    d = df.dropna(subset=[_CUSTOMER, _DATE])
    if d.empty:
        return None

    data_max = d[_DATE].max()
    cutoff = data_max - pd.Timedelta(days=window_days)
    train = d[d[_DATE] <= cutoff]
    future = d[d[_DATE] > cutoff]
    if train.empty or future.empty:
        return None
    if int(train[_CUSTOMER].nunique()) < min_customers:
        return None

    # وارد کردن دیرهنگام برای پرهیز از حلقه‌ی import
    from .next_purchase import predict_next_purchases

    pred = predict_next_purchases(train, window_days=window_days)
    rows = [(c.customer_id, c.buy_probability_30d) for c in pred.customers
            if c.buy_probability_30d is not None]
    if len(rows) < min_customers:
        return None

    buyers = set(future[_CUSTOMER].astype(str).unique())
    ids = np.array([r[0] for r in rows], dtype=object)
    p = np.array([r[1] for r in rows], dtype=float)
    y = np.array([1.0 if cid in buyers else 0.0 for cid in ids])

    base_rate = float(y.mean())
    brier = float(np.mean((p - y) ** 2))
    baseline = float(np.mean((base_rate - y) ** 2))

    bins: list[dict] = []
    idx = np.digitize(p, _BINS) - 1
    for b in range(len(_BINS) - 1):
        sel = idx == b
        n = int(sel.sum())
        if not n:
            continue
        bins.append({
            "از": _BINS[b],
            "تا": min(_BINS[b + 1], 1.0),
            "تعداد": n,
            "پیش‌بینی": round(float(p[sel].mean()), 3),
            "واقعی": round(float(y[sel].mean()), 3),
        })

    return ProbabilityCalibration(
        n_eval=len(rows),
        window_days=window_days,
        brier=round(brier, 4),
        baseline_brier=round(baseline, 4),
        actual_rate=round(base_rate, 4),
        mean_predicted=round(float(p.mean()), 4),
        bins=bins,
    )


__all__ = ["ProbabilityCalibration", "evaluate_probability"]
