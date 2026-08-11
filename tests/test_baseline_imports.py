"""تله‌ی رگرسیون: عکس‌برداری از رفتار امروزِ ورود داده و تحلیل.

این تست‌ها **پیش از** ارتقای Revenue Intelligence نوشته شده‌اند و باید در تمام
مراحل ارتقا سبز بمانند. هر شکستی یعنی ارتقا رفتار موجود را تغییر داده است.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from mktcore.analysis.actions import build_action_list  # noqa: E402
from mktcore.ingest.cleaning import (  # noqa: E402
    clean_frame,
    get_exclusions,
    get_returns,
)
from mktcore.ingest.currency import conversion_factor, convert_monetary_columns  # noqa: E402
from mktcore.ingest.mapper import SchemaMapper  # noqa: E402
from mktcore.ingest.profiler import profile_frame  # noqa: E402
from mktcore.ingest.schema import ColumnRole  # noqa: E402
from mktcore.pipeline import run_analysis  # noqa: E402
from mktcore.synthetic import generate_synthetic_sales  # noqa: E402


def _clean_sample(rows: int | None = None) -> pd.DataFrame:
    raw = generate_synthetic_sales(seed=7, days=540)
    if rows:
        raw = raw.head(rows)
    m = SchemaMapper()
    return clean_frame(m.apply(raw, m.auto_detect(raw).mapping))


# ---------------------------------------------------- ورود داده و پاک‌سازی
def test_baseline_clean_frame_shape_and_columns():
    """ستون‌های استاندارد و ستون فنی provenance باید ثابت بمانند."""
    clean = _clean_sample()
    for col in ("date", "revenue", "quantity", "unit_price", "product",
                "customer_id", "order_id", "source_row"):
        assert col in clean.columns, col
    # فریم بر اساس تاریخ مرتب می‌شود، پس source_row صعودی نیست — ولی یکتاست
    assert clean["source_row"].is_unique
    assert clean["revenue"].dtype.kind == "f"  # تحلیل روی float است
    assert (clean["revenue"] > 0).all()  # برگشت‌ها جدا شده‌اند


def test_baseline_attrs_contract():
    """کلیدهای attrs که لایه‌های بالادست به آن‌ها تکیه می‌کنند."""
    clean = _clean_sample()
    for key in ("sign_flipped", "dropped_invalid_rows", "dropped_duplicate_rows",
                "exclusions_df", "returns_df", "n_returns", "returns_total",
                "validation", "discount_is_amount"):
        assert key in clean.attrs, key
    assert isinstance(get_exclusions(clean), pd.DataFrame)
    assert isinstance(get_returns(clean), pd.DataFrame)


def test_baseline_row_accounting_adds_up():
    """ردیف‌های خام = تمیز + حذفی + برگشتی (بدون ردیف گم‌شده)."""
    raw = generate_synthetic_sales(seed=7, days=540)
    m = SchemaMapper()
    std = m.apply(raw, m.auto_detect(raw).mapping)
    clean = clean_frame(std)
    accounted = (len(clean) + clean.attrs["dropped_invalid_rows"]
                 + clean.attrs["dropped_duplicate_rows"] + clean.attrs["n_returns"])
    assert accounted == len(std)


def test_baseline_profiler_report():
    clean = _clean_sample()
    rep = profile_frame(clean)
    assert rep.n_rows == len(clean)
    assert rep.date_min and rep.date_max
    assert isinstance(rep.warnings, list)


# ------------------------------------------------------------- واحد پول
def test_baseline_currency_conversion_scales_revenue():
    """تبدیل ریال→تومان باید درآمد را ۰.۱ کند و quantity را دست نزند."""
    clean = _clean_sample(2000)
    before_rev = float(clean["revenue"].sum())
    before_qty = float(clean["quantity"].sum())
    out = convert_monetary_columns(clean, conversion_factor("ریال", "تومان"))
    assert abs(float(out["revenue"].sum()) - before_rev * 0.1) < 1e-6 * before_rev
    assert float(out["quantity"].sum()) == before_qty


# --------------------------------------------------------- تحلیل و KPI
def test_baseline_kpi_identities():
    """اتحادهای KPI که هر ارتقایی باید حفظ کند."""
    clean = _clean_sample()
    b = run_analysis(clean, horizon=3, with_forecast=False)
    k = b.kpis
    assert k.total_revenue == k.net_sales
    assert abs(k.net_sales - (k.gross_sales - k.returns_total)) < 1e-6
    assert k.n_customers == clean["customer_id"].nunique()
    assert k.n_orders > 0
    assert abs(k.aov * k.n_orders - k.net_sales) < 1.0
    assert 0 <= (k.repeat_rate or 0) <= 1


def test_baseline_pipeline_sections_available():
    """بخش‌هایی که امروز روی داده‌ی نمونه در دسترس‌اند."""
    clean = _clean_sample()
    b = run_analysis(clean, horizon=3, with_forecast=False)
    assert b.products.available
    assert b.basket.available
    assert b.purchase_cycle.available
    assert b.next_purchase.available
    assert b.performance.has_branch and b.performance.has_salesperson
    assert b.inventory.available
    assert b.actions.available
    assert b.validation is not None
    assert b.validation.status in ("PASS", "PASS_WITH_WARNINGS", "FAIL")


def test_baseline_action_list_invariants():
    """فهرست اقدام: ارزش نزولی، یک اقدام به‌ازای مشتری، ارزش‌ها مثبت."""
    clean = _clean_sample()
    b = run_analysis(clean, horizon=3, with_forecast=False)
    ap = b.actions
    values = [a.value_rial for a in ap.actions]
    assert values == sorted(values, reverse=True)
    assert all(v > 0 for v in values)
    assert len({a.customer_id for a in ap.actions}) == len(ap.actions)
    assert abs(ap.total_value - sum(values)) < 1e-6
    # ارزش‌ها از قبل در احتمال ضرب شده‌اند → دوباره ضرب نشود
    assert ap.total_value > 0


def test_baseline_wider_action_list_is_superset():
    """موتور فرصت‌ها با cap بازتر باید ابرمجموعه‌ی همان محاسبه بدهد."""
    clean = _clean_sample()
    b = run_analysis(clean, horizon=3, with_forecast=False)
    wide = build_action_list(b, clean, per_customer_cap=3, limit=5000)
    assert len(wide.actions) >= len(b.actions.actions)
    narrow_keys = {(a.customer_id, a.kind) for a in b.actions.actions}
    wide_keys = {(a.customer_id, a.kind) for a in wide.actions}
    assert narrow_keys <= wide_keys


def test_baseline_returns_are_netted_not_dropped():
    rows = [(f"1402/{(i % 11) + 1:02d}/{(i % 27) + 1:02d}", 1000 + i,
             f"C{i % 20}", f"F{i}", "P") for i in range(150)]
    rows += [("1402/06/10", -(500 + j), f"C{j}", f"R{j}", "P") for j in range(8)]
    raw = pd.DataFrame(rows, columns=["تاریخ", "مبلغ", "مشتری", "فاکتور", "کالا"])
    m = SchemaMapper()
    mapping = {ColumnRole.DATE: "تاریخ", ColumnRole.REVENUE: "مبلغ",
               ColumnRole.CUSTOMER_ID: "مشتری", ColumnRole.ORDER_ID: "فاکتور",
               ColumnRole.PRODUCT: "کالا"}
    clean = clean_frame(m.apply(raw, mapping))
    b = run_analysis(clean, with_forecast=False)
    assert b.kpis.returns_count == 8
    assert b.kpis.net_sales < b.kpis.gross_sales
    assert len(clean) == 150
