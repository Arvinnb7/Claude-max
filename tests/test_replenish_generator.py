"""مولدِ مدعیِ چرخه‌ی خریدِ شخصی (§۱۳.۲) — قهرمان/مدعی پشتِ اجرای فعال.

R0: `as_of` از موتور به مولدها می‌رسد (§۱۲ `generate(as_of)`) و مولدهای امروزی آن را
نادیده می‌گیرند ⇒ خروجی بیت‌به‌بیت همان است.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

from mktcore.analysis.kpis import compute_kpis  # noqa: E402
from mktcore.db.migrations import reset_ensure_cache  # noqa: E402
from mktcore.db.repo_import import write_import  # noqa: E402
from mktcore.ingest.cleaning import clean_frame  # noqa: E402
from mktcore.ingest.mapper import SchemaMapper  # noqa: E402
from mktcore.opportunities import run_opportunity_engine  # noqa: E402
from mktcore.opportunities.engine import _as_of  # noqa: E402
from mktcore.opportunities.generators import (  # noqa: E402
    generate_candidates,
    generate_from_action_list,
    generate_from_expansion_gap,
)
from mktcore.pipeline import run_analysis  # noqa: E402
from mktcore.synthetic import generate_synthetic_sales  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_schema_cache():
    reset_ensure_cache()
    yield
    reset_ensure_cache()


@pytest.fixture(scope="module")
def analyzed():
    raw = generate_synthetic_sales(seed=3, days=420)
    mapper = SchemaMapper()
    clean = clean_frame(mapper.apply(raw, mapper.auto_detect(raw).mapping))
    bundle = run_analysis(clean, horizon=3, with_forecast=False)
    return clean, bundle


def _shape(candidates) -> list[tuple]:
    return sorted(
        (c.kind, c.generator, c.customer_key, c.product_name, c.expected_value_display,
         c.probability, c.due_date, c.value_kind)
        for c in candidates
    )


# ═══════════════════════════════════════════ R0: as_of بی‌اثر روی مولدهای امروزی
def test_as_of_threading_is_a_no_op(analyzed):
    clean, bundle = analyzed
    as_of = _as_of(clean)
    assert as_of == str(clean["date"].max().date())

    without = generate_candidates(bundle, clean)
    with_as_of = generate_candidates(bundle, clean, as_of=as_of)
    assert without, "فیکسچر باید نامزد بسازد"
    assert _shape(without) == _shape(with_as_of)
    assert _shape(generate_from_action_list(bundle, clean)) == _shape(
        generate_from_action_list(bundle, clean, as_of=as_of)
    )
    assert _shape(generate_from_expansion_gap(bundle, clean)) == _shape(
        generate_from_expansion_gap(bundle, clean, as_of=as_of)
    )


def test_engine_generated_count_equals_the_sum_of_generators_without_models(tmp_path, analyzed):
    """بدون مدلِ فعال، موتور دقیقاً همان نامزدهای دو مولدِ امروزی را می‌بیند."""
    clean, bundle = analyzed
    db = tmp_path / "app.db"
    write_import(clean, kpis=compute_kpis(clean), db_path=db)
    result = run_opportunity_engine(bundle, clean, db_path=db)
    assert result is not None
    expected = len(generate_from_action_list(bundle, clean)) + len(
        generate_from_expansion_gap(bundle, clean)
    )
    assert result.generated == expected
