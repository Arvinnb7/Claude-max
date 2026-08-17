"use client";

import { useCallback, useEffect, useState } from "react";
import {
  ArrowRight,
  Download,
  FlaskConical,
  Lock,
  RefreshCw,
  ShieldAlert,
  Sparkles,
  TrendingDown,
  TrendingUp,
} from "lucide-react";

import {
  campaignExportUrl,
  closeCampaign,
  getCampaign,
  getLearnedUplift,
  listCampaigns,
  refreshCampaign,
  type CampaignDetail,
  type CampaignReport,
  type CampaignSummary,
  type UpliftTable,
} from "@/lib/apiV1";
import { toFa } from "@/lib/format";

import { Alert, Badge, Button, Card, SectionTitle, Spinner, StatCard } from "./ui";

const VERDICT_TONE: Record<CampaignReport["verdict"], "green" | "accent" | "gray"> = {
  proven: "green",
  inconclusive: "accent",
  attribution_only: "gray",
  not_ready: "gray",
};

function pct(value: number | null | undefined, digits = 1): string {
  if (value == null) return "—";
  return `${toFa((value * 100).toFixed(digits))}٪`;
}

export default function CampaignImpact() {
  const [items, setItems] = useState<CampaignSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [openId, setOpenId] = useState<number | null>(null);
  const [detail, setDetail] = useState<CampaignDetail | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await listCampaigns();
      setItems(res.items ?? []);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "خطا در خواندن کمپین‌ها");
      setItems([]);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    queueMicrotask(() => {
      if (!cancelled) void load();
    });
    return () => {
      cancelled = true;
    };
  }, [load]);

  async function open(id: number) {
    setOpenId(id);
    setDetail(null);
    try {
      setDetail(await getCampaign(id));
    } catch (e) {
      setError(e instanceof Error ? e.message : "خطا در خواندن کمپین");
    }
  }

  async function refresh(id: number) {
    setBusy(true);
    try {
      setDetail(await refreshCampaign(id));
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "به‌روزرسانی ناموفق بود");
    } finally {
      setBusy(false);
    }
  }

  async function close(id: number) {
    setBusy(true);
    try {
      setDetail(await closeCampaign(id));
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "بستن کمپین ناموفق بود");
    } finally {
      setBusy(false);
    }
  }

  if (items === null && !error) {
    return (
      <Card>
        <Spinner label="در حال خواندن کمپین‌ها…" />
      </Card>
    );
  }

  if (openId !== null) {
    return (
      <div className="space-y-3">
        <Button
          variant="ghost"
          onClick={() => {
            setOpenId(null);
            setDetail(null);
          }}
        >
          <ArrowRight size={14} /> بازگشت به فهرست کمپین‌ها
        </Button>
        {detail === null ? (
          <Card>
            <Spinner label="در حال خواندن گزارش اثر…" />
          </Card>
        ) : (
          <CampaignDetailView
            data={detail}
            busy={busy}
            onRefresh={() => void refresh(detail.id)}
            onClose={() => void close(detail.id)}
          />
        )}
      </div>
    );
  }

  return (
    <Card>
      <SectionTitle
        title="اثر کمپین‌ها"
        subtitle="هر کمپین یک آزمایش است: بخشی از مخاطبان عمداً تماس نمی‌گیرند تا بدانیم تماس واقعاً اثر داشت یا نه."
      />

      {error && (
        <div className="mb-3">
          <Alert tone="warn">{error}</Alert>
        </div>
      )}

      <LearnedUplift />

      {!items?.length ? (
        <Alert tone="info">
          هنوز کمپینی ساخته نشده است. از تب «صندوق فرصت‌ها» با دکمه‌ی «ساخت
          کمپین» شروع کنید.
        </Alert>
      ) : (
        <ul className="space-y-2">
          {items.map((c) => (
            <li
              key={c.id}
              className="rounded-xl border border-ink-200 p-3 text-sm dark:border-ink-700"
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <b className="truncate">{c.name}</b>
                    {c.status === "closed" && <Badge tone="gray">بسته‌شده</Badge>}
                    {c.control_size === 0 && (
                      <Badge tone="accent">بدون گروه کنترل</Badge>
                    )}
                    {c.exposed_count === 0 && c.control_size > 0 && (
                      <Badge tone="gray">هنوز تماسی گرفته نشده</Badge>
                    )}
                  </div>
                  <div
                    className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs tnum"
                    style={{ color: "var(--muted)" }}
                  >
                    <span>گروه آزمایش: {toFa(String(c.treatment_size))}</span>
                    <span>گروه کنترل: {toFa(String(c.control_size))}</span>
                    <span>تماس‌گرفته: {toFa(String(c.exposed_count))}</span>
                    <span>پنجره: {toFa(String(c.analysis_window_days))} روز</span>
                    <span>ارزش فهرست: {toFa(c.treatment_pipeline.display_text)}</span>
                  </div>
                </div>
                <div className="flex shrink-0 gap-2">
                  <a href={campaignExportUrl(c.id)} className="inline-flex">
                    <Button variant="outline">
                      <Download size={14} /> فهرست تماس
                    </Button>
                  </a>
                  <Button variant="ghost" onClick={() => void open(c.id)}>
                    گزارش اثر
                  </Button>
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

/**
 * «آنچه یاد گرفته‌ایم» — جدول اثرِ اندازه‌گیری‌شده به‌ازای هر گروه.
 *
 * این جدول مستقیماً ترتیب صندوق فرصت‌ها را تعیین می‌کند، پس دیدنی‌بودنش لازم
 * است: کاربر باید بتواند بفهمد چرا فهرستش عوض شده.
 */
function LearnedUplift() {
  const [data, setData] = useState<UpliftTable | null>(null);

  useEffect(() => {
    let cancelled = false;
    queueMicrotask(() => {
      if (cancelled) return;
      void getLearnedUplift()
        .then((res) => {
          if (!cancelled) setData(res);
        })
        .catch(() => {
          /* نبودِ یادگیری نباید بقیه‌ی صفحه را بشکند */
        });
    });
    return () => {
      cancelled = true;
    };
  }, []);

  if (!data) return null;

  if (!data.available) {
    return (
      <div className="mb-4">
        <Alert tone="info">
          <span className="inline-flex items-center gap-1">
            <Sparkles size={14} /> <b>آنچه یاد گرفته‌ایم</b>
          </span>
          <p className="mt-1">{data.note_fa}</p>
        </Alert>
      </div>
    );
  }

  const cells = (data.cells ?? []).filter((c) => c.has_enough_data);
  const useless = cells.filter((c) => c.useless);

  return (
    <div className="mb-5 rounded-xl border border-brand-200 p-3 dark:border-brand-500/40">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <Sparkles size={16} />
        <b>آنچه یاد گرفته‌ایم</b>
        <span className="text-xs tnum" style={{ color: "var(--muted)" }}>
          از {toFa(String(data.n_observations ?? 0))} مشاهده‌ی آزمایشی
        </span>
        {data.global_uplift != null && (
          <Badge tone={data.global_uplift > 0 ? "green" : "rose"}>
            اثر کل: {pct(data.global_uplift)}
          </Badge>
        )}
      </div>

      {useless.length > 0 && (
        <div className="mb-2">
          <Alert tone="warn">
            <b>{toFa(String(useless.length))} گروه</b> پیدا شد که تماس با آن‌ها
            نتیجه را بهتر نمی‌کند. این گروه‌ها از فهرست تماس حذف می‌شوند تا
            حوصله‌ی مشتری بی‌دلیل خرج نشود.
          </Alert>
        </div>
      )}

      {!cells.length ? (
        <p className="text-xs" style={{ color: "var(--muted)" }}>
          هنوز هیچ گروهی نمونه‌ی کافی برای نتیجه‌گیری ندارد؛ رتبه‌بندی مثل قبل
          کار می‌کند.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr style={{ color: "var(--muted)" }}>
                <th className="p-1.5 text-start font-medium">نوع اقدام</th>
                <th className="p-1.5 text-start font-medium">حالت مشتری</th>
                <th className="p-1.5 text-start font-medium">اثر</th>
                <th className="p-1.5 text-start font-medium">بازه ۹۵٪</th>
                <th className="p-1.5 text-start font-medium">نمونه</th>
                <th className="p-1.5 text-start font-medium">نتیجه</th>
              </tr>
            </thead>
            <tbody>
              {cells.map((c) => (
                <tr
                  key={`${c.kind}|${c.lifecycle_state}`}
                  className="border-t border-ink-100 dark:border-ink-800"
                >
                  <td className="p-1.5">{c.kind}</td>
                  <td className="p-1.5">{c.lifecycle_state}</td>
                  <td className="p-1.5 tnum">{pct(c.uplift)}</td>
                  <td className="p-1.5 tnum">
                    {c.ci ? `${pct(c.ci[0])} تا ${pct(c.ci[1])}` : "—"}
                  </td>
                  <td className="p-1.5 tnum">
                    {toFa(String(c.n_treatment))} / {toFa(String(c.n_control))}
                  </td>
                  <td className="p-1.5">
                    {c.useless ? (
                      <Badge tone="rose">تماس بی‌فایده</Badge>
                    ) : c.uplift > 0 ? (
                      <Badge tone="green">پاسخ می‌دهد</Badge>
                    ) : (
                      <Badge tone="gray">نامعلوم</Badge>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {data.method_note_fa && (
        <p className="mt-2 text-xs" style={{ color: "var(--muted)" }}>
          {data.method_note_fa}
        </p>
      )}
      {data.reference_note_fa && (
        <p className="mt-1 text-xs" style={{ color: "var(--muted)" }}>
          {data.reference_note_fa}
        </p>
      )}
    </div>
  );
}

function CampaignDetailView({
  data,
  busy,
  onRefresh,
  onClose,
}: {
  data: CampaignDetail;
  busy: boolean;
  onRefresh: () => void;
  onClose: () => void;
}) {
  const r = data.report;
  const t = r.arms.treatment;
  const c = r.arms.control;

  return (
    <div className="space-y-4">
      <Card>
        <SectionTitle title={data.name} subtitle={`پنجره‌ی سنجش: ${data.analysis_window_days} روز`} />

        <div className="mb-4 flex flex-wrap items-center gap-2">
          <Badge tone={VERDICT_TONE[r.verdict]}>{r.verdict_label}</Badge>
          {data.status === "closed" && <Badge tone="gray">بسته‌شده</Badge>}
          <div className="ms-auto flex gap-2">
            <a href={campaignExportUrl(data.id)} className="inline-flex">
              <Button variant="outline">
                <Download size={14} /> فهرست تماس
              </Button>
            </a>
            <Button variant="ghost" disabled={busy} onClick={onRefresh}>
              <RefreshCw size={14} /> به‌روزرسانی نتیجه
            </Button>
            {data.status !== "closed" && (
              <Button variant="ghost" disabled={busy} onClick={onClose}>
                <Lock size={14} /> بستن کمپین
              </Button>
            )}
          </div>
        </div>

        <Alert tone={r.is_causal ? "info" : "warn"}>
          <span className="inline-flex items-center gap-1">
            {r.is_causal ? <FlaskConical size={14} /> : <ShieldAlert size={14} />}
            <b>{r.verdict_label}</b>
          </span>
          <span> — {r.verdict_reason_fa}</span>
        </Alert>

        <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-4">
          <StatCard label="نرخ خرید گروه آزمایش" value={pct(t.conversion_rate)} />
          <StatCard label="نرخ خرید گروه کنترل" value={pct(c.conversion_rate)} />
          {/* آیکون لازم است تا رنگِ tone واقعاً دیده شود؛ بدون آن، tone بی‌اثر است */}
          <StatCard
            label="اثر مطلق"
            value={pct(r.absolute_lift)}
            tone={r.absolute_lift && r.absolute_lift > 0 ? "green" : "rose"}
            icon={
              r.absolute_lift && r.absolute_lift < 0 ? (
                <TrendingDown size={16} />
              ) : (
                <TrendingUp size={16} />
              )
            }
          />
          <StatCard
            label="درآمد افزوده"
            value={r.is_causal ? toFa(r.incremental_revenue.display_text) : "—"}
            hint={r.is_causal ? undefined : "تا اثبات اثر، عدد ارائه نمی‌شود"}
          />
        </div>

        {r.lift_ci && (
          <p className="mt-3 text-xs tnum" style={{ color: "var(--muted)" }}>
            بازه‌ی اطمینان ۹۵٪ اثر: از {pct(r.lift_ci[0])} تا {pct(r.lift_ci[1])}
            {r.lift_ci[0] <= 0 && r.lift_ci[1] >= 0
              ? " — چون صفر داخل بازه است، اثر اثبات‌نشده می‌ماند."
              : ""}
          </p>
        )}
      </Card>

      <Card>
        <SectionTitle
          title="آنچه اندازه نگرفتیم"
          subtitle="این سنجه‌ها با زیرساخت فعلی محاسبه‌شدنی نیستند — نبودشان پنهان نمی‌ماند."
        />
        <ul className="space-y-1.5 text-sm">
          {Object.entries(r.blocked_metrics).map(([key, why]) => (
            <li key={key} className="flex flex-wrap gap-2">
              <Badge tone="gray">اندازه‌گیری نشد</Badge>
              <span style={{ color: "var(--muted)" }}>{why}</span>
            </li>
          ))}
        </ul>
      </Card>

      <Card>
        <SectionTitle title="اعضا" subtitle="گروه کنترل عمداً در فهرست تماس نیامده است." />
        <div className="max-h-96 overflow-auto">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-[var(--card)]">
              <tr style={{ color: "var(--muted)" }}>
                <th className="p-2 text-start font-medium">مشتری</th>
                <th className="p-2 text-start font-medium">بازو</th>
                <th className="p-2 text-start font-medium">تماس</th>
                <th className="p-2 text-start font-medium">خرید در پنجره</th>
                <th className="p-2 text-start font-medium">درآمد</th>
              </tr>
            </thead>
            <tbody>
              {data.members.map((m) => (
                <tr
                  key={m.customer_id}
                  className="border-t border-ink-100 dark:border-ink-800"
                >
                  <td className="p-2">{m.customer_name ?? m.customer_id}</td>
                  <td className="p-2">
                    <Badge tone={m.arm === "control" ? "gray" : "brand"}>
                      {m.arm === "control" ? "کنترل" : "آزمایش"}
                    </Badge>
                  </td>
                  <td className="p-2 tnum">{m.exposure_date ?? "—"}</td>
                  <td className="p-2 tnum">
                    {m.outcome ? toFa(String(m.outcome.orders)) : "—"}
                  </td>
                  <td className="p-2 tnum">
                    {m.outcome ? toFa(m.outcome.revenue.display_text) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {data.exposure_note_fa && (
          <p className="mt-3 text-xs" style={{ color: "var(--muted)" }}>
            {data.exposure_note_fa}
          </p>
        )}
      </Card>
    </div>
  );
}
