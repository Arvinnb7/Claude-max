"use client";

import { useMemo, useState } from "react";
import {
  AlertTriangle,
  BrainCircuit,
  Download,
  LineChart as LineIcon,
  Repeat,
  ShoppingCart,
  Target,
  TrendingUp,
  Users,
} from "lucide-react";

import { getStrategy } from "@/lib/api";
import { compact, num, pct, toFa } from "@/lib/format";
import type { AnalyzeResponse, StrategyResponse } from "@/lib/types";
import {
  BreakdownBars,
  ForecastChart,
  MonthlyBars,
  RevenueTrend,
  SegmentBars,
  WeekdayChart,
} from "./charts";
import { Alert, Badge, Button, Card, SectionTitle, Spinner, StatCard } from "./ui";

type Tab = "kpi" | "segments" | "forecast" | "targets" | "ai";

const TABS: { id: Tab; label: string; icon: React.ReactNode }[] = [
  { id: "kpi", label: "شاخص‌ها", icon: <TrendingUp size={16} /> },
  { id: "segments", label: "سگمنت‌بندی", icon: <Users size={16} /> },
  { id: "forecast", label: "پیش‌بینی", icon: <LineIcon size={16} /> },
  { id: "targets", label: "تارگت", icon: <Target size={16} /> },
  { id: "ai", label: "استراتژی هوش مصنوعی", icon: <BrainCircuit size={16} /> },
];

const DIM_LABELS: Record<string, string> = {
  PRODUCT: "محصول",
  CATEGORY: "دسته‌بندی",
  CHANNEL: "کانال فروش",
  REGION: "منطقه",
};

export default function Dashboard({
  data,
  sessionId,
  aiAvailable,
  onReset,
}: {
  data: AnalyzeResponse;
  sessionId: string;
  aiAvailable: boolean;
  onReset: () => void;
}) {
  const [tab, setTab] = useState<Tab>("kpi");
  const unit = data.currency;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold">داشبورد تحلیل فروش</h1>
          <p className="text-sm" style={{ color: "var(--muted)" }}>
            {data.quality.date_min} تا {data.quality.date_max} ·{" "}
            {toFa(num(data.quality.n_rows))} رکورد
          </p>
        </div>
        <Button variant="outline" onClick={onReset}>
          داده‌ی جدید
        </Button>
      </div>

      {data.quality.warnings.length > 0 && (
        <Alert tone="warn">
          <div className="flex items-start gap-2">
            <AlertTriangle size={16} className="mt-0.5 shrink-0" />
            <ul className="list-inside list-disc space-y-1">
              {data.quality.warnings.map((w, i) => (
                <li key={i}>{w}</li>
              ))}
            </ul>
          </div>
        </Alert>
      )}

      <div className="scrollbar-thin flex gap-2 overflow-x-auto border-b border-ink-200 pb-px dark:border-ink-700">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`flex items-center gap-2 whitespace-nowrap rounded-t-xl px-4 py-2.5 text-sm font-medium transition ${
              tab === t.id
                ? "border-b-2 border-brand-600 text-brand-700 dark:text-brand-300"
                : "text-ink-500 hover:text-ink-700 dark:text-ink-400 dark:hover:text-ink-200"
            }`}
          >
            {t.icon}
            {t.label}
          </button>
        ))}
      </div>

      {tab === "kpi" && <KpiTab data={data} unit={unit} />}
      {tab === "segments" && <SegmentsTab data={data} unit={unit} />}
      {tab === "forecast" && <ForecastTab data={data} unit={unit} />}
      {tab === "targets" && <TargetsTab data={data} unit={unit} />}
      {tab === "ai" && (
        <AiTab sessionId={sessionId} aiAvailable={aiAvailable} />
      )}
    </div>
  );
}

function KpiTab({ data, unit }: { data: AnalyzeResponse; unit: string }) {
  const k = data.kpis;
  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          label="درآمد کل"
          value={`${compact(k.total_revenue)} ${unit}`}
          icon={<TrendingUp size={18} />}
        />
        <StatCard label="تعداد سفارش" value={toFa(num(k.n_orders))} icon={<ShoppingCart size={18} />} tone="accent" />
        <StatCard label="تعداد مشتری" value={toFa(num(k.n_customers))} icon={<Users size={18} />} tone="green" />
        <StatCard
          label="میانگین ارزش سفارش"
          value={`${compact(k.aov)} ${unit}`}
          icon={<ShoppingCart size={18} />}
        />
        <StatCard label="رشد ماهانه" value={pct(k.mom_growth)} icon={<TrendingUp size={18} />} />
        <StatCard label="رشد سالانه" value={pct(k.yoy_growth)} icon={<TrendingUp size={18} />} tone="accent" />
        <StatCard label="نرخ مشتری تکراری" value={pct(k.repeat_rate)} icon={<Repeat size={18} />} tone="green" />
        <StatCard label="حاشیه‌ی سود ناخالص" value={pct(k.gross_margin)} icon={<TrendingUp size={18} />} />
      </div>

      {k.flags.map((f, i) => (
        <Alert key={i} tone="info">
          {f}
        </Alert>
      ))}

      <Card>
        <SectionTitle title="روند درآمد" />
        <RevenueTrend daily={data.trends.daily} ma30={data.trends.moving_avg_30} unit={unit} />
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <SectionTitle title="درآمد ماهانه" />
          <MonthlyBars monthly={data.trends.monthly} unit={unit} />
        </Card>
        <Card>
          <SectionTitle
            title="الگوی فصلی هفتگی"
            subtitle={
              data.seasonality.peak_day
                ? `قوی‌ترین روز: ${data.seasonality.peak_day}`
                : undefined
            }
          />
          <WeekdayChart index={data.seasonality.weekday_index} />
        </Card>
      </div>
    </div>
  );
}

function SegmentsTab({ data, unit }: { data: AnalyzeResponse; unit: string }) {
  const seg = data.segmentation;
  const dims = Object.keys(seg.breakdowns);
  const [dim, setDim] = useState(dims[0] ?? "");
  const rows = seg.breakdowns[dim] ?? [];

  return (
    <div className="space-y-6">
      {seg.segments.length > 0 ? (
        <div className="grid gap-6 lg:grid-cols-2">
          <Card>
            <SectionTitle title="سگمنت‌بندی RFM مشتریان" subtitle="بر اساس درآمد هر سگمنت" />
            <SegmentBars segments={seg.segments} unit={unit} />
          </Card>
          <Card>
            <SectionTitle title="جزئیات سگمنت‌ها" />
            <table className="w-full text-right text-sm">
              <thead>
                <tr className="border-b border-ink-200 text-ink-500 dark:border-ink-700 dark:text-ink-400">
                  <th className="px-3 py-2 font-medium">سگمنت</th>
                  <th className="px-3 py-2 font-medium">تعداد مشتری</th>
                  <th className="px-3 py-2 font-medium">درآمد</th>
                </tr>
              </thead>
              <tbody>
                {[...seg.segments]
                  .sort((a, b) => b.revenue - a.revenue)
                  .map((s) => (
                    <tr key={s.name} className="border-b border-ink-100 dark:border-ink-800">
                      <td className="px-3 py-2">
                        <Badge tone="brand">{s.name}</Badge>
                      </td>
                      <td className="px-3 py-2 tnum">{toFa(num(s.size))}</td>
                      <td className="px-3 py-2 tnum">
                        {compact(s.revenue)} {unit}
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </Card>
        </div>
      ) : (
        <Alert tone="info">ستون مشتری در داده موجود نیست؛ سگمنت‌بندی RFM در دسترس نیست.</Alert>
      )}

      {dims.length > 0 && (
        <Card>
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <SectionTitle title="تفکیک درآمد بر اساس ابعاد" />
            <div className="flex gap-2">
              {dims.map((d) => (
                <button
                  key={d}
                  onClick={() => setDim(d)}
                  className={`rounded-lg px-3 py-1.5 text-sm transition ${
                    dim === d
                      ? "bg-brand-600 text-white"
                      : "bg-ink-100 text-ink-600 dark:bg-ink-800 dark:text-ink-300"
                  }`}
                >
                  {DIM_LABELS[d] ?? d}
                </button>
              ))}
            </div>
          </div>
          <BreakdownBars rows={rows} unit={unit} />
        </Card>
      )}
    </div>
  );
}

function ForecastTab({ data, unit }: { data: AnalyzeResponse; unit: string }) {
  const fc = data.forecast;
  if (!fc) return <Alert tone="warn">داده برای پیش‌بینی کافی نیست.</Alert>;
  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-3">
        <StatCard label="مدل پیش‌بینی" value={fc.model_name} icon={<LineIcon size={18} />} />
        <StatCard
          label={`مجموع پیش‌بینی ${toFa(fc.horizon)} دوره`}
          value={`${compact(fc.total)} ${unit}`}
          tone="accent"
          icon={<TrendingUp size={18} />}
        />
        {fc.backtest.MAPE !== undefined && (
          <StatCard
            label="خطای اعتبارسنجی (MAPE)"
            value={pct(fc.backtest.MAPE, false)}
            tone="green"
            icon={<LineIcon size={18} />}
          />
        )}
      </div>
      <Card>
        <SectionTitle title="پیش‌بینی فروش با بازه‌ی اطمینان" />
        <ForecastChart
          history={fc.history}
          yhat={fc.yhat}
          lower={fc.lower}
          upper={fc.upper}
          unit={unit}
        />
      </Card>
    </div>
  );
}

function TargetsTab({ data, unit }: { data: AnalyzeResponse; unit: string }) {
  const tp = data.targets;
  if (!tp) return <Alert tone="warn">داده برای تارگت‌گذاری کافی نیست.</Alert>;
  const toneFor: Record<string, "green" | "brand" | "accent"> = {
    conservative: "green",
    balanced: "brand",
    ambitious: "accent",
  };
  return (
    <div className="space-y-6">
      <Card>
        <p className="text-sm" style={{ color: "var(--muted)" }}>
          مجموع پیش‌بینی پایه برای {toFa(tp.horizon)} دوره‌ی آینده
        </p>
        <p className="mt-1 text-2xl font-bold tnum">
          {compact(tp.forecast_total)} {unit}
        </p>
      </Card>
      <div className="grid gap-4 md:grid-cols-3">
        {tp.scenarios.map((s) => (
          <Card key={s.key} className={s.key === tp.recommended ? "ring-2 ring-brand-400" : ""}>
            <div className="flex items-center justify-between">
              <h3 className="font-bold">{s.name_fa}</h3>
              {s.key === tp.recommended && <Badge tone="brand">پیشنهادی</Badge>}
            </div>
            <p className="mt-3 text-2xl font-bold tnum">
              {compact(s.total)} {unit}
            </p>
            <p className="mt-1 text-sm tnum">
              <Badge tone={toneFor[s.key]}>{pct(s.uplift_vs_forecast)} نسبت به پیش‌بینی</Badge>
            </p>
            <p className="mt-3 text-sm leading-6" style={{ color: "var(--muted)" }}>
              {s.rationale}
            </p>
          </Card>
        ))}
      </div>
    </div>
  );
}

function AiTab({
  sessionId,
  aiAvailable,
}: {
  sessionId: string;
  aiAvailable: boolean;
}) {
  const [report, setReport] = useState<StrategyResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function generate() {
    setError(null);
    setLoading(true);
    try {
      setReport(await getStrategy(sessionId));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  const priorityTone: Record<string, "rose" | "accent" | "brand" | "gray"> = {
    بحرانی: "rose",
    بالا: "accent",
    متوسط: "brand",
    پایین: "gray",
  };

  const markdown = useMemo(() => (report ? buildMarkdown(report) : ""), [report]);

  if (!aiAvailable) {
    return (
      <Alert tone="warn">
        کلید <code>ANTHROPIC_API_KEY</code> روی سرور تنظیم نشده است. بخش‌های تحلیل، پیش‌بینی و
        تارگت بدون کلید کار می‌کنند؛ برای استراتژی هوش مصنوعی کلید را تنظیم کنید.
      </Alert>
    );
  }

  return (
    <div className="space-y-5">
      <Card className="hero-gradient">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <span className="grid h-12 w-12 place-items-center rounded-2xl bg-white text-brand-600 shadow">
              <BrainCircuit size={24} />
            </span>
            <div>
              <h3 className="font-bold">تحلیل مدیر مارکتینگ سنیور</h3>
              <p className="text-sm" style={{ color: "var(--muted)" }}>
                مدل بر پایه‌ی همه‌ی متریک‌ها، استراتژی و توصیه‌های عملیاتی فارسی می‌سازد.
              </p>
            </div>
          </div>
          <div className="flex gap-2">
            {report && (
              <Button
                variant="outline"
                onClick={() => downloadMarkdown(markdown)}
              >
                <Download size={16} /> دانلود گزارش
              </Button>
            )}
            <Button onClick={generate} disabled={loading}>
              {loading ? "در حال تدوین…" : report ? "تولید مجدد" : "تولید استراتژی"}
            </Button>
          </div>
        </div>
      </Card>

      {loading && <Spinner label="مدیر مارکتینگ هوشمند در حال تحلیل داده‌ها و تدوین استراتژی است…" />}
      {error && <Alert tone="error">{error}</Alert>}

      {report && !loading && (
        <div className="space-y-5">
          <Card>
            <SectionTitle title="خلاصه‌ی مدیریتی" />
            <p className="leading-8">{report.executive_summary}</p>
          </Card>

          {report.factor_analysis.length > 0 && (
            <Card>
              <SectionTitle title="تحلیل عوامل مؤثر بر فروش" />
              <div className="space-y-3">
                {report.factor_analysis.map((f, i) => (
                  <div key={i} className="rounded-xl bg-ink-50 p-4 dark:bg-ink-800/60">
                    <div className="flex items-center gap-2">
                      <Badge tone="brand">{f.factor}</Badge>
                    </div>
                    <p className="mt-2 text-sm leading-7">{f.finding}</p>
                    <p className="mt-1 text-xs" style={{ color: "var(--muted)" }}>
                      تأثیر: {f.impact}
                    </p>
                  </div>
                ))}
              </div>
            </Card>
          )}

          <Card>
            <SectionTitle title="توجیه تارگت" />
            <p className="leading-8">{report.target_rationale}</p>
          </Card>

          {report.recommendations.length > 0 && (
            <Card>
              <SectionTitle title="توصیه‌های عملیاتی اولویت‌بندی‌شده" />
              <div className="space-y-3">
                {report.recommendations.map((r, i) => (
                  <div key={i} className="rounded-xl border border-ink-200 p-4 dark:border-ink-700">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <h4 className="font-semibold">{r.title}</h4>
                      <div className="flex gap-2">
                        <Badge tone={priorityTone[r.priority] ?? "gray"}>
                          اولویت: {r.priority}
                        </Badge>
                        <Badge tone="gray">تلاش: {r.effort}</Badge>
                      </div>
                    </div>
                    <p className="mt-2 text-sm leading-7">{r.rationale}</p>
                    <p className="mt-1 text-xs text-emerald-600">اثر مورد انتظار: {r.expected_impact}</p>
                  </div>
                ))}
              </div>
            </Card>
          )}

          {report.risks.length > 0 && (
            <Card>
              <SectionTitle title="ریسک‌ها و نکات احتیاطی" />
              <ul className="space-y-2">
                {report.risks.map((risk, i) => (
                  <li key={i} className="flex items-start gap-2 text-sm">
                    <AlertTriangle size={16} className="mt-0.5 shrink-0 text-amber-500" />
                    {risk}
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </div>
      )}

      {!report && !loading && (
        <Alert tone="info">
          برای دریافت تحلیل و استراتژی، دکمه‌ی «تولید استراتژی» را بزنید.
        </Alert>
      )}
    </div>
  );
}

function buildMarkdown(r: StrategyResponse): string {
  const lines = ["# استراتژی مارکتینگ", "", "## خلاصه‌ی مدیریتی", r.executive_summary, ""];
  if (r.factor_analysis.length) {
    lines.push("## تحلیل عوامل مؤثر بر فروش");
    for (const f of r.factor_analysis) lines.push(`- **${f.factor}:** ${f.finding} _(تأثیر: ${f.impact})_`);
    lines.push("");
  }
  lines.push("## توجیه تارگت", r.target_rationale, "");
  if (r.recommendations.length) {
    lines.push("## توصیه‌های عملیاتی");
    for (const x of r.recommendations)
      lines.push(`- **${x.title}** (اولویت: ${x.priority}) — ${x.rationale}`);
    lines.push("");
  }
  if (r.risks.length) {
    lines.push("## ریسک‌ها");
    for (const risk of r.risks) lines.push(`- ${risk}`);
  }
  return lines.join("\n");
}

function downloadMarkdown(md: string) {
  const blob = new Blob([md], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "marketing_strategy.md";
  a.click();
  URL.revokeObjectURL(url);
}
