"""پل بین تحلیل موجود و دفتر کل canonical — با جداسازی کاملِ خطا.

این تنها جایی است که مسیر کارکنِ تحلیل به لایه‌ی جدید وصل می‌شود، و عمداً
باریک‌ترین پل ممکن است:

* **هرگز استثنا بالا نمی‌دهد.** اگر نوشتن دفتر کل شکست بخورد، تحلیل و داشبورد
  دقیقاً مثل قبل کار می‌کنند و فقط یک هشدار در پاسخ می‌آید. یک قابلیت جدید
  نباید بتواند قابلیت قدیمیِ سالم را از کار بیندازد.
* **فریم و باندل را تغییر نمی‌دهد** — فقط می‌خواند.
* **بعد از** `save_bundle` صدا زده می‌شود، پس حتی خطای مهلک هم نتیجه‌ی
  ذخیره‌شده‌ی تحلیل را از بین نمی‌برد.
* با `MKT_CANONICAL_ENABLE=0` کاملاً خاموش می‌شود (کلید فرار عملیاتی).
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from mktcore.config import get_settings

logger = logging.getLogger("mktcore.canonical_hook")


def canonical_enabled() -> bool:
    return bool(get_settings().mkt_canonical_enable)


def record_analysis(
    clean: pd.DataFrame,
    bundle: Any,
    *,
    session_id: str,
    filename: str | None = None,
    dataset_key: str | None = None,
    sheet_name: str = "",
    display_currency: str = "تومان",
    file_currency: str | None = None,
    business_slug: str | None = None,
) -> dict | None:
    """نوشتن نتیجه‌ی همین تحلیل در دفتر کل. خطا → `None` + لاگ.

    خروجی برای کلید `payload["canonical"]` است: **کلیدی افزودنی و شرطی**، پس
    هیچ مصرف‌کننده‌ی فعلی‌ای آن را نمی‌بیند مگر بخواهد.
    """
    if not canonical_enabled():
        return None
    try:
        from mktcore.db.repo_import import DEFAULT_BUSINESS_SLUG, write_import

        slug = business_slug or DEFAULT_BUSINESS_SLUG
        result = write_import(
            clean,
            business_slug=slug,
            dataset_key=dataset_key,
            session_id=session_id,
            filename=filename,
            sheet_name=sheet_name,
            display_currency=display_currency,
            file_currency=file_currency,
            kpis=getattr(bundle, "kpis", None),
            validation_status=getattr(getattr(bundle, "validation", None), "status", None),
        )
        payload = result.to_dict()
        payload["ok"] = True
        payload["note_fa"] = (
            "این تحلیل در دفتر کل ثبت شد؛ مشتریان و کالاها بین بارگذاری‌ها به هم وصل می‌شوند."
        )
        # همه‌ی گام‌های بعدی باید روی **همان** کسب‌وکار بنشینند، وگرنه ویژگی و
        # فرصتِ داده‌ی نمونه در کسب‌وکار واقعی نوشته می‌شود و جداسازی بی‌اثر است.
        payload["features_written"] = _record_features(
            clean, bundle, display_currency=display_currency, business_slug=slug,
        )
        # امتیازِ مدل‌ها **پیش از** فرصت‌ها: مولدهای فرصت ممکن است به آن نگاه
        # کنند. بدون مدلِ فعال این گام هیچ‌چیز نمی‌نویسد.
        payload["models"] = _score_models(business_slug=slug)
        payload["opportunities"] = _run_opportunities(
            clean, bundle, session_id=session_id,
            display_currency=display_currency, business_slug=slug,
        )
        # حلقه بسته می‌شود: خرید‌های تازه‌ای که همین حالا وارد دفتر شدند، ممکن
        # است نتیجه‌ی کمپین‌های قبلی باشند.
        payload["campaign_outcomes"] = _refresh_campaign_outcomes(
            result.batch_id, business_slug=slug,
        )
        # حلقه کامل می‌شود: نتیجه‌های تازه، جدولِ اثر را به‌روز می‌کنند و
        # رتبه‌بندیِ اجرای بعدی از آن تغذیه می‌کند.
        payload["uplift"] = _refresh_uplift(business_slug=slug)
        return payload
    except Exception:  # noqa: BLE001 - جداسازی عمدی: تحلیل نباید قربانی دفتر کل شود
        logger.exception("ثبت در دفتر کل canonical ناموفق بود (نشست %s)", session_id)
        return {
            "ok": False,
            "note_fa": (
                "ثبت این تحلیل در دفتر کل انجام نشد؛ گزارش‌ها و داشبورد دست‌نخورده‌اند. "
                "پیوند مشتری بین بارگذاری‌ها برای این نوبت به‌روز نشده است."
            ),
        }


def _record_features(clean: pd.DataFrame, bundle: Any, *, display_currency: str,
                     business_slug: str = "default") -> int:
    """عکس ویژگی مشتری. شکستش نباید ثبتِ موفقِ دفتر کل را باطل کند."""
    try:
        from mktcore.db.repo_features import write_customer_features

        return write_customer_features(
            clean, bundle, display_currency=display_currency,
            business_slug=business_slug,
        )
    except Exception:  # noqa: BLE001 - همان جداسازی، یک لایه پایین‌تر
        logger.exception("نوشتن عکس ویژگی مشتری ناموفق بود")
        return 0


def _score_models(*, business_slug: str = "default") -> dict | None:
    """امتیازِ مدل‌های فعال روی تازه‌ترین عکس ویژگی.

    مثل بقیه‌ی این پل، شکستش کسی را نمی‌کُشد: تحلیل و دفتر کل مستقل از این گام
    کامل می‌مانند. و بدون مدلِ **فعال**، این گام هیچ ستونی را لمس نمی‌کند.
    """
    try:
        from mktcore.ml.churn import score_churn_customers
        from mktcore.ml.whale import score_whale_customers

        return {
            "whale": score_whale_customers(business_slug=business_slug),
            "churn": score_churn_customers(business_slug=business_slug),
        }
    except Exception:  # noqa: BLE001 - همان جداسازی عمدی
        logger.exception("امتیازدهی مدل‌ها ناموفق بود")
        return None


def _run_opportunities(
    clean: pd.DataFrame, bundle: Any, *, session_id: str | None, display_currency: str,
    business_slug: str = "default",
) -> dict | None:
    """اجرای موتور فرصت‌ها. مثل بقیه‌ی این پل، شکستش کسی را نمی‌کُشد."""
    try:
        from mktcore.db.leases import LeaseBusyError
        from mktcore.opportunities import run_opportunity_engine

        try:
            result = run_opportunity_engine(
                bundle, clean, session_id=session_id,
                display_currency=display_currency, business_slug=business_slug,
            )
        except LeaseBusyError as busy:
            # این «خطا» نیست، «رد شدن» است: یک اجرای دیگر همین حالا در جریان
            # است. لاگِ با stack trace اینجا فقط ترس ایجاد می‌کند.
            logger.info("موتور فرصت‌ها رد شد: %s", busy.reason_fa)
            return {"skipped": "concurrent_run", "note_fa": busy.reason_fa}
        return result.to_dict() if result else None
    except Exception:  # noqa: BLE001 - همان جداسازی
        logger.exception("اجرای موتور فرصت‌ها ناموفق بود")
        return None


def _refresh_campaign_outcomes(
    batch_id: int | None, *, business_slug: str = "default",
) -> dict | None:
    """به‌روزرسانی نتیجه‌ی کمپین‌های در جریان. مثل بقیه‌ی این پل، بی‌صدا شکست می‌خورد."""
    try:
        from mktcore.campaigns import compute_campaign_outcomes

        return compute_campaign_outcomes(batch_id=batch_id, business_slug=business_slug)
    except Exception:  # noqa: BLE001 - همان جداسازی
        logger.exception("به‌روزرسانی نتیجه‌ی کمپین‌ها ناموفق بود")
        return None


def _refresh_uplift(*, business_slug: str = "default") -> dict | None:
    """به‌روزرسانی جدولِ اثر آموخته‌شده + ذخیره‌ی عکسش."""
    try:
        from mktcore.uplift import refresh_uplift

        return refresh_uplift(business_slug=business_slug)
    except Exception:  # noqa: BLE001 - همان جداسازی
        logger.exception("به‌روزرسانی جدول اثر ناموفق بود")
        return None


__all__ = ["canonical_enabled", "record_analysis"]
