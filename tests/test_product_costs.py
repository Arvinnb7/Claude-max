"""ورودِ بها و انتسابش به خطوط فروش — روی دیتابیس واقعی.

بها در فایل فروشِ این کسب‌وکار نیست؛ در سیستم دیگری است. پس مسیر ورودِ جدا لازم
است. مهم‌ترین تست‌ها: کالای تطبیق‌نیافته **بی‌صدا حذف نشود**، و خط برگشتی سود را
دو برابر کم نکند.
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
from mktcore.costs.basis import (  # noqa: E402
    CONFIDENCE_HISTORY_EXACT,
    CONFIDENCE_HISTORY_IMPUTED,
)
from mktcore.costs.register import (  # noqa: E402
    apply_costs,
    cost_coverage,
    import_costs,
    margin_by_product,
    margin_lookup,
)
from mktcore.db import session_scope  # noqa: E402
from mktcore.db.migrations import reset_ensure_cache  # noqa: E402
from mktcore.db.models import Business, OrderLine, ProductCostHistory  # noqa: E402
from mktcore.db.repo_import import write_import  # noqa: E402
from mktcore.ingest.cleaning import clean_frame  # noqa: E402
from mktcore.ingest.mapper import SchemaMapper  # noqa: E402
from mktcore.ingest.schema import ColumnRole  # noqa: E402
from mktcore.opportunities.contract import OpportunityCandidate  # noqa: E402
from mktcore.opportunities.filters import filter_margin_floor  # noqa: E402
from mktcore.settings_store import margin_floor_bp, set_margin_floor_bp  # noqa: E402

_COLS = ["تاریخ", "مبلغ", "مشتری", "فاکتور", "کالا", "تعداد"]
_MAPPING = {
    ColumnRole.DATE: "تاریخ",
    ColumnRole.REVENUE: "مبلغ",
    ColumnRole.CUSTOMER_ID: "مشتری",
    ColumnRole.ORDER_ID: "فاکتور",
    ColumnRole.PRODUCT: "کالا",
    ColumnRole.QUANTITY: "تعداد",
}


@pytest.fixture(autouse=True)
def _isolate():
    reset_ensure_cache()
    yield
    reset_ensure_cache()


def _ingest(db: Path, rows: list[tuple]) -> None:
    raw = pd.DataFrame(rows, columns=_COLS)
    clean = clean_frame(SchemaMapper().apply(raw, _MAPPING))
    write_import(clean, kpis=compute_kpis(clean), db_path=db)


def _basic(db: Path) -> None:
    """دو خرید از «کالای الف»، یکی ۱۴۰۲ و یکی ۱۴۰۳."""
    _ingest(db, [
        ("1402/03/01", 1_000, "C1", "A1", "کالای الف", 1),
        ("1403/03/01", 1_000, "C1", "A2", "کالای الف", 1),
    ])


# ═════════════════════════════════════════ ورودِ فایل بها
def test_costs_are_stored_against_resolved_products(tmp_path):
    db = tmp_path / "app.db"
    _basic(db)
    result = import_costs(
        [{"product": "کالای الف", "cost": 600, "date": "2023-01-01"}], db_path=db,
    )
    assert result["written"] == 1
    assert result["unmatched_count"] == 0

    with session_scope(db) as session:
        row = session.scalar(select(ProductCostHistory))
    assert row.unit_cost_rial == 6_000, "۶۰۰ تومان = ۶۰۰۰ ریال"


def test_unmatched_products_are_reported_not_dropped_silently(tmp_path):
    """اگر بی‌صدا حذف شوند، پوشش بها ناقص می‌ماند و کسی نمی‌فهمد چرا."""
    db = tmp_path / "app.db"
    _basic(db)
    result = import_costs([
        {"product": "کالای الف", "cost": 600},
        {"product": "کالایی که وجود ندارد", "cost": 900},
    ], db_path=db)

    assert result["written"] == 1
    assert result["unmatched_products"] == ["کالایی که وجود ندارد"]
    assert "اصلاح" in result["note_fa"]


def test_reimporting_the_same_cost_updates_instead_of_duplicating(tmp_path):
    db = tmp_path / "app.db"
    _basic(db)
    import_costs([{"product": "کالای الف", "cost": 600, "date": "2023-01-01"}], db_path=db)
    second = import_costs(
        [{"product": "کالای الف", "cost": 650, "date": "2023-01-01"}], db_path=db,
    )
    assert second["written"] == 0 and second["updated"] == 1

    with session_scope(db) as session:
        rows = session.scalars(select(ProductCostHistory)).all()
    assert len(rows) == 1
    assert rows[0].unit_cost_rial == 6_500


def test_import_without_any_sales_data_is_refused_clearly(tmp_path):
    with pytest.raises(ValueError, match="کسب‌وکاری"):
        import_costs([{"product": "x", "cost": 1}], db_path=tmp_path / "empty.db")


# ═══════════════════════════ انتساب: بهای زمانِ معامله (§۳.۴)
def test_each_line_gets_the_cost_of_its_own_period(tmp_path):
    """خرید ۱۴۰۲ بهای ۱۴۰۲ می‌گیرد، نه بهای گران‌ترِ ۱۴۰۳."""
    db = tmp_path / "app.db"
    _basic(db)
    import_costs([
        {"product": "کالای الف", "cost": 400, "date": "2023-01-01"},
        {"product": "کالای الف", "cost": 900, "date": "2024-01-01"},
    ], db_path=db)
    apply_costs(db_path=db)

    with session_scope(db) as session:
        lines = session.scalars(
            select(OrderLine).order_by(OrderLine.line_date)
        ).all()
        costs = [(ln.line_date, ln.cost_rial, ln.gross_profit_rial) for ln in lines]

    assert costs[0][1] == 4_000, "خط قدیمی باید بهای قدیمی بگیرد"
    assert costs[1][1] == 9_000
    assert costs[0][2] == 10_000 - 4_000
    assert costs[1][2] == 10_000 - 9_000


def test_sale_before_any_known_cost_is_flagged_imputed(tmp_path):
    db = tmp_path / "app.db"
    _basic(db)
    # دو خرید داریم: ۱۴۰۲/۰۳/۰۱ (≈۲۰۲۳-۰۵) و ۱۴۰۳/۰۳/۰۱ (≈۲۰۲۴-۰۵).
    # بها از ۲۰۲۴-۰۱ معتبر است، پس خطِ دوم دقیق و خطِ اول تعمیم‌یافته می‌شود.
    import_costs([{"product": "کالای الف", "cost": 900, "date": "2024-01-01"}], db_path=db)
    apply_costs(db_path=db)

    with session_scope(db) as session:
        lines = session.scalars(select(OrderLine).order_by(OrderLine.line_date)).all()
        levels = [ln.cost_confidence for ln in lines]

    assert CONFIDENCE_HISTORY_IMPUTED in levels, "تعمیم به عقب باید تخمینی برچسب بخورد"
    assert CONFIDENCE_HISTORY_EXACT in levels


def test_applying_costs_twice_is_idempotent(tmp_path):
    db = tmp_path / "app.db"
    _basic(db)
    import_costs([{"product": "کالای الف", "cost": 400, "date": "2023-01-01"}], db_path=db)
    apply_costs(db_path=db)
    with session_scope(db) as session:
        first = [ln.gross_profit_rial for ln in session.scalars(select(OrderLine)).all()]
    apply_costs(db_path=db)
    with session_scope(db) as session:
        second = [ln.gross_profit_rial for ln in session.scalars(select(OrderLine)).all()]
    assert first == second


def test_lines_without_a_cost_keep_null_profit(tmp_path):
    """قاعده‌ی سخت: بدون بها، سود NULL می‌ماند — نه صفر."""
    db = tmp_path / "app.db"
    _ingest(db, [
        ("1402/03/01", 1_000, "C1", "A1", "کالای الف", 1),
        ("1402/04/01", 2_000, "C2", "A2", "کالای ب", 1),
    ])
    import_costs([{"product": "کالای الف", "cost": 400}], db_path=db)
    apply_costs(db_path=db)

    with session_scope(db) as session:
        rows = {
            ln.raw_product_name: (ln.cost_rial, ln.gross_profit_rial)
            for ln in session.scalars(select(OrderLine)).all()
        }
    assert rows["کالای ب"] == (None, None), "کالای بدون بها نباید سود صفر بگیرد"
    assert rows["کالای الف"][1] is not None


# ═══════════════════════════════ خط برگشتی سود را خنثی می‌کند
def test_return_line_cancels_the_original_profit(tmp_path):
    """اگر بهای برگشتی مثبت بماند، سود دو برابر کم می‌شود."""
    db = tmp_path / "app.db"
    _ingest(db, [
        ("1402/03/01", 1_000, "C1", "A1", "کالای الف", 1),
        ("1402/03/05", -1_000, "C1", "A2", "کالای الف", -1),
    ])
    import_costs([{"product": "کالای الف", "cost": 400}], db_path=db)
    apply_costs(db_path=db)

    with session_scope(db) as session:
        lines = session.scalars(select(OrderLine)).all()
        total_profit = sum(ln.gross_profit_rial or 0 for ln in lines)
        returns = [ln for ln in lines if ln.is_return]

    assert returns, "خط برگشتی باید در دفتر باشد"
    assert all((ln.cost_rial or 0) <= 0 for ln in returns), "بهای برگشتی باید منفی باشد"
    assert total_profit == 0, "برگشت باید سود خط اصلی را دقیقاً خنثی کند"


# ═════════════════════════════════════════════════════ پوشش
def test_coverage_reflects_reality(tmp_path):
    db = tmp_path / "app.db"
    _ingest(db, [
        ("1402/03/01", 1_000, "C1", "A1", "کالای الف", 1),
        ("1402/04/01", 2_000, "C2", "A2", "کالای ب", 1),
    ])
    with session_scope(db) as session:
        business_id = session.scalar(select(Business.id))
        assert cost_coverage(session, business_id)[2] == 0.0

    import_costs([{"product": "کالای الف", "cost": 400}], db_path=db)
    apply_costs(db_path=db)
    with session_scope(db) as session:
        business_id = session.scalar(select(Business.id))
        total, with_cost, ratio = cost_coverage(session, business_id)
    assert total == 2 and with_cost == 1 and ratio == 0.5


# ═══════════════════════════════════ حاشیه‌ی هر کالا
def test_margin_only_includes_fully_covered_products(tmp_path):
    """کالایی با پوششِ ناقص، حاشیه‌ی گمراه‌کننده می‌دهد — پس وارد نمی‌شود."""
    db = tmp_path / "app.db"
    _ingest(db, [
        ("1402/03/01", 1_000, "C1", "A1", "کالای الف", 1),
        ("1402/04/01", 2_000, "C2", "A2", "کالای ب", 1),
    ])
    import_costs([{"product": "کالای الف", "cost": 400}], db_path=db)
    apply_costs(db_path=db)

    with session_scope(db) as session:
        business_id = session.scalar(select(Business.id))
        margins = margin_by_product(session, business_id)

    assert "کالای ب" not in margins
    # درآمد ۱۰۰۰۰ ریال، بها ۴۰۰۰ ⇒ حاشیه ۶۰٪ = ۶۰۰۰ پایه‌ی هزارم
    assert margins["کالای الف"] == 6_000


def test_margin_lookup_answers_by_every_name_a_proposal_may_use(tmp_path):
    """پیشنهاد با نامِ نمایشی یا نامِ دسته می‌آید، دفتر کل با نامِ نرمال‌شده.

    اگر فقط یک شکل از نام کلید باشد، `filter_margin_floor` همیشه «حاشیه محاسبه
    نشده» می‌دهد و کفِ تعیین‌شده‌ی کاربر بی‌صدا بی‌اثر می‌ماند.
    """
    db = tmp_path / "app.db"
    raw = pd.DataFrame(
        [("1402/03/01", 1_000, "C1", "A1", "غذاي  خشك", 1, "خشکبار")],
        columns=[*_COLS, "دسته"],
    )
    mapping = {**_MAPPING, ColumnRole.CATEGORY: "دسته"}
    clean = clean_frame(SchemaMapper().apply(raw, mapping))
    write_import(clean, kpis=compute_kpis(clean), db_path=db)

    import_costs([{"product": "غذاي  خشك", "cost": 400}], db_path=db)
    apply_costs(db_path=db)

    with session_scope(db) as session:
        business_id = session.scalar(select(Business.id))
        lookup = margin_lookup(session, business_id)

    assert lookup["غذای خشک"] == 6_000       # نامِ نرمال‌شده
    assert lookup["غذاي  خشك"] == 6_000      # نامِ نمایشی، همان‌طور که در فایل بود
    assert lookup["خشکبار"] == 6_000         # نامِ دسته، برای پیشنهادِ شکاف دسته


def test_category_margin_is_absent_when_one_of_its_products_lacks_cost(tmp_path):
    """حاشیه‌ی دسته از داده‌ی ناقص، کفِ حاشیه را روی نیمی از واقعیت می‌سنجد."""
    db = tmp_path / "app.db"
    raw = pd.DataFrame(
        [
            ("1402/03/01", 1_000, "C1", "A1", "کالای الف", 1, "لبنیات"),
            ("1402/04/01", 2_000, "C2", "A2", "کالای ب", 1, "لبنیات"),
        ],
        columns=[*_COLS, "دسته"],
    )
    mapping = {**_MAPPING, ColumnRole.CATEGORY: "دسته"}
    clean = clean_frame(SchemaMapper().apply(raw, mapping))
    write_import(clean, kpis=compute_kpis(clean), db_path=db)

    import_costs([{"product": "کالای الف", "cost": 400}], db_path=db)
    apply_costs(db_path=db)

    with session_scope(db) as session:
        business_id = session.scalar(select(Business.id))
        lookup = margin_lookup(session, business_id)

    assert lookup["کالای الف"] == 6_000
    assert "لبنیات" not in lookup, "دسته‌ای که یک کالایش بها ندارد، حاشیه‌ی معتبر ندارد"


# ═══════════════════════════════════ کف حاشیه — تصمیمِ کاربر
def test_margin_floor_is_unset_until_the_user_sets_it(tmp_path):
    db = tmp_path / "app.db"
    _basic(db)
    with session_scope(db) as session:
        business_id = session.scalar(select(Business.id))
        assert margin_floor_bp(session, business_id) is None

    set_margin_floor_bp(2_000, db_path=db)
    with session_scope(db) as session:
        business_id = session.scalar(select(Business.id))
        assert margin_floor_bp(session, business_id) == 2_000

    set_margin_floor_bp(None, db_path=db)
    with session_scope(db) as session:
        business_id = session.scalar(select(Business.id))
        assert margin_floor_bp(session, business_id) is None, (
            "برداشتنِ کف باید به «تعیین‌نشده» برگردد، نه به صفر"
        )


def test_margin_floor_rejects_impossible_values(tmp_path):
    db = tmp_path / "app.db"
    _basic(db)
    with pytest.raises(ValueError):
        set_margin_floor_bp(10_001, db_path=db)


def test_margin_filter_blocks_only_after_the_user_sets_a_floor(tmp_path):
    """همان قاعده‌ی همیشگی: نبودِ تصمیمِ کاربر، «قبول» نیست — «بررسی نشد» است."""
    candidate = OpportunityCandidate(
        kind="cross_sell", generator="آزمون", generator_version=1,
        customer_key="C1", title_fa="پیشنهاد", action_fa="اقدام", reason_fa="دلیل",
        expected_value_display=100.0, value_kind="revenue",
        product_name="کالای کم‌حاشیه",
    )
    margins = {"کالای کم‌حاشیه": 500}

    note = filter_margin_floor(candidate, {
        "has_cost_data": True, "margin_floor_bp": None, "margin_by_product": margins,
    })
    assert note.outcome == "filter_skip"

    note = filter_margin_floor(candidate, {
        "has_cost_data": True, "margin_floor_bp": 2_000, "margin_by_product": margins,
    })
    assert note.outcome == "filter_block"
