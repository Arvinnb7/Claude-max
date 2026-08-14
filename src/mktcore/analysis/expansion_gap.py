"""شکاف توسعه‌ی درآمد — «این مشتری چه چیزی می‌خرد، ولی نه از ما؟»

## ایده

اگر ده مشتریِ **شبیه به هم** داریم و نُه‌تایشان دسته‌ی «الف» را هم می‌خرند و
یکی نمی‌خرد، آن یکی احتمالاً آن دسته را از جای دیگری می‌خرد. تفاوت بین آنچه
همتایانش خرج می‌کنند و آنچه او خرج می‌کند، **شکاف** است.

```
میانه‌ی خرید همتایان از دسته − خرید خود مشتری از دسته = شکاف
```

## چرا میانه، نه میانگین

یک مشتریِ عمده‌فروش در گروه همتا، میانگین را بالا می‌برد و برای همه شکافِ
جعلی می‌سازد. میانه در برابر همین ناهنجاری مقاوم است.

## بی‌دامنه بودن

سند برای تعریف همتا از «گونه‌ی حیوان خانگی و مرحله‌ی زندگی» مثال می‌زند؛ این
نصب چنددامنه است، پس همتایی با ابعادی تعریف می‌شود که **در هر صنعتی از داده
درمی‌آید**: سگمنت رفتاری، دهک ارزش، و سابقه‌ی خرید.

## آنچه این ماژول ادعا نمی‌کند

شکاف، درآمدِ قطعی نیست؛ یک **تخمین رتبه‌بندی‌شده از پتانسیل** است. و چون بهای
تمام‌شده در دست نیست، بر پایه‌ی **درآمد** است نه سود ناخالص — برخلاف متن سند
که سود می‌خواهد.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..ingest.schema import ColumnRole, standard_column

_CUSTOMER = standard_column(ColumnRole.CUSTOMER_ID)
_PRODUCT = standard_column(ColumnRole.PRODUCT)
_CATEGORY = standard_column(ColumnRole.CATEGORY)
_REVENUE = standard_column(ColumnRole.REVENUE)

# کمینه‌ی گروه همتا. با کمتر از این، «میانه‌ی همتایان» یک عدد اتفاقی است و
# شکاف گزارش نمی‌شود — نه اینکه عدد ضعیف با اطمینان پایین برگردد.
MIN_PEERS = 10
# کمینه‌ی نفوذ دسته در گروه همتا: اگر فقط ۲۰٪ همتایان این دسته را می‌خرند،
# نخریدنِ مشتری «شکاف» نیست، سلیقه است.
MIN_PEER_ADOPTION = 0.5
# دهک‌بندی ارزش برای تعریف همتا
_VALUE_TIERS = 4


@dataclass
class CategoryGap:
    """یک دسته‌ی غایب در سبد مشتری، با شواهدش."""

    customer_id: str
    category: str
    peer_median_revenue: float
    customer_revenue: float
    gap_value: float
    peer_count: int
    peer_adoption: float          # چه نسبتی از همتایان این دسته را می‌خرند
    peer_group_fa: str            # توضیح خواناِ گروه همتا

    @property
    def confidence(self) -> str:
        """اطمینان از اندازه‌ی گروه و شدت پذیرش می‌آید، نه از حدس."""
        if self.peer_count >= 30 and self.peer_adoption >= 0.8:
            return "بالا"
        if self.peer_count >= 15 and self.peer_adoption >= 0.65:
            return "متوسط"
        return "کم"

    @property
    def evidence_fa(self) -> str:
        return (
            f"{self.peer_count} مشتری مشابه ({self.peer_group_fa}) از این دسته خرید "
            f"می‌کنند — {round(self.peer_adoption * 100)}٪ آن‌ها. "
            f"میانه‌ی خریدشان {round(self.peer_median_revenue):,} است."
        )


@dataclass
class ExpansionGapResult:
    gaps: list[CategoryGap] = field(default_factory=list)
    dimension: str = ""           # روی چه ستونی دسته‌بندی شد (دسته یا محصول)
    n_customers_scanned: int = 0
    skipped_reason_fa: str | None = None

    @property
    def available(self) -> bool:
        return bool(self.gaps)

    def for_customer(self, customer_id: str, limit: int = 3) -> list[CategoryGap]:
        items = [g for g in self.gaps if g.customer_id == customer_id]
        return sorted(items, key=lambda g: -g.gap_value)[:limit]

    def compact(self, limit: int = 12) -> dict:
        top = sorted(self.gaps, key=lambda g: -g.gap_value)[:limit]
        return {
            "بُعد": self.dimension,
            "شکاف‌ها": [
                {
                    "مشتری": g.customer_id,
                    "دسته": g.category,
                    "ارزش_شکاف": round(g.gap_value),
                    "اطمینان": g.confidence,
                }
                for g in top
            ],
        }


def _peer_group_label(segment: str, tier: int) -> str:
    return f"{segment}، گروه ارزش {tier + 1} از {_VALUE_TIERS}"


def _value_tiers(totals: pd.Series) -> pd.Series:
    """دهک‌بندی ارزش مشتری. با داده‌ی کم، همه در یک گروه می‌مانند."""
    if totals.nunique() < _VALUE_TIERS:
        return pd.Series(0, index=totals.index, dtype=int)
    try:
        return pd.qcut(totals.rank(method="first"), _VALUE_TIERS, labels=False).astype(int)
    except ValueError:  # pragma: no cover - توزیع بسیار فشرده
        return pd.Series(0, index=totals.index, dtype=int)


def compute_expansion_gap(
    df: pd.DataFrame,
    segments: pd.DataFrame | None = None,
    *,
    min_peers: int = MIN_PEERS,
    min_adoption: float = MIN_PEER_ADOPTION,
    top_per_customer: int = 3,
) -> ExpansionGapResult:
    """محاسبه‌ی شکاف برای همه‌ی مشتریان.

    `segments` جدول RFM موجود است (اختیاری)؛ اگر نباشد، همتایی فقط بر پایه‌ی
    گروه ارزش تعریف می‌شود.
    """
    result = ExpansionGapResult()
    if _CUSTOMER not in df.columns or not len(df):
        result.skipped_reason_fa = "ستون مشتری در داده وجود ندارد."
        return result

    # دسته‌بندی ترجیحاً روی «دسته»؛ اگر نبود، روی «محصول»
    dimension = _CATEGORY if _CATEGORY in df.columns else _PRODUCT
    if dimension not in df.columns:
        result.skipped_reason_fa = "نه ستون دسته‌بندی و نه نام کالا در داده وجود ندارد."
        return result
    result.dimension = "دسته‌بندی" if dimension == _CATEGORY else "کالا"

    # `unstack(fill_value=...)` وقتی dtype ستون‌ها با مقدار پرکننده نخواند در
    # نسخه‌های آینده‌ی pandas خطا می‌دهد؛ پس پرکردن جداگانه و صریح انجام می‌شود.
    spend = (
        df.groupby([_CUSTOMER, dimension])[_REVENUE]
        .sum()
        .unstack()
        .astype("float64")
        .fillna(0.0)
    )
    if spend.shape[1] < 2:
        result.skipped_reason_fa = "برای مقایسه دست‌کم دو دسته لازم است."
        return result

    totals = spend.sum(axis=1)
    peers = pd.DataFrame({"tier": _value_tiers(totals)}, index=spend.index)
    peers["segment"] = "همه"
    if segments is not None and len(segments) and "segment_fa" in segments.columns:
        mapped = segments["segment_fa"].reindex(peers.index)
        peers["segment"] = mapped.fillna("سایر").astype(str)

    result.n_customers_scanned = int(len(spend))
    gaps: list[CategoryGap] = []

    for (segment, tier), group in peers.groupby(["segment", "tier"], sort=False):
        members = group.index
        if len(members) < min_peers:
            continue  # گروه کوچک → میانه بی‌معناست
        block = spend.loc[members]
        label = _peer_group_label(str(segment), int(tier))

        for category in block.columns:
            column = block[category]
            buyers = column > 0
            adoption = float(buyers.mean())
            if adoption < min_adoption:
                continue  # اکثریت همتایان هم نمی‌خرند → سلیقه است، نه شکاف
            peer_median = float(np.median(column[buyers])) if buyers.any() else 0.0
            if peer_median <= 0:
                continue
            for customer_id in column[~buyers].index:
                gaps.append(CategoryGap(
                    customer_id=str(customer_id),
                    category=str(category),
                    peer_median_revenue=peer_median,
                    customer_revenue=0.0,
                    gap_value=peer_median,
                    peer_count=int(buyers.sum()),
                    peer_adoption=adoption,
                    peer_group_fa=label,
                ))

    # فقط چند شکاف برتر هر مشتری نگه داشته می‌شود؛ فهرست بلند غیرقابل‌اقدام است
    trimmed: list[CategoryGap] = []
    by_customer: dict[str, list[CategoryGap]] = {}
    for gap in sorted(gaps, key=lambda g: -g.gap_value):
        bucket = by_customer.setdefault(gap.customer_id, [])
        if len(bucket) < top_per_customer:
            bucket.append(gap)
            trimmed.append(gap)

    result.gaps = trimmed
    if not trimmed and result.skipped_reason_fa is None:
        result.skipped_reason_fa = (
            f"گروه همتای به‌اندازه‌ی کافی بزرگ (حداقل {min_peers} مشتری) پیدا نشد."
        )
    return result


__all__ = [
    "MIN_PEERS",
    "MIN_PEER_ADOPTION",
    "CategoryGap",
    "ExpansionGapResult",
    "compute_expansion_gap",
]
