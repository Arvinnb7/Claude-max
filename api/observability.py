"""شناسه‌ی درخواست، لاگِ ساختاریافته، و شمارنده‌های سبک — §۳۲.

## سه چیزی که نبودشان دیده شد

1. **شناسه‌ی درخواست.** وقتی کاربر می‌گوید «صبح خطا داد»، هیچ راهی نبود که
   لاگِ آن درخواست و لاگِ کارِ پس‌زمینه‌ای که همان درخواست کلید زد به هم وصل
   شوند. حالا هر درخواست یک `X-Request-Id` دارد که در هدرِ پاسخ برمی‌گردد و در
   هر خطِ لاگِ همان درخواست می‌آید.
2. **لاگِ ساختاریافته.** خطِ لاگِ بدون شناسه، در یک سرورِ چندکاربره فقط نویز
   است.
3. **شمارنده.** «چند درخواست، چندتا خطا، چقدر طول کشید» — بدون این، «کند شده
   است» یک حسِ شخصی می‌ماند، نه یک عدد.

## چرا شمارنده‌ها در حافظه‌اند و نه در دیتابیس

اینجا مقیاسِ یک نصبِ تک-پروسه‌ای است. نوشتنِ هر درخواست در SQLite یعنی هر
درخواست یک تراکنشِ نوشتن اضافه — که خودش کندی می‌آورد. شمارنده‌ها با ری‌استارت
صفر می‌شوند و همین در پاسخ **صریح گفته می‌شود** (`since`), تا کسی عددِ کوچک را
با «ترافیک کم» اشتباه نگیرد.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import Counter
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

logger = logging.getLogger("mktcore.api.access")

REQUEST_ID_HEADER = "X-Request-Id"

_request_id: ContextVar[str] = ContextVar("mkt_request_id", default="-")

_lock = threading.Lock()
_started_at = time.time()
_counters: Counter[str] = Counter()
_duration_ms_total: Counter[str] = Counter()
_slowest: dict[str, float] = {}

__all__ = [
    "REQUEST_ID_HEADER",
    "UNMATCHED_ROUTE",
    "RequestContextMiddleware",
    "RequestIdLogFilter",
    "current_request_id",
    "install_log_filter",
    "metrics_snapshot",
    "reset_metrics",
    "set_request_id",
]


def current_request_id() -> str:
    """شناسه‌ی درخواستِ جاری، یا `-` بیرون از چرخه‌ی درخواست."""
    return _request_id.get()


def set_request_id(request_id: str) -> None:
    """چسباندنِ شناسه به یک thread یا task دیگر.

    `ContextVar` با `ThreadPoolExecutor.submit` منتقل نمی‌شود، پس کارِ طولانی
    که در استخر اجرا می‌شود بدون این، شناسه‌ی درخواستِ راه‌اندازش را گم می‌کند.
    """
    _request_id.set(request_id or "-")


class RequestIdLogFilter(logging.Filter):
    """شناسه را به **هر** رکوردِ لاگ می‌چسباند، حتی لاگِ کتابخانه‌های دیگر."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = current_request_id()
        return True


def install_log_filter() -> None:
    """نصبِ فیلتر روی handlerهای ریشه، یک‌بار در راه‌اندازی."""
    root = logging.getLogger()
    for handler in root.handlers:
        if not any(isinstance(f, RequestIdLogFilter) for f in handler.filters):
            handler.addFilter(RequestIdLogFilter())


def _clean_id(raw: str | None) -> str:
    """فقط کاراکترهای بی‌خطر، حداکثر ۶۴ نویسه.

    این مقدار دوباره در **هدرِ پاسخ** می‌نشیند. کاراکترِ کنترلی در هدر یعنی
    امکانِ تزریقِ هدر، و کاراکترِ غیر-ASCII یعنی خطای رمزگذاری در پاسخ.
    """
    if not raw:
        return ""
    safe = "".join(ch for ch in raw.strip() if ch.isascii() and ch.isprintable())
    # شناسه‌ی فارسی کاملاً حذف می‌شود و فقط فاصله‌هایش می‌ماند؛ «فاصله» شناسه
    # نیست، پس همان‌جا به «نبودِ شناسه» تبدیل می‌شود تا یکی تازه ساخته شود.
    return safe.strip()[:64]


UNMATCHED_ROUTE = "<مسیر ناشناخته>"


def _route_template(request: Request) -> str:
    """قالبِ مسیر، نه مسیرِ پرشده.

    بدون این، `/api/jobs/{id}` هزار کلیدِ متفاوت می‌سازد و شمارنده به‌جای
    خلاصه، یک فهرستِ بی‌فایده می‌شود.

    و مسیری که به هیچ روتی نمی‌خورد **همه** زیر یک کلید جمع می‌شود: وگرنه یک
    خزنده با آدرس‌های تصادفی می‌تواند این دیکشنری را بی‌کران بزرگ کند — یعنی
    نشتِ حافظه از راهِ سنجه‌ای که قرار بود سلامت را نشان دهد.
    """
    route = request.scope.get("route")
    return getattr(route, "path", None) or UNMATCHED_ROUTE


class RequestContextMiddleware(BaseHTTPMiddleware):
    """شناسه‌ی درخواست + لاگِ دسترسی + شمارنده."""

    async def dispatch(self, request: Request, call_next):
        incoming = _clean_id(request.headers.get(REQUEST_ID_HEADER))
        # شناسه‌ی بیرونی پذیرفته می‌شود (تا زنجیره‌ی proxy → API → job قطع نشود)
        # ولی پاک و بریده می‌شود؛ ورودیِ کنترل‌نشده نه در لاگ جا دارد نه در هدر.
        request_id = incoming or uuid.uuid4().hex[:16]
        token = _request_id.set(request_id)
        started = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers[REQUEST_ID_HEADER] = request_id
            return response
        finally:
            elapsed_ms = (time.perf_counter() - started) * 1000
            _record(request, status, elapsed_ms)
            logger.info(
                "%s %s → %s در %.0f میلی‌ثانیه [rid=%s]",
                request.method, _route_template(request), status, elapsed_ms,
                request_id,
            )
            _request_id.reset(token)


def _record(request: Request, status: int, elapsed_ms: float) -> None:
    key = f"{request.method} {_route_template(request)}"
    with _lock:
        _counters["requests_total"] += 1
        _counters[f"status_{status // 100}xx"] += 1
        _counters[f"route::{key}"] += 1
        _duration_ms_total[key] += int(elapsed_ms)
        if elapsed_ms > _slowest.get(key, 0.0):
            _slowest[key] = elapsed_ms


def metrics_snapshot() -> dict:
    """عکسِ شمارنده‌ها. سبک عمداً ساده است: بدون وابستگیِ تازه."""
    with _lock:
        counters = dict(_counters)
        durations = dict(_duration_ms_total)
        slowest = dict(_slowest)
        since = _started_at

    routes = []
    for key, count in sorted(counters.items()):
        if not key.startswith("route::"):
            continue
        name = key[len("route::"):]
        total_ms = durations.get(name, 0)
        routes.append({
            "route": name,
            "count": count,
            "avg_ms": round(total_ms / count, 1) if count else None,
            "max_ms": round(slowest.get(name, 0.0), 1),
        })

    total = counters.get("requests_total", 0)
    errors = counters.get("status_5xx", 0)
    return {
        "since": since,
        "uptime_seconds": round(time.time() - since, 1),
        "requests_total": total,
        "by_status_class": {
            key: value for key, value in sorted(counters.items())
            if key.startswith("status_")
        },
        "error_rate": round(errors / total, 4) if total else None,
        "routes": sorted(routes, key=lambda r: -r["count"])[:40],
        "note_fa": (
            "این شمارنده‌ها در حافظه‌اند و با هر ری‌استارت صفر می‌شوند؛ "
            "«uptime_seconds» می‌گوید از کِی می‌شمارند."
        ),
    }


def reset_metrics() -> None:
    """فقط برای تست‌ها."""
    global _started_at
    with _lock:
        _counters.clear()
        _duration_ms_total.clear()
        _slowest.clear()
        _started_at = time.time()
