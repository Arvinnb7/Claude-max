# حسابرسی وضعیت فعلی سیستم

> این سند وضعیت سیستم را **پیش از** ارتقای Revenue Intelligence ثبت می‌کند.
> مبنای تصمیم «چه چیزی حفظ، چه چیزی توسعه، چه چیزی refactor، چه چیزی ساخته شود».
> تاریخ حسابرسی: مرداد ۱۴۰۵ · commit مبنا: `614606b`

## ۱. فهرست معماری

### بک‌اند
| لایه | مسیر | وضعیت |
|---|---|---|
| API | `api/main.py` (~۷۲۰ خط) | FastAPI، ۱۹ endpoint، بدون احراز هویت — **از حسابرسیِ اول تغییر کرده**: حالا توکنِ opt-in روی مسیرهای نوشتنی و PII (بخش ۷) |
| jobهای پس‌زمینه | `api/jobs.py` | `ThreadPoolExecutor(max_workers=2)` + ثبت وضعیت در SQLite |
| ماندگاری | `api/persistence.py` (~۷۱۵ خط) | `sqlite3` خام، ۴ جدول، مهاجرت دستی با `PRAGMA user_version=2` |
| زمان‌بند | `api/scheduler.py` | APScheduler، **MemoryJobStore** (اجرای ازدست‌رفته بازیابی نمی‌شود) — از حسابرسیِ اول تغییر کرده: جبرانِ اجرای ازدست‌رفته + همه‌ی کارها زیرِ `run_job` (بخش ۷) |
| سریال‌سازی | `api/serialize.py` | تبدیل خالص `MetricsBundle` → JSON (۷ کلید ثابت + ۱۸ شرطی) |
| خروجی اکسل | `api/export.py` | ۶ بخش، شیت‌های RTL با سرستون فارسی |
| هسته‌ی تحلیل | `src/mktcore/` (~۶۹۰۰ خط) | خالص و بدون وابستگی به UI |

### هسته (`src/mktcore/`)
`ingest/` (schema, mapper, cleaning, currency, profiler) · `analysis/` (۲۱ ماژول) ·
`forecasting/` (ETS + Prophet + selector) · `targets/` · `execution/` · `reporting/` ·
`ai/` · `connectors/` · `pipeline.py` · `synthetic.py` · `locale_fa.py` · `config.py`

**همه‌ی ماژول‌های `analysis/*` توابع خالص‌اند** (DataFrame → dataclass). تنها
نویسنده‌های دیسک/شبکه: `api/persistence.py`، `api/scheduler.py`،
`reporting/pdf_report.py` (با مسیر صریح)، `execution/providers.py` (با گیت dry-run).

### فرانت‌اند
Next.js 16.2.9 · `frontend/src/app/page.tsx` (ماشین حالت upload→mapping→dashboard) ·
`Dashboard.tsx` (۱۰ تب) · `AdvancedTabs.tsx` · `steps.tsx` · `RecentSessions.tsx` ·
`charts.tsx` · `ui.tsx`. نشانی نشست در `localStorage`، تب فعال در `sessionStorage`.

### CI و استقرار
`.github/workflows/ci.yml`: backend (`ruff` + `pytest` با افزونه‌های `[api,dev]`) و
frontend (`eslint` + `build`). **تست فرانت وجود ندارد.**
`docker-compose.yml`: دو سرویس (api تک-worker + frontend)، bind mount `./data:/data`،
بدون healthcheck.

## ۲. فهرست داده

| منبع | دانه‌بندی | کلید | یادداشت |
|---|---|---|---|
| فایل اکسل/CSV آپلودی | ردیف قلم فروش | `source_row` (۰-مبنا، بعد از هدر) | `.xlsx/.xlsm` استریمی، `.xlsb` با pyxlsb، `.xls` غیراستریمی، CSV با تشخیص encoding |
| فریم استانداردشده (`clean.parquet`) | همان ردیف | `source_row` | ۱۸ ستون نقش + `source_row`؛ float64 برای مبالغ |
| `attrs` فریم | — | — | `sign_flipped`, `dropped_invalid_rows`, `dropped_duplicate_rows`, `exclusions_df`, `returns_df`, `n_returns`, `returns_total`, `ambiguous_sign`, `validation`, `discount_is_amount` |
| `bundle.pkl` | نشست | `session_id` | pickle کامل `MetricsBundle` (شکننده به تغییر نام فیلد) |
| SQLite `app.db` | — | — | ۴ جدول: `sessions`, `jobs`, `outbox`, `mapping_profiles` |

### نقش‌های ستون (`ingest/schema.py`)
DATE, REVENUE, QUANTITY, UNIT_PRICE, PRODUCT, CATEGORY, CUSTOMER_ID, CHANNEL,
REGION, COST, ORDER_ID, DISCOUNT, SALESPERSON, BRANCH, PHONE, EMAIL, DOC_TYPE,
GROSS_AMOUNT. اجباری: DATE + REVENUE.

### معناشناسی مهم
- **برگشت از فروش**: ردیف‌های `revenue < 0` جدا نگه داشته می‌شوند (`returns_df`) و
  در KPI خالص‌سازی می‌شوند؛ فریم اصلی فقط خرید مثبت است.
- **قرارداد علامت حسابداری**: ستون مبلغی با >۶۰٪ منفی، کل ستون قرینه می‌شود.
- **تخفیف**: نسبت یا مبلغ، با تشخیص در `cleaning.py` و ثبت در `attrs`.
- **واحد پول**: انتخاب صریح کاربر (تومان/ریال)؛ ضریب تبدیل float.

## ۳. تحلیل شکاف در برابر سند

### الف) موجود و درست (حفظ می‌شود)
خواننده‌ی استریمی با گارد dimension بادکرده · نگاشت نسخه‌دار با امضای سرستون +
پیش‌نمایش · دروازه‌ی PASS/WARN/FAIL با کنترل‌های آشتی C04–C12 · حسابرسی ردیف
حذف‌شده با `source_row` · KPI برگشت‌آگاه · ماه ناقص + nowcast · CF آیتم-آیتم با
خودتنظیمی وزن‌ها · کالیبراسیون Brier · مدل زمان‌بندی گاما + p_alive + CLV ·
صداقت علّی (برچسب «ارزش فرصت») · منع عددسازی LLM · حافظه‌ی دائمی نشست.

### ب) موجود ولی نیازمند توسعه
`analysis/actions.py` (فهرست موقت → موجودیت ماندگار) · `segmentation.py` (۸ سگمنت →
ماشین حالت چرخه‌ی عمر) · `purchase_cycle.py` (تعدیل مقدار/تخلیه) ·
`recommender.py` (فیلتر سازگاری/موجودی) · `market_basket.py` (اقتصاد باندل) ·
`kpis.py` (COGS per-line) · `execution/audience.py` (رضایت/خستگی تماس) ·
`persistence.py` (لایه‌ی canonical) · `main.py` (فضای نام `/api/v1`).

### ج) غایب (ساخته می‌شود)
جداول canonical (`import_batches`, `customers`, `customer_keys`, `products`,
`product_aliases`, `orders`, `order_lines`, `customer_features`) · جداول فرصت
(`opportunities`, `opportunity_factors`, `opportunity_events`, `opportunity_runs`) ·
حل هویت مشتری/محصول · نرمال‌سازی موبایل ایرانی · آشتی ماندگار per-batch ·
Opportunity Inbox · پرونده مشتری (Customer 360).

### د) مسدود به دلیل نبود داده
| قابلیت | داده‌ی لازم | وضعیت |
|---|---|---|
| سود ناخالص / COGS / سود افزوده | بهای خرید یا تمام‌شده | **نداریم** — زیرساخت ساخته می‌شود، اعداد درآمدمحور می‌مانند |
| فیلتر قابلیت تأمین | موجودی انبار | **نداریم** — فیلتر no-op با برچسب صریح |
| کشش قیمت | تنوع قیمت + کنترل promo/فصل | ناکافی |
| مدل uplift / اثر علّی | داده‌ی گروه کنترل | وجود ندارد (فاز بعد) |
| لایه‌ی دامنه‌ی خاص (گونه/مرحله‌ی زندگی) | متادیتای محصول | کسب‌وکار چنددامنه است → لایه‌ی عمومی داده‌محور |

## ۴. باگ‌های واقعی کشف‌شده در حسابرسی

| # | باگ | اثر | وضعیت |
|---|---|---|---|
| ۱ | `currency.py` ستون تخفیف را تبدیل نمی‌کند ولی `kpis.py` تخفیف **مبلغی** را روی فریم تبدیل‌شده جمع می‌زند | `discount_total` وقتی واحد فایل ≠ واحد نمایش، **۱۰ برابر** غلط | ✅ رفع شد |
| ۲ | `run_cycle_scan` اول پیامک می‌فرستد، بعد outbox را می‌نویسد | مرگ پروسه بین این دو → **ارسال دوباره** در اجرای بعدی | ✅ رفع شد (ادعا سپس ارسال) |
| ۳ | زمان‌بند روی MemoryJobStore | اجرای ازدست‌رفته بعد از ری‌استارت بی‌صدا حذف می‌شود | ✅ رفع شد (`catch_up_missed_scan`) |
| ۴ | `outbox.customer_id` ایندکس ندارد | dedupe = table scan به‌ازای هر گیرنده | ✅ رفع شد |
| ۵ | انتخاب parser فقط با پسوند فایل | فایل بدون پسوند/با پسوند غلط خوانده نمی‌شود | ✅ رفع شد (امضای بایت) |
| ۶ | fixture واقعی `.xls`/`.xlsb` وجود ندارد | رگرسیون واقعی این فرمت‌ها در CI دیده نمی‌شود | ⛔ مسدود — نویسنده‌ی زنده وجود ندارد (توضیح در IMPLEMENTATION_STATUS) |
| ۷ | CI افزونه‌های `pdf`/`forecast` را نصب نمی‌کند | آن مسیرها در CI اجرا نمی‌شوند | ✅ رفع شد |
| ۸ | `sqlalchemy` در افزونه‌ی `connectors` است نه deps اصلی | تست‌های لایه‌ی canonical در CI شکست می‌خوردند | ✅ رفع شد |

### باگ نهمی که حین پیاده‌سازی پیدا شد

`api/v1.py` در نسخه‌ی اول، «بهای تمام‌شده وجود ندارد» را به‌صورت ثابت گزارش
می‌کرد. اما بعضی فایل‌ها ستون بها **دارند** (از جمله داده‌ی نمونه‌ی خود پروژه).
حالا پوشش بها از دفتر کل شمرده می‌شود و جمله‌ی اقتصادی و شدتِ شکاف از همان
عدد ساخته می‌شوند — `test_economics_note_tracks_actual_cost_coverage`.

## ۵. استراتژی مهاجرت

1. **جداول legacy دست نمی‌خورند** → کد قدیمی روی دیتابیس جدید هم درست کار می‌کند؛
   rollback = `git checkout` قبلی، بازگردانی پشتیبان اختیاری است.
2 `PRAGMA user_version` در **۲** می‌ماند و مالکش `persistence.py` است؛ لایه‌ی
   canonical جدول مستقل `schema_migrations` دارد → دو مکانیزم اثبات‌پذیر مستقل.
3. `ensure_schema()` **تنبل** است (اولین استفاده) + یک بار در lifespan با
   try/except → تست‌هایی که `TestClient` را بیرون از `with` می‌سازند دست‌نخورده.
4. نوشتن canonical در همان analyze job و **بعد از** `save_bundle`، از طریق هوکی که
   **هرگز خطا نمی‌دهد** و با `MKT_CANONICAL_ENABLE=0` خاموش می‌شود.
5. پشتیبان‌گیری با `sqlite3.backup` (نه کپی فایل — چون WAL). دستور در `ROLLBACK.md`.

## ۶. تعداد تست‌های مبنا
۱۵۰ تست سبز در ۲۴ فایل. قرارداد پین‌شده در `PRESERVE_CONTRACT.md`.

## ۷. تکمیلِ فهرستِ معماریِ §۵.۱ (۱۴۰۵/۰۶/۲۱)

حسابرسیِ اول (بخش ۱) چهار بندِ §۵.۱ را نداشت: ایندکس‌ها و چرخه‌ی اتصال، صف/Redis و تلاشِ
دوباره، ناظرِ فایل، و لاگ/پایش. این بخش هر هفت بند را **از روی کدِ امروز** می‌نویسد؛ جایی
که وضعیت از حسابرسیِ اول عوض شده، صریح گفته می‌شود. شمارش‌ها با `tests/test_docs_drift.py`
به کد پین شده‌اند.

### ۷.۱ بک‌اند: ماژول‌ها و جریانِ درخواست

`api/main.py` (۱۹ مسیرِ legacy: آپلود → نگاشت → تحلیل به‌صورت job → داشبورد/اکسل/PDF/AI/پیامک)
+ چهار router افزودنی: `api/v1.py` و `api/brief_api.py` (دفتر کل، فرصت‌ها، کیفیت داده،
خروجیِ روزانه)، `api/campaigns_api.py` (کمپین/آزمایش)، `api/models_api.py` (رجیستری مدل)،
`api/ops_api.py` (کارها و صفِ مرده). فهرستِ کاملِ مسیرها در `API_GUIDE.md` تولید می‌شود
(۵۶ مسیرِ `/api/v1` + ۱۹ legacy). جریانِ یک درخواست: `RequestContextMiddleware` (شناسه‌ی
درخواست، لاگ، شمارنده) → گاردِ `require_token_for_writes` (منعِ پیش‌فرضِ مسیرهای نوشتنی و
`EXTRA_GUARDED_ROUTES`) → handler → `session_scope()` (commit/rollback/close). تحلیل و
نوشتنِ canonical در `ThreadPoolExecutor(max_workers=2)` (`api/jobs.py`) با ضربانِ job و
watchdog (`MKT_JOB_HEARTBEAT_TIMEOUT`) اجرا می‌شود؛ هوکِ canonical هرگز raise نمی‌کند.

### ۷.۲ فرانت‌اند: مسیرها و وضعیت

Next.js 16 با **یک صفحه** (`app/page.tsx`) و ماشینِ حالتِ upload → mapping → dashboard؛
`Dashboard.tsx` ۱۶ تب (سه تبِ افزودنیِ این فازها: صندوق فرصت‌ها + اتاق فرمانِ روزانه، اثر
کمپین‌ها، پرونده مشتریان، سلامت مدل‌ها، کارها و عملیات، دفتر کل). داده‌گیری با `fetch`ِ
ساده در `lib/api.ts` (legacy) و `lib/apiV1.ts` (canonical؛ پول همیشه `Money` با
`display_text`)؛ توکن در `lib/token.ts` و `localStorage`؛ نشستِ فعال در `localStorage`،
تبِ فعال در `sessionStorage`. هیچ state managerِ سراسری و هیچ SSR داده‌ای وجود ندارد.
**تستِ فرانت هنوز وجود ندارد** (فقط `eslint` + `next build` در CI) — شکافِ §۳۷.

### ۷.۳ پایگاه‌داده: فناوری، طرح‌واره، مهاجرت، ایندکس‌ها، چرخه‌ی اتصال

* **فناوری**: یک فایل SQLite (`MKT_DATA_DIR/app.db`) با دو لایه: legacy (`sqlite3` خام،
  `PRAGMA user_version=2`، مالک `api/persistence.py`) و canonical (SQLAlchemy 2.0،
  `schema_migrations`، `CANONICAL_SCHEMA_VERSION` در `db/migrations.py`). Postgres واگذارشده
  (تصمیم ۱ در `TARGET_ARCHITECTURE.md`).
* **طرح‌واره**: ۳۲ جدولِ canonical (فهرستِ ستون‌ها در `DATA_DICTIONARY.md` تولیدی) + ۵ جدولِ
  legacy که دست نمی‌خورند.
* **مهاجرت**: runner گام‌به‌گام، بدون Alembic؛ هر مهاجرت idempotent و در `ROLLBACK.md` با
  دستورِ بازگشت.
* **ایندکس‌ها**: همه در مدل‌ها اعلام شده‌اند (`Index`/`UniqueConstraint`/`index=True`)؛ هیچ
  ایندکسی خارج از کد ساخته نمی‌شود. شمارِ ایندکس + قیدِ یکتایی به‌ازای جدول (پین‌شده به
  `Base.metadata`):

| جدول | ایندکس/یکتایی | جدول | ایندکس/یکتایی |
|---|---|---|---|
| `opportunities` | ۱۴ | `customer_features` | ۵ |
| `order_lines` | ۱۲ | `mapping_profile_versions` | ۵ |
| `model_runs` | ۸ | `product_cost_history` | ۵ |
| `orders` | ۸ | `uplift_snapshots` | ۵ |
| `campaign_sends` | ۷ | `audit_events` | ۴ |
| `customer_lifecycle_events` | ۷ | `campaign_opportunities` | ۴ |
| `import_batches` | ۷ | `campaign_outcomes` | ۴ |
| `import_quarantine` | ۷ | `campaigns` | ۴ |
| `import_rows_raw` | ۷ | `customers` | ۴ |
| `campaign_members` | ۶ | `opportunity_runs` | ۴ |
| `job_runs` | ۶ | `product_aliases` | ۴ |
| `contact_suppressions` | ۵ | `app_settings` | ۳ |
| `customer_keys` | ۳ | `job_leases` | ۳ |
| `opportunity_events` | ۳ | `opportunity_offers` | ۳ |
| `products` | ۳ | `import_reconciliation` | ۲ |
| `opportunity_factors` | ۲ | `businesses` | ۱ |

  ایندکسِ پوششیِ پرس‌وجوهای داغ: `(business_id, line_date)`، `(customer_id, line_date)`،
  `(product_id, line_date)` روی خطوط؛ `(business_id, status)`، `expires_at`، `assigned_to`
  روی فرصت‌ها؛ `outbox.customer_id` (باگ ۴ حسابرسیِ اول).
* **چرخه‌ی اتصال**: یک `Engine` به‌ازای هر URL (`db/engine.py`, `get_engine`) با
  `pool_pre_ping`، `check_same_thread=False` (هر thread اتصالِ خودش)، PRAGMAهای
  `journal_mode=WAL`، `busy_timeout=15000`، `foreign_keys=ON`، `synchronous=NORMAL` روی هر
  اتصالِ تازه؛ `session_scope()` = commit در موفقیت، rollback در خطا، close همیشه؛ نوشتن‌های
  سنگین پشتِ `write_lock` (RLock درون‌پروسه‌ای — با یک worker کافی است، با چند worker
  **نیست**؛ به همین دلیل compose تک-worker است)؛ `dispose_engine()` فقط در خاموشی و تست.
  لایه‌ی legacy اتصالِ کوتاه‌عمر به‌ازای هر عمل با همان WAL/busy_timeout می‌گیرد.

### ۷.۴ کارهای پس‌زمینه، زمان‌بند، صف، Redis، تلاشِ دوباره

* **صف و Redis: ندارد** (تصمیمِ §۳۹.۲؛ ردیفِ ۳ جدولِ تصمیم‌ها). کارِ درخواستی (تحلیل) در
  ThreadPool؛ کارِ زمان‌بندی‌شده در APScheduler با MemoryJobStore و timezone تهران.
* **کارها** (`mktcore.jobs.SCHEDULED_JOBS`، ۹ کار): تولیدِ فرصت، انقضا/بستن با خرید،
  تطبیقِ نتیجه، جدولِ اثر، بازآموزی، پایشِ انحراف، جاروکش، **اسکنِ چرخه** و **نگه‌داری**
  (دو کاری که تا این دور مستقیم روی زمان‌بند بودند). همه از راهِ `run_job` (`jobs/runner.py`).
* **تلاشِ دوباره**: هر شکست ردیفِ `job_runs` می‌گیرد؛ backoff نمایی از ۶۰ ثانیه
  (`60·2^(attempt−1)`)، سقفِ `max_attempts` (پیش‌فرض ۳؛ بازآموزی ۲؛ جاروکش و اسکنِ چرخه ۱)؛
  تمام‌شدنِ تلاش‌ها = **صفِ مرده** (`GET /api/v1/ops/jobs/dead-letter`، تلاشِ دستی با
  `/retry`). جاروکشِ هر ۱۵ دقیقه تلاش‌های سررسیدشده را اجرا و ردیف‌های موفقِ قدیمی‌تر از
  ۳۰ روز را هرس می‌کند؛ ردیفِ مرده هرگز هرس نمی‌شود. `JobSkipped` = «شرط برقرار نبود»،
  بدون تلاشِ دوباره. اجرای هم‌زمانِ موتور با اجاره‌ی `(business, as_of)` در `job_leases`.
* **اجرای ازدست‌رفته**: MemoryJobStore بعد از ری‌استارت نوبت را فراموش می‌کند؛
  `catch_up_missed_scan` با `LAST_SCAN_KEY` جبران می‌کند (باگ ۳).

### ۷.۵ ناظرِ فایل و رفتارِ ورود

**ناظرِ فایل ندارد.** تنها راهِ ورود، `POST /api/upload` (و `POST /api/sample`) است؛ هیچ
پوشه‌ای پایش نمی‌شود و هیچ importِ زمان‌بندی‌شده‌ای نیست. کانکتورهای `mktcore/connectors/`
(اکسل/CSV استریمی، SQL، CRM، فروشگاه) فقط در لایه‌ی خواندنِ فایل به‌کار می‌روند؛ SQL/CRM
اسکلت‌اند و واگذارشده. ورود: تشخیصِ امضای بایت (باگ ۵) → نگاشتِ ستون (پیشنهاد + تأییدِ کاربر،
نسخه‌دار در `mapping_profile_versions`) → پاک‌سازی → گاردِ §۸.۵ (C04/C05/واحدِ نامعلوم ⇒ دسته‌ی
`BLOCKED`، هیچ خطی نوشته نمی‌شود) → دفتر کل با هویتِ پایدارِ خط و سرِ فاکتورِ دوره‌دار →
آشتیِ L01–L13 → قرنطینه‌ی ردیف‌های ردشده با راهِ اصلاح. بازپردازشِ همان فایل idempotent است.

### ۷.۶ احراز هویت و مجوز

**از حسابرسیِ اول تغییر کرده.** توکنِ مشترکِ opt-in (`MKT_API_TOKEN`، `mktcore/security.py`):
با توکنِ تنظیم‌شده هر مسیرِ نوشتنی و مسیرهای خواندنیِ `EXTRA_GUARDED_ROUTES` (PII/پرهزینه)
سرآیندِ `X-API-Token` می‌خواهند؛ استثناها در `OPEN_WRITE_ROUTES` با دلیل. بدون توکن هیچ‌چیز
بسته نیست ولی `/api/health` و لاگِ راه‌اندازی هشدار می‌دهند. RBAC و کاربرِ نام‌دار
واگذارشده. کنش‌های حساس در `audit_events` ثبت می‌شوند (`SECURITY_AND_PRIVACY.md`).

### ۷.۷ لاگ، پایش، CI و استقرار

* **لاگ**: `logging.basicConfig` سطحِ INFO + فیلترِ شناسه‌ی درخواست (`api/observability.py`)؛
  هر پاسخ `X-Request-Id` برمی‌گرداند و کارِ پس‌زمینه با `correlation_id` به آن وصل است.
* **پایش**: `GET /api/health` (۵۰۳ وقتی دیتابیس جواب نمی‌دهد، وضعیتِ زمان‌بند و گارد)،
  `GET /api/v1/ops/metrics` (شمارنده‌های درون‌حافظه‌ای با `since`؛ با ری‌استارت صفر)،
  `GET /api/v1/ops/jobs` و صفِ مرده، هشدارِ انحرافِ مدل در لاگ و پاسخِ کارِ پایش. **هیچ
  متریکِ خارجی** (Prometheus/Sentry) وصل نیست — واگذارشده.
* **CI**: `.github/workflows/ci.yml` دو job — backend (`ruff` + `pytest` با افزونه‌ها) و
  frontend (`eslint` + `next build`)؛ تستِ فرانت ندارد.
* **استقرار**: `docker-compose.yml` دو سرویس (api تک-worker + frontend)، `./data` روی
  bind mount؛ پشتیبان با `sqlite3.backup` (`OPERATIONS_RUNBOOK.md`).
