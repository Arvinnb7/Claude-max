"""موتور فرصت‌ها: تولید، فیلتر با شواهد صریح، و چرخه‌ی حیات.

مهم‌ترین ادعاها:
* `analysis/actions.py` دست‌نخورده می‌ماند و `bundle.actions` تغییر نمی‌کند.
* فیلترهایی که داده ندارند «قبول» ثبت نمی‌شوند، «اجرا نشد» ثبت می‌شوند.
* تصمیم انسان با اجرای دوباره‌ی موتور پاک نمی‌شود.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import func, select

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

from mktcore.analysis.kpis import compute_kpis  # noqa: E402
from mktcore.db import session_scope  # noqa: E402
from mktcore.db.migrations import reset_ensure_cache  # noqa: E402
from mktcore.db.models import (  # noqa: E402
    Opportunity,
    OpportunityEvent,
    OpportunityFactor,
    OpportunityOffer,
    OpportunityRun,
)
from mktcore.db.repo_import import write_import  # noqa: E402
from mktcore.ingest.cleaning import clean_frame  # noqa: E402
from mktcore.ingest.mapper import SchemaMapper  # noqa: E402
from mktcore.opportunities import run_opportunity_engine  # noqa: E402
from mktcore.opportunities.contract import (  # noqa: E402
    OUTCOME_PASS,
    OUTCOME_SKIP,
    OpportunityCandidate,
)
from mktcore.opportunities.engine import (  # noqa: E402
    STATUS_ACCEPTED,
    STATUS_OPEN,
    STATUS_SUPERSEDED,
)
from mktcore.opportunities.filters import apply_filters  # noqa: E402
from mktcore.pipeline import run_analysis  # noqa: E402
from mktcore.synthetic import generate_synthetic_sales  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_schema_cache():
    reset_ensure_cache()
    yield
    reset_ensure_cache()


@pytest.fixture(scope="module")
def analyzed():
    raw = generate_synthetic_sales(seed=3, days=420)
    mapper = SchemaMapper()
    clean = clean_frame(mapper.apply(raw, mapper.auto_detect(raw).mapping))
    bundle = run_analysis(clean, horizon=3, with_forecast=False)
    return clean, bundle


def _prepare(tmp_path: Path, analyzed) -> Path:
    clean, bundle = analyzed
    db = tmp_path / "app.db"
    write_import(clean, kpis=compute_kpis(clean), db_path=db)
    return db


# ------------------------------------------------------------------ فیلترها
def _candidate(**kwargs) -> OpportunityCandidate:
    base = {
        "kind": "یادآوری چرخه‌ی مصرف",
        "generator": "test",
        "generator_version": 1,
        "customer_key": "C1",
        "title_fa": "عنوان",
        "action_fa": "اقدام",
        "reason_fa": "دلیل",
        "expected_value_display": 100_000.0,
        "value_kind": "ارزش فرصت",
    }
    base.update(kwargs)
    return OpportunityCandidate(**base)


def test_missing_data_filters_are_skipped_not_passed():
    """قاعده‌ی سخت: بدون داده، «بررسی شد» ثبت نمی‌شود."""
    accepted, rejected = apply_filters([_candidate()], {
        "has_cost_data": False, "has_inventory_data": False, "has_consent_data": False,
        "compatibility_rules": None, "recently_contacted": set(),
        "fatigue_window_days": 14, "per_customer_open_cap": 3,
    })
    assert len(accepted) == 1 and not rejected
    outcomes = {f.code: f.outcome for f in accepted[0].factors}
    assert outcomes["inventory"] == OUTCOME_SKIP
    assert outcomes["margin_floor"] == OUTCOME_SKIP
    assert outcomes["consent"] == OUTCOME_SKIP
    assert outcomes["compatibility"] == OUTCOME_SKIP
    assert outcomes["offer_policy"] == OUTCOME_SKIP
    # آن‌هایی که داده دارند واقعاً بررسی می‌شوند
    assert outcomes["eligibility"] == OUTCOME_PASS
    assert outcomes["fatigue"] == OUTCOME_PASS


def test_skip_notes_explain_why_in_persian():
    accepted, _ = apply_filters([_candidate()], {"recently_contacted": set()})
    detail = {f.code: (f.detail_fa or "") for f in accepted[0].factors}
    assert "موجودی بررسی نشد" in detail["inventory"]
    assert "بهای تمام‌شده" in detail["margin_floor"]
    assert "تخفیفی پیشنهاد نشده" in detail["offer_policy"]


def test_cost_data_alone_does_not_make_margin_check_pass():
    """داشتن ستون بها ≠ بررسی حاشیه.

    تا وقتی معنای ستون بها و کف قابل‌قبول از کاربر پرسیده نشده، «قبول» ثبت‌کردن
    یعنی ادعای بررسی‌ای که انجام نشده.
    """
    accepted, _ = apply_filters([_candidate()], {
        "has_cost_data": True, "margin_floor_bp": None, "recently_contacted": set(),
    })
    note = next(f for f in accepted[0].factors if f.code == "margin_floor")
    assert note.outcome == OUTCOME_SKIP
    assert "کف حاشیه" in (note.detail_fa or "")


def test_margin_floor_blocks_when_fully_configured():
    """وقتی هم بها هست و هم کف تعیین شده، فیلتر واقعاً کار می‌کند."""
    low = _candidate(product_name="P-کم‌حاشیه")
    high = _candidate(product_name="P-پرحاشیه")
    ctx = {
        "has_cost_data": True,
        "margin_floor_bp": 2000,  # ۲۰٪
        "margin_by_product": {"P-کم‌حاشیه": 500, "P-پرحاشیه": 3500},
        "recently_contacted": set(),
    }
    accepted, rejected = apply_filters([low, high], ctx)
    assert [c.product_name for c in accepted] == ["P-پرحاشیه"]
    assert rejected[0].blocked_by.code == "margin_floor"


def test_zero_value_candidate_is_blocked():
    accepted, rejected = apply_filters(
        [_candidate(expected_value_display=0.0)], {"recently_contacted": set()},
    )
    assert not accepted and len(rejected) == 1
    assert rejected[0].blocked_by.code == "eligibility"


def test_recently_contacted_customer_is_blocked():
    accepted, rejected = apply_filters([_candidate()], {
        "recently_contacted": {"C1"}, "fatigue_window_days": 14,
    })
    assert not accepted
    assert rejected[0].blocked_by.code == "fatigue"


def test_per_customer_cap_keeps_the_most_valuable():
    """وقتی سقف تداخل می‌خورد، باید ارزشمندترها بمانند نه تصادفی‌ها."""
    candidates = [
        _candidate(product_name=f"P{i}", expected_value_display=float(i) * 1000)
        for i in range(1, 6)
    ]
    accepted, rejected = apply_filters(candidates, {
        "recently_contacted": set(), "per_customer_open_cap": 2,
    })
    assert len(accepted) == 2
    assert {c.product_name for c in accepted} == {"P5", "P4"}
    assert all(r.blocked_by.code == "conflict" for r in rejected)


# ------------------------------------------------------------------- موتور
def test_engine_creates_opportunities_with_evidence(tmp_path, analyzed):
    clean, bundle = analyzed
    db = _prepare(tmp_path, analyzed)

    result = run_opportunity_engine(bundle, clean, session_id="s1", db_path=db)
    assert result is not None
    assert result.generated > 0
    assert result.created > 0
    assert result.refreshed == 0

    with session_scope(db) as session:
        opportunities = session.scalars(select(Opportunity)).all()
        assert len(opportunities) == result.created
        assert all(o.status == STATUS_OPEN for o in opportunities)
        # هر فرصت شواهد دارد — قاعده‌ی غیرقابل‌مذاکره
        for opportunity in opportunities:
            factors = session.scalars(
                select(OpportunityFactor)
                .where(OpportunityFactor.opportunity_id == opportunity.id)
            ).all()
            assert factors, opportunity.id
            assert any(f.outcome == "evidence" for f in factors)
            assert any(f.code == "inventory" and f.outcome == OUTCOME_SKIP for f in factors)


def test_engine_never_reprices_probability(tmp_path, analyzed):
    """ارزش از قبل در احتمال ضرب شده؛ دوباره ضرب‌شدن یعنی کم‌برآوردِ سیستماتیک."""
    from mktcore.money import to_rial_int

    clean, bundle = analyzed
    db = _prepare(tmp_path, analyzed)
    run_opportunity_engine(bundle, clean, db_path=db)

    from mktcore.analysis.actions import build_action_list
    wide = build_action_list(bundle, clean, per_customer_cap=3, limit=5000)
    by_key = {(a.customer_id, a.kind, a.product): a for a in wide.actions}

    with session_scope(db) as session:
        opportunity = session.scalars(
            select(Opportunity).order_by(Opportunity.score_rial.desc())
        ).first()
        matches = [
            a for (cust, kind, _prod), a in by_key.items()
            if kind == opportunity.kind
        ]
    assert matches
    expected = max(to_rial_int(a.value_rial, "تومان") for a in matches)
    assert opportunity.expected_value_rial == expected


def test_rerun_refreshes_instead_of_duplicating(tmp_path, analyzed):
    clean, bundle = analyzed
    db = _prepare(tmp_path, analyzed)

    first = run_opportunity_engine(bundle, clean, db_path=db)
    with session_scope(db) as session:
        count_1 = session.scalar(select(func.count()).select_from(Opportunity))

    second = run_opportunity_engine(bundle, clean, db_path=db)
    with session_scope(db) as session:
        count_2 = session.scalar(select(func.count()).select_from(Opportunity))
        runs = session.scalar(select(func.count()).select_from(OpportunityRun))

    assert count_2 == count_1 == first.created
    assert second.created == 0
    assert second.refreshed == first.created
    assert runs == 2


def test_human_decision_survives_a_rerun(tmp_path, analyzed):
    """اگر تصمیم کاربر با هر تحلیل پاک شود، صندوق غیرقابل‌استفاده می‌شود."""
    clean, bundle = analyzed
    db = _prepare(tmp_path, analyzed)
    run_opportunity_engine(bundle, clean, db_path=db)

    with session_scope(db) as session:
        opportunity = session.scalars(select(Opportunity)).first()
        opportunity.status = STATUS_ACCEPTED
        opportunity.assigned_to = "زهرا"
        target_id = opportunity.id

    run_opportunity_engine(bundle, clean, db_path=db)

    with session_scope(db) as session:
        after = session.get(Opportunity, target_id)
        assert after.status == STATUS_ACCEPTED
        assert after.assigned_to == "زهرا"
        assert after.seen_count == 2  # تازه‌سازی شده، ولی وضعیت دست‌نخورده


def test_vanished_opportunity_is_superseded_not_deleted(tmp_path, analyzed):
    clean, bundle = analyzed
    db = _prepare(tmp_path, analyzed)
    run_opportunity_engine(bundle, clean, db_path=db)

    with session_scope(db) as session:
        before = session.scalar(select(func.count()).select_from(Opportunity))

    # تحلیلی روی زیرمجموعه‌ی کوچک → بیشتر فرصت‌های قبلی دیگر مصداق ندارند
    small = clean[clean["customer_id"].isin(clean["customer_id"].unique()[:3])].copy()
    small.attrs = dict(clean.attrs)
    small_bundle = run_analysis(small, horizon=2, with_forecast=False)
    result = run_opportunity_engine(small_bundle, small, db_path=db)

    with session_scope(db) as session:
        after = session.scalar(select(func.count()).select_from(Opportunity))
        superseded = session.scalar(
            select(func.count()).select_from(Opportunity)
            .where(Opportunity.status == STATUS_SUPERSEDED)
        )
    assert after >= before        # هیچ ردیفی حذف نشده است
    assert superseded == result.superseded > 0


def test_reappearing_opportunity_is_reopened(tmp_path, analyzed):
    clean, bundle = analyzed
    db = _prepare(tmp_path, analyzed)
    run_opportunity_engine(bundle, clean, db_path=db)

    small = clean[clean["customer_id"].isin(clean["customer_id"].unique()[:3])].copy()
    small.attrs = dict(clean.attrs)
    run_opportunity_engine(run_analysis(small, horizon=2, with_forecast=False), small,
                           db_path=db)
    run_opportunity_engine(bundle, clean, db_path=db)  # داده‌ی کامل دوباره

    with session_scope(db) as session:
        still_superseded = session.scalar(
            select(func.count()).select_from(Opportunity)
            .where(Opportunity.status == STATUS_SUPERSEDED)
        )
        reopened = session.scalars(
            select(OpportunityEvent).where(OpportunityEvent.event_type == "reopened")
        ).all()
    assert reopened
    assert still_superseded == 0


def test_expired_opportunities_are_marked(tmp_path, analyzed):
    clean, bundle = analyzed
    db = _prepare(tmp_path, analyzed)
    run_opportunity_engine(bundle, clean, db_path=db)

    with session_scope(db) as session:
        for opportunity in session.scalars(select(Opportunity)).all():
            opportunity.expires_at = "2000-01-01"

    result = run_opportunity_engine(bundle, clean, db_path=db)
    assert result.expired == 0  # تازه‌سازی، تاریخ انقضا را دوباره تنظیم می‌کند

    with session_scope(db) as session:
        expired_now = session.scalar(
            select(func.count()).select_from(Opportunity)
            .where(Opportunity.expires_at == "2000-01-01")
        )
    assert expired_now == 0


def test_every_status_change_is_recorded(tmp_path, analyzed):
    clean, bundle = analyzed
    db = _prepare(tmp_path, analyzed)
    result = run_opportunity_engine(bundle, clean, db_path=db)

    with session_scope(db) as session:
        created_events = session.scalar(
            select(func.count()).select_from(OpportunityEvent)
            .where(OpportunityEvent.event_type == "created")
        )
    assert created_events == result.created


def test_bundle_actions_are_not_mutated_by_the_engine(tmp_path, analyzed):
    """`analysis/actions.py` و خروجی داشبورد باید دقیقاً همان بمانند."""
    clean, bundle = analyzed
    db = _prepare(tmp_path, analyzed)

    before = [(a.rank, a.customer_id, a.kind, a.value_rial) for a in bundle.actions.actions]
    before_total = bundle.actions.total_value
    run_opportunity_engine(bundle, clean, db_path=db)
    after = [(a.rank, a.customer_id, a.kind, a.value_rial) for a in bundle.actions.actions]

    assert after == before
    assert bundle.actions.total_value == before_total


def test_engine_returns_none_without_a_business(tmp_path, analyzed):
    """بدون دفتر کل (هیچ بارگذاری‌ای ثبت نشده) موتور بی‌صدا کنار می‌رود."""
    clean, bundle = analyzed
    result = run_opportunity_engine(bundle, clean, db_path=tmp_path / "empty.db")
    assert result is None


def test_without_a_ladder_no_offer_or_discount_is_ever_generated(tmp_path, analyzed):
    """بدون نردبانِ تنظیم‌شده، سیستم تخفیف پیشنهاد نمی‌کند — رفتارِ پیش از §۲۰.۳.

    این تست عمداً **باریک** شد نه حذف: قبلاً می‌گفت «هرگز»، حالا می‌گوید «تا
    وقتی کاربر نردبانی نگفته، هرگز». نسخه‌ی با نردبان و قاعده‌ی «بدون تأییدِ
    انسان ارسال نمی‌شود» در `test_offer_send_gate.py` و `test_offer_approval.py`
    است.
    """
    clean, bundle = analyzed
    db = _prepare(tmp_path, analyzed)
    run_opportunity_engine(bundle, clean, db_path=db)

    with session_scope(db) as session:
        policies = session.scalars(
            select(OpportunityFactor).where(OpportunityFactor.code == "offer_policy")
        ).all()
        offers = session.scalar(select(func.count()).select_from(OpportunityOffer))
    assert policies
    assert all(p.outcome == OUTCOME_SKIP for p in policies)
    assert offers == 0, "بدون نردبان هیچ ردیفِ آفری نباید ساخته شود"


def test_causal_fields_stay_null(tmp_path, analyzed):
    """پرکردن اثر علّی بدون گروه کنترل، ادعای اثبات‌نشده است."""
    clean, bundle = analyzed
    db = _prepare(tmp_path, analyzed)
    run_opportunity_engine(bundle, clean, db_path=db)

    with session_scope(db) as session:
        non_null = session.scalar(
            select(func.count()).select_from(Opportunity).where(
                (Opportunity.attributed_revenue_rial.isnot(None))
                | (Opportunity.incremental_revenue_rial.isnot(None))
                | (Opportunity.experiment_id.isnot(None))
            )
        )
    assert non_null == 0


def test_blocked_candidates_are_not_persisted(tmp_path, analyzed):
    clean, bundle = analyzed
    db = _prepare(tmp_path, analyzed)
    result = run_opportunity_engine(bundle, clean, db_path=db)

    with session_scope(db) as session:
        stored = session.scalar(select(func.count()).select_from(Opportunity))
    assert stored == result.created
    # حسابرسی نامزدها: هیچ نامزدی بی‌حساب ناپدید نمی‌شود
    assert result.generated == result.created + result.filtered_out + result.capped_out


def test_cap_is_reported_not_silent(tmp_path, analyzed):
    """اگر سقف چیزی را کنار بگذارد، باید در خروجی دیده شود، نه بی‌صدا."""
    from mktcore.opportunities.engine import MAX_PERSISTED_PER_RUN

    clean, bundle = analyzed
    db = _prepare(tmp_path, analyzed)
    result = run_opportunity_engine(bundle, clean, db_path=db)

    assert result.created <= MAX_PERSISTED_PER_RUN
    if result.capped_out:
        assert "ذخیره نشد" in result.to_dict()["cap_note_fa"]
    else:
        assert "cap_note_fa" not in result.to_dict()


def test_capped_candidates_do_not_churn_between_runs(tmp_path, analyzed, monkeypatch):
    """فرصتی که فقط به‌خاطر سقف کنار مانده «بی‌مصداق» نیست.

    بدون این، هر اجرا صدها فرصت را بی‌مصداق و دوباره باز می‌کرد و تاریخچه را
    از رخدادهای بی‌معنا پر می‌کرد.
    """
    import mktcore.opportunities.engine as engine_mod

    clean, bundle = analyzed
    db = _prepare(tmp_path, analyzed)
    # سقف را آن‌قدر پایین می‌آوریم که قطعاً نامزدی بیرون بماند — تست نباید به
    # حجمِ داده‌ی نمونه وابسته باشد.
    monkeypatch.setattr(engine_mod, "MAX_PERSISTED_PER_RUN", 5)
    first = run_opportunity_engine(bundle, clean, db_path=db)
    assert first.capped_out > 0, "با سقفِ ۵ باید نامزدی بیرون بماند"

    second = run_opportunity_engine(bundle, clean, db_path=db)
    assert second.superseded == 0
    assert second.created == 0
    assert second.refreshed == first.created


def test_duplicate_dedupe_keys_in_one_run_do_not_crash(tmp_path, analyzed):
    """دو نامزد با کلید یکسان: اولی برنده، اجرا سالم می‌ماند."""
    from mktcore.opportunities import engine as engine_mod

    clean, bundle = analyzed
    db = _prepare(tmp_path, analyzed)
    key = clean["customer_id"].iloc[0]
    twins = [
        _candidate(customer_key=str(key), product_name="کالا", expected_value_display=v)
        for v in (50_000.0, 40_000.0)
    ]
    assert twins[0].dedupe_key() == twins[1].dedupe_key()

    original = engine_mod.generate_candidates
    engine_mod.generate_candidates = lambda *_a, **_k: twins
    try:
        result = run_opportunity_engine(bundle, clean, db_path=db)
    finally:
        engine_mod.generate_candidates = original

    assert result is not None
    assert result.created == 1
    with session_scope(db) as session:
        stored = session.scalars(select(Opportunity)).all()
    assert len(stored) == 1
    assert stored[0].expected_value_rial == 500_000  # ۵۰٬۰۰۰ تومان → ریال


def test_expansion_gap_generator_produces_evidence_backed_candidates():
    """مولد شکاف باید نامزد بسازد و هر نامزد شواهد همتایان داشته باشد."""
    from mktcore.opportunities.generators import (
        KIND_EXPANSION,
        generate_from_expansion_gap,
    )

    rows = [
        (f"C{i}", cat, 100_000)
        for i in range(20)
        for cat in ("لبنیات", "نوشیدنی")
    ]
    rows.append(("CX", "لبنیات", 100_000))  # نوشیدنی نمی‌خرد
    frame = pd.DataFrame(rows, columns=["customer_id", "category", "revenue"])

    class _Bundle:
        segments = None

    candidates = generate_from_expansion_gap(_Bundle(), frame)
    assert candidates
    target = [c for c in candidates if c.customer_key == "CX"]
    assert target
    candidate = target[0]
    assert candidate.kind == KIND_EXPANSION
    assert candidate.product_name == "نوشیدنی"
    codes = {f.code for f in candidate.factors}
    assert {"peer_comparison", "peer_adoption", "value_basis"} <= codes


def test_expansion_gap_value_is_discounted_below_peer_median():
    """ارزش شکاف پتانسیل است؛ نباید هم‌وزن فرصت‌های رفتاری رتبه بگیرد."""
    from mktcore.opportunities.generators import generate_from_expansion_gap

    rows = [
        (f"C{i}", cat, 100_000)
        for i in range(40)
        for cat in ("الف", "ب")
    ]
    rows.append(("CX", "الف", 100_000))
    frame = pd.DataFrame(rows, columns=["customer_id", "category", "revenue"])

    class _Bundle:
        segments = None

    candidate = next(
        c for c in generate_from_expansion_gap(_Bundle(), frame) if c.customer_key == "CX"
    )
    assert 0 < candidate.expected_value_display < 100_000


def test_expansion_generator_returns_empty_when_peers_are_too_few():
    from mktcore.opportunities.generators import generate_from_expansion_gap

    frame = pd.DataFrame(
        [("C1", "الف", 100), ("C2", "ب", 100)],
        columns=["customer_id", "category", "revenue"],
    )

    class _Bundle:
        segments = None

    assert generate_from_expansion_gap(_Bundle(), frame) == []


def test_empty_frame_is_handled(tmp_path):
    """فریم بدون داده نباید استثنا بدهد."""
    empty = pd.DataFrame({"date": pd.to_datetime([]), "revenue": [], "customer_id": []})

    class _Bundle:
        actions = None
        kpis = None

    assert run_opportunity_engine(_Bundle(), empty, db_path=tmp_path / "x.db") is None
