# سیستم اتوماسیون تحلیل داده و استراتژی مارکتینگ

سرویسی که دیتای فروش (اکسل/CSV، و در آینده CRM/دیتابیس/سایت فروشگاهی) را می‌گیرد و
مثل یک **مدیر مارکتینگ سنیور + تحلیل‌گر داده** عمل می‌کند: تحلیل دقیق عوامل مؤثر بر
فروش، پیش‌بینی، تارگت‌گذاری خودکار و تدوین استراتژی — همه با خروجی **فارسی**.

موتور سیستم **ترکیبی** است:
- لایه‌ی **آماری/یادگیری ماشین** (pandas, scikit-learn, statsmodels/Prophet) برای
  KPIها، سگمنت‌بندی RFM، روند، ناهنجاری، کوهورت، فصلی‌بودن، پیش‌بینی و تارگت.
- لایه‌ی **هوش مصنوعی** با مدل `claude-opus-4-8` که متریک‌ها را مثل یک مدیر مارکتینگ
  تفسیر می‌کند، تارگت را توجیه می‌کند و استراتژی اولویت‌بندی‌شده می‌سازد.

## معماری

```
src/mktcore/            هسته‌ی مستقل و قابل‌تست (بدون وابستگی به UI)
├── connectors/         منابع داده: اکسل/CSV (کامل) + اسکلت SQL/CRM/فروشگاهی
├── ingest/             نگاشت ستون (SchemaMapper)، پاک‌سازی، پروفایل کیفیت
├── analysis/           kpis, segmentation(RFM), trends, anomalies, cohorts, seasonality
├── forecasting/        انتخاب مدل (Prophet/ETS) + backtest
├── targets/            سناریوهای محافظه‌کار/متعادل/جسورانه
├── ai/                 payload فشرده، پرامپت فارسی، schema، strategist (Claude)
├── reporting/          گزارش Markdown و PDF فارسی (RTL)
├── pipeline.py         run_analysis() → MetricsBundle
└── synthetic.py        تولید داده‌ی نمونه

app/                    داشبورد Streamlit (خانه + ۶ صفحه)
tests/                  تست واحد همه‌ی ماژول‌ها
```

## راه‌اندازی

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"          # هسته + ابزار توسعه
# گروه‌های اختیاری:
pip install -e ".[forecast]"     # Prophet (پیش‌بینی پیشرفته‌تر)
pip install -e ".[pdf]"          # WeasyPrint (خروجی PDF) — نیازمند pango/cairo سیستمی
pip install -e ".[connectors]"   # SQLAlchemy/httpx (کانکتورهای آینده)
```

کلید API را تنظیم کنید (برای لایه‌ی استراتژی هوش مصنوعی):

```bash
cp .env.example .env
# سپس ANTHROPIC_API_KEY را در .env قرار دهید
```

## اجرا

دو رابط کاربری موجود است:

### الف) فرانت اختصاصی Next.js + API (توصیه‌شده)

طراحی اختصاصی RTL فارسی با Next.js، روی یک API با FastAPI.

```bash
# ترمینال ۱ — backend
pip install -e ".[api]"
uvicorn api.main:app --port 8000

# ترمینال ۲ — frontend
cd frontend
npm install
cp .env.example .env.local        # NEXT_PUBLIC_API_URL=http://localhost:8000
npm run dev                       # یا: npm run build && npm run start
```

سپس `http://localhost:3000` را باز کنید.

### ب) داشبورد سریع Streamlit (همه‌چیز در پایتون)

```bash
streamlit run app/Home.py
```

در هر دو رابط: داده را بارگذاری کنید (یا «داده‌ی نمونه» را بزنید) → نگاشت ستون‌ها را
تأیید کنید → شاخص‌ها، سگمنت‌بندی، پیش‌بینی، تارگت و استراتژی هوش مصنوعی را ببینید.

> بخش‌های تحلیل آماری، پیش‌بینی و تارگت **بدون نیاز به کلید API** کار می‌کنند؛ فقط
> صفحه‌ی استراتژی هوش مصنوعی به `ANTHROPIC_API_KEY` نیاز دارد.

## تست

```bash
pytest            # تست‌های واحد (بدون فراخوانی شبکه؛ لایه‌ی AI ماک می‌شود)
ruff check .      # لینت
```

تست‌ها روی داده‌ی مصنوعی قطعی اجرا می‌شوند و صحت KPIها، تشخیص ناهنجاری، ترتیب
سناریوهای تارگت، نگاشت/پاک‌سازی داده‌ی کثیف و تولید گزارش را بررسی می‌کنند.

## استفاده‌ی برنامه‌نویسی (بدون UI)

```python
from mktcore.synthetic import generate_synthetic_sales
from mktcore.ingest.mapper import SchemaMapper
from mktcore.ingest.cleaning import clean_frame
from mktcore.pipeline import run_analysis
from mktcore.ai import generate_strategy   # نیازمند کلید API

raw = generate_synthetic_sales()
mapper = SchemaMapper()
clean = clean_frame(mapper.apply(raw, mapper.auto_detect(raw).mapping))
bundle = run_analysis(clean, horizon=6)        # تحلیل + پیش‌بینی + تارگت
report = generate_strategy(bundle)             # استراتژی فارسی (Claude)
```
