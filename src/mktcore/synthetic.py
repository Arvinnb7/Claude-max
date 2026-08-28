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
              "کلاسیک": "سخت‌افزار", "ویژه": "سخت‌افزار", "باکس حمل": "لوازم جانبی"}
CHANNELS = ["وب‌سایت", "اینستاگرام", "فروش مستقیم", "نمایندگی"]
REGIONS = ["تهران", "اصفهان", "مشهد", "شیراز", "تبریز"]
BASE_PRICE = {"پرو": 2_500_000, "استاندارد": 1_500_000, "لایت": 800_000,
              "کلاسیک": 3_200_000, "ویژه": 5_000_000, "باکس حمل": 1_200_000}
# «باکس حمل» محصول تک‌خریدی است (هر مشتری حداکثر یک‌بار) برای آزمایش تشخیص مصرفی/تک‌خریدی

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
    bought_onetime: set[str] = set()  # مشتریانی که محصول تک‌خریدی را گرفته‌اند

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

            # محصول تک‌خریدی «باکس حمل»: هر مشتری حداکثر یک‌بار
            if customer not in bought_onetime and rng.random() < 0.12:
                bought_onetime.add(customer)
                _add_line(date, oid, customer, "باکس حمل", 1, region)

    return pd.DataFrame(rows)


# ═══════════════════════════════ داده‌ی کوهورت‌دار (برای مدل‌های پیش‌بین)
#
# **چرا تابع جداگانه و نه یک پارامتر تازه روی `generate_synthetic_sales`.**
# آن تابع دکمه‌ی «داده‌ی نمونه»ی برنامه است و اعداد خروجی‌اش در تست‌های طلایی
# پین شده‌اند (`total_revenue == 1090` و مانند آن). هر شاخه‌ی تازه‌ای داخل بدنه‌اش
# می‌تواند یک قرعه‌ی تصادفی جابه‌جا کند و کلِ جریان اعداد را عوض کند. تابع خواهر
# **هیچ** مکانیزمی برای تغییرِ آن ندارد.
#
# **چه چیزی اینجا هست که آنجا نیست.** مولد قدیمی مشتری‌ها را از یک استخر ثابت
# انتخاب می‌کند، پس «مشتری تازه» ندارد و §۱۸.۴ («اعتبارسنجی روی کوهورت‌های
# بعدی») روی آن اجراشدنی نیست. اینجا مشتری‌ها در طول زمان **وارد می‌شوند**، هر
# کدام یک «کیفیت» پنهان دارند، و حاشیه‌ی سودشان با همان کیفیت همبسته است — نه
# تصادفی. اگر حاشیه نویزِ محض بود، مدل می‌توانست روی آن بیش‌برازش کند و الکی
# موفق به‌نظر برسد.

# نسبت بهای تمام‌شده به قیمت پایه — عمداً متفاوت، تا «ترکیب سبد» روی حاشیه اثر
# بگذارد و ویژگیِ «کیفیت حاشیه» معنا پیدا کند.
_COHORT_COST_RATIO = {
    "پرو": 0.52, "استاندارد": 0.66, "لایت": 0.72,
    "کلاسیک": 0.45, "ویژه": 0.40, "باکس حمل": 0.60,
}
# کالاهای «گران‌قیمت» که مشتریِ باکیفیت بیشتر سراغشان می‌رود
_PREMIUM = ("ویژه", "کلاسیک", "پرو")


def generate_cohort_sales(
    *,
    seed: int = 101,
    start: str = "2021-01-01",
    days: int = 1_460,
    arrivals_per_day: float = 1.8,
    whale_fraction: float = 0.12,
) -> pd.DataFrame:
    """داده‌ی فروش با **فرایند جذب مشتری** و حاشیه‌ی همبسته با کیفیت مشتری.

    ستون‌ها دقیقاً همان ستون‌های `generate_synthetic_sales` است، پس از همان
    مسیر ورودِ معمول عبور می‌کند؛ این یک **مجموعه‌داده‌ی دیگر** است، نه
    طرح‌واره‌ی دیگر.

    `whale_fraction` سهمِ مشتریانی است که کیفیت پنهانشان بالاست. عمداً از دهکِ
    برچسب بزرگ‌تر است تا برچسب‌گذاری «مرزی» بماند و مدل کارِ واقعی داشته باشد.
    """
    rng = np.random.default_rng(seed)
    dates = pd.date_range(start=start, periods=days, freq="D")

    rows: list[dict] = []
    order_counter = 1
    customers: dict[str, dict] = {}
    next_id = 1

    def _spawn(day_index: int) -> str:
        nonlocal next_id
        key = f"K{next_id:05d}"
        next_id += 1
        # کیفیت پنهان: چولگی به‌سمت پایین، با دُمی از مشتریان بسیار خوب
        quality = float(rng.beta(2.0, 5.0))
        if rng.random() < whale_fraction:
            quality = min(1.0, quality + float(rng.uniform(0.35, 0.6)))
        region = str(rng.choice(REGIONS, p=[0.40, 0.18, 0.16, 0.14, 0.12]))
        customers[key] = {
            "quality": quality,
            "region": region,
            "phone": "0912" + "".join(str(d) for d in rng.integers(0, 10, 7)),
            "joined": day_index,
            # آهنگ خرید: مشتری باکیفیت‌تر زودتر برمی‌گردد
            "cadence": float(np.clip(rng.normal(70 - 45 * quality, 12), 9.0, 160.0)),
            "next_due": day_index + int(rng.integers(5, 40)),
            # عمرِ رابطه: باکیفیت‌ها دیرتر می‌روند
            "lifespan": int(np.clip(rng.normal(220 + 900 * quality, 120), 45, days)),
        }
        return key

    def _basket(quality: float) -> list[str]:
        """سبدِ خرید — مشتری باکیفیت‌تر بیشتر سراغ کالای گران و پرحاشیه می‌رود."""
        premium_bias = 0.15 + 0.6 * quality
        weights = np.array([
            0.20 + 0.25 * premium_bias,   # پرو
            0.30 - 0.10 * premium_bias,   # استاندارد
            0.28 - 0.15 * premium_bias,   # لایت
            0.12 + 0.15 * premium_bias,   # کلاسیک
            0.10 + 0.25 * premium_bias,   # ویژه
        ])
        weights = weights / weights.sum()
        basket = [str(rng.choice(PRODUCTS, p=weights))]
        # تنوع دسته: باکیفیت‌ها سبد بزرگ‌تری می‌بندند
        if rng.random() < 0.15 + 0.45 * quality:
            second = str(rng.choice(PRODUCTS, p=weights))
            if second != basket[0]:
                basket.append(second)
        if rng.random() < 0.10 + 0.25 * quality:
            basket.append("باکس حمل")
        return basket

    def _add_line(date, order_id: str, key: str, product: str, qty: int) -> None:
        profile = customers[key]
        unit_price = BASE_PRICE[product] * (1 + rng.normal(0, 0.04))
        # تخفیف: مشتری باکیفیت‌تر کمتر تخفیف می‌گیرد (و کمتر هم می‌خواهد)
        discount = 0.0
        if rng.random() < 0.35 - 0.25 * profile["quality"]:
            discount = float(rng.choice([0.05, 0.10, 0.15]))
        revenue = unit_price * qty * (1 - discount)
        # بها از **قیمت پایه** می‌آید و با روند تورمی بالا می‌رود؛ حاشیه‌ی هر
        # کالا متفاوت است، پس ترکیب سبدِ مشتری حاشیه‌اش را تعیین می‌کند.
        drift = 1.0 + 0.00008 * (date - dates[0]).days
        unit_cost = BASE_PRICE[product] * _COHORT_COST_RATIO[product] * drift
        rows.append({
            "تاریخ": date,
            "شماره سفارش": order_id,
            "کد مشتری": key,
            "شماره موبایل": profile["phone"],
            "نام محصول": product,
            "دسته‌بندی": CATEGORIES[product],
            "کانال فروش": str(rng.choice(CHANNELS, p=[0.45, 0.25, 0.18, 0.12])),
            "استان": profile["region"],
            "شعبه": _branch_of(profile["region"]),
            "فروشنده": str(rng.choice(SALESPEOPLE[profile["region"]])),
            "تعداد": qty,
            "قیمت واحد": round(unit_price),
            "تخفیف": discount,
            "مبلغ کل": round(revenue),
            "بهای تمام شده": round(unit_cost * qty),
        })

    for day_index, date in enumerate(dates):
        for _ in range(int(rng.poisson(arrivals_per_day))):
            _spawn(day_index)

        for key, profile in customers.items():
            if day_index < profile["next_due"]:
                continue
            if day_index - profile["joined"] > profile["lifespan"]:
                continue
            order_id = f"CINV-{order_counter:06d}"
            order_counter += 1
            quality = profile["quality"]
            for product in _basket(quality):
                quantity = int(rng.integers(1, 3 + int(2 * quality)))
                _add_line(date, order_id, key, product, quantity)
            profile["next_due"] = day_index + max(
                3, int(rng.normal(profile["cadence"], profile["cadence"] * 0.35))
            )

    return pd.DataFrame(rows)


def cohort_quality(frame: pd.DataFrame) -> dict[str, float]:
    """کیفیتِ پنهانِ هر مشتری — فقط برای **تستِ خودِ مولد**.

    مدل هرگز این را نمی‌بیند؛ اینجاست تا تست بتواند بسنجد که ویژگی‌های
    مشاهده‌پذیر واقعاً با کیفیت همبسته‌اند. اگر نبودند، fixture چیزی به مدل
    یاد نمی‌داد و تستِ «مدل خط پایه را برد» بی‌معنا می‌شد.
    """
    if frame.empty:
        return {}
    profit = frame["مبلغ کل"] - frame["بهای تمام شده"]
    by_customer = profit.groupby(frame["کد مشتری"]).sum()
    return {str(key): float(value) for key, value in by_customer.items()}
