"""مدل به‌صورت JSON — بدون pickle، بدون فایلِ آرتیفکت.

## چرا

`pickle` سه مشکل دارد که هر سه در همین پروژه گران تمام می‌شوند:

1. **بازگشت (rollback) شکننده می‌شود.** مدل در فایل است و وضعیتِ promote در
   دیتابیس؛ هر ناهم‌خوانی بین این دو یعنی «مدلی که فکر می‌کنیم فعال است، فعال
   نیست». با JSON، **خودِ ردیفِ دیتابیس خودِ مدل است** و ناهم‌خوانی ممکن نیست.
2. **ارتقای scikit-learn مدلِ ذخیره‌شده را می‌شکند.** آرایه‌ی عدد نمی‌شکند.
3. **قابل‌بازبینی نیست.** ضریبِ ذخیره‌شده باید در «سلامت مدل» به کاربر توضیح
   داده شود؛ از یک بلوکِ بایت نمی‌شود توضیح ساخت.

این ماژول عمداً `sklearn` را import نمی‌کند: امتیازدهی در تولید نباید به
کتابخانه‌ی آموزش وابسته باشد.

## شکلِ ماتریسِ طراحی

ستون‌ها به این ترتیب‌اند: اول `features` (به همان ترتیبِ
`PIT_FEATURE_SCHEMA`)، بعد `indicator_features` — یعنی برای هر ویژگیِ
جای‌گذاری‌شده یک ستونِ «این مقدار نامعلوم بود». آن ستون **باربر** است:
«نمی‌دانیم حاشیه‌ی این مشتری چقدر است» خودش یک سیگنال است، و جای‌گذاریِ بی‌پرچم
ادعا می‌کند که می‌دانیم.
"""

from __future__ import annotations

from typing import Any

LINEAR_KIND = "logistic_l2"
ISOTONIC_KIND = "isotonic"


def linear_model_to_json(
    *,
    features: list[str],
    indicator_features: list[str],
    impute_median: list[float],
    center: list[float],
    scale: list[float],
    coef: list[float],
    intercept: float,
    kind: str = LINEAR_KIND,
) -> dict[str, Any]:
    """ضرایبِ یک مدل خطی به دیکشنری قابلِ‌ذخیره."""
    n_design = len(features) + len(indicator_features)
    if not (len(center) == len(scale) == len(coef) == n_design):
        raise ValueError(
            "طولِ مرکز/مقیاس/ضرایب باید با تعداد ستون‌های ماتریس طراحی یکی باشد."
        )
    if len(impute_median) != len(features):
        raise ValueError("برای هر ویژگی دقیقاً یک میانه‌ی جای‌گذاری لازم است.")
    return {
        "kind": kind,
        "features": list(features),
        "indicator_features": list(indicator_features),
        "impute_median": [float(v) for v in impute_median],
        "center": [float(v) for v in center],
        "scale": [float(v) if float(v) else 1.0 for v in scale],
        "coef": [float(v) for v in coef],
        "intercept": float(intercept),
    }


def calibration_to_json(
    *,
    x: list[float],
    y: list[float],
    reliability_bins: list[dict] | None = None,
) -> dict[str, Any]:
    """آرتیفکتِ کالیبراسیون (§۷.۶) — دو آرایه و بین‌های اتکا.

    `reliability_bins` همان چیزی است که §۲۹.۴ می‌خواهد: «۸۰٪ نمایش‌داده‌شده باید
    تقریباً به نرخ ۸۰٪ منجر شود» فقط با جدولِ بین‌ها قابل بررسی است.
    """
    if len(x) != len(y):
        raise ValueError("دو آرایه‌ی کالیبراسیون باید هم‌طول باشند.")
    return {
        "kind": ISOTONIC_KIND,
        "x": [float(v) for v in x],
        "y": [float(v) for v in y],
        "clip": True,
        "reliability_bins": reliability_bins or [],
    }


__all__ = ["ISOTONIC_KIND", "LINEAR_KIND", "calibration_to_json", "linear_model_to_json"]
