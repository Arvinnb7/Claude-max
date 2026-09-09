"""مدعیِ یادآورِ تکرارِ خرید: آهنگِ **شخصیِ** جفتِ (مشتری، کالا) روی holdout زمانی (§۱۳.۲–۱۳.۴، §۲۹).

قهرمانِ فعلی (`analysis/purchase_cycle.py`) برای هر کالا یک میانه‌ی جمعیتی می‌سازد و همان
را روی آخرین خریدِ هر مشتری می‌اندازد. این مدعی یک **قاعده** است نه مدلِ خطی: جدولِ
سررسیدی که می‌گوید «با این نسبتِ عقب‌افتادگی و این عدم‌قطعیت، چند درصد از جفت‌ها در
بازه‌ی ادعا واقعاً خریدند» — کالیبره‌شده روی گذشته، نه درصدِ نمایشیِ دلبخواه (§۱۳.۳).

واحدِ سنجش: (مشتری، کالا، تاریخِ عکس). هر طرف برای جفت یک سررسید و یک **بازه‌ی ادعا**
(±۲۵٪ فاصله‌ی خودش — تصمیمِ کاربر) دارد؛ «برد» یعنی مشتری همان کالا را داخلِ همان
بازه خرید. ردیفی شمرده می‌شود که بازه‌ی ادعای **هر دو** طرف تا پایانِ داده پوشیده باشد.
سنجه‌ی اقتصادی: درآمدِ (یا با پوششِ کاملِ بها، سودِ) خریدهای داخلِ بازه در K تای اولِ
رتبه‌بندیِ هر طرف. نامِ کلیدِ سنجه مبنایش را می‌گوید؛ فایلِ واقعی بها ندارد.

مدل به‌صورت JSON در `coefficients_json` می‌نشیند (promote/rollbackِ رجیستری) ولی **هرگز**
از مسیرِ `score_job` (مدلِ خطی، گرینِ مشتری) نمی‌گذرد؛ ستون‌های `replenish_*` NULL می‌مانند.
"""

from __future__ import annotations

import logging
import math
from dataclasses import asdict, dataclass, replace
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

from mktcore.analysis.purchase_cycle import analyze_purchase_cycles
from mktcore.analysis.replenish_personal import LEDGER_COLUMNS, personal_cadence_table
from mktcore.db.engine import session_scope
from mktcore.db.lookup import resolve_business_id
from mktcore.db.migrations import ensure_schema
from mktcore.db.models import ModelRun
from mktcore.features.ledger_frame import load_line_frame
from mktcore.ml.linear_fit import captured, chronological_cut, reliability_bins
from mktcore.ml.registry import compute_data_hash, promoted_run, record_run
from mktcore.ml.train import register_trainer
from mktcore.ml.whale import cost_coverage_of

if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.orm import Session

logger = logging.getLogger("mktcore.ml.replenish")

MODEL_KEY = "replenish"
MODEL_KIND = "replenish_rule"
TABLE_KIND = "replenish_rule_v1"
LABEL_BASIS = "same_product_claimed_window"  # ≤ ۳۲ نویسه (ستونِ label_basis)
BASELINE_NAME_FA = "میانه‌ی جمعیتِ کالا (analyze_purchase_cycles)"
CHAMPION_UNCLAIMED = -1e9


@dataclass(frozen=True)
class ReplenishSpec:
    """پیکربندی؛ همه‌ی اعداد ثبت می‌شوند تا اجرا بازتولیدپذیر بماند."""

    period_days: int = 60
    max_snapshots: int = 12
    # پنجره‌ی نتیجه‌ی آخرین عکس: بازه‌های ادعا باید تا پایانِ داده پوشیده باشند؛ آخرین
    # عکس دست‌کم این‌قدر پیش از پایانِ داده است (بازه‌های بلندتر با `future_covered` حذف می‌شوند)
    tail_days: int = 30
    min_gaps: int = 2
    decay: float = 0.75
    window_fraction: float = 0.25          # ±۲۵٪ فاصله‌ی هر طرف — تصمیمِ کاربر
    info_horizon_days: int = 30            # سنجه‌ی اطلاعی (قابل مقایسه با buy_probability_30d)
    ratio_edges: tuple[float, ...] = (0.0, 0.5, 0.8, 1.0, 1.2, 1.5, 2.0, 3.0)   # آخری تا ∞
    uncertainty_edges: tuple[float, ...] = (0.0, 0.25, 0.5)                     # آخری تا ∞
    min_cell: int = 20
    min_span_days: int = 150
    min_snapshots: int = 3
    min_rows: int = 500
    min_positive_per_arm: int = 50
    train_fraction: float = 0.70
    top_fraction: float = 0.10
    min_topk_lift_bp: int = 200
    bootstrap_samples: int = 400
    bootstrap_quantile: float = 0.05
    max_calibration_bin_error: float = 0.15

    def with_params(self, params: dict[str, Any] | None) -> ReplenishSpec:
        if not params:
            return self
        known = {k: (tuple(v) if isinstance(v, list) else v)
                 for k, v in params.items() if k in asdict(self)}
        return replace(self, **known)


# ───────────────────────────────────────────── عکس‌ها و جدولِ جفت × دوره
def snapshot_dates(lines: pd.DataFrame, spec: ReplenishSpec) -> list[str]:
    """از انتها به عقب؛ آخرین عکس `data_max − tail_days` (همان الگوی `ml/churn.snapshot_dates`)."""
    if lines.empty:
        return []
    stamps = pd.to_datetime(lines["line_date"])
    data_min, data_max = stamps.min(), stamps.max()
    cursor = data_max - pd.Timedelta(days=spec.tail_days)
    out: list[pd.Timestamp] = []
    while len(out) < spec.max_snapshots and cursor > data_min:
        out.append(cursor)
        cursor -= pd.Timedelta(days=spec.period_days)
    return [stamp.date().isoformat() for stamp in sorted(out)]


def _champion_cycles(past: pd.DataFrame) -> dict[int, float]:
    """میانه‌ی کالا از **خودِ** تابعِ تولیدی — نه بازنویسی‌اش (همان قاعده‌ی `churn._baseline_churn_score`)."""
    adapter = pd.DataFrame({
        "date": pd.to_datetime(past["line_date"]),
        "customer_id": past["customer_id"].astype(str),
        "product": past["product_id"].astype(int).astype(str),
    })
    cycles = analyze_purchase_cycles(adapter)
    return {
        int(c.product): float(c.median_cycle_days)
        for c in cycles.consumables() if c.median_cycle_days
    }


def _window_hits(
    future: pd.DataFrame, customer: int, product: int, start: pd.Timestamp, end: pd.Timestamp,
    value_col: str,
) -> tuple[int, float]:
    part = future[(future["customer_id"] == customer) & (future["product_id"] == product)]
    if part.empty:
        return 0, 0.0
    inside = part[(part["_date"] > start) & (part["_date"] <= end)]
    if inside.empty:
        return 0, 0.0
    return 1, float(pd.to_numeric(inside[value_col], errors="coerce").fillna(0.0).sum())


def build_pair_period(lines: pd.DataFrame, spec: ReplenishSpec) -> pd.DataFrame:
    """جدولِ «جفت × عکس» با ویژگی‌های مدعی، ادعای هر دو طرف، برچسبِ بازه و ارزش."""
    if lines.empty:
        return pd.DataFrame()
    work = lines.copy()
    work["_date"] = pd.to_datetime(work["line_date"])
    work = work[work["product_id"].notna() & work["customer_id"].notna()]
    work["product_id"] = work["product_id"].astype(int)
    work["customer_id"] = work["customer_id"].astype(int)
    purchases = work[~work["is_return"].astype(bool)]
    data_max = work["_date"].max()
    value_col = "gross_profit_rial" if cost_coverage_of(lines) == 1.0 else "revenue_rial"

    frames: list[pd.DataFrame] = []
    for as_of in snapshot_dates(lines, spec):
        stamp = pd.Timestamp(as_of)
        past = work[work["_date"] < stamp]
        future = purchases[purchases["_date"] > stamp]
        if past.empty:
            continue
        table = personal_cadence_table(
            past, as_of=as_of, columns=LEDGER_COLUMNS, min_gaps=spec.min_gaps, decay=spec.decay,
        )
        if table.empty:
            continue
        cycles = _champion_cycles(past)
        rows: list[dict] = []
        for (customer, product), row in table.iterrows():
            customer, product = int(customer), int(product)
            last = pd.Timestamp(row["last_purchase"])
            interval = float(row["pack_adjusted_interval_days"])
            half = spec.window_fraction * interval
            ch_due = last + pd.Timedelta(days=interval)
            ch_start, ch_end = ch_due - pd.Timedelta(days=half), ch_due + pd.Timedelta(days=half)
            cycle = cycles.get(product)
            if cycle:
                elapsed = float((stamp - last).days)
                offset = elapsed - cycle
                near = max(3.0, 0.2 * cycle)
                claimed = offset >= -near
                # قهرمان در بهترین حالتش: نزدیک‌ترین به سررسیدِ خودش اول (سخت‌گیرانه‌تر از
                # ترتیبِ تولیدیِ «عقب‌افتاده‌ترین اول» که برای مقایسه جداگانه ثبت می‌شود)
                champion_score = -abs(offset) if claimed else CHAMPION_UNCLAIMED
                champion_offset_score = offset if claimed else CHAMPION_UNCLAIMED
                cp_due = last + pd.Timedelta(days=cycle)
                cp_half = spec.window_fraction * cycle
                cp_start, cp_end = cp_due - pd.Timedelta(days=cp_half), cp_due + pd.Timedelta(days=cp_half)
            else:
                champion_score = champion_offset_score = CHAMPION_UNCLAIMED
                cp_start = cp_end = None
            covered = ch_end <= data_max and (cp_end is None or cp_end <= data_max)
            hit_ch, value_ch = _window_hits(future, customer, product, max(ch_start, stamp), ch_end, value_col)
            if cp_end is not None:
                hit_cp, value_cp = _window_hits(future, customer, product, max(cp_start, stamp), cp_end, value_col)
            else:
                hit_cp, value_cp = 0, 0.0
            hit_30, _ = _window_hits(
                future, customer, product, stamp, stamp + pd.Timedelta(days=spec.info_horizon_days), value_col,
            )
            rows.append({
                "as_of": as_of, "customer_id": customer, "product_id": product,
                "n_gaps": int(row["n_gaps"]),
                "expected_interval_days": interval,
                "uncertainty": float(row["uncertainty"]) if row["uncertainty"] is not None else 0.0,
                "overdue_ratio": float(row["overdue_ratio"]),
                "future_covered": bool(covered),
                "label": int(hit_ch), "value_rial": value_ch,
                "champion_score": float(champion_score),
                "champion_offset_score": float(champion_offset_score),
                "champion_label": int(hit_cp), "champion_value_rial": value_cp,
                "label_30d": int(hit_30),
            })
        if rows:
            frames.append(pd.DataFrame(rows))
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    out.attrs["value_basis"] = "gross_profit" if value_col == "gross_profit_rial" else "revenue"
    return out


# ───────────────────────────────────────────────── جدولِ سررسید (مدل)
def _bin(values: np.ndarray, edges: tuple[float, ...]) -> np.ndarray:
    return np.clip(np.digitize(values, edges[1:], right=False), 0, len(edges) - 1)


def fit_due_table(train: pd.DataFrame, spec: ReplenishSpec) -> dict:
    """P(خرید در بازه‌ی ادعا | بینِ نسبتِ عقب‌افتادگی، بینِ عدم‌قطعیت) — با شمار."""
    ratio_bin = _bin(train["overdue_ratio"].to_numpy(dtype=float), spec.ratio_edges)
    unc_bin = _bin(train["uncertainty"].to_numpy(dtype=float), spec.uncertainty_edges)
    labels = train["label"].to_numpy(dtype=int)
    cells = [[None, 0] for _ in range(len(spec.ratio_edges) * len(spec.uncertainty_edges))]
    marginal = [[None, 0] for _ in range(len(spec.ratio_edges))]
    for r in range(len(spec.ratio_edges)):
        mask_r = ratio_bin == r
        if mask_r.any():
            marginal[r] = [float(labels[mask_r].mean()), int(mask_r.sum())]
        for u in range(len(spec.uncertainty_edges)):
            mask = mask_r & (unc_bin == u)
            if mask.any():
                cells[r * len(spec.uncertainty_edges) + u] = [float(labels[mask].mean()), int(mask.sum())]
    return {
        "kind": TABLE_KIND,
        "ratio_edges": list(spec.ratio_edges),
        "uncertainty_edges": list(spec.uncertainty_edges),
        "cells": cells, "marginal": marginal,
        "prevalence": float(labels.mean()) if len(labels) else None,
        "min_cell": spec.min_cell, "min_gaps": spec.min_gaps, "decay": spec.decay,
        "window_fraction": spec.window_fraction,
    }


def score_due_table(table: dict, overdue_ratio: np.ndarray, uncertainty: np.ndarray) -> np.ndarray:
    """احتمالِ کالیبره؛ سلولِ نازک ⇒ حاشیه‌ی نسبت؛ حاشیه‌ی نازک ⇒ NaN (بی‌امتیاز، نه حدس)."""
    ratio_edges = tuple(table["ratio_edges"])
    unc_edges = tuple(table["uncertainty_edges"])
    r = _bin(np.asarray(overdue_ratio, dtype=float), ratio_edges)
    u = _bin(np.asarray(uncertainty, dtype=float), unc_edges)
    out = np.full(len(r), np.nan, dtype=float)
    min_cell = int(table.get("min_cell", 20))
    for i in range(len(r)):
        p, n = table["cells"][int(r[i]) * len(unc_edges) + int(u[i])]
        if p is not None and n >= min_cell:
            out[i] = p
            continue
        p, n = table["marginal"][int(r[i])]
        if p is not None and n >= min_cell:
            out[i] = p
    return out


def _bootstrap_two_sided(
    value_a: np.ndarray, score_a: np.ndarray, value_b: np.ndarray, score_b: np.ndarray,
    *, top_fraction: float, samples: int, quantile: float, seed: int = 20240918,
) -> float | None:
    """همان `linear_fit.bootstrap_advantage` وقتی هر طرف ارزشِ خودش (بازه‌ی خودش) را دارد."""
    n = len(value_a)
    if n < 20 or samples <= 0:
        return None
    rng = np.random.default_rng(seed)
    share = max(1, math.ceil(top_fraction * n))
    diffs = np.empty(samples, dtype=float)
    for i in range(samples):
        idx = rng.integers(0, n, n)
        diffs[i] = captured(value_a[idx], score_a[idx], share) - captured(value_b[idx], score_b[idx], share)
    return float(np.quantile(diffs, quantile))


def evaluate_replenish(
    validate: pd.DataFrame, predicted: np.ndarray, *, spec: ReplenishSpec, train: pd.DataFrame,
    value_basis: str,
) -> dict:
    """سه دروازه‌ی promote با سنجه‌ی «ارزشِ خریدهای داخلِ بازه‌ی ادعا در K تای اول»."""
    labels = validate["label"].to_numpy(dtype=int)
    champion_labels = validate["champion_label"].to_numpy(dtype=int)
    prevalence = float(labels.mean()) if len(labels) else 0.0
    scored = ~np.isnan(predicted)
    filled = np.where(scored, predicted, prevalence)
    brier = float(np.mean((filled - labels) ** 2)) if len(labels) else None
    baseline_brier = float(np.mean((prevalence - labels) ** 2)) if len(labels) else None

    value_ch = validate["value_rial"].to_numpy(dtype=float)
    value_cp = validate["champion_value_rial"].to_numpy(dtype=float)
    score_ch = np.where(scored, filled, -1.0)
    score_cp = validate["champion_score"].to_numpy(dtype=float)
    score_cp_offset = validate["champion_offset_score"].to_numpy(dtype=float)
    top_k = max(1, math.ceil(spec.top_fraction * len(validate)))
    model_top = captured(value_ch, score_ch, top_k)
    baseline_top = captured(value_cp, score_cp, top_k)
    baseline_offset_top = captured(value_cp, score_cp_offset, top_k)
    lift_bp = int(round((model_top / baseline_top - 1.0) * 10_000)) if baseline_top > 0 else None
    lower_bound = _bootstrap_two_sided(
        value_ch, score_ch, value_cp, score_cp, top_fraction=spec.top_fraction,
        samples=spec.bootstrap_samples, quantile=spec.bootstrap_quantile,
    )
    bins = reliability_bins(filled, labels)
    max_bin_error = max((abs(b["خطا"]) for b in bins if b["تعداد"] >= 20), default=0.0)

    beats_brier = bool(brier is not None and baseline_brier is not None and brier < baseline_brier)
    # قهرمانی که در K تای اولش هیچ خریدِ داخلِ بازه ندارد، «لیفتِ» تعریف‌شده ندارد؛
    # برتری آن‌وقت با کرانِ پایینِ bootstrap و ارزشِ مثبتِ مدعی سنجیده می‌شود.
    beats_topk = bool(
        lower_bound is not None and lower_bound > 0 and (
            (lift_bp is not None and lift_bp >= spec.min_topk_lift_bp)
            or (baseline_top <= 0 and model_top > 0)
        )
    )
    calibrated = bool(max_bin_error <= spec.max_calibration_bin_error)

    order_ch = np.argsort(-score_ch, kind="stable")[:top_k]
    order_cp = np.argsort(-score_cp, kind="stable")[:top_k]
    hits_30 = validate["label_30d"].to_numpy(dtype=int)
    key = f"topk_captured_{value_basis}_rial"
    return {
        "n_train": int(len(train)), "n_validate": int(len(validate)),
        "n_validate_positives": int(labels.sum()),
        "hit_rate": round(prevalence, 4),
        "champion_hit_rate": round(float(champion_labels.mean()), 4) if len(labels) else None,
        "scored_share": round(float(scored.mean()), 4) if len(labels) else None,
        "brier": None if brier is None else round(brier, 5),
        "brier_baseline": None if baseline_brier is None else round(baseline_brier, 5),
        "baseline_name_fa": BASELINE_NAME_FA,
        "label_window_fa": f"خریدِ همان کالا در بازه‌ی ادعای هر طرف (±{int(spec.window_fraction * 100)}٪ فاصله)",
        "top_k": top_k,
        key: int(round(model_top)),
        f"baseline_{key}": int(round(baseline_top)),
        f"baseline_by_offset_{key}": int(round(baseline_offset_top)),
        "baseline_ranking_fa": "نزدیک‌ترین به سررسیدِ خودش اول (بهترین حالتِ قهرمان)؛ ترتیبِ تولیدی «عقب‌افتاده‌ترین اول» جداگانه",
        "topk_lift_bp": lift_bp,
        "topk_advantage_lower_rial": None if lower_bound is None else int(round(lower_bound)),
        "topk_hit_precision": round(float(labels[order_ch].mean()), 4) if len(labels) else None,
        "baseline_topk_hit_precision": round(float(champion_labels[order_cp].mean()), 4) if len(labels) else None,
        # اطلاعی: افقِ ثابتِ ۳۰ روزه (قابل مقایسه با buy_probability_30d)؛ دروازه نیست
        "info_30d_hit_precision": round(float(hits_30[order_ch].mean()), 4) if len(labels) else None,
        "baseline_info_30d_hit_precision": round(float(hits_30[order_cp].mean()), 4) if len(labels) else None,
        "value_basis": value_basis,
        "value_basis_note_fa": (
            "بها در همه‌ی خطوط هست؛ سنجه سودِ ناخالص است." if value_basis == "gross_profit"
            else "بها در داده نیست؛ سنجه درآمدی است نه سودی."
        ),
        "max_calibration_bin_error": round(float(max_bin_error), 4),
        "reliability_bins": bins,
        "gates": {
            "beats_baseline_brier": beats_brier,
            "beats_baseline_topk": beats_topk,
            "calibrated": calibrated,
        },
        "passed": bool(beats_brier and beats_topk and calibrated),
    }


def _rejection_reason(metrics: dict, spec: ReplenishSpec) -> str:
    gates = metrics["gates"]
    parts: list[str] = []
    if not gates["beats_baseline_brier"]:
        parts.append(f"دقتش از نرخِ پایه بهتر نشد (Brier {metrics['brier']} در برابر {metrics['brier_baseline']})")
    if not gates["beats_baseline_topk"]:
        parts.append(
            "ارزشِ خریدهای داخلِ بازه در K تای اول از میانه‌ی کالا جلو نزد یا اختلافش آماری "
            f"واقعی نبود (حداقل {spec.min_topk_lift_bp / 100:.1f}٪)"
        )
    if not gates["calibrated"]:
        parts.append(f"کالیبراسیون خارج از تلرانس است ({metrics['max_calibration_bin_error']})")
    return "؛ ".join(parts) + "."


def _requirements(
    lines: pd.DataFrame, table: pd.DataFrame, spec: ReplenishSpec, positives: int | None,
) -> tuple[list[dict], str | None]:
    """جدولِ «لازم در برابر موجود» — همان قالبِ `features/cohorts.assess_cohort_maturity`."""
    stamps = pd.to_datetime(lines["line_date"]) if not lines.empty else pd.Series(dtype="datetime64[ns]")
    span = int((stamps.max() - stamps.min()).days) if len(stamps) else 0
    snapshots = int(table["as_of"].nunique()) if not table.empty else 0
    rows = int(len(table))
    checks = [
        ("span_too_short", "دامنه‌ی داده (روز)", spec.min_span_days, span),
        ("too_few_snapshots", "شمارِ عکس‌های زمانی", spec.min_snapshots, snapshots),
        ("too_few_pairs", "ردیف‌های جفت × عکسِ پوشیده", spec.min_rows, rows),
        ("too_few_positives", "کمینه‌ی نمونه‌ی مثبت در دو بازو", spec.min_positive_per_arm,
         0 if positives is None else positives),
    ]
    out = [{"code": code, "label_fa": label, "required": need, "available": have} for code, label, need, have in checks]
    failing = next((code for code, _l, need, have in checks if have < need), None)
    return out, failing


def train_replenish(
    *, business_slug: str = "default", params: dict[str, Any] | None = None,
    db_path: Path | None = None,
) -> dict:
    """آموزشِ جدولِ سررسیدِ شخصی و ثبتش در رجیستری؛ هیچ‌چیز promote نمی‌شود."""
    ensure_schema(db_path)
    spec = ReplenishSpec().with_params(params)
    with session_scope(db_path) as session:
        business_id = resolve_business_id(session, business_slug)
        if business_id is None:
            raise ValueError("کسب‌وکاری ثبت نشده است؛ اول یک فایل فروش تحلیل کنید.")
        lines = load_line_frame(session, business_id)

    profit = lines["gross_profit_rial"] if not lines.empty else pd.Series(dtype=float)
    common = {
        "business_slug": business_slug, "model_key": MODEL_KEY, "db_path": db_path,
        "model_kind": MODEL_KIND, "params_json": asdict(spec), "label_basis": LABEL_BASIS,
        "data_hash": compute_data_hash(
            business_id=business_id, model_key=MODEL_KEY,
            train_start=str(lines["line_date"].min()) if not lines.empty else None,
            train_end=str(lines["line_date"].max()) if not lines.empty else None,
            n_lines=int(len(lines)),
            sum_revenue_rial=int(lines["revenue_rial"].sum()) if not lines.empty else 0,
            sum_gross_profit_rial=None if lines.empty or profit.isna().any() else int(profit.sum()),
        ),
    }
    unchanged = "قاعده‌ای ساخته نشد؛ یادآورِ تکرارِ خرید دقیقاً مثل قبل (میانه‌ی کالا) می‌ماند."

    full = build_pair_period(lines, spec)
    table = full[full["future_covered"]] if not full.empty else full
    value_basis = full.attrs.get("value_basis", "revenue") if not full.empty else "revenue"

    positives: int | None = None
    split_date = train = validate = None
    if not table.empty:
        split_date = chronological_cut(table["as_of"], spec.train_fraction)
        train = table[table["as_of"] < split_date]
        validate = table[table["as_of"] >= split_date]
        positives = min(int(train["label"].sum()), int(validate["label"].sum()))
    requirements, failing = _requirements(lines, table, spec, positives)
    if failing or train is None or train.empty or validate.empty:
        code = failing or "too_few_pairs"
        need = next(r for r in requirements if r["code"] == code)
        return record_run(
            status=ModelRun.STATUS_INSUFFICIENT, blocked_reason_code=code,
            blocked_reason_fa=f"{need['label_fa']}: {need['available']} موجود، دست‌کم {need['required']} لازم.",
            metrics_json={"requirements": requirements, "n_rows": int(len(table)),
                          "value_basis": value_basis},
            note_fa=unchanged, **common,
        )

    due_table = fit_due_table(train, spec)
    predicted = score_due_table(
        due_table, validate["overdue_ratio"].to_numpy(dtype=float), validate["uncertainty"].to_numpy(dtype=float),
    )
    metrics = evaluate_replenish(validate, predicted, spec=spec, train=train, value_basis=value_basis)
    metrics["requirements"] = requirements
    metrics["snapshots"] = sorted(table["as_of"].unique().tolist())
    metrics["coverage"] = {
        "pair_snapshots_total": int(len(full)),
        "pair_snapshots_covered": int(len(table)),
        "champion_claimed_share": round(float((validate["champion_score"] > CHAMPION_UNCLAIMED).mean()), 4),
    }
    status = ModelRun.STATUS_VALIDATED if metrics["passed"] else ModelRun.STATUS_REJECTED
    return record_run(
        status=status,
        train_start=str(train["as_of"].min()), train_end=str(train["as_of"].max()),
        validate_start=str(validate["as_of"].min()), validate_end=str(validate["as_of"].max()),
        n_train=int(len(train)), n_validate=int(len(validate)),
        n_train_positives=int(train["label"].sum()), n_validate_positives=int(validate["label"].sum()),
        feature_schema_json=["overdue_ratio", "uncertainty", "expected_interval_days", "n_gaps"],
        metrics_json=metrics,
        calibration_json={"method": "due_table", "reliability_bins": metrics["reliability_bins"]},
        coefficients_json=due_table,
        drift_baseline_json=None,
        blocked_reason_code=None if metrics["passed"] else "did_not_beat_baseline",
        blocked_reason_fa=None if metrics["passed"] else _rejection_reason(metrics, spec),
        note_fa=(
            "این قاعده قهرمانِ فعلی (میانه‌ی کالا) را برد و آماده‌ی فعال‌سازی است."
            if metrics["passed"] else "این قاعده فعال نمی‌شود؛ " + unchanged
        ),
        **common,
    )


def promoted_due_table(session: Session, business_id: int) -> tuple[ModelRun, dict] | None:
    """اجرای فعالِ `replenish` و جدولِ سررسیدش؛ بدونِ اجرای فعال `None`."""
    import json

    run = promoted_run(session, business_id, MODEL_KEY)
    if run is None or not run.coefficients_json:
        return None
    try:
        table = json.loads(run.coefficients_json)
    except (TypeError, ValueError):
        return None
    if not isinstance(table, dict) or table.get("kind") != TABLE_KIND:
        return None
    return run, table


register_trainer(MODEL_KEY, train_replenish)

__all__ = [
    "CHAMPION_UNCLAIMED", "LABEL_BASIS", "MODEL_KEY", "ReplenishSpec", "build_pair_period",
    "evaluate_replenish", "fit_due_table", "promoted_due_table", "score_due_table",
    "snapshot_dates", "train_replenish",
]
