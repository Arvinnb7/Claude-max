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


def full_price_share_bp(frame: pd.DataFrame) -> pd.Series:
    """سهمِ خطوطِ بدون تخفیفِ هر مشتری، به پایه‌ی هزارم.

    ورودی فریمِ دفتر کل است (ستون‌های `customer_id`، `discount_rial`،
    `discount_rate_bp`؛ همان `LINE_COLUMNS`). خروجی با ایندکسِ `customer_id`.
    نبودِ **هر دو** ستون یا خالی‌بودنِ هر دو ⇒ سریِ NaN برای همه.
    """
    if frame.empty or "customer_id" not in frame.columns:
        return pd.Series(dtype=float, name="full_price_share_bp")

    has_amount = "discount_rial" in frame.columns and frame["discount_rial"].notna().any()
    has_rate = "discount_rate_bp" in frame.columns and frame["discount_rate_bp"].notna().any()
    customers = frame["customer_id"].dropna().unique()
    if not (has_amount or has_rate):
        return pd.Series(np.nan, index=pd.Index(customers, name="customer_id"),
                         name="full_price_share_bp")

    amount = pd.to_numeric(frame["discount_rial"], errors="coerce").fillna(0) if has_amount else 0
    rate = pd.to_numeric(frame["discount_rate_bp"], errors="coerce").fillna(0) if has_rate else 0
    full_price = ((amount == 0) & (rate == 0)).astype(float)
    share = full_price.groupby(frame["customer_id"]).mean() * _BP
    share.index.name = "customer_id"
    return share.round().rename("full_price_share_bp")


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
