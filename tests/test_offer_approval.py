"""تأییدِ انسانیِ تخفیف — §۲۰.۳ و تصمیمِ کاربر: «بدون تأیید، هیچ تخفیفی ارسال نمی‌شود».

## قاعده‌هایی که این فایل پین می‌کند

* موتور پیشنهاد می‌سازد، ولی **تصمیمِ انسان را پاک نمی‌کند**: اجرای بعدی تأیید
  را نگه می‌دارد، مگر مبنای پیشنهاد (حاشیه/کف) عوض شده باشد ⇒ «کهنه».
* تأیید در لحظه‌ی خودش حاشیه را دوباره حساب می‌کند؛ زیرِ کف ⇒ رد (۴۰۹) و «کهنه».
* هر تصمیم یک ردیفِ ممیزی و یک رخدادِ فرصت می‌سازد.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import select

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

from mktcore.analysis.kpis import compute_kpis  # noqa: E402
from mktcore.db import session_scope  # noqa: E402
from mktcore.db.migrations import reset_ensure_cache  # noqa: E402
from mktcore.db.models import (  # noqa: E402
    AuditEvent,
    Customer,
    Opportunity,
    OpportunityEvent,
    OpportunityOffer,
)
from mktcore.db.repo_features import write_customer_features  # noqa: E402
from mktcore.db.repo_import import write_import  # noqa: E402
from mktcore.ingest.cleaning import clean_frame  # noqa: E402
from mktcore.ingest.mapper import SchemaMapper  # noqa: E402
from mktcore.ingest.schema import ColumnRole  # noqa: E402
from mktcore.opportunities import run_opportunity_engine  # noqa: E402
from mktcore.opportunities.offers import (  # noqa: E402
    DECISION_APPROVE,
    DECISION_REJECT,
    OfferDecisionError,
    decide_offer,
)
from mktcore.pipeline import run_analysis  # noqa: E402
from mktcore.settings_store import set_margin_floor_bp, set_offer_ladder_bp  # noqa: E402

from .test_golden_scenarios import _COLS_DISC, _MAPPING_DISC, _discount_rows  # noqa: E402

COLS = [*_COLS_DISC, "بها"]
MAPPING = {**_MAPPING_DISC, ColumnRole.COST: "بها"}
LADDER = [500, 1000, 1500]


@pytest.fixture(autouse=True)
def _isolate():
    reset_ensure_cache()
    yield
    reset_ensure_cache()


def _rows() -> list[tuple]:
    """همان سه مشتریِ §۳۴.۳، به‌اضافه‌ی بها: حاشیه‌ی همه‌ی خطوط ۳۰٪."""
    out = []
    for row in _discount_rows(amount=False):
        revenue = row[1]
        out.append((*row, round(revenue * 0.7)))
    return out


@pytest.fixture
def ledger(tmp_path) -> tuple[Path, object, pd.DataFrame]:
    db = tmp_path / "app.db"
    raw = pd.DataFrame(_rows(), columns=COLS)
    clean = clean_frame(SchemaMapper().apply(raw, MAPPING))
    write_import(clean, kpis=compute_kpis(clean), db_path=db)
    bundle = run_analysis(clean, horizon=2, with_forecast=False)
    write_customer_features(clean, bundle, db_path=db)
    set_margin_floor_bp(2_000, db_path=db)
    set_offer_ladder_bp(LADDER, db_path=db)
    return db, bundle, clean


def _offers(db: Path) -> dict[str, OpportunityOffer]:
    with session_scope(db) as session:
        rows = session.execute(
            select(Customer.canonical_key, OpportunityOffer)
            .join(Opportunity, Opportunity.id == OpportunityOffer.opportunity_id)
            .join(Customer, Customer.id == Opportunity.customer_id)
        ).all()
        session.expunge_all()
    return {key: offer for key, offer in rows}


def _run(db, bundle, clean):
    result = run_opportunity_engine(bundle, clean, db_path=db)
    assert result is not None
    return result


# ═══════════════════════════════════════════ پیشنهاد از موتور
def test_engine_suggests_the_smallest_rung_only_for_discount_dependent_customers(ledger):
    db, bundle, clean = ledger
    _run(db, bundle, clean)

    offers = _offers(db)
    assert "تخفیفی" in offers, "مشتریِ وابسته به تخفیف باید پیشنهاد بگیرد"
    assert offers["تخفیفی"].suggested_discount_bp == 500
    assert offers["تخفیفی"].status == OpportunityOffer.STATUS_SUGGESTED
    assert offers["تخفیفی"].tier == "low"
    assert offers["تخفیفی"].margin_bp_at_suggestion == 3_000
    assert offers["تخفیفی"].floor_bp_at_suggestion == 2_000
    assert "وفادار" not in offers, "تمام‌قیمت‌خر پیشنهادِ تخفیف نمی‌گیرد"


def test_without_a_ladder_no_offer_row_is_ever_written(ledger):
    db, bundle, clean = ledger
    set_offer_ladder_bp(None, db_path=db)
    _run(db, bundle, clean)

    assert _offers(db) == {}


# ═══════════════════════════════════════════ تأیید و رد
def _opportunity_id(db: Path, key: str) -> int:
    with session_scope(db) as session:
        return session.scalar(
            select(Opportunity.id)
            .join(OpportunityOffer, OpportunityOffer.opportunity_id == Opportunity.id)
            .join(Customer, Customer.id == Opportunity.customer_id)
            .where(Customer.canonical_key == key)
        )


def test_approval_is_recorded_with_an_audit_row_and_an_event(ledger):
    db, bundle, clean = ledger
    _run(db, bundle, clean)
    opportunity_id = _opportunity_id(db, "تخفیفی")

    payload = decide_offer(
        opportunity_id, DECISION_APPROVE, decided_by="مدیر فروش", db_path=db,
    )

    assert payload["status"] == OpportunityOffer.STATUS_APPROVED
    assert payload["sendable"] is True
    assert payload["decided_by"] == "مدیر فروش"
    with session_scope(db) as session:
        audit = session.scalars(
            select(AuditEvent).where(AuditEvent.action == AuditEvent.ACTION_OFFER_APPROVED)
        ).all()
        events = session.scalars(
            select(OpportunityEvent).where(
                OpportunityEvent.opportunity_id == opportunity_id,
                OpportunityEvent.event_type == "offer_approved",
            )
        ).all()
        assert len(audit) == 1 and "مدیر فروش" in (audit[0].detail_fa or "")
        assert len(events) == 1


def test_approval_survives_the_next_engine_run(ledger):
    """اجرای روزانه‌ی موتور نباید تصمیمِ انسان را پاک کند."""
    db, bundle, clean = ledger
    _run(db, bundle, clean)
    decide_offer(_opportunity_id(db, "تخفیفی"), DECISION_APPROVE, db_path=db)

    _run(db, bundle, clean)

    assert _offers(db)["تخفیفی"].status == OpportunityOffer.STATUS_APPROVED


def test_a_raised_floor_makes_the_approval_stale_on_the_next_run(ledger):
    """کف بالا رفت ولی همان پله هنوز جا دارد ⇒ مبنای تأیید عوض شده، تأیید دوباره."""
    db, bundle, clean = ledger
    _run(db, bundle, clean)
    decide_offer(_opportunity_id(db, "تخفیفی"), DECISION_APPROVE, db_path=db)

    set_margin_floor_bp(2_500, db_path=db)   # ۵٪ تخفیف حاشیه را به ۲۶٫۳٪ می‌رساند؛ هنوز ≥ ۲۵٪
    _run(db, bundle, clean)

    offer = _offers(db)["تخفیفی"]
    assert offer.status == OpportunityOffer.STATUS_STALE
    assert offer.suggested_discount_bp == 500
    assert "کهنه" in (offer.decision_note_fa or "")


def test_a_floor_above_every_rung_withdraws_the_approval_on_the_next_run(ledger):
    """کف چنان بالا رفت که هیچ پله‌ای جا ندارد ⇒ پیشنهادی نیست که دوباره تأیید شود."""
    db, bundle, clean = ledger
    _run(db, bundle, clean)
    decide_offer(_opportunity_id(db, "تخفیفی"), DECISION_APPROVE, db_path=db)

    set_margin_floor_bp(2_700, db_path=db)   # ۲۶٫۳٪ < ۲۷٪ — حتی کوچک‌ترین پله رد می‌شود
    _run(db, bundle, clean)

    offer = _offers(db)["تخفیفی"]
    assert offer.status == OpportunityOffer.STATUS_WITHDRAWN
    assert "برداشته شد" in (offer.decision_note_fa or "")


def test_approving_below_todays_floor_is_refused_and_marked_stale(ledger):
    db, bundle, clean = ledger
    _run(db, bundle, clean)
    opportunity_id = _opportunity_id(db, "تخفیفی")
    set_margin_floor_bp(2_700, db_path=db)   # کف بعد از پیشنهاد بالا رفت

    with pytest.raises(OfferDecisionError) as caught:
        decide_offer(opportunity_id, DECISION_APPROVE, db_path=db)

    assert caught.value.conflict is True
    assert "زیرِ کف" in caught.value.reason_fa
    assert _offers(db)["تخفیفی"].status == OpportunityOffer.STATUS_STALE


def test_rejection_is_respected_by_later_runs_with_the_same_rung(ledger):
    db, bundle, clean = ledger
    _run(db, bundle, clean)
    opportunity_id = _opportunity_id(db, "تخفیفی")

    decide_offer(opportunity_id, DECISION_REJECT, decided_by="مدیر", note_fa="نه", db_path=db)
    _run(db, bundle, clean)

    offer = _offers(db)["تخفیفی"]
    assert offer.status == OpportunityOffer.STATUS_REJECTED
    assert offer.decision_note_fa == "نه"


def test_unknown_opportunity_or_decision_is_not_a_conflict(ledger):
    db, _bundle, _clean = ledger
    with pytest.raises(OfferDecisionError) as caught:
        decide_offer(999_999, DECISION_APPROVE, db_path=db)
    assert caught.value.conflict is False

    with pytest.raises(OfferDecisionError):
        decide_offer(1, "maybe", db_path=db)


# ═══════════════════════════════════ یافته‌های بازبینی خصمانه
def test_removing_the_ladder_withdraws_the_offer_and_blocks_approval(ledger):
    """ردیفِ کهنه‌ی یک نردبانِ برداشته‌شده نباید با یک کلیک به پیامک برسد."""
    db, bundle, clean = ledger
    _run(db, bundle, clean)
    opportunity_id = _opportunity_id(db, "تخفیفی")
    decide_offer(opportunity_id, DECISION_APPROVE, db_path=db)

    set_offer_ladder_bp(None, db_path=db)
    _run(db, bundle, clean)
    offer = _offers(db)["تخفیفی"]
    assert offer.status == OpportunityOffer.STATUS_WITHDRAWN
    assert "برداشته شد" in (offer.decision_note_fa or "")

    with pytest.raises(OfferDecisionError) as caught:
        decide_offer(opportunity_id, DECISION_APPROVE, db_path=db)
    assert "برداشته" in caught.value.reason_fa
    assert _offers(db)["تخفیفی"].status == OpportunityOffer.STATUS_WITHDRAWN


def test_a_rung_no_longer_on_the_ladder_cannot_be_approved(ledger):
    db, bundle, clean = ledger
    _run(db, bundle, clean)
    opportunity_id = _opportunity_id(db, "تخفیفی")
    set_offer_ladder_bp([1_000, 1_500], db_path=db)   # پله‌ی ۵٪ دیگر روی نردبان نیست

    with pytest.raises(OfferDecisionError) as caught:
        decide_offer(opportunity_id, DECISION_APPROVE, db_path=db)

    assert "روی نردبانِ فعلی" in caught.value.reason_fa
    with session_scope(db) as session:
        refused = session.scalars(
            select(AuditEvent).where(
                AuditEvent.action == AuditEvent.ACTION_OFFER_APPROVAL_REFUSED
            )
        ).all()
        events = session.scalars(
            select(OpportunityEvent).where(
                OpportunityEvent.opportunity_id == opportunity_id,
                OpportunityEvent.event_type == "offer_approval_refused",
            )
        ).all()
    assert len(refused) == 1 and len(events) == 1, "ردِ سیستمی هم باید ردیفِ ممیزی و رخداد داشته باشد"


def test_a_refused_approval_keeps_the_human_rejection_note(ledger):
    """یک تأییدِ ناموفق نباید یادداشتِ «نه» مدیر را با متنِ سیستم بازنویسی کند."""
    db, bundle, clean = ledger
    _run(db, bundle, clean)
    opportunity_id = _opportunity_id(db, "تخفیفی")
    decide_offer(opportunity_id, DECISION_REJECT, decided_by="مدیر", note_fa="نه، این مشتری تخفیف نمی‌خواهد", db_path=db)
    set_margin_floor_bp(2_700, db_path=db)

    with pytest.raises(OfferDecisionError):
        decide_offer(opportunity_id, DECISION_APPROVE, decided_by="کارمند", db_path=db)

    offer = _offers(db)["تخفیفی"]
    assert offer.status == OpportunityOffer.STATUS_REJECTED
    assert offer.decided_by == "مدیر"
    assert offer.decision_note_fa == "نه، این مشتری تخفیف نمی‌خواهد"


def test_approval_recomputes_margin_on_the_basis_the_engine_used(ledger):
    """فرصتِ بی‌`product_id` با مبنای نام (مثل «شکاف دسته») باید با همان نام بازخوانی شود."""
    from mktcore.opportunities.offers import _current_margin_and_floor

    db, bundle, clean = ledger
    _run(db, bundle, clean)
    with session_scope(db) as session:
        offer = session.scalars(select(OpportunityOffer)).first()
        opportunity = session.get(Opportunity, offer.opportunity_id)
        opportunity.product_id = None            # مثل «شکاف دسته»
        offer.margin_basis, offer.margin_key = "name", "کالا"   # نامی که در دفتر کل حاشیه دارد
        by_name = _current_margin_and_floor(session, opportunity, offer)
        offer.margin_basis, offer.margin_key = "customer", None
        by_customer = _current_margin_and_floor(session, opportunity, offer)
        session.rollback()

    assert by_name[0] == 3_000, "مبنای نام باید حاشیه‌ی کالا/دسته را بخواند، نه سبدِ مشتری"
    assert by_customer[0] == 3_000


def test_margin_by_customer_requires_full_cost_coverage(tmp_path):
    """مشتری با یک خطِ بی‌بها حاشیه ندارد — حاشیه از داده‌ی ناقص، دروغ است."""
    from mktcore.costs.register import margin_by_customer
    from mktcore.db.lookup import resolve_business_id

    rows = _rows()
    # یک خطِ مشتریِ «وفادار» بی‌بها می‌شود
    rows = [(*r[:-1], "") if r[3] == "وفادار" and r[4] == "L0" else r for r in rows]
    raw = pd.DataFrame(rows, columns=COLS)
    clean = clean_frame(SchemaMapper().apply(raw, MAPPING))
    db = tmp_path / "app.db"
    write_import(clean, kpis=compute_kpis(clean), db_path=db)

    with session_scope(db) as session:
        business_id = resolve_business_id(session, "default")
        margins = margin_by_customer(session, business_id)
        keys = dict(session.execute(select(Customer.id, Customer.canonical_key)).all())
    by_key = {keys[cid]: bp for cid, bp in margins.items()}
    assert by_key["تخفیفی"] == 3_000
    assert "وفادار" not in by_key
