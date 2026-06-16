"""تست چرخه‌ی خرید، تشخیص مصرفی/تک‌خریدی، اعلان‌ها و هدف‌گیری تک‌خریدی."""

from __future__ import annotations

from mktcore.analysis.purchase_cycle import CONSUMABLE, ONE_TIME
from mktcore.execution import build_audience, render_messages, send_campaign
from mktcore.ingest.cleaning import clean_frame
from mktcore.ingest.mapper import SchemaMapper
from mktcore.pipeline import run_analysis


def _bundle_df(raw):
    mapper = SchemaMapper()
    std = mapper.apply(raw, mapper.auto_detect(raw).mapping)
    clean = clean_frame(std)
    return run_analysis(clean, with_forecast=False), clean


def test_product_cycles_and_types(raw_sales):
    bundle, _ = _bundle_df(raw_sales)
    pc = bundle.purchase_cycle
    assert pc.available
    types = {c.product: c.product_type for c in pc.product_cycles}
    # «باکس حمل» تک‌خریدی است (هر مشتری یک‌بار)
    assert types.get("باکس حمل") == ONE_TIME
    # دست‌کم یک کالای مصرفی شناسایی شود
    assert any(t == CONSUMABLE for t in types.values())
    # کالاهای مصرفی چرخه‌ی روز دارند
    for c in pc.consumables():
        assert c.median_cycle_days and c.median_cycle_days > 0


def test_cycle_notifications(raw_sales):
    bundle, _ = _bundle_df(raw_sales)
    overdue = bundle.purchase_cycle.overdue()
    # ساختار اعلان
    if overdue:
        n = overdue[0]
        assert n.status in ("عقب‌افتاده", "نزدیک")
        assert "چرخه" in n.message()


def test_onetime_targets_exclude_buyers(raw_sales):
    bundle, df = _bundle_df(raw_sales)
    targets = bundle.purchase_cycle.onetime_targets
    assert targets
    box = next((t for t in targets if t.product == "باکس حمل"), None)
    assert box is not None
    # بالقوه‌ها نباید جزو خریداران فعلی باشند
    buyers = set(df[df["product"] == "باکس حمل"]["customer_id"].astype(str))
    assert not (set(box.potential_customers) & buyers)
    assert box.existing_buyers > 0


def test_new_audience_kinds(raw_sales):
    bundle, df = _bundle_df(raw_sales)
    for kind in ("چرخه_عقب‌افتاده", "تارگت_تک‌خریدی"):
        recips = build_audience(bundle, kind, df=df, limit=30)
        # حداقل ساختار درست برگردد (ممکن است بسته به داده خالی نباشد)
        assert isinstance(recips, list)
    # تارگت تک‌خریدی باید مخاطب داشته باشد
    onetime = build_audience(bundle, "تارگت_تک‌خریدی", df=df, limit=30)
    assert len(onetime) > 0
    msgs = render_messages("سلام {نام}، پیشنهاد {محصول}", onetime)
    res = send_campaign(msgs, dry_run=True)
    assert res.dry_run and res.total == len(msgs)
