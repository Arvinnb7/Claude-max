"""پیش‌بینی خرید بعدی و سبد بعدی هر مشتری (مدل احتمالاتی).

- **زمان خرید بعدی**: cadence هر مشتری = ترکیب میانگین نمایی-وزنی فاصله‌های
  اخیر (وزن بیشتر به خریدهای تازه) و میانه‌ی فاصله‌ها (مقاوم به پرت)، با
  shrinkage سلسله‌مراتبی به میانه‌ی کل مشتریان برای مشتریان کم‌سابقه.
- **احتمال خرید ۳۰ روزه**: فاصله‌های خرید هر مشتری با توزیع گاما (برآورد
  گشتاورها: k=(μ/σ)²، θ=σ²/μ) مدل می‌شود؛ احتمالِ شرطی «خرید در پنجره‌ی آینده
  به شرط زمان سپری‌شده از آخرین خرید» = (F(e+w)−F(e))/(1−F(e))، ضرب‌در میراگر
  زنده‌بودن به سبک sBG هندسی: p_alive = π^max(e/μ−1, 0) با π=0.85 — هرچه مشتری
  بیش از یک چرخه‌ی کامل عقب باشد، احتمال ریزش بیشتر لحاظ می‌شود.
- **ارزش مورد انتظار**: میانگین وزنی-بازگشتی ارزش سفارش‌های خود مشتری.
- **سبد بعدی**: محصولات چرخه‌عقب‌افتاده‌ی خود مشتری + مکمل‌های سبد + پرفروش‌ها.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..ingest.schema import ColumnRole, standard_column
from .market_basket import BasketAnalysis
from .purchase_cycle import PurchaseCycleAnalysis
from .recommender import BasketRecommender, Recommendation

_DATE = standard_column(ColumnRole.DATE)
_PRODUCT = standard_column(ColumnRole.PRODUCT)
_CUSTOMER = standard_column(ColumnRole.CUSTOMER_ID)
_ORDER = standard_column(ColumnRole.ORDER_ID)
_REVENUE = standard_column(ColumnRole.REVENUE)

# وزن نمایی فاصله‌های اخیر (آخرین فاصله وزن ۱)
_DECAY = 0.75
# قدرت shrinkage به میانه‌ی کل (بر حسب «تعداد فاصله‌ی معادل»)
_K0 = 3.0
# سهم میانگین وزنی در برابر میانه در برآورد محلی cadence
_EW_SHARE = 0.6
# کف ضریب تغییرات (فاصله‌های خیلی منظم → توزیع بیش‌ازحد قطعی نشود)
_CV_FLOOR = 0.15
# بقای هندسی per-cycle برای میراگر زنده‌بودن
_ALIVE_PI = 0.85
# وزن نمایی ارزش سفارش‌های اخیر
_VALUE_DECAY = 0.8


@dataclass
class NextPurchase:
    customer_id: str
    last_purchase: str
    avg_interval_days: float | None
    predicted_next_date: str | None
    status: str  # "سررسیدشده" | "نزدیک" | "زود" | "نامشخص"
    overdue_days: int  # روزهای گذشته از پیش‌بینی (مثبت = معوق)
    likely_products: list[str] = field(default_factory=list)
    expected_value: float = 0.0  # ارزش یک سفارش (وزن‌دار تازگی)
    buy_probability_30d: float | None = None  # احتمال خرید در پنجره‌ی ۳۰ روز آینده
    recommendations: list[Recommendation] = field(default_factory=list)  # با دلیل
    alive_probability: float | None = None  # احتمال فعال‌بودن مشتری (sBG)
    churn_risk: float | None = None  # ۱ − احتمال فعال‌بودن
    expected_value_30d: float | None = None  # ارزش مورد انتظار ۳۰ روز = EV × احتمال
    clv_12m: float | None = None  # ارزش عمر تنزیل‌شده‌ی ۱۲ ماه آینده
    value_confidence: str | None = None  # «بالا» | «متوسط» | «کم (نمونه ناکافی)»


@dataclass
class NextPurchaseAnalysis:
    customers: list[NextPurchase] = field(default_factory=list)

    @property
    def available(self) -> bool:
        return bool(self.customers)

    def due_now(self, n: int = 50) -> list[NextPurchase]:
        """مشتریانی که خریدشان سررسید شده یا معوق است (بیشترین تأخیر اول)."""
        due = [c for c in self.customers if c.status in ("سررسیدشده", "نزدیک")]
        return sorted(due, key=lambda c: -c.overdue_days)[:n]

    def compact(self, n: int = 10) -> list[dict]:
        return [
            {"مشتری": c.customer_id, "خرید_بعدی": c.predicted_next_date, "وضعیت": c.status,
             "تأخیر_روز": c.overdue_days, "سبد_محتمل": c.likely_products,
             "ارزش_مورد_انتظار": round(c.expected_value)}
            for c in self.due_now(n)
        ]


def alive_probability(elapsed: np.ndarray, mu: np.ndarray) -> np.ndarray:
    """احتمال «زنده‌بودن» مشتری: افت هندسی sBG بعد از یک چرخه‌ی کامل تأخیر."""
    mu = np.clip(np.asarray(mu, dtype=float), 1e-9, None)
    elapsed = np.clip(np.asarray(elapsed, dtype=float), 0.0, None)
    return np.clip(_ALIVE_PI ** np.maximum(elapsed / mu - 1.0, 0.0), 0.0, 1.0)


def window_components(elapsed: np.ndarray, mu: np.ndarray, cv: np.ndarray,
                      window_days: int) -> tuple[np.ndarray, np.ndarray]:
    """اجزای احتمال: (احتمال خرید در پنجره به‌شرط زنده‌بودن، احتمال زنده‌بودن).

    گامای گشتاوری per-customer برای زمان بین خرید + میراگر زنده‌بودن sBG هندسی.
    جدا برگرداندن اجزا لازم است چون «احتمال ریزش» و CLV به p_alive نیاز دارند.
    """
    mu = np.clip(np.asarray(mu, dtype=float), 1e-9, None)
    cv = np.clip(np.asarray(cv, dtype=float), _CV_FLOOR, None)
    elapsed = np.clip(np.asarray(elapsed, dtype=float), 0.0, None)
    try:
        from scipy.stats import gamma as _gamma

        k = 1.0 / cv**2
        theta = cv**2 * mu
        f_t = _gamma.cdf(elapsed, a=k, scale=theta)
        f_th = _gamma.cdf(elapsed + window_days, a=k, scale=theta)
        p_window = (f_th - f_t) / np.clip(1.0 - f_t, 1e-9, None)
    except Exception:
        # fallback نمایی (بی‌حافظه): مستقل از elapsed
        p_window = 1.0 - np.exp(-window_days / mu)
    return np.clip(p_window, 0.0, 1.0), alive_probability(elapsed, mu)


def _window_probability(elapsed: np.ndarray, mu: np.ndarray, cv: np.ndarray,
                        window_days: int) -> np.ndarray:
    """P(خرید در window روز آینده | elapsed روز از آخرین خرید گذشته)، در [0, 1]."""
    p_window, p_alive = window_components(elapsed, mu, cv, window_days)
    return np.clip(p_window * p_alive, 0.0, 1.0)


# نرخ تنزیل ماهانه‌ی CLV و افق آن (۱۲ ماه)
_CLV_MONTHS = 12
_CLV_DISCOUNT_MONTHLY = 0.02


def _clv_12m(ev: float, mu: float | None, p_alive_now: float | None) -> float | None:
    """ارزش عمر تنزیل‌شده‌ی ۱۲ ماه آینده با همان cadence و افت زنده‌بودن.

    برای هر ماه t: (تعداد خرید انتظاری = ۳۰/μ) × ارزش سفارش × p_alive(t) ÷ (1+r)^t
    که p_alive با گذر هر چرخه به‌صورت هندسی افت می‌کند (همان π مدل موجود).
    """
    if not ev or mu is None or pd.isna(mu) or float(mu) <= 0:
        return None
    mu_f = float(mu)
    alive = 1.0 if p_alive_now is None or pd.isna(p_alive_now) else float(p_alive_now)
    orders_per_month = 30.0 / mu_f
    total = 0.0
    for t in range(1, _CLV_MONTHS + 1):
        # افت زنده‌بودن متناسب با تعداد چرخه‌های سپری‌شده در این ماه
        alive *= _ALIVE_PI ** (30.0 / mu_f)
        total += orders_per_month * ev * alive / ((1.0 + _CLV_DISCOUNT_MONTHLY) ** t)
    return round(total)


def predict_next_purchases(
    df: pd.DataFrame,
    basket: BasketAnalysis | None = None,
    *,
    cycles: PurchaseCycleAnalysis | None = None,
    recommender: BasketRecommender | None = None,
    near_window: int = 14,
    max_basket_customers: int = 1500,
    window_days: int = 30,
) -> NextPurchaseAnalysis:
    """پیش‌بینی زمان، احتمال و سبد خرید بعدی هر مشتری (وکتورایز و مقیاس‌پذیر)."""
    res = NextPurchaseAnalysis()
    if _CUSTOMER not in df.columns or df.empty:
        return res

    d = df.dropna(subset=[_CUSTOMER, _DATE]).copy()
    if d.empty:
        return res
    data_max = d[_DATE].max()
    order_col = _ORDER if (_ORDER in d.columns and d[_ORDER].notna().any()) else None

    # ---------------------------------------------- آماره‌های پایه‌ی هر مشتری
    g = d.groupby(_CUSTOMER)
    last = g[_DATE].max()
    n_dates = g[_DATE].nunique()

    # ------------------------------------------- فاصله‌های بین خرید (وکتورایز)
    u = (d[[_CUSTOMER, _DATE]]
         .assign(**{_DATE: d[_DATE].dt.normalize()})
         .drop_duplicates()
         .sort_values([_CUSTOMER, _DATE]))
    gaps = u.groupby(_CUSTOMER)[_DATE].diff().dt.days
    gv = gaps.dropna().astype(float)
    gc = u.loc[gv.index, _CUSTOMER]

    has_repeats = not gv.empty
    if has_repeats:
        pooled_median = float(gv.median())
        pooled_mean = float(gv.mean())
        pooled_std = float(gv.std()) if len(gv) > 1 else 0.0
        cv_pooled = (pooled_std / pooled_mean) if pooled_mean > 0 else 0.6
        cv_pooled = max(cv_pooled, _CV_FLOOR)

        tmp = pd.DataFrame({"c": gc.to_numpy(), "g": gv.to_numpy()})
        tmp["w"] = _DECAY ** tmp.groupby("c").cumcount(ascending=False)
        wsum = tmp.groupby("c")["w"].sum()
        ew = (tmp["g"] * tmp["w"]).groupby(tmp["c"]).sum() / wsum
        med = gv.groupby(gc).median()
        n_i = gv.groupby(gc).size().astype(float)
        mean_i = gv.groupby(gc).mean()
        std_i = gv.groupby(gc).std()  # NaN برای n=1

        local = _EW_SHARE * ew + (1.0 - _EW_SHARE) * med
        shrink = n_i / (n_i + _K0)
        cadence = shrink * local + (1.0 - shrink) * pooled_median

        cv_local = (std_i / mean_i).where(mean_i > 0)
        cv_i = ((n_i * cv_local.fillna(cv_pooled) + _K0 * cv_pooled)
                / (n_i + _K0)).clip(lower=_CV_FLOOR)
    else:
        pooled_median, cv_pooled = None, None
        cadence = pd.Series(dtype=float)
        cv_i = pd.Series(dtype=float)

    # μ و cv برای «همه»ی مشتریان: تک‌خریدها از prior استخری
    all_ids = last.index
    if has_repeats:
        mu_all = cadence.reindex(all_ids).fillna(pooled_median)
        cv_all = cv_i.reindex(all_ids).fillna(cv_pooled)
        elapsed_all = (data_max - last).dt.days.astype(float)
        p_win, p_alive = window_components(
            elapsed_all.to_numpy(), mu_all.to_numpy(), cv_all.to_numpy(), window_days)
        prob_all = pd.Series(np.clip(p_win * p_alive, 0.0, 1.0), index=all_ids)
        alive_all = pd.Series(p_alive, index=all_ids)
        predicted = last + pd.to_timedelta(cadence.reindex(all_ids), unit="D")
        overdue = (data_max - predicted).dt.days
    else:
        prob_all = pd.Series(np.nan, index=all_ids)
        alive_all = pd.Series(np.nan, index=all_ids)
        mu_all = pd.Series(np.nan, index=all_ids)
        predicted = pd.Series(pd.NaT, index=all_ids)
        overdue = pd.Series(np.nan, index=all_ids)

    # -------------------------------- ارزش مورد انتظار: میانگین وزنی-بازگشتی
    if order_col:
        ov = (d.groupby([_CUSTOMER, order_col])
                .agg(v=(_REVENUE, "sum"), t=(_DATE, "max")).reset_index())
    else:
        ov = (d.assign(_day=d[_DATE].dt.normalize())
                .groupby([_CUSTOMER, "_day"])
                .agg(v=(_REVENUE, "sum"), t=(_DATE, "max")).reset_index())
    ov = ov.sort_values([_CUSTOMER, "t"])
    ov["w"] = _VALUE_DECAY ** ov.groupby(_CUSTOMER).cumcount(ascending=False)
    ev = ((ov["v"] * ov["w"]).groupby(ov[_CUSTOMER]).sum()
          / ov["w"].groupby(ov[_CUSTOMER]).sum())
    ev_fallback = float(d[_REVENUE].mean()) if d[_REVENUE].notna().any() else 0.0

    top_products = list(d.groupby(_PRODUCT)[_REVENUE].sum().sort_values(ascending=False).index[:3]) \
        if _PRODUCT in d.columns else []

    # ------------------------------------------------------- ساخت خروجی‌ها
    np_by_id: dict[str, NextPurchase] = {}
    for cust in all_ids:
        nd = int(n_dates[cust])
        p = prob_all[cust]
        prob = round(float(p), 3) if pd.notna(p) else None
        if nd >= 2:
            ov_days = int(overdue[cust]) if pd.notna(overdue[cust]) else 0
            status = ("سررسیدشده" if ov_days >= 0 else
                      ("نزدیک" if ov_days >= -near_window else "زود"))
            pred_str = predicted[cust].date().isoformat() if pd.notna(predicted[cust]) else None
            ai = round(float(cadence[cust]), 1) if (has_repeats and pd.notna(cadence.get(cust))) else None
        else:
            # تک‌خرید: تاریخ قطعی نداریم ولی احتمال از prior استخری معنادار است
            ov_days, status, pred_str, ai = 0, "نامشخص", None, None
        ev_c = float(ev.get(cust, ev_fallback))
        pa = alive_all.get(cust)
        pa_f = round(float(pa), 3) if pd.notna(pa) else None
        mu_c = mu_all.get(cust) if has_repeats else np.nan
        npr = NextPurchase(
            customer_id=str(cust),
            last_purchase=last[cust].date().isoformat(),
            avg_interval_days=ai, predicted_next_date=pred_str, status=status,
            overdue_days=ov_days, likely_products=[],
            expected_value=ev_c,
            buy_probability_30d=prob,
            alive_probability=pa_f,
            churn_risk=None if pa_f is None else round(1.0 - pa_f, 3),
            expected_value_30d=(None if prob is None else round(ev_c * prob)),
            clv_12m=_clv_12m(ev_c, mu_c, pa),
            value_confidence=("بالا" if nd >= 4 else
                              ("متوسط" if nd >= 2 else "کم (نمونه ناکافی)")),
        )
        np_by_id[str(cust)] = npr
        res.customers.append(npr)

    # -------- سبد پیشنهادی: با موتور CF برای «همه»ی مشتریان (پوشش کامل)؛
    # fallback ابتکاری (فقط در داده‌ی کوچک که موتور غیرفعال است) برای dueها.
    if _PRODUCT in d.columns:
        if recommender is not None and recommender.available:
            all_ids = [c.customer_id for c in res.customers]
            recs = recommender.recommend_many(all_ids, n=5)
            for c in res.customers:
                c.recommendations = recs.get(c.customer_id, [])
                c.likely_products = [r.product for r in c.recommendations]
        else:
            due = sorted(
                [c for c in res.customers if c.status in ("سررسیدشده", "نزدیک")],
                key=lambda c: -c.overdue_days,
            )[:max_basket_customers]
            if due:
                due_ids = {c.customer_id for c in due}
                baskets = _heuristic_basket(d, due_ids, cycles=cycles, basket=basket,
                                            top_products=top_products)
                for c in due:
                    c.likely_products = baskets.get(c.customer_id, [])

    return res


def _heuristic_basket(
    d: pd.DataFrame,
    due_ids: set[str],
    *,
    cycles: PurchaseCycleAnalysis | None,
    basket: BasketAnalysis | None,
    top_products: list,
) -> dict[str, list[str]]:
    """منطق قدیمی سبد محتمل (بدون CF) — baseline سنجش دقت هم از همین استفاده می‌کند."""
    bought_map = (
        d[d[_CUSTOMER].astype(str).isin(due_ids)]
        .groupby(_CUSTOMER)[_PRODUCT]
        .agg(lambda s: {str(x) for x in s if pd.notna(x)})
        .rename(index=str)
    )
    cycle_due: dict[str, list[str]] = {}
    if cycles is not None and getattr(cycles, "notifications", None):
        for note in cycles.notifications:
            if note.status in ("عقب‌افتاده", "نزدیک") and str(note.customer_id) in due_ids:
                cycle_due.setdefault(str(note.customer_id), []).append(str(note.product))
    out: dict[str, list[str]] = {}
    for cid in due_ids:
        bought = bought_map.get(cid, set())
        likely: list[str] = []
        for p in cycle_due.get(cid, []):
            if p not in likely:
                likely.append(p)
        if basket is not None and basket.available:
            for p in bought:
                for rule in basket.complements_for(p, n=2):
                    if rule.consequent not in bought and rule.consequent not in likely:
                        likely.append(rule.consequent)
        for p in top_products:
            ps = str(p)
            if ps not in bought and ps not in likely:
                likely.append(ps)
        out[cid] = likely[:5]
    return out


__all__ = ["NextPurchaseAnalysis", "NextPurchase", "predict_next_purchases"]
