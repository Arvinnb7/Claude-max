"""تولید داده‌ی فروش مصنوعی برای توسعه، تست و دموی داشبورد.

داده شامل روند، فصلی‌بودن، نویز، ناهنجاری، مشتری تکرارشونده، فروشنده/شعبه و
الگوهای خرید واقعی است:
- محصولات مکمل: «کلاسیک» اغلب همراه «لایت» در یک سبد خریده می‌شود.
- توالی خرید: مشتری‌ای که «پرو» می‌خرد معمولاً ~۳۰ روز بعد «ویژه» هم می‌خرد.
این الگوها تزریق می‌شوند تا تحلیل سبد، توالی و پیش‌بینی سبد بعدی قابل آزمایش باشد.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

PRODUCTS = ["پرو", "استاندارد", "لایت", "کلاسیک", "ویژه"]
CATEGORIES = {"پرو": "نرم‌افزار", "استاندارد": "نرم‌افزار", "لایت": "نرم‌افزار",
              "کلاسیک": "سخت‌افزار", "ویژه": "سخت‌افزار"}
CHANNELS = ["وب‌سایت", "اینستاگرام", "فروش مستقیم", "نمایندگی"]
REGIONS = ["تهران", "اصفهان", "مشهد", "شیراز", "تبریز"]
BASE_PRICE = {"پرو": 2_500_000, "استاندارد": 1_500_000, "لایت": 800_000,
              "کلاسیک": 3_200_000, "ویژه": 5_000_000}

# فروشنده‌ها به تفکیک شعبه (هر شعبه = یک منطقه)
SALESPEOPLE = {
    "تهران": ["مرادی", "کاظمی", "رضایی"],
    "اصفهان": ["نوری", "صادقی"],
    "مشهد": ["حسینی", "اکبری"],
    "شیراز": ["محمدی", "یزدانی"],
    "تبریز": ["علیزاده", "بابایی"],
}


def _branch_of(region: str) -> str:
    return f"شعبه {region}"


def generate_synthetic_sales(
    *,
    seed: int = 42,
    start: str = "2023-01-01",
    days: int = 730,
    base_orders_per_day: int = 18,
    yoy_growth: float = 0.25,
    n_customers: int = 400,
) -> pd.DataFrame:
    """تولید یک DataFrame خام فروش در سطح ردیف-قلم سفارش (هر سفارش می‌تواند چند قلم داشته باشد)."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range(start=start, periods=days, freq="D")
    t = np.arange(days)

    daily_growth = (1.0 + yoy_growth) ** (1.0 / 365.0)
    trend = daily_growth**t
    weekday = dates.dayofweek.to_numpy()
    weekly = 1.0 + 0.25 * np.isin(weekday, [3, 4]).astype(float)  # پنجشنبه/جمعه
    yearly = 1.0 + 0.30 * np.sin(2 * np.pi * (t % 365) / 365.0 - np.pi / 2)
    intensity = base_orders_per_day * trend * weekly * yearly
    orders_per_day = rng.poisson(np.maximum(intensity, 1.0))

    # ناهنجاری: یک جهش و یک افت
    spike_idx, drop_idx = int(days * 0.55), int(days * 0.80)
    orders_per_day[spike_idx] = int(orders_per_day[spike_idx] * 3.5) + 30
    orders_per_day[drop_idx] = max(1, int(orders_per_day[drop_idx] * 0.1))

    customer_ids = [f"C{idx:04d}" for idx in range(n_customers)]
    cust_weights = rng.dirichlet(np.ones(n_customers) * 0.6)
    # هر مشتری یک منطقه‌ی ثابت و شماره تماس دارد
    cust_region = {c: rng.choice(REGIONS, p=[0.40, 0.18, 0.16, 0.14, 0.12]) for c in customer_ids}
    cust_phone = {c: "0912" + "".join(str(d) for d in rng.integers(0, 10, 7)) for c in customer_ids}
    # وزن عملکرد فروشنده‌ها (برخی قوی‌تر)
    rep_skill = {rep: float(rng.uniform(0.8, 1.3)) for reps in SALESPEOPLE.values() for rep in reps}

    rows: list[dict] = []
    order_counter = 1
    # صف توالی: (تاریخ سررسید, مشتری, محصول هدف)
    pending: dict[int, list[tuple[str, str]]] = {}

    def _add_line(date, order_id, customer, product, qty, region):
        unit_price = BASE_PRICE[product] * (1 + rng.normal(0, 0.05))
        discount = float(rng.choice([0, 0, 0, 0.1, 0.15], p=[0.6, 0.1, 0.1, 0.1, 0.1]))
        revenue = unit_price * qty * (1 - discount)
        cost = BASE_PRICE[product] * 0.55 * qty
        rep = str(rng.choice(SALESPEOPLE[region]))
        # عملکرد فروشنده روی مبلغ اثر می‌گذارد (طبیعی‌سازی تحلیل عملکرد)
        revenue *= rep_skill[rep]
        rows.append({
            "تاریخ": date,
            "شماره سفارش": order_id,
            "کد مشتری": customer,
            "شماره موبایل": cust_phone[customer],
            "نام محصول": product,
            "دسته‌بندی": CATEGORIES[product],
            "کانال فروش": str(rng.choice(CHANNELS, p=[0.45, 0.25, 0.18, 0.12])),
            "استان": region,
            "شعبه": _branch_of(region),
            "فروشنده": rep,
            "تعداد": qty,
            "قیمت واحد": round(unit_price),
            "تخفیف": discount,
            "مبلغ کل": round(revenue),
            "بهای تمام شده": round(cost),
        })

    for day_i, date in enumerate(dates):
        # ابتدا توالی‌های سررسیدشده‌ی این روز را اجرا کن
        for customer, target in pending.pop(day_i, []):
            oid = f"INV-{order_counter:06d}"
            _add_line(date, oid, customer, target, int(rng.integers(1, 3)), cust_region[customer])
            order_counter += 1

        n = int(orders_per_day[day_i])
        cust_choice = rng.choice(customer_ids, size=max(n, 0), p=cust_weights)
        for k in range(n):
            customer = cust_choice[k]
            region = cust_region[customer]
            oid = f"INV-{order_counter:06d}"
            order_counter += 1
            # محصول اصلی سبد
            main = str(rng.choice(PRODUCTS, p=[0.30, 0.28, 0.22, 0.12, 0.08]))
            _add_line(date, oid, customer, main, int(rng.integers(1, 4)), region)

            # مکمل: «کلاسیک» اغلب با «لایت» در همان سبد
            if main == "کلاسیک" and rng.random() < 0.5:
                _add_line(date, oid, customer, "لایت", 1, region)

            # توالی: خرید «پرو» → خرید «ویژه» حدود ۳۰ روز بعد
            if main == "پرو" and rng.random() < 0.6:
                due = day_i + int(max(7, rng.normal(30, 7)))
                if due < days:
                    pending.setdefault(due, []).append((customer, "ویژه"))

    return pd.DataFrame(rows)
