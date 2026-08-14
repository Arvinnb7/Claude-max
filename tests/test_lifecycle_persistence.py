"""حالت چرخه‌ی عمر در دفتر کل: نوشتن، گذار، و نبودِ نویز.

سند §۱۱ می‌خواهد گذارها و دلیلشان ماندگار شوند. ادعای اینجا: حالت پر می‌شود،
گذار فقط وقتی ثبت می‌شود که **واقعاً** عوض شده باشد، و اجرای دوباره روی همان
داده هیچ گذارِ ساختگی نمی‌سازد.
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
    Customer,
    CustomerFeature,
    CustomerLifecycleEvent,
)
from mktcore.db.repo_features import write_customer_features  # noqa: E402
from mktcore.db.repo_import import write_import  # noqa: E402
from mktcore.ingest.cleaning import clean_frame  # noqa: E402
from mktcore.ingest.mapper import SchemaMapper  # noqa: E402
from mktcore.ingest.schema import ColumnRole  # noqa: E402
from mktcore.lifecycle import LIFECYCLE_STATES  # noqa: E402
from mktcore.pipeline import run_analysis  # noqa: E402

_COLS = ["تاریخ", "مبلغ", "مشتری", "فاکتور", "کالا"]
_MAPPING = {
    ColumnRole.DATE: "تاریخ",
    ColumnRole.REVENUE: "مبلغ",
    ColumnRole.CUSTOMER_ID: "مشتری",
    ColumnRole.ORDER_ID: "فاکتور",
    ColumnRole.PRODUCT: "کالا",
}


@pytest.fixture(autouse=True)
def _isolate_schema_cache():
    reset_ensure_cache()
    yield
    reset_ensure_cache()


def _clean(rows: list[tuple]) -> pd.DataFrame:
    raw = pd.DataFrame(rows, columns=_COLS)
    return clean_frame(SchemaMapper().apply(raw, _MAPPING))


def _write(rows: list[tuple], db: Path) -> pd.DataFrame:
    clean = _clean(rows)
    write_import(clean, kpis=compute_kpis(clean), db_path=db)
    bundle = run_analysis(clean, horizon=2, with_forecast=False)
    write_customer_features(clean, bundle, db_path=db)
    return clean


def _regular_buyers(months: int, customers: int = 12) -> list[tuple]:
    """مشتریانی که هر ماه خرید می‌کنند — پایه‌ی معنادار برای تحلیل."""
    rows = []
    for c in range(customers):
        for m in range(months):
            rows.append((
                f"1402/{m + 1:02d}/{(c % 27) + 1:02d}",
                200_000 + c * 1000,
                f"C{c}", f"F{c}-{m}", "کالا",
            ))
    return rows


def test_lifecycle_state_is_written_for_every_customer(tmp_path):
    db = tmp_path / "app.db"
    _write(_regular_buyers(months=6), db)

    with session_scope(db) as session:
        features = session.scalars(select(CustomerFeature)).all()
        assert features
        assert all(f.lifecycle_state for f in features), "حالتی خالی مانده است"
        assert all(f.lifecycle_state in LIFECYCLE_STATES for f in features)


def test_first_snapshot_records_an_entry_transition(tmp_path):
    """اولین بار، گذار از «هیچ» به حالت اول ثبت می‌شود."""
    db = tmp_path / "app.db"
    _write(_regular_buyers(months=6), db)

    with session_scope(db) as session:
        events = session.scalars(select(CustomerLifecycleEvent)).all()
        customers = session.scalar(select(func.count()).select_from(Customer))
    assert len(events) == customers
    assert all(e.from_state is None for e in events)
    assert all(e.reason_fa for e in events), "گذار بدون دلیل ثبت شده است"
    assert all(e.basis in ("personal", "population", "count_only") for e in events)


def test_rerunning_the_same_analysis_creates_no_new_transitions(tmp_path):
    """اجرای دوباره روی همان داده نباید تایم‌لاین را از نویز پر کند."""
    db = tmp_path / "app.db"
    clean = _clean(_regular_buyers(months=6))
    bundle = run_analysis(clean, horizon=2, with_forecast=False)
    write_import(clean, kpis=compute_kpis(clean), db_path=db)

    write_customer_features(clean, bundle, db_path=db)
    with session_scope(db) as session:
        first = session.scalar(select(func.count()).select_from(CustomerLifecycleEvent))

    for _ in range(3):
        write_customer_features(clean, bundle, db_path=db)
    with session_scope(db) as session:
        after = session.scalar(select(func.count()).select_from(CustomerLifecycleEvent))

    assert after == first


def test_transition_is_recorded_when_the_state_actually_changes(tmp_path):
    """مشتری‌ای که در فایل بعدی غایب است باید گذار به حالت عقب‌افتاده بگیرد."""
    db = tmp_path / "app.db"
    base = _regular_buyers(months=6)
    _write(base, db)

    with session_scope(db) as session:
        before = {
            f.customer_id: f.lifecycle_state
            for f in session.scalars(select(CustomerFeature)).all()
        }

    # چند ماه بعد، همه خرید کرده‌اند جز «C0»
    later = base + [
        (f"1402/{m:02d}/10", 200_000 + c * 1000, f"C{c}", f"G{c}-{m}", "کالا")
        for c in range(1, 12) for m in (7, 8, 9, 10, 11)
    ]
    _write(later, db)

    with session_scope(db) as session:
        c0 = session.scalar(select(Customer).where(Customer.canonical_key == "C0"))
        latest = session.scalars(
            select(CustomerFeature)
            .where(CustomerFeature.customer_id == c0.id)
            .order_by(CustomerFeature.as_of_date.desc())
        ).first()
        transitions = session.scalars(
            select(CustomerLifecycleEvent)
            .where(CustomerLifecycleEvent.customer_id == c0.id)
            .order_by(CustomerLifecycleEvent.as_of_date)
        ).all()

    # C0 دیگر خرید نکرده → باید از حالت سالم به حالت عقب‌افتاده رفته باشد
    assert latest.lifecycle_state in ("slipping", "at_risk", "dormant", "lost")
    assert len(transitions) >= 2
    assert transitions[-1].from_state == before[c0.id]
    assert transitions[-1].to_state == latest.lifecycle_state
    assert transitions[-1].reason_fa


def test_states_are_personalised_not_calendar_based(tmp_path):
    """دو مشتری با آهنگ متفاوت و بی‌خریدیِ یکسان → دو حالت متفاوت."""
    db = tmp_path / "app.db"
    rows = []
    # مشتری هفتگی: ۱۲ خرید هفتگی، بعد ۶۰ روز سکوت
    for w in range(12):
        day = 1 + w * 7
        rows.append((f"1402/{(day - 1) // 30 + 1:02d}/{(day - 1) % 30 + 1:02d}",
                     150_000, "هفتگی", f"W{w}", "کالا"))
    # مشتری فصلی: ۴ خرید با فاصله‌ی ~۹۰ روز، آخری هم‌زمان با آخرین خرید هفتگی
    for q in range(4):
        month = 1 + q * 3
        rows.append((f"1402/{month:02d}/01", 600_000, "فصلی", f"Q{q}", "کالا"))
    # پس‌زمینه تا تحلیل معنادار بماند
    rows += _regular_buyers(months=5, customers=8)

    _write(rows, db)

    with session_scope(db) as session:
        states = {}
        for key in ("هفتگی", "فصلی"):
            customer = session.scalar(select(Customer).where(Customer.canonical_key == key))
            feature = session.scalar(
                select(CustomerFeature).where(CustomerFeature.customer_id == customer.id)
            )
            states[key] = feature.lifecycle_state

    # همان تعداد روز سکوت، ولی برای مشتری هفتگی خیلی بیشتر از آهنگش است
    assert states["هفتگی"] != states["فصلی"]


def test_basis_shows_when_judgement_used_population_median(tmp_path):
    """مشتری تک‌خرید آهنگ شخصی ندارد؛ UI باید بداند قضاوت روی جامعه بوده."""
    db = tmp_path / "app.db"
    rows = _regular_buyers(months=6)
    rows.append(("1402/03/15", 500_000, "تک‌خرید", "S1", "کالا"))
    _write(rows, db)

    with session_scope(db) as session:
        customer = session.scalar(
            select(Customer).where(Customer.canonical_key == "تک‌خرید")
        )
        event = session.scalar(
            select(CustomerLifecycleEvent)
            .where(CustomerLifecycleEvent.customer_id == customer.id)
        )
    assert event.basis in ("population", "count_only")
