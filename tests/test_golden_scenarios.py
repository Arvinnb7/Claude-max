"""سناریوهای طلایی — رفتار سرتاسری روی داده‌ی ساختگیِ با پاسخِ معلوم.

هر سناریو یک وضعیت واقعیِ کسب‌وکار است که پاسخ درستش از قبل معلوم است، پس
شکستِ هرکدام یعنی یک رفتار **تجاری** خراب شده، نه فقط یک assert فنی.

سناریوها عمداً **بی‌دامنه**اند (نه فروشگاه حیوانات، نه هیچ صنعت خاص) و هیچ‌کدام
ستون بهای تمام‌شده ندارند — دقیقاً مثل داده‌ی واقعیِ این نصب.
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
    ImportBatch,
    Opportunity,
    OrderLine,
    Product,
)
from mktcore.db.repo_features import write_customer_features  # noqa: E402
from mktcore.db.repo_import import frame_dataset_key, write_import  # noqa: E402
from mktcore.ingest.cleaning import clean_frame  # noqa: E402
from mktcore.ingest.currency import conversion_factor, convert_monetary_columns  # noqa: E402
from mktcore.ingest.mapper import SchemaMapper  # noqa: E402
from mktcore.ingest.schema import ColumnRole  # noqa: E402
from mktcore.opportunities import run_opportunity_engine  # noqa: E402
from mktcore.opportunities.engine import STATUS_ACCEPTED  # noqa: E402
from mktcore.pipeline import run_analysis  # noqa: E402

_COLS = ["تاریخ", "مبلغ", "تعداد", "مشتری", "فاکتور", "کالا", "موبایل"]
_MAPPING = {
    ColumnRole.DATE: "تاریخ",
    ColumnRole.REVENUE: "مبلغ",
    ColumnRole.QUANTITY: "تعداد",
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


def _clean(rows: list[tuple], columns: list[str] = _COLS, mapping=None) -> pd.DataFrame:
    raw = pd.DataFrame(rows, columns=columns)
    return clean_frame(SchemaMapper().apply(raw, mapping or _MAPPING))


def _ingest(clean: pd.DataFrame, db: Path, **kwargs):
    return write_import(clean, kpis=compute_kpis(clean), db_path=db, **kwargs)


# ------------------------------------------------------ ۱: چرخه‌ی منظم خرید
def test_scenario_regular_buyer_becomes_a_cycle_opportunity(tmp_path):
    """مشتری‌ای که هر ۳۰ روز می‌خرید و حالا ۶۰ روز نیامده باید فرصت بسازد."""
    rows = []
    for i in range(8):  # هر ۳۰ روز، هشت بار
        day = 1 + i * 30
        month, dom = divmod(day - 1, 30)
        rows.append((f"1402/{month + 1:02d}/{dom + 1:02d}", 500_000, 1,
                     "منظم", f"F{i}", "مواد مصرفی", "09121110000"))
    # چند مشتری دیگر تا تحلیل معنادار شود
    for j in range(20):
        rows.append((f"1402/{(j % 10) + 1:02d}/15", 200_000 + j * 1000, 1,
                     f"C{j}", f"G{j}", "مواد مصرفی", ""))

    clean = _clean(rows)
    db = tmp_path / "app.db"
    _ingest(clean, db)
    bundle = run_analysis(clean, horizon=2, with_forecast=False)
    result = run_opportunity_engine(bundle, clean, db_path=db)

    assert result is not None and result.created > 0
    with session_scope(db) as session:
        kinds = {o.kind for o in session.scalars(select(Opportunity)).all()}
    assert kinds, "هیچ فرصتی ساخته نشد"


# ------------------------------------------- ۲: هویت مشتری بین چند بارگذاری
def test_scenario_same_person_across_three_files_is_one_customer(tmp_path):
    """همان فرد با سه نگارش شماره و سه کد مشتری متفاوت → یک پرونده."""
    db = tmp_path / "app.db"
    files = [
        [("1402/01/10", 300_000, 1, "کد-الف", "F1", "کالای الف", "09121110000")],
        [("1402/03/12", 400_000, 1, "کد-ب", "F2", "کالای ب", "۰۹۱۲۱۱۱۰۰۰۰")],
        [("1402/06/14", 500_000, 1, "ALEF", "F3", "کالای ج", "+98 912 111 0000")],
    ]
    for rows in files:
        _ingest(_clean(rows), db)

    with session_scope(db) as session:
        customers = session.scalars(select(Customer)).all()
        assert len(customers) == 1
        person = customers[0]
        lines = session.scalars(
            select(OrderLine).where(OrderLine.customer_id == person.id)
        ).all()
    assert len(lines) == 3
    assert person.phone_e164 == "+989121110000"
    assert person.first_order_date < person.last_order_date


# --------------------------------------------------- ۳: یکسان‌سازی نام کالا
def test_scenario_product_written_five_ways_is_one_product(tmp_path):
    rows = [
        ("1402/01/01", 100_000, 1, "C1", "F1", "روغن موتور ۴ لیتری", ""),
        ("1402/01/02", 100_000, 1, "C2", "F2", "روغن موتور 4 لیتری", ""),
        ("1402/01/03", 100_000, 1, "C3", "F3", "روغن  موتور ۴  لیتری", ""),
        ("1402/01/04", 100_000, 1, "C4", "F4", "روغن‌موتور ۴ لیتری", ""),
        ("1402/01/05", 100_000, 1, "C5", "F5", "روغن موتور ۴ ليتري", ""),
    ]
    db = tmp_path / "app.db"
    _ingest(_clean(rows), db)

    with session_scope(db) as session:
        products = session.scalars(select(Product)).all()
    assert len(products) == 1
    assert products[0].pack_size_milli == 4_000_000  # ۴ لیتر = ۴۰۰۰ میلی‌لیتر
    assert products[0].pack_unit == "ml"


# ----------------------------------------------------- ۴: برگشت‌ها و آشتی
def test_scenario_heavy_returns_reconcile_exactly(tmp_path):
    """یک فایل با برگشت زیاد: دفتر کل باید دقیقاً با KPI بخواند."""
    rows = [(f"1402/0{(i % 9) + 1}/10", 1_000_000, 1, f"C{i % 5}", f"F{i}", "کالا", "")
            for i in range(30)]
    rows += [("1402/05/20", -1_000_000, 1, f"C{j}", f"R{j}", "کالا", "") for j in range(5)]

    clean = _clean(rows)
    kpis = compute_kpis(clean)
    db = tmp_path / "app.db"
    result = _ingest(clean, db)

    assert result.reconcile_status == "RECONCILED"
    assert not [c for c in result.checks if c.status == "MISMATCH"]
    with session_scope(db) as session:
        net = session.scalar(select(func.sum(OrderLine.revenue_rial)))
    assert net == round(kpis.net_sales * 10)
    assert kpis.returns_count == 5


# ------------------------------------ ۵: تحلیل دوباره‌ی همان فایل (idempotent)
def test_scenario_monthly_reupload_does_not_double_count(tmp_path):
    """کاربر همان فایل را دوباره تحلیل می‌کند — جمع‌ها نباید دو برابر شوند."""
    rows = [(f"1402/0{(i % 9) + 1}/05", 250_000, 2, f"C{i % 7}", f"F{i}", "کالا", "")
            for i in range(40)]
    clean = _clean(rows)
    db = tmp_path / "app.db"
    key = frame_dataset_key(clean)

    _ingest(clean, db, dataset_key=key)
    with session_scope(db) as session:
        first = session.scalar(select(func.sum(OrderLine.revenue_rial)))
        lines_1 = session.scalar(select(func.count()).select_from(OrderLine))

    for _ in range(3):  # سه بار دیگر
        _ingest(clean, db, dataset_key=key)

    with session_scope(db) as session:
        assert session.scalar(select(func.sum(OrderLine.revenue_rial))) == first
        assert session.scalar(select(func.count()).select_from(OrderLine)) == lines_1
        batches = session.scalars(select(ImportBatch)).all()
    assert [b.revision for b in batches] == [1, 2, 3, 4]


# ------------------------------------------- ۶: فایل ماهانه‌ی پشت‌سرهم (رشد)
def test_scenario_two_months_accumulate_not_replace(tmp_path):
    """فایل ماه دوم باید به دفتر **اضافه** شود، نه جایگزین ماه اول."""
    db = tmp_path / "app.db"
    month1 = [(f"1402/01/{d:02d}", 100_000, 1, f"C{d}", f"A{d}", "کالا", "")
              for d in range(1, 16)]
    month2 = [(f"1402/02/{d:02d}", 100_000, 1, f"C{d}", f"B{d}", "کالا", "")
              for d in range(1, 16)]

    _ingest(_clean(month1), db)
    _ingest(_clean(month2), db)

    with session_scope(db) as session:
        assert session.scalar(select(func.count()).select_from(OrderLine)) == 30
        assert session.scalar(select(func.count()).select_from(Customer)) == 15
        total = session.scalar(select(func.sum(OrderLine.revenue_rial)))
    assert total == 30 * 100_000 * 10


# ---------------------------------------------- ۷: فایل بدون شماره‌ی فاکتور
def test_scenario_no_invoice_column_still_produces_a_ledger(tmp_path):
    cols = ["تاریخ", "مبلغ", "مشتری", "کالا"]
    mapping = {ColumnRole.DATE: "تاریخ", ColumnRole.REVENUE: "مبلغ",
               ColumnRole.CUSTOMER_ID: "مشتری", ColumnRole.PRODUCT: "کالا"}
    rows = [(f"1402/0{(i % 9) + 1}/0{(i % 9) + 1}", 120_000, f"C{i % 6}", "کالا")
            for i in range(25)]
    clean = _clean(rows, cols, mapping)
    db = tmp_path / "app.db"
    result = _ingest(clean, db)

    assert result.orders_written == 0  # فاکتور جعلی ساخته نمی‌شود
    with session_scope(db) as session:
        assert session.scalar(select(func.count()).select_from(OrderLine)) == len(clean)
        assert session.scalar(select(func.count()).select_from(Customer)) == 6


# ------------------------------------- ۸: تخفیف مبلغی با واحد پول متفاوت
def test_scenario_amount_discount_with_currency_switch(tmp_path):
    """فایل ریالی، نمایش تومانی، تخفیف مبلغی — همه‌چیز باید هم‌واحد بماند."""
    cols = ["تاریخ", "مبلغ", "تعداد", "قیمت واحد", "تخفیف", "مشتری", "فاکتور"]
    mapping = {ColumnRole.DATE: "تاریخ", ColumnRole.REVENUE: "مبلغ",
               ColumnRole.QUANTITY: "تعداد", ColumnRole.UNIT_PRICE: "قیمت واحد",
               ColumnRole.DISCOUNT: "تخفیف", ColumnRole.CUSTOMER_ID: "مشتری",
               ColumnRole.ORDER_ID: "فاکتور"}
    rows = [(f"1402/01/{d:02d}", "", 2, 100_000, 20_000, f"C{d}", f"F{d}")
            for d in range(1, 13)]
    clean = _clean(rows, cols, mapping)
    assert clean.attrs["discount_is_amount"] is True

    converted = convert_monetary_columns(clean, conversion_factor("ریال", "تومان"))
    kpis = compute_kpis(converted)
    # درآمد هر خط: ۲×۱۰۰۰۰۰ − ۲۰۰۰۰ = ۱۸۰۰۰۰ ریال = ۱۸۰۰۰ تومان
    assert kpis.gross_sales == pytest.approx(18_000 * 12)
    # و تخفیف هم در همان واحد است (باگ ۱۰ برابری رفع‌شده)
    assert kpis.discount_total == pytest.approx(2_000 * 12)

    db = tmp_path / "app.db"
    _ingest(converted, db, display_currency="تومان", file_currency="ریال")
    with session_scope(db) as session:
        line = session.scalars(select(OrderLine)).first()
        total = session.scalar(select(func.sum(OrderLine.revenue_rial)))
    assert line.discount_rial == 20_000     # برگشته به ریال
    assert line.discount_rate_bp is None    # تخفیف مبلغی است، نه نسبتی
    assert total == 180_000 * 12


# ------------------------------------------------ ۹: ردیف‌های خراب و حسابرسی
def test_scenario_broken_rows_are_accounted_for(tmp_path):
    """ردیف بی‌تاریخ/بی‌مبلغ/تکراری باید شمرده شود، نه بی‌صدا ناپدید."""
    rows = [(f"1402/01/{d:02d}", 100_000, 1, f"C{d}", f"F{d}", "کالا", "")
            for d in range(1, 21)]
    rows += [("", 100_000, 1, "CX", "FX", "کالا", "")]          # بدون تاریخ
    rows += [("1402/01/05", "", 1, "CY", "FY", "کالا", "")]      # بدون مبلغ
    rows += [rows[0], rows[0]]                                   # تکراری

    clean = _clean(rows)
    db = tmp_path / "app.db"
    result = _ingest(clean, db)

    with session_scope(db) as session:
        batch = session.get(ImportBatch, result.batch_id)
    assert batch.rows_invalid >= 2
    assert batch.rows_duplicate >= 2
    # حسابرسی ردیف: هیچ ردیفی گم نشده است
    assert batch.rows_total == (
        batch.rows_clean + batch.rows_invalid + batch.rows_duplicate + batch.rows_returns
    )


# ----------------------------------------- ۱۰: تصمیم انسان و تحلیل مجدد
def test_scenario_accepted_opportunity_survives_next_month_analysis(tmp_path):
    rows = [(f"1402/0{(i % 9) + 1}/10", 400_000, 1, f"C{i % 8}", f"F{i}", "کالا", "")
            for i in range(40)]
    clean = _clean(rows)
    db = tmp_path / "app.db"
    _ingest(clean, db)
    bundle = run_analysis(clean, horizon=2, with_forecast=False)
    run_opportunity_engine(bundle, clean, db_path=db)

    with session_scope(db) as session:
        first = session.scalars(select(Opportunity)).first()
        if first is None:
            pytest.skip("این داده فرصتی تولید نکرد")
        first.status = STATUS_ACCEPTED
        first.assigned_to = "تیم فروش"
        target = first.id

    run_opportunity_engine(bundle, clean, db_path=db)
    with session_scope(db) as session:
        after = session.get(Opportunity, target)
    assert after.status == STATUS_ACCEPTED
    assert after.assigned_to == "تیم فروش"


# ------------------------------------------------ ۱۱: نبود بهای تمام‌شده
def test_scenario_no_cost_column_leaves_cost_null(tmp_path):
    rows = [(f"1402/01/{d:02d}", 100_000, 1, f"C{d}", f"F{d}", "کالا", "")
            for d in range(1, 16)]
    db = tmp_path / "app.db"
    _ingest(_clean(rows), db)

    with session_scope(db) as session:
        with_cost = session.scalar(
            select(func.count()).select_from(OrderLine)
            .where(OrderLine.cost_rial.isnot(None))
        )
        products = session.scalars(select(Product)).all()
    assert with_cost == 0
    assert all(p.last_unit_cost_rial is None for p in products)


# ----------------------------------------------- ۱۲: عکس ویژگی مشتری
def test_scenario_customer_features_snapshot_matches_the_data(tmp_path):
    """جمع خرید در پرونده‌ی مشتری باید دقیقاً با خطوط همان مشتری بخواند."""
    rows = [
        ("1402/01/10", 300_000, 1, "پرخرید", "F1", "کالای الف", ""),
        ("1402/02/10", 700_000, 1, "پرخرید", "F2", "کالای الف", ""),
        ("1402/03/10", 200_000, 1, "کم‌خرید", "F3", "کالای ب", ""),
    ]
    for i in range(12):  # پس‌زمینه تا تحلیل معنادار شود
        rows.append((f"1402/0{(i % 9) + 1}/20", 150_000, 1, f"C{i}", f"G{i}", "کالای ج", ""))

    clean = _clean(rows)
    db = tmp_path / "app.db"
    _ingest(clean, db)
    bundle = run_analysis(clean, horizon=2, with_forecast=False)
    written = write_customer_features(clean, bundle, db_path=db)
    assert written > 0

    with session_scope(db) as session:
        customer = session.scalar(select(Customer).where(Customer.canonical_key == "پرخرید"))
        feature = session.scalar(
            select(CustomerFeature).where(CustomerFeature.customer_id == customer.id)
        )
    assert feature.n_orders == 2
    assert feature.monetary_rial == 1_000_000 * 10
    assert feature.aov_rial == 500_000 * 10
    assert feature.top_product == "کالای الف"


# ---------------------------- ۱۳: هویتِ ادغام‌شده، پرونده‌ی جمع‌شده
def test_scenario_merged_identity_gets_one_combined_feature_row(tmp_path):
    """دو کد مشتری با یک شماره → یک پرونده با جمعِ خرید هر دو.

    این حالت دقیقاً نتیجه‌ی مطلوب حل هویت است؛ اگر جمع‌بندی نشود، نوشتن ویژگی
    به قید یکتایی می‌خورد و کل عکس‌برداری از دست می‌رود.
    """
    rows = [
        ("1402/01/10", 600_000, 1, "کد-قدیم", "F1", "کالای الف", "09125550000"),
        ("1402/02/10", 400_000, 1, "کد-جدید", "F2", "کالای ب", "۰۹۱۲۵۵۵۰۰۰۰"),
    ]
    for i in range(12):
        rows.append((f"1402/0{(i % 9) + 1}/20", 100_000, 1, f"C{i}", f"G{i}", "کالای ج", ""))

    clean = _clean(rows)
    db = tmp_path / "app.db"
    _ingest(clean, db)
    bundle = run_analysis(clean, horizon=2, with_forecast=False)
    write_customer_features(clean, bundle, db_path=db)

    with session_scope(db) as session:
        merged = session.scalar(
            select(Customer).where(Customer.phone_e164 == "+989125550000")
        )
        features = session.scalars(
            select(CustomerFeature).where(CustomerFeature.customer_id == merged.id)
        ).all()

    assert len(features) == 1                       # نه دو ردیف، نه صفر
    assert features[0].n_orders == 2                # جمع هر دو کلید
    assert features[0].monetary_rial == 1_000_000 * 10
    assert features[0].top_product == "کالای الف"   # کلید غالب (خرید بیشتر)


def test_scenario_opportunities_attach_to_merged_identity(tmp_path):
    """فرصتِ کلیدِ دوم هم باید به همان مشتریِ ادغام‌شده وصل شود، نه بی‌صاحب بماند."""
    rows = []
    for i in range(8):  # چرخه‌ی منظم، با دو کد مشتریِ متفاوت ولی یک شماره
        day = 1 + i * 30
        month, dom = divmod(day - 1, 30)
        key = "کد-قدیم" if i < 4 else "کد-جدید"
        rows.append((f"1402/{month + 1:02d}/{dom + 1:02d}", 500_000, 1,
                     key, f"F{i}", "مواد مصرفی", "09126660000"))
    for j in range(20):
        rows.append((f"1402/{(j % 10) + 1:02d}/15", 200_000, 1,
                     f"C{j}", f"G{j}", "مواد مصرفی", ""))

    clean = _clean(rows)
    db = tmp_path / "app.db"
    _ingest(clean, db)
    bundle = run_analysis(clean, horizon=2, with_forecast=False)
    run_opportunity_engine(bundle, clean, db_path=db)

    with session_scope(db) as session:
        merged = session.scalar(
            select(Customer).where(Customer.phone_e164 == "+989126660000")
        )
        assert merged is not None
        orphans = session.scalar(
            select(func.count()).select_from(Opportunity)
            .where(Opportunity.customer_id.is_(None))
        )
    # هیچ فرصتی بدون مشتری نمی‌ماند — یعنی جستجو از راه customer_keys کار می‌کند
    assert orphans == 0


def test_scenario_identity_merge_is_not_reported_as_a_mismatch(tmp_path):
    """ادغام هویت نتیجه‌ی مطلوب است؛ نباید مثل خطای آشتی گزارش شود."""
    rows = [
        ("1402/01/10", 300_000, 1, "کد-الف", "F1", "کالا", "09127770000"),
        ("1402/02/10", 300_000, 1, "کد-ب", "F2", "کالا", "۰۹۱۲۷۷۷۰۰۰۰"),
        ("1402/03/10", 300_000, 1, "دیگری", "F3", "کالا", "09128880000"),
    ]
    clean = _clean(rows)
    db = tmp_path / "app.db"
    result = _ingest(clean, db)

    customer_check = next(c for c in result.checks if c.check_id == "L06")
    assert customer_check.expected == 3      # تحلیل سه کلید خام دید
    assert customer_check.actual == 2        # دفتر دو نفر شناخت
    assert customer_check.status == "OK"     # نه MISMATCH
    assert "ادغام هویت" in customer_check.detail_fa
    assert result.reconcile_status == "RECONCILED"
