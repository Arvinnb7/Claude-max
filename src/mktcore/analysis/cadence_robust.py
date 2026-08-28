"""آهنگ خریدِ مقاوم — میانه‌ی وزنی، MAD، و تعدیلِ اندازه‌ی بسته (§۱۳.۳ و §۱۳.۴).

## نسبتش با `next_purchase`

`next_purchase.py` از قبل چیزی بهتر از «میانه‌ی ساده» دارد: ترکیبِ میانگینِ
نمایی‌وزن‌دار با میانه، انقباض سلسله‌مراتبی به میانه‌ی جامعه، و کفِ پراکندگی.
آن **دست نمی‌خورد** — این ماژول جایش نمی‌نشیند.

آنچه واقعاً کم بود و اینجا اضافه می‌شود:

* **MAD** به‌عنوان سنجه‌ی پراکندگیِ مقاوم (§۱۳.۳). انحراف معیار با یک فاصله‌ی
  پرت منفجر می‌شود؛ MAD نمی‌شود.
* **تعدیلِ اندازه‌ی بسته** (§۱۳.۴). `Product.pack_size_milli` از قبل ذخیره
  می‌شد ولی **هیچ‌جا خوانده نمی‌شد**: مشتری‌ای که سه بسته می‌خرد دیرتر برمی‌گردد
  از کسی که یکی می‌خرد، و بدون این تعدیل هر دو «یک آهنگ» دیده می‌شوند.
* **نردبانِ شواهد** (§۱۳.۲): وقتی آهنگِ شخصی نیست، صریح گفته شود که تکیه‌گاه
  چه بوده — نه اینکه عددِ جامعه به‌جای عددِ شخصی جا بزند.
"""

from __future__ import annotations

import numpy as np

# سطوحِ شواهد، از قوی به ضعیف (§۱۳.۲)
EVIDENCE_PERSONAL_PRODUCT = "آهنگ خودِ مشتری برای همین کالا"
EVIDENCE_PERSONAL = "آهنگ خودِ مشتری"
EVIDENCE_PRODUCT = "آهنگ همین کالا در بین همه‌ی مشتریان"
EVIDENCE_POPULATION = "میانه‌ی جامعه"
EVIDENCE_NONE = "شواهدی برای آهنگ خرید وجود ندارد"

# کمینه‌ی فاصله‌ها برای ادعای آهنگِ شخصی. با یک فاصله، «الگو» وجود ندارد.
MIN_GAPS_PERSONAL = 2
# مقدارِ مرجع برای تعدیلِ بسته: اگر مشتری همان مقدارِ معمول را بخرد، تعدیل ۱ است.
DEFAULT_BASELINE_QUANTITY_MILLI = 1_000


def weighted_median(values: list[float], weights: list[float]) -> float | None:
    """میانه‌ی وزنی — مقاوم مثل میانه، ولی با وزنِ تازگی.

    §۱۳.۳ «میانه‌ی وزنیِ مقاوم» می‌خواهد: فاصله‌ی سه سال پیش نباید هم‌وزنِ
    فاصله‌ی ماه پیش باشد، ولی میانگین‌گیریِ وزنی هم با یک پرت خراب می‌شود.
    """
    pairs = [
        (float(value), float(weight))
        for value, weight in zip(values, weights, strict=False)
        if weight > 0 and np.isfinite(value)
    ]
    if not pairs:
        return None
    pairs.sort(key=lambda pair: pair[0])
    total = sum(weight for _value, weight in pairs)
    running = 0.0
    for value, weight in pairs:
        running += weight
        if running >= total / 2:
            return value
    return pairs[-1][0]


def mad(values: list[float]) -> float | None:
    """انحرافِ مطلقِ میانه — پراکندگیِ مقاوم در برابر پرت."""
    clean = [float(v) for v in values if np.isfinite(v)]
    if not clean:
        return None
    center = float(np.median(clean))
    return float(np.median([abs(v - center) for v in clean]))


def dispersion_ratio(spread: float | None, expected: float | None) -> float | None:
    """پراکندگی نسبت به آهنگ. عددِ بزرگ یعنی «این مشتری بی‌قاعده است»."""
    if spread is None or not expected:
        return None
    return float(spread) / float(expected)


def pack_adjusted_gap(
    gap_days: float | None,
    *,
    quantity_milli: float | None,
    baseline_quantity_milli: float | None = DEFAULT_BASELINE_QUANTITY_MILLI,
    pack_size_milli: float | None = None,
) -> tuple[float | None, str | None]:
    """فاصله‌ی موردانتظار با درنظرگرفتنِ **مقدارِ خریداری‌شده** (§۱۳.۴).

    برمی‌گرداند (فاصله‌ی تعدیل‌شده، دلیلِ فارسی). نبودِ داده‌ی مقدار ⇒ همان
    فاصله‌ی ورودی و دلیلِ صریح — نه تعدیلِ حدسی.

    مبنا ساده و قابل‌دفاع است: مصرف تقریباً خطی است، پس دو برابر خرید یعنی
    تقریباً دو برابر دوامِ مصرف. جایی که `pack_size_milli` معلوم است، مقدار به
    «چند بسته» تبدیل می‌شود تا واحدهای ناهمگن با هم جمع نشوند.
    """
    if gap_days is None or not np.isfinite(gap_days):
        return None, "فاصله‌ی پایه معلوم نیست."
    if not quantity_milli or not np.isfinite(quantity_milli):
        return float(gap_days), "مقدارِ خرید در داده نیست؛ تعدیلِ اندازه انجام نشد."

    baseline = float(baseline_quantity_milli or DEFAULT_BASELINE_QUANTITY_MILLI)
    if pack_size_milli and np.isfinite(pack_size_milli) and pack_size_milli > 0:
        # با اندازه‌ی بسته، مقدار به «چند بسته» تبدیل می‌شود؛ بدون آن، واحدهای
        # مختلف (کیلو/عدد/لیتر) با هم جمع می‌شدند و عدد بی‌معنا می‌شد.
        quantity_milli = float(quantity_milli) / float(pack_size_milli) * 1_000.0
    if baseline <= 0:
        return float(gap_days), "مقدارِ مرجع صفر است؛ تعدیل انجام نشد."

    factor = float(quantity_milli) / baseline
    if factor <= 0:
        return float(gap_days), "مقدارِ خرید معتبر نیست؛ تعدیل انجام نشد."
    adjusted = float(gap_days) * factor
    if abs(factor - 1.0) < 0.05:
        return adjusted, None
    direction = "بیشتر" if factor > 1 else "کمتر"
    return adjusted, (
        f"چون مقدارِ خریدش {round(factor, 2)} برابرِ معمول بود، فاصله‌ی "
        f"موردانتظار همان‌قدر {direction} گرفته شد."
    )


def evidence_level(
    *,
    personal_product_gaps: int = 0,
    personal_gaps: int = 0,
    product_gaps: int = 0,
    population_gap: float | None = None,
) -> tuple[str, str]:
    """نردبانِ پنج‌سطحیِ §۱۳.۲ — و اینکه تکیه‌گاه چه بوده.

    §۱۳.۲ صریح است: «با یک خرید، آهنگِ مشتری-کالا استفاده نشود؛ صریح به سطحِ
    پایین‌تر برگرد و اطمینان را کم کن.» پس هر سطح نامِ خودش را دارد و در UI
    دیده می‌شود؛ عددِ جامعه هرگز به‌جای عددِ شخصی جا نمی‌زند.
    """
    if personal_product_gaps >= MIN_GAPS_PERSONAL:
        return EVIDENCE_PERSONAL_PRODUCT, "بالا"
    if personal_gaps >= MIN_GAPS_PERSONAL:
        return EVIDENCE_PERSONAL, "متوسط"
    if product_gaps >= MIN_GAPS_PERSONAL:
        return EVIDENCE_PRODUCT, "کم"
    if population_gap:
        return EVIDENCE_POPULATION, "کم"
    return EVIDENCE_NONE, "کم"


__all__ = [
    "DEFAULT_BASELINE_QUANTITY_MILLI",
    "EVIDENCE_NONE",
    "EVIDENCE_PERSONAL",
    "EVIDENCE_PERSONAL_PRODUCT",
    "EVIDENCE_POPULATION",
    "EVIDENCE_PRODUCT",
    "MIN_GAPS_PERSONAL",
    "dispersion_ratio",
    "evidence_level",
    "mad",
    "pack_adjusted_gap",
    "weighted_median",
]
