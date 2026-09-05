# فرهنگِ داده (Data Dictionary)

سند §۳۶. **از کد تولید می‌شود** (`tools/gen_reference_docs.py`) و با
`tests/test_docs_drift.py` به `Base.metadata` پین شده: هر جدول و ستونِ لایه‌ی canonical
اینجا هست، وگرنه تست می‌شکند. توضیح‌ها در همان اسکریپت نگه‌داری می‌شوند.

**نسخه‌ی طرح‌واره‌ی canonical:** `CANONICAL_SCHEMA_VERSION = 19`
(`src/mktcore/db/migrations.py`؛ جدولِ `schema_migrations` نسخه‌های اعمال‌شده را دارد).
`PRAGMA user_version` لایه‌ی legacy در ۲ می‌ماند.

## قراردادهای سراسری

* **پول همیشه ریالِ صحیح** (`*_rial`)؛ واحدِ نمایش فقط در لایه‌ی API اعمال می‌شود. هیچ float پولی در دیتابیس نیست.
* **نسبت‌ها در پایه‌ی ده‌هزارم** (`*_bp`؛ ۱۰۰۰۰ = ۱۰۰٪). **مقدار ×۱۰۰۰** (`*_milli`).
* **تاریخ** رشته‌ی ISO `YYYY-MM-DD` (`*_date`, `line_date`, `as_of_date`)؛ **زمان** یونیکسِ ثانیه (`*_at`).
* **`NULL` یعنی «نامعلوم/سنجیده نشد»، نه صفر** — بها، سود، احتمالِ مدل، سهمِ تمام‌قیمت.
* `business_id` روی هر جدولِ داده: داده‌ی نمونه در کسب‌وکارِ `sample` می‌نشیند، نه `default`.
* جدول‌های **افزودنی** (رخدادها، گذارها، نسخه‌های نگاشت، ممیزی) هرگز به‌روز یا حذف نمی‌شوند.

## بارگذاری و کیفیت (§۷.۱، §۸)

### `businesses`

واحد جداسازی داده. امروز یکی است؛ فردا چند مستأجر.

| ستون | نوع | NULL | کلید | توضیح |
|---|---|---|---|---|
| `id` | INTEGER | — | PK | کلید اصلی (خودافزا) |
| `slug` | VARCHAR(64) | — | UQ | شناسه‌ی متنیِ یکتا (`default` / `sample`) |
| `name` | VARCHAR(255) | — |  | نام |
| `display_currency` | VARCHAR(16) | — |  | واحدِ نمایش (تومان/ریال) — مبالغ در دیتابیس همیشه ریال‌اند |
| `created_at` | FLOAT | — |  | زمانِ ساختِ ردیف (یونیکس، ثانیه) |

### `import_batches`

یک بارگذاری فایل. `dataset_key` هشِ محتوای فایل است، پس یک فایل یکسان     همیشه همان دسته را می‌گیرد و تحلیل دوباره‌اش `revision` را بالا می‌برد.

`reconcile_status`: RECONCILED / RECONCILED_WITH_WARNINGS / MISMATCH / BLOCKED

| ستون | نوع | NULL | کلید | توضیح |
|---|---|---|---|---|
| `id` | INTEGER | — | PK | کلید اصلی (خودافزا) |
| `business_id` | INTEGER | — | FK→`businesses` UQ IX | کسب‌وکار (جداسازی داده؛ داده‌ی نمونه در کسب‌وکارِ جدا) |
| `dataset_key` | VARCHAR(64) | — | UQ IX | هشِ محتوای فایل — فایلِ یکسان همیشه همان کلید |
| `revision` | INTEGER | — | UQ | شماره‌ی نسخه‌ی همین `dataset_key` (تحلیلِ دوباره‌ی همان فایل +۱) |
| `session_id` | VARCHAR(64) | ✓ | IX | نشستِ تحلیل در لایه‌ی legacy |
| `filename` | VARCHAR(255) | ✓ |  | نامِ فایلِ بارگذاری‌شده |
| `sheet_name` | VARCHAR(255) | ✓ |  | نامِ برگه‌ی اکسل |
| `file_currency` | VARCHAR(16) | ✓ |  | واحدِ پولِ فایلِ منبع (انتخابِ اپراتور) |
| `display_currency` | VARCHAR(16) | ✓ |  | واحدِ نمایش (تومان/ریال) — مبالغ در دیتابیس همیشه ریال‌اند |
| `rial_per_file_unit` | INTEGER | ✓ |  | ضریبِ تبدیلِ واحدِ فایل به ریال (۱ یا ۱۰) |
| `rows_total` | INTEGER | ✓ |  | ردیف‌های خامِ فایل (سالم + نامعتبر + تکراری + برگشت) |
| `rows_clean` | INTEGER | ✓ |  | ردیف‌های خریدِ سالم |
| `rows_invalid` | INTEGER | ✓ |  | ردیف‌های با تاریخ/مبلغِ نامعتبر (قرنطینه) |
| `rows_duplicate` | INTEGER | ✓ |  | ردیف‌های کاملاً تکراری (قرنطینه) |
| `rows_returns` | INTEGER | ✓ |  | ردیف‌های برگشت از فروش |
| `lines_inserted` | INTEGER | — |  | خطوطِ تازه‌درج‌شده |
| `lines_updated` | INTEGER | — |  | خطوطِ موجودی که به‌روز شدند (صادراتِ هم‌پوشان) |
| `date_min` | VARCHAR(10) | ✓ |  | کمینه‌ی تاریخِ خطوطِ این دسته (ISO) |
| `date_max` | VARCHAR(10) | ✓ |  | بیشینه‌ی تاریخِ خطوطِ این دسته (ISO) |
| `net_sales_rial` | BIGINT | ✓ |  | فروشِ خالصِ این دسته به ریال |
| `validation_status` | VARCHAR(32) | ✓ |  | دروازه‌ی تحلیل: PASS / PASS_WITH_WARNINGS / FAIL |
| `reconcile_status` | VARCHAR(32) | ✓ |  | آشتیِ نوشتن: RECONCILED / RECONCILED_WITH_WARNINGS / MISMATCH / BLOCKED |
| `notes_json` | TEXT | ✓ |  | جزئیاتِ ساختاریافته‌ی افزودنی (JSON) |
| `mapping_signature` | VARCHAR(64) | ✓ | IX | امضای سرستونِ فایل (§۸.۲) |
| `mapping_version` | INTEGER | ✓ |  | نسخه‌ی نگاشتِ به‌کاررفته برای این دسته (§۸.۲) |
| `created_at` | FLOAT | — | IX | زمانِ ساختِ ردیف (یونیکس، ثانیه) |

### `import_rows_raw`

نمایشِ تغییرناپذیرِ ردیف‌های فایل ورودی — §۷.۱.

| ستون | نوع | NULL | کلید | توضیح |
|---|---|---|---|---|
| `id` | INTEGER | — | PK | کلید اصلی (خودافزا) |
| `business_id` | INTEGER | — | FK→`businesses` IX | کسب‌وکار (جداسازی داده؛ داده‌ی نمونه در کسب‌وکارِ جدا) |
| `batch_id` | INTEGER | — | FK→`import_batches` UQ IX | بارگذاری‌ای که این ردیف را نوشت/آخرین بار به‌روز کرد |
| `row_number` | INTEGER | ✓ | UQ IX | شماره‌ی ردیفِ منبع (۰-مبنا پس از سرستون) |
| `raw_payload_json` | TEXT | — |  | ردیفِ خام به‌صورت JSON (ستون→مقدار) |
| `row_hash` | VARCHAR(64) | — |  | هشِ محتوای ردیف |
| `parse_status` | VARCHAR(16) | — | IX | نتیجه‌ی خواندنِ ردیف |
| `error_codes_json` | TEXT | ✓ |  | کدهای خطای ثبت‌شده |
| `created_at` | FLOAT | — | IX | زمانِ ساختِ ردیف (یونیکس، ثانیه) |

### `import_quarantine`

ردیف‌هایی که وارد دفتر کل نشدند — §۷.۱.

| ستون | نوع | NULL | کلید | توضیح |
|---|---|---|---|---|
| `id` | INTEGER | — | PK | کلید اصلی (خودافزا) |
| `business_id` | INTEGER | — | FK→`businesses` IX | کسب‌وکار (جداسازی داده؛ داده‌ی نمونه در کسب‌وکارِ جدا) |
| `batch_id` | INTEGER | — | FK→`import_batches` UQ IX | بارگذاری‌ای که این ردیف را نوشت/آخرین بار به‌روز کرد |
| `row_number` | INTEGER | ✓ | UQ IX | شماره‌ی ردیفِ منبع (۰-مبنا پس از سرستون) |
| `raw_payload_json` | TEXT | — |  | ردیفِ خام به‌صورت JSON (ستون→مقدار) |
| `reason_code` | VARCHAR(64) | — | UQ IX | کدِ دلیل (پایدار، برای فیلتر) |
| `reason_detail_fa` | TEXT | — |  | دلیلِ کنارگذاشتن به فارسی |
| `suggested_resolution_fa` | TEXT | ✓ |  | راهِ اصلاحِ پیشنهادی برای اپراتور |
| `resolved_at` | FLOAT | ✓ |  | زمانِ رسیدگی (NULL = باز) |
| `resolved_by` | VARCHAR(128) | ✓ |  | چه کسی رسیدگی کرد |
| `resolution_note_fa` | TEXT | ✓ |  | یادداشتِ رسیدگی |
| `created_at` | FLOAT | — | IX | زمانِ ساختِ ردیف (یونیکس، ثانیه) |

### `import_reconciliation`

آشتی هر بارگذاری: «آنچه تحلیل گفت» در برابر «آنچه در دفتر کل نشست».

`status`: OK / WARN / MISMATCH / SKIPPED

| ستون | نوع | NULL | کلید | توضیح |
|---|---|---|---|---|
| `id` | INTEGER | — | PK | کلید اصلی (خودافزا) |
| `batch_id` | INTEGER | — | FK→`import_batches` UQ IX | بارگذاری‌ای که این ردیف را نوشت/آخرین بار به‌روز کرد |
| `check_id` | VARCHAR(32) | — | UQ | کدِ کنترل (L01…L13) |
| `label_fa` | VARCHAR(255) | — |  | برچسبِ فارسی |
| `expected_text` | VARCHAR(64) | ✓ |  | مقدارِ موردِ انتظار (از تحلیل/فایل) |
| `actual_text` | VARCHAR(64) | ✓ |  | مقدارِ دفتر کل |
| `delta_text` | VARCHAR(64) | ✓ |  | اختلاف |
| `tolerance_text` | VARCHAR(64) | ✓ |  | تلرانس |
| `status` | VARCHAR(16) | — |  | OK / WARN / MISMATCH / SKIPPED («سنجیده نشد») |
| `detail_fa` | TEXT | ✓ |  | توضیحِ فارسی |
| `created_at` | FLOAT | — |  | زمانِ ساختِ ردیف (یونیکس، ثانیه) |

### `mapping_profile_versions`

تاریخچه‌ی نگاشتِ ستون‌ها به‌ازای امضای سرستون (§۸.۲) — **افزودنی**.

| ستون | نوع | NULL | کلید | توضیح |
|---|---|---|---|---|
| `id` | INTEGER | — | PK | کلید اصلی (خودافزا) |
| `business_id` | INTEGER | — | FK→`businesses` UQ IX | کسب‌وکار (جداسازی داده؛ داده‌ی نمونه در کسب‌وکارِ جدا) |
| `signature` | VARCHAR(64) | — | UQ | امضای سرستون |
| `version` | INTEGER | — | UQ | شماره‌ی نسخه (به‌ازای امضا، از ۱) |
| `mapping_hash` | VARCHAR(64) | — | UQ | اثرِ انگشتِ نگاشت (نقش→ستون + واحدها) |
| `columns_json` | TEXT | — |  | سرستون‌های فایل (JSON) |
| `mapping_json` | TEXT | — |  | نگاشتِ نقش→نامِ ستون (JSON) |
| `file_currency` | VARCHAR(16) | ✓ |  | واحدِ پولِ فایلِ منبع (انتخابِ اپراتور) |
| `display_currency` | VARCHAR(16) | ✓ |  | واحدِ نمایش (تومان/ریال) — مبالغ در دیتابیس همیشه ریال‌اند |
| `created_at` | FLOAT | — | IX | زمانِ ساختِ ردیف (یونیکس، ثانیه) |

## دفتر کل فروش (§۷.۲)

### `customers`

مشتری پایدار. `canonical_key` کلیدی است که تحلیل با آن کار می‌کند، پس     اعداد داشبورد و دفتر کل روی یک تعریف از «مشتری» می‌ایستند.

| ستون | نوع | NULL | کلید | توضیح |
|---|---|---|---|---|
| `id` | INTEGER | — | PK | کلید اصلی (خودافزا) |
| `business_id` | INTEGER | — | FK→`businesses` UQ IX | کسب‌وکار (جداسازی داده؛ داده‌ی نمونه در کسب‌وکارِ جدا) |
| `canonical_key` | VARCHAR(128) | — | UQ IX | کلیدی که تحلیل با آن کار می‌کند (کلیدِ خامِ نخستین دیدار) |
| `display_name` | VARCHAR(255) | ✓ |  | نامِ نمایشی |
| `phone_e164` | VARCHAR(20) | ✓ | IX | شماره‌ی نرمال‌شده‌ی E.164 (`+98…`) |
| `email` | VARCHAR(255) | ✓ |  | ایمیلِ نرمال‌شده |
| `first_order_date` | VARCHAR(10) | ✓ |  | نخستین خرید (ISO) |
| `last_order_date` | VARCHAR(10) | ✓ |  | آخرین خرید (ISO) |
| `resolution_method` | VARCHAR(32) | — |  | چطور حل شد: `phone` / `raw_key` |
| `created_at` | FLOAT | — |  | زمانِ ساختِ ردیف (یونیکس، ثانیه) |
| `updated_at` | FLOAT | — |  | آخرین به‌روزرسانی (یونیکس، ثانیه) |

### `customer_keys`

شناسه‌های یک مشتری (کلید خام فایل، موبایل نرمال‌شده، ایمیل).

| ستون | نوع | NULL | کلید | توضیح |
|---|---|---|---|---|
| `id` | INTEGER | — | PK | کلید اصلی (خودافزا) |
| `business_id` | INTEGER | — | FK→`businesses` UQ IX | کسب‌وکار (جداسازی داده؛ داده‌ی نمونه در کسب‌وکارِ جدا) |
| `customer_id` | INTEGER | — | FK→`customers` IX | مشتری پایدار |
| `key_type` | VARCHAR(16) | — | UQ | نوعِ کلید: `raw_key` / `phone` / `email` |
| `key_value` | VARCHAR(255) | — | UQ | مقدارِ نرمال‌شده‌ی کلید |
| `confidence_bp` | INTEGER | — |  | اطمینانِ پیوند (bp) — فقط پیوندهای قطعی نوشته می‌شوند |
| `first_seen_at` | FLOAT | — |  | نخستین دیدار |

### `products`

محصول پایدار با نامِ نرمال‌شده. ویژگی‌ها **از داده** استخراج می‌شوند     (اندازه/واحد بسته)؛ هیچ فرضِ دامنه‌ای hardcode نشده چون کسب‌وکار چنددامنه است.

| ستون | نوع | NULL | کلید | توضیح |
|---|---|---|---|---|
| `id` | INTEGER | — | PK | کلید اصلی (خودافزا) |
| `business_id` | INTEGER | — | FK→`businesses` UQ IX | کسب‌وکار (جداسازی داده؛ داده‌ی نمونه در کسب‌وکارِ جدا) |
| `canonical_name` | VARCHAR(255) | — | UQ IX | نامِ نرمال‌شده‌ی یکتا |
| `display_name` | VARCHAR(255) | — |  | نامِ نمایشی |
| `category` | VARCHAR(255) | ✓ |  | دسته |
| `brand` | VARCHAR(255) | ✓ |  | برند (استخراج‌شده از نام) |
| `pack_size_milli` | BIGINT | ✓ |  | اندازه‌ی بسته ×۱۰۰۰ (از نام) |
| `pack_unit` | VARCHAR(16) | ✓ |  | واحدِ بسته |
| `last_unit_cost_rial` | BIGINT | ✓ |  | آخرین بهای واحدِ شناخته‌شده به ریال |
| `cost_confidence` | VARCHAR(16) | ✓ |  | اطمینانِ بها: `from_file` / `history_exact` / `history_imputed` |
| `created_at` | FLOAT | — |  | زمانِ ساختِ ردیف (یونیکس، ثانیه) |
| `updated_at` | FLOAT | — |  | آخرین به‌روزرسانی (یونیکس، ثانیه) |

### `product_aliases`

نام‌های خامی که به یک محصول اشاره می‌کنند (فاصله/نیم‌فاصله/ی‌وک متفاوت).

| ستون | نوع | NULL | کلید | توضیح |
|---|---|---|---|---|
| `id` | INTEGER | — | PK | کلید اصلی (خودافزا) |
| `business_id` | INTEGER | — | FK→`businesses` UQ IX | کسب‌وکار (جداسازی داده؛ داده‌ی نمونه در کسب‌وکارِ جدا) |
| `product_id` | INTEGER | — | FK→`products` IX | کالای پایدار |
| `alias_norm` | VARCHAR(255) | — | UQ IX | نامِ نرمال‌شده‌ی مترادف |
| `alias_raw` | VARCHAR(255) | — |  | نامِ خامِ مترادف |
| `source` | VARCHAR(32) | — |  | منبعِ ردیف (فایل/تاریخچه/دستی/تست) |
| `created_at` | FLOAT | — |  | زمانِ ساختِ ردیف (یونیکس، ثانیه) |

### `orders`

سرِ فاکتور. جمع‌ها از خطوط ساخته می‌شوند، پس همیشه با آن‌ها آشتی‌اند.

| ستون | نوع | NULL | کلید | توضیح |
|---|---|---|---|---|
| `id` | INTEGER | — | PK | کلید اصلی (خودافزا) |
| `business_id` | INTEGER | — | FK→`businesses` UQ IX | کسب‌وکار (جداسازی داده؛ داده‌ی نمونه در کسب‌وکارِ جدا) |
| `order_key` | VARCHAR(128) | — | UQ IX | کلیدِ یکتای سر: «دوره/شماره» (مهاجرت ۱۸) |
| `order_period` | VARCHAR(4) | ✓ |  | دوره (سالِ ISO تاریخِ خط) |
| `order_number` | VARCHAR(128) | ✓ | IX | شماره‌ی نرمال‌شده‌ی فاکتور برای نمایش |
| `customer_id` | INTEGER | ✓ | FK→`customers` IX | مشتری پایدار |
| `order_date` | VARCHAR(10) | — | IX | تاریخِ فاکتور = کمینه‌ی تاریخِ خطوط |
| `gross_rial` | BIGINT | — |  | جمعِ خطوطِ فروش به ریال |
| `returns_rial` | BIGINT | — |  | جمعِ برگشت‌ها (مثبت) به ریال |
| `net_rial` | BIGINT | — |  | ناخالص − برگشت |
| `discount_rial` | BIGINT | ✓ |  | تخفیفِ مبلغی به ریال (فقط وقتی ستونِ تخفیف مبلغی است) |
| `line_count` | INTEGER | — |  | شمارِ خطوطِ وصل‌شده |
| `branch` | VARCHAR(255) | ✓ |  | شعبه |
| `salesperson` | VARCHAR(255) | ✓ |  | فروشنده |
| `channel` | VARCHAR(255) | ✓ |  | کانال فروش |
| `region` | VARCHAR(255) | ✓ |  | منطقه |
| `batch_id` | INTEGER | ✓ | FK→`import_batches` IX | بارگذاری‌ای که این ردیف را نوشت/آخرین بار به‌روز کرد |
| `created_at` | FLOAT | — |  | زمانِ ساختِ ردیف (یونیکس، ثانیه) |
| `updated_at` | FLOAT | — |  | آخرین به‌روزرسانی (یونیکس، ثانیه) |

### `order_lines`

قلم فروش — دانه‌بندی پایه‌ی همه‌چیز.

| ستون | نوع | NULL | کلید | توضیح |
|---|---|---|---|---|
| `id` | INTEGER | — | PK | کلید اصلی (خودافزا) |
| `line_uid` | VARCHAR(64) | — | UQ IX | هویتِ پایدارِ خط: فاکتوردار = دوره+فاکتور+کالا+نوع+ترتیب؛ بی‌فاکتور = فایل+ردیف |
| `business_id` | INTEGER | — | FK→`businesses` IX | کسب‌وکار (جداسازی داده؛ داده‌ی نمونه در کسب‌وکارِ جدا) |
| `batch_id` | INTEGER | — | FK→`import_batches` IX | بارگذاری‌ای که این ردیف را نوشت/آخرین بار به‌روز کرد |
| `order_id` | INTEGER | ✓ | FK→`orders` IX | سرِ فاکتور (NULL برای فایلِ بی‌فاکتور) |
| `customer_id` | INTEGER | ✓ | FK→`customers` IX | مشتری پایدار |
| `product_id` | INTEGER | ✓ | FK→`products` IX | کالای پایدار |
| `line_date` | VARCHAR(10) | — | IX | تاریخِ خط (ISO) |
| `quantity_milli` | BIGINT | ✓ |  | مقدار ×۱۰۰۰ |
| `unit_price_rial` | BIGINT | ✓ |  | قیمتِ واحد به ریال |
| `revenue_rial` | BIGINT | — |  | درآمدِ خط به ریال؛ خطِ برگشتی منفی |
| `gross_amount_rial` | BIGINT | ✓ |  | مبلغِ ناخالصِ پیش از تخفیف به ریال |
| `discount_rial` | BIGINT | ✓ |  | تخفیفِ مبلغی به ریال (فقط وقتی ستونِ تخفیف مبلغی است) |
| `discount_rate_bp` | INTEGER | ✓ |  | نرخِ تخفیف (bp) وقتی ستونِ تخفیف نسبتی است |
| `cost_rial` | BIGINT | ✓ |  | بهای تمام‌شده به ریال؛ NULL = نامعلوم، نه صفر |
| `cost_confidence` | VARCHAR(24) | ✓ |  | اطمینانِ بها: `from_file` / `history_exact` / `history_imputed` |
| `gross_profit_rial` | BIGINT | ✓ |  | سودِ ناخالصِ خط = درآمد − بها؛ NULL بدون بها |
| `is_return` | BOOLEAN | — | IX | خطِ برگشت از فروش |
| `source_row` | INTEGER | ✓ |  | شماره‌ی ردیفِ منبع |
| `sheet_name` | VARCHAR(255) | ✓ |  | نامِ برگه‌ی اکسل |
| `raw_customer_key` | VARCHAR(255) | ✓ |  | کلیدِ خامِ مشتری در لحظه‌ی ساخت |
| `raw_product_name` | VARCHAR(255) | ✓ |  | نامِ خامِ کالا همان‌طور که در فایل بود |
| `revision` | INTEGER | — |  | شماره‌ی نسخه‌ی همین `dataset_key` (تحلیلِ دوباره‌ی همان فایل +۱) |
| `created_at` | FLOAT | — |  | زمانِ ساختِ ردیف (یونیکس، ثانیه) |
| `updated_at` | FLOAT | — |  | آخرین به‌روزرسانی (یونیکس، ثانیه) |

### `product_cost_history`

بهای هر کالا در طول زمان — منبعِ محاسبه‌ی سود ناخالص.

| ستون | نوع | NULL | کلید | توضیح |
|---|---|---|---|---|
| `id` | INTEGER | — | PK | کلید اصلی (خودافزا) |
| `business_id` | INTEGER | — | FK→`businesses` UQ IX | کسب‌وکار (جداسازی داده؛ داده‌ی نمونه در کسب‌وکارِ جدا) |
| `product_id` | INTEGER | — | FK→`products` UQ IX | کالای پایدار |
| `unit_cost_rial` | BIGINT | — |  | بهای واحد به ریال |
| `effective_from` | VARCHAR(10) | — | UQ IX | از این تاریخ معتبر (ISO) |
| `effective_to` | VARCHAR(10) | ✓ |  | تا این تاریخ (NULL = تا اطلاعِ بعدی) |
| `source` | VARCHAR(16) | — |  | منبعِ ردیف (فایل/تاریخچه/دستی/تست) |
| `note_fa` | TEXT | ✓ |  | یادداشتِ فارسی برای نمایش |
| `raw_product_name` | VARCHAR(255) | ✓ |  | نامِ خامِ کالا همان‌طور که در فایل بود |
| `created_at` | FLOAT | — |  | زمانِ ساختِ ردیف (یونیکس، ثانیه) |

## پرونده‌ی ۳۶۰ و چرخه‌ی عمر (§۱۰، §۱۱)

### `customer_features`

عکس ماندگارِ ویژگی‌های مشتری در یک زمان مشخص.

| ستون | نوع | NULL | کلید | توضیح |
|---|---|---|---|---|
| `id` | INTEGER | — | PK | کلید اصلی (خودافزا) |
| `business_id` | INTEGER | — | FK→`businesses` UQ IX | کسب‌وکار (جداسازی داده؛ داده‌ی نمونه در کسب‌وکارِ جدا) |
| `customer_id` | INTEGER | — | FK→`customers` UQ IX | مشتری پایدار |
| `as_of_date` | VARCHAR(10) | — | UQ IX | تاریخِ مرجعِ عکس/اجرا (آخرین روزِ داده، نه امروز) |
| `feature_version` | INTEGER | — | UQ | نسخه‌ی تعریفِ ویژگی‌ها (تغییرِ معنا ⇒ +۱) |
| `n_orders` | INTEGER | ✓ |  | شمار خرید (فاکتورِ یکتا + خطوطِ بی‌فاکتور) |
| `n_lines` | INTEGER | ✓ |  | شمار خطوط |
| `monetary_rial` | BIGINT | ✓ |  | جمعِ خرید به ریال (درآمد، نه سود) |
| `aov_rial` | BIGINT | ✓ |  | میانگینِ ارزشِ سفارش به ریال |
| `recency_days` | INTEGER | ✓ |  | روز از آخرین خرید تا `as_of` |
| `tenure_days` | INTEGER | ✓ |  | روز از نخستین خرید تا `as_of` |
| `avg_gap_days` | FLOAT | ✓ |  | میانگینِ فاصله‌ی خرید (روز) |
| `expected_gap_days` | FLOAT | ✓ |  | فاصله‌ی موردِ انتظار (روز) |
| `overdue_days` | FLOAT | ✓ |  | روزهای عقب‌افتادگی از آهنگِ شخصی |
| `p_alive_bp` | INTEGER | ✓ |  | احتمالِ زنده‌بودن (bp) |
| `clv_rial` | BIGINT | ✓ |  | CLV درآمدیِ ۱۲ ماهه به ریال |
| `segment` | VARCHAR(64) | ✓ |  | سگمنتِ RFM |
| `lifecycle_state` | VARCHAR(64) | ✓ |  | حالتِ چرخه‌ی عمر (§۱۱) |
| `cycle_status` | VARCHAR(64) | ✓ |  | وضعیتِ چرخه‌ی خرید: عقب‌افتاده / نزدیک / در مسیر |
| `top_product` | VARCHAR(255) | ✓ |  | پرفروش‌ترین کالای مشتری |
| `value_at_risk_rial` | BIGINT | ✓ |  | ارزشِ در معرضِ خطر (درآمدی) به ریال |
| `clv_gp_90d_rial` | BIGINT | ✓ |  | CLV سودمحور ۹۰ روزه |
| `clv_gp_180d_rial` | BIGINT | ✓ |  | CLV سودمحور ۱۸۰ روزه |
| `clv_gp_365d_rial` | BIGINT | ✓ |  | CLV سودمحور ۳۶۵ روزه |
| `clv_gp_365d_low_rial` | BIGINT | ✓ |  | کرانِ پایینِ بازه‌ی ۳۶۵ روزه |
| `clv_gp_365d_high_rial` | BIGINT | ✓ |  | کرانِ بالای بازه‌ی ۳۶۵ روزه |
| `clv_gp_basis` | VARCHAR(16) | ✓ |  | `gross_profit` / `blocked` (نبودِ بها) |
| `clv_model_version` | INTEGER | ✓ |  | نسخه‌ی مدلِ CLV |
| `whale_probability_bp` | INTEGER | ✓ |  | احتمالِ نهنگِ آینده (bp)؛ NULL = مدلی فعال نیست |
| `whale_model_run_id` | INTEGER | ✓ |  | اجرای مدلی که این امتیاز را داد |
| `churn_probability_bp` | INTEGER | ✓ |  | احتمالِ ریزش (bp) |
| `churn_model_run_id` | INTEGER | ✓ |  | اجرای مدلِ ریزش |
| `replenish_probability_bp` | INTEGER | ✓ |  | احتمالِ تکرارِ خرید (bp) |
| `replenish_model_run_id` | INTEGER | ✓ |  | اجرای مدلِ تکرار |
| `scored_at` | FLOAT | ✓ |  | زمانِ امتیازدهی |
| `full_price_share_bp` | INTEGER | ✓ |  | سهمِ خریدِ تمام‌قیمت (bp)؛ NULL = فایل ستونِ تخفیف نداشت |
| `full_price_lines` | INTEGER | ✓ |  | شمارِ خطوطِ مبنای سهمِ بالا |
| `created_at` | FLOAT | — |  | زمانِ ساختِ ردیف (یونیکس، ثانیه) |

### `customer_lifecycle_events`

گذارهای حالت چرخه‌ی عمر — فقط افزودنی.

| ستون | نوع | NULL | کلید | توضیح |
|---|---|---|---|---|
| `id` | INTEGER | — | PK | کلید اصلی (خودافزا) |
| `business_id` | INTEGER | — | FK→`businesses` UQ IX | کسب‌وکار (جداسازی داده؛ داده‌ی نمونه در کسب‌وکارِ جدا) |
| `customer_id` | INTEGER | — | FK→`customers` UQ IX | مشتری پایدار |
| `as_of_date` | VARCHAR(10) | — | UQ IX | تاریخِ مرجعِ عکس/اجرا (آخرین روزِ داده، نه امروز) |
| `from_state` | VARCHAR(32) | ✓ |  | حالتِ قبلی |
| `to_state` | VARCHAR(32) | — | UQ IX | حالتِ تازه |
| `reason_fa` | TEXT | ✓ |  | دلیلِ فارسی (برای انسان) |
| `basis` | VARCHAR(16) | ✓ |  | مبنای عدد (سود/درآمد/…) |
| `overdue_ratio` | FLOAT | ✓ |  | نسبتِ عقب‌افتادگی |
| `created_at` | FLOAT | — | IX | زمانِ ساختِ ردیف (یونیکس، ثانیه) |

## موتور فرصت‌ها (§۱۲–§۱۶، §۲۰.۳)

### `opportunity_runs`

یک اجرای موتور فرصت‌ها. بدون این، نمی‌شود گفت یک فرصت از کجا آمده.

| ستون | نوع | NULL | کلید | توضیح |
|---|---|---|---|---|
| `id` | INTEGER | — | PK | کلید اصلی (خودافزا) |
| `business_id` | INTEGER | — | FK→`businesses` IX | کسب‌وکار (جداسازی داده؛ داده‌ی نمونه در کسب‌وکارِ جدا) |
| `session_id` | VARCHAR(64) | ✓ | IX | نشستِ تحلیل در لایه‌ی legacy |
| `as_of_date` | VARCHAR(10) | — | IX | تاریخِ مرجعِ عکس/اجرا (آخرین روزِ داده، نه امروز) |
| `engine_version` | INTEGER | — |  | نسخه‌ی موتور |
| `candidates_generated` | INTEGER | — |  | نامزدهای تولیدشده |
| `candidates_filtered` | INTEGER | — |  | نامزدهای ردشده در فیلترها |
| `opportunities_created` | INTEGER | — |  | فرصت‌های تازه |
| `opportunities_refreshed` | INTEGER | — |  | فرصت‌های به‌روزشده |
| `opportunities_superseded` | INTEGER | — |  | فرصت‌هایی که دیگر مصداق ندارند |
| `opportunities_expired` | INTEGER | — |  | منقضی‌شده‌ها |
| `notes_json` | TEXT | ✓ |  | `skipped_filters`, `capped_out`, `fatigue_reference_ts`, `feature_basis_diff` |
| `created_at` | FLOAT | — | IX | زمانِ ساختِ ردیف (یونیکس، ثانیه) |

### `opportunities`

فرصت ماندگار با چرخه‌ی حیات.

`status`: open / accepted / snoozed / dismissed / done / superseded / expired

| ستون | نوع | NULL | کلید | توضیح |
|---|---|---|---|---|
| `id` | INTEGER | — | PK | کلید اصلی (خودافزا) |
| `business_id` | INTEGER | — | FK→`businesses` UQ IX | کسب‌وکار (جداسازی داده؛ داده‌ی نمونه در کسب‌وکارِ جدا) |
| `dedupe_key` | VARCHAR(128) | — | UQ IX | کلیدِ یکتای فرصت (مشتری × نوع × کالا) |
| `customer_id` | INTEGER | ✓ | FK→`customers` IX | مشتری پایدار |
| `product_id` | INTEGER | ✓ | FK→`products` IX | کالای پایدار |
| `kind` | VARCHAR(64) | — | IX | نوع |
| `generator` | VARCHAR(64) | — |  | مولدی که فرصت را ساخت |
| `generator_version` | INTEGER | — |  | نسخه‌ی مولد |
| `title_fa` | VARCHAR(255) | — |  | عنوان |
| `action_fa` | TEXT | — |  | اقدامِ پیشنهادی |
| `reason_fa` | TEXT | — |  | دلیلِ فارسی (برای انسان) |
| `message_fa` | TEXT | ✓ |  | پیشنهادِ متنِ پیام |
| `expected_value_rial` | BIGINT | — |  | ارزشِ موردِ انتظار به ریال (درآمدی، از قبل در احتمال ضرب‌شده) |
| `score_rial` | BIGINT | — | IX | امتیازِ رتبه‌بندی به ریال (ارزش × ضریبِ اثر) |
| `value_kind` | VARCHAR(32) | — |  | نوعِ ارزش: ارزش فرصت / ارزش در معرض خطر / رابطه‌ای |
| `probability_bp` | INTEGER | ✓ |  | احتمالِ به‌کاررفته در ارزش (bp) |
| `confidence` | VARCHAR(32) | ✓ |  | سطحِ اطمینان |
| `attributed_revenue_rial` | BIGINT | ✓ |  | درآمدِ منتسب پس از اقدام |
| `incremental_revenue_rial` | BIGINT | ✓ |  | درآمدِ افزوده (فقط با حکمِ علّی) |
| `experiment_id` | VARCHAR(64) | ✓ |  | شناسه‌ی آزمایش |
| `status` | VARCHAR(32) | — | IX | open / accepted / snoozed / dismissed / done / superseded / expired |
| `status_reason_fa` | TEXT | ✓ |  | دلیلِ وضعیت |
| `assigned_to` | VARCHAR(255) | ✓ | IX | مسئول |
| `owner_hint` | VARCHAR(255) | ✓ |  | پیشنهادِ مسئول |
| `snooze_until` | VARCHAR(10) | ✓ |  | تا این تاریخ خاموش |
| `due_date` | VARCHAR(10) | ✓ | IX | مهلتِ اقدام |
| `expires_at` | VARCHAR(10) | ✓ | IX | انقضا |
| `first_seen_run_id` | INTEGER | ✓ | FK→`opportunity_runs` | نخستین اجرایی که فرصت را دید |
| `last_seen_run_id` | INTEGER | ✓ | FK→`opportunity_runs` | آخرین اجرا |
| `seen_count` | INTEGER | — |  | چند اجرا این فرصت را دیده‌اند |
| `created_at` | FLOAT | — | IX | زمانِ ساختِ ردیف (یونیکس، ثانیه) |
| `updated_at` | FLOAT | — |  | آخرین به‌روزرسانی (یونیکس، ثانیه) |

### `opportunity_factors`

شواهد یک فرصت — چرا ساخته شد و از کدام فیلترها گذشت.

| ستون | نوع | NULL | کلید | توضیح |
|---|---|---|---|---|
| `id` | INTEGER | — | PK | کلید اصلی (خودافزا) |
| `opportunity_id` | INTEGER | — | FK→`opportunities` UQ IX | فرصت |
| `code` | VARCHAR(64) | — | UQ | کدِ عامل/فیلتر |
| `label_fa` | VARCHAR(255) | — |  | برچسبِ فارسی |
| `outcome` | VARCHAR(32) | — |  | نتیجه: evidence / filter_pass / filter_block / filter_skip |
| `detail_fa` | TEXT | ✓ |  | توضیحِ فارسی |
| `value_text` | VARCHAR(128) | ✓ |  | مقدار به‌صورت متن |
| `created_at` | FLOAT | — |  | زمانِ ساختِ ردیف (یونیکس، ثانیه) |

### `opportunity_events`

رخدادهای چرخه‌ی حیات — فقط افزودنی (append-only).

| ستون | نوع | NULL | کلید | توضیح |
|---|---|---|---|---|
| `id` | INTEGER | — | PK | کلید اصلی (خودافزا) |
| `opportunity_id` | INTEGER | — | FK→`opportunities` IX | فرصت |
| `event_type` | VARCHAR(32) | — |  | نوعِ رخداد |
| `from_status` | VARCHAR(32) | ✓ |  | وضعیتِ قبلی |
| `to_status` | VARCHAR(32) | ✓ |  | وضعیتِ تازه |
| `actor` | VARCHAR(255) | ✓ |  | چه کسی/چه چیزی این کار را کرد (کاربر/کار/سیستم) |
| `note_fa` | TEXT | ✓ |  | یادداشتِ فارسی برای نمایش |
| `payload_json` | TEXT | ✓ |  | جزئیات |
| `created_at` | FLOAT | — | IX | زمانِ ساختِ ردیف (یونیکس، ثانیه) |

### `opportunity_offers`

پیشنهادِ تخفیفِ یک فرصت و **تصمیمِ انسان** درباره‌اش — §۲۰.۳.

| ستون | نوع | NULL | کلید | توضیح |
|---|---|---|---|---|
| `id` | INTEGER | — | PK | کلید اصلی (خودافزا) |
| `business_id` | INTEGER | — | FK→`businesses` IX | کسب‌وکار (جداسازی داده؛ داده‌ی نمونه در کسب‌وکارِ جدا) |
| `opportunity_id` | INTEGER | — | FK→`opportunities` IX | فرصت |
| `suggested_discount_bp` | INTEGER | — |  | تخفیفِ پیشنهادیِ سیستم (bp) |
| `margin_bp_at_suggestion` | INTEGER | ✓ |  | حاشیه در لحظه‌ی پیشنهاد (bp) |
| `floor_bp_at_suggestion` | INTEGER | ✓ |  | کفِ حاشیه در لحظه‌ی پیشنهاد (bp) |
| `tier` | VARCHAR(16) | ✓ |  | طبقه‌ی مشتری از سهمِ تمام‌قیمت |
| `margin_basis` | VARCHAR(16) | ✓ |  | مبنای حاشیه |
| `margin_key` | VARCHAR(255) | ✓ |  | کلیدِ مبنای حاشیه (کالا/دسته/مشتری) |
| `status` | VARCHAR(16) | — | IX | وضعیتِ ردیف (واژگانِ هر جدول در توضیحِ همان جدول) |
| `decided_by` | VARCHAR(128) | ✓ |  | چه کسی تصمیم گرفت |
| `decided_at` | FLOAT | ✓ |  | زمانِ تصمیم |
| `decision_note_fa` | TEXT | ✓ |  | یادداشتِ تصمیم |
| `run_id` | INTEGER | ✓ | FK→`opportunity_runs` | اجرا |
| `created_at` | FLOAT | — |  | زمانِ ساختِ ردیف (یونیکس، ثانیه) |
| `updated_at` | FLOAT | — |  | آخرین به‌روزرسانی (یونیکس، ثانیه) |

## کمپین و آزمایش (§۲۲، §۲۹)

### `campaigns`

یک کمپین = یک آزمایش.

`status`: draft / active / closed

| ستون | نوع | NULL | کلید | توضیح |
|---|---|---|---|---|
| `id` | INTEGER | — | PK | کلید اصلی (خودافزا) |
| `business_id` | INTEGER | — | FK→`businesses` IX | کسب‌وکار (جداسازی داده؛ داده‌ی نمونه در کسب‌وکارِ جدا) |
| `name` | VARCHAR(255) | — |  | نام |
| `kind` | VARCHAR(64) | ✓ |  | نوع |
| `status` | VARCHAR(32) | — | IX | وضعیتِ ردیف (واژگانِ هر جدول در توضیحِ همان جدول) |
| `holdout_pct` | INTEGER | — |  | درصدِ گروهِ کنترل |
| `primary_metric` | VARCHAR(64) | — |  | سنجه‌ی اصلی |
| `analysis_window_days` | INTEGER | — |  | طولِ پنجره‌ی سنجش (روز) |
| `created_at` | FLOAT | — | IX | زمانِ ساختِ ردیف (یونیکس، ثانیه) |
| `exported_at` | FLOAT | ✓ |  | زمانِ خروجیِ اکسل |
| `closed_at` | FLOAT | ✓ |  | زمانِ بستن |
| `notes_json` | TEXT | ✓ |  | جزئیاتِ ساختاریافته‌ی افزودنی (JSON) |

### `campaign_members`

عضویت یک مشتری در یک کمپین، با بازوی تصادفی‌شده‌اش.

| ستون | نوع | NULL | کلید | توضیح |
|---|---|---|---|---|
| `id` | INTEGER | — | PK | کلید اصلی (خودافزا) |
| `campaign_id` | INTEGER | — | FK→`campaigns` UQ IX | کمپین |
| `customer_id` | INTEGER | — | FK→`customers` UQ IX | مشتری پایدار |
| `arm` | VARCHAR(16) | — |  | بازوی آزمایش: `treatment` / `control` |
| `stratum` | VARCHAR(64) | ✓ |  | لایه‌ی تصادفی‌سازی |
| `assigned_at` | FLOAT | — |  | زمانِ سپردن |
| `assigned_date` | VARCHAR(10) | — | IX | تاریخِ سپردن |
| `exposure_at` | FLOAT | ✓ |  | مهرِ تماسِ واقعی (اکسل/پیامک) |
| `exposure_date` | VARCHAR(10) | ✓ | IX | تاریخِ تماس |
| `exposure_channel` | VARCHAR(32) | ✓ |  | کانالِ تماس |
| `expected_value_rial` | BIGINT | ✓ |  | ارزشِ موردِ انتظار به ریال (درآمدی، از قبل در احتمال ضرب‌شده) |
| `offer_discount_bp` | INTEGER | ✓ |  | تخفیفِ مصوبِ پیشنهاد (bp)؛ NULL = بدون تخفیف |

### `campaign_opportunities`

پیوند عضو کمپین با فرصت‌هایی که باعث انتخابش شدند.

| ستون | نوع | NULL | کلید | توضیح |
|---|---|---|---|---|
| `id` | INTEGER | — | PK | کلید اصلی (خودافزا) |
| `campaign_id` | INTEGER | — | FK→`campaigns` UQ IX | کمپین |
| `opportunity_id` | INTEGER | — | FK→`opportunities` UQ IX | فرصت |
| `customer_id` | INTEGER | — | FK→`customers` IX | مشتری پایدار |
| `created_at` | FLOAT | — |  | زمانِ ساختِ ردیف (یونیکس، ثانیه) |

### `campaign_sends`

هر پیامی که برای یک کمپین فرستاده شد — دفترِ ارسال.

| ستون | نوع | NULL | کلید | توضیح |
|---|---|---|---|---|
| `id` | INTEGER | — | PK | کلید اصلی (خودافزا) |
| `business_id` | INTEGER | — | FK→`businesses` IX | کسب‌وکار (جداسازی داده؛ داده‌ی نمونه در کسب‌وکارِ جدا) |
| `campaign_id` | INTEGER | — | FK→`campaigns` UQ IX | کمپین |
| `customer_id` | INTEGER | — | FK→`customers` UQ IX | مشتری پایدار |
| `phone_e164` | VARCHAR(20) | ✓ |  | شماره‌ی نرمال‌شده‌ی E.164 (`+98…`) |
| `message_text` | TEXT | ✓ |  | متنِ پیامِ فرستاده‌شده |
| `segments` | INTEGER | — |  | سگمنت‌های تحلیلی (متن) |
| `cost_rial` | BIGINT | — |  | بهای تمام‌شده به ریال؛ NULL = نامعلوم، نه صفر |
| `provider` | VARCHAR(32) | — |  | درگاهِ پیامک |
| `dry_run` | BOOLEAN | — |  | پیش‌نمایش (بدون ارسالِ واقعی) |
| `status` | VARCHAR(32) | — | IX | وضعیتِ ردیف (واژگانِ هر جدول در توضیحِ همان جدول) |
| `status_detail_fa` | TEXT | ✓ |  | جزئیاتِ وضعیت |
| `provider_message_id` | VARCHAR(128) | ✓ |  | شناسه‌ی درگاه |
| `offer_discount_bp` | INTEGER | ✓ |  | تخفیفِ مصوبِ پیشنهاد (bp)؛ NULL = بدون تخفیف |
| `sent_at` | FLOAT | — | IX | زمانِ ارسال |

### `campaign_outcomes`

آنچه در پنجره‌ی سنجش واقعاً اتفاق افتاد — عکسِ ماندگار.

| ستون | نوع | NULL | کلید | توضیح |
|---|---|---|---|---|
| `id` | INTEGER | — | PK | کلید اصلی (خودافزا) |
| `campaign_id` | INTEGER | — | FK→`campaigns` UQ IX | کمپین |
| `customer_id` | INTEGER | — | FK→`customers` UQ IX | مشتری پایدار |
| `arm` | VARCHAR(16) | — | IX | بازوی آزمایش: `treatment` / `control` |
| `window_start` | VARCHAR(10) | — |  | آغازِ پنجره‌ی سنجش |
| `window_end` | VARCHAR(10) | — |  | پایانِ پنجره |
| `orders_count` | INTEGER | — |  | شمارِ سفارش‌ها |
| `lines_count` | INTEGER | — |  | شمارِ خطوط |
| `revenue_rial` | BIGINT | — |  | درآمدِ خط به ریال؛ خطِ برگشتی منفی |
| `cost_rial` | BIGINT | ✓ |  | بهای تمام‌شده به ریال؛ NULL = نامعلوم، نه صفر |
| `lines_with_cost` | INTEGER | — |  | خطوطِ دارای بها |
| `matched_product` | BOOLEAN | — |  | کالای تطبیق‌شده |
| `source_batch_id` | INTEGER | ✓ | FK→`import_batches` | بارگذاریِ منبعِ بها |
| `computed_at` | FLOAT | — |  | زمانِ محاسبه |

### `uplift_snapshots`

عکسِ جدولِ اثرِ آموخته‌شده در یک لحظه.

| ستون | نوع | NULL | کلید | توضیح |
|---|---|---|---|---|
| `id` | INTEGER | — | PK | کلید اصلی (خودافزا) |
| `business_id` | INTEGER | — | FK→`businesses` UQ IX | کسب‌وکار (جداسازی داده؛ داده‌ی نمونه در کسب‌وکارِ جدا) |
| `as_of_date` | VARCHAR(10) | — | UQ IX | تاریخِ مرجعِ عکس/اجرا (آخرین روزِ داده، نه امروز) |
| `cell_kind` | VARCHAR(64) | — | UQ | نوعِ اقدامِ سلول |
| `cell_state` | VARCHAR(64) | — | UQ | حالتِ چرخه‌ی عمرِ سلول |
| `n_treatment` | INTEGER | — |  | شمارِ بازوی آزمایش |
| `n_control` | INTEGER | — |  | شمارِ بازوی کنترل |
| `conv_treatment` | INTEGER | — |  | تبدیل در آزمایش |
| `conv_control` | INTEGER | — |  | تبدیل در کنترل |
| `raw_uplift_bp` | INTEGER | ✓ |  | اثرِ خامِ اندازه‌گیری‌شده (bp) |
| `uplift_bp` | INTEGER | ✓ |  | اثرِ منقبض‌شده (bp) |
| `ci_low_bp` | INTEGER | ✓ |  | کرانِ پایینِ بازه (bp) |
| `ci_high_bp` | INTEGER | ✓ |  | کرانِ بالای بازه (bp) |
| `basis` | VARCHAR(16) | — |  | مبنای عدد (سود/درآمد/…) |
| `is_useless` | BOOLEAN | — |  | پرچمِ «نامِ بی‌معنا» (مثلاً «متفرقه») |
| `created_at` | FLOAT | — | IX | زمانِ ساختِ ردیف (یونیکس، ثانیه) |

### `contact_suppressions`

دفترِ «با این مشتری تماس نگیر».

| ستون | نوع | NULL | کلید | توضیح |
|---|---|---|---|---|
| `id` | INTEGER | — | PK | کلید اصلی (خودافزا) |
| `business_id` | INTEGER | — | FK→`businesses` UQ IX | کسب‌وکار (جداسازی داده؛ داده‌ی نمونه در کسب‌وکارِ جدا) |
| `customer_id` | INTEGER | ✓ | FK→`customers` UQ IX | مشتری پایدار |
| `phone_e164` | VARCHAR(20) | ✓ | UQ IX | شماره‌ی نرمال‌شده‌ی E.164 (`+98…`) |
| `scope` | VARCHAR(64) | — | UQ | دامنه‌ی انصراف |
| `source` | VARCHAR(32) | — |  | منبعِ ردیف (فایل/تاریخچه/دستی/تست) |
| `reason_code` | VARCHAR(64) | ✓ |  | کدِ دلیل (پایدار، برای فیلتر) |
| `reason_fa` | TEXT | ✓ |  | دلیلِ فارسی (برای انسان) |
| `opted_out_at` | FLOAT | — |  | زمانِ انصراف |
| `revoked_at` | FLOAT | ✓ |  | زمانِ پس‌گرفتن (NULL = فعال) |
| `created_by` | VARCHAR(128) | ✓ |  | سازنده |
| `updated_at` | FLOAT | — |  | آخرین به‌روزرسانی (یونیکس، ثانیه) |

## مدل‌ها (§۲۶)

### `model_runs`

یک اجرای آموزشِ مدل — و **خودِ مدل**.

| ستون | نوع | NULL | کلید | توضیح |
|---|---|---|---|---|
| `id` | INTEGER | — | PK | کلید اصلی (خودافزا) |
| `business_id` | INTEGER | — | FK→`businesses` UQ IX | کسب‌وکار (جداسازی داده؛ داده‌ی نمونه در کسب‌وکارِ جدا) |
| `model_key` | VARCHAR(64) | — | UQ IX | کلیدِ مدل (whale/churn/…) |
| `model_kind` | VARCHAR(64) | — |  | نوعِ مدل |
| `model_version` | INTEGER | — | UQ | نسخه‌ی مدل |
| `code_version` | VARCHAR(64) | ✓ |  | نسخه‌ی کد |
| `feature_schema_version` | INTEGER | ✓ |  | نسخه‌ی طرح‌واره |
| `feature_schema_json` | TEXT | ✓ |  | طرح‌واره‌ی ویژگی‌ها |
| `params_json` | TEXT | ✓ |  | پارامترها |
| `train_start` | VARCHAR(10) | ✓ |  | آغازِ دوره‌ی آموزش |
| `train_end` | VARCHAR(10) | ✓ |  | پایانِ آموزش |
| `validate_start` | VARCHAR(10) | ✓ |  | آغازِ holdout |
| `validate_end` | VARCHAR(10) | ✓ |  | پایانِ holdout |
| `data_hash` | VARCHAR(64) | ✓ | IX | هشِ داده‌ی آموزش |
| `n_train` | INTEGER | ✓ |  | شمارِ نمونه‌ی آموزش |
| `n_validate` | INTEGER | ✓ |  | شمارِ نمونه‌ی holdout |
| `n_train_positives` | INTEGER | ✓ |  | مثبت‌های آموزش |
| `n_validate_positives` | INTEGER | ✓ |  | مثبت‌های holdout |
| `label_basis` | VARCHAR(32) | ✓ |  | مبنای برچسب (مشاهده‌ای، نه علّی) |
| `status` | VARCHAR(32) | — | IX | وضعیتِ ردیف (واژگانِ هر جدول در توضیحِ همان جدول) |
| `blocked_reason_code` | VARCHAR(64) | ✓ |  | کدِ دلیلِ مسدودشدن |
| `blocked_reason_fa` | TEXT | ✓ |  | دلیلِ مسدودشدن |
| `metrics_json` | TEXT | ✓ |  | سنجه‌ها (AUC، کالیبراسیون…) |
| `calibration_json` | TEXT | ✓ |  | آرتیفکتِ کالیبراسیون |
| `drift_baseline_json` | TEXT | ✓ |  | خط‌پایه‌ی انحراف |
| `coefficients_json` | TEXT | ✓ |  | ضرایبِ مدل (خودِ مدل) |
| `promoted` | BOOLEAN | — | IX | فعال روی داده‌ی واقعی |
| `promoted_at` | FLOAT | ✓ |  | زمانِ فعال‌سازی |
| `promoted_by` | VARCHAR(128) | ✓ |  | چه کسی فعال کرد |
| `rolled_back_at` | FLOAT | ✓ |  | زمانِ بازگشت |
| `rollback_of_run_id` | INTEGER | ✓ |  | به‌جای کدام اجرا برگشت |
| `last_scored_at` | FLOAT | ✓ |  | آخرین امتیازدهی |
| `n_scored` | INTEGER | — |  | شمارِ امتیازدهی‌شده |
| `note_fa` | TEXT | ✓ |  | یادداشتِ فارسی برای نمایش |
| `created_at` | FLOAT | — | IX | زمانِ ساختِ ردیف (یونیکس، ثانیه) |

## عملیات و امنیت (§۲۸، §۳۱)

### `job_runs`

یک اجرای کارِ زمان‌بندی‌شده: چه شد، چند بار تلاش شد، و کجا مُرد.

`status`: running / succeeded / failed / dead

| ستون | نوع | NULL | کلید | توضیح |
|---|---|---|---|---|
| `id` | INTEGER | — | PK | کلید اصلی (خودافزا) |
| `job_name` | VARCHAR(64) | — | IX | نامِ کارِ زمان‌بندی‌شده |
| `correlation_id` | VARCHAR(64) | — | IX | شناسه‌ی همبستگیِ لاگ |
| `status` | VARCHAR(24) | — | IX | وضعیتِ ردیف (واژگانِ هر جدول در توضیحِ همان جدول) |
| `attempt` | INTEGER | — |  | شماره‌ی تلاش |
| `max_attempts` | INTEGER | — |  | سقفِ تلاش |
| `started_at` | FLOAT | — | IX | آغاز |
| `finished_at` | FLOAT | ✓ |  | پایان |
| `next_retry_at` | FLOAT | ✓ | IX | زمانِ تلاشِ بعدی |
| `error_type` | VARCHAR(64) | ✓ |  | نوعِ خطا |
| `error_text` | TEXT | ✓ |  | متنِ خطا |
| `result_json` | TEXT | ✓ |  | نتیجه‌ی کار |
| `note_fa` | TEXT | ✓ |  | یادداشتِ فارسی برای نمایش |

### `job_leases`

اجاره‌ی اجرا: «این کار برای این دامنه، همین حالا دستِ یک نفر است».

| ستون | نوع | NULL | کلید | توضیح |
|---|---|---|---|---|
| `id` | INTEGER | — | PK | کلید اصلی (خودافزا) |
| `job_name` | VARCHAR(64) | — | UQ IX | نامِ کارِ زمان‌بندی‌شده |
| `scope_key` | VARCHAR(128) | — | UQ IX | دامنه‌ی اجاره (مثلاً `default|2025-01-01`) |
| `holder` | VARCHAR(128) | — |  | دارنده‌ی اجاره |
| `acquired_at` | FLOAT | — |  | زمانِ ثبتِ مشتری |
| `expires_at` | FLOAT | — |  | انقضا |
| `released_at` | FLOAT | ✓ |  | زمانِ آزادشدن |
| `takeovers` | INTEGER | — |  | چند بار اجاره‌ی مرده تصاحب شد |

### `app_settings`

تنظیمِ سیاست که **کاربر** می‌گذارد، نه سیستم حدس می‌زند.

| ستون | نوع | NULL | کلید | توضیح |
|---|---|---|---|---|
| `id` | INTEGER | — | PK | کلید اصلی (خودافزا) |
| `business_id` | INTEGER | — | FK→`businesses` UQ IX | کسب‌وکار (جداسازی داده؛ داده‌ی نمونه در کسب‌وکارِ جدا) |
| `key` | VARCHAR(64) | — | UQ IX | کلیدِ تنظیم |
| `value_text` | TEXT | — |  | مقدار به‌صورت متن |
| `note_fa` | TEXT | ✓ |  | یادداشتِ فارسی برای نمایش |
| `updated_at` | FLOAT | — |  | آخرین به‌روزرسانی (یونیکس، ثانیه) |

### `audit_events`

ردِ پای کارهای حساس: چه چیزی از سیستم بیرون رفت یا عوض شد، کِی، و از کجا.

| ستون | نوع | NULL | کلید | توضیح |
|---|---|---|---|---|
| `id` | INTEGER | — | PK | کلید اصلی (خودافزا) |
| `business_id` | INTEGER | ✓ | FK→`businesses` IX | کسب‌وکار (جداسازی داده؛ داده‌ی نمونه در کسب‌وکارِ جدا) |
| `at` | FLOAT | — | IX | زمانِ رخداد |
| `action` | VARCHAR(64) | — | IX | کارِ حساس (خروجی، ارسال، تغییرِ سیاست…) |
| `entity_type` | VARCHAR(32) | ✓ |  | نوعِ موجودیت |
| `entity_id` | VARCHAR(64) | ✓ | IX | شناسه‌ی موجودیت |
| `actor` | VARCHAR(128) | ✓ |  | چه کسی/چه چیزی این کار را کرد (کاربر/کار/سیستم) |
| `source_ip` | VARCHAR(64) | ✓ |  | IP درخواست |
| `row_count` | INTEGER | ✓ |  | شمارِ ردیف‌های بیرون‌رفته |
| `detail_fa` | TEXT | ✓ |  | توضیحِ فارسی |

## جدول‌های لایه‌ی legacy (دست‌نخورده)

این جدول‌ها در `api/persistence.py` با DDL خام ساخته می‌شوند، در `Base.metadata`
**نیستند** و هیچ مهاجرتِ canonical به آن‌ها دست نمی‌زند (`PRESERVE_CONTRACT.md`).

### `sessions`

| ستون | نوع |
|---|---|
| `id` | TEXT |
| `created_at` | REAL |
| `filename` | TEXT |
| `columns_json` | TEXT |
| `mapping_json` | TEXT |
| `analysis_json` | TEXT |
| `strategy_json` | TEXT |
| `campaign_json` | TEXT |
| `label` | TEXT |
| `archived_at` | REAL |
| `summary_json` | TEXT |
| `last_opened_at` | REAL |

### `jobs`

| ستون | نوع |
|---|---|
| `id` | TEXT |
| `session_id` | TEXT |
| `kind` | TEXT |
| `status` | TEXT |
| `progress` | REAL |
| `stage` | TEXT |
| `error` | TEXT |
| `result_json` | TEXT |
| `created_at` | REAL |
| `updated_at` | REAL |

### `outbox`

| ستون | نوع |
|---|---|
| `id` | INTEGER |
| `created_at` | REAL |
| `session_id` | TEXT |
| `kind` | TEXT |
| `audience` | TEXT |
| `customer_id` | TEXT |
| `phone` | TEXT |
| `message` | TEXT |
| `status` | TEXT |
| `provider` | TEXT |
| `dry_run` | INTEGER |

### `app_meta`

| ستون | نوع |
|---|---|
| `key` | TEXT |
| `value` | TEXT |
| `updated_at` | REAL |

### `mapping_profiles`

| ستون | نوع |
|---|---|
| `signature` | TEXT |
| `columns_json` | TEXT |
| `mapping_json` | TEXT |
| `file_currency` | TEXT |
| `display_currency` | TEXT |
| `created_at` | REAL |
| `updated_at` | REAL |
| `use_count` | INTEGER |

### `schema_migrations`

| ستون | نوع |
|---|---|
| `version` | INTEGER (PK) |
| `name` | TEXT |
| `applied_at` | REAL |
