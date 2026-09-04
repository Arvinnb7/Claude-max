"""گاردِ توکن روی مسیرهای نوشتنی و پرخرج.

این سیستم می‌تواند پیامک واقعی بفرستد و پول خرج کند، و تا پیش از این هیچ
احراز هویتی نداشت. مهم‌ترین تستِ این فایل
`test_expensive_routes_reject_a_missing_token` است.

قاعده‌ی سازگاری: بدون تنظیمِ `MKT_API_TOKEN` هیچ‌چیز بسته نمی‌شود (وگرنه هر نصبِ
موجود با ارتقا از کار می‌افتاد) — ولی این حالت **صریح هشدار می‌دهد**.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

from api.main import app  # noqa: E402

from mktcore.config import get_settings  # noqa: E402
from mktcore.security import (  # noqa: E402
    HEADER_NAME,
    token_configured,
    token_is_usable,
)

client = TestClient(app)

# توکنِ واقعی باید ASCII باشد: مقدارِ هدرِ HTTP نمی‌تواند کاراکتر فارسی داشته
# باشد. تستِ اختصاصیِ همین محدودیت پایین‌تر هست.
TOKEN = "test-token-abc123"

# (method, path, body) — مسیرهایی که پول خرج می‌کنند یا داده را تغییر می‌دهند
GUARDED = [
    ("post", "/api/sms/send",
     {"session_id": "x", "kind": "سررسیدشده", "template": "س", "dry_run": True}),
    ("post", "/api/scheduler/run-now", None),
    ("post", "/api/v1/campaigns", {"name": "آزمون"}),
    ("post", "/api/v1/campaigns/1/send", {"dry_run": True}),
    ("post", "/api/v1/campaigns/1/close", None),
    ("post", "/api/v1/customers/1/opt-out", {"reason_fa": "دلیل"}),
    ("delete", "/api/v1/customers/1/opt-out", None),
    ("post", "/api/v1/opportunities/1/dismiss", {}),
    # خواندنی ولی PII: دفترِ «تماس نگیر» فهرستِ افرادِ مشخص است
    ("get", "/api/v1/contact-suppressions", None),
]

# مسیرهای خواندنی که باید باز بمانند
OPEN_READS = [
    "/api/health",
    "/api/v1/opportunities",
    "/api/v1/customers",
    "/api/v1/data-quality",
    "/api/v1/uplift",
    "/api/v1/experiment-plan",
]


@pytest.fixture
def with_token(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "mkt_api_token", TOKEN, raising=False)
    return TOKEN


def _call(method: str, path: str, body, headers=None):
    fn = getattr(client, method)
    if body is None:
        return fn(path, headers=headers or {})
    return fn(path, json=body, headers=headers or {})


# ═══════════════════════════════════════════ با توکنِ تنظیم‌شده
@pytest.mark.parametrize(("method", "path", "body"), GUARDED)
def test_expensive_routes_reject_a_missing_token(with_token, method, path, body):
    r = _call(method, path, body)
    assert r.status_code == 401, f"{path} بدون توکن باز است"
    assert HEADER_NAME in r.json()["detail"]


@pytest.mark.parametrize(("method", "path", "body"), GUARDED)
def test_expensive_routes_reject_a_wrong_token(with_token, method, path, body):
    r = _call(method, path, body, {HEADER_NAME: "wrong-token"})
    assert r.status_code == 401


@pytest.mark.parametrize(("method", "path", "body"), GUARDED)
def test_a_correct_token_passes_the_guard(with_token, method, path, body):
    """با توکنِ درست دیگر ۴۰۱ نمی‌گیریم؛ هر کد دیگری منطقِ خودِ مسیر است."""
    r = _call(method, path, body, {HEADER_NAME: TOKEN})
    assert r.status_code != 401, r.text


@pytest.mark.parametrize("path", OPEN_READS)
def test_read_routes_stay_open(with_token, path):
    """خواندن نباید بسته شود: داشبورد بدون توکن هم باید کار کند."""
    r = client.get(path)
    assert r.status_code != 401, f"{path} نباید توکن بخواهد"


# ═════════════════════════════════ بدون توکن: سازگاری عقب‌رو
@pytest.fixture
def without_token(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "mkt_api_token", None, raising=False)


def test_without_a_configured_token_nothing_is_blocked(without_token):
    """هر نصبِ موجود باید بدون تغییر تنظیمات کار کند."""
    r = client.post("/api/v1/campaigns", json={"name": "بدون توکن"})
    assert r.status_code != 401


def test_health_warns_loudly_when_unprotected(without_token):
    body = client.get("/api/health").json()
    assert body["api_token_required"] is False
    assert "امنیت_هشدار" in body, "نبودِ گارد باید صریح گزارش شود"
    assert "پیامک واقعی" in body["امنیت_هشدار"]


def test_health_reports_protection_when_configured(with_token):
    body = client.get("/api/health").json()
    assert body["api_token_required"] is True
    assert "امنیت_هشدار" not in body


def test_token_configured_reflects_settings(with_token):
    assert token_configured() is True


# ═════════════════════════════════ گاردهای مستقل از توکن
def test_scheduler_run_now_needs_confirmation_when_it_would_really_send(monkeypatch):
    """این مسیر هیچ پارامتری نداشت؛ یک درخواست خالی ارسال واقعی را کلید می‌زد."""
    settings = get_settings()
    monkeypatch.setattr(settings, "mkt_api_token", None, raising=False)
    monkeypatch.setattr(settings, "mkt_auto_sms", True, raising=False)
    monkeypatch.setattr(settings, "mkt_sms_enable", True, raising=False)
    monkeypatch.setattr(settings, "kavenegar_api_key", "k", raising=False)

    blocked = client.post("/api/scheduler/run-now")
    assert blocked.status_code == 409
    assert "confirm=true" in blocked.json()["detail"]

    allowed = client.post("/api/scheduler/run-now?confirm=true")
    assert allowed.status_code == 200


def test_scheduler_run_now_stays_open_when_it_cannot_really_send(monkeypatch):
    """وقتی ارسال واقعی ممکن نیست، تأیید لازم نیست — رفتار قبلی حفظ می‌شود."""
    settings = get_settings()
    monkeypatch.setattr(settings, "mkt_api_token", None, raising=False)
    monkeypatch.setattr(settings, "mkt_auto_sms", False, raising=False)
    assert client.post("/api/scheduler/run-now").status_code == 200


def test_legacy_sms_limit_is_capped(monkeypatch):
    """بدون سقف، یک درخواست می‌توانست کل پایگاه مشتری را پیامک کند."""
    settings = get_settings()
    monkeypatch.setattr(settings, "mkt_api_token", None, raising=False)
    r = client.post("/api/sms/send", json={
        "session_id": "x", "kind": "سررسیدشده", "template": "س",
        "limit": 1_000_000, "dry_run": True,
    })
    assert r.status_code == 422, "limit بی‌سقف نباید پذیرفته شود"


# ═════════════════════════════ محدودیتِ واقعیِ هدرِ HTTP
def test_a_non_ascii_token_is_flagged_as_unusable(monkeypatch):
    """توکنِ فارسی روی کاغذ درست است ولی هیچ کلاینتی نمی‌تواند بفرستدش.

    مقدارِ هدرِ HTTP باید ASCII باشد؛ بدون این هشدار، کاربر توکنِ فارسی می‌گذاشت
    و **همه‌ی** درخواست‌ها با خطایی مبهم رد می‌شدند.
    """
    settings = get_settings()
    monkeypatch.setattr(settings, "mkt_api_token", "توکنِ-فارسی", raising=False)
    assert token_configured() is True
    assert token_is_usable() is False

    body = client.get("/api/health").json()
    assert "توکن_هشدار" in body
    assert "ASCII" in body["توکن_هشدار"]


def test_an_ascii_token_is_usable(with_token):
    assert token_is_usable() is True
    assert "توکن_هشدار" not in client.get("/api/health").json()
