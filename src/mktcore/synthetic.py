"""تولید داده‌ی فروش مصنوعی برای توسعه، تست و دموی داشبورد.

داده شامل روند صعودی، فصلی‌بودن هفتگی و سالانه، نویز، چند ناهنجاری تزریق‌شده
و رفتار مشتری تکرارشونده است تا همه‌ی ماژول‌های تحلیلی قابل آزمایش باشند.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

PRODUCTS = ["پرو", "استاندارد", "لایت", "کلاسیک", "ویژه"]
CATEGORIES = {"پرو": "نرم‌افزار", "استاندارد": "نرم‌افزار", "لایت": "نرم‌افزار",
              "کلاسیک": "سخت‌افزار", "ویژه": "سخت‌افزار"}
CHANNELS = ["وب‌سایت", "اینستاگرام", "فروش مستقیم", "نمایندگی"]
REGIONS = ["تهران", "اصفهان", "مشهد", "شیراز", "تبریز"]


def generate_synthetic_sales(
    *,
    seed: int = 42,
    start: str = "2023-01-01",
    days: int = 730,
    base_orders_per_day: int = 18,
    yoy_growth: float = 0.25,
    n_customers: int = 400,
) -> pd.DataFrame:
    """تولید یک DataFrame خام فروش در سطح ردیف-سفارش.

    خروجی ستون‌های فارسی/خام دارد تا مسیر نگاشت ستون هم آزمایش شود.

    Args:
        seed: بذر تصادفی برای بازتولید قطعی.
        start: تاریخ شروع (میلادی، ISO).
        days: تعداد روزها.
        base_orders_per_day: میانگین پایه‌ی سفارش روزانه.
        yoy_growth: نرخ رشد سالانه‌ی تقریبی (برای تست YoY).
        n_customers: تعداد مشتریان یکتا.
    """
    rng = np.random.default_rng(seed)
    dates = pd.date_range(start=start, periods=days, freq="D")
    t = np.arange(days)

    # روند رشد (سالانه ~ yoy_growth)
    daily_growth = (1.0 + yoy_growth) ** (1.0 / 365.0)
    trend = daily_growth**t

    # فصلی هفتگی (آخر هفته‌ی ایرانی: پنجشنبه/جمعه قوی‌تر) و سالانه
    weekday = dates.dayofweek.to_numpy()  # دوشنبه=0 ... یکشنبه=6
    weekly = 1.0 + 0.25 * np.isin(weekday, [3, 4]).astype(float)  # پنجشنبه=3، جمعه=4
    yearly = 1.0 + 0.30 * np.sin(2 * np.pi * (t % 365) / 365.0 - np.pi / 2)

    intensity = base_orders_per_day * trend * weekly * yearly
    orders_per_day = rng.poisson(np.maximum(intensity, 1.0))

    # تزریق ناهنجاری: یک جهش فروش و یک افت شدید
    spike_idx = int(days * 0.55)
    drop_idx = int(days * 0.80)
    orders_per_day[spike_idx] = int(orders_per_day[spike_idx] * 3.5) + 30
    orders_per_day[drop_idx] = max(1, int(orders_per_day[drop_idx] * 0.1))

    customer_ids = [f"C{idx:04d}" for idx in range(n_customers)]
    # وزن‌دهی برای مشتریان تکرارشونده (برخی مشتریان فعال‌تر)
    cust_weights = rng.dirichlet(np.ones(n_customers) * 0.6)

    rows = []
    order_counter = 1
    for day_i, date in enumerate(dates):
        n = int(orders_per_day[day_i])
        if n <= 0:
            continue
        prod_choice = rng.choice(PRODUCTS, size=n, p=[0.30, 0.28, 0.22, 0.12, 0.08])
        cust_choice = rng.choice(customer_ids, size=n, p=cust_weights)
        chan_choice = rng.choice(CHANNELS, size=n, p=[0.45, 0.25, 0.18, 0.12])
        region_choice = rng.choice(REGIONS, size=n, p=[0.40, 0.18, 0.16, 0.14, 0.12])

        for k in range(n):
            product = prod_choice[k]
            base_price = {
                "پرو": 2_500_000, "استاندارد": 1_500_000, "لایت": 800_000,
                "کلاسیک": 3_200_000, "ویژه": 5_000_000,
            }[product]
            unit_price = base_price * (1 + rng.normal(0, 0.05))
            qty = int(rng.integers(1, 4))
            discount = float(rng.choice([0, 0, 0, 0.1, 0.15], p=[0.6, 0.1, 0.1, 0.1, 0.1]))
            revenue = unit_price * qty * (1 - discount)
            cost = base_price * 0.55 * qty  # بهای تمام‌شده‌ی تقریبی
            rows.append(
                {
                    "تاریخ": date,
                    "شماره سفارش": f"INV-{order_counter:06d}",
                    "کد مشتری": cust_choice[k],
                    "نام محصول": product,
                    "دسته‌بندی": CATEGORIES[product],
                    "کانال فروش": chan_choice[k],
                    "استان": region_choice[k],
                    "تعداد": qty,
                    "قیمت واحد": round(unit_price),
                    "تخفیف": discount,
                    "مبلغ کل": round(revenue),
                    "بهای تمام شده": round(cost),
                }
            )
            order_counter += 1

    return pd.DataFrame(rows)
