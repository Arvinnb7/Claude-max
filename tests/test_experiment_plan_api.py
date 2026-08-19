"""برنامه‌ی آزمایش روی داده‌ی واقعی — عرضه، دروازه، و قرارداد API.

مهم‌ترین تستِ این فایل `test_supply_excludes_customers_the_gate_blocks` است:
اگر مشتریِ منصرف یا عضوِ گروه کنترل در شمارشِ «ظرفیت آزمایش» بیاید، برنامه
کمپینی را پیشنهاد می‌دهد که در عمل آن اندازه را هرگز پیدا نمی‌کند.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

from api.main import app  # noqa: E402

from mktcore.contact.register import (  # noqa: E402
    build_gate,
    record_opt_out,
    revoke_opt_out,
)
from mktcore.db import session_scope  # noqa: E402
from mktcore.db.models import Business, Customer, Opportunity  # noqa: E402
from mktcore.experiments.plan import collect_supply  # noqa: E402

from .conftest import poll_job  # noqa: E402

client = TestClient(app)


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


def _supply() -> list:
    with session_scope() as session:
        business_id = session.scalar(select(Business.id))
        return collect_supply(session, business_id)


# ═══════════════════════════════════════════════════════════ عرضه
def test_supply_is_built_from_open_opportunities(analyzed):
    """عرضه‌ی هر سلول = مشتریانِ **یکتای** آن سلول.

    جمعِ سلول‌ها می‌تواند از سرشمارِ افراد بیشتر باشد و این درست است: مشتری‌ای که
    در دو نوع اقدام حاضر است، دو فرصتِ تماسِ جدا می‌سازد. پس ادعای درست، ادعای
    **درون‌سلولی** است.
    """
    supplies = _supply()
    assert supplies, "با داده‌ی تحلیل‌شده باید فرصت باز و در نتیجه عرضه وجود داشته باشد"
    assert all(s.available > 0 for s in supplies)

    with session_scope() as session:
        business_id = session.scalar(select(Business.id))
        rows = session.execute(
            select(Opportunity.kind, Opportunity.customer_id).where(
                Opportunity.business_id == business_id,
                Opportunity.status == "open",
                Opportunity.customer_id.isnot(None),
            )
        ).all()

    per_kind_customers: dict[str, set[int]] = {}
    for kind, customer_id in rows:
        per_kind_customers.setdefault(str(kind), set()).add(int(customer_id))

    per_kind_supply: dict[str, int] = {}
    for s in supplies:
        per_kind_supply[s.kind] = per_kind_supply.get(s.kind, 0) + s.available

    for kind, counted in per_kind_supply.items():
        assert counted <= len(per_kind_customers[kind]), (
            f"عرضه‌ی نوع {kind} از مشتریانِ یکتایش بیشتر شد"
        )


def test_supply_counts_each_customer_once_per_cell(analyzed):
    """یک مشتری با چند فرصتِ هم‌نوع نباید ظرفیت را دو برابر نشان دهد."""
    supplies = _supply()
    with session_scope() as session:
        business_id = session.scalar(select(Business.id))
        rows = session.execute(
            select(Opportunity.kind, Opportunity.customer_id).where(
                Opportunity.business_id == business_id,
                Opportunity.status == "open",
                Opportunity.customer_id.isnot(None),
            )
        ).all()
    per_kind_rows: dict[str, int] = {}
    for kind, _cid in rows:
        per_kind_rows[str(kind)] = per_kind_rows.get(str(kind), 0) + 1
    per_kind_supply: dict[str, int] = {}
    for s in supplies:
        per_kind_supply[s.kind] = per_kind_supply.get(s.kind, 0) + s.available
    for kind, counted in per_kind_supply.items():
        assert counted <= per_kind_rows[kind]


def _gate_allowed_customers(limit: int = 3) -> list[int]:
    """مشتریانِ فرصت‌دارِ **هنوز مجاز**.

    تست‌های دیگرِ همین اجرا روی دیتابیس مشترک کمپین می‌سازند، پس بخشی از
    مشتریان از قبل در گروه کنترل‌اند و دروازه مسدودشان کرده. اگر یکی از آن‌ها
    انتخاب شود، «منصرف کردنش» هیچ تغییری نمی‌دهد و تست به دلیل غلط می‌شکند.
    """
    with session_scope() as session:
        business_id = session.scalar(select(Business.id))
        gate = build_gate(session, business_id)
        candidates = session.scalars(
            select(Opportunity.customer_id).where(
                Opportunity.business_id == business_id,
                Opportunity.status == "open",
                Opportunity.customer_id.isnot(None),
            )
        ).all()
    allowed: list[int] = []
    for customer_id in sorted({int(c) for c in candidates}):
        if gate.reason_for(str(customer_id)) is None:
            allowed.append(customer_id)
        if len(allowed) == limit:
            break
    return allowed


def _cell_memberships(customer_ids: list[int]) -> int:
    """تعداد عضویت‌های سلولیِ این مشتریان — واحدِ واقعیِ کاهشِ ظرفیت."""
    if not customer_ids:
        return 0
    with session_scope() as session:
        business_id = session.scalar(select(Business.id))
        rows = session.execute(
            select(Opportunity.kind, Opportunity.customer_id).where(
                Opportunity.business_id == business_id,
                Opportunity.status == "open",
                Opportunity.customer_id.in_(customer_ids),
            )
        ).all()
    return len({(str(k), int(c)) for k, c in rows})


def test_supply_excludes_customers_the_gate_blocks(analyzed):
    """مشتریِ منصرف در ظرفیتِ آزمایش شمرده نمی‌شود."""
    before = sum(s.available for s in _supply())

    ids = _gate_allowed_customers(3)
    assert ids, "برای این تست به مشتریِ فرصت‌دارِ هنوز مجاز نیاز است"

    # کاهشِ انتظاری = تعداد **عضویت‌های سلولی** این مشتریان، نه تعداد خودشان:
    # مشتریِ حاضر در دو نوع اقدام، دو فرصتِ تماس را با خودش می‌برد.
    expected_drop = _cell_memberships(ids)
    assert expected_drop >= len(ids)

    for customer_id in ids:
        record_opt_out(customer_id=customer_id, reason_fa="آزمون ظرفیت")
    try:
        after = sum(s.available for s in _supply())
        assert after == before - expected_drop, (
            "ظرفیت باید دقیقاً به تعداد عضویت‌های سلولیِ مشتریانِ منصرف کم شود"
        )
    finally:
        for customer_id in ids:
            revoke_opt_out(customer_id=customer_id)

    assert sum(s.available for s in _supply()) == before


def test_supply_can_include_blocked_when_explicitly_asked(analyzed):
    """برای تشخیصِ خرابی، شمارشِ بدون دروازه هم باید ممکن باشد.

    اختلافِ دو شمارش باید دقیقاً برابر عضویت‌های سلولیِ **همه‌ی** مسدودشده‌ها
    باشد — نه فقط آن یکی که این تست منصرف می‌کند. تست‌های دیگرِ همین اجرا
    کمپین می‌سازند و اعضای گروه کنترلشان هم مسدودند.
    """
    target = _gate_allowed_customers(1)
    assert target, "برای این تست به مشتریِ هنوز مجاز نیاز است"
    customer_id = target[0]

    record_opt_out(customer_id=customer_id, reason_fa="آزمون")
    try:
        with session_scope() as session:
            business_id = session.scalar(select(Business.id))
            gate = build_gate(session, business_id)
            blocked_ids = sorted({
                int(c) for (c,) in session.execute(
                    select(Opportunity.customer_id).where(
                        Opportunity.business_id == business_id,
                        Opportunity.status == "open",
                        Opportunity.customer_id.isnot(None),
                    )
                ).all()
                if gate.reason_for(str(int(c))) is not None
            })
            gated = sum(s.available for s in collect_supply(session, business_id))
            ungated = sum(
                s.available
                for s in collect_supply(session, business_id, exclude_blocked=False)
            )
    finally:
        revoke_opt_out(customer_id=customer_id)

    assert customer_id in blocked_ids
    assert ungated == gated + _cell_memberships(blocked_ids)


# ═══════════════════════════════════════════════════════════ API
def test_experiment_plan_endpoint_returns_a_ranked_plan(analyzed):
    r = client.get("/api/v1/experiment-plan")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["available"] is True
    assert body["cells"]
    assert body["method_note_fa"] and body["holdout_note_fa"]

    # ترتیب باید نزولی بر پایه‌ی تماسِ اندازه‌گیری‌نشده باشد
    counts = [c["unmeasured_contacts"] for c in body["cells"]]
    assert counts == sorted(counts, reverse=True)


def test_plan_reports_missing_evidence_honestly(analyzed):
    """هر سلول باید وضعیتِ شواهدش را صادقانه بگوید.

    ادعای «همه‌ی سلول‌ها بدون آزمایش‌اند» فقط روی دیتابیسِ دست‌نخورده درست است؛
    تست‌های دیگرِ همین اجرا کمپین می‌سازند و نتیجه ثبت می‌کنند. پس اینجا
    **ناوردا** سنجیده می‌شود، نه یک وضعیتِ خاص.
    """
    body = client.get("/api/v1/experiment-plan").json()
    assert body["cells"]

    for cell in body["cells"]:
        if cell["status"] == "no_data":
            assert cell["n_treatment"] == 0 and cell["n_control"] == 0, (
                "«بدون آزمایش» با مشاهده‌ی ثبت‌شده تناقض دارد"
            )
            assert cell["measured_uplift"] is None
        # نرخ پایه‌ی فرضی باید صریحاً «فرضی» برچسب بخورد
        if cell["baseline_source"] == "assumed":
            assert "فرضی" in cell["baseline_source_fa"]
        else:
            assert "فرضی" not in cell["baseline_source_fa"]
        # سلولی که شواهدش قطعی نیست، تماسِ بی‌شاهدش برابر ظرفیتش است
        if not cell["settled"]:
            assert cell["unmeasured_contacts"] == cell["available"]
        else:
            assert cell["unmeasured_contacts"] == 0


def test_plan_respects_target_effect_and_holdout_params(analyzed):
    small = client.get(
        "/api/v1/experiment-plan?target_effect=0.10&holdout_pct=20"
    ).json()
    tight = client.get(
        "/api/v1/experiment-plan?target_effect=0.03&holdout_pct=20"
    ).json()

    assert small["target_effect"] == 0.10
    assert tight["target_effect"] == 0.03
    # اثرِ کوچک‌تر ⇒ نمونه‌ی بزرگ‌تر
    assert tight["cells"][0]["required_total"] > small["cells"][0]["required_total"]


def test_bigger_holdout_needs_a_smaller_campaign(analyzed):
    """یافته‌ی فاز ۴: کنترل ۲۰٪ کاراتر از ۱۰٪ است."""
    ten = client.get("/api/v1/experiment-plan?holdout_pct=10").json()
    twenty = client.get("/api/v1/experiment-plan?holdout_pct=20").json()
    assert twenty["cells"][0]["required_total"] < ten["cells"][0]["required_total"]


def test_plan_rejects_impossible_parameters(analyzed):
    assert client.get("/api/v1/experiment-plan?target_effect=0").status_code == 422
    assert client.get("/api/v1/experiment-plan?holdout_pct=90").status_code == 422


def test_every_cell_explains_itself_in_persian(analyzed):
    body = client.get("/api/v1/experiment-plan").json()
    for cell in body["cells"]:
        assert cell["note_fa"], "هر سلول باید توضیح فارسی داشته باشد"
        assert cell["status_label_fa"]


def test_next_experiment_is_runnable_when_present(analyzed):
    body = client.get("/api/v1/experiment-plan?target_effect=0.10").json()
    nxt = body["next_experiment"]
    if nxt is not None:
        assert nxt["feasible_now"] is True
        assert nxt["settled"] is False
        assert nxt["available"] >= nxt["required_total"]


def test_plan_never_recommends_contacting_an_opted_out_customer(analyzed):
    """ظرفیتِ گزارش‌شده باید با آنچه کمپین واقعاً می‌تواند بردارد هم‌خوان باشد."""
    with session_scope() as session:
        customer_id = session.scalar(select(Customer.id))
    record_opt_out(customer_id=int(customer_id), reason_fa="آزمون هم‌خوانی")
    try:
        body = client.get("/api/v1/experiment-plan").json()
        total_capacity = sum(c["available"] for c in body["cells"])
        with session_scope() as session:
            business_id = session.scalar(select(Business.id))
            supplies = collect_supply(session, business_id)
        assert total_capacity == sum(s.available for s in supplies)
    finally:
        revoke_opt_out(customer_id=int(customer_id))
