"""§۳۲: شناسه‌ی درخواست، لاگِ ساختاریافته، شمارنده، و healthی که دروغ نگوید.

## چرا این تست‌ها

`/api/health` بی‌قید و شرط `"ok"` برمی‌گرداند — یعنی با دیتابیسِ خراب هم «سالم»
می‌گفت. سنجه‌ای که همیشه سبز باشد، سنجه نیست؛ فقط آرامشِ کاذب است.

و وقتی کاربر می‌گفت «صبح خطا داد»، هیچ راهی نبود که لاگِ آن درخواست و لاگِ کارِ
پس‌زمینه‌ای که همان درخواست کلید زد به هم وصل شوند.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

from api.main import app  # noqa: E402
from api.observability import (  # noqa: E402
    REQUEST_ID_HEADER,
    RequestIdLogFilter,
    current_request_id,
    metrics_snapshot,
    reset_metrics,
    set_request_id,
)

client = TestClient(app)


# ═════════════════════════════════════════════════ شناسه‌ی درخواست
def test_every_response_carries_a_request_id():
    response = client.get("/api/health")

    assert response.headers.get(REQUEST_ID_HEADER)
    assert len(response.headers[REQUEST_ID_HEADER]) >= 8


def test_two_requests_get_different_ids():
    first = client.get("/api/health").headers[REQUEST_ID_HEADER]
    second = client.get("/api/health").headers[REQUEST_ID_HEADER]

    assert first != second


def test_an_incoming_id_is_kept_so_the_chain_is_not_broken():
    """پشتِ proxy، شناسه از بیرون می‌آید؛ عوض‌کردنش زنجیره را قطع می‌کند.

    مقدارِ هدر باید ASCII باشد — همان محدودیتی که توکنِ فارسی را هم غیرقابل‌ارسال
    می‌کند.
    """
    response = client.get("/api/health", headers={REQUEST_ID_HEADER: "trace-from-proxy"})

    assert response.headers[REQUEST_ID_HEADER] == "trace-from-proxy"


def test_a_control_character_in_the_incoming_id_is_stripped():
    """این مقدار دوباره در هدرِ پاسخ می‌نشیند؛ تزریقِ هدر نباید ممکن باشد."""
    from api.observability import _clean_id

    assert _clean_id("abc\r\nX-Evil: 1") == "abcX-Evil: 1"
    assert _clean_id("شناسه‌ی فارسی") == ""


def test_a_very_long_incoming_id_is_truncated():
    """ورودیِ کنترل‌نشده در لاگ جای ندارد."""
    response = client.get("/api/health", headers={REQUEST_ID_HEADER: "x" * 500})

    assert len(response.headers[REQUEST_ID_HEADER]) == 64


def test_the_id_reaches_the_error_response_too():
    """درخواستی که ۴۰۴ می‌گیرد هم باید قابلِ ردیابی باشد."""
    response = client.get("/api/jobs/شناسه‌ای-که-وجود-ندارد")

    assert response.status_code in (404, 422)
    assert response.headers.get(REQUEST_ID_HEADER)


# ═════════════════════════════════════════════════ لاگِ ساختاریافته
def test_the_log_filter_stamps_every_record():
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "پیام", None, None)
    set_request_id("rid-آزمون")
    try:
        assert RequestIdLogFilter().filter(record) is True
        assert record.request_id == "rid-آزمون"
    finally:
        set_request_id("-")


def test_outside_a_request_the_id_is_a_dash_not_a_crash():
    set_request_id("-")
    assert current_request_id() == "-"


# ═════════════════════════════════════════════════════════ شمارنده
def test_metrics_count_requests_by_route_template():
    """قالبِ مسیر، نه مسیرِ پرشده — وگرنه شمارنده هزار کلید می‌شود."""
    reset_metrics()
    for _ in range(3):
        client.get("/api/health")

    snapshot = metrics_snapshot()
    routes = {row["route"]: row for row in snapshot["routes"]}

    assert snapshot["requests_total"] == 3
    assert routes["GET /api/health"]["count"] == 3
    assert routes["GET /api/health"]["avg_ms"] is not None


def test_metrics_are_reachable_from_the_api():
    body = client.get("/api/v1/ops/metrics").json()

    assert "requests_total" in body
    assert "uptime_seconds" in body
    # ادعایِ صادقانه: این عددها با ری‌استارت صفر می‌شوند و باید گفته شود
    assert "ری‌استارت" in body["note_fa"]


def test_metrics_do_not_explode_on_an_unknown_path():
    reset_metrics()
    client.get("/مسیری/که/وجود/ندارد")

    assert metrics_snapshot()["requests_total"] == 1


# ═════════════════════════════════════════════════════════ health
def test_health_reports_the_database_it_actually_touched():
    body = client.get("/api/health").json()

    assert body["status"] == "ok"
    assert body["database"]["ok"] is True
    assert body["database"]["latency_ms"] >= 0


def test_health_says_unhealthy_when_the_database_is_broken(monkeypatch):
    """مهم‌ترین ادعای این فایل: با دیتابیسِ خراب، «ok» ممنوع است."""
    from api import main as api_main

    def explode():
        raise OSError("فایل دیتابیس در دسترس نیست")

    monkeypatch.setattr(api_main.store, "_conn", explode, raising=True)
    response = client.get("/api/health")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "unhealthy"
    assert body["database"]["ok"] is False
    assert "دیتابیس" in body["database"]["note_fa"]


@pytest.mark.parametrize("field", ["ai_available", "sms_enabled", "api_token_required"])
def test_health_keeps_the_fields_the_ui_already_reads(field):
    """صفرـرگرسیون: افزودنِ `database` نباید قرارداد قبلی را عوض کند."""
    assert field in client.get("/api/health").json()
