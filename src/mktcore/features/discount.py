"""رفتارِ خریدِ تمام‌قیمت — §۲۰.۳ بند ۱ و ۲.

## چه چیزی می‌سنجد و چه چیزی **نمی‌سنجد**

می‌سنجد: از خطوطِ خریدِ این مشتری، چه سهمی **بدون تخفیف** بوده. نمی‌سنجد:
اینکه اگر تخفیف بدهیم بیشتر می‌خرد یا نه. دومی «حساسیتِ علّی» است و فقط با
آزمایش (گروه کنترل) به‌دست می‌آید. §۲۰.۳ صریح می‌گوید: «هرگز همبستگیِ
مشاهده‌ایِ تخفیف را حساسیتِ علّی جا نزن.» برای همین هر جا این عدد نمایش داده
می‌شود، `NON_CAUSAL_NOTE_FA` کنارش **اجباری** است.

## چرا NaN، نه صفر و نه ۱۰۰٪

فایلی که ستون تخفیف ندارد، درباره‌ی تخفیف **هیچ** نمی‌گوید. اگر نبودِ ستون را
«هیچ‌وقت تخفیف نگرفته» بخوانیم، همه‌ی مشتریان «وفادارِ تمام‌قیمت» می‌شوند و
نردبان به هیچ‌کس تخفیف نمی‌دهد — که یک تصمیمِ سیاستی است، نه یک واقعیتِ داده.

## دو شکلِ ستونِ تخفیف

فایل‌ها تخفیف را یا **مبلغی** می‌دهند (`discount_rial`) یا **نسبتی**
(`discount_rate_bp`)، و `repo_import` فقط یکی از دو ستون را پر می‌کند. هر
محاسبه‌ای که فقط یکی را ببیند، روی نیمی از فایل‌های واقعی غلط است. این ماژول
هر دو را می‌خواند.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

__all__ = [
    "DEFAULT_HIGH_BP",
    "DEFAULT_LOW_BP",
    "DEFAULT_MIN_LINES",
    "NON_CAUSAL_NOTE_FA",
    "TIER_HIGH",
    "TIER_LOW",
    "TIER_MID",
    "full_price_share_bp",
    "full_price_stats",
    "full_price_tier",
]

_BP = 10_000

# آستانه‌های پیش‌فرضِ طبقه‌بندی. S3 آن‌ها را تنظیم‌پذیر می‌کند؛ این‌ها فقط
# مقدارِ اولیه‌اند و در پاسخِ API همیشه گفته می‌شود از کجا آمده‌اند.
DEFAULT_HIGH_BP = 9_000    # ≥ ۹۰٪ خرید تمام‌قیمت ⇒ «تمام‌قیمت‌خر»
DEFAULT_LOW_BP = 5_000     # ≤ ۵۰٪ ⇒ «وابسته به تخفیف»
DEFAULT_MIN_LINES = 3      # کمتر از این، سهمِ درصدی گمراه‌کننده است

TIER_HIGH = "high"
TIER_MID = "mid"
TIER_LOW = "low"

NON_CAUSAL_NOTE_FA = (
    "این عدد سهمِ خریدهای بدون تخفیف در **گذشته** است — یک همبستگیِ مشاهده‌ای. "
    "نمی‌گوید تخفیف روی این مشتری اثر دارد یا نه؛ آن را فقط آزمایش با گروه "
    "کنترل نشان می‌دهد."
)


def full_price_stats(frame: pd.DataFrame) -> pd.DataFrame:
    """به‌ازای هر مشتری: `share_bp` (NaN = نامعلوم) و `known_lines`.

    * فقط خطوطِ **خرید** (بدون برگشتی) — همان تعریفی که حاشیه‌ها به‌کار می‌برند.
    * خطی که هر دو ستونِ تخفیفش NULL است «نامعلوم» است، نه «بدون تخفیف»؛ پوشش
      **به‌ازای هر مشتری** سنجیده می‌شود. مشتری‌ای که همه‌ی خطوطش نامعلوم است
      (مثلاً فقط در فایلی بوده که ستون تخفیف نداشت) `NaN` می‌گیرد — حتی اگر
      فایل‌های دیگرِ همان کسب‌وکار ستون تخفیف داشته باشند. بازبینیِ خصمانه نشان
      داد پوششِ سراسری چنین مشتری‌ای را «۱۰۰٪ تمام‌قیمت‌خر» می‌کرد.
    """
    empty = pd.DataFrame(
        columns=["share_bp", "known_lines"], index=pd.Index([], name="customer_id"),
    )
    if frame.empty or "customer_id" not in frame.columns:
        return empty
    rows = frame[frame["customer_id"].notna()]
    if "is_return" in rows.columns:
        rows = rows[~rows["is_return"].fillna(False).astype(bool)]
    if rows.empty:
        return empty

    amount = (
        pd.to_numeric(rows["discount_rial"], errors="coerce")
        if "discount_rial" in rows.columns else pd.Series(np.nan, index=rows.index)
    )
    rate = (
        pd.to_numeric(rows["discount_rate_bp"], errors="coerce")
        if "discount_rate_bp" in rows.columns else pd.Series(np.nan, index=rows.index)
    )
    known = amount.notna() | rate.notna()
    full_price = ((amount.fillna(0) == 0) & (rate.fillna(0) == 0)).astype(float)

    grouped_known = known.groupby(rows["customer_id"])
    known_lines = grouped_known.sum().astype(int)
    full_price_known = full_price.where(known, np.nan).groupby(rows["customer_id"]).mean() * _BP
    out = pd.DataFrame({
        "share_bp": full_price_known.round(),
        "known_lines": known_lines,
    })
    out.loc[out["known_lines"] == 0, "share_bp"] = np.nan
    out.index.name = "customer_id"
    return out


def full_price_share_bp(frame: pd.DataFrame) -> pd.Series:
    """سهمِ خطوطِ بدون تخفیفِ هر مشتری، به پایه‌ی هزارم (NaN = نامعلوم)."""
    stats = full_price_stats(frame)
    return stats["share_bp"].rename("full_price_share_bp")


def full_price_tier(
    share_bp: float | int | None,
    n_lines: int | None,
    *,
    high_bp: int = DEFAULT_HIGH_BP,
    low_bp: int = DEFAULT_LOW_BP,
    min_lines: int = DEFAULT_MIN_LINES,
) -> str | None:
    """طبقه‌ی «تمام‌قیمت‌خری». `None` یعنی نمی‌دانیم — نه «متوسط».

    * سهمِ نامعلوم (فایل بدون ستون تخفیف) ⇒ `None`.
    * کمتر از `min_lines` خط ⇒ `None`؛ «۱۰۰٪ از یک خرید» ادعا نیست.
    """
    if share_bp is None or (isinstance(share_bp, float) and np.isnan(share_bp)):
        return None
    if n_lines is None or int(n_lines) < min_lines:
        return None
    value = int(share_bp)
    if value >= high_bp:
        return TIER_HIGH
    if value <= low_bp:
        return TIER_LOW
    return TIER_MID
