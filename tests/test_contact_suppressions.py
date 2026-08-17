"""دفترِ انصراف روی دیتابیس — ماندگاری، idempotency، و بازوی کنترل.

مهم‌ترین تستِ این فایل `test_opt_out_survives_a_reimport` است: اگر انصراف با
بارگذاری فایل ماه بعد پاک شود، سیستم به کسی پیام می‌دهد که گفته «نده» — و کاربر
هیچ‌وقت نمی‌فهمد چرا.
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
from mktcore.campaigns.assign import ARM_CONTROL, ARM_TREATMENT  # noqa: E402
from mktcore.contact.register import (  # noqa: E402
    active_suppressions,
    build_gate,
    control_arm_customer_ids,
    list_suppressions,
    load_gate,
    record_opt_out,
    revoke_opt_out,
)
from mktcore.db import session_scope  # noqa: E402
from mktcore.db.migrations import reset_ensure_cache  # noqa: E402
from mktcore.db.models import (  # noqa: E402
    Business,
    Campaign,
    CampaignMember,
    ContactSuppression,
    Customer,
)
from mktcore.db.repo_import import write_import  # noqa: E402
from mktcore.ingest.cleaning import clean_frame  # noqa: E402
from mktcore.ingest.mapper import SchemaMapper  # noqa: E402
from mktcore.ingest.schema import ColumnRole  # noqa: E402

_COLS = ["تاریخ", "مبلغ", "مشتری", "فاکتور", "کالا", "موبایل"]
_MAPPING = {
    ColumnRole.DATE: "تاریخ",
    ColumnRole.REVENUE: "مبلغ",
    ColumnRole.CUSTOMER_ID: "مشتری",
    ColumnRole.ORDER_ID: "فاکتور",
    ColumnRole.PRODUCT: "کالا",
    ColumnRole.PHONE: "موبایل",
}


@pytest.fixture(autouse=True)
def _isolate_schema_cache():
    reset_ensure_cache()
    yield
    reset_ensure_cache()


def _rows(n: int = 5, *, with_phone: bool = True) -> list[tuple]:
    out = []
    for i in range(n):
        phone = f"0912000{i:04d}" if with_phone else None
        out.append((f"1402/01/{(i % 28) + 1:02d}", 500_000 + i, f"C{i}", f"A{i}", "کالا", phone))
        out.append((f"1402/02/{(i % 28) + 1:02d}", 500_000 + i, f"C{i}", f"B{i}", "کالا", phone))
    return out


def _ingest(rows: list[tuple], db: Path) -> pd.DataFrame:
    raw = pd.DataFrame(rows, columns=_COLS)
    clean = clean_frame(SchemaMapper().apply(raw, _MAPPING))
    write_import(clean, kpis=compute_kpis(clean), db_path=db)
    return clean


def _customer(db: Path, canonical_key: str) -> Customer:
    with session_scope(db) as session:
        row = session.scalar(select(Customer).where(Customer.canonical_key == canonical_key))
        assert row is not None, f"مشتری {canonical_key} ساخته نشد"
        session.expunge(row)
        return row


# ═══════════════════════════════════════════════════ ثبت و بازگردانی
def test_record_and_revoke_opt_out(tmp_path):
    db = tmp_path / "app.db"
    _ingest(_rows(), db)
    customer = _customer(db, "C1")

    result = record_opt_out(
        customer_id=customer.id, reason_fa="خودش تلفنی گفت تماس نگیرید", db_path=db,
    )
    assert result["created"] is True

    gate = load_gate(db_path=db)
    assert gate.reason_for(str(customer.id)) == "consent"
    assert gate.reason_for("C1") == "consent", "کلید خام هم باید بشناسد"

    assert revoke_opt_out(customer_id=customer.id, db_path=db) is True
    assert load_gate(db_path=db).reason_for("C1") is None


def test_record_opt_out_is_idempotent(tmp_path):
    db = tmp_path / "app.db"
    _ingest(_rows(), db)
    customer = _customer(db, "C1")

    first = record_opt_out(customer_id=customer.id, reason_fa="دلیل", db_path=db)
    second = record_opt_out(customer_id=customer.id, reason_fa="دلیل تازه", db_path=db)

    assert first["created"] is True
    assert second["created"] is False
    with session_scope(db) as session:
        assert session.scalar(
            select(ContactSuppression).where(ContactSuppression.id == first["id"])
        ).reason_fa == "دلیل تازه"
        rows = session.scalars(select(ContactSuppression)).all()
    assert len(rows) == 1, "ثبتِ دوباره نباید ردیف تازه بسازد"


def test_re_opting_out_after_revoke_reactivates_the_same_row(tmp_path):
    db = tmp_path / "app.db"
    _ingest(_rows(), db)
    customer = _customer(db, "C1")

    record_opt_out(customer_id=customer.id, reason_fa="یک", db_path=db)
    revoke_opt_out(customer_id=customer.id, db_path=db)
    again = record_opt_out(customer_id=customer.id, reason_fa="دو", db_path=db)

    assert again["reactivated"] is True
    with session_scope(db) as session:
        assert len(session.scalars(select(ContactSuppression)).all()) == 1


def test_revoking_keeps_the_row_for_history(tmp_path):
    """پس گرفتن انصراف نباید تاریخ را پاک کند."""
    db = tmp_path / "app.db"
    _ingest(_rows(), db)
    customer = _customer(db, "C1")

    record_opt_out(customer_id=customer.id, reason_fa="دلیل", db_path=db)
    revoke_opt_out(customer_id=customer.id, db_path=db)

    everything = list_suppressions(db_path=db, active_only=False)
    assert len(everything) == 1
    assert everything[0]["active"] is False
    assert everything[0]["revoked_at"] is not None
    assert list_suppressions(db_path=db, active_only=True) == []


def test_reason_is_mandatory(tmp_path):
    db = tmp_path / "app.db"
    _ingest(_rows(), db)
    customer = _customer(db, "C1")
    with pytest.raises(ValueError, match="دلیل"):
        record_opt_out(customer_id=customer.id, reason_fa="   ", db_path=db)


def test_identifier_is_mandatory(tmp_path):
    db = tmp_path / "app.db"
    _ingest(_rows(), db)
    with pytest.raises(ValueError, match="شناسه"):
        record_opt_out(reason_fa="دلیل", db_path=db)


# ═════════════════════════════════════════════ ماندگاری در برابر re-import
def test_opt_out_survives_a_reimport(tmp_path):
    """فایل ماه بعد نباید انصراف را پاک کند."""
    db = tmp_path / "app.db"
    _ingest(_rows(), db)
    customer = _customer(db, "C1")
    record_opt_out(customer_id=customer.id, reason_fa="نمی‌خواهد", db_path=db)

    # ماه بعد: همان مشتریان + خریدهای تازه
    _ingest(_rows() + [("1402/03/05", 900_000, "C1", "Z1", "کالا", "09120000001")], db)

    assert load_gate(db_path=db).reason_for("C1") == "consent"


def test_opt_out_by_phone_is_found_before_identity_resolution(tmp_path):
    """انصراف با شماره، پیش از اینکه مشتری در سیستم شناخته شود."""
    db = tmp_path / "app.db"
    _ingest(_rows(), db)

    record_opt_out(phone="09129999999", reason_fa="پاسخ لغو در پنل", source="provider", db_path=db)
    gate = load_gate(db_path=db)
    assert gate.reason_for("someone", phone="+989129999999") == "consent"


def test_phone_is_normalised_on_write(tmp_path):
    db = tmp_path / "app.db"
    _ingest(_rows(), db)
    record_opt_out(phone="0912 000 0002", reason_fa="دلیل", db_path=db)
    with session_scope(db) as session:
        row = session.scalar(select(ContactSuppression))
    assert row.phone_e164 == "+989120000002"


# ═══════════════════════════════════════════════════════ بازوی کنترل
def _make_campaign(db: Path, *, status: str = "running") -> tuple[int, list[int]]:
    with session_scope(db) as session:
        business_id = session.scalar(select(Business.id))
        customers = session.scalars(select(Customer)).all()
        campaign = Campaign(
            business_id=business_id, name="آزمون", status=status,
            holdout_pct=20, analysis_window_days=30,
        )
        session.add(campaign)
        session.flush()
        control_ids = []
        for index, customer in enumerate(customers):
            arm = ARM_CONTROL if index % 2 == 0 else ARM_TREATMENT
            if arm == ARM_CONTROL:
                control_ids.append(customer.id)
            session.add(CampaignMember(
                campaign_id=campaign.id, customer_id=customer.id,
                arm=arm, stratum="همه", assigned_date="1402-03-01",
            ))
        session.flush()
        return campaign.id, control_ids


def test_control_arm_members_are_blocked(tmp_path):
    db = tmp_path / "app.db"
    _ingest(_rows(), db)
    _campaign_id, control_ids = _make_campaign(db)

    gate = load_gate(db_path=db)
    for customer_id in control_ids:
        assert gate.reason_for(str(customer_id)) == "control_arm"


def test_closed_campaign_releases_its_control_arm(tmp_path):
    """بعد از بسته‌شدن کمپین، پنجره‌ی سنجش تمام است و تماس مجاز می‌شود."""
    db = tmp_path / "app.db"
    _ingest(_rows(), db)
    _campaign_id, control_ids = _make_campaign(db, status="closed")

    gate = load_gate(db_path=db)
    for customer_id in control_ids:
        assert gate.reason_for(str(customer_id)) is None


def test_treatment_arm_is_not_blocked_by_the_control_check(tmp_path):
    db = tmp_path / "app.db"
    _ingest(_rows(), db)
    _make_campaign(db)

    with session_scope(db) as session:
        business_id = session.scalar(select(Business.id))
        treated = session.scalars(
            select(CampaignMember.customer_id).where(CampaignMember.arm == ARM_TREATMENT)
        ).all()
        blocked = control_arm_customer_ids(session, business_id)
    assert treated, "کمپین باید بازوی آزمایش داشته باشد"
    assert not (set(treated) & blocked)


def test_gate_recognises_a_control_member_by_raw_key_too(tmp_path):
    """مسیر ارسال کلید خام دارد، نه شناسه‌ی عددی. دروازه باید هر دو را بشناسد."""
    db = tmp_path / "app.db"
    _ingest(_rows(), db)
    _make_campaign(db)

    with session_scope(db) as session:
        business_id = session.scalar(select(Business.id))
        control_ids = control_arm_customer_ids(session, business_id)
        raw_keys = session.scalars(
            select(Customer.canonical_key).where(Customer.id.in_(sorted(control_ids)))
        ).all()

    gate = load_gate(db_path=db)
    for raw_key in raw_keys:
        assert gate.reason_for(raw_key) == "control_arm"


# ═══════════════════════════════════════════════ صداقت و عدم رگرسیون
def test_empty_register_blocks_nobody_but_admits_it_ran(tmp_path):
    """قرارداد صفر-رگرسیون: دفترِ خالی هیچ‌کس را مسدود نمی‌کند."""
    db = tmp_path / "app.db"
    _ingest(_rows(), db)

    gate = load_gate(db_path=db)
    assert gate.reason_for("C1") is None
    assert gate.has_suppression_data is True
    assert gate.has_campaign_data is True


def test_gate_reports_fatigue_unchecked_when_no_history_is_supplied(tmp_path):
    """پنجره‌ی خستگی از لایه‌ی legacy می‌آید؛ اگر داده نشود، «بررسی نشد»."""
    db = tmp_path / "app.db"
    _ingest(_rows(), db)
    gate = load_gate(db_path=db)
    assert "fatigue" in gate.unchecked_reasons()

    supplied = load_gate(db_path=db, recently_contacted={"C1"})
    assert "fatigue" not in supplied.unchecked_reasons()
    assert supplied.reason_for("C1") == "fatigue"


def test_load_gate_never_raises_on_a_broken_path(tmp_path):
    """نبودِ دفتر نباید ارسال را بخواباند — ولی باید صریح بگوید بررسی نشد."""
    gate = load_gate(db_path=tmp_path / "nonexistent" / "deep" / "app.db")
    assert gate.reason_for("C1") is None
    assert gate.unchecked_reasons(), "باید صریح بگوید چه چیزی بررسی نشد"


def test_active_suppressions_ignores_revoked_rows(tmp_path):
    db = tmp_path / "app.db"
    _ingest(_rows(), db)
    a, b = _customer(db, "C1"), _customer(db, "C2")
    record_opt_out(customer_id=a.id, reason_fa="یک", db_path=db)
    record_opt_out(customer_id=b.id, reason_fa="دو", db_path=db)
    revoke_opt_out(customer_id=a.id, db_path=db)

    with session_scope(db) as session:
        business_id = session.scalar(select(Business.id))
        ids, _phones = active_suppressions(session, business_id)
    assert ids == {b.id}


def test_build_gate_expands_every_identifier_of_a_person(tmp_path):
    db = tmp_path / "app.db"
    _ingest(_rows(), db)
    customer = _customer(db, "C3")
    record_opt_out(customer_id=customer.id, reason_fa="دلیل", db_path=db)

    with session_scope(db) as session:
        business_id = session.scalar(select(Business.id))
        gate = build_gate(session, business_id)

    assert str(customer.id) in gate.opted_out
    assert "C3" in gate.opted_out
