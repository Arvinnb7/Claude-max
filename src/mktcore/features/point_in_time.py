"""ویژگی‌های مشتری در یک لحظه‌ی مشخص — خالص، بدون دیتابیس.

## قاعده‌ی حاکم

هر ستون این ماژول باید با این جمله سازگار باشد: «اگر امروز فقط داده‌ی تا تاریخ
T را داشتیم، همین عدد درمی‌آمد.» هر انحرافی از این، نشت است و مدل را در
اعتبارسنجی خوش‌بین و در عمل بی‌خاصیت می‌کند.

## چرا NaN و نه صفر

مثل بقیه‌ی این سیستم: «نمی‌دانیم» با «صفر» یکی نیست. مشتریِ تک‌خرید فاصله‌ی
خرید **ندارد**؛ اگر صفر بگذاریم مدل یاد می‌گیرد «فاصله‌ی صفر یعنی مشتری خوب».
کالای بی‌بها حاشیه‌ی **نامعلوم** دارد نه حاشیه‌ی صفر. جای‌گذاری (imputation)
کارِ لایه‌ی مدل است و آنجا با پرچمِ «این مقدار جای‌گذاری شده» انجام می‌شود.

## پنجره‌ی مشاهده

وقتی `observation_days` داده شود، پنجره‌ی هر مشتری از **نخستین خرید خودش**
شروع می‌شود، نه از تاریخ تقویمی مشترک. §۱۸.۳ ویژگی‌هایی مثل «فاصله‌ی خرید اول
تا دوم» و «تعداد خرید در ۳۰ روز اول» می‌خواهد که فقط با لنگرِ شخصی معنا دارند.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

PIT_SCHEMA_VERSION = 2

# ترتیب این چندتایی بخشی از قرارداد است: بردار ضرایبِ ذخیره‌شده‌ی مدل با همین
# ترتیب معنا پیدا می‌کند. افزودن ستون یعنی بالا بردن `PIT_SCHEMA_VERSION`.
PIT_FEATURE_SCHEMA: tuple[str, ...] = (
    "tenure_days",
    "recency_days",
    "n_orders",
    "n_lines",
    "monetary_rial",
    "aov_rial",
    "gross_profit_rial",
    "margin_quality_bp",
    "days_to_second_order",
    "orders_first_30d",
    "orders_first_60d",
    "revenue_first_30d_rial",
    "revenue_first_60d_rial",
    "median_gap_days",
    "weighted_median_gap_days",
    "mad_gap_days",
    "cv_gap",
    "units_per_order_milli",
    "pack_adjusted_gap_days",
    "category_breadth",
    "product_breadth",
    "branch_breadth",
    "channel_breadth",
    "premium_share_bp",
    "full_price_share_bp",
    "return_rate_bp",
)

_BP = 10_000


class LeakageError(RuntimeError):
    """فریمِ ورودی داده‌ای از بعد از لحظه‌ی پیش‌بینی دارد.

    این استثنا عمداً سخت‌گیر است: نشت در تست‌ها دیده نمی‌شود و فقط وقتی معلوم
    می‌شود که مدل در عمل کار نکند — یعنی دیرترین و گران‌ترین لحظه‌ی ممکن.
    """


@dataclass(frozen=True)
class PointInTimeSpec:
    """پیکربندی یک بازسازیِ نقطه‌ی زمانی."""

    as_of: str
    # پنجره‌ی مشاهده از نخستین خرید هر مشتری. `None` یعنی «همه‌ی تاریخچه تا as_of».
    observation_days: int | None = None
    # مشتری‌ای که پنجره‌اش هنوز تمام نشده، ویژگیِ کامل ندارد و باید کنار برود.
    require_complete_window: bool = True


def customer_anchors(frame: pd.DataFrame, observation_days: int) -> pd.Series:
    """پایانِ پنجره‌ی مشاهده‌ی هر مشتری (تاریخ ISO، انحصاری)."""
    if frame.empty:
        return pd.Series(dtype=object)
    first = frame.groupby("customer_id")["line_date"].min()
    stamps = pd.to_datetime(first) + pd.Timedelta(days=observation_days)
    return pd.Series(
        stamps.dt.strftime("%Y-%m-%d").to_numpy(), index=first.index, name="anchor",
    )


def compute_point_in_time_features(
    lines: pd.DataFrame, spec: PointInTimeSpec,
) -> pd.DataFrame:
    """ویژگی هر مشتری از خطوطِ خودش — با گاردِ نشت روی ورودی."""
    _guard(lines, spec.as_of)
    if lines.empty:
        return pd.DataFrame(columns=list(PIT_FEATURE_SCHEMA), index=pd.Index([], name="customer_id"))

    frame = lines.copy()
    if spec.observation_days is not None:
        anchors = customer_anchors(frame, spec.observation_days)
        if spec.require_complete_window:
            # پنجره‌ی نیمه‌تمام یعنی «۳۰ روز اول» هنوز کامل نشده؛ عددش با بقیه
            # قابل‌مقایسه نیست و مدل را به‌سمت مشتریانِ تازه اریب می‌کند.
            anchors = anchors[anchors <= spec.as_of]
        frame = frame[frame["customer_id"].isin(anchors.index)]
        if frame.empty:
            return pd.DataFrame(
                columns=list(PIT_FEATURE_SCHEMA), index=pd.Index([], name="customer_id"),
            )
        frame = frame[frame["line_date"] < frame["customer_id"].map(anchors)]
        window_end = frame["customer_id"].map(anchors)
    else:
        anchors = None
        window_end = pd.Series(spec.as_of, index=frame.index)

    if frame.empty:
        return pd.DataFrame(
            columns=list(PIT_FEATURE_SCHEMA), index=pd.Index([], name="customer_id"),
        )

    frame = frame.assign(
        _date=pd.to_datetime(frame["line_date"]),
        _window_end=pd.to_datetime(window_end),
    )
    grouped = frame.groupby("customer_id")
    out = pd.DataFrame(index=grouped.size().index)
    out.index.name = "customer_id"

    first_date = grouped["_date"].min()
    last_date = grouped["_date"].max()
    end = grouped["_window_end"].first()

    out["tenure_days"] = (end - first_date).dt.days.astype(float)
    out["recency_days"] = (end - last_date).dt.days.astype(float)
    out["n_lines"] = grouped.size().astype(float)
    out["n_orders"] = _order_counts(frame).astype(float)
    out["monetary_rial"] = grouped["revenue_rial"].sum().astype(float)
    out["aov_rial"] = (out["monetary_rial"] / out["n_orders"]).astype(float)

    _attach_profit(out, frame, grouped)
    _attach_gaps(out, frame)
    _attach_pack_adjusted(out, frame, grouped)
    _attach_early_window(out, frame, first_date)
    _attach_breadth(out, frame, grouped)
    _attach_premium(out, frame, grouped)
    _attach_discount(out, frame, grouped)

    out["return_rate_bp"] = (
        grouped["is_return"].sum().astype(float) / out["n_lines"] * _BP
    ).round()

    return out[list(PIT_FEATURE_SCHEMA)]


def compute_outcome_window(
    lines: pd.DataFrame, *, starts: pd.Series, days: int,
) -> pd.DataFrame:
    """نتیجه‌ی پنجره‌ی [start ، start+days) برای هر مشتری.

    `starts` نگاشتِ «مشتری → تاریخ شروع» است (همان لنگرِ پایانِ پنجره‌ی مشاهده).
    ستون `future_covered` می‌گوید سودِ این پنجره **کامل** بوده یا نه؛ سود ناقص
    گزارش نمی‌شود چون برچسبِ نهنگ را کم‌برآورد می‌کند.
    """
    columns = [
        "future_orders", "future_revenue_rial", "future_gross_profit_rial",
        "future_covered", "window_start", "window_end",
    ]
    if lines.empty or starts.empty:
        return pd.DataFrame(columns=columns, index=pd.Index([], name="customer_id"))

    ends = pd.Series(
        (pd.to_datetime(starts) + pd.Timedelta(days=days)).dt.strftime("%Y-%m-%d").to_numpy(),
        index=starts.index,
    )
    frame = lines[lines["customer_id"].isin(starts.index)].copy()
    start_of = frame["customer_id"].map(starts)
    end_of = frame["customer_id"].map(ends)
    frame = frame[(frame["line_date"] >= start_of) & (frame["line_date"] < end_of)]

    out = pd.DataFrame(index=pd.Index(starts.index, name="customer_id"))
    out["window_start"] = starts
    out["window_end"] = ends
    if frame.empty:
        # هیچ خریدی در پنجره یعنی صفرِ **قطعی** — چیزی نخریده که سودش نامعلوم باشد.
        out["future_orders"] = 0.0
        out["future_revenue_rial"] = 0.0
        out["future_gross_profit_rial"] = 0.0
        out["future_covered"] = True
        return out[columns]

    grouped = frame.groupby("customer_id")
    out["future_orders"] = _order_counts(frame).reindex(out.index).fillna(0.0).astype(float)
    out["future_revenue_rial"] = (
        grouped["revenue_rial"].sum().reindex(out.index).fillna(0).astype(float)
    )
    covered = (
        grouped["gross_profit_rial"].count() == grouped.size()
    ).reindex(out.index).fillna(True)
    profit = grouped["gross_profit_rial"].sum().reindex(out.index).fillna(0).astype(float)
    out["future_covered"] = covered.to_numpy()
    out["future_gross_profit_rial"] = np.where(covered.to_numpy(), profit.to_numpy(), np.nan)
    return out[columns]


# ------------------------------------------------------------------ کمکی‌ها
def _guard(lines: pd.DataFrame, as_of: str) -> None:
    if lines.empty:
        return
    latest = str(lines["line_date"].max())
    if latest >= as_of:
        raise LeakageError(
            f"فریمِ ورودی خطی با تاریخ {latest} دارد که در {as_of} هنوز دانسته "
            "نبود. ویژگی‌ها باید از فریمِ برش‌خورده ساخته شوند."
        )


def _order_counts(frame: pd.DataFrame) -> pd.Series:
    """تعداد خرید: فاکتورهای یکتا + خطوطِ بدون فاکتور.

    همان قراردادی که `kpis.n_orders` و `campaigns/outcomes.py` دارند: وقتی فایل
    ستون فاکتور ندارد، هر خط یک خرید است.
    """
    known = frame[frame["order_id"].notna()]
    loose = frame[frame["order_id"].isna()]
    counts = known.groupby("customer_id")["order_id"].nunique()
    extra = loose.groupby("customer_id").size()
    return counts.add(extra, fill_value=0).reindex(
        frame["customer_id"].unique()
    ).fillna(0)


def _attach_profit(out: pd.DataFrame, frame: pd.DataFrame, grouped) -> None:
    """سود و کیفیت حاشیه — فقط با پوشش کاملِ بها.

    قاعده همان `costs/register.py::margin_by_product` است: پوششِ ناقص کالای
    سودده را زیانده (یا برعکس) نشان می‌دهد، پس اصلاً وارد نمی‌شود.
    """
    covered = grouped["gross_profit_rial"].count() == grouped.size()
    profit = grouped["gross_profit_rial"].sum().astype(float)
    out["gross_profit_rial"] = np.where(covered.to_numpy(), profit.to_numpy(), np.nan)
    with np.errstate(divide="ignore", invalid="ignore"):
        margin = out["gross_profit_rial"] / out["monetary_rial"] * _BP
    out["margin_quality_bp"] = margin.replace([np.inf, -np.inf], np.nan).round()


def _attach_gaps(out: pd.DataFrame, frame: pd.DataFrame) -> None:
    """آماره‌های فاصله‌ی خرید. مشتریِ تک‌خرید NaN می‌گیرد، نه صفر."""
    dates = (
        frame[["customer_id", "_date"]].drop_duplicates()
        .sort_values(["customer_id", "_date"])
    )
    dates["_gap"] = dates.groupby("customer_id")["_date"].diff().dt.days
    gaps = dates.dropna(subset=["_gap"]).groupby("customer_id")["_gap"]

    median = gaps.median()
    out["median_gap_days"] = median.reindex(out.index).astype(float)
    # میانه‌ی وزنی (§۱۳.۳): فاصله‌ی تازه‌تر وزنِ بیشتری می‌گیرد، ولی چون میانه
    # است نه میانگین، یک فاصله‌ی پرت خرابش نمی‌کند.
    out["weighted_median_gap_days"] = _weighted_median_gaps(dates).reindex(
        out.index
    ).astype(float)
    # MAD: انحرافِ مطلقِ میانه — برخلاف انحراف معیار، یک فاصله‌ی پرت آن را
    # منفجر نمی‌کند (§۱۳.۳).
    mad = gaps.apply(lambda g: float(np.median(np.abs(g - np.median(g)))))
    out["mad_gap_days"] = mad.reindex(out.index).astype(float)
    std = gaps.std()
    with np.errstate(divide="ignore", invalid="ignore"):
        cv = std / median
    out["cv_gap"] = cv.replace([np.inf, -np.inf], np.nan).reindex(out.index).astype(float)

    first_two = (
        dates.groupby("customer_id")["_gap"].first().reindex(out.index).astype(float)
    )
    out["days_to_second_order"] = first_two


def _weighted_median_gaps(dates: pd.DataFrame) -> pd.Series:
    """میانه‌ی وزنیِ فاصله‌ها، با وزنِ نمایی برای تازگی."""
    from mktcore.analysis.cadence_robust import weighted_median

    out: dict[int, float] = {}
    for customer_id, group in dates.dropna(subset=["_gap"]).groupby("customer_id"):
        values = group["_gap"].astype(float).tolist()
        # همان قرارداد `next_purchase`: هر فاصله‌ی قدیمی‌تر ۰٫۷۵ وزنِ بعدی
        weights = [0.75 ** index for index in range(len(values) - 1, -1, -1)]
        value = weighted_median(values, weights)
        if value is not None:
            out[customer_id] = value
    return pd.Series(out, dtype=float)


def _attach_pack_adjusted(out: pd.DataFrame, frame: pd.DataFrame, grouped) -> None:
    """مقدارِ سرانه‌ی هر سفارش و فاصله‌ی تعدیل‌شده با اندازه‌ی بسته (§۱۳.۴).

    نبودِ ستون مقدار ⇒ هر دو `NaN`. تعدیلِ حدسی بدترین حالت است: عددی می‌سازد
    که شبیه دانستن است ولی نیست.
    """
    from mktcore.analysis.cadence_robust import pack_adjusted_gap

    if "quantity_milli" not in frame.columns or frame["quantity_milli"].notna().sum() == 0:
        out["units_per_order_milli"] = np.nan
        out["pack_adjusted_gap_days"] = out["median_gap_days"]
        return

    quantity = frame["quantity_milli"].astype("Float64")
    packs = (
        frame["pack_size_milli"].astype("Float64")
        if "pack_size_milli" in frame.columns else None
    )
    per_customer = quantity.groupby(frame["customer_id"]).sum()
    orders = out["n_orders"].replace(0, np.nan)
    units = (per_customer.reindex(out.index).astype(float) / orders).astype(float)
    out["units_per_order_milli"] = units

    pack_median = (
        packs.groupby(frame["customer_id"]).median().reindex(out.index).astype(float)
        if packs is not None else pd.Series(np.nan, index=out.index)
    )
    baseline = float(units.median()) if units.notna().any() else None
    adjusted = []
    for customer_id in out.index:
        value, _reason = pack_adjusted_gap(
            out.loc[customer_id, "median_gap_days"],
            quantity_milli=units.get(customer_id),
            baseline_quantity_milli=baseline,
            pack_size_milli=pack_median.get(customer_id),
        )
        adjusted.append(value)
    out["pack_adjusted_gap_days"] = pd.Series(adjusted, index=out.index, dtype=float)


def _attach_early_window(out: pd.DataFrame, frame: pd.DataFrame, first_date) -> None:
    """تعداد و درآمدِ ۳۰ و ۶۰ روزِ اول — دقیقاً ویژگی‌های §۱۸.۳."""
    start = frame["customer_id"].map(first_date)
    elapsed = (frame["_date"] - start).dt.days
    for days in (30, 60):
        window = frame[elapsed < days]
        orders = (
            _order_counts(window).reindex(out.index).fillna(0.0).astype(float)
            if not window.empty else pd.Series(0.0, index=out.index)
        )
        revenue = (
            window.groupby("customer_id")["revenue_rial"].sum()
            .reindex(out.index).fillna(0).astype(float)
            if not window.empty else pd.Series(0.0, index=out.index)
        )
        out[f"orders_first_{days}d"] = orders
        out[f"revenue_first_{days}d_rial"] = revenue


def _attach_breadth(out: pd.DataFrame, frame: pd.DataFrame, grouped) -> None:
    """تنوع دسته/کالا/شعبه/کانال. نبودِ ستون ⇒ NaN، نه صفر و نه یک."""
    for column, name in (
        ("category", "category_breadth"), ("product_id", "product_breadth"),
        ("branch", "branch_breadth"), ("channel", "channel_breadth"),
    ):
        if column not in frame.columns or frame[column].notna().sum() == 0:
            out[name] = np.nan
            continue
        out[name] = grouped[column].nunique().reindex(out.index).astype(float)


def _attach_premium(out: pd.DataFrame, frame: pd.DataFrame, grouped) -> None:
    """سهم خریدِ گران‌تر از میانه‌ی دسته — «premium share» در §۱۸.۳.

    میانه از **همین فریمِ برش‌خورده** گرفته می‌شود، وگرنه معیارِ گرانی از
    آینده می‌آمد و خودش یک نشت بود.
    """
    if "unit_price_rial" not in frame.columns or frame["unit_price_rial"].notna().sum() == 0:
        out["premium_share_bp"] = np.nan
        return
    priced = frame[frame["unit_price_rial"].notna()].copy()
    key = priced["category"].fillna("—") if "category" in priced.columns else "—"
    medians = priced.assign(_key=key).groupby("_key")["unit_price_rial"].median()
    priced["_premium"] = (
        priced["unit_price_rial"].astype(float)
        > priced.assign(_key=key)["_key"].map(medians).astype(float)
    )
    share = priced.groupby("customer_id")["_premium"].mean() * _BP
    out["premium_share_bp"] = share.reindex(out.index).round().astype(float)


def _attach_discount(out: pd.DataFrame, frame: pd.DataFrame, grouped) -> None:
    """سهم خریدِ بدون تخفیف. نبودِ ستونِ تخفیف ⇒ NaN، نه ۱۰۰٪.

    «هیچ ستون تخفیفی نداریم» با «هیچ‌وقت تخفیف نگرفته» یکی نیست؛ دومی ادعایی
    است که داده پشتش نیست.
    """
    # منطقِ مشترک با عکسِ ویژگی و نردبانِ تخفیف در یک جا زندگی می‌کند؛ دو نسخه
    # از «تمام‌قیمت یعنی چه» دیر یا زود از هم فاصله می‌گیرند.
    from mktcore.features.discount import full_price_share_bp

    share = full_price_share_bp(frame)
    out["full_price_share_bp"] = share.reindex(out.index).astype(float)


__all__ = [
    "PIT_FEATURE_SCHEMA",
    "PIT_SCHEMA_VERSION",
    "LeakageError",
    "PointInTimeSpec",
    "compute_outcome_window",
    "compute_point_in_time_features",
    "customer_anchors",
]
