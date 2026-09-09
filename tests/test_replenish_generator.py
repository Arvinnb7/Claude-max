"""مولدِ مدعیِ چرخه‌ی خریدِ شخصی (§۱۳.۲) — قهرمان/مدعی پشتِ اجرای فعال.

R0: `as_of` از موتور به مولدها می‌رسد (§۱۲ `generate(as_of)`) و مولدهای امروزی آن را
نادیده می‌گیرند ⇒ خروجی بیت‌به‌بیت همان است.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

from mktcore.analysis.kpis import compute_kpis  # noqa: E402
from mktcore.db.migrations import reset_ensure_cache  # noqa: E402
from mktcore.db.repo_import import write_import  # noqa: E402
from mktcore.ingest.cleaning import clean_frame  # noqa: E402
from mktcore.ingest.mapper import SchemaMapper  # noqa: E402
from mktcore.opportunities import run_opportunity_engine  # noqa: E402
from mktcore.opportunities.engine import _as_of  # noqa: E402
from mktcore.opportunities.generators import (  # noqa: E402
    generate_candidates,
    generate_from_action_list,
    generate_from_expansion_gap,
)
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


def _shape(candidates) -> list[tuple]:
    return sorted(
        (c.kind, c.generator, c.customer_key, c.product_name, c.expected_value_display,
         c.probability, c.due_date, c.value_kind)
        for c in candidates
    )


# ═══════════════════════════════════════════ R0: as_of بی‌اثر روی مولدهای امروزی
def test_as_of_threading_is_a_no_op(analyzed):
    clean, bundle = analyzed
    as_of = _as_of(clean)
    assert as_of == str(clean["date"].max().date())

    without = generate_candidates(bundle, clean)
    with_as_of = generate_candidates(bundle, clean, as_of=as_of)
    assert without, "فیکسچر باید نامزد بسازد"
    assert _shape(without) == _shape(with_as_of)
    assert _shape(generate_from_action_list(bundle, clean)) == _shape(
        generate_from_action_list(bundle, clean, as_of=as_of)
    )
    assert _shape(generate_from_expansion_gap(bundle, clean)) == _shape(
        generate_from_expansion_gap(bundle, clean, as_of=as_of)
    )


def test_engine_generated_count_equals_the_sum_of_generators_without_models(tmp_path, analyzed):
    """بدون مدلِ فعال، موتور دقیقاً همان نامزدهای دو مولدِ امروزی را می‌بیند."""
    clean, bundle = analyzed
    db = tmp_path / "app.db"
    write_import(clean, kpis=compute_kpis(clean), db_path=db)
    result = run_opportunity_engine(bundle, clean, db_path=db)
    assert result is not None
    expected = len(generate_from_action_list(bundle, clean)) + len(
        generate_from_expansion_gap(bundle, clean)
    )
    assert result.generated == expected


# ═══════════════════════════════════════════ R3: مدعی فقط پشتِ اجرای فعال
import json  # noqa: E402

import pandas as pd  # noqa: E402
from sqlalchemy import select  # noqa: E402

from mktcore.analysis.actions import KIND_CYCLE  # noqa: E402
from mktcore.db import session_scope  # noqa: E402
from mktcore.db.models import Opportunity, OpportunityFactor, OpportunityRun  # noqa: E402
from mktcore.ml.registry import promote_run  # noqa: E402
from mktcore.ml.train import train_model  # noqa: E402
from mktcore.opportunities.contract import OpportunityCandidate  # noqa: E402
from mktcore.opportunities.generators import (  # noqa: E402
    ACTION_GENERATOR,
    REPLENISH_GENERATOR,
    generate_replenishment_personal,
    replace_champion_cycle,
)
from mktcore.synthetic import generate_replenishment_sales  # noqa: E402

EVIDENCE_CODES = {
    "evidence_level", "expected_interval", "interval_uncertainty", "overdue_ratio",
    "pack_adjustment", "probability", "champion_replaced", "value_basis",
}


@pytest.fixture(scope="module")
def replenish_world(tmp_path_factory):
    """دفتر کل با آهنگِ شخصی + تحلیل + اجرای آموزش‌دیده‌ی replenish (هنوز فعال نشده)."""
    db = tmp_path_factory.mktemp("replenish-gen") / "app.db"
    raw = generate_replenishment_sales()
    mapper = SchemaMapper()
    clean = clean_frame(mapper.apply(raw, mapper.auto_detect(raw).mapping))
    write_import(clean, kpis=compute_kpis(clean), db_path=db)
    bundle = run_analysis(clean, horizon=2, with_forecast=False)
    run = train_model("replenish", db_path=db)
    assert run["status"] == "validated", run["blocked_reason_fa"]
    return {"db": db, "clean": clean, "bundle": bundle, "run": run}


def _inbox(db: Path) -> list[tuple]:
    with session_scope(db) as session:
        rows = session.scalars(
            select(Opportunity).order_by(Opportunity.score_rial.desc(), Opportunity.dedupe_key)
        ).all()
        return [(o.dedupe_key, o.score_rial, o.status, o.generator) for o in rows]


def _actions_snapshot(bundle) -> list[tuple]:
    return [(a.kind, str(a.customer_id), a.product, a.value_rial) for a in bundle.actions.actions]


def test_no_promoted_model_means_no_personal_candidates_and_identical_engine_output(replenish_world):
    db, clean, bundle = replenish_world["db"], replenish_world["clean"], replenish_world["bundle"]
    assert generate_replenishment_personal(bundle, clean, as_of=_as_of(clean), db_path=db) == []
    first = run_opportunity_engine(bundle, clean, db_path=db)
    inbox_1 = _inbox(db)
    second = run_opportunity_engine(bundle, clean, db_path=db)
    inbox_2 = _inbox(db)
    assert first.created > 0 and second.created == 0
    assert inbox_1 == inbox_2
    assert not [row for row in inbox_1 if row[3] == REPLENISH_GENERATOR]
    with session_scope(db) as session:
        notes = json.loads(session.get(OpportunityRun, second.run_id).notes_json)
    assert notes["replenish_challenger"] is None, "بدون مدلِ فعال، مدعی حتی صدا هم زده نمی‌شود"


def test_replace_champion_cycle_only_touches_covered_pairs():
    def make(kind, generator, customer, product):
        return OpportunityCandidate(
            kind=kind, generator=generator, generator_version=1, customer_key=customer,
            title_fa="t", action_fa="a", reason_fa="r", expected_value_display=1.0,
            value_kind="ارزش فرصت", product_name=product,
        )
    champion = [
        make(KIND_CYCLE, ACTION_GENERATOR, "C1", "P1"),   # پوشش‌داده‌شده ⇒ حذف
        make(KIND_CYCLE, ACTION_GENERATOR, "C2", "P1"),   # بی‌پوشش ⇒ می‌ماند
        make("تکمیل الگوی خرید", ACTION_GENERATOR, "C1", "P1"),  # نوعِ دیگر ⇒ می‌ماند
    ]
    challenger = [make(KIND_CYCLE, REPLENISH_GENERATOR, "C1", "P1")]
    merged, replaced = replace_champion_cycle(champion, challenger)
    assert replaced == 1
    assert [(c.generator, c.customer_key, c.kind) for c in merged] == [
        (ACTION_GENERATOR, "C2", KIND_CYCLE), (ACTION_GENERATOR, "C1", "تکمیل الگوی خرید"),
        (REPLENISH_GENERATOR, "C1", KIND_CYCLE),
    ]
    assert replace_champion_cycle(champion, []) == (champion, 0)


def test_promoted_model_emits_personal_reminders_with_evidence_and_replaces_the_champion(replenish_world):
    db, clean, bundle, run = (replenish_world[k] for k in ("db", "clean", "bundle", "run"))
    before = _actions_snapshot(bundle)
    promote_run(run["id"], db_path=db, actor="آزمون")

    as_of = _as_of(clean)
    challenger = generate_replenishment_personal(bundle, clean, as_of=as_of, db_path=db)
    assert challenger, "با مدلِ فعال، جفت‌های سررسیدشده یادآورِ شخصی می‌گیرند"
    covered = {(c.customer_key, c.product_name) for c in challenger}
    for candidate in challenger:
        codes = {f.code for f in candidate.factors}
        assert EVIDENCE_CODES <= codes
        by_code = {f.code: f for f in candidate.factors}
        assert "درآمد" in by_code["value_basis"].value_text
        assert by_code["champion_replaced"].value_text == "بله"
        assert candidate.kind == KIND_CYCLE and candidate.generator == REPLENISH_GENERATOR
        assert 0 < candidate.probability <= 1 and candidate.expected_value_display > 0
        assert candidate.due_date and candidate.expires_at > as_of

    result = run_opportunity_engine(bundle, clean, db_path=db)
    with session_scope(db) as session:
        notes = json.loads(session.get(OpportunityRun, result.run_id).notes_json)
        live = session.scalars(select(Opportunity).where(Opportunity.status == "open")).all()
        personal = [o for o in live if o.generator == REPLENISH_GENERATOR]
        assert personal, "یادآورهای شخصی در صندوق نشسته‌اند"
        factor_codes = {
            f.code for f in session.scalars(select(OpportunityFactor).where(
                OpportunityFactor.opportunity_id == personal[0].id)).all()
        }
        assert EVIDENCE_CODES <= factor_codes
        # جفتِ پوشش‌داده‌شده دیگر یادآورِ قهرمان (action_list × KIND_CYCLE) ندارد
        from mktcore.db.models import Customer, Product

        customer_key = {c.id: c.canonical_key for c in session.scalars(select(Customer)).all()}
        product_name = {p.id: p.display_name for p in session.scalars(select(Product)).all()}
        champion_cycle = [
            o for o in live if o.generator == ACTION_GENERATOR and o.kind == KIND_CYCLE
        ]
        overlap = [
            o for o in champion_cycle
            if (customer_key.get(o.customer_id), product_name.get(o.product_id)) in covered
        ]
    assert notes["replenish_challenger"]["emitted"] == len(challenger)
    assert notes["replenish_challenger"]["replaced"] >= 1
    assert overlap == [], "یادآورِ قهرمان برای جفتِ پوشش‌داده‌شده باز نمی‌ماند"
    assert _actions_snapshot(bundle) == before, "فهرستِ اقدامِ داشبورد (قهرمان) دست نمی‌خورد"


def test_hand_fixture_card_numbers_follow_the_spec_example(replenish_world):
    """مشتریِ ۴۳/۴۷/۴۵ (§۱۳.۶) روی مدلِ فعالِ همین دفتر: کارت اعدادِ خودش را می‌گوید."""
    db = replenish_world["db"]
    rows = [(d, 3_200_000, "الف", f"F{i}", "غذای خشک ۱۲.۵ کیلویی", "09121110000")
            for i, d in enumerate(("2024-01-01", "2024-02-13", "2024-03-31", "2024-05-15"))]
    raw = pd.DataFrame(rows, columns=["تاریخ", "مبلغ", "مشتری", "فاکتور", "کالا", "موبایل"])
    from mktcore.ingest.schema import ColumnRole

    mapping = {ColumnRole.DATE: "تاریخ", ColumnRole.REVENUE: "مبلغ", ColumnRole.CUSTOMER_ID: "مشتری",
               ColumnRole.ORDER_ID: "فاکتور", ColumnRole.PRODUCT: "کالا", ColumnRole.PHONE: "موبایل"}
    clean = clean_frame(SchemaMapper().apply(raw, mapping))
    cards = generate_replenishment_personal(None, clean, as_of="2024-06-28", db_path=db)
    assert len(cards) == 1
    card = cards[0]
    by_code = {f.code: f for f in card.factors}
    assert by_code["expected_interval"].value_text == "45 روز"
    assert by_code["overdue_ratio"].value_text == "0.98"
    assert "43، 47، 45" in card.reason_fa and "44 روز" in card.reason_fa
    assert "45 روزه" in card.message_fa
    assert card.due_date == "2024-06-29" and card.phone == "09121110000", "شماره همان‌طور که فهرستِ اقدام می‌دهد (خام)"
    assert card.expected_value_display == pytest.approx(3_200_000 * card.probability)
