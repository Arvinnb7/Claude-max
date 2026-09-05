"""تولیدِ سه سندِ کدمحورِ §۳۶ از خودِ کد — نه از حافظه‌ی نویسنده.

* `DATA_DICTIONARY.md`  ← `Base.metadata` (+ جدول‌های legacy از DDLِ `api/persistence.py`)
* `API_GUIDE.md`        ← پیمایشِ مسیرهای FastAPI + فهرست‌های گارد در `mktcore.security`
* `SOURCE_MAPPING_GUIDE.md` ← `ingest/schema.py` + کلیدواژه‌های `ingest/mapper.py`

اجرا: `python tools/gen_reference_docs.py` (بازنویسی) یا `--check` (فقط مقایسه؛
`tests/test_docs_drift.py` همین را صدا می‌زند تا سند از کد عقب نماند). توضیح‌های
فارسی در همین فایل نگه‌داری می‌شوند؛ نامِ جدول/ستون/مسیر همیشه از کد می‌آید.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

DOCS = ROOT / "docs" / "revenue-intelligence"

# ═══════════════════════════════════════════════════════════ DATA_DICTIONARY
TABLE_GROUPS: list[tuple[str, tuple[str, ...]]] = [
    ("بارگذاری و کیفیت (§۷.۱، §۸)", (
        "businesses", "import_batches", "import_rows_raw", "import_quarantine",
        "import_reconciliation", "mapping_profile_versions",
    )),
    ("دفتر کل فروش (§۷.۲)", ("customers", "customer_keys", "products", "product_aliases",
                              "orders", "order_lines", "product_cost_history")),
    ("پرونده‌ی ۳۶۰ و چرخه‌ی عمر (§۱۰، §۱۱)", ("customer_features", "customer_lifecycle_events")),
    ("موتور فرصت‌ها (§۱۲–§۱۶، §۲۰.۳)", ("opportunity_runs", "opportunities", "opportunity_factors",
                                        "opportunity_events", "opportunity_offers")),
    ("کمپین و آزمایش (§۲۲، §۲۹)", ("campaigns", "campaign_members", "campaign_opportunities",
                                   "campaign_sends", "campaign_outcomes", "uplift_snapshots",
                                   "contact_suppressions")),
    ("مدل‌ها (§۲۶)", ("model_runs",)),
    ("عملیات و امنیت (§۲۸، §۳۱)", ("job_runs", "job_leases", "app_settings", "audit_events")),
]

# توضیحِ ستون‌ها. کلید = نامِ ستون (مشترک بین جدول‌ها) یا «جدول.ستون» برای استثنا.
COLUMN_DOCS: dict[str, str] = {
    "id": "کلید اصلی (خودافزا)",
    "business_id": "کسب‌وکار (جداسازی داده؛ داده‌ی نمونه در کسب‌وکارِ جدا)",
    "created_at": "زمانِ ساختِ ردیف (یونیکس، ثانیه)",
    "updated_at": "آخرین به‌روزرسانی (یونیکس، ثانیه)",
    "customer_id": "مشتری پایدار",
    "product_id": "کالای پایدار",
    "batch_id": "بارگذاری‌ای که این ردیف را نوشت/آخرین بار به‌روز کرد",
    "opportunity_id": "فرصت",
    "campaign_id": "کمپین",
    "as_of_date": "تاریخِ مرجعِ عکس/اجرا (آخرین روزِ داده، نه امروز)",
    "status": "وضعیتِ ردیف (واژگانِ هر جدول در توضیحِ همان جدول)",
    "note_fa": "یادداشتِ فارسی برای نمایش",
    "notes_json": "جزئیاتِ ساختاریافته‌ی افزودنی (JSON)",
    "detail_fa": "توضیحِ فارسی",
    "reason_fa": "دلیلِ فارسی (برای انسان)",
    "label_fa": "برچسبِ فارسی",
    "display_currency": "واحدِ نمایش (تومان/ریال) — مبالغ در دیتابیس همیشه ریال‌اند",
    "file_currency": "واحدِ پولِ فایلِ منبع (انتخابِ اپراتور)",
    "phone_e164": "شماره‌ی نرمال‌شده‌ی E.164 (`+98…`)",
    "source": "منبعِ ردیف (فایل/تاریخچه/دستی/تست)",
    "cost_rial": "بهای تمام‌شده به ریال؛ NULL = نامعلوم، نه صفر",
    "cost_confidence": "اطمینانِ بها: `from_file` / `history_exact` / `history_imputed`",
    "discount_rial": "تخفیفِ مبلغی به ریال (فقط وقتی ستونِ تخفیف مبلغی است)",
    "revenue_rial": "درآمدِ خط به ریال؛ خطِ برگشتی منفی",
    "raw_product_name": "نامِ خامِ کالا همان‌طور که در فایل بود",
    "name": "نام",
    "revision": "شماره‌ی نسخه‌ی همین `dataset_key` (تحلیلِ دوباره‌ی همان فایل +۱)",
    "session_id": "نشستِ تحلیل در لایه‌ی legacy",
    "sheet_name": "نامِ برگه‌ی اکسل",
    "display_name": "نامِ نمایشی",
    "basis": "مبنای عدد (سود/درآمد/…)",
    "kind": "نوع",
    "expected_value_rial": "ارزشِ موردِ انتظار به ریال (درآمدی، از قبل در احتمال ضرب‌شده)",
    "expires_at": "انقضا",
    "value_text": "مقدار به‌صورت متن",
    "actor": "چه کسی/چه چیزی این کار را کرد (کاربر/کار/سیستم)",
    "arm": "بازوی آزمایش: `treatment` / `control`",
    "offer_discount_bp": "تخفیفِ مصوبِ پیشنهاد (bp)؛ NULL = بدون تخفیف",
    "reason_code": "کدِ دلیل (پایدار، برای فیلتر)",
    "row_number": "شماره‌ی ردیفِ منبع (۰-مبنا پس از سرستون)",
    "raw_payload_json": "ردیفِ خام به‌صورت JSON (ستون→مقدار)",
    "job_name": "نامِ کارِ زمان‌بندی‌شده",
    # businesses
    "slug": "شناسه‌ی متنیِ یکتا (`default` / `sample`)",
    # import_batches
    "dataset_key": "هشِ محتوای فایل — فایلِ یکسان همیشه همان کلید",
    "filename": "نامِ فایلِ بارگذاری‌شده",
    "rial_per_file_unit": "ضریبِ تبدیلِ واحدِ فایل به ریال (۱ یا ۱۰)",
    "rows_total": "ردیف‌های خامِ فایل (سالم + نامعتبر + تکراری + برگشت)",
    "rows_clean": "ردیف‌های خریدِ سالم",
    "rows_invalid": "ردیف‌های با تاریخ/مبلغِ نامعتبر (قرنطینه)",
    "rows_duplicate": "ردیف‌های کاملاً تکراری (قرنطینه)",
    "rows_returns": "ردیف‌های برگشت از فروش",
    "lines_inserted": "خطوطِ تازه‌درج‌شده",
    "lines_updated": "خطوطِ موجودی که به‌روز شدند (صادراتِ هم‌پوشان)",
    "date_min": "کمینه‌ی تاریخِ خطوطِ این دسته (ISO)",
    "date_max": "بیشینه‌ی تاریخِ خطوطِ این دسته (ISO)",
    "net_sales_rial": "فروشِ خالصِ این دسته به ریال",
    "validation_status": "دروازه‌ی تحلیل: PASS / PASS_WITH_WARNINGS / FAIL",
    "reconcile_status": "آشتیِ نوشتن: RECONCILED / RECONCILED_WITH_WARNINGS / MISMATCH / BLOCKED",
    "mapping_signature": "امضای سرستونِ فایل (§۸.۲)",
    "mapping_version": "نسخه‌ی نگاشتِ به‌کاررفته برای این دسته (§۸.۲)",
    # import_rows_raw / quarantine
    "row_hash": "هشِ محتوای ردیف",
    "parse_status": "نتیجه‌ی خواندنِ ردیف",
    "reason_detail_fa": "دلیلِ کنارگذاشتن به فارسی",
    "suggested_resolution_fa": "راهِ اصلاحِ پیشنهادی برای اپراتور",
    "resolved_at": "زمانِ رسیدگی (NULL = باز)",
    "resolved_by": "چه کسی رسیدگی کرد",
    "resolution_note_fa": "یادداشتِ رسیدگی",
    # import_reconciliation
    "check_id": "کدِ کنترل (L01…L13)",
    "expected_text": "مقدارِ موردِ انتظار (از تحلیل/فایل)",
    "actual_text": "مقدارِ دفتر کل",
    "delta_text": "اختلاف",
    "tolerance_text": "تلرانس",
    "import_reconciliation.status": "OK / WARN / MISMATCH / SKIPPED («سنجیده نشد»)",
    # mapping_profile_versions
    "signature": "امضای سرستون",
    "version": "شماره‌ی نسخه (به‌ازای امضا، از ۱)",
    "mapping_hash": "اثرِ انگشتِ نگاشت (نقش→ستون + واحدها)",
    "columns_json": "سرستون‌های فایل (JSON)",
    "mapping_json": "نگاشتِ نقش→نامِ ستون (JSON)",
    # customers
    "canonical_key": "کلیدی که تحلیل با آن کار می‌کند (کلیدِ خامِ نخستین دیدار)",
    "email": "ایمیلِ نرمال‌شده",
    "first_order_date": "نخستین خرید (ISO)",
    "last_order_date": "آخرین خرید (ISO)",
    "resolution_method": "چطور حل شد: `phone` / `raw_key`",
    "acquired_at": "زمانِ ثبتِ مشتری",
    "segments": "سگمنت‌های تحلیلی (متن)",
    # customer_keys
    "key_type": "نوعِ کلید: `raw_key` / `phone` / `email`",
    "key_value": "مقدارِ نرمال‌شده‌ی کلید",
    "confidence_bp": "اطمینانِ پیوند (bp) — فقط پیوندهای قطعی نوشته می‌شوند",
    "first_seen_at": "نخستین دیدار",
    # products
    "canonical_name": "نامِ نرمال‌شده‌ی یکتا",
    "brand": "برند (استخراج‌شده از نام)",
    "category": "دسته",
    "pack_size_milli": "اندازه‌ی بسته ×۱۰۰۰ (از نام)",
    "pack_unit": "واحدِ بسته",
    "is_useless": "پرچمِ «نامِ بی‌معنا» (مثلاً «متفرقه»)",
    "last_unit_cost_rial": "آخرین بهای واحدِ شناخته‌شده به ریال",
    "alias_norm": "نامِ نرمال‌شده‌ی مترادف",
    "alias_raw": "نامِ خامِ مترادف",
    # orders
    "order_key": "کلیدِ یکتای سر: «دوره/شماره» (مهاجرت ۱۸)",
    "order_period": "دوره (سالِ ISO تاریخِ خط)",
    "order_number": "شماره‌ی نرمال‌شده‌ی فاکتور برای نمایش",
    "order_date": "تاریخِ فاکتور = کمینه‌ی تاریخِ خطوط",
    "gross_rial": "جمعِ خطوطِ فروش به ریال",
    "returns_rial": "جمعِ برگشت‌ها (مثبت) به ریال",
    "net_rial": "ناخالص − برگشت",
    "line_count": "شمارِ خطوطِ وصل‌شده",
    "branch": "شعبه", "salesperson": "فروشنده", "channel": "کانال فروش", "region": "منطقه",
    # order_lines
    "line_uid": "هویتِ پایدارِ خط: فاکتوردار = دوره+فاکتور+کالا+نوع+ترتیب؛ بی‌فاکتور = فایل+ردیف",
    "order_id": "سرِ فاکتور (NULL برای فایلِ بی‌فاکتور)",
    "line_date": "تاریخِ خط (ISO)",
    "quantity_milli": "مقدار ×۱۰۰۰",
    "unit_price_rial": "قیمتِ واحد به ریال",
    "gross_amount_rial": "مبلغِ ناخالصِ پیش از تخفیف به ریال",
    "discount_rate_bp": "نرخِ تخفیف (bp) وقتی ستونِ تخفیف نسبتی است",
    "gross_profit_rial": "سودِ ناخالصِ خط = درآمد − بها؛ NULL بدون بها",
    "is_return": "خطِ برگشت از فروش",
    "source_row": "شماره‌ی ردیفِ منبع",
    # product_cost_history
    "unit_cost_rial": "بهای واحد به ریال",
    "effective_from": "از این تاریخ معتبر (ISO)",
    "effective_to": "تا این تاریخ (NULL = تا اطلاعِ بعدی)",
    "source_batch_id": "بارگذاریِ منبعِ بها",
    # customer_features
    "feature_version": "نسخه‌ی تعریفِ ویژگی‌ها (تغییرِ معنا ⇒ +۱)",
    "n_orders": "شمار خرید (فاکتورِ یکتا + خطوطِ بی‌فاکتور)",
    "n_lines": "شمار خطوط",
    "monetary_rial": "جمعِ خرید به ریال (درآمد، نه سود)",
    "aov_rial": "میانگینِ ارزشِ سفارش به ریال",
    "recency_days": "روز از آخرین خرید تا `as_of`",
    "tenure_days": "روز از نخستین خرید تا `as_of`",
    "avg_gap_days": "میانگینِ فاصله‌ی خرید (روز)",
    "expected_gap_days": "فاصله‌ی موردِ انتظار (روز)",
    "overdue_days": "روزهای عقب‌افتادگی از آهنگِ شخصی",
    "p_alive_bp": "احتمالِ زنده‌بودن (bp)",
    "clv_rial": "CLV درآمدیِ ۱۲ ماهه به ریال",
    "segment": "سگمنتِ RFM",
    "lifecycle_state": "حالتِ چرخه‌ی عمر (§۱۱)",
    "cycle_status": "وضعیتِ چرخه‌ی خرید: عقب‌افتاده / نزدیک / در مسیر",
    "top_product": "پرفروش‌ترین کالای مشتری",
    "value_at_risk_rial": "ارزشِ در معرضِ خطر (درآمدی) به ریال",
    "clv_gp_90d_rial": "CLV سودمحور ۹۰ روزه", "clv_gp_180d_rial": "CLV سودمحور ۱۸۰ روزه",
    "clv_gp_365d_rial": "CLV سودمحور ۳۶۵ روزه", "clv_gp_365d_low_rial": "کرانِ پایینِ بازه‌ی ۳۶۵ روزه",
    "clv_gp_365d_high_rial": "کرانِ بالای بازه‌ی ۳۶۵ روزه",
    "clv_gp_basis": "`gross_profit` / `blocked` (نبودِ بها)",
    "clv_model_version": "نسخه‌ی مدلِ CLV",
    "whale_probability_bp": "احتمالِ نهنگِ آینده (bp)؛ NULL = مدلی فعال نیست",
    "whale_model_run_id": "اجرای مدلی که این امتیاز را داد",
    "churn_probability_bp": "احتمالِ ریزش (bp)", "churn_model_run_id": "اجرای مدلِ ریزش",
    "replenish_probability_bp": "احتمالِ تکرارِ خرید (bp)", "replenish_model_run_id": "اجرای مدلِ تکرار",
    "scored_at": "زمانِ امتیازدهی",
    "full_price_share_bp": "سهمِ خریدِ تمام‌قیمت (bp)؛ NULL = فایل ستونِ تخفیف نداشت",
    "full_price_lines": "شمارِ خطوطِ مبنای سهمِ بالا",
    # lifecycle events
    "from_state": "حالتِ قبلی", "to_state": "حالتِ تازه",
    # opportunity_runs
    "engine_version": "نسخه‌ی موتور",
    "candidates_generated": "نامزدهای تولیدشده", "candidates_filtered": "نامزدهای ردشده در فیلترها",
    "opportunities_created": "فرصت‌های تازه", "opportunities_refreshed": "فرصت‌های به‌روزشده",
    "opportunities_superseded": "فرصت‌هایی که دیگر مصداق ندارند", "opportunities_expired": "منقضی‌شده‌ها",
    "opportunity_runs.notes_json": "`skipped_filters`, `capped_out`, `fatigue_reference_ts`, `feature_basis_diff`",
    # opportunities
    "dedupe_key": "کلیدِ یکتای فرصت (مشتری × نوع × کالا)",
    "generator": "مولدی که فرصت را ساخت", "generator_version": "نسخه‌ی مولد",
    "title_fa": "عنوان", "action_fa": "اقدامِ پیشنهادی", "message_fa": "پیشنهادِ متنِ پیام",
    "score_rial": "امتیازِ رتبه‌بندی به ریال (ارزش × ضریبِ اثر)",
    "value_kind": "نوعِ ارزش: ارزش فرصت / ارزش در معرض خطر / رابطه‌ای",
    "probability_bp": "احتمالِ به‌کاررفته در ارزش (bp)",
    "confidence": "سطحِ اطمینان",
    "attributed_revenue_rial": "درآمدِ منتسب پس از اقدام", "incremental_revenue_rial": "درآمدِ افزوده (فقط با حکمِ علّی)",
    "experiment_id": "شناسه‌ی آزمایش",
    "opportunities.status": "open / accepted / snoozed / dismissed / done / superseded / expired",
    "status_reason_fa": "دلیلِ وضعیت", "assigned_to": "مسئول", "owner_hint": "پیشنهادِ مسئول",
    "snooze_until": "تا این تاریخ خاموش", "due_date": "مهلتِ اقدام", "assigned_date": "تاریخِ سپردن",
    "first_seen_run_id": "نخستین اجرایی که فرصت را دید", "last_seen_run_id": "آخرین اجرا",
    "seen_count": "چند اجرا این فرصت را دیده‌اند", "closed_at": "زمانِ بستن",
    "exposure_date": "تاریخِ تماس", "exposure_channel": "کانالِ تماس",
    # factors / events
    "code": "کدِ عامل/فیلتر", "outcome": "نتیجه: evidence / filter_pass / filter_block / filter_skip",
    "event_type": "نوعِ رخداد", "from_status": "وضعیتِ قبلی", "to_status": "وضعیتِ تازه",
    "at": "زمانِ رخداد",
    # offers
    "suggested_discount_bp": "تخفیفِ پیشنهادیِ سیستم (bp)",
    "tier": "طبقه‌ی مشتری از سهمِ تمام‌قیمت", "margin_bp_at_suggestion": "حاشیه در لحظه‌ی پیشنهاد (bp)",
    "floor_bp_at_suggestion": "کفِ حاشیه در لحظه‌ی پیشنهاد (bp)", "margin_basis": "مبنای حاشیه",
    "margin_key": "کلیدِ مبنای حاشیه (کالا/دسته/مشتری)", "label_basis": "مبنای برچسب (مشاهده‌ای، نه علّی)",
    "decided_by": "چه کسی تصمیم گرفت", "decided_at": "زمانِ تصمیم", "decision_note_fa": "یادداشتِ تصمیم",
    # campaigns
    "holdout_pct": "درصدِ گروهِ کنترل", "analysis_window_days": "طولِ پنجره‌ی سنجش (روز)",
    "primary_metric": "سنجه‌ی اصلی", "window_start": "آغازِ پنجره‌ی سنجش", "window_end": "پایانِ پنجره",
    "created_by": "سازنده", "stratum": "لایه‌ی تصادفی‌سازی", "exposure_at": "مهرِ تماسِ واقعی (اکسل/پیامک)",
    "exported_at": "زمانِ خروجیِ اکسل", "raw_customer_key": "کلیدِ خامِ مشتری در لحظه‌ی ساخت",
    "message_text": "متنِ پیامِ فرستاده‌شده", "provider": "درگاهِ پیامک", "provider_message_id": "شناسه‌ی درگاه",
    "sent_at": "زمانِ ارسال", "dry_run": "پیش‌نمایش (بدون ارسالِ واقعی)",
    "n_treatment": "شمارِ بازوی آزمایش", "n_control": "شمارِ بازوی کنترل",
    "conv_treatment": "تبدیل در آزمایش", "conv_control": "تبدیل در کنترل",
    "computed_at": "زمانِ محاسبه",
    # uplift snapshots
    "cell_kind": "نوعِ اقدامِ سلول", "cell_state": "حالتِ چرخه‌ی عمرِ سلول",
    "uplift_bp": "اثرِ منقبض‌شده (bp)", "raw_uplift_bp": "اثرِ خامِ اندازه‌گیری‌شده (bp)",
    "ci_low_bp": "کرانِ پایینِ بازه (bp)", "ci_high_bp": "کرانِ بالای بازه (bp)",
    # suppressions
    "scope": "دامنه‌ی انصراف", "opted_out_at": "زمانِ انصراف", "revoked_at": "زمانِ پس‌گرفتن (NULL = فعال)",
    # model_runs
    "model_key": "کلیدِ مدل (whale/churn/…)", "model_kind": "نوعِ مدل", "model_version": "نسخه‌ی مدل",
    "train_start": "آغازِ دوره‌ی آموزش", "train_end": "پایانِ آموزش", "validate_start": "آغازِ holdout",
    "validate_end": "پایانِ holdout", "n_train": "شمارِ نمونه‌ی آموزش", "n_train_positives": "مثبت‌های آموزش",
    "n_validate": "شمارِ نمونه‌ی holdout", "n_validate_positives": "مثبت‌های holdout",
    "data_hash": "هشِ داده‌ی آموزش", "code_version": "نسخه‌ی کد", "params_json": "پارامترها",
    "metrics_json": "سنجه‌ها (AUC، کالیبراسیون…)", "calibration_json": "آرتیفکتِ کالیبراسیون",
    "coefficients_json": "ضرایبِ مدل (خودِ مدل)", "feature_schema_json": "طرح‌واره‌ی ویژگی‌ها",
    "feature_schema_version": "نسخه‌ی طرح‌واره", "drift_baseline_json": "خط‌پایه‌ی انحراف",
    "promoted": "فعال روی داده‌ی واقعی", "promoted_at": "زمانِ فعال‌سازی", "promoted_by": "چه کسی فعال کرد",
    "rolled_back_at": "زمانِ بازگشت", "rollback_of_run_id": "به‌جای کدام اجرا برگشت",
    "n_scored": "شمارِ امتیازدهی‌شده", "last_scored_at": "آخرین امتیازدهی",
    "error_codes_json": "کدهای خطای ثبت‌شده", "matched_product": "کالای تطبیق‌شده",
    # jobs
    "started_at": "آغاز", "finished_at": "پایان", "attempt": "شماره‌ی تلاش", "max_attempts": "سقفِ تلاش",
    "next_retry_at": "زمانِ تلاشِ بعدی", "error_type": "نوعِ خطا", "error_text": "متنِ خطا",
    "result_json": "نتیجه‌ی کار", "correlation_id": "شناسه‌ی همبستگیِ لاگ",
    "scope_key": "دامنه‌ی اجاره (مثلاً `default|2025-01-01`)", "holder": "دارنده‌ی اجاره",
    "released_at": "زمانِ آزادشدن", "takeovers": "چند بار اجاره‌ی مرده تصاحب شد",
    # settings / audit
    "key": "کلیدِ تنظیم", "action": "کارِ حساس (خروجی، ارسال، تغییرِ سیاست…)",
    "entity_type": "نوعِ موجودیت", "entity_id": "شناسه‌ی موجودیت", "payload_json": "جزئیات",
    "source_ip": "IP درخواست", "row_count": "شمارِ ردیف‌های بیرون‌رفته",
    "lines_count": "شمارِ خطوط", "orders_count": "شمارِ سفارش‌ها", "lines_with_cost": "خطوطِ دارای بها",
    "overdue_ratio": "نسبتِ عقب‌افتادگی", "blocked_reason_code": "کدِ دلیلِ مسدودشدن",
    "blocked_reason_fa": "دلیلِ مسدودشدن", "status_detail_fa": "جزئیاتِ وضعیت", "assigned_at": "زمانِ سپردن",
    "run_id": "اجرا",
}

_STATUS_VOCAB = {
    "opportunities": "`status`: open / accepted / snoozed / dismissed / done / superseded / expired",
    "import_reconciliation": "`status`: OK / WARN / MISMATCH / SKIPPED",
    "import_batches": "`reconcile_status`: RECONCILED / RECONCILED_WITH_WARNINGS / MISMATCH / BLOCKED",
    "campaigns": "`status`: draft / active / closed",
    "job_runs": "`status`: running / succeeded / failed / dead",
}


def _fallback(column) -> str:
    name = column.name
    if column.primary_key:
        return "کلید اصلی"
    if column.foreign_keys:
        target = sorted(fk.column.table.name for fk in column.foreign_keys)[0]
        return f"ارجاع به `{target}`"
    if name.endswith("_rial"):
        return "مبلغ به ریال (عدد صحیح)"
    if name.endswith("_bp"):
        return "نسبت به پایه‌ی ده‌هزارم (bp)"
    if name.endswith("_milli"):
        return "مقدار ×۱۰۰۰ (عدد صحیح)"
    if name.endswith("_json"):
        return "JSON متنی"
    if name.endswith("_at"):
        return "زمانِ یونیکس (ثانیه)"
    if name.endswith("_date"):
        return "تاریخ ISO (YYYY-MM-DD)"
    if name.startswith("is_"):
        return "پرچمِ بولی"
    if name.endswith("_fa"):
        return "متنِ فارسی"
    return ""


def _column_doc(table: str, column) -> str:
    return COLUMN_DOCS.get(f"{table}.{column.name}") or COLUMN_DOCS.get(column.name) or _fallback(column)


def _keys(column, table) -> str:
    parts = []
    if column.primary_key:
        parts.append("PK")
    for fk in column.foreign_keys:
        parts.append(f"FK→`{fk.column.table.name}`")
    for constraint in table.constraints:
        if constraint.__class__.__name__ == "UniqueConstraint" and column.name in [c.name for c in constraint.columns]:
            parts.append("UQ")
            break
    if column.index:
        parts.append("IX")
    return " ".join(parts)


def _legacy_tables() -> list[tuple[str, list[tuple[str, str]]]]:
    from api.persistence import _ADDED_COLUMNS, _SCHEMA

    out = []
    for name, body in re.findall(r"CREATE TABLE IF NOT EXISTS (\w+) \((.*?)\);", _SCHEMA, re.S):
        columns = []
        for line in body.strip().splitlines():
            token = line.strip().rstrip(",")
            if not token or token.upper().startswith(("PRIMARY", "UNIQUE", "FOREIGN")):
                continue
            col, _, rest = token.partition(" ")
            columns.append((col, rest.split(" ")[0] if rest else ""))
        for table, col, ddl in _ADDED_COLUMNS:
            if table == name:
                columns.append((col, ddl))
        out.append((name, columns))
    return out


def render_data_dictionary() -> str:
    from mktcore.db import Base, models  # noqa: F401
    from mktcore.db.migrations import CANONICAL_SCHEMA_VERSION

    docs = {}
    for mapper in Base.registry.mappers:
        text = (mapper.class_.__doc__ or "").strip()
        docs[mapper.local_table.name] = text.split("\n\n")[0].replace("\n", " ").strip()

    lines = [
        "# فرهنگِ داده (Data Dictionary)",
        "",
        "سند §۳۶. **از کد تولید می‌شود** (`tools/gen_reference_docs.py`) و با",
        "`tests/test_docs_drift.py` به `Base.metadata` پین شده: هر جدول و ستونِ لایه‌ی canonical",
        "اینجا هست، وگرنه تست می‌شکند. توضیح‌ها در همان اسکریپت نگه‌داری می‌شوند.",
        "",
        f"**نسخه‌ی طرح‌واره‌ی canonical:** `CANONICAL_SCHEMA_VERSION = {CANONICAL_SCHEMA_VERSION}`",
        "(`src/mktcore/db/migrations.py`؛ جدولِ `schema_migrations` نسخه‌های اعمال‌شده را دارد).",
        "`PRAGMA user_version` لایه‌ی legacy در ۲ می‌ماند.",
        "",
        "## قراردادهای سراسری",
        "",
        "* **پول همیشه ریالِ صحیح** (`*_rial`)؛ واحدِ نمایش فقط در لایه‌ی API اعمال می‌شود. هیچ float پولی در دیتابیس نیست.",
        "* **نسبت‌ها در پایه‌ی ده‌هزارم** (`*_bp`؛ ۱۰۰۰۰ = ۱۰۰٪). **مقدار ×۱۰۰۰** (`*_milli`).",
        "* **تاریخ** رشته‌ی ISO `YYYY-MM-DD` (`*_date`, `line_date`, `as_of_date`)؛ **زمان** یونیکسِ ثانیه (`*_at`).",
        "* **`NULL` یعنی «نامعلوم/سنجیده نشد»، نه صفر** — بها، سود، احتمالِ مدل، سهمِ تمام‌قیمت.",
        "* `business_id` روی هر جدولِ داده: داده‌ی نمونه در کسب‌وکارِ `sample` می‌نشیند، نه `default`.",
        "* جدول‌های **افزودنی** (رخدادها، گذارها، نسخه‌های نگاشت، ممیزی) هرگز به‌روز یا حذف نمی‌شوند.",
        "",
    ]
    covered: set[str] = set()
    for title, names in TABLE_GROUPS:
        lines += [f"## {title}", ""]
        for name in names:
            table = Base.metadata.tables[name]
            covered.add(name)
            lines += [f"### `{name}`", ""]
            if docs.get(name):
                lines += [docs[name], ""]
            if name in _STATUS_VOCAB:
                lines += [_STATUS_VOCAB[name], ""]
            lines += ["| ستون | نوع | NULL | کلید | توضیح |", "|---|---|---|---|---|"]
            for column in table.columns:
                lines.append(
                    f"| `{column.name}` | {column.type!s} | {'✓' if column.nullable else '—'} "
                    f"| {_keys(column, table)} | {_column_doc(name, column)} |"
                )
            lines.append("")
    leftovers = sorted(set(Base.metadata.tables) - covered)
    if leftovers:
        lines += ["## سایر جدول‌ها", ""]
        for name in leftovers:
            table = Base.metadata.tables[name]
            lines += [f"### `{name}`", "", docs.get(name, ""), "",
                      "| ستون | نوع | NULL | کلید | توضیح |", "|---|---|---|---|---|"]
            for column in table.columns:
                lines.append(
                    f"| `{column.name}` | {column.type!s} | {'✓' if column.nullable else '—'} "
                    f"| {_keys(column, table)} | {_column_doc(name, column)} |"
                )
            lines.append("")

    lines += [
        "## جدول‌های لایه‌ی legacy (دست‌نخورده)",
        "",
        "این جدول‌ها در `api/persistence.py` با DDL خام ساخته می‌شوند، در `Base.metadata`",
        "**نیستند** و هیچ مهاجرتِ canonical به آن‌ها دست نمی‌زند (`PRESERVE_CONTRACT.md`).",
        "",
    ]
    for name, columns in _legacy_tables():
        lines += [f"### `{name}`", "", "| ستون | نوع |", "|---|---|"]
        for col, ddl in columns:
            lines.append(f"| `{col}` | {ddl} |")
        lines.append("")
    lines += [
        "### `schema_migrations`",
        "",
        "| ستون | نوع |", "|---|---|", "| `version` | INTEGER (PK) |", "| `name` | TEXT |",
        "| `applied_at` | REAL |", "",
    ]
    return "\n".join(lines).rstrip() + "\n"


# ═══════════════════════════════════════════════════════════════ API_GUIDE
_INFRA_PATHS = {"/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"}


def _walk(routes) -> list:
    found: list = []
    for route in routes:
        included = getattr(route, "original_router", None)
        if included is not None:
            found.extend(_walk(included.routes))
            continue
        if hasattr(route, "methods") and hasattr(route, "path"):
            found.append(route)
            continue
        nested = getattr(route, "routes", None)
        if nested:
            found.extend(_walk(nested))
    return found


def route_pairs() -> list[tuple[str, str, object]]:
    from api.main import app

    out = []
    for route in _walk(app.routes):
        if route.path in _INFRA_PATHS:
            continue
        for method in sorted(route.methods or []):
            if method in {"HEAD", "OPTIONS"}:
                continue
            out.append((method, route.path, route))
    seen: set[tuple[str, str]] = set()
    unique = []
    for method, path, route in sorted(out, key=lambda x: (x[1], x[0])):
        if (method, path) not in seen:
            seen.add((method, path))
            unique.append((method, path, route))
    return unique


def _summary(route) -> str:
    doc = (getattr(route.endpoint, "__doc__", None) or "").strip()
    first = doc.split("\n\n")[0].replace("\n", " ").strip()
    return first.replace("|", "/")


def render_api_guide() -> str:
    from mktcore.security import (
        EXTRA_GUARDED_ROUTES,
        HEADER_NAME,
        OPEN_WRITE_ROUTES,
        WRITE_METHODS,
        route_key,
    )

    pairs = route_pairs()
    groups: dict[str, list] = {"v1": [], "legacy": []}
    for method, path, route in pairs:
        groups["v1" if path.startswith("/api/v1") else "legacy"].append((method, path, route))

    def guard(method: str, path: str) -> str:
        key = route_key(method, path)
        if key in OPEN_WRITE_ROUTES:
            return "باز (استثنای مستند)"
        if method in WRITE_METHODS or key in EXTRA_GUARDED_ROUTES:
            return "🔒 توکن"
        return "خواندنی"

    lines = [
        "# راهنمای API",
        "",
        "سند §۳۶. **از پیمایشِ مسیرهای FastAPI تولید می‌شود** (`tools/gen_reference_docs.py`) و با",
        "`tests/test_docs_drift.py` پین شده: هر جفتِ (متد، مسیر) که برنامه دارد اینجا هست.",
        "",
        "## گارد",
        "",
        f"وقتی `MKT_API_TOKEN` تنظیم باشد، هر مسیرِ نوشتنی ({', '.join(sorted(WRITE_METHODS))}) و مسیرهای",
        f"خواندنیِ فهرستِ `EXTRA_GUARDED_ROUTES` توکن می‌خواهند (سرآیندِ `{HEADER_NAME}`)؛ استثناهای",
        "مکتوب در `OPEN_WRITE_ROUTES` بازند. بدون توکنِ تنظیم‌شده هیچ‌چیز بسته نیست (سازگاری عقب‌رو).",
        "منبعِ حقیقت: `src/mktcore/security.py`.",
        "",
        "| مسیرِ خواندنیِ گارددار | چرا |", "|---|---|",
    ]
    for key, why in EXTRA_GUARDED_ROUTES.items():
        lines.append(f"| `{key}` | {why.replace('|', '/')} |")
    lines += ["", "| مسیرِ نوشتنیِ باز | چرا |", "|---|---|"]
    for key, why in OPEN_WRITE_ROUTES.items():
        lines.append(f"| `{key}` | {why.replace('|', '/')} |")
    lines += [
        "",
        "## قراردادهای پاسخ",
        "",
        "* پول همیشه با شکلِ `{\"rial\": int | null, \"display_text\": str, \"display_currency\": str}` (`money_payload`)؛ هرگز float.",
        "* «سنجیده نشد» با `null` (نه صفر) و یک `note_fa` گفته می‌شود — ابعادِ کیفیت، فیلترهای `filter_skip`، سودِ بدون بها.",
        "* تاریخ‌ها ISO (`YYYY-MM-DD`)؛ زمان‌ها یونیکسِ ثانیه.",
        "* خطاها با `detail` فارسی (۴۰۰ ورودیِ نامعتبر، ۴۰۴ نبود، ۴۰۹ تداخل/اجرای هم‌زمان، ۴۲۲ اعتبارسنجی، ۴۰۱/۴۰۳ توکن).",
        "",
        "## مسیرهای `/api/v1` (لایه‌ی canonical)",
        "",
        "| متد | مسیر | گارد | چه می‌کند |", "|---|---|---|---|",
    ]
    for method, path, route in groups["v1"]:
        lines.append(f"| `{method}` | `{path}` | {guard(method, path)} | {_summary(route)} |")
    lines += [
        "",
        "## مسیرهای legacy (`/api/*`) — قراردادِ حفظ‌شده",
        "",
        "این مسیرها همان داشبورد و گزارش‌های پیش از ارتقا را می‌دهند (`PRESERVE_CONTRACT.md`).",
        "",
        "| متد | مسیر | گارد | چه می‌کند |", "|---|---|---|---|",
    ]
    for method, path, route in groups["legacy"]:
        lines.append(f"| `{method}` | `{path}` | {guard(method, path)} | {_summary(route)} |")
    lines += [
        "",
        "## کلیدهای اصلیِ چند پاسخِ پرمصرف",
        "",
        "| مسیر | کلیدهای اصلی |", "|---|---|",
        "| `GET /api/v1/imports/{batch_id}` | `reconcile_status`, `posted`, `blocked_by[]`, `checks[]` (L01–L13 با `status` OK/WARN/MISMATCH/SKIPPED), `quality_dimensions[]`, `quality_summary`, `mapping_signature`, `mapping_version` |",
        "| `GET /api/v1/data-quality` | `counts`, `dimensions[]` (نُه بُعدِ §۸.۵ از کلِ دفتر کل), `quality_summary`, `latest_batch`, `mismatches[]`, `latest_import_blocked`, `gaps[]` |",
        "| `GET /api/v1/feature-basis-diff` | `as_of`, `champion`, `challenger`, `columns{…mismatches, examples}`, `only_in_challenger`, `lifecycle_changes`, `identical`, `written=false` |",
        "| `GET /api/v1/source-mappings` | `items[]{signature, versions, latest_version, history[]{version, mapping, columns, file_currency, display_currency, batch_ids}}` |",
        "| `GET /api/v1/opportunities` | `items[]{id, kind, customer, expected_value, score_rial, offer, factors[], expires_at}`, `expiring_soon_count` |",
        "| `GET /api/v1/customers/{customer_id}` | هویت، آخرین عکسِ ویژگی، روند، تاریخچه‌ی خرید، گذارهای چرخه‌ی عمر |",
        "| `GET /api/v1/campaigns/{campaign_id}/report` | `verdict`, `observed_difference`, `incremental_*` فقط با حکمِ علّی |",
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"


# ═══════════════════════════════════════════════════════ SOURCE_MAPPING_GUIDE
_KW_BY_ROLE = {
    "DATE": ("DATE_KW",), "REVENUE": ("REVENUE_KW",), "QUANTITY": ("QTY_KW",),
    "UNIT_PRICE": ("UNIT_PRICE_KW",), "PRODUCT": ("PRODUCT_TEXT_KW", "PRODUCT_CODE_KW"),
    "CATEGORY": ("CATEGORY_KW",), "CUSTOMER_ID": ("CUSTOMER_KW",), "CHANNEL": ("CHANNEL_KW",),
    "REGION": ("REGION_KW",), "COST": ("COST_KW",), "ORDER_ID": ("ORDER_KW",),
    "DISCOUNT": ("DISCOUNT_KW",), "SALESPERSON": ("SALESPERSON_KW",), "BRANCH": ("BRANCH_KW",),
    "PHONE": ("PHONE_KW",), "EMAIL": ("EMAIL_KW",), "DOC_TYPE": ("DOC_TYPE_KW",),
    "GROSS_AMOUNT": ("GROSS_KW",),
}

_ROLE_USE = {
    "DATE": "پایه‌ی هر تحلیلِ زمانی؛ جلالی/میلادی هر دو خوانده می‌شود، در دفتر کل ISO",
    "REVENUE": "درآمدِ خط؛ منفی = برگشت (اگر «نوع سند» نباشد، حدس است)",
    "QUANTITY": "مقدار؛ با قیمتِ واحد، درآمدِ خالی را مشتق می‌کند",
    "UNIT_PRICE": "قیمتِ واحد",
    "PRODUCT": "نامِ کالا → کالای پایدار (نرمال‌سازیِ نام، اندازه‌ی بسته، برند)",
    "CATEGORY": "دسته‌ی کالا (شکافِ دسته، پیشنهاد)",
    "CUSTOMER_ID": "کلیدِ خامِ مشتری → مشتری پایدار (با شماره قوی‌تر می‌شود)",
    "CHANNEL": "کانالِ فروش", "REGION": "منطقه",
    "COST": "بهای تمام‌شده‌ی خط؛ بدون آن سود «سنجیده نشد»",
    "ORDER_ID": "شماره‌ی فاکتور → هویتِ پایدارِ خط و سرِ فاکتورِ دوره‌دار؛ بدون آن هر خط یک خرید است",
    "DISCOUNT": "تخفیف؛ مبلغی یا نسبتی — تفسیر یک‌بار در پاک‌سازی تعیین می‌شود",
    "SALESPERSON": "فروشنده", "BRANCH": "شعبه (شعبه‌ی محتملِ مشتری)",
    "PHONE": "موبایل → کلیدِ هویتِ قوی + کانالِ پیامک",
    "EMAIL": "ایمیل → کلیدِ هویتِ ذخیره‌شده (پیوند نمی‌سازد؛ L13)",
    "DOC_TYPE": "نوعِ سند: برگشتی‌های **اعلام‌شده** به‌جای حدس از علامت (C04، §۸.۵)",
    "GROSS_AMOUNT": "مبلغِ ناخالص پیش از تخفیف — فقط برای کنترلِ آشتی",
}


def render_source_mapping_guide() -> str:
    from mktcore.ingest import mapper
    from mktcore.ingest.currency import rial_per_unit
    from mktcore.ingest.schema import (
        CATEGORICAL_ROLES,
        NUMERIC_ROLES,
        REQUIRED_ROLES,
        ROLE_TO_COLUMN,
        SOURCE_ROW,
        ColumnRole,
    )
    from mktcore.locale_fa import ROLE_LABELS_FA

    lines = [
        "# راهنمای نگاشتِ منبع (Source Mapping Guide)",
        "",
        "سند §۳۶. **از کد تولید می‌شود** (`tools/gen_reference_docs.py`): نقش‌ها از",
        "`ingest/schema.py`، کلیدواژه‌های تشخیصِ خودکار از `ingest/mapper.py`، برچسب‌ها از",
        "`locale_fa.py`. `tests/test_docs_drift.py` هر `ColumnRole` و نقش‌های الزامی را اینجا پین می‌کند.",
        "",
        "## چرخه‌ی نگاشت",
        "",
        "1. فایل (اکسل/CSV) بارگذاری می‌شود؛ `SchemaMapper.auto_detect` هر ستون را با کلیدواژه و",
        f"   شکلِ محتوا امتیاز می‌دهد و بالای `AUTO_SELECT_THRESHOLD = {mapper.AUTO_SELECT_THRESHOLD}` خودکار انتخاب می‌کند.",
        "2. اپراتور نگاشت را تأیید/اصلاح می‌کند و **واحدِ پولِ فایل** و **واحدِ نمایش** را انتخاب می‌کند",
        "   (سیستم واحد را حدس نمی‌زند؛ واحدِ نامعلوم ثبت در دفتر کل را مسدود می‌کند — C00، §۸.۵).",
        "3. `SchemaMapper.apply` فریمِ استاندارد را می‌سازد (ستون‌های جدولِ زیر + ستونِ فنیِ",
        f"   `{SOURCE_ROW}` = شماره‌ی ردیفِ منبع)؛ نبودِ نقشِ الزامی خطا است.",
        "4. **حافظه‌ی نگاشت**: امضای سرستون (`header_signature` — مجموعه‌ی مرتبِ نام‌های نرمال‌شده،",
        "   مستقل از ترتیب و نگارش) در `mapping_profiles` (legacy، upsert) نگه داشته می‌شود تا فایلِ ماهِ بعد",
        "   با همان ساختار، همان نگاشت و واحدها را پیش‌فرض بگیرد.",
        "5. **نگاشتِ نسخه‌دار (برشِ اول)** — §۸.۲: هر نگاشتِ متفاوتی که روی یک امضا نهایی شد یک ردیفِ",
        "   افزودنی در `mapping_profile_versions` می‌گیرد (`version` از ۱)؛ همان نگاشت با همان واحدها",
        "   نسخه‌ی تازه نمی‌سازد (`mapping_hash`). هر بارگذاری — حتی مسدود — `mapping_signature` و",
        "   `mapping_version`ِ خودش را دارد و `GET /api/v1/source-mappings` تاریخچه را می‌دهد.",
        "",
        "## نقش‌ها",
        "",
        f"الزامی: {'، '.join(f'`{r.value}`' for r in REQUIRED_ROLES)} — بقیه اختیاری‌اند و نبودشان",
        "«سنجیده نشد» می‌سازد، نه خطا.",
        "",
        "| نقش | برچسب | ستونِ استاندارد | الزامی | نوع | کاربرد | کلیدواژه‌های تشخیصِ خودکار (نمونه) |",
        "|---|---|---|---|---|---|---|",
    ]
    for role in ColumnRole:
        kws: list[str] = []
        for attr in _KW_BY_ROLE.get(role.value, ()):
            kws += [k for k, _w in getattr(mapper, attr)]
        kind = "عددی" if role in NUMERIC_ROLES else "برچسبی" if role in CATEGORICAL_ROLES else "—"
        lines.append(
            f"| `{role.value}` | {ROLE_LABELS_FA.get(role.value, '')} | `{ROLE_TO_COLUMN[role]}` | "
            f"{'✓' if role in REQUIRED_ROLES else '—'} | {kind} | {_ROLE_USE.get(role.value, '')} | "
            f"{'، '.join(kws[:6])} |"
        )
    lines += [
        "",
        "## واحدِ پول",
        "",
        "| واحدِ فایل | ریال به‌ازای هر واحد |", "|---|---|",
        f"| `ریال` | {rial_per_unit('ریال')} |", f"| `تومان` | {rial_per_unit('تومان')} |",
        "",
        "واحد **انتخابِ اپراتور** است و روی دسته ثبت می‌شود (`file_currency`, `display_currency`,",
        "`rial_per_file_unit`). تبدیل بعد از اعتبارسنجی انجام می‌شود؛ ردیف‌های کنارگذاشته با مبلغِ",
        "اصلیِ فایل می‌مانند (کنترلِ L12 با واحدِ فایل به ریال می‌برد). تخفیفِ **مبلغی** هم تبدیل می‌شود،",
        "تخفیفِ نسبتی نه.",
        "",
        "## آنچه در نگاشت **حدس زده نمی‌شود**",
        "",
        "* واحدِ پول (C00 مسدود می‌کند) · قراردادِ علامتِ مبهم (C04 مسدود می‌کند) · تفسیرِ تخفیف زیرِ اطمینان.",
        "* ادغامِ مشتری با نام (فقط شماره و کلیدِ خام؛ ایمیل کلیدِ ذخیره‌شده است) — `IDENTITY` در",
        "  `FINANCIAL_CALCULATION_RULES.md` و کنترلِ L13.",
        "",
        "## آنچه §۸.۲ می‌خواهد و هنوز نیست",
        "",
        "| خواسته‌ی سند | وضعیت |", "|---|---|",
        "| شناسه‌ی `source_system` به‌ازای هر منبع | نیست — با یک منبعِ فروش، کلید فقط امضای سرستون است |",
        "| قواعدِ تبدیلِ نسخه‌دار به‌ازای منبع (فراتر از نقش→ستون) | نیست — تبدیل‌ها در `cleaning.py` سراسری‌اند |",
        "| گردشِ تأییدِ نگاشت (پیشنهاد → بازبینی → تصویب) | نیست — اپراتور در همان صفحه تأیید می‌کند و همان لحظه نسخه ثبت می‌شود |",
        "| بازپخشِ یک بارگذاری با نسخه‌ی مشخصِ نگاشت | نیست — نسخه ثبت می‌شود ولی مسیرِ «دوباره با نسخه‌ی n» وجود ندارد |",
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"


TARGETS = {
    "DATA_DICTIONARY.md": render_data_dictionary,
    "API_GUIDE.md": render_api_guide,
    "SOURCE_MAPPING_GUIDE.md": render_source_mapping_guide,
}


def main(argv: list[str]) -> int:
    check = "--check" in argv
    drift = []
    for name, render in TARGETS.items():
        path = DOCS / name
        content = render()
        if check:
            if not path.exists() or path.read_text(encoding="utf-8") != content:
                drift.append(name)
        else:
            path.write_text(content, encoding="utf-8")
            print(f"wrote {path.relative_to(ROOT)} ({len(content):,} chars)")
    if check and drift:
        print("این اسناد از کد عقب‌اند؛ `python tools/gen_reference_docs.py` را اجرا کنید: " + ", ".join(drift))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
