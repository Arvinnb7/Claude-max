"""سنجش دقت واقعی پیشنهاد سبد — leave-last-basket-out زمانی روی داده‌ی خود کاربر.

آخرین سبد مشتریان نمونه پنهان می‌شود، مدل روی بقیه‌ی تاریخچه ساخته می‌شود و
پیش‌بینی top-N با سبد واقعیِ پنهان‌شده مقایسه می‌شود — بدون هیچ نشت داده.
دو baseline: پرفروش‌های train و منطق ابتکاری قدیمی (بدون CF).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..ingest.schema import ColumnRole, standard_column
from .market_basket import analyze_basket
from .next_purchase import _heuristic_basket
from .purchase_cycle import analyze_purchase_cycles
from .recommender import build_recommender

_DATE = standard_column(ColumnRole.DATE)
_PRODUCT = standard_column(ColumnRole.PRODUCT)
_CUSTOMER = standard_column(ColumnRole.CUSTOMER_ID)
_ORDER = standard_column(ColumnRole.ORDER_ID)
_REVENUE = standard_column(ColumnRole.REVENUE)


@dataclass
class BasketEvaluation:
    n_eval: int
    hitrate_at_5: float
    recall_at_5: float
    popularity_hitrate_at_5: float
    heuristic_hitrate_at_5: float
    method: str = "temporal leave-last-basket-out"


def evaluate_recommender(
    df: pd.DataFrame,
    *,
    max_customers: int = 2000,
    n: int = 5,
    min_baskets: int = 3,
) -> BasketEvaluation | None:
    """HitRate@n و Recall@n مدل در برابر baselineها؛ None اگر داده کافی نباشد."""
    if _CUSTOMER not in df.columns or _PRODUCT not in df.columns or df.empty:
        return None
    d = df.dropna(subset=[_CUSTOMER, _PRODUCT, _DATE]).copy()
    if d.empty:
        return None
    if len(d) > 600_000:
        max_customers = min(max_customers, 1000)

    d["_cid"] = d[_CUSTOMER].astype(str)
    if _ORDER in d.columns and d[_ORDER].notna().any():
        d["_bk"] = d["_cid"] + "|" + d[_ORDER].astype(str)
    else:
        d["_bk"] = d["_cid"] + "|" + d[_DATE].dt.normalize().astype(str)

    # رتبه‌ی زمانی سبدهای هر مشتری (وکتورایز)
    bmax = d.groupby("_bk")[_DATE].transform("max")
    d["_bdate"] = bmax
    baskets_per_cust = d.groupby("_cid")["_bk"].nunique()
    eligible = baskets_per_cust[baskets_per_cust >= min_baskets].index.to_numpy()
    if len(eligible) < 30:
        return None

    rng = np.random.default_rng(42)
    eligible = np.sort(eligible)
    sample = set(eligible[rng.permutation(len(eligible))[:max_customers]])

    # آخرین سبد هر مشتریِ نمونه = truth؛ بقیه = train
    last_bdate = d.groupby("_cid")["_bdate"].transform("max")
    is_last_basket = (d["_bdate"] == last_bdate) & d["_cid"].isin(sample)
    truth_df = d[is_last_basket]
    train = d[~is_last_basket].drop(columns=["_bk", "_bdate"])

    truth: dict[str, set[str]] = (
        truth_df.groupby("_cid")[_PRODUCT]
        .agg(lambda s: {str(x) for x in s if pd.notna(x)})
        .to_dict()
    )
    # مشتریانی که در train هنوز تاریخچه دارند
    train_ids = set(train["_cid"].unique())
    eval_ids = sorted(cid for cid in truth if cid in train_ids and truth[cid])
    if len(eval_ids) < 30:
        return None

    train = train.drop(columns=["_cid"])

    # بازسازی کامل روی train (بدون نشت)
    basket_tr = analyze_basket(train)
    cycles_tr = analyze_purchase_cycles(train, basket_tr)
    rec_tr = build_recommender(train, cycles=cycles_tr, basket=basket_tr)

    if _REVENUE in train.columns:
        pop = [str(p) for p in train.groupby(_PRODUCT)[_REVENUE].sum().nlargest(n).index]
    else:
        pop = [str(p) for p in train.groupby(_PRODUCT).size().nlargest(n).index]

    top_products = pop[:3]
    heuristic = _heuristic_basket(
        train.dropna(subset=[_CUSTOMER, _DATE]), set(eval_ids),
        cycles=cycles_tr, basket=basket_tr, top_products=top_products,
    )

    if rec_tr.available:
        model_preds = {cid: [r.product for r in recs]
                       for cid, recs in rec_tr.recommend_many(eval_ids, n=n).items()}
    else:
        model_preds = heuristic

    def _metrics(preds: dict[str, list[str]]) -> tuple[float, float]:
        hits, recalls = [], []
        for cid in eval_ids:
            t = truth[cid]
            p = set(preds.get(cid, [])[:n])
            inter = len(t & p)
            hits.append(1.0 if inter else 0.0)
            recalls.append(inter / min(len(t), n))
        return float(np.mean(hits)), float(np.mean(recalls))

    hr, rc = _metrics(model_preds)
    hr_pop, _ = _metrics({cid: pop for cid in eval_ids})
    hr_heur, _ = _metrics(heuristic)

    return BasketEvaluation(
        n_eval=len(eval_ids),
        hitrate_at_5=round(hr, 4),
        recall_at_5=round(rc, 4),
        popularity_hitrate_at_5=round(hr_pop, 4),
        heuristic_hitrate_at_5=round(hr_heur, 4),
    )


__all__ = ["BasketEvaluation", "evaluate_recommender"]
