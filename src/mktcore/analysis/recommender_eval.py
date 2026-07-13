"""خودتنظیمی و سنجش دقت پیشنهاد سبد — leave-last-basket-out زمانی.

آخرین سبد مشتریان نمونه پنهان می‌شود، مدل روی بقیه‌ی تاریخچه ساخته می‌شود و
چند پیکربندی وزن سیگنال‌ها روی همان holdout سنجیده می‌شود؛ بهترین پیکربندی
انتخاب و به مدل نهایی (روی کل داده) تزریق می‌شود — کاربر هیچ تنظیمی نمی‌کند.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..ingest.schema import ColumnRole, standard_column
from .market_basket import analyze_basket
from .next_purchase import _heuristic_basket
from .purchase_cycle import analyze_purchase_cycles
from .recommender import DEFAULT_WEIGHTS, build_recommender

_DATE = standard_column(ColumnRole.DATE)
_PRODUCT = standard_column(ColumnRole.PRODUCT)
_CUSTOMER = standard_column(ColumnRole.CUSTOMER_ID)
_ORDER = standard_column(ColumnRole.ORDER_ID)
_REVENUE = standard_column(ColumnRole.REVENUE)

# گرید پیکربندی‌های نام‌دار — kلیدها: cycle/cf/triple/pair/pop
WEIGHT_CONFIGS: dict[str, dict[str, float]] = {
    "متعادل": dict(DEFAULT_WEIGHTS),
    "CF-محور": {"cycle": 0.7, "cf": 1.0, "triple": 0.45, "pair": 0.30, "pop": 0.10},
    "چرخه-محور": {"cycle": 1.0, "cf": 0.35, "triple": 0.30, "pair": 0.20, "pop": 0.10},
    "مکمل-محور": {"cycle": 0.8, "cf": 0.5, "triple": 0.8, "pair": 0.6, "pop": 0.1},
    "بدون-چرخه": {"cycle": 0.3, "cf": 1.0, "triple": 0.5, "pair": 0.4, "pop": 0.15},
}


@dataclass
class BasketEvaluation:
    n_eval: int
    hitrate_at_5: float
    recall_at_5: float
    popularity_hitrate_at_5: float
    heuristic_hitrate_at_5: float
    best_config: str = "متعادل"
    configs_tested: int = 1
    coverage: int = 0  # تعداد مشتریانی که در مدل نهایی پیشنهاد دارند
    method: str = "temporal leave-last-basket-out"


def tune_and_evaluate(
    df: pd.DataFrame,
    *,
    max_customers: int = 5000,
    n: int = 5,
    min_baskets: int = 3,
) -> tuple[dict[str, float] | None, BasketEvaluation | None]:
    """انتخاب خودکار بهترین وزن‌ها + گزارش دقت؛ (None, None) اگر داده کافی نباشد."""
    if _CUSTOMER not in df.columns or _PRODUCT not in df.columns or df.empty:
        return None, None
    d = df.dropna(subset=[_CUSTOMER, _PRODUCT, _DATE]).copy()
    if d.empty:
        return None, None
    if len(d) > 600_000:
        max_customers = min(max_customers, 2500)

    d["_cid"] = d[_CUSTOMER].astype(str)
    if _ORDER in d.columns and d[_ORDER].notna().any():
        d["_bk"] = d["_cid"] + "|" + d[_ORDER].astype(str)
    else:
        d["_bk"] = d["_cid"] + "|" + d[_DATE].dt.normalize().astype(str)

    d["_bdate"] = d.groupby("_bk")[_DATE].transform("max")
    baskets_per_cust = d.groupby("_cid")["_bk"].nunique()
    eligible = baskets_per_cust[baskets_per_cust >= min_baskets].index.to_numpy()
    if len(eligible) < 30:
        return None, None

    rng = np.random.default_rng(42)
    eligible = np.sort(eligible)
    sample = set(eligible[rng.permutation(len(eligible))[:max_customers]])

    last_bdate = d.groupby("_cid")["_bdate"].transform("max")
    is_last_basket = (d["_bdate"] == last_bdate) & d["_cid"].isin(sample)
    truth_df = d[is_last_basket]
    train = d[~is_last_basket].drop(columns=["_bk", "_bdate"])

    truth: dict[str, set[str]] = (
        truth_df.groupby("_cid")[_PRODUCT]
        .agg(lambda s: {str(x) for x in s if pd.notna(x)})
        .to_dict()
    )
    train_ids = set(train["_cid"].unique())
    eval_ids = sorted(cid for cid in truth if cid in train_ids and truth[cid])
    if len(eval_ids) < 30:
        return None, None
    train = train.drop(columns=["_cid"])

    # بازسازی کامل روی train (بدون نشت)
    basket_tr = analyze_basket(train)
    cycles_tr = analyze_purchase_cycles(train, basket_tr)
    rec_tr = build_recommender(train, cycles=cycles_tr, basket=basket_tr)

    if _REVENUE in train.columns:
        pop = [str(p) for p in train.groupby(_PRODUCT)[_REVENUE].sum().nlargest(n).index]
    else:
        pop = [str(p) for p in train.groupby(_PRODUCT).size().nlargest(n).index]

    heuristic = _heuristic_basket(
        train.dropna(subset=[_CUSTOMER, _DATE]), set(eval_ids),
        cycles=cycles_tr, basket=basket_tr, top_products=pop[:3],
    )

    def _metrics(preds: dict[str, list[str]]) -> tuple[float, float]:
        hits, recalls = [], []
        for cid in eval_ids:
            t = truth[cid]
            p = set(preds.get(cid, [])[:n])
            inter = len(t & p)
            hits.append(1.0 if inter else 0.0)
            recalls.append(inter / min(len(t), n))
        return float(np.mean(hits)), float(np.mean(recalls))

    hr_pop, _ = _metrics({cid: pop for cid in eval_ids})
    hr_heur, _ = _metrics(heuristic)

    # ---------------------------- آزمون گرید وزن‌ها روی همان holdout (خودتنظیمی)
    best_name, best_hr, best_rc = "متعادل", -1.0, -1.0
    if rec_tr.available:
        for name, weights in WEIGHT_CONFIGS.items():
            rec_tr.weights = {**DEFAULT_WEIGHTS, **weights}
            preds = {cid: [r.product for r in recs]
                     for cid, recs in rec_tr.recommend_many(eval_ids, n=n).items()}
            hr, rc = _metrics(preds)
            if (hr, rc) > (best_hr, best_rc):
                best_name, best_hr, best_rc = name, hr, rc
        best_weights = {**DEFAULT_WEIGHTS, **WEIGHT_CONFIGS[best_name]}
        configs_tested = len(WEIGHT_CONFIGS)
    else:
        best_weights = None
        best_hr, best_rc = _metrics(heuristic)
        configs_tested = 1

    evaluation = BasketEvaluation(
        n_eval=len(eval_ids),
        hitrate_at_5=round(best_hr, 4),
        recall_at_5=round(best_rc, 4),
        popularity_hitrate_at_5=round(hr_pop, 4),
        heuristic_hitrate_at_5=round(hr_heur, 4),
        best_config=best_name,
        configs_tested=configs_tested,
    )
    return best_weights, evaluation


__all__ = ["BasketEvaluation", "WEIGHT_CONFIGS", "tune_and_evaluate"]
