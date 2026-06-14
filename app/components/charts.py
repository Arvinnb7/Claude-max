"""نمودارهای Plotly با برچسب فارسی و چیدمان RTL."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

_FONT = dict(family="Vazirmatn, Tahoma, sans-serif")


def _rtl(fig: go.Figure) -> go.Figure:
    fig.update_layout(font=_FONT, legend=dict(font=_FONT), margin=dict(t=40, r=20, l=20, b=30))
    return fig


def revenue_trend(daily: pd.Series, ma30: pd.Series) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=daily.index, y=daily.values, name="درآمد روزانه",
                             line=dict(color="#a0aec0", width=1)))
    fig.add_trace(go.Scatter(x=ma30.index, y=ma30.values, name="میانگین متحرک ۳۰ روزه",
                             line=dict(color="#2b6cb0", width=3)))
    fig.update_layout(title="روند درآمد", xaxis_title="تاریخ", yaxis_title="درآمد")
    return _rtl(fig)


def monthly_bar(monthly: pd.Series) -> go.Figure:
    fig = px.bar(x=[str(d.date()) for d in monthly.index], y=monthly.values,
                 labels={"x": "ماه", "y": "درآمد"}, title="درآمد ماهانه")
    fig.update_traces(marker_color="#2b6cb0")
    return _rtl(fig)


def breakdown_bar(df: pd.DataFrame, title: str) -> go.Figure:
    label_col = df.columns[0]
    fig = px.bar(df, x="revenue", y=label_col, orientation="h",
                 labels={"revenue": "درآمد", label_col: ""}, title=title)
    fig.update_traces(marker_color="#3182ce")
    fig.update_layout(yaxis=dict(autorange="reversed"))
    return _rtl(fig)


def segment_treemap(sizes: dict[str, int], revenue: dict[str, float]) -> go.Figure:
    labels = list(sizes.keys())
    fig = px.treemap(
        names=labels,
        parents=[""] * len(labels),
        values=[revenue.get(k, 0) for k in labels],
        title="سهم درآمد سگمنت‌های مشتری",
    )
    return _rtl(fig)


def forecast_chart(history: pd.Series, yhat: pd.Series, lower: pd.Series, upper: pd.Series) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=history.index, y=history.values, name="تاریخی",
                             line=dict(color="#2b6cb0")))
    fig.add_trace(go.Scatter(x=upper.index, y=upper.values, name="سقف اطمینان",
                             line=dict(width=0), showlegend=False))
    fig.add_trace(go.Scatter(x=lower.index, y=lower.values, name="بازه‌ی اطمینان",
                             fill="tonexty", fillcolor="rgba(43,108,176,0.2)",
                             line=dict(width=0)))
    fig.add_trace(go.Scatter(x=yhat.index, y=yhat.values, name="پیش‌بینی",
                             line=dict(color="#dd6b20", dash="dash", width=3)))
    fig.update_layout(title="پیش‌بینی فروش", xaxis_title="تاریخ", yaxis_title="درآمد")
    return _rtl(fig)


def pareto_chart(df: pd.DataFrame, title: str) -> go.Figure:
    label_col = df.columns[0]
    fig = go.Figure()
    fig.add_trace(go.Bar(x=df[label_col].astype(str), y=df["revenue"], name="درآمد",
                         marker_color="#3182ce"))
    fig.add_trace(go.Scatter(x=df[label_col].astype(str), y=df["cumulative_share"] * 100,
                             name="سهم تجمعی (٪)", yaxis="y2", line=dict(color="#dd6b20")))
    fig.update_layout(
        title=title,
        yaxis=dict(title="درآمد"),
        yaxis2=dict(title="سهم تجمعی ٪", overlaying="y", side="left", range=[0, 100]),
    )
    return _rtl(fig)
