"""صفحه‌ی خانه: بارگذاری داده، انتخاب شیت، نگاشت ستون‌ها، پاک‌سازی و پروفایل."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

# افزودن src به مسیر تا mktcore بدون نصب هم در دسترس باشد
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))

from components.rtl import page_setup  # noqa: E402
from components.state import set_value  # noqa: E402
from mktcore.connectors import ExcelCsvConnector  # noqa: E402
from mktcore.ingest.cleaning import clean_frame  # noqa: E402
from mktcore.ingest.mapper import SchemaMapper  # noqa: E402
from mktcore.ingest.profiler import profile_frame  # noqa: E402
from mktcore.ingest.schema import REQUIRED_ROLES, ColumnRole  # noqa: E402
from mktcore.locale_fa import ROLE_LABELS_FA  # noqa: E402
from mktcore.synthetic import generate_synthetic_sales  # noqa: E402

page_setup("سیستم تحلیل و استراتژی مارکتینگ", "🏠")

st.title("🏠 سیستم اتوماسیون تحلیل داده و استراتژی مارکتینگ")
st.caption("دیتای فروش را بارگذاری کنید تا مثل یک مدیر مارکتینگ سنیور تحلیل، پیش‌بینی، تارگت‌گذاری و استراتژی دریافت کنید.")

# --- انتخاب منبع داده ---
st.subheader("۱) منبع داده")
source = st.radio(
    "منبع داده را انتخاب کنید:",
    ["اکسل / CSV", "داده‌ی نمونه (دمو)", "CRM (به‌زودی)", "دیتابیس/نرم‌افزار فروش (به‌زودی)", "سایت فروشگاهی (به‌زودی)"],
    horizontal=True,
)

raw_df = None

if source == "اکسل / CSV":
    uploaded = st.file_uploader("فایل اکسل یا CSV فروش را بارگذاری کنید", type=["xlsx", "xls", "xlsb", "csv", "txt", "tsv"])
    if uploaded is not None:
        connector = ExcelCsvConnector(content=uploaded.getvalue(), filename=uploaded.name)
        sheets = connector.list_sources()
        sheet = sheets[0]
        if len(sheets) > 1:
            sheet = st.selectbox("شیت موردنظر:", sheets)
        header_row = st.number_input("شماره‌ی ردیف هدر (از ۰):", min_value=0, value=0, step=1)
        raw_df = connector.read(sheet, header_row=int(header_row)).dataframe

elif source == "داده‌ی نمونه (دمو)":
    if st.button("بارگذاری داده‌ی نمونه"):
        set_value("raw_df", generate_synthetic_sales())
    if "raw_df" in st.session_state and st.session_state.get("source_kind") == "demo":
        raw_df = st.session_state["raw_df"]
    elif st.session_state.get("raw_df") is not None and source == "داده‌ی نمونه (دمو)":
        raw_df = st.session_state.get("raw_df")

else:
    st.info("این کانکتور در نسخه‌ی فعلی اسکلت است. فعلاً می‌توانید خروجی CSV/Excel این منبع را بارگذاری کنید.")

# هندل دکمه‌ی داده‌ی نمونه (نگه‌داری در state)
if source == "داده‌ی نمونه (دمو)" and raw_df is not None:
    set_value("source_kind", "demo")

if raw_df is None:
    raw_df = st.session_state.get("_pending_raw")
else:
    set_value("_pending_raw", raw_df)

if raw_df is None:
    st.stop()

st.success(f"داده بارگذاری شد: {len(raw_df):,} ردیف، {raw_df.shape[1]} ستون")
with st.expander("پیش‌نمایش داده‌ی خام"):
    st.dataframe(raw_df.head(20), use_container_width=True)

# --- نگاشت ستون‌ها ---
st.subheader("۲) نگاشت ستون‌ها")
st.caption("سیستم نقش هر ستون را حدس زده است؛ در صورت نیاز اصلاح کنید. حداقل «تاریخ» و «درآمد/مبلغ» لازم است.")

mapper = SchemaMapper()
suggestion = mapper.auto_detect(raw_df)

columns_options = ["—"] + [str(c) for c in raw_df.columns]
mapping_input: dict[ColumnRole, str] = {}

cols = st.columns(3)
for i, role in enumerate(ColumnRole):
    guess = suggestion.mapping.get(role, "—")
    label = ROLE_LABELS_FA.get(role.value, role.value)
    required = role in REQUIRED_ROLES
    with cols[i % 3]:
        chosen = st.selectbox(
            f"{label}{' *' if required else ''}",
            columns_options,
            index=columns_options.index(guess) if guess in columns_options else 0,
            key=f"map_{role.value}",
        )
        if chosen != "—":
            mapping_input[role] = chosen

missing = [ROLE_LABELS_FA[r.value] for r in REQUIRED_ROLES if r not in mapping_input]
if missing:
    st.error(f"نقش‌های ضروری انتخاب نشده‌اند: {', '.join(missing)}")
    st.stop()

# --- پاک‌سازی و پروفایل ---
if st.button("✅ تأیید نگاشت و آماده‌سازی داده", type="primary"):
    std = mapper.apply(raw_df, mapping_input)
    clean = clean_frame(std)
    report = profile_frame(clean)

    set_value("clean_df", clean)
    set_value("data_token", f"{len(clean)}-{clean['revenue'].sum():.0f}")
    set_value("quality_report", report)

    st.success(f"داده آماده شد: {report.n_rows:,} ردیف معتبر.")
    col1, col2, col3 = st.columns(3)
    col1.metric("ردیف معتبر", f"{report.n_rows:,}")
    col2.metric("بازه‌ی زمانی", f"{report.span_days or 0} روز")
    col3.metric("ردیف حذف‌شده", f"{report.dropped_invalid + report.dropped_duplicates:,}")

    if report.warnings:
        with st.expander("نکات کیفیت داده", expanded=True):
            for w in report.warnings:
                st.write("•", w)

    st.info("اکنون از منوی کناری به صفحات «شاخص‌ها»، «پیش‌بینی»، «تارگت» و «استراتژی هوش مصنوعی» بروید.")

if st.session_state.get("clean_df") is not None:
    st.sidebar.success("داده آماده است ✅")
