"""«چه کسی و از کجا» برای ردیف‌های ممیزی.

جدا از `repo_audit` نگه داشته شده چون آن ماژول درونِ `mktcore` است و نباید به
FastAPI وابسته شود؛ اینجا لایه‌ی HTTP است و می‌تواند `Request` بشناسد.
"""

from __future__ import annotations

from fastapi import Request

from mktcore.db.models import AuditEvent
from mktcore.security import HEADER_NAME

__all__ = ["actor_fa", "client_ip"]


def client_ip(request: Request) -> str | None:
    """نشانیِ درخواست، تا جایی که واقعاً می‌دانیم.

    پشتِ reverse proxy، `request.client` نشانیِ خودِ proxy است. اگر
    `X-Forwarded-For` بود، **اولین** عضوش نزدیک‌ترین چیز به مبدأ است — و چون
    این هدر جعل‌شدنی است، نباید مبنای هیچ تصمیمِ امنیتی باشد؛ فقط سرنخِ ممیزی
    است.
    """
    forwarded = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if forwarded:
        return forwarded[:64]
    client = request.client
    return client.host[:64] if client else None


def actor_fa(request: Request) -> str:
    """هویت، صادقانه: توکنِ مشترک «چه کسی» را نمی‌داند."""
    if (request.headers.get(HEADER_NAME) or "").strip():
        return AuditEvent.ACTOR_TOKEN
    return AuditEvent.ACTOR_ANONYMOUS
