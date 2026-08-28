"""گاردِ دسترسی برای مسیرهای نوشتنی و پرخرج.

## چرا توکنِ مشترک و نه RBAC

این سیستم امروز تک‌کاربره و تک‌کسب‌وکاره است. RBAC (کاربر، نقش، مالکیت نشست)
سربارِ واقعی دارد و مسئله‌ی امروز را حل نمی‌کند. مسئله‌ی امروز این است:

* `POST /api/v1/campaigns/{id}/send` و `POST /api/sms/send` **پول واقعی خرج
  می‌کنند** و به مشتریانِ واقعی پیام می‌دهند.
* `POST /api/scheduler/run-now` می‌تواند بدون هیچ پارامتری ارسال را کلید بزند.
* `DELETE /api/v1/customers/{id}/opt-out` می‌تواند انصرافِ یک مشتری را پس بگیرد.
* `POST /api/strategy` و `/api/campaign` هزینه‌ی واقعیِ Anthropic دارند.
* `GET /api/v1/campaigns/{id}/export`، `GET /api/export` و `GET /api/outbox`
  شماره‌ی تماسِ **کامل** (نه ماسک‌شده) می‌دهند؛ اولی ضمناً مهرِ تماس می‌زند —
  یعنی یک GET که وضعیت را عوض می‌کند.

یک توکنِ مشترک همه را می‌بندد، در استقرار لوکال و عمومی یکسان کار می‌کند، و
وقتی روزی احراز هویتِ کامل لازم شد، جای درستِ جایگزینی همین‌جا است.

## چرا فهرستِ مسیرها با تست پین شده است

نسخه‌ی اول همین متن ادعا می‌کرد `/api/strategy` و `/api/campaign` بسته‌اند، در
حالی که نبودند: گارد **به‌ازای هر مسیر** اعمال می‌شود و افزودنِ مسیرِ تازه
به‌طور پیش‌فرض آن را **باز** می‌گذارد. حالا `tests/test_route_guards.py` کلِ
برنامه را پیمایش می‌کند و هر مسیرِ نوشتنی/پرخرج باید یا گارد داشته باشد یا در
فهرستِ سفیدِ همان تست با دلیل ثبت شده باشد. سندی که با تست پین نشده باشد،
دیر یا زود دروغ می‌گوید.

## سازگاری عقب‌رو

اگر `MKT_API_TOKEN` تنظیم **نشده باشد**، رفتار دقیقاً مثل امروز است و هیچ
درخواستی رد نمی‌شود — وگرنه هر نصبِ موجود با ارتقا از کار می‌افتاد. ولی این
حالت **صریح هشدار می‌دهد** (در `/api/health` و لاگِ راه‌اندازی)، چون سکوت در
برابر «هیچ گاردی نیست» همان اشتباهی است که این فاز برای رفعش ساخته شده.
"""

from __future__ import annotations

import hmac
import logging

from fastapi import Header, HTTPException, Request

from mktcore.config import get_settings

logger = logging.getLogger("mktcore.security")

HEADER_NAME = "X-API-Token"

UNPROTECTED_NOTE_FA = (
    "هیچ توکنی تنظیم نشده است: هر کسی که به این آدرس دسترسی داشته باشد می‌تواند "
    "پیامک واقعی بفرستد و هزینه ایجاد کند. برای بستنِ مسیرهای پرخرج، "
    "MKT_API_TOKEN را در تنظیمات سرور بگذارید."
)


NON_ASCII_NOTE_FA = (
    "توکنِ تنظیم‌شده کاراکترِ غیرانگلیسی دارد. مقدارِ هدرهای HTTP فقط ASCII "
    "می‌تواند باشد، پس چنین توکنی هرگز از سمت مرورگر یا curl فرستادنی نیست و "
    "همه‌ی درخواست‌ها رد می‌شوند. از حروف و ارقام انگلیسی استفاده کنید."
)


def token_configured() -> bool:
    return bool((get_settings().mkt_api_token or "").strip())


def token_is_usable() -> bool:
    """آیا توکن اصلاً از راه هدرِ HTTP فرستادنی است؟

    مقدارِ هدر HTTP باید ASCII باشد. توکنِ فارسی روی کاغذ درست به‌نظر می‌رسد ولی
    در عمل هیچ کلاینتی نمی‌تواند بفرستدش — و نتیجه، ردِ **همه‌ی** درخواست‌ها با
    خطایی مبهم است. این را باید در راه‌اندازی گفت، نه اینکه کاربر ساعت‌ها دنبال
    علتش بگردد.
    """
    token = (get_settings().mkt_api_token or "").strip()
    if not token:
        return True
    return token.isascii()


def require_token(x_api_token: str = Header(default="", alias=HEADER_NAME)) -> None:
    """وابستگیِ FastAPI برای مسیرهای نوشتنی و پرخرج.

    مقایسه با `hmac.compare_digest` انجام می‌شود تا زمانِ پاسخ، طول یا محتوای
    توکن را لو ندهد.
    """
    expected = (get_settings().mkt_api_token or "").strip()
    if not expected:
        # سازگاری عقب‌رو: بدون توکنِ تنظیم‌شده چیزی بسته نمی‌شود.
        return
    # ⚠️ مقایسه روی **بایت** انجام می‌شود، نه رشته: `compare_digest` رشته‌ی
    # غیر-ASCII را نمی‌پذیرد و با توکنِ فارسی به‌جای احراز هویت، خطای ۵۰۰
    # می‌داد — یعنی گارد دقیقاً وقتی می‌شکست که کاربر توکنِ فارسی می‌گذاشت.
    if not hmac.compare_digest(
        str(x_api_token or "").encode("utf-8"), expected.encode("utf-8"),
    ):
        raise HTTPException(
            status_code=401,
            detail=(
                "این مسیر نیازمند توکن است. هدر "
                f"{HEADER_NAME} را با مقدار درست بفرستید."
            ),
        )


def warn_if_unprotected() -> None:
    """هشدارِ راه‌اندازی. سکوت در برابر «هیچ گاردی نیست» پذیرفتنی نیست."""
    if not token_configured():
        logger.warning("⚠️  %s", UNPROTECTED_NOTE_FA)
    elif not token_is_usable():
        logger.error("⚠️  %s", NON_ASCII_NOTE_FA)


# ---------------------------------------------------------------- منع پیش‌فرض
#
# **چرا این لایه لازم شد.** گاردِ بالا به‌ازای هر مسیر اعمال می‌شود، یعنی
# فراموش‌کردنش حالتِ **پیش‌فرض** است. همین اتفاق افتاد: `POST /api/strategy` و
# `POST /api/campaign` ماه‌ها باز بودند در حالی که همین فایل ادعا می‌کرد بسته‌اند.
# حالا گارد روی کلِ برنامه می‌نشیند و مسیرِ باز باید **صریحاً** استثنا شود.

WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# مسیرهای نوشتنی‌ای که عمداً باز می‌مانند — هر کدام با دلیل. اگر دلیلی ندارد،
# یعنی یادمان رفته، نه اینکه تصمیم گرفته‌ایم.
OPEN_WRITE_ROUTES: dict[str, str] = {
    "POST /api/upload": (
        "نقطه‌ی ورودِ کاربر است؛ بستنش یعنی بدون توکن اصلاً نمی‌شود فایلی داد. "
        "هزینه‌ی بیرونی ندارد و سقف حجم دارد."
    ),
    "POST /api/sample": "داده‌ی نمونه‌ی مصنوعی؛ نه هزینه دارد نه داده‌ی واقعی.",
    "POST /api/analyze": "تحلیل محلی روی فایلِ خودِ کاربر؛ هزینه‌ی بیرونی ندارد.",
    "PATCH /api/session/{session_id}": "تغییر برچسبِ نشستِ خودِ کاربر.",
    "POST /api/v1/campaigns/{campaign_id}/refresh": (
        "فقط نتیجه را از دفتر کل دوباره می‌خواند؛ چیزی نمی‌فرستد و پولی خرج "
        "نمی‌کند و خروجی‌اش idempotent است."
    ),
}

# مسیرهای **خواندنی** که با وجود GET بودن باید گارد داشته باشند: یا PII می‌دهند
# یا وضعیت را عوض می‌کنند. متدِ GET به‌خودیِ‌خود بی‌خطر نیست.
EXTRA_GUARDED_ROUTES: dict[str, str] = {
    "GET /api/v1/campaigns/{campaign_id}/export": (
        "فهرست شماره‌ی تماسِ کامل (نه ماسک‌شده) می‌دهد و ضمناً مهرِ تماس می‌زند "
        "— یعنی یک GET که وضعیت را عوض می‌کند."
    ),
    "GET /api/export": (
        "فایل اکسل با ستون «موبایل»؛ همان PIIِ خروجی کمپین، از مسیری دیگر. "
        "بستنِ یکی و بازگذاشتنِ دیگری یعنی هیچ‌کدام بسته نیست."
    ),
    "GET /api/outbox": (
        "سابقه‌ی پیامک‌های فرستاده‌شده با شماره‌ی خامِ گیرنده در ستون `phone`."
    ),
}


def route_key(method: str, path: str) -> str:
    return f"{method.upper()} {path}"


def require_token_for_writes(request: Request) -> None:
    """گاردِ سطحِ برنامه: هر مسیر نوشتنی بسته است مگر صریحاً استثنا شده باشد.

    این وابستگی روی خودِ `FastAPI(...)` می‌نشیند، پس شاملِ روترهای امروز و هر
    روتری که فردا اضافه شود می‌شود. تکرارِ `Depends(require_token)` روی مسیرها
    بی‌ضرر است (اجرای دوباره‌ی همان بررسی) و به‌عنوان مستندسازی می‌ماند.
    """
    route = request.scope.get("route")
    path = getattr(route, "path", None) or request.url.path
    key = route_key(request.method, path)

    if request.method.upper() not in WRITE_METHODS and key not in EXTRA_GUARDED_ROUTES:
        return
    if key in OPEN_WRITE_ROUTES:
        return
    require_token(request.headers.get(HEADER_NAME, ""))


__all__ = [
    "EXTRA_GUARDED_ROUTES",
    "HEADER_NAME",
    "OPEN_WRITE_ROUTES",
    "WRITE_METHODS",
    "NON_ASCII_NOTE_FA",
    "UNPROTECTED_NOTE_FA",
    "require_token",
    "require_token_for_writes",
    "route_key",
    "token_configured",
    "token_is_usable",
    "warn_if_unprotected",
]
