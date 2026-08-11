# حسابرسی وضعیت فعلی سیستم

> این سند وضعیت سیستم را **پیش از** ارتقای Revenue Intelligence ثبت می‌کند.
> مبنای تصمیم «چه چیزی حفظ، چه چیزی توسعه، چه چیزی refactor، چه چیزی ساخته شود».
> تاریخ حسابرسی: مرداد ۱۴۰۵ · commit مبنا: `614606b`

## ۱. فهرست معماری

### بک‌اند
| لایه | مسیر | وضعیت |
|---|---|---|
| API | `api/main.py` (~۷۲۰ خط) | FastAPI، ۱۹ endpoint، بدون احراز هویت |
| jobهای پس‌زمینه | `api/jobs.py` | `ThreadPoolExecutor(max_workers=2)` + ثبت وضعیت در SQLite |
| ماندگاری | `api/persistence.py` (~۷۱۵ خط) | `sqlite3` خام، ۴ جدول، مهاجرت دستی با `PRAGMA user_version=2` |
| زمان‌بند | `api/scheduler.py` | APScheduler، **MemoryJobStore** (اجرای ازدست‌رفته بازیابی نمی‌شود) |
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
| ۱ | `currency.py` ستون تخفیف را تبدیل نمی‌کند ولی `kpis.py` تخفیف **مبلغی** را روی فریم تبدیل‌شده جمع می‌زند | `discount_total` وقتی واحد فایل ≠ واحد نمایش، **۱۰ برابر** غلط | رفع در C2 |
| ۲ | `run_cycle_scan` اول پیامک می‌فرستد، بعد outbox را می‌نویسد | مرگ پروسه بین این دو → **ارسال دوباره** در اجرای بعدی | رفع (الگوی claim) |
| ۳ | زمان‌بند روی MemoryJobStore | اجرای ازدست‌رفته بعد از ری‌استارت بی‌صدا حذف می‌شود | رفع (catch-up) |
| ۴ | `outbox.customer_id` ایندکس ندارد | dedupe = table scan به‌ازای هر گیرنده | رفع (ایندکس) |
| ۵ | انتخاب parser فقط با پسوند فایل | فایل بدون پسوند/با پسوند غلط خوانده نمی‌شود | رفع (magic bytes) |
| ۶ | fixture واقعی `.xls`/`.xlsb` وجود ندارد | رگرسیون واقعی این فرمت‌ها در CI دیده نمی‌شود | رفع (fixture) |
| ۷ | CI افزونه‌های `pdf`/`forecast` را نصب نمی‌کند | آن مسیرها در CI اجرا نمی‌شوند | رفع |
| ۸ | `sqlalchemy` در افزونه‌ی `connectors` است نه deps اصلی | تست‌های لایه‌ی canonical در CI شکست می‌خوردند | رفع در C3 |

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
