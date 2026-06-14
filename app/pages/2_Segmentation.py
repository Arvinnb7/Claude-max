"""صفحه‌ی سگمنت‌بندی مشتریان و تفکیک ابعاد."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from components import charts  # noqa: E402
from components.rtl import page_setup  # noqa: E402
from components.state import get_bundle  # noqa: E402
from mktcore.ingest.schema import ColumnRole  # noqa: E402

page_setup("سگمنت‌بندی", "👥")
st.title("👥 سگمنت‌بندی مشتریان و تحلیل ابعاد")

bundle = get_bundle()
seg = bundle.segmentation

if seg.segment_sizes:
    st.subheader("سگمنت‌بندی RFM مشتریان")
    col1, col2 = st.columns([1, 1])
    with col1:
        import pandas as pd

        tbl = pd.DataFrame(
            {
                "سگمنت": list(seg.segment_sizes.keys()),
                "تعداد مشتری": list(seg.segment_sizes.values()),
                "درآمد": [round(seg.segment_revenue.get(k, 0)) for k in seg.segment_sizes],
            }
        ).sort_values("درآمد", ascending=False)
        st.dataframe(tbl, use_container_width=True, hide_index=True)
    with col2:
        st.plotly_chart(charts.segment_treemap(seg.segment_sizes, seg.segment_revenue),
                        use_container_width=True)
else:
    st.info("ستون مشتری در داده موجود نیست؛ سگمنت‌بندی RFM در دسترس نیست.")

st.divider()
st.subheader("تفکیک درآمد بر اساس ابعاد")

if seg.breakdowns:
    dim_labels = {ColumnRole.PRODUCT.value: "محصول", ColumnRole.CATEGORY.value: "دسته‌بندی",
                  ColumnRole.CHANNEL.value: "کانال فروش", ColumnRole.REGION.value: "منطقه"}
    available = list(seg.breakdowns.keys())
    chosen = st.selectbox("بُعد:", available, format_func=lambda x: dim_labels.get(x, x))
    table = seg.breakdowns[chosen]
    c1, c2 = st.columns(2)
    with c1:
        st.plotly_chart(charts.breakdown_bar(table, f"درآمد بر اساس {dim_labels.get(chosen, chosen)}"),
                        use_container_width=True)
    with c2:
        st.plotly_chart(charts.pareto_chart(table, "نمودار پارتو"), use_container_width=True)
    st.dataframe(table, use_container_width=True, hide_index=True)
else:
    st.info("ابعاد تفکیک (محصول/کانال/منطقه) در داده موجود نیست.")
