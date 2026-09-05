# راهنمای API

سند §۳۶. **از پیمایشِ مسیرهای FastAPI تولید می‌شود** (`tools/gen_reference_docs.py`) و با
`tests/test_docs_drift.py` پین شده: هر جفتِ (متد، مسیر) که برنامه دارد اینجا هست.

## گارد

وقتی `MKT_API_TOKEN` تنظیم باشد، هر مسیرِ نوشتنی (DELETE, PATCH, POST, PUT) و مسیرهای
خواندنیِ فهرستِ `EXTRA_GUARDED_ROUTES` توکن می‌خواهند (سرآیندِ `X-API-Token`)؛ استثناهای
مکتوب در `OPEN_WRITE_ROUTES` بازند. بدون توکنِ تنظیم‌شده هیچ‌چیز بسته نیست (سازگاری عقب‌رو).
منبعِ حقیقت: `src/mktcore/security.py`.

| مسیرِ خواندنیِ گارددار | چرا |
|---|---|
| `GET /api/v1/campaigns/{campaign_id}/export` | فهرست شماره‌ی تماسِ کامل (نه ماسک‌شده) می‌دهد و ضمناً مهرِ تماس می‌زند — یعنی یک GET که وضعیت را عوض می‌کند. |
| `GET /api/export` | فایل اکسل با ستون «موبایل»؛ همان PIIِ خروجی کمپین، از مسیری دیگر. بستنِ یکی و بازگذاشتنِ دیگری یعنی هیچ‌کدام بسته نیست. |
| `GET /api/outbox` | سابقه‌ی پیامک‌های فرستاده‌شده با شماره‌ی خامِ گیرنده در ستون `phone`. |
| `GET /api/v1/contact-suppressions` | دفترِ «تماس نگیر»: شماره (ماسک‌شده) و نامِ مشتری‌هایی که انصراف داده‌اند — فهرستِ افرادِ مشخص، پس داده‌ی شخصی است. |
| `GET /api/v1/feature-basis-diff` | کلِ دفتر کل را می‌خواند و پرونده‌ی ۳۶۰ را دوباره می‌سازد (هزینه‌بر) و اعدادِ خریدِ تک‌تکِ مشتری‌ها را کنارِ شناسه‌شان برمی‌گرداند. |
| `GET /api/v1/quarantine` | ردیفِ خامِ فایلِ فروش را همان‌طور که بود برمی‌گرداند — با ستونِ موبایل و نامِ مشتری. شماره‌ها ماسک می‌شوند، ولی بقیه‌ی ردیف هم داده‌ی شخصی است. |

| مسیرِ نوشتنیِ باز | چرا |
|---|---|
| `POST /api/upload` | نقطه‌ی ورودِ کاربر است؛ بستنش یعنی بدون توکن اصلاً نمی‌شود فایلی داد. هزینه‌ی بیرونی ندارد و سقف حجم دارد. |
| `POST /api/sample` | داده‌ی نمونه‌ی مصنوعی؛ نه هزینه دارد نه داده‌ی واقعی. |
| `POST /api/analyze` | تحلیل محلی روی فایلِ خودِ کاربر؛ هزینه‌ی بیرونی ندارد. |
| `PATCH /api/session/{session_id}` | تغییر برچسبِ نشستِ خودِ کاربر. |
| `POST /api/v1/campaigns/{campaign_id}/refresh` | فقط نتیجه را از دفتر کل دوباره می‌خواند؛ چیزی نمی‌فرستد و پولی خرج نمی‌کند و خروجی‌اش idempotent است. |

## قراردادهای پاسخ

* پول همیشه با شکلِ `{"rial": int | null, "display_text": str, "display_currency": str}` (`money_payload`)؛ هرگز float.
* «سنجیده نشد» با `null` (نه صفر) و یک `note_fa` گفته می‌شود — ابعادِ کیفیت، فیلترهای `filter_skip`، سودِ بدون بها.
* تاریخ‌ها ISO (`YYYY-MM-DD`)؛ زمان‌ها یونیکسِ ثانیه.
* خطاها با `detail` فارسی (۴۰۰ ورودیِ نامعتبر، ۴۰۴ نبود، ۴۰۹ تداخل/اجرای هم‌زمان، ۴۲۲ اعتبارسنجی، ۴۰۱/۴۰۳ توکن).

## مسیرهای `/api/v1` (لایه‌ی canonical)

| متد | مسیر | گارد | چه می‌کند |
|---|---|---|---|
| `GET` | `/api/v1/campaigns` | خواندنی |  |
| `POST` | `/api/v1/campaigns` | 🔒 توکن | ساخت کمپین از فرصت‌های باز، با تخصیص تصادفیِ گروه کنترل. |
| `GET` | `/api/v1/campaigns/{campaign_id}` | خواندنی | جزئیات کمپین + گزارش اثر. |
| `POST` | `/api/v1/campaigns/{campaign_id}/close` | 🔒 توکن | بستن کمپین — پنجره‌ی سنجش دیگر به‌روز نمی‌شود. |
| `GET` | `/api/v1/campaigns/{campaign_id}/export` | 🔒 توکن | خروجی اکسل بازوی آزمایش — و ثبت لحظه‌ی تماس. |
| `POST` | `/api/v1/campaigns/{campaign_id}/refresh` | باز (استثنای مستند) | محاسبه‌ی دوباره‌ی نتیجه‌ها از دفتر کل (بدون انتظار برای بارگذاری بعدی). |
| `POST` | `/api/v1/campaigns/{campaign_id}/send` | 🔒 توکن | ارسال مستقیم پیامک به بازوی آزمایش. |
| `DELETE` | `/api/v1/contact-suppressions` | 🔒 توکن | پس گرفتن انصرافِ یک شماره. ردیف پاک نمی‌شود تا تاریخش بماند. |
| `GET` | `/api/v1/contact-suppressions` | 🔒 توکن | دفترِ «با این‌ها تماس نگیر». |
| `POST` | `/api/v1/contact-suppressions` | 🔒 توکن | ثبت انصراف با شماره — بدون نیاز به شناسه‌ی مشتری. |
| `POST` | `/api/v1/contact-suppressions/import` | 🔒 توکن | واردکردنِ چند شماره (لیستِ سیاهِ پنل) در یک تراکنش. شماره‌ی نامعتبر صریح رد می‌شود. |
| `GET` | `/api/v1/cost-coverage` | خواندنی | پوشش بها — پاسخِ «چرا سود محاسبه نشد؟». |
| `POST` | `/api/v1/costs` | 🔒 توکن | ثبت بهای کالاها — منبعِ محاسبه‌ی سود ناخالص. |
| `GET` | `/api/v1/customers` | خواندنی | فهرست مشتریان با آخرین عکسِ ویژگی‌های هرکدام. |
| `GET` | `/api/v1/customers/{customer_id}` | خواندنی | پرونده‌ی مشتری: هویت، آخرین ویژگی‌ها، روند ویژگی و تاریخچه‌ی خرید. |
| `DELETE` | `/api/v1/customers/{customer_id}/opt-out` | 🔒 توکن | پس گرفتن انصراف. ردیف پاک نمی‌شود تا تاریخش بماند. |
| `POST` | `/api/v1/customers/{customer_id}/opt-out` | 🔒 توکن | ثبت انصراف یک مشتری از تماس بازاریابی. |
| `GET` | `/api/v1/data-gates` | خواندنی |  |
| `PUT` | `/api/v1/data-gates` | 🔒 توکن |  |
| `GET` | `/api/v1/data-quality` | خواندنی | تصویر کیفیت دفتر کل: آشتی آخرین بارگذاری + شکاف‌های شناخته‌شده. |
| `GET` | `/api/v1/dismiss-reasons` | خواندنی | فهرست دلایل رد — تا UI و گزارش روی یک واژگان بایستند. |
| `GET` | `/api/v1/experiment-plan` | خواندنی | کمپین بعدی را روی چه گروهی، و با چه اندازه‌ای؟ |
| `GET` | `/api/v1/feature-basis-diff` | 🔒 توکن | اختلافِ مدعیِ دفترکلیِ پرونده‌ی ۳۶۰ با عکسِ نوشته‌شده (قهرمان) — بدون نوشتن. |
| `GET` | `/api/v1/imports` | خواندنی | فهرست بارگذاری‌های ثبت‌شده، تازه‌ترین اول. |
| `GET` | `/api/v1/imports/{batch_id}` | خواندنی | جزئیات یک بارگذاری همراه با شواهد آشتی. |
| `GET` | `/api/v1/margin-floor` | خواندنی | کف حاشیه‌ی تعیین‌شده + اینکه با این کف چه چیزی کنار گذاشته می‌شود. |
| `PUT` | `/api/v1/margin-floor` | 🔒 توکن | ثبت کف حاشیه — تصمیمِ کاربر است، نه حدسِ سیستم. |
| `GET` | `/api/v1/models` | خواندنی | فهرست اجراها + اینکه هر نوع مدل الان چه چیزی فعال دارد. |
| `POST` | `/api/v1/models/train` | 🔒 توکن | آموزش یک مدل. «داده کافی نبود» هم یک پاسخِ موفق است، نه خطا. |
| `GET` | `/api/v1/models/{run_id}` | خواندنی |  |
| `GET` | `/api/v1/models/{run_id}/drift` | خواندنی | انحرافِ توزیع نسبت به لحظه‌ی آموزش (§۲۹.۷). |
| `GET` | `/api/v1/models/{run_id}/metrics` | خواندنی |  |
| `POST` | `/api/v1/models/{run_id}/promote` | 🔒 توکن |  |
| `POST` | `/api/v1/models/{run_id}/rollback` | 🔒 توکن |  |
| `POST` | `/api/v1/models/{run_id}/validate` | 🔒 توکن | گزارشِ اینکه این اجرا دروازه‌ی پذیرش را رد کرده یا نه. |
| `GET` | `/api/v1/offer-policy` | خواندنی | نردبانِ تخفیف (§۲۰.۳) + اینکه روی چند فرصت اصلاً **می‌تواند** اثر بگذارد. |
| `PUT` | `/api/v1/offer-policy` | 🔒 توکن | ثبت سیاستِ آفر — تصمیمِ کاربر است، نه حدسِ سیستم. |
| `GET` | `/api/v1/operator-capacity` | خواندنی | ظرفیت پیگیری تیم + اینکه با این عدد چه چیزی کنار می‌ماند (§۲۵). |
| `PUT` | `/api/v1/operator-capacity` | 🔒 توکن | ثبت ظرفیت — تصمیمِ کاربر است، نه حدسِ سیستم. |
| `GET` | `/api/v1/opportunities` | خواندنی | صندوق فرصت‌ها — به ترتیب ارزش مورد انتظار نزولی. |
| `GET` | `/api/v1/opportunities/{opportunity_id}` | خواندنی | جزئیات یک فرصت با همه‌ی شواهد و تاریخچه‌ی وضعیت. |
| `POST` | `/api/v1/opportunities/{opportunity_id}/offer/{decision}` | 🔒 توکن | تأیید یا ردِ تخفیفِ پیشنهادی (§۲۰.۳) — تنها راهی که تخفیف وارد ارسال می‌شود. |
| `POST` | `/api/v1/opportunities/{opportunity_id}/{action}` | 🔒 توکن | تغییر وضعیت یک فرصت. هر تغییر یک رخداد ماندگار ثبت می‌کند. |
| `GET` | `/api/v1/opportunity-quality` | خواندنی | کیفیت مولدها از دید اپراتور — کدام مولد بیشتر رد می‌شود و چرا. |
| `GET` | `/api/v1/ops/jobs` | خواندنی | فهرستِ کارها و آخرین اجراهایشان. |
| `GET` | `/api/v1/ops/jobs/dead-letter` | خواندنی | کارهایی که تلاش‌هایشان تمام شد و کسی باید ببیندشان. |
| `POST` | `/api/v1/ops/jobs/runs/{run_id}/retry` | 🔒 توکن | تلاشِ دوباره روی یک ردیفِ صفِ مرده. شمارنده از نو شروع می‌شود. |
| `POST` | `/api/v1/ops/jobs/{job_name}/run` | 🔒 توکن | اجرای دستیِ یک کار — برای راه‌اندازی و رفعِ اشکال. |
| `GET` | `/api/v1/ops/metrics` | خواندنی | شمارنده‌های سبکِ درخواست‌ها (§۳۲). |
| `GET` | `/api/v1/phase5-readiness` | خواندنی | چقدر تا دروازه‌ی داده‌ی فاز ۵ مانده — سنجه، نه مدل. |
| `GET` | `/api/v1/quarantine` | 🔒 توکن | ردیف‌هایی که وارد دفتر کل نشدند و **چرا** (§۷.۱). |
| `POST` | `/api/v1/quarantine/{row_id}/resolve` | 🔒 توکن | رسیدگی‌شده علامت‌زدنِ یک ردیف. ردیف پاک نمی‌شود تا تاریخ بماند. |
| `GET` | `/api/v1/source-mappings` | خواندنی | نگاشت‌های نسخه‌دارِ منبع (§۸.۲): هر امضای سرستون با تاریخچه‌ی نسخه‌هایش. |
| `GET` | `/api/v1/uplift` | خواندنی | آنچه سیستم از کمپین‌های خودش یاد گرفته است. |

## مسیرهای legacy (`/api/*`) — قراردادِ حفظ‌شده

این مسیرها همان داشبورد و گزارش‌های پیش از ارتقا را می‌دهند (`PRESERVE_CONTRACT.md`).

| متد | مسیر | گارد | چه می‌کند |
|---|---|---|---|
| `POST` | `/api/analyze` | باز (استثنای مستند) |  |
| `GET` | `/api/audience-kinds` | خواندنی |  |
| `POST` | `/api/campaign` | 🔒 توکن |  |
| `GET` | `/api/export` | 🔒 توکن | خروجی اکسل یک بخش داشبورد (سگمنت‌ها/پیش‌بینی خرید/محصولات/تشخیص و تأمین). |
| `GET` | `/api/health` | خواندنی |  |
| `GET` | `/api/jobs/{job_id}` | خواندنی |  |
| `GET` | `/api/outbox` | 🔒 توکن |  |
| `GET` | `/api/report` | خواندنی |  |
| `POST` | `/api/sample` | باز (استثنای مستند) | داده‌ی نمونه (سریع؛ بدون job) — همان قرارداد نتیجه‌ی آپلود. |
| `POST` | `/api/scheduler/run-now` | 🔒 توکن | اجرای دستی اسکن چرخه (برای تست/راه‌اندازی). |
| `GET` | `/api/scheduler/status` | خواندنی |  |
| `DELETE` | `/api/session/{session_id}` | 🔒 توکن | حذف کامل و دائمی یک تحلیل (تنها راه حذف — سیستم خودش حذف نمی‌کند). |
| `GET` | `/api/session/{session_id}` | خواندنی | بازیابی وضعیت نشست برای فرانت (بعد از reload/ری‌استارت/بستن تب). |
| `PATCH` | `/api/session/{session_id}` | باز (استثنای مستند) | نام دلخواه برای تحلیل (مثلاً «فروش شهریور ۱۴۰۴»). |
| `GET` | `/api/sessions` | خواندنی | فهرست تحلیل‌های ذخیره‌شده (سبک — بدون پارس کردن نتیجه‌ی کامل تحلیل). |
| `POST` | `/api/sms/send` | 🔒 توکن | ساخت مخاطب، شخصی‌سازی پیام و ارسال. |
| `GET` | `/api/storage` | خواندنی | محل واقعی «حافظه»ی سیستم و مصرف فضا (برای رفع ابهام مسیر داده). |
| `POST` | `/api/strategy` | 🔒 توکن |  |
| `POST` | `/api/upload` | باز (استثنای مستند) |  |

## کلیدهای اصلیِ چند پاسخِ پرمصرف

| مسیر | کلیدهای اصلی |
|---|---|
| `GET /api/v1/imports/{batch_id}` | `reconcile_status`, `posted`, `blocked_by[]`, `checks[]` (L01–L13 با `status` OK/WARN/MISMATCH/SKIPPED), `quality_dimensions[]`, `quality_summary`, `mapping_signature`, `mapping_version` |
| `GET /api/v1/data-quality` | `counts`, `dimensions[]` (نُه بُعدِ §۸.۵ از کلِ دفتر کل), `quality_summary`, `latest_batch`, `mismatches[]`, `latest_import_blocked`, `gaps[]` |
| `GET /api/v1/feature-basis-diff` | `as_of`, `champion`, `challenger`, `columns{…mismatches, examples}`, `only_in_challenger`, `lifecycle_changes`, `identical`, `written=false` |
| `GET /api/v1/source-mappings` | `items[]{signature, versions, latest_version, history[]{version, mapping, columns, file_currency, display_currency, batch_ids}}` |
| `GET /api/v1/opportunities` | `items[]{id, kind, customer, expected_value, score_rial, offer, factors[], expires_at}`, `expiring_soon_count` |
| `GET /api/v1/customers/{customer_id}` | هویت، آخرین عکسِ ویژگی، روند، تاریخچه‌ی خرید، گذارهای چرخه‌ی عمر |
| `GET /api/v1/campaigns/{campaign_id}/report` | `verdict`, `observed_difference`, `incremental_*` فقط با حکمِ علّی |
