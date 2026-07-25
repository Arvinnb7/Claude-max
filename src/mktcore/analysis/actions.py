"""فهرست اقدام ریالی: همه‌ی فرصت‌های فروش، مرتب بر اساس پول.

هر فرصتی که تحلیل‌های موجود می‌سازند (چرخه‌ی عقب‌افتاده، سبد پیشنهادی، الگوی
ناتمام، کالای تک‌خریدی، مشتری در خطر ریزش) به یک «اقدام» با عدد ریالی، دلیل و
درجه‌ی اتکا تبدیل می‌شود تا تیم فروش بداند از کجا شروع کند.

صداقت در نام‌گذاری: عددها **«ارزش فرصت»** هستند نه «افزایش قطعی فروش» — یعنی
اگر مشتری خرید کند چقدر پول در میان است. ادعای علّی («این اقدام فروش را X
بیشتر کرد») فقط پس از سنجش با گروه کنترل مجاز است.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from ..ingest.schema import ColumnRole, standard_column

_CUSTOMER = standard_column(ColumnRole.CUSTOMER_ID)
_PRODUCT = standard_column(ColumnRole.PRODUCT)
_REVENUE = standard_column(ColumnRole.REVENUE)
_PHONE = standard_column(ColumnRole.PHONE)
_SALESPERSON = standard_column(ColumnRole.SALESPERSON)
_BRANCH = standard_column(ColumnRole.BRANCH)

# انواع اقدام (کلید گروه‌بندی و نمایش)
KIND_CYCLE = "یادآوری چرخه‌ی مصرف"
KIND_BASKET = "پیشنهاد سبد شخصی"
KIND_SEQUENCE = "تکمیل الگوی خرید"
KIND_ONETIME = "معرفی کالای مکمل"
KIND_CHURN = "نجات مشتری در خطر ریزش"

VALUE_OPPORTUNITY = "ارزش فرصت"
VALUE_AT_RISK = "ارزش در معرض خطر"

# حداقل ریسک ریزش برای ساخت اقدام نجات
_CHURN_MIN_RISK = 0.30


@dataclass
class Action:
    rank: int
    kind: str
    customer_id: str
    product: str | None
    action_fa: str  # جمله‌ی امری برای تیم فروش
    reason_fa: str  # شواهد پشت اقدام
    value_rial: float
    value_kind: str
    confidence: str
    probability: float | None = None
    phone: str | None = None
    owner: str | None = None  # فروشنده/شعبه‌ی مرتبط (برای تقسیم کار)
    last_purchase: str | None = None
    predicted_next_date: str | None = None
    message_fa: str | None = None  # متن پیشنهادی تماس/پیامک


@dataclass
class ActionPlan:
    actions: list[Action] = field(default_factory=list)
    summary: list[dict] = field(default_factory=list)  # به تفکیک نوع اقدام
    total_value: float = 0.0

    @property
    def available(self) -> bool:
        return bool(self.actions)

    def top(self, n: int = 20) -> list[Action]:
        return self.actions[:n]

    def compact(self, n: int = 10) -> list[dict]:
        """نمای فشرده برای لایه‌ی هوش مصنوعی (اعداد از کد، نه از مدل زبانی).

        عمداً کوتاه است: payload مدل باید جمع‌وجور بماند (نوع اقدام در «خلاصه» هست).
        """
        return [
            {"اقدام": a.action_fa, "مشتری": a.customer_id,
             "ارزش_تومان": round(a.value_rial), "اتکا": a.confidence,
             "دلیل": a.reason_fa[:90]}
            for a in self.actions[:n]
        ]


def _phone_map(df: pd.DataFrame) -> dict[str, str]:
    if _PHONE not in df.columns:
        return {}
    return (df.dropna(subset=[_PHONE]).groupby(_CUSTOMER)[_PHONE]
            .first().astype(str).rename(index=str).to_dict())


def _owner_map(df: pd.DataFrame) -> dict[str, str]:
    """فروشنده‌ی غالب هر مشتری (یا شعبه، اگر فروشنده نبود) برای تقسیم فهرست."""
    col = _SALESPERSON if _SALESPERSON in df.columns else (
        _BRANCH if _BRANCH in df.columns else None)
    if col is None:
        return {}
    counts = df.dropna(subset=[col]).groupby([_CUSTOMER, col]).size()
    if counts.empty:
        return {}
    # idxmax روی گروه سطح مشتری → زوج (مشتری، مالک) با بیشترین تعداد ردیف
    top = counts.groupby(level=0).idxmax()
    return {str(cust): str(pair[1]) for cust, pair in top.items()}


def _median_price(df: pd.DataFrame) -> dict[str, float]:
    """میانه‌ی مبلغ هر قلم فروش برای هر محصول (تقریب ارزش یک خرید از آن کالا)."""
    if _PRODUCT not in df.columns or _REVENUE not in df.columns:
        return {}
    med = df.dropna(subset=[_PRODUCT]).groupby(_PRODUCT)[_REVENUE].median()
    return {str(k): float(v) for k, v in med.items() if pd.notna(v)}


def build_action_list(
    bundle,
    df: pd.DataFrame,
    *,
    per_customer_cap: int = 1,
    limit: int = 500,
) -> ActionPlan:
    """ساخت فهرست اقدام از همه‌ی تحلیل‌های موجود، مرتب بر اساس ارزش ریالی."""
    plan = ActionPlan()
    if df.empty or _CUSTOMER not in df.columns:
        return plan

    npa = bundle.next_purchase
    by_cust = {c.customer_id: c for c in npa.customers} if npa.available else {}
    prices = _median_price(df)
    phones = _phone_map(df)
    owners = _owner_map(df)
    raw: list[Action] = []

    def _add(kind: str, cid: str, product: str | None, action: str, reason: str,
             value: float, value_kind: str, confidence: str,
             probability: float | None, message: str) -> None:
        if value is None or value <= 0:
            return
        c = by_cust.get(cid)
        raw.append(Action(
            rank=0, kind=kind, customer_id=cid, product=product,
            action_fa=action, reason_fa=reason, value_rial=float(value),
            value_kind=value_kind, confidence=confidence, probability=probability,
            phone=phones.get(cid), owner=owners.get(cid),
            last_purchase=c.last_purchase if c else None,
            predicted_next_date=c.predicted_next_date if c else None,
            message_fa=message,
        ))

    # ۱) چرخه‌ی مصرف عقب‌افتاده — قوی‌ترین سیگنال شخصی
    pc = bundle.purchase_cycle
    if getattr(pc, "available", False):
        for note in pc.overdue(1000):
            cid = str(note.customer_id)
            c = by_cust.get(cid)
            prob = c.buy_probability_30d if c else None
            ev = c.expected_value if c else prices.get(str(note.product), 0.0)
            if prob and ev:
                value = ev * prob
            else:
                # احتمال پنجره‌ای در دست نیست (یا صفر شده): قیمت میانه‌ی کالا را با
                # احتمال فعال‌بودن مشتری وزن بده تا بیش‌برآورد نشود
                alive = (c.alive_probability if c and c.alive_probability is not None
                         else 0.5)
                value = prices.get(str(note.product), 0.0) * alive
            _add(KIND_CYCLE, cid, str(note.product),
                 f"تماس/پیام یادآوری خرید «{note.product}»",
                 f"{note.days_offset} روز از چرخه‌ی {round(note.cycle_days)} روزه گذشته است",
                 value, VALUE_OPPORTUNITY,
                 c.value_confidence if c and c.value_confidence else "متوسط", prob,
                 f"سلام، طبق چرخه‌ی خریدتان زمان تهیه‌ی «{note.product}» رسیده است.")

    # ۲) سبد پیشنهادی شخصی برای مشتریان سررسیدشده
    for c in npa.due_now(2000) if npa.available else []:
        if not c.recommendations:
            continue
        top = c.recommendations[0]
        value = c.expected_value_30d or (c.expected_value * (c.buy_probability_30d or 0))
        basket = "، ".join(c.likely_products[:3])
        _add(KIND_BASKET, c.customer_id, top.product,
             f"پیشنهاد سبد: {basket}",
             f"دلیل پیشنهاد: {top.reason}",
             value, VALUE_OPPORTUNITY, c.value_confidence or "متوسط",
             c.buy_probability_30d,
             f"سلام، پیشنهاد ویژه برای شما: {basket}.")

    # ۳) الگوی خرید ناتمام (A خریده، B نه) — ارزش = نرخ تکمیل × قیمت میانه‌ی B
    seq = bundle.sequences
    if getattr(seq, "available", False):
        for pat in seq.top(10):
            price = prices.get(str(pat.consequent), 0.0)
            if price <= 0:
                continue
            value = pat.completion_rate * price
            conf = "بالا" if pat.n_antecedent_buyers >= 100 else (
                "متوسط" if pat.n_antecedent_buyers >= 30 else "کم (نمونه ناکافی)")
            for cid in pat.incomplete_customers[:500]:
                _add(KIND_SEQUENCE, str(cid), str(pat.consequent),
                     f"معرفی «{pat.consequent}» به خریدار «{pat.antecedent}»",
                     f"{round(pat.completion_rate * 100)}٪ خریداران «{pat.antecedent}» "
                     f"بعداً «{pat.consequent}» را خریده‌اند "
                     f"(میانه‌ی فاصله {round(pat.median_lag_days)} روز)",
                     value, VALUE_OPPORTUNITY, conf, pat.completion_rate,
                     f"سلام، همراه «{pat.antecedent}» معمولاً «{pat.consequent}» هم انتخاب می‌شود.")

    # ۴) کالای تک‌خریدی که مشتری هنوز نخریده — ارزش = نرخ تبدیل تاریخی × قیمت
    for tgt in getattr(pc, "onetime_targets", []) or []:
        price = prices.get(str(tgt.product), 0.0)
        pool = len(tgt.potential_customers) + max(tgt.existing_buyers, 0)
        conv = (tgt.existing_buyers / pool) if pool else 0.0
        if price <= 0 or conv <= 0:
            continue
        conf = "متوسط" if tgt.existing_buyers >= 30 else "کم (نمونه ناکافی)"
        for cid in tgt.potential_customers[:300]:
            _add(KIND_ONETIME, str(cid), str(tgt.product),
                 f"معرفی «{tgt.product}» (تاکنون نخریده)",
                 f"{tgt.existing_buyers} مشتری این کالا را خریده‌اند؛ "
                 f"نرخ تبدیل تاریخی {round(conv * 100)}٪",
                 conv * price, VALUE_OPPORTUNITY, conf, conv,
                 f"سلام، «{tgt.product}» می‌تواند مکمل خریدهای شما باشد.")

    # ۵) مشتری باارزش در خطر ریزش — ارزش = CLV × ریسک ریزش (در معرض خطر)
    for c in npa.customers if npa.available else []:
        if c.clv_12m and c.churn_risk and c.churn_risk >= _CHURN_MIN_RISK:
            _add(KIND_CHURN, c.customer_id, (c.likely_products[0] if c.likely_products else None),
                 "تماس نگه‌داشت مشتری (آفر بازگشت)",
                 f"ریسک ریزش {round(c.churn_risk * 100)}٪ و ارزش ۱۲ماهه‌ی "
                 f"{round(c.clv_12m):,} — آخرین خرید {c.last_purchase}",
                 c.clv_12m * c.churn_risk, VALUE_AT_RISK,
                 c.value_confidence or "متوسط", c.buy_probability_30d,
                 "سلام، جای شما خالی بوده؛ یک پیشنهاد ویژه برای بازگشت شما داریم.")

    if not raw:
        return plan

    # مرتب‌سازی ریالی + سقف هر مشتری (فهرست باید عملیاتی بماند)
    raw.sort(key=lambda a: (-a.value_rial, a.customer_id))
    seen: dict[str, int] = {}
    kept: list[Action] = []
    for a in raw:
        n = seen.get(a.customer_id, 0)
        if n >= per_customer_cap:
            continue
        seen[a.customer_id] = n + 1
        kept.append(a)
        if len(kept) >= limit:
            break

    for i, a in enumerate(kept, 1):
        a.rank = i
    plan.actions = kept
    plan.total_value = float(sum(a.value_rial for a in kept))

    agg: dict[str, dict] = {}
    for a in kept:
        s = agg.setdefault(a.kind, {"نوع اقدام": a.kind, "تعداد": 0, "جمع ارزش": 0.0,
                                    "نوع ارزش": a.value_kind})
        s["تعداد"] += 1
        s["جمع ارزش"] += a.value_rial
    plan.summary = sorted(agg.values(), key=lambda s: -s["جمع ارزش"])
    return plan


__all__ = ["Action", "ActionPlan", "build_action_list",
           "KIND_CYCLE", "KIND_BASKET", "KIND_SEQUENCE", "KIND_ONETIME", "KIND_CHURN",
           "VALUE_OPPORTUNITY", "VALUE_AT_RISK"]
