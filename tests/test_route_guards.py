"""هیچ مسیرِ نوشتنی یا پرخرجی نباید بی‌گارد بماند.

## چرا این تست وجود دارد

نسخه‌ی اولِ گارد **به‌ازای هر مسیر** اعمال می‌شد، یعنی هر مسیرِ تازه به‌طور
پیش‌فرض **باز** بود و فقط اگر نویسنده یادش می‌ماند بسته می‌شد. همین دقیقاً اتفاق
افتاد: `POST /api/strategy` و `POST /api/campaign` ماه‌ها باز بودند در حالی که
متنِ `security.py` و `.env.example` هر دو ادعا می‌کردند بسته‌اند — یعنی سند دروغ
می‌گفت و کسی نمی‌فهمید.

حالا گارد روی **کلِ برنامه** می‌نشیند و باز بودن باید صریح باشد. این تست همان
قاعده را پین می‌کند: کلِ برنامه پیمایش می‌شود (از جمله روترهای include‌شده که در
`app.routes` تخت نمی‌شوند) و برای هر مسیر، **خودِ تابعِ تصمیم** صدا زده می‌شود.
یعنی تست به وجودِ دکوراتور نگاه نمی‌کند، به **رفتار** نگاه می‌کند.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

from api.main import app  # noqa: E402

from mktcore.config import get_settings  # noqa: E402
from mktcore.security import (  # noqa: E402
    EXTRA_GUARDED_ROUTES,
    HEADER_NAME,
    OPEN_WRITE_ROUTES,
    WRITE_METHODS,
    require_token_for_writes,
    route_key,
)

TOKEN = "route-guard-token"

# مسیرهای زیرساختیِ خودِ FastAPI که تحویلِ ما نیستند
_INFRA_PATHS = {"/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"}


# ═════════════════════════════════════════════════════ پیمایشِ کاملِ مسیرها
def _walk(routes) -> list:
    """همه‌ی مسیرهای HTTP، از جمله روترهای include‌شده.

    در FastAPI ≥ ۰٫۱۴ روترِ include‌شده به‌صورت یک شیءِ `_IncludedRouter` در
    `app.routes` می‌نشیند و مسیرهایش **تخت نمی‌شوند**. نسخه‌ی اولِ همین تست
    همین را نمی‌دانست و در عمل فقط ۲۳ مسیر از ۴۷ مسیر را می‌دید — یعنی کلِ
    `/api/v1/*` از چشمش پنهان بود. اگر روزی این ساختار عوض شود،
    `test_the_walker_sees_the_whole_app` سر و صدا می‌کند.
    """
    found: list = []
    for route in routes:
        included = getattr(route, "original_router", None)
        if included is not None:
            found.extend(_walk(included.routes))
            continue
        if hasattr(route, "methods") and hasattr(route, "path"):
            found.append(route)
            continue
        nested = getattr(route, "routes", None)
        if nested:
            found.extend(_walk(nested))
    return found


def _pairs() -> list[tuple[str, str, object]]:
    """(متد، مسیر، شیءِ روت) برای هر ترکیبِ واقعیِ برنامه."""
    out: list[tuple[str, str, object]] = []
    for route in _walk(app.routes):
        if route.path in _INFRA_PATHS:
            continue
        for method in sorted(route.methods or []):
            if method in {"HEAD", "OPTIONS"}:
                continue
            out.append((method, route.path, route))
    seen: set[tuple[str, str]] = set()
    unique: list[tuple[str, str, object]] = []
    for method, path, route in sorted(out, key=lambda x: (x[1], x[0])):
        if (method, path) in seen:
            continue
        seen.add((method, path))
        unique.append((method, path, route))
    return unique


ALL_PAIRS = _pairs()


@pytest.fixture
def with_token(monkeypatch):
    monkeypatch.setattr(get_settings(), "mkt_api_token", TOKEN, raising=False)
    return TOKEN


def _decides_to_block(method: str, path: str, route, token: str = "") -> bool:
    """آیا گاردِ سطحِ برنامه این درخواست را رد می‌کند؟

    تصمیم را از **خودِ تابع** می‌پرسیم، نه از روی دکوراتورها. اگر فردا سازوکارِ
    گارد عوض شود ولی رفتار درست بماند، این تست بی‌جهت نمی‌شکند؛ و اگر رفتار
    عوض شود، حتماً می‌شکند.
    """
    headers = [(HEADER_NAME.lower().encode(), token.encode())] if token else []
    request = Request({
        "type": "http",
        "method": method,
        "path": path,
        "raw_path": path.encode(),
        "root_path": "",
        "scheme": "http",
        "server": ("testserver", 80),
        "query_string": b"",
        "headers": headers,
        "route": route,
    })
    try:
        require_token_for_writes(request)
    except HTTPException as exc:
        assert exc.status_code == 401
        return True
    return False


# ═════════════════════════════════════════════════════════ قاعده‌ی اصلی
def test_the_walker_sees_the_whole_app():
    """اگر این عدد یک‌باره افت کند، یعنی پیمایش کور شده — نه اینکه مسیر کم شده."""
    paths = {path for _, path, _ in ALL_PAIRS}
    assert len(ALL_PAIRS) >= 40, f"فقط {len(ALL_PAIRS)} مسیر دیده شد"
    # نمونه‌ای از هر سه روترِ include‌شده باید در فهرست باشد
    for probe in (
        "/api/v1/opportunities",
        "/api/v1/campaigns/{campaign_id}/send",
        "/api/v1/models/{run_id}/promote",
    ):
        assert probe in paths, f"{probe} در پیمایش دیده نشد"


@pytest.mark.parametrize(("method", "path"), [(m, p) for m, p, _ in ALL_PAIRS])
def test_every_write_route_is_blocked_unless_explicitly_opened(
    with_token, method, path,
):
    """مسیرِ نوشتنی یا بسته است یا **با دلیلِ مکتوب** در فهرستِ سفید."""
    route = next(r for m, p, r in ALL_PAIRS if (m, p) == (method, path))
    key = route_key(method, path)
    should_block = (method in WRITE_METHODS or key in EXTRA_GUARDED_ROUTES) and (
        key not in OPEN_WRITE_ROUTES
    )

    assert _decides_to_block(method, path, route) is should_block, (
        f"{key}: تصمیمِ گارد با فهرستِ مستند نمی‌خواند"
    )


def test_a_correct_token_is_accepted_everywhere(with_token):
    """گاردی که با توکنِ درست هم رد کند، فقط برنامه را خراب کرده است."""
    for method, path, route in ALL_PAIRS:
        assert not _decides_to_block(method, path, route, token=TOKEN), path


def test_without_a_configured_token_nothing_is_blocked():
    """سازگاری عقب‌رو: نصبِ بدونِ `MKT_API_TOKEN` باید مثل دیروز کار کند."""
    assert not (get_settings().mkt_api_token or "").strip()
    for method, path, route in ALL_PAIRS:
        assert not _decides_to_block(method, path, route), path


def test_expensive_and_pii_routes_are_guarded(with_token):
    """مسیرهایی که پول خرج می‌کنند یا PII می‌دهند — اسم‌به‌اسم."""
    must_block = {
        "POST /api/strategy": "هزینه‌ی واقعی Anthropic",
        "POST /api/campaign": "هزینه‌ی واقعی Anthropic",
        "POST /api/sms/send": "ارسال واقعی پیامک",
        "POST /api/scheduler/run-now": "می‌تواند ارسال را کلید بزند",
        "POST /api/v1/campaigns/{campaign_id}/send": "ارسال واقعی پیامک",
        "GET /api/v1/campaigns/{campaign_id}/export": "فهرست شماره‌ی تماس کامل",
        "GET /api/export": "اکسل با ستون موبایل",
        "GET /api/outbox": "شماره‌ی خامِ گیرنده‌های پیامک",
        "DELETE /api/v1/customers/{customer_id}/opt-out": "پس‌گرفتن انصراف مشتری",
        "POST /api/v1/models/{run_id}/promote": "فعال‌کردن مدل روی داده‌ی واقعی",
        "POST /api/v1/costs": "بازنویسی بهای تمام‌شده و در نتیجه همه‌ی سودها",
        "PUT /api/v1/margin-floor": "کف حاشیه، دروازه‌ی همه‌ی پیشنهادها",
    }
    by_key = {route_key(m, p): (m, p, r) for m, p, r in ALL_PAIRS}

    failures = []
    for key, why in must_block.items():
        entry = by_key.get(key)
        if entry is None:
            failures.append(f"{key} (اصلاً وجود ندارد)")
        elif not _decides_to_block(*entry):
            failures.append(f"{key} ({why})")

    assert not failures, "این مسیرها باید گارد داشته باشند: " + " · ".join(failures)


# ═════════════════════════════════════════════════ بهداشتِ فهرستِ سفید
def test_the_allow_list_has_no_stale_entries():
    """استثنایی که مسیرش دیگر وجود ندارد، فهرست را بی‌اعتبار می‌کند."""
    keys = {route_key(m, p) for m, p, _ in ALL_PAIRS}
    stale = sorted((set(OPEN_WRITE_ROUTES) | set(EXTRA_GUARDED_ROUTES)) - keys)

    assert not stale, f"این ردیف‌ها دیگر مسیر ندارند: {stale}"


def test_every_allow_list_entry_has_a_reason():
    documented = {**OPEN_WRITE_ROUTES, **EXTRA_GUARDED_ROUTES}
    for key, reason in documented.items():
        assert len(reason.strip()) > 20, f"ردیفِ {key} دلیلِ واقعی ندارد"


def test_allow_list_entries_are_well_formed():
    """`POST /api/x` — نه `/api/x`، نه `post /api/x`."""
    for key in list(OPEN_WRITE_ROUTES) + list(EXTRA_GUARDED_ROUTES):
        assert re.fullmatch(r"[A-Z]+ /\S*", key), f"کلیدِ بدشکل: {key!r}"


# ═══════════════════════════════════════ اثباتِ زنده روی سه نقصِ واقعی
_CLIENT = TestClient(app)


@pytest.mark.parametrize(("method", "path", "body"), [
    ("post", "/api/strategy", {"session_id": "x"}),
    ("post", "/api/campaign", {"session_id": "x", "segment": "y"}),
    ("get", "/api/v1/campaigns/1/export", None),
])
def test_the_three_defects_reject_a_missing_token(with_token, method, path, body):
    """این سه مسیر همان‌هایی‌اند که حسابرسی باز پیدایشان کرد."""
    call = getattr(_CLIENT, method)
    response = call(path) if body is None else call(path, json=body)

    assert response.status_code == 401, response.text
    assert HEADER_NAME in response.json()["detail"]
