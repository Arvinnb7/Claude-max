"""حلقه‌ی کامل سود ناخالص — از ورودِ بها تا سودِ افزوده‌ی کمپین.

این تست دروازه‌ی پذیرشِ **فاز ۳** سند را می‌سنجد:

> a test campaign can be run end-to-end with treatment/control and
> **incremental gross profit** reporting.

تا پیش از این، آن دروازه رد می‌شد چون فقط درآمد افزوده داشتیم.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

from api.main import app  # noqa: E402

from mktcore.db import session_scope  # noqa: E402
from mktcore.db.models import CampaignMember, OrderLine, Product  # noqa: E402

from .conftest import poll_job, reset_contact_history  # noqa: E402

client = TestClient(app)


@pytest.fixture(autouse=True)
def _fresh_contact_history():
    """هر تست از وضعیتِ «کسی تازه تماس نگرفته» شروع می‌کند (خستگیِ تماسِ کمپین)."""
    reset_contact_history()


@pytest.fixture(scope="module")
def analyzed() -> str:
    r = client.post("/api/sample")
    assert r.status_code == 200, r.text
    data = r.json()
    mapping = {x["role"]: x["suggested"] for x in data["roles"] if x["suggested"]}
    r = client.post("/api/analyze", json={
        "session_id": data["session_id"], "mapping": mapping, "horizon": 3,
    })
    assert r.status_code == 200, r.text
    poll_job(client, r.json()["job_id"])
    return data["session_id"]


def _line_costs(session) -> dict[int, tuple[int | None, str | None]]:
    rows = session.execute(
        select(OrderLine.id, OrderLine.cost_rial, OrderLine.cost_confidence)
    ).all()
    return {r[0]: (r[1], r[2]) for r in rows}


def _all_products() -> list[str]:
    with session_scope() as session:
        return [str(n) for n in session.scalars(select(Product.canonical_name)).all()]


# ═══════════════════════════════════ پوشش، پیش و پس از ورودِ بها
def test_coverage_endpoint_explains_why_profit_is_missing(analyzed):
    body = client.get("/api/v1/cost-coverage").json()
    assert body["available"] is True
    assert 0.0 <= body["coverage"] <= 1.0
    assert body["note_fa"], "باید بگوید چرا سود محاسبه شد یا نشد"


def test_file_cost_wins_over_imported_history(analyzed):
    """فایل فروشِ نمونه خودش ستون بها دارد؛ ورودِ تاریخچه نباید آن را عوض کند.

    §۳.۴: منبعِ مستقیم‌تر اولویت دارد. پس اینجا انتظارِ درست «بالا رفتنِ پوشش»
    نیست — پوشش از قبل کامل است — بلکه **دست‌نخوردن** بهای موجود است.
    """
    products = _all_products()
    assert products, "داده‌ی نمونه باید کالا داشته باشد"

    before = client.get("/api/v1/cost-coverage").json()
    assert before["coverage"] == 1.0, "داده‌ی نمونه ستون بها دارد"

    with session_scope() as session:
        snapshot = _line_costs(session)

    r = client.post("/api/v1/costs", json={
        "rows": [{"product": name, "cost": 999_999} for name in products],
    })
    assert r.status_code == 200, r.text
    assert r.json()["written"] + r.json()["updated"] == len(products)

    with session_scope() as session:
        assert _line_costs(session) == snapshot, (
            "بهای آمده از فایل فروش نباید با تاریخچه بازنویسی شود"
        )


def test_imported_history_fills_lines_that_have_no_cost(analyzed):
    """مسیرِ واقعیِ این کسب‌وکار: بها در فایل فروش نیست، در سیستم دیگری است.

    داده‌ی نمونه بها دارد، پس برای سنجشِ این مسیر بهای یک کالا موقتاً برداشته
    می‌شود، تاریخچه وارد می‌شود، و در پایان وضعیت اولیه برگردانده می‌شود.
    """
    target = _all_products()[0]
    with session_scope() as session:
        product_id = session.scalar(
            select(Product.id).where(Product.canonical_name == target)
        )
        rows = session.execute(
            select(OrderLine.id, OrderLine.cost_rial, OrderLine.cost_confidence,
                   OrderLine.gross_profit_rial)
            .where(OrderLine.product_id == product_id)
        ).all()
    assert rows, "این کالا باید خط فروش داشته باشد"
    original = {r[0]: (r[1], r[2], r[3]) for r in rows}

    try:
        with session_scope() as session:
            session.execute(
                update(OrderLine)
                .where(OrderLine.product_id == product_id)
                .values(cost_rial=None, cost_confidence=None, gross_profit_rial=None)
            )
        stripped = client.get("/api/v1/cost-coverage").json()
        assert stripped["coverage"] < 1.0, "بها برداشته شد، پس پوشش باید ناقص شود"

        r = client.post("/api/v1/costs", json={
            "rows": [{"product": target, "cost": 100}],
        })
        assert r.status_code == 200, r.text
        assert r.json()["applied"]["updated"] >= len(original)

        restored = client.get("/api/v1/cost-coverage").json()
        assert restored["coverage"] > stripped["coverage"]
        assert restored["coverage"] == 1.0

        with session_scope() as session:
            confidences = set(session.scalars(
                select(OrderLine.cost_confidence)
                .where(OrderLine.product_id == product_id)
            ).all())
        assert confidences <= {"history_exact", "history_imputed"}, (
            "بهای آمده از تاریخچه باید صریحاً برچسب بخورد، نه «from_file»"
        )
    finally:
        with session_scope() as session:
            for line_id, (cost, confidence, profit) in original.items():
                session.execute(
                    update(OrderLine).where(OrderLine.id == line_id).values(
                        cost_rial=cost, cost_confidence=confidence,
                        gross_profit_rial=profit,
                    )
                )


def test_unmatched_cost_rows_are_reported(analyzed):
    r = client.post("/api/v1/costs", json={
        "rows": [{"product": "کالایی که هرگز فروخته نشده", "cost": 500}],
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["unmatched_count"] == 1
    assert "کالایی که هرگز فروخته نشده" in body["unmatched_products"]


def test_lines_get_profit_after_cost_import(analyzed):
    client.post("/api/v1/costs", json={
        "rows": [{"product": name, "cost": 100} for name in _all_products()],
    })
    with session_scope() as session:
        rows = session.scalars(
            select(OrderLine).where(OrderLine.gross_profit_rial.isnot(None)).limit(5)
        ).all()
        pairs = [(r.revenue_rial, r.cost_rial, r.gross_profit_rial) for r in rows]

    assert pairs, "پس از ورودِ بها، خطوط باید سود بگیرند"
    for revenue, cost, profit in pairs:
        assert profit == revenue - cost, "سود باید دقیقاً درآمد منهای بها باشد"


# ═══════════ دروازه‌ی پذیرش فاز ۳: سود افزوده‌ی کمپین
def _ledger_window() -> str:
    """تاریخی که دفتر کل حول آن خط فروش دارد.

    پنجره‌ی سنجش از لحظه‌ی تماس شروع می‌شود؛ در تست، «امروز» بسیار جلوتر از
    آخرین خط داده‌ی نمونه است و هر دو بازو صفر می‌شوند. صفرِ درست چیزی درباره‌ی
    محاسبه ثابت نمی‌کند، پس پنجره روی بازه‌ای برده می‌شود که واقعاً خرید دارد.
    """
    with session_scope() as session:
        last = session.scalar(select(func.max(OrderLine.line_date)))
    return (pd.Timestamp(last) - pd.Timedelta(days=30)).date().isoformat()


def _backdate(campaign_id: int, day: str) -> None:
    stamp = pd.Timestamp(day).timestamp()
    with session_scope() as session:
        session.execute(
            update(CampaignMember)
            .where(CampaignMember.campaign_id == campaign_id)
            .values(assigned_date=day, assigned_at=stamp)
        )
        session.execute(
            update(CampaignMember).where(
                CampaignMember.campaign_id == campaign_id,
                CampaignMember.exposure_at.isnot(None),
            ).values(exposure_date=day, exposure_at=stamp)
        )


def test_campaign_reports_incremental_gross_profit_with_full_coverage(analyzed):
    """دروازه‌ی پذیرش فاز ۳ که تا امروز رد می‌شد."""
    client.post("/api/v1/costs", json={
        "rows": [{"product": name, "cost": 100} for name in _all_products()],
    })
    coverage = client.get("/api/v1/cost-coverage").json()["coverage"]
    assert coverage >= 0.999, "این دروازه به پوشش کاملِ بها نیاز دارد"

    created = client.post("/api/v1/campaigns", json={
        "name": "سود افزوده", "holdout_pct": 20,
    })
    assert created.status_code == 200, created.text
    campaign_id = created.json()["id"]

    # خروجی = لحظه‌ی تماس. بدون آن، گروه آزمایش هنوز وارد آزمایش نشده و
    # پنجره‌ی سنجشش باز نشده است.
    assert client.get(f"/api/v1/campaigns/{campaign_id}/export").status_code == 200
    _backdate(campaign_id, _ledger_window())

    client.post(f"/api/v1/campaigns/{campaign_id}/refresh")
    report = client.get(f"/api/v1/campaigns/{campaign_id}").json()["report"]
    arms = report["arms"]

    assert arms["treatment"]["size"] > 0 and arms["control"]["size"] > 0
    assert arms["treatment"]["revenue_rial"] > 0, "پنجره باید خرید واقعی داشته باشد"

    assert "incremental_gross_profit" not in report["blocked_metrics"], (
        "با پوشش کامل، این سنجه دیگر نباید مسدود باشد"
    )
    assert report["gross_profit_note_fa"]

    # عدد باید همان تفاضلِ سودِ سرانه باشد، نه چیز دیگری
    expected = round(
        (arms["treatment"]["gross_profit_rial"] / arms["treatment"]["size"]
         - arms["control"]["gross_profit_rial"] / arms["control"]["size"])
        * arms["treatment"]["size"]
    )
    observed = report["observed_difference"]
    assert observed["gross_profit_rial"] == expected
    # سود از درآمد جدا است: با بهای مثبت، این دو نباید یکی باشند
    assert observed["gross_profit_rial"] != observed["revenue_rial"]
    if report["is_causal"]:
        assert report["incremental_gross_profit_rial"] == expected
    else:
        # حکمِ غیرعلّی: عددِ «افزوده» نداریم، فقط تفاوتِ مشاهده‌شده با نامِ خودش
        assert report["incremental_gross_profit_rial"] is None
        assert report["incremental_revenue_rial"] is None
        assert "مشاهده‌ای" in report["gross_profit_note_fa"]


def test_incomplete_cost_coverage_blocks_the_number(analyzed):
    """پوشش ناقص ⇒ عدد گزارش نمی‌شود و دلیلش صریح است."""
    created = client.post("/api/v1/campaigns", json={
        "name": "پوشش ناقص", "holdout_pct": 20,
    })
    campaign_id = created.json()["id"]
    client.get(f"/api/v1/campaigns/{campaign_id}/export")
    day = _ledger_window()
    _backdate(campaign_id, day)
    client.post(f"/api/v1/campaigns/{campaign_id}/refresh")

    before = client.get(f"/api/v1/campaigns/{campaign_id}").json()["report"]
    assert before["arms"]["treatment"]["cost_rial"] is not None

    # خطی که **قطعاً** داخل پنجره‌ی یک عضو گروه آزمایش است؛ وگرنه برداشتنِ بها
    # ممکن است هیچ اثری روی این کمپین نگذارد و تست چیزی ثابت نکند.
    end = (pd.Timestamp(day) + pd.Timedelta(days=30)).date().isoformat()
    with session_scope() as session:
        line_id, cost, profit, confidence = session.execute(
            select(OrderLine.id, OrderLine.cost_rial, OrderLine.gross_profit_rial,
                   OrderLine.cost_confidence)
            .join(CampaignMember, CampaignMember.customer_id == OrderLine.customer_id)
            .where(
                CampaignMember.campaign_id == campaign_id,
                CampaignMember.arm == "treatment",
                OrderLine.line_date >= day,
                OrderLine.line_date < end,
                OrderLine.cost_rial.isnot(None),
            ).limit(1)
        ).one()

    try:
        with session_scope() as session:
            session.execute(
                update(OrderLine).where(OrderLine.id == line_id)
                .values(cost_rial=None, gross_profit_rial=None, cost_confidence=None)
            )
        client.post(f"/api/v1/campaigns/{campaign_id}/refresh")
        report = client.get(f"/api/v1/campaigns/{campaign_id}").json()["report"]

        assert report["arms"]["treatment"]["cost_rial"] is None
        assert report["incremental_gross_profit_rial"] is None
        assert "incremental_gross_profit" in report["blocked_metrics"]
        assert "ناقص" in report["gross_profit_note_fa"]
    finally:
        with session_scope() as session:
            session.execute(
                update(OrderLine).where(OrderLine.id == line_id)
                .values(cost_rial=cost, gross_profit_rial=profit,
                        cost_confidence=confidence)
            )
        client.post(f"/api/v1/campaigns/{campaign_id}/refresh")


def test_money_payload_shape_is_consistent(analyzed):
    """هر مبلغِ تازه باید همان سه‌کلیدیِ بقیه‌ی سیستم باشد."""
    created = client.post("/api/v1/campaigns", json={
        "name": "شکل پول", "holdout_pct": 10,
    })
    assert created.status_code == 200, created.text
    report = client.get(f"/api/v1/campaigns/{created.json()['id']}").json()["report"]
    profit = report.get("incremental_gross_profit")
    if profit is not None:
        assert set(profit) == {"rial", "display_text", "display_currency"}


# ═══════════════════════════════════ کف حاشیه: از «همیشه skip» به فیلترِ واقعی
def test_margin_floor_is_reported_as_unset_before_the_user_decides(analyzed):
    body = client.get("/api/v1/margin-floor").json()
    assert body["available"] is True
    assert body["margin_floor_bp"] is None
    assert body["products_with_margin"] > 0, "با پوشش بها، حاشیه باید محاسبه شود"
    assert "بررسی نشد" in body["note_fa"]


def test_setting_a_margin_floor_reaches_the_opportunity_engine(analyzed):
    """تنظیمِ کاربر باید واقعاً به زمینه‌ی فیلترها برسد، نه فقط ذخیره شود."""
    from mktcore.opportunities.engine import _policy_settings

    try:
        r = client.put("/api/v1/margin-floor", json={"margin_floor_bp": 2_000})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["margin_floor_bp"] == 2_000
        assert isinstance(body["products_below_floor"], list)
        assert "کف" in body["note_fa"]

        floor, margins, _capacity = _policy_settings("default", None)
        assert floor == 2_000
        assert margins, "حاشیه‌ی کالاها باید به موتور برسد"
    finally:
        client.put("/api/v1/margin-floor", json={"margin_floor_bp": None})

    assert client.get("/api/v1/margin-floor").json()["margin_floor_bp"] is None
