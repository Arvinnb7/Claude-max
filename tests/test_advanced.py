"""تست ماژول‌های پیشرفته: محصولات، سبد، توالی، خرید بعدی، عملکرد، تأمین، تشخیص، تخصیص، pacing."""

from __future__ import annotations

from mktcore.ingest.cleaning import clean_frame
from mktcore.ingest.mapper import SchemaMapper
from mktcore.pipeline import run_analysis


def _bundle(raw, **kw):
    mapper = SchemaMapper()
    std = mapper.apply(raw, mapper.auto_detect(raw).mapping)
    return run_analysis(clean_frame(std), **kw)


def test_salesperson_branch_mapping(raw_sales):
    from mktcore.ingest.schema import ColumnRole

    sugg = SchemaMapper().auto_detect(raw_sales)
    assert sugg.mapping[ColumnRole.SALESPERSON] == "فروشنده"
    assert sugg.mapping[ColumnRole.BRANCH] == "شعبه"
    assert sugg.mapping[ColumnRole.PHONE] == "شماره موبایل"
    # تاریخ و درآمد نباید با موبایل اشتباه شوند
    assert sugg.mapping[ColumnRole.REVENUE] == "مبلغ کل"


def test_products_and_abc(raw_sales):
    b = _bundle(raw_sales, with_forecast=False)
    assert b.products.available
    classes = {p.abc_class for p in b.products.products}
    assert classes <= {"A", "B", "C"}
    # مجموع سهم‌ها ~ ۱
    assert abs(sum(p.share for p in b.products.products) - 1.0) < 0.01


def test_market_basket_finds_complement(raw_sales):
    b = _bundle(raw_sales, with_forecast=False)
    assert b.basket.available
    # الگوی تزریق‌شده: کلاسیک → لایت باید با lift بالا کشف شود
    comps = b.basket.complements_for("کلاسیک", n=5)
    assert any(r.consequent == "لایت" and r.lift > 1.0 for r in comps)


def test_sequence_pattern_pro_to_special(raw_sales):
    b = _bundle(raw_sales, with_forecast=False)
    assert b.sequences.available
    # الگوی تزریق‌شده: پرو → ویژه
    pats = {(p.antecedent, p.consequent): p for p in b.sequences.patterns}
    assert ("پرو", "ویژه") in pats
    pat = pats[("پرو", "ویژه")]
    assert pat.completion_rate > 0.2
    assert isinstance(pat.incomplete_customers, list)


def test_next_purchase(raw_sales):
    b = _bundle(raw_sales, with_forecast=False)
    assert b.next_purchase.available
    due = b.next_purchase.due_now()
    # ساختار خروجی
    if due:
        assert due[0].status in ("سررسیدشده", "نزدیک")
        assert isinstance(due[0].likely_products, list)


def test_performance_by_entity(raw_sales):
    b = _bundle(raw_sales, with_forecast=False)
    assert b.performance.has_branch
    assert b.performance.has_salesperson
    # رتبه‌ها از ۱ شروع و سهم‌ها مرتب نزولی
    branches = b.performance.by_branch
    assert branches[0].rank == 1
    assert branches[0].revenue >= branches[-1].revenue


def test_inventory_advice(raw_sales):
    b = _bundle(raw_sales, with_forecast=False)
    assert b.inventory.available
    recs = {i.recommendation for i in b.inventory.items}
    valid = {"افزایش تأمین", "حفظ تأمین", "کاهش تأمین", "قطع تأمین"}
    assert recs <= valid


def test_diagnostics(raw_sales):
    b = _bundle(raw_sales, with_forecast=False)
    # گزارش تشخیص باید دوره داشته باشد
    assert b.diagnostics.period_label != ""


def test_target_allocation_and_pacing(raw_sales):
    b = _bundle(raw_sales, horizon=6)
    assert b.branch_targets is not None
    assert b.salesperson_targets is not None
    # مجموع تخصیص ~ تارگت کل
    alloc_sum = sum(e.target for e in b.branch_targets.entities)
    assert abs(alloc_sum - b.branch_targets.total_target) / b.branch_targets.total_target < 0.02
    # هر واحد پله‌ی پاداش دارد
    assert all(e.reward_tiers for e in b.branch_targets.entities)
    # pacing
    assert b.pacing is not None
    assert b.pacing.monthly_target > 0
    assert b.pacing.days_remaining >= 0
