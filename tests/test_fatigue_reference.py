"""بازتولیدپذیریِ دروازه‌ی فاز ۲: مرجعِ زمانیِ خستگیِ تماس صریح، ثبت‌شده و بازپخش‌پذیر.

پیش از این، پنجره‌ی ۱۴ روزه‌ی خستگی از ساعتِ دیوارِ لحظه‌ی اجرا حساب می‌شد و هیچ‌جا
ثبت نمی‌شد؛ یعنی «همان اجرا با همان ورودی‌ها» فردا نتیجه‌ی دیگری می‌داد بی‌آنکه
معلوم باشد چرا. حالا `fatigue_now` ورودیِ موتور است (پیش‌فرض همان ساعتِ دیوار) و
مقدارِ به‌کاررفته در `OpportunityRun.notes_json["fatigue_reference_ts"]` می‌نشیند.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest
from sqlalchemy import select

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

from api.persistence import store  # noqa: E402

from mktcore.analysis.kpis import compute_kpis  # noqa: E402
from mktcore.db import session_scope  # noqa: E402
from mktcore.db.migrations import reset_ensure_cache  # noqa: E402
from mktcore.db.models import Opportunity, OpportunityFactor, OpportunityRun  # noqa: E402
from mktcore.db.repo_import import write_import  # noqa: E402
from mktcore.ingest.cleaning import clean_frame  # noqa: E402
from mktcore.ingest.mapper import SchemaMapper  # noqa: E402
from mktcore.opportunities import run_opportunity_engine  # noqa: E402
from mktcore.opportunities.contract import OUTCOME_PASS  # noqa: E402
from mktcore.pipeline import run_analysis  # noqa: E402
from mktcore.synthetic import generate_synthetic_sales  # noqa: E402

from .conftest import reset_contact_history  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate():
    reset_ensure_cache()
    reset_contact_history()
    yield
    reset_contact_history()
    reset_ensure_cache()


@pytest.fixture(scope="module")
def analyzed():
    raw = generate_synthetic_sales(seed=3, days=420)
    mapper = SchemaMapper()
    clean = clean_frame(mapper.apply(raw, mapper.auto_detect(raw).mapping))
    bundle = run_analysis(clean, horizon=3, with_forecast=False)
    return clean, bundle


def _prepare(tmp_path: Path, analyzed) -> Path:
    clean, _ = analyzed
    db = tmp_path / "app.db"
    write_import(clean, kpis=compute_kpis(clean), db_path=db)
    return db


def _ranking(db: Path) -> list[tuple[str, int, int]]:
    """رتبه و ارزشِ صندوق — همان چیزی که کاربر می‌بیند."""
    with session_scope(db) as session:
        rows = session.scalars(
            select(Opportunity).order_by(Opportunity.score_rial.desc(), Opportunity.dedupe_key)
        ).all()
        return [(o.dedupe_key, o.expected_value_rial, o.score_rial) for o in rows]


def _run_notes(db: Path, run_id: int) -> dict:
    with session_scope(db) as session:
        return json.loads(session.get(OpportunityRun, run_id).notes_json)


# ═══════════════════════════════ پینِ رتبه/ارزش: دو اجرا با همان ورودی‌ها
def test_two_runs_with_the_same_inputs_give_the_same_ranking_and_values(tmp_path, analyzed):
    clean, bundle = analyzed
    db = _prepare(tmp_path, analyzed)
    reference = time.time()

    first = run_opportunity_engine(bundle, clean, db_path=db, fatigue_now=reference)
    ranking_1 = _ranking(db)
    second = run_opportunity_engine(bundle, clean, db_path=db, fatigue_now=reference)
    ranking_2 = _ranking(db)

    assert first is not None and second is not None and first.created > 0
    assert ranking_1 == ranking_2, "رتبه و ارزش با همان ورودی‌ها بیت‌به‌بیت یکی است"
    assert second.created == 0 and second.refreshed == first.created
    notes_1, notes_2 = _run_notes(db, first.run_id), _run_notes(db, second.run_id)
    assert notes_1["fatigue_reference_ts"] == notes_2["fatigue_reference_ts"] == reference
    assert notes_1["fatigue_window_days"] == 14


def test_default_reference_is_the_wall_clock_and_is_recorded(tmp_path, analyzed):
    clean, bundle = analyzed
    db = _prepare(tmp_path, analyzed)
    before = time.time()
    result = run_opportunity_engine(bundle, clean, db_path=db)
    after = time.time()
    notes = _run_notes(db, result.run_id)
    assert before <= notes["fatigue_reference_ts"] <= after


# ═══════════════════════════════ تماسِ واقعی + مرجعِ دیرتر ⇒ مسدود با کدِ خستگی
def test_a_real_contact_blocks_the_customer_only_inside_the_window(tmp_path, analyzed):
    clean, bundle = analyzed
    db = _prepare(tmp_path, analyzed)
    baseline = run_opportunity_engine(bundle, clean, db_path=db, fatigue_now=time.time())
    with session_scope(db) as session:
        top = session.scalars(
            select(Opportunity).where(Opportunity.customer_id.isnot(None))
            .order_by(Opportunity.score_rial.desc())
        ).first()
        assert top is not None
        from mktcore.db.models import CustomerKey

        raw_key = session.scalar(select(CustomerKey.key_value).where(
            CustomerKey.customer_id == top.customer_id, CustomerKey.key_type == "raw_key",
        ))
    assert raw_key

    # تماسِ واقعی (نه پیش‌نمایش) همین حالا
    contact_at = time.time()
    store.add_outbox(kind="test", status="sent", customer_id=raw_key, phone=None,
                     message="x", dry_run=False)

    # مرجع یک روز بعد از تماس ⇒ داخلِ پنجره ⇒ فرصت‌های این مشتری با کدِ خستگی مسدود
    later = run_opportunity_engine(bundle, clean, db_path=db, fatigue_now=contact_at + 86400)
    with session_scope(db) as session:
        open_for_customer = session.scalars(
            select(Opportunity).where(
                Opportunity.customer_id == top.customer_id, Opportunity.status == "open",
            )
        ).all()
    assert later.filtered_out > baseline.filtered_out
    assert not open_for_customer, "مشتریِ تازه‌تماس‌گرفته فرصتِ باز ندارد"
    assert _run_notes(db, later.run_id)["fatigue_reference_ts"] == contact_at + 86400

    # همان تماس، مرجع ۳۰ روز بعد ⇒ بیرونِ پنجره ⇒ دوباره باز
    again = run_opportunity_engine(bundle, clean, db_path=db, fatigue_now=contact_at + 30 * 86400)
    with session_scope(db) as session:
        reopened = session.scalars(
            select(Opportunity).where(
                Opportunity.customer_id == top.customer_id, Opportunity.status == "open",
            )
        ).all()
        passes = session.execute(
            select(OpportunityFactor.outcome)
            .join(Opportunity, Opportunity.id == OpportunityFactor.opportunity_id)
            .where(OpportunityFactor.code == "fatigue", Opportunity.customer_id == top.customer_id)
        ).all()
    assert reopened, "بیرونِ پنجره، فرصت‌های مشتری برمی‌گردند"
    assert {str(p[0]) for p in passes} == {OUTCOME_PASS}
    assert again.filtered_out == baseline.filtered_out
