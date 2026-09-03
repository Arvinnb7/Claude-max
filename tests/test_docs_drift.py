"""اسناد نباید بی‌صدا از کد عقب بمانند.

این تست از یک اتفاق واقعی آمده: `ROLLBACK.md` می‌گفت «حذفِ این جدول‌ها بی‌خطر
است» در حالی که هشت جدول تازه اصلاً در فهرستش نبودند — و یکی از آن‌ها
(`contact_suppressions`) فهرستِ کسانی است که گفته‌اند «پیام نفرست». سندِ غلط در
لحظه‌ی بازیابیِ اضطراری خوانده می‌شود؛ دقیقاً بدترین لحظه برای اشتباه‌بودن.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

from mktcore.db import Base, models  # noqa: E402, F401  - models: ثبت در metadata

_ROLLBACK = _ROOT / "docs" / "revenue-intelligence" / "ROLLBACK.md"

# جدولِ نسخه‌ی مهاجرت در `Base.metadata` نیست ولی در سند باید باشد
_EXTRA_DOCUMENTED = {"schema_migrations"}


def _documented_tables() -> set[str]:
    text = _ROLLBACK.read_text(encoding="utf-8")
    # نام جدول‌ها هم در بلوک کد می‌آیند هم در ستون اولِ جدول مارک‌داون
    names = set(re.findall(r"[a-z_][a-z0-9_]{3,}", text))
    return {n for n in names if n in _all_tables() | _EXTRA_DOCUMENTED}


def _all_tables() -> set[str]:
    return set(Base.metadata.tables.keys())


def test_rollback_doc_lists_every_canonical_table():
    """هر جدولِ تازه باید در سند بازگشت ثبت شود."""
    missing = _all_tables() - _documented_tables()
    assert not missing, (
        "این جدول‌ها در ROLLBACK.md نیستند؛ سند بازگشت ناقص است: "
        f"{sorted(missing)}"
    )


def test_rollback_doc_separates_rebuildable_from_irreversible():
    """تفکیک باید صریح باشد، وگرنه خواننده همه را بازساختنی فرض می‌کند."""
    text = _ROLLBACK.read_text(encoding="utf-8")
    assert "بازساختنی" in text
    assert "برگشت‌ناپذیر" in text


def test_the_opt_out_register_is_marked_irreversible():
    """مهم‌ترین ادعای این سند: حذف دفترِ انصراف برگشت‌ناپذیر است."""
    text = _ROLLBACK.read_text(encoding="utf-8")
    head, _, tail = text.partition("### برگشت‌ناپذیر")
    assert "contact_suppressions" in tail, (
        "دفترِ انصراف باید در بخشِ «برگشت‌ناپذیر» باشد، نه بازساختنی"
    )
    assert "contact_suppressions" not in head.split("### بازساختنی")[-1].split("###")[0]


def test_learned_effect_tables_are_marked_irreversible():
    text = _ROLLBACK.read_text(encoding="utf-8")
    _head, _, tail = text.partition("### برگشت‌ناپذیر")
    for table in ("campaign_outcomes", "uplift_snapshots", "campaign_sends"):
        assert table in tail, f"{table} از تحلیل بازساختنی نیست"


def test_doc_no_longer_claims_dropping_is_always_safe():
    """جمله‌ی قدیمی («حذفشان بی‌خطر است») حالا مشروط است، نه مطلق."""
    text = _ROLLBACK.read_text(encoding="utf-8")
    assert "حذف نکنید" in text


# ═══════════════════════════════════ اسناد مدل‌ها (فاز ۴)
_MODEL_CARDS = _ROOT / "docs" / "revenue-intelligence" / "MODEL_CARDS.md"
_FEATURE_CATALOG = _ROOT / "docs" / "revenue-intelligence" / "FEATURE_CATALOG.md"


def test_model_cards_document_every_trainable_model():
    """مدلی که آموزش‌دهنده دارد ولی کارت ندارد، جعبه‌ی سیاه است."""
    from mktcore.ml.train import available_trainers

    text = _MODEL_CARDS.read_text(encoding="utf-8")
    missing = [key for key in available_trainers() if f"`{key}`" not in text]
    assert not missing, f"این مدل‌ها کارت ندارند: {missing}"


def test_model_cards_state_the_champion_challenger_rule():
    """قاعده‌ای که کلِ ایمنیِ این لایه رویش بنا شده باید نوشته باشد."""
    text = _MODEL_CARDS.read_text(encoding="utf-8")
    assert "قهرمان" in text and "مدعی" in text
    assert "promote" in text or "فعال‌سازی" in text


def test_feature_catalog_covers_every_column_in_the_schema():
    """ستونی که در طرح‌واره هست ولی در سند نیست، بعداً بی‌معنا تفسیر می‌شود."""
    from mktcore.features.point_in_time import PIT_FEATURE_SCHEMA

    text = _FEATURE_CATALOG.read_text(encoding="utf-8")
    missing = [name for name in PIT_FEATURE_SCHEMA if name not in text]
    assert not missing, f"این ستون‌ها در فهرست ویژگی‌ها نیستند: {missing}"


def test_feature_catalog_states_the_nan_rule():
    """قاعده‌ی «NaN یعنی نمی‌دانیم، نه صفر» باید صریح نوشته باشد."""
    text = _FEATURE_CATALOG.read_text(encoding="utf-8")
    assert "NaN" in text
    assert "نه صفر" in text


# ════════════════════════════════════════ تنظیم‌ها در برابر `.env.example`
_ENV_EXAMPLE = _ROOT / ".env.example"

# تنظیم‌هایی که عمداً مستند نمی‌شوند، با دلیل
_UNDOCUMENTED_SETTINGS: dict[str, str] = {}


def _env_names() -> set[str]:
    from mktcore.config import Settings

    return {name.upper() for name in Settings.model_fields}


def test_every_setting_appears_in_env_example():
    """تنظیمی که در `.env.example` نباشد، عملاً وجود ندارد.

    هفت کلید ماه‌ها فقط در کد بودند: کسی که سرور را بالا می‌آورد راهی نداشت
    بفهمد `MKT_UPLIFT_RANKING` یا `MKT_CANONICAL_ENABLE` وجود دارند.
    """
    text = _ENV_EXAMPLE.read_text(encoding="utf-8")
    missing = sorted(
        name for name in _env_names()
        if name not in text and name not in _UNDOCUMENTED_SETTINGS
    )

    assert not missing, (
        "این تنظیم‌ها در `.env.example` نیستند، پس کسی از وجودشان خبر ندارد: "
        + "، ".join(missing)
    )


def test_no_stale_exemptions_in_the_settings_allow_list():
    stale = sorted(set(_UNDOCUMENTED_SETTINGS) - _env_names())
    assert not stale, f"این استثناها دیگر تنظیمی ندارند: {stale}"


# ════════════════════════════════════════════════ اسنادِ عملیاتی §۳۶
_OPERATIONS = _ROOT / "docs" / "revenue-intelligence" / "OPERATIONS_RUNBOOK.md"
_SECURITY = _ROOT / "docs" / "revenue-intelligence" / "SECURITY_AND_PRIVACY.md"


def test_the_operations_runbook_covers_backup_and_restore():
    """راهنمایی که پشتیبان‌گیری نداشته باشد، در روز حادثه بی‌فایده است."""
    text = _OPERATIONS.read_text(encoding="utf-8")

    for topic in ("پشتیبان", "بازیابی", "docker compose", "مهاجرت"):
        assert topic in text, f"«{topic}» در راهنمای عملیات نیست"


def test_the_security_doc_names_what_leaves_the_machine():
    """سندی که نگوید چه چیزی از این سرور بیرون می‌رود، سند امنیتی نیست."""
    text = _SECURITY.read_text(encoding="utf-8")

    for topic in ("Anthropic", "پیامک", "MKT_API_TOKEN", "شماره تماس"):
        assert topic in text, f"«{topic}» در سند امنیت و حریم خصوصی نیست"


def test_the_security_doc_lists_the_guarded_routes_from_code():
    """فهرستِ مسیرها باید از کد بیاید، نه از حافظه‌ی نویسنده."""
    from mktcore.security import EXTRA_GUARDED_ROUTES

    text = _SECURITY.read_text(encoding="utf-8")
    for key in EXTRA_GUARDED_ROUTES:
        path = key.split(" ", 1)[1]
        assert path in text, f"{path} در سند امنیت نیامده است"


# ═══════════════════════════════════════ نردبان تخفیف و ممیزی (§۲۰.۳، §۳۱)
_EXPERIMENTATION = _ROOT / "docs" / "revenue-intelligence" / "EXPERIMENTATION_GUIDE.md"
_IMPLEMENTATION_STATUS = _ROOT / "docs" / "revenue-intelligence" / "IMPLEMENTATION_STATUS.md"


def test_the_security_doc_names_every_audit_action():
    """رویدادِ ممیزی‌ای که در سند امنیت نیامده، برای خواننده وجود ندارد."""
    from mktcore.db.models import AuditEvent

    text = _SECURITY.read_text(encoding="utf-8")
    actions = [
        value for name, value in vars(AuditEvent).items()
        if name.startswith("ACTION_") and isinstance(value, str)
    ]
    assert actions
    missing = [a for a in actions if a not in text]
    assert not missing, f"این رویدادهای ممیزی در سند امنیت نیستند: {missing}"


def test_the_experimentation_guide_states_the_approval_rule():
    text = _EXPERIMENTATION.read_text(encoding="utf-8")
    for fragment in ("holdout", "approved", "{تخفیف}", "(m − d) / (1 − d)", "phase5-readiness"):
        assert fragment in text, f"«{fragment}» در راهنمای آزمایش نیست"


def test_required_docs_count_in_status_matches_the_disk():
    """«۶ از ۱۵» و «۴ از ۱۵» هم‌زمان در یک سند بودند و هیچ‌کدام درست نبود."""
    required = [
        "CURRENT_SYSTEM_AUDIT", "TARGET_ARCHITECTURE", "DATA_DICTIONARY",
        "SOURCE_MAPPING_GUIDE", "FINANCIAL_CALCULATION_RULES", "IDENTITY_RESOLUTION",
        "FEATURE_CATALOG", "OPPORTUNITY_ENGINE", "MODEL_CARDS", "EXPERIMENTATION_GUIDE",
        "API_GUIDE", "OPERATIONS_RUNBOOK", "SECURITY_AND_PRIVACY",
        "IMPLEMENTATION_STATUS", "RELEASE_NOTES",
    ]
    on_disk = sum((_ROOT / "docs" / "revenue-intelligence" / f"{n}.md").exists() for n in required)
    text = _IMPLEMENTATION_STATUS.read_text(encoding="utf-8")
    claims = set(re.findall(r"\*\*(\d+|[۰-۹]+) از ۱۵\*\*", text))
    fa = "۰۱۲۳۴۵۶۷۸۹"
    normalised = {"".join(str(fa.index(ch)) if ch in fa else ch for ch in c) for c in claims}
    assert normalised == {str(on_disk)}, (
        f"سند وضعیت می‌گوید {sorted(claims)} از ۱۵؛ روی دیسک {on_disk} سند هست"
    )


# ═══════════════════════════════ راست‌شدنِ اسناد با کد (دورِ صحت و ایمنی)
_STATUS = _ROOT / "docs" / "revenue-intelligence" / "IMPLEMENTATION_STATUS.md"
_RUNBOOK = _ROOT / "docs" / "revenue-intelligence" / "OPERATIONS_RUNBOOK.md"
_TARGET = _ROOT / "docs" / "revenue-intelligence" / "TARGET_ARCHITECTURE.md"
_SPEC_GAP = _ROOT / "docs" / "revenue-intelligence" / "SPEC_GAP_AUDIT.md"


def test_status_ledger_does_not_call_shipped_features_deferred():
    """auth و audit log ساخته و تست شده‌اند؛ دفتر نباید «خارج از دامنه» بخواندشان."""
    text = _STATUS.read_text(encoding="utf-8")
    assert "احراز هویت / RBAC / audit log" not in text
    assert "`security.py`" in text and "audit_events" in text
    assert "لغو ۱۱" in text and "contact-suppressions" in text


def test_runbook_and_rollback_agree_on_code_rollback():
    """کدِ قدیمی روی دیتابیسِ جدید کار می‌کند — دو سند نباید خلافِ هم بگویند."""
    runbook = _RUNBOOK.read_text(encoding="utf-8")
    rollback = _ROLLBACK.read_text(encoding="utf-8")
    assert "پشتیبانی نمی‌شود" not in runbook.split("مهاجرت طرح‌واره")[-1].split("---")[0]
    assert "MKT_CANONICAL_ENABLE" in runbook and "MKT_CANONICAL_ENABLE" in rollback
    assert "اختیاری" in runbook and "اختیاری" in rollback


def test_target_architecture_reflects_the_token_guard_and_later_phases():
    text = _TARGET.read_text(encoding="utf-8")
    assert "MKT_API_TOKEN" in text and "security.py" in text
    assert "## تصمیم‌های فاز ۵" in text
    assert "auth/RBAC" not in text


def test_spec_gap_docs_table_matches_the_disk():
    from tests.test_docs_drift import _ROOT as root  # noqa: PLC0415

    text = _SPEC_GAP.read_text(encoding="utf-8")
    docs_dir = root / "docs" / "revenue-intelligence"
    required = [
        "CURRENT_SYSTEM_AUDIT", "TARGET_ARCHITECTURE", "DATA_DICTIONARY",
        "SOURCE_MAPPING_GUIDE", "FINANCIAL_CALCULATION_RULES", "IDENTITY_RESOLUTION",
        "FEATURE_CATALOG", "OPPORTUNITY_ENGINE", "MODEL_CARDS", "EXPERIMENTATION_GUIDE",
        "API_GUIDE", "OPERATIONS_RUNBOOK", "SECURITY_AND_PRIVACY", "IMPLEMENTATION_STATUS",
        "RELEASE_NOTES",
    ]
    present = sum(1 for name in required if (docs_dir / f"{name}.md").exists())
    assert f"## اسناد الزامی (§۳۶): {present} از ۱۵" in text.replace("۱۰", "10").replace("۱۵", "15") or (
        f"{present}" in text.split("## اسناد الزامی (§۳۶):")[1].split("\n")[0]
        .replace("۱۰", "10").replace("۱۵", "15")
    )
