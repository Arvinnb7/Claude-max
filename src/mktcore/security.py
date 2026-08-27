"""گاردِ دسترسی برای مسیرهای نوشتنی و پرخرج.

## چرا توکنِ مشترک و نه RBAC

این سیستم امروز تک‌کاربره و تک‌کسب‌وکاره است. RBAC (کاربر، نقش، مالکیت نشست)
سربارِ واقعی دارد و مسئله‌ی امروز را حل نمی‌کند. مسئله‌ی امروز این است:

* `POST /api/v1/campaigns/{id}/send` و `POST /api/sms/send` **پول واقعی خرج
  می‌کنند** و به مشتریانِ واقعی پیام می‌دهند.
* `POST /api/scheduler/run-now` می‌تواند بدون هیچ پارامتری ارسال را کلید بزند.
* `DELETE /api/v1/customers/{id}/opt-out` می‌تواند انصرافِ یک مشتری را پس بگیرد.
* `POST /api/strategy` و `/api/campaign` هزینه‌ی واقعیِ Anthropic دارند.

یک توکنِ مشترک هر شش را می‌بندد، در استقرار لوکال و عمومی یکسان کار می‌کند، و
وقتی روزی احراز هویتِ کامل لازم شد، جای درستِ جایگزینی همین‌جا است.

## سازگاری عقب‌رو

اگر `MKT_API_TOKEN` تنظیم **نشده باشد**، رفتار دقیقاً مثل امروز است و هیچ
درخواستی رد نمی‌شود — وگرنه هر نصبِ موجود با ارتقا از کار می‌افتاد. ولی این
حالت **صریح هشدار می‌دهد** (در `/api/health` و لاگِ راه‌اندازی)، چون سکوت در
برابر «هیچ گاردی نیست» همان اشتباهی است که این فاز برای رفعش ساخته شده.
"""

from __future__ import annotations

import hmac
import logging

from fastapi import Header, HTTPException

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


__all__ = [
    "HEADER_NAME",
    "NON_ASCII_NOTE_FA",
    "UNPROTECTED_NOTE_FA",
    "require_token",
    "token_configured",
    "token_is_usable",
    "warn_if_unprotected",
]
