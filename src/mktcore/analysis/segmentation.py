"""سگمنت‌بندی: تحلیل RFM مشتریان و تفکیک بر اساس محصول/کانال/منطقه."""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from ..ingest.schema import ColumnRole, standard_column

_DATE = standard_column(ColumnRole.DATE)
_REVENUE = standard_column(ColumnRole.REVENUE)
_CUSTOMER = standard_column(ColumnRole.CUSTOMER_ID)
_ORDER = standard_column(ColumnRole.ORDER_ID)

# نام فارسی سگمنت‌های RFM
RFM_SEGMENT_NAMES = {
    "champions": "قهرمانان",
    "loyal": "وفادار",
    "potential": "مستعد رشد",
    "new": "تازه‌وارد",
    "at_risk": "در معرض ریزش",
    "hibernating": "خفته",
    "lost": "از‌دست‌رفته",
    "others": "سایر",
}


@dataclass
class SegmentationResult:
    """نتیجه‌ی سگمنت‌بندی."""

    rfm_table: pd.DataFrame = field(default_factory=pd.DataFrame)
    segment_sizes: dict[str, int] = field(default_factory=dict)
    segment_revenue: dict[str, float] = field(default_factory=dict)
    breakdowns: dict[str, pd.DataFrame] = field(default_factory=dict)

    def top_segments_compact(self, n: int = 5) -> dict:
        """نمایش فشرده‌ی سگمنت‌ها برای ارسال به مدل."""
        return {
            "اندازه_سگمنت": dict(sorted(self.segment_sizes.items(), key=lambda x: -x[1])[:n]),
            "درآمد_سگمنت": {k: round(v) for k, v in sorted(self.segment_revenue.items(), key=lambda x: -x[1])[:n]},
        }


def _name_segment(r: int, f: int, m: int) -> str:
    """نگاشت امتیاز R/F/M (۱ تا ۴) به نام سگمنت."""
    if r >= 4 and f >= 4 and m >= 4:
        return "champions"
    if f >= 3 and m >= 3:
        return "loyal"
    if r >= 4 and f <= 2:
        return "new"
    if r >= 3 and (f >= 2 or m >= 2):
        return "potential"
    if r <= 2 and f >= 3:
        return "at_risk"
    if r <= 2 and f <= 2 and m >= 3:
        return "hibernating"
    if r == 1 and f <= 2:
        return "lost"
    return "others"


def compute_rfm(df: pd.DataFrame, *, reference_date: pd.Timestamp | None = None) -> SegmentationResult:
    """تحلیل RFM در سطح مشتری و نام‌گذاری سگمنت‌ها."""
    res = SegmentationResult()
    if _CUSTOMER not in df.columns or df.empty:
        return res

    ref = reference_date or (df[_DATE].max() + pd.Timedelta(days=1))
    order_col = _ORDER if _ORDER in df.columns else None

    grp = df.groupby(_CUSTOMER)
    recency = (ref - grp[_DATE].max()).dt.days
    frequency = grp[order_col].nunique() if order_col else grp.size()
    monetary = grp[_REVENUE].sum()

    rfm = pd.DataFrame({"recency": recency, "frequency": frequency, "monetary": monetary})

    # امتیازدهی ۱ تا ۴ (کوآرتایل). recency معکوس (کمتر = بهتر).
    def _score(series: pd.Series, reverse: bool = False) -> pd.Series:
        try:
            q = pd.qcut(series.rank(method="first"), 4, labels=[1, 2, 3, 4])
            s = q.astype(int)
        except ValueError:
            s = pd.Series(2, index=series.index)
        return (5 - s) if reverse else s

    rfm["R"] = _score(rfm["recency"], reverse=True)
    rfm["F"] = _score(rfm["frequency"])
    rfm["M"] = _score(rfm["monetary"])
    rfm["segment"] = [
        _name_segment(int(r), int(f), int(m))
        for r, f, m in zip(rfm["R"], rfm["F"], rfm["M"], strict=True)
    ]
    rfm["segment_fa"] = rfm["segment"].map(RFM_SEGMENT_NAMES)

    res.rfm_table = rfm
    res.segment_sizes = {RFM_SEGMENT_NAMES[k]: int(v) for k, v in rfm["segment"].value_counts().items()}
    rev = rfm.groupby("segment")["monetary"].sum()
    res.segment_revenue = {RFM_SEGMENT_NAMES[k]: float(v) for k, v in rev.items()}
    return res


def breakdown(df: pd.DataFrame, role: ColumnRole, *, top: int = 10) -> pd.DataFrame:
    """تفکیک درآمد بر اساس یک بُعد (محصول/کانال/منطقه/دسته) با سهم و پارتو."""
    col = standard_column(role)
    if col not in df.columns or df.empty:
        return pd.DataFrame()
    agg = (
        df.groupby(col)[_REVENUE]
        .agg(["sum", "count"])
        .rename(columns={"sum": "revenue", "count": "rows"})
        .sort_values("revenue", ascending=False)
    )
    total = agg["revenue"].sum()
    agg["share"] = agg["revenue"] / total if total else 0.0
    agg["cumulative_share"] = agg["share"].cumsum()
    return agg.head(top).reset_index()


def all_breakdowns(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """تفکیک بر اساس همه‌ی ابعاد موجود."""
    out: dict[str, pd.DataFrame] = {}
    for role in (ColumnRole.PRODUCT, ColumnRole.CATEGORY, ColumnRole.CHANNEL, ColumnRole.REGION):
        col = standard_column(role)
        if col in df.columns:
            bd = breakdown(df, role)
            if not bd.empty:
                out[role.value] = bd
    return out


def compute_segmentation(df: pd.DataFrame) -> SegmentationResult:
    """اجرای کامل سگمنت‌بندی: RFM + تفکیک ابعاد."""
    res = compute_rfm(df)
    res.breakdowns = all_breakdowns(df)
    return res


__all__ = [
    "SegmentationResult",
    "compute_rfm",
    "compute_segmentation",
    "breakdown",
    "all_breakdowns",
    "RFM_SEGMENT_NAMES",
]
