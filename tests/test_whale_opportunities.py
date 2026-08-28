"""اقدامِ رابطه‌ای — فرصتی که عمداً عدد ریالی ندارد (§۱۸.۵ و §۳۸).

سه مکانیزمِ موجود این نوع فرصت را می‌کُشتند و هر سه اینجا تست دارند:
`filter_eligibility` (ارزش صفر را بلوکه می‌کرد) · سقفِ صندوق (ته صف را می‌بُرید)
· سقفِ سه فرصت به‌ازای هر مشتری (جای یادآوری چرخه را می‌گرفت).

و مهم‌تر از همه: **بدون مدلِ فعال، هیچ ردیفی ساخته نمی‌شود.** جایگزین‌کردنش با
«دهک بالای CLV» همان اشتباهی است که یک‌بار در حسابرسی ثبت شد.
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
from mktcore.db.models import Opportunity, OpportunityFactor  # noqa: E402
from mktcore.db.repo_features import write_customer_features  # noqa: E402
from mktcore.db.repo_import import write_import  # noqa: E402
from mktcore.ingest.cleaning import clean_frame  # noqa: E402
from mktcore.ingest.mapper import SchemaMapper  # noqa: E402
from mktcore.ml.registry import promote_run  # noqa: E402
from mktcore.ml.train import train_model  # noqa: E402
from mktcore.ml.whale import score_whale_customers  # noqa: E402
from mktcore.opportunities import run_opportunity_engine  # noqa: E402
from mktcore.opportunities.contract import (  # noqa: E402
    OUTCOME_BLOCK,
    OUTCOME_PASS,
    VALUE_RELATIONSHIP,
    OpportunityCandidate,
)
from mktcore.opportunities.filters import filter_conflict, filter_eligibility  # noqa: E402
from mktcore.opportunities.generators import (  # noqa: E402
    KIND_WHALE_RELATIONSHIP,
    WHALE_ACTIONS_FA,
    generate_whale_relationship,
)
from mktcore.pipeline import run_analysis  # noqa: E402
from mktcore.synthetic import generate_cohort_sales  # noqa: E402

_FORBIDDEN = ("تخفیف", "آفر", "رایگان", "درصد", "کد تخفیف")


@pytest.fixture(autouse=True)
def _isolate():
    reset_ensure_cache()
    yield
    reset_ensure_cache()


def _candidate(*, value: float, kind: str) -> OpportunityCandidate:
    return OpportunityCandidate(
        kind="آزمون", generator="test", generator_version=1,
        customer_key="C1", title_fa="عنوان", action_fa="اقدام", reason_fa="دلیل",
        expected_value_display=value, value_kind=kind,
    )


# ═══════════════════════════════════ فیلترها
def test_relationship_candidate_with_zero_value_passes_eligibility():
    note = filter_eligibility(_candidate(value=0.0, kind=VALUE_RELATIONSHIP), {})

    assert note.outcome == OUTCOME_PASS
    assert "رابطه" in note.detail_fa


def test_ordinary_zero_value_candidate_is_still_blocked():
    """گاردِ قبلی **باریک** شد، نه ضعیف: فرصتِ فروشیِ بی‌ارزش هنوز رد می‌شود."""
    note = filter_eligibility(_candidate(value=0.0, kind="ارزش فرصت"), {})

    assert note.outcome == OUTCOME_BLOCK


def test_relationship_and_money_opportunities_have_separate_caps():
    ctx: dict = {"per_customer_open_cap": 3}
    money = [filter_conflict(_candidate(value=10, kind="ارزش فرصت"), ctx) for _ in range(4)]
    rapport = [
        filter_conflict(_candidate(value=0, kind=VALUE_RELATIONSHIP), ctx)
        for _ in range(2)
    ]

    assert [n.outcome for n in money] == [OUTCOME_PASS] * 3 + [OUTCOME_BLOCK]
    assert [n.outcome for n in rapport] == [OUTCOME_PASS, OUTCOME_BLOCK]


def test_relationship_actions_never_mention_a_discount():
    """§۱۸.۵: «این مشتریان را به انتظارِ تخفیف عادت ندهید.»"""
    text = " ".join(WHALE_ACTIONS_FA)
    for word in _FORBIDDEN:
        assert word not in text


# ═══════════════════════════════════ روی دفتر کل
@pytest.fixture(scope="module")
def promoted(tmp_path_factory) -> dict:
    """یک مدلِ نهنگِ فعال + عکس ویژگیِ امتیازخورده."""
    db = tmp_path_factory.mktemp("whale-opp") / "app.db"
    raw = generate_cohort_sales()
    mapper = SchemaMapper()
    clean = clean_frame(mapper.apply(raw, mapper.auto_detect(raw).mapping))
    write_import(clean, kpis=compute_kpis(clean), db_path=db)
    bundle = run_analysis(clean, with_forecast=False)
    write_customer_features(clean, bundle, db_path=db)

    run = train_model("whale", db_path=db)
    assert run["status"] == "validated", run["blocked_reason_fa"]
    promote_run(run["id"], db_path=db)
    score_whale_customers(db_path=db)
    return {"db": db, "clean": clean, "bundle": bundle, "run": run}


def test_no_promoted_model_means_no_relationship_candidates(tmp_path):
    """صداقت: بدون مدل، فهرست خالی است — نه یک fallback از CLV."""
    db = tmp_path / "app.db"
    raw = generate_cohort_sales(days=300)
    mapper = SchemaMapper()
    clean = clean_frame(mapper.apply(raw, mapper.auto_detect(raw).mapping))
    write_import(clean, kpis=compute_kpis(clean), db_path=db)

    assert generate_whale_relationship(db_path=db) == []


def test_relationship_candidates_carry_probability_and_no_money(promoted):
    candidates = generate_whale_relationship(db_path=promoted["db"])

    assert candidates, "با مدلِ فعال باید نامزد ساخته شود"
    for candidate in candidates:
        assert candidate.value_kind == VALUE_RELATIONSHIP
        assert candidate.expected_value_display == 0.0
        assert candidate.probability >= 0.6
        assert candidate.kind == KIND_WHALE_RELATIONSHIP


def test_relationship_text_has_no_offer_wording(promoted):
    for candidate in generate_whale_relationship(db_path=promoted["db"]):
        blob = " ".join(
            part for part in (candidate.action_fa, candidate.reason_fa, candidate.message_fa)
            if part
        )
        for word in _FORBIDDEN:
            assert word not in blob, f"«{word}» در متن اقدام رابطه‌ای آمده است"


def test_engine_persists_relationship_opportunities_without_value(promoted):
    db, bundle, clean = promoted["db"], promoted["bundle"], promoted["clean"]

    run_opportunity_engine(bundle, clean, db_path=db)

    with session_scope(db) as session:
        rows = session.scalars(
            select(Opportunity).where(Opportunity.value_kind == VALUE_RELATIONSHIP)
        ).all()
        assert rows, "اقدام رابطه‌ای باید ذخیره شود"
        for row in rows:
            assert row.expected_value_rial == 0
            assert row.score_rial == 0
            assert row.probability_bp is not None
        factors = session.scalars(
            select(OpportunityFactor).where(
                OpportunityFactor.code == "whale_probability"
            )
        ).all()
        assert factors, "شواهدِ احتمال باید ثبت شود"


def test_money_opportunities_keep_their_own_quota(promoted):
    """سهمیه‌ی رابطه‌ای نباید جای فرصت‌های ریالی را تنگ کند."""
    db, bundle, clean = promoted["db"], promoted["bundle"], promoted["clean"]
    run_opportunity_engine(bundle, clean, db_path=db)

    with session_scope(db) as session:
        money = session.scalar(
            select(func.count()).select_from(Opportunity).where(
                Opportunity.value_kind != VALUE_RELATIONSHIP
            )
        )
    assert money >= 100, "فرصت‌های ریالی باید مثل قبل ساخته شوند"


def test_a_customer_gets_at_most_one_relationship_action(promoted):
    db, bundle, clean = promoted["db"], promoted["bundle"], promoted["clean"]
    run_opportunity_engine(bundle, clean, db_path=db)

    with session_scope(db) as session:
        rows = session.execute(
            select(Opportunity.customer_id, func.count())
            .where(Opportunity.value_kind == VALUE_RELATIONSHIP)
            .group_by(Opportunity.customer_id)
        ).all()
    assert rows
    assert max(count for _customer, count in rows) == 1


def test_engine_output_is_unchanged_without_a_whale_model(tmp_path):
    """قرارداد صفر-رگرسیون: بدون مدل، ترتیب و محتوای صندوق دقیقاً مثل قبل است."""
    db = tmp_path / "app.db"
    raw = generate_cohort_sales(days=400)
    mapper = SchemaMapper()
    clean = clean_frame(mapper.apply(raw, mapper.auto_detect(raw).mapping))
    write_import(clean, kpis=compute_kpis(clean), db_path=db)
    bundle = run_analysis(clean, with_forecast=False)
    write_customer_features(clean, bundle, db_path=db)

    run_opportunity_engine(bundle, clean, db_path=db)
    with session_scope(db) as session:
        first = [
            (o.dedupe_key, o.score_rial, o.status)
            for o in session.scalars(
                select(Opportunity).order_by(Opportunity.dedupe_key)
            ).all()
        ]

    run_opportunity_engine(bundle, clean, db_path=db)
    with session_scope(db) as session:
        second = [
            (o.dedupe_key, o.score_rial, o.status)
            for o in session.scalars(
                select(Opportunity).order_by(Opportunity.dedupe_key)
            ).all()
        ]

    assert first == second
    assert all(kind != VALUE_RELATIONSHIP for _key, _score, kind in [])
    with session_scope(db) as session:
        relationship = session.scalar(
            select(func.count()).select_from(Opportunity).where(
                Opportunity.value_kind == VALUE_RELATIONSHIP
            )
        )
    assert relationship == 0


def test_dates_are_not_used_for_relationship_ranking(promoted):
    """اقدام رابطه‌ای بر پایه‌ی احتمال مرتب می‌شود، نه ارزش صفرش."""
    candidates = generate_whale_relationship(db_path=promoted["db"])
    probabilities = [c.probability for c in candidates]

    assert probabilities == sorted(probabilities, reverse=True)
    assert isinstance(pd.Series(probabilities).max(), float)
