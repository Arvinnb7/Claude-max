"""موتور پیشنهاد سبد شخصی‌سازی‌شده — فیلترینگ اشتراکی آیتم-آیتم + ترکیب سیگنال‌ها.

سیگنال‌ها و وزن‌ها (جمع امتیازِ نرمال‌شده؛ قطعی و توضیح‌پذیر):
1. «یادآوری چرخه» (۱٫۰): محصول مصرفی‌ای که خود مشتری در چرخه‌اش عقب است.
2. «مشتریان مشابه» (۰٫۵۵): CF آیتم-آیتم — ماتریس اسپارس مشتری×محصول با وزن
   تازگی (نیم‌عمر ۹۰ روز) و BM25، شباهت کسینوسی، top-K همسایه با گارد حداقل
   هم‌خریدار.
3. «مکمل خرید» (۰٫۴۵ سه‌تایی A+B→C / ۰٫۳۰ جفتی): قواعد انجمنی سبد اخیر مشتری.
4. «پرفروش» (۰٫۱۰): fallback برای مشتریان سرد.

اقلام قبلاً خریده‌شده حذف می‌شوند مگر محصول «مصرفی» باشد (بازخرید معنادار است).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy import sparse

from ..ingest.schema import ColumnRole, standard_column
from .market_basket import BasketAnalysis
from .purchase_cycle import CONSUMABLE, PurchaseCycleAnalysis

_DATE = standard_column(ColumnRole.DATE)
_PRODUCT = standard_column(ColumnRole.PRODUCT)
_CUSTOMER = standard_column(ColumnRole.CUSTOMER_ID)
_REVENUE = standard_column(ColumnRole.REVENUE)
_QTY = standard_column(ColumnRole.QUANTITY)

REASON_CYCLE = "یادآوری چرخه"
REASON_CF = "مشتریان مشابه"
REASON_COMPLEMENT = "مکمل خرید"
REASON_POPULAR = "پرفروش"

_W_CYCLE = 1.00
_W_CF = 0.55
_W_TRIPLE = 0.45
_W_PAIR = 0.30
_W_POPULAR = 0.10

_CHUNK = 256  # densify امتیازها فقط در chunkهای کوچک


@dataclass
class Recommendation:
    product: str
    score: float  # [0,1] تقریبی (جمع وزن‌دار سهم‌ها)
    reason: str


@dataclass
class BasketRecommender:
    available: bool = False
    item_index: list[str] = field(default_factory=list)
    cust_index: dict[str, int] = field(default_factory=dict)
    user_matrix: sparse.csr_matrix | None = None  # وزن‌های خام (برای امتیازدهی)
    sim_topk: sparse.csr_matrix | None = None  # آیتم×آیتم top-K
    consumable_mask: np.ndarray | None = None
    cycle_due: dict[str, list[tuple[str, float]]] = field(default_factory=dict)
    pair_complements: dict[str, list[tuple[str, float]]] = field(default_factory=dict)
    triple_rules: list = field(default_factory=list)
    recent_items: dict[str, list[str]] = field(default_factory=dict)
    popularity: list[str] = field(default_factory=list)

    def recommend(self, customer_id: str, n: int = 5) -> list[Recommendation]:
        return self.recommend_many([customer_id], n=n).get(str(customer_id), [])

    def recommend_many(self, customer_ids: Sequence[str],
                       n: int = 5) -> dict[str, list[Recommendation]]:
        ids = [str(c) for c in customer_ids]
        if not self.available:
            return {c: [] for c in ids}
        cf_scores = self._cf_scores(ids)
        out: dict[str, list[Recommendation]] = {}
        for cid in ids:
            out[cid] = self._fuse(cid, cf_scores.get(cid, {}), n)
        return out

    # ------------------------------------------------------------- CF داخلی
    def _cf_scores(self, ids: list[str]) -> dict[str, dict[str, float]]:
        """امتیاز CF هر مشتری برای اقلام کاندید (top-15 هر مشتری)."""
        rows = [(cid, self.cust_index[cid]) for cid in ids if cid in self.cust_index]
        result: dict[str, dict[str, float]] = {}
        if not rows or self.user_matrix is None or self.sim_topk is None:
            return result
        items = np.asarray(self.item_index, dtype=object)
        for start in range(0, len(rows), _CHUNK):
            chunk = rows[start:start + _CHUNK]
            r_idx = np.array([r for _, r in chunk])
            scores = (self.user_matrix[r_idx] @ self.sim_topk).toarray()
            bought = self.user_matrix[r_idx].toarray() > 0
            # حذف خریده‌شده‌ها مگر مصرفی
            scores[bought & ~self.consumable_mask[None, :]] = 0.0
            for i, (cid, _) in enumerate(chunk):
                row = scores[i]
                if row.max() <= 0:
                    continue
                k = min(15, np.count_nonzero(row))
                top = np.argpartition(row, -k)[-k:]
                mx = row[top].max()
                result[cid] = {str(items[j]): float(row[j] / mx)
                               for j in top if row[j] > 0}
        return result

    # ------------------------------------------------- ترکیب سیگنال‌ها (fusion)
    def _fuse(self, cid: str, cf: dict[str, float], n: int) -> list[Recommendation]:
        contrib: dict[str, dict[str, float]] = {}

        def add(product: str, amount: float, reason: str) -> None:
            contrib.setdefault(product, {})[reason] = max(
                contrib.get(product, {}).get(reason, 0.0), amount)

        for product, strength in self.cycle_due.get(cid, []):
            add(product, _W_CYCLE * strength, REASON_CYCLE)
        for product, score in cf.items():
            add(product, _W_CF * score, REASON_CF)

        recent = self.recent_items.get(cid, [])
        recent_set = set(recent)
        for tr in self.triple_rules:
            a, b = tr.antecedents
            if a in recent_set and b in recent_set and tr.consequent not in recent_set:
                add(tr.consequent, _W_TRIPLE * min(tr.confidence, 1.0), REASON_COMPLEMENT)
        for p in recent:
            for cons, rank_score in self.pair_complements.get(p, []):
                if cons not in recent_set:
                    add(cons, _W_PAIR * rank_score, REASON_COMPLEMENT)

        bought_all = self._bought_set(cid)
        for rank, p in enumerate(self.popularity):
            if p not in bought_all:
                add(p, _W_POPULAR * (1.0 - rank / max(len(self.popularity), 1)),
                    REASON_POPULAR)

        # حذف اقلام خریده‌شده‌ی غیرمصرفی از همه‌ی سیگنال‌ها (CF خودش حذف کرده)
        consumables = self._consumable_products()
        scored: list[tuple[float, str, str]] = []
        for product, parts in contrib.items():
            if product in bought_all and product not in consumables:
                # فقط «یادآوری چرخه» حق بازپیشنهاد قلم خریده‌شده را دارد
                if REASON_CYCLE not in parts:
                    continue
            total = sum(parts.values())
            reason = max(parts.items(), key=lambda kv: kv[1])[0]
            scored.append((total, product, reason))
        scored.sort(key=lambda t: (-t[0], t[1]))
        return [Recommendation(product=p, score=round(min(s, 1.0), 3), reason=r)
                for s, p, r in scored[:n]]

    def _bought_set(self, cid: str) -> set[str]:
        row = self.cust_index.get(cid)
        if row is None or self.user_matrix is None:
            return set()
        sl = self.user_matrix[row]
        return {self.item_index[j] for j in sl.indices}

    def _consumable_products(self) -> set[str]:
        if self.consumable_mask is None:
            return set()
        return {self.item_index[j] for j in np.flatnonzero(self.consumable_mask)}


def _bm25_weight(x: sparse.csr_matrix, k1: float = 1.2, b: float = 0.75) -> sparse.csr_matrix:
    """وزن‌دهی BM25 — اشباع خریدار عمده و نرمال‌سازی طول فعالیت کاربر."""
    n_users = x.shape[0]
    ni = np.diff((x > 0).tocsc().indptr).astype(float)
    idf = np.log1p((n_users - ni + 0.5) / (ni + 0.5))
    ulen = np.asarray(x.sum(axis=1)).ravel()
    avg = ulen.mean() if ulen.size and ulen.mean() > 0 else 1.0
    coo = x.tocoo()
    tf = coo.data
    denom = tf + k1 * (1.0 - b + b * ulen[coo.row] / avg)
    data = tf * (k1 + 1.0) / denom * idf[coo.col]
    return sparse.csr_matrix((data, (coo.row, coo.col)), shape=x.shape)


def _topk_rows(s: sparse.csr_matrix, k: int) -> sparse.csr_matrix:
    """نگه‌داشتن k مقدار بزرگ هر سطر از یک ماتریس اسپارس."""
    s = s.tocsr()
    data, indices, indptr = [], [], [0]
    for i in range(s.shape[0]):
        row = s.data[s.indptr[i]:s.indptr[i + 1]]
        cols = s.indices[s.indptr[i]:s.indptr[i + 1]]
        if len(row) > k:
            keep = np.argpartition(row, -k)[-k:]
            row, cols = row[keep], cols[keep]
        data.append(row)
        indices.append(cols)
        indptr.append(indptr[-1] + len(row))
    if not data:
        return s
    return sparse.csr_matrix(
        (np.concatenate(data), np.concatenate(indices), np.array(indptr)),
        shape=s.shape,
    )


def build_recommender(
    df: pd.DataFrame,
    *,
    cycles: PurchaseCycleAnalysis | None = None,
    basket: BasketAnalysis | None = None,
    half_life_days: float = 90.0,
    top_k: int = 20,
    min_cobuyers: int = 3,
    max_products: int = 20_000,
) -> BasketRecommender:
    """ساخت موتور پیشنهاد از دیتافریم پاک‌شده (وکتورایز، بدون dep جدید)."""
    rec = BasketRecommender()
    if _CUSTOMER not in df.columns or _PRODUCT not in df.columns or df.empty:
        return rec
    d = df.dropna(subset=[_CUSTOMER, _PRODUCT, _DATE])
    if d.empty:
        return rec

    cust = d[_CUSTOMER].astype(str).astype("category")
    prod = d[_PRODUCT].astype(str).astype("category")
    n_users = cust.cat.categories.size
    n_items = prod.cat.categories.size
    if n_users < 50 or n_items < 5:
        return rec  # داده برای شخصی‌سازی کافی نیست → fallback به روش قدیمی

    # سقف تعداد محصول (ایمنی حافظه؛ در عمل بعید)
    if n_items > max_products:
        top_prods = set(d.groupby(_PRODUCT).size().nlargest(max_products).index.astype(str))
        d = d[d[_PRODUCT].astype(str).isin(top_prods)]
        cust = d[_CUSTOMER].astype(str).astype("category")
        prod = d[_PRODUCT].astype(str).astype("category")
        n_users, n_items = cust.cat.categories.size, prod.cat.categories.size

    # ------------------------------------------- ماتریس تعامل با وزن تازگی
    age = (d[_DATE].max() - d[_DATE]).dt.days.to_numpy(dtype=float)
    w = 0.5 ** (age / half_life_days)
    if _QTY in d.columns and d[_QTY].notna().any():
        q = pd.to_numeric(d[_QTY], errors="coerce").fillna(1).clip(lower=1).to_numpy(dtype=float)
        w = w * (1.0 + np.log1p(q - 1.0))
    x = sparse.coo_matrix(
        (w, (cust.cat.codes.to_numpy(), prod.cat.codes.to_numpy())),
        shape=(n_users, n_items),
    ).tocsr()
    x.sum_duplicates()

    # ------------------------------------------------ شباهت آیتم-آیتم (CF)
    from sklearn.metrics.pairwise import cosine_similarity

    xw = _bm25_weight(x)
    sim = cosine_similarity(xw.T.tocsr(), dense_output=False)
    xb = (x > 0).astype(np.float32)
    cobuy = (xb.T @ xb) >= min_cobuyers
    sim = sim.multiply(cobuy)
    sim = sparse.csr_matrix(sim)
    sim.setdiag(0.0)
    sim.eliminate_zeros()
    sim = _topk_rows(sim, top_k)

    rec.available = True
    rec.item_index = [str(c) for c in prod.cat.categories]
    rec.cust_index = {str(c): i for i, c in enumerate(cust.cat.categories)}
    rec.user_matrix = x
    rec.sim_topk = sim

    # ------------------------------------------------------- سیگنال‌های جانبی
    mask = np.zeros(n_items, dtype=bool)
    item_pos = {p: i for i, p in enumerate(rec.item_index)}
    if cycles is not None:
        for pc in getattr(cycles, "product_cycles", []):
            if pc.product_type == CONSUMABLE and str(pc.product) in item_pos:
                mask[item_pos[str(pc.product)]] = True
        for note in getattr(cycles, "notifications", []):
            if note.status in ("عقب‌افتاده", "نزدیک"):
                strength = float(np.clip(
                    0.5 + note.days_offset / (2.0 * max(note.cycle_days, 1.0)), 0.0, 1.0))
                rec.cycle_due.setdefault(str(note.customer_id), []).append(
                    (str(note.product), strength))
    rec.consumable_mask = mask

    if basket is not None and basket.available:
        by_ante: dict[str, list] = {}
        for r in basket.rules:
            by_ante.setdefault(r.antecedent, []).append(r)
        for ante, rules in by_ante.items():
            rules.sort(key=lambda r: -r.lift)
            rec.pair_complements[ante] = [
                (r.consequent, 1.0 / (i + 1)) for i, r in enumerate(rules[:3])
            ]
        rec.triple_rules = list(getattr(basket, "triple_rules", []))

    # سبد/اقلام اخیر هر مشتری (برای قواعد مکمل) — آخرین تاریخ خرید هر مشتری
    last_date = d.groupby(_CUSTOMER)[_DATE].transform("max")
    recent = d[d[_DATE] == last_date]
    rec.recent_items = (
        recent.groupby(_CUSTOMER)[_PRODUCT]
        .agg(lambda s: [str(v) for v in dict.fromkeys(s.dropna())][:10])
        .rename(index=str)
        .to_dict()
    )

    if _REVENUE in d.columns:
        rec.popularity = [str(p) for p in
                          d.groupby(_PRODUCT)[_REVENUE].sum().nlargest(5).index]
    else:
        rec.popularity = [str(p) for p in d.groupby(_PRODUCT).size().nlargest(5).index]

    return rec


__all__ = ["Recommendation", "BasketRecommender", "build_recommender",
           "REASON_CYCLE", "REASON_CF", "REASON_COMPLEMENT", "REASON_POPULAR"]
