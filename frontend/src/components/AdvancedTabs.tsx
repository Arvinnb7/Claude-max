"use client";

import { useCallback, useEffect, useState } from "react";
import { Download, History, Megaphone, MessageSquare, Send } from "lucide-react";

import { exportUrl, getCampaign, getOutbox, sendSMS, type OutboxItem } from "@/lib/api";
import { compact, jalali, num, pct, toFa } from "@/lib/format";
import type { AnalyzeResponse, CampaignResponse, SMSResult } from "@/lib/types";
import { Alert, Badge, Button, Card, ProgressBar, SectionTitle } from "./ui";

const ABC_TONE: Record<string, "green" | "brand" | "gray"> = { A: "green", B: "brand", C: "gray" };
const REC_TONE: Record<string, "green" | "brand" | "accent" | "rose"> = {
  "افزایش تأمین": "green",
  "حفظ تأمین": "brand",
  "کاهش تأمین": "accent",
  "قطع تأمین": "rose",
};

/* ---------- محصولات و سبد خرید ---------- */
export function ProductsTab({
  data,
  unit,
  sessionId,
}: {
  data: AnalyzeResponse;
  unit: string;
  sessionId: string;
}) {
  return (
    <div className="space-y-6">
      {data.products && (
        <Card>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <SectionTitle title="محصولات پرفروش و تحلیل ABC" subtitle="کلاس A پرفروش‌ترین‌ها، C کم‌اهمیت‌ترین‌ها" />
            <a href={exportUrl(sessionId, "products")}>
              <Button variant="outline"><Download size={16} /> دانلود اکسل</Button>
            </a>
          </div>
          <table className="w-full text-right text-sm">
            <thead>
              <tr className="border-b border-ink-200 text-ink-500 dark:border-ink-700 dark:text-ink-400">
                <th className="px-3 py-2 font-medium">محصول</th>
                <th className="px-3 py-2 font-medium">درآمد</th>
                <th className="px-3 py-2 font-medium">سهم</th>
                <th className="px-3 py-2 font-medium">کلاس</th>
                <th className="px-3 py-2 font-medium">رشد</th>
              </tr>
            </thead>
            <tbody>
              {data.products.map((p) => (
                <tr key={p.product} className="border-b border-ink-100 dark:border-ink-800">
                  <td className="px-3 py-2 font-medium">{p.product}</td>
                  <td className="px-3 py-2 tnum">{compact(p.revenue)} {unit}</td>
                  <td className="px-3 py-2 tnum">{pct(p.share)}</td>
                  <td className="px-3 py-2"><Badge tone={ABC_TONE[p.abc_class] ?? "gray"}>{p.abc_class}</Badge></td>
                  <td className="px-3 py-2 tnum">{p.growth === null ? "—" : pct(p.growth)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      {data.basket && data.basket.rules.length > 0 && (
        <Card>
          <SectionTitle
            title="محصولات مکمل (تحلیل سبد خرید)"
            subtitle={`میانگین اندازه‌ی سبد: ${toFa(data.basket.avg_basket_size.toFixed(1))} قلم — «اگر X خریده شد، Y هم با احتمال بالا خریده می‌شود»`}
          />
          <div className="grid gap-3 sm:grid-cols-2">
            {data.basket.rules.map((r, i) => (
              <div key={i} className="rounded-xl border border-ink-200 p-3 dark:border-ink-700">
                <div className="flex items-center gap-2 text-sm">
                  <Badge tone="brand">{r.antecedent}</Badge>
                  <span>←</span>
                  <Badge tone="accent">{r.consequent}</Badge>
                </div>
                <div className="mt-2 text-xs tnum" style={{ color: "var(--muted)" }}>
                  اطمینان {pct(r.confidence)} · lift {toFa(r.lift.toFixed(2))} · {toFa(num(r.pair_count))} بار با هم
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {data.sequences && data.sequences.length > 0 && (
        <Card>
          <SectionTitle
            title="الگوهای خرید توالی"
            subtitle="مشتریانی که A خریده‌اند معمولاً در بازه‌ی مشخص B هم می‌خرند؛ «ناتمام»ها فرصت مانور دارند"
          />
          <table className="w-full text-right text-sm">
            <thead>
              <tr className="border-b border-ink-200 text-ink-500 dark:border-ink-700 dark:text-ink-400">
                <th className="px-3 py-2 font-medium">الگو</th>
                <th className="px-3 py-2 font-medium">نرخ تکمیل</th>
                <th className="px-3 py-2 font-medium">میانه فاصله</th>
                <th className="px-3 py-2 font-medium">مشتریان ناتمام</th>
              </tr>
            </thead>
            <tbody>
              {data.sequences.map((s, i) => (
                <tr key={i} className="border-b border-ink-100 dark:border-ink-800">
                  <td className="px-3 py-2">{s.antecedent} ← {s.consequent}</td>
                  <td className="px-3 py-2 tnum">{pct(s.completion_rate)}</td>
                  <td className="px-3 py-2 tnum">{toFa(Math.round(s.median_lag_days))} روز</td>
                  <td className="px-3 py-2 tnum"><Badge tone="accent">{toFa(num(s.incomplete_count))} نفر</Badge></td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      {data.next_purchase && data.next_purchase.length > 0 && (
        <Card>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <SectionTitle title="پیش‌بینی خرید بعدی و سبد بعدی" subtitle="مشتریانِ سررسیدشده برای خرید مجدد، احتمال خرید و سبد محتمل آن‌ها" />
            <a href={exportUrl(sessionId, "next_purchase")}>
              <Button variant="outline"><Download size={16} /> دانلود اکسل کامل</Button>
            </a>
          </div>
          <div className="scrollbar-thin overflow-x-auto">
            <table className="w-full text-right text-sm">
              <thead>
                <tr className="border-b border-ink-200 text-ink-500 dark:border-ink-700 dark:text-ink-400">
                  <th className="px-3 py-2 font-medium">مشتری</th>
                  <th className="px-3 py-2 font-medium">وضعیت</th>
                  <th className="px-3 py-2 font-medium">تاریخ پیش‌بینی</th>
                  <th className="px-3 py-2 font-medium">تأخیر</th>
                  <th className="px-3 py-2 font-medium">احتمال خرید (۳۰ روز)</th>
                  <th className="px-3 py-2 font-medium">سبد محتمل</th>
                  <th className="px-3 py-2 font-medium">ارزش مورد انتظار</th>
                </tr>
              </thead>
              <tbody>
                {data.next_purchase.slice(0, 15).map((c, i) => (
                  <tr key={i} className="border-b border-ink-100 dark:border-ink-800">
                    <td className="px-3 py-2">{c.customer_id}</td>
                    <td className="px-3 py-2"><Badge tone={c.status === "سررسیدشده" ? "rose" : "accent"}>{c.status}</Badge></td>
                    <td className="whitespace-nowrap px-3 py-2 tnum">{c.predicted_next_date ? jalali(c.predicted_next_date) : "—"}</td>
                    <td className="px-3 py-2 tnum">{toFa(num(c.overdue_days))} روز</td>
                    <td className="px-3 py-2 tnum">{c.buy_probability_30d == null ? "—" : pct(c.buy_probability_30d)}</td>
                    <td className="px-3 py-2">{c.likely_products.join("، ") || "—"}</td>
                    <td className="px-3 py-2 tnum">{compact(c.expected_value)} {unit}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}

/* ---------- فروشنده‌ها و شعب ---------- */
function PerfTable({ items, unit, allocTargets }: {
  items: AnalyzeResponse["performance"] extends infer T ? (T extends { branches: infer B } ? B : never) : never;
  unit: string;
  allocTargets?: Record<string, number>;
}) {
  return (
    <table className="w-full text-right text-sm">
      <thead>
        <tr className="border-b border-ink-200 text-ink-500 dark:border-ink-700 dark:text-ink-400">
          <th className="px-3 py-2 font-medium">#</th>
          <th className="px-3 py-2 font-medium">نام</th>
          <th className="px-3 py-2 font-medium">درآمد</th>
          <th className="px-3 py-2 font-medium">سهم</th>
          <th className="px-3 py-2 font-medium">رشد</th>
          {allocTargets && <th className="px-3 py-2 font-medium">تارگت دوره‌ی بعد</th>}
        </tr>
      </thead>
      <tbody>
        {items.map((e) => (
          <tr key={e.name} className="border-b border-ink-100 dark:border-ink-800">
            <td className="px-3 py-2 tnum">{toFa(e.rank)}</td>
            <td className="px-3 py-2 font-medium">{e.name}</td>
            <td className="px-3 py-2 tnum">{compact(e.revenue)} {unit}</td>
            <td className="px-3 py-2 tnum">{pct(e.share)}</td>
            <td className="px-3 py-2 tnum">{e.growth === null ? "—" : pct(e.growth)}</td>
            {allocTargets && <td className="px-3 py-2 tnum">{compact(allocTargets[e.name] ?? 0)} {unit}</td>}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function PerformanceTab({ data, unit }: { data: AnalyzeResponse; unit: string }) {
  const perf = data.performance;
  if (!perf || (perf.branches.length === 0 && perf.salespeople.length === 0)) {
    return <Alert tone="info">ستون فروشنده یا شعبه در داده موجود نیست.</Alert>;
  }
  const branchT: Record<string, number> = {};
  data.branch_targets?.entities.forEach((e) => (branchT[e.name] = e.target));
  const repT: Record<string, number> = {};
  data.salesperson_targets?.entities.forEach((e) => (repT[e.name] = e.target));

  return (
    <div className="space-y-6">
      {perf.branches.length > 0 && (
        <Card>
          <SectionTitle title="عملکرد شعب و تخصیص تارگت" subtitle="تارگت دوره‌ی بعد بر اساس سهم و رشد، با طرح پاداش پلکانی" />
          <PerfTable items={perf.branches} unit={unit} allocTargets={branchT} />
        </Card>
      )}
      {perf.salespeople.length > 0 && (
        <Card>
          <SectionTitle title="عملکرد فروشندگان و تخصیص تارگت" />
          <PerfTable items={perf.salespeople} unit={unit} allocTargets={repT} />
        </Card>
      )}
      {data.branch_targets && data.branch_targets.entities[0] && (
        <Card>
          <SectionTitle title="طرح پاداش (نمونه برای شعبه برتر)" />
          <div className="flex flex-wrap gap-3">
            {data.branch_targets.entities[0].reward_tiers.map((r, i) => (
              <div key={i} className="rounded-xl bg-ink-50 px-4 py-3 text-sm dark:bg-ink-800/60">
                <div className="font-semibold">{r.آستانه}</div>
                <div style={{ color: "var(--muted)" }}>{r.پاداش}</div>
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}

/* ---------- تشخیص و تأمین ---------- */
export function DiagnosticsTab({
  data,
  unit,
  sessionId,
}: {
  data: AnalyzeResponse;
  unit: string;
  sessionId: string;
}) {
  return (
    <div className="space-y-6">
      <div className="flex justify-end">
        <a href={exportUrl(sessionId, "diagnostics")}>
          <Button variant="outline"><Download size={16} /> دانلود اکسل تشخیص و تأمین</Button>
        </a>
      </div>
      {data.pacing && (
        <Card>
          <SectionTitle title="پیشروی به‌سمت تارگت ماهانه" />
          <div className="grid gap-4 sm:grid-cols-4">
            <div><div className="text-xs" style={{ color: "var(--muted)" }}>تارگت ماه</div><div className="text-lg font-bold tnum">{compact(data.pacing.monthly_target)} {unit}</div></div>
            <div><div className="text-xs" style={{ color: "var(--muted)" }}>محقق‌شده</div><div className="text-lg font-bold tnum">{compact(data.pacing.achieved)} {unit}</div></div>
            <div><div className="text-xs" style={{ color: "var(--muted)" }}>نرخ روزانه‌ی لازم</div><div className="text-lg font-bold tnum">{compact(data.pacing.required_daily)} {unit}</div></div>
            <div><div className="text-xs" style={{ color: "var(--muted)" }}>وضعیت</div><Badge tone={data.pacing.on_track ? "green" : "rose"}>{data.pacing.on_track ? "در مسیر" : "عقب از برنامه"}</Badge></div>
          </div>
          {data.pacing.week_plan.length > 0 && (
            <table className="mt-4 w-full text-right text-sm">
              <thead><tr className="border-b border-ink-200 text-ink-500 dark:border-ink-700 dark:text-ink-400">
                <th className="px-3 py-2 font-medium">روز</th><th className="px-3 py-2 font-medium">هدف روز</th><th className="px-3 py-2 font-medium">تمرکز</th></tr></thead>
              <tbody>
                {data.pacing.week_plan.map((d, i) => (
                  <tr key={i} className="border-b border-ink-100 dark:border-ink-800">
                    <td className="px-3 py-2">{d.weekday}</td>
                    <td className="px-3 py-2 tnum">{compact(d.target_revenue)} {unit}</td>
                    <td className="px-3 py-2 text-xs">{d.emphasis}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      )}

      {data.diagnostics && (
        <Card>
          <SectionTitle title="تشخیص دلایل تغییر فروش" subtitle={data.diagnostics.period_label} />
          <p className="mb-3 text-sm">
            تغییر کلی فروش: <Badge tone={data.diagnostics.is_declining ? "rose" : "green"}>{pct(data.diagnostics.overall_pct)}</Badge>
          </p>
          {data.diagnostics.drivers.length > 0 ? (
            <table className="w-full text-right text-sm">
              <thead><tr className="border-b border-ink-200 text-ink-500 dark:border-ink-700 dark:text-ink-400">
                <th className="px-3 py-2 font-medium">بُعد</th><th className="px-3 py-2 font-medium">مورد</th><th className="px-3 py-2 font-medium">تغییر</th><th className="px-3 py-2 font-medium">سهم از افت</th></tr></thead>
              <tbody>
                {data.diagnostics.drivers.map((d, i) => (
                  <tr key={i} className="border-b border-ink-100 dark:border-ink-800">
                    <td className="px-3 py-2 text-xs">{d.dimension}</td>
                    <td className="px-3 py-2">{d.label}</td>
                    <td className="px-3 py-2 tnum">{d.pct_change === null ? "—" : pct(d.pct_change)}</td>
                    <td className="px-3 py-2 tnum">{pct(d.contribution)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : <Alert tone="info">در دوره‌ی اخیر افت قابل‌توجهی در ابعاد فروش دیده نمی‌شود.</Alert>}
        </Card>
      )}

      {data.inventory && (
        <Card>
          <SectionTitle title="پیشنهاد تأمین کالا" subtitle="بر اساس روند، سهم درآمد و حاشیه‌ی سود" />
          <div className="grid gap-3 sm:grid-cols-2">
            {data.inventory.map((it, i) => (
              <div key={i} className="rounded-xl border border-ink-200 p-3 dark:border-ink-700">
                <div className="flex items-center justify-between">
                  <span className="font-medium">{it.product}</span>
                  <Badge tone={REC_TONE[it.recommendation] ?? "gray"}>{it.recommendation}</Badge>
                </div>
                <p className="mt-1 text-xs" style={{ color: "var(--muted)" }}>{it.reason}</p>
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}

/* ---------- چرخه خرید و اعلان‌ها ---------- */
const TYPE_TONE: Record<string, "green" | "accent" | "gray"> = {
  "مصرفی": "green",
  "تک‌خریدی": "accent",
  "نامشخص": "gray",
};

export function CycleTab({ data }: { data: AnalyzeResponse }) {
  const pc = data.purchase_cycle;
  if (!pc) return <Alert tone="info">داده‌ی کافی برای تحلیل چرخه‌ی خرید موجود نیست.</Alert>;
  return (
    <div className="space-y-6">
      <Card>
        <SectionTitle
          title="چرخه‌ی خرید محصولات و تشخیص مصرفی/تک‌خریدی"
          subtitle="کالای «مصرفی» چرخه‌ی بازخرید دارد؛ کالای «تک‌خریدی» معمولاً یک‌بار خریده می‌شود"
        />
        <table className="w-full text-right text-sm">
          <thead>
            <tr className="border-b border-ink-200 text-ink-500 dark:border-ink-700 dark:text-ink-400">
              <th className="px-3 py-2 font-medium">محصول</th>
              <th className="px-3 py-2 font-medium">نوع</th>
              <th className="px-3 py-2 font-medium">نرخ بازخرید</th>
              <th className="px-3 py-2 font-medium">چرخه (روز)</th>
              <th className="px-3 py-2 font-medium">خریداران</th>
            </tr>
          </thead>
          <tbody>
            {pc.products.map((p) => (
              <tr key={p.product} className="border-b border-ink-100 dark:border-ink-800">
                <td className="px-3 py-2 font-medium">{p.product}</td>
                <td className="px-3 py-2"><Badge tone={TYPE_TONE[p.product_type] ?? "gray"}>{p.product_type}</Badge></td>
                <td className="px-3 py-2 tnum">{pct(p.repurchase_rate)}</td>
                <td className="px-3 py-2 tnum">{p.median_cycle_days === null ? "—" : toFa(Math.round(p.median_cycle_days))}</td>
                <td className="px-3 py-2 tnum">{toFa(num(p.n_buyers))}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      {pc.notifications.length > 0 && (
        <Card>
          <SectionTitle title="اعلان‌های چرخه‌ی خرید مشتریان" subtitle="چقدر از چرخه‌ی هر مشتری عقب افتاده یا چقدر مانده" />
          <div className="space-y-2">
            {pc.notifications.slice(0, 25).map((n, i) => (
              <div key={i} className="flex items-center justify-between rounded-lg bg-ink-50 px-3 py-2 text-sm dark:bg-ink-800/60">
                <span>{n.message}</span>
                <Badge tone={n.status === "عقب‌افتاده" ? "rose" : "accent"}>{n.status}</Badge>
              </div>
            ))}
          </div>
        </Card>
      )}

      {pc.onetime_targets.length > 0 && (
        <Card>
          <SectionTitle
            title="هدف‌گیری کالاهای تک‌خریدی"
            subtitle="مشتریان بالقوه که کالای مرتبط را خریده‌اند ولی خودِ کالای تک‌خریدی را نه (خریداران فعلی حذف شده‌اند)"
          />
          <div className="grid gap-3 sm:grid-cols-2">
            {pc.onetime_targets.map((t, i) => (
              <div key={i} className="rounded-xl border border-ink-200 p-3 dark:border-ink-700">
                <div className="flex items-center justify-between">
                  <span className="font-medium">{t.product}</span>
                  <Badge tone="accent">{toFa(num(t.potential_count))} بالقوه</Badge>
                </div>
                <p className="mt-1 text-xs" style={{ color: "var(--muted)" }}>
                  کالاهای مرتبط: {t.gateway_products.join("، ") || "—"} · خریداران فعلی: {toFa(num(t.existing_buyers))} (حذف‌شده از هدف)
                </p>
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}

/* ---------- کمپین و پیام‌ها ---------- */
const CHANNEL_ICON: Record<string, string> = {
  "پیامک": "✉️", "ایمیل": "📧", "مسنجر": "💬", "تماس تلفنی": "📞",
};

export function CampaignTab({
  sessionId,
  aiAvailable,
  smsEnabled = false,
  initial = null,
}: {
  sessionId: string;
  aiAvailable: boolean;
  smsEnabled?: boolean;
  initial?: CampaignResponse | null;
}) {
  const [plan, setPlan] = useState<CampaignResponse | null>(initial);
  const [loading, setLoading] = useState(false);
  const [progress, setProgress] = useState<{ pct: number; stage: string } | null>(null);
  const [error, setError] = useState<string | null>(null);

  // پیش‌نمایش ارسال پیامک (dry-run) + ارسال واقعی (فقط با پنل پیکربندی‌شده)
  const [kind, setKind] = useState("سررسیدشده");
  const [template, setTemplate] = useState("سلام {نام} عزیز، پیشنهاد ویژه برای شما: {سبد_پیشنهادی}. همین حالا سفارش دهید!");
  const [realSend, setRealSend] = useState(false);
  const [sms, setSms] = useState<SMSResult | null>(null);
  const [smsLoading, setSmsLoading] = useState(false);
  const [smsError, setSmsError] = useState<string | null>(null);
  const [outbox, setOutbox] = useState<OutboxItem[]>([]);

  const refreshOutbox = useCallback(() => {
    getOutbox(15)
      .then((r) => setOutbox(r.items))
      .catch(() => {
        /* outbox اختیاری است؛ خطای آن نباید تب را بشکند */
      });
  }, []);

  useEffect(() => {
    refreshOutbox();
  }, [refreshOutbox]);

  async function generate() {
    setError(null); setLoading(true);
    setProgress({ pct: 0, stage: "در صف پردازش…" });
    try { setPlan(await getCampaign(sessionId, (pct, stage) => setProgress({ pct, stage }))); }
    catch (e) { setError((e as Error).message); }
    finally { setLoading(false); setProgress(null); }
  }

  async function preview() {
    const isReal = realSend && smsEnabled;
    if (isReal) {
      const ok = window.confirm(
        "ارسال واقعی پیامک به مشتریان انجام می‌شود و قابل بازگشت نیست. مطمئن هستید؟",
      );
      if (!ok) return;
    }
    setSmsError(null); setSmsLoading(true);
    try {
      setSms(await sendSMS({
        session_id: sessionId, kind, template, limit: 50,
        dry_run: !isReal, confirm: isReal,
      }));
      refreshOutbox();
    }
    catch (e) { setSmsError((e as Error).message); }
    finally { setSmsLoading(false); }
  }

  return (
    <div className="space-y-6">
      <Card className="hero-gradient">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <span className="grid h-12 w-12 place-items-center rounded-2xl bg-white text-brand-600 shadow"><Megaphone size={24} /></span>
            <div>
              <h3 className="font-bold">تدوین خودمختار کمپین و پیام‌ها</h3>
              <p className="text-sm" style={{ color: "var(--muted)" }}>مدل، مخاطبان را هدف‌گیری و پیام‌های شخصی‌سازی‌شده‌ی چندکاناله را می‌نویسد.</p>
            </div>
          </div>
          {aiAvailable && (
            <Button onClick={generate} disabled={loading}>{loading ? "در حال تدوین…" : plan ? "تولید مجدد" : "تولید کمپین"}</Button>
          )}
        </div>
      </Card>

      {!aiAvailable && <Alert tone="warn">برای تولید کمپین با هوش مصنوعی، کلید <code>ANTHROPIC_API_KEY</code> روی سرور تنظیم شود.</Alert>}
      {loading && (
        <ProgressBar pct={progress?.pct ?? 0} stage={progress?.stage} label="در حال طراحی کمپین و نوشتن پیام‌ها…" />
      )}
      {error && <Alert tone="error">{error}</Alert>}

      {plan && !loading && (
        <div className="space-y-5">
          <Card><SectionTitle title="رویکرد کمپین" /><p className="leading-8">{plan.summary}</p></Card>
          {plan.audiences.map((a, i) => (
            <Card key={i}>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h4 className="font-bold">{a.segment_name}</h4>
                <Badge tone="accent">{a.objective}</Badge>
              </div>
              <p className="mt-1 text-sm" style={{ color: "var(--muted)" }}>{a.audience_definition}</p>
              <p className="mt-1 text-sm">پیشنهاد: <span className="font-medium">{a.offer}</span> · شاخص موفقیت: {a.success_kpi}</p>
              <div className="mt-4 grid gap-3 md:grid-cols-2">
                {a.channels.map((c, j) => (
                  <div key={j} className="rounded-xl border border-ink-200 p-3 dark:border-ink-700">
                    <div className="mb-2 flex items-center justify-between">
                      <span className="font-medium">{CHANNEL_ICON[c.channel] ?? ""} {c.channel}</span>
                      <span className="text-xs" style={{ color: "var(--muted)" }}>{c.timing}</span>
                    </div>
                    {c.subject && <div className="mb-1 text-sm font-medium">موضوع: {c.subject}</div>}
                    <p className="whitespace-pre-wrap text-sm leading-7">{c.body}</p>
                    {c.call_script && (
                      <details className="mt-2 text-sm">
                        <summary className="cursor-pointer text-brand-600">اسکریپت کامل تماس</summary>
                        <p className="mt-1 whitespace-pre-wrap leading-7">{c.call_script}</p>
                      </details>
                    )}
                  </div>
                ))}
              </div>
            </Card>
          ))}
          {plan.weekly_actions.length > 0 && (
            <Card>
              <SectionTitle title="برنامه‌ی اجرایی هفته" />
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {plan.weekly_actions.map((w, i) => (
                  <div key={i} className="rounded-xl bg-ink-50 p-3 dark:bg-ink-800/60">
                    <div className="font-semibold">{w.day}</div>
                    <div className="text-xs" style={{ color: "var(--muted)" }}>{w.focus}</div>
                    <ul className="mt-2 list-inside list-disc text-sm">{w.actions.map((x, k) => <li key={k}>{x}</li>)}</ul>
                  </div>
                ))}
              </div>
            </Card>
          )}
        </div>
      )}

      {/* اجرای پیامکی (پیش‌نمایش امن + ارسال واقعی گیت‌شده) */}
      <Card>
        <SectionTitle
          title="اجرای پیامکی روی مخاطب هدف"
          subtitle={smsEnabled
            ? "پنل پیامکی متصل است؛ ارسال واقعی با تأیید صریح انجام می‌شود. پیش‌فرض همیشه پیش‌نمایش امن است."
            : "مخاطب از تحلیل ساخته می‌شود و پیام شخصی‌سازی می‌گردد؛ ارسال واقعی نیازمند اتصال پنل پیامکی (MKT_SMS_ENABLE + KAVENEGAR_API_KEY) است."}
        />
        <div className="flex flex-col gap-3">
          <div className="flex flex-wrap gap-2">
            {[["سررسیدشده", "سررسیدشده برای خرید"], ["چرخه_عقب‌افتاده", "عقب از چرخه‌ی مصرفی"], ["تارگت_تک‌خریدی", "بالقوه‌ی تک‌خریدی"], ["ناتمام_الگو", "ناتمام در الگوی خرید"], ["در_معرض_ریزش", "در معرض ریزش"]].map(([k, lbl]) => (
              <button key={k} onClick={() => setKind(k)}
                className={`rounded-lg px-3 py-1.5 text-sm transition ${kind === k ? "bg-brand-600 text-white" : "bg-ink-100 text-ink-600 dark:bg-ink-800 dark:text-ink-300"}`}>{lbl}</button>
            ))}
          </div>
          <textarea value={template} onChange={(e) => setTemplate(e.target.value)} rows={3}
            className="w-full rounded-xl border border-ink-200 bg-white px-3 py-2 text-sm outline-none focus:border-brand-400 dark:border-ink-700 dark:bg-ink-800 dark:text-ink-100"
            placeholder="متن پیام با متغیرهای {نام} {سبد_پیشنهادی} {محصول}" />
          <div className="flex flex-wrap items-center gap-3">
            <Button onClick={preview} disabled={smsLoading}>
              <Send size={16} />{" "}
              {smsLoading
                ? "در حال آماده‌سازی…"
                : realSend && smsEnabled
                  ? "ارسال واقعی پیامک"
                  : "پیش‌نمایش ارسال"}
            </Button>
            {smsEnabled && (
              <label className="flex cursor-pointer items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={realSend}
                  onChange={(e) => setRealSend(e.target.checked)}
                />
                <span className={realSend ? "font-semibold text-rose-600" : ""}>
                  ارسال واقعی (به‌جای پیش‌نمایش)
                </span>
              </label>
            )}
            <span className="text-xs" style={{ color: "var(--muted)" }}>متغیرهای موجود: {"{نام}"} {"{سبد_پیشنهادی}"} {"{محصول}"}</span>
          </div>
        </div>
        {smsError && <div className="mt-3"><Alert tone="error">{smsError}</Alert></div>}
        {sms && (
          <div className="mt-4">
            <div className="mb-2 flex flex-wrap gap-3 text-sm">
              <Badge tone="brand">مخاطب: {toFa(num(sms.audience_size))}</Badge>
              <Badge tone="green">
                {sms["حالت_آزمایشی"] ? "آماده‌ی ارسال" : "ارسال‌شده"}: {toFa(num(sms["ارسال‌شده"]))}
              </Badge>
              <Badge tone="gray">بدون شماره: {toFa(num(sms["ناموفق"]))}</Badge>
              {sms["حالت_آزمایشی"] && <Badge tone="accent">حالت آزمایشی (بدون ارسال واقعی)</Badge>}
            </div>
            {sms["توضیح"] && <div className="mb-2"><Alert tone="warn">{sms["توضیح"]}</Alert></div>}
            <div className="space-y-2">
              {sms["نمونه"].slice(0, 5).map((m, i) => (
                <div key={i} className="rounded-lg bg-ink-50 p-3 text-sm dark:bg-ink-800/60">
                  <div className="flex items-center gap-2 text-xs" style={{ color: "var(--muted)" }}>
                    <MessageSquare size={14} /> {m["مشتری"]} · {m["گیرنده"]}
                  </div>
                  <p className="mt-1 leading-7">{m["متن"]}</p>
                </div>
              ))}
            </div>
          </div>
        )}
      </Card>

      {/* تاریخچه‌ی ارسال‌ها (outbox) */}
      <Card>
        <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
          <SectionTitle
            title="تاریخچه‌ی ارسال‌ها"
            subtitle="ارسال‌های دستی و اعلان‌های خودکار زمان‌بند (چرخه‌ی خرید) اینجا ثبت می‌شوند."
          />
          <Button variant="outline" onClick={refreshOutbox}>
            <History size={16} /> به‌روزرسانی
          </Button>
        </div>
        {outbox.length === 0 ? (
          <Alert tone="info">هنوز ارسالی ثبت نشده است.</Alert>
        ) : (
          <div className="scrollbar-thin overflow-x-auto">
            <table className="w-full text-right text-sm">
              <thead>
                <tr className="border-b border-ink-200 text-ink-500 dark:border-ink-700 dark:text-ink-400">
                  <th className="px-3 py-2 font-medium">نوع</th>
                  <th className="px-3 py-2 font-medium">مشتری</th>
                  <th className="px-3 py-2 font-medium">گیرنده</th>
                  <th className="px-3 py-2 font-medium">وضعیت</th>
                  <th className="px-3 py-2 font-medium">پیام</th>
                </tr>
              </thead>
              <tbody>
                {outbox.map((row) => (
                  <tr key={row.id} className="border-b border-ink-100 dark:border-ink-800">
                    <td className="whitespace-nowrap px-3 py-2 text-xs">
                      {row.kind === "cycle_notification" ? "اعلان خودکار چرخه" : "پیامک کمپین"}
                    </td>
                    <td className="whitespace-nowrap px-3 py-2">{row.customer_id ?? "—"}</td>
                    <td className="whitespace-nowrap px-3 py-2 tnum">{row.phone ?? "—"}</td>
                    <td className="whitespace-nowrap px-3 py-2">
                      <Badge tone={row.dry_run ? "accent" : row.status === "ارسال‌شده" ? "green" : "gray"}>
                        {row.status}
                      </Badge>
                    </td>
                    <td className="max-w-xs truncate px-3 py-2 text-xs" title={row.message ?? ""}>
                      {row.message ?? "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
