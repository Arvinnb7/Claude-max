"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Check,
  ChevronDown,
  ChevronUp,
  Clock,
  RotateCcw,
  ShieldQuestion,
  X,
} from "lucide-react";

import {
  actOnOpportunity,
  getOpportunity,
  listOpportunities,
  type Opportunity,
  type OpportunityActionName,
  type OpportunityFactor,
} from "@/lib/apiV1";
import { toFa } from "@/lib/format";

import { Alert, Badge, Button, Card, SectionTitle, Spinner } from "./ui";

const STATUS_LABELS: Record<string, string> = {
  open: "باز",
  accepted: "پذیرفته‌شده",
  dismissed: "رد‌شده",
  snoozed: "به‌تعویق‌افتاده",
  done: "انجام‌شده",
  expired: "منقضی",
  superseded: "بی‌مصداق",
  all: "همه",
};

const FILTER_TABS = ["open", "accepted", "snoozed", "dismissed", "all"] as const;

/** نتیجه‌ی هر بررسی با رنگ و برچسب صریح — «بررسی نشد» هرگز شبیه «قبول» نیست. */
const OUTCOME_META: Record<
  OpportunityFactor["outcome"],
  { label: string; tone: "brand" | "green" | "gray" | "rose" }
> = {
  evidence: { label: "شواهد", tone: "brand" },
  filter_pass: { label: "بررسی شد ✓", tone: "green" },
  filter_skip: { label: "بررسی نشد", tone: "gray" },
  filter_block: { label: "مانع", tone: "rose" },
};

function statusTone(status: string): "brand" | "green" | "accent" | "gray" | "rose" {
  if (status === "accepted" || status === "done") return "green";
  if (status === "dismissed") return "rose";
  if (status === "snoozed") return "accent";
  if (status === "open") return "brand";
  return "gray";
}

/** تاریخ میلادی ISO → نمایش جلالی (ارقام فارسی). */
function jalali(iso: string | null): string {
  if (!iso) return "—";
  try {
    return toFa(
      new Intl.DateTimeFormat("fa-IR", {
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
      }).format(new Date(`${iso}T00:00:00`)),
    );
  } catch {
    return iso;
  }
}

function todayPlus(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
}

export default function OpportunityInbox() {
  const [status, setStatus] = useState<string>("open");
  const [data, setData] = useState<Awaited<ReturnType<typeof listOpportunities>> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [openId, setOpenId] = useState<number | null>(null);
  const [detail, setDetail] = useState<Opportunity | null>(null);

  const load = useCallback(async () => {
    try {
      setData(await listOpportunities({ status, limit: 100 }));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "خطا در خواندن صندوق فرصت‌ها");
      setData(null);
    }
  }, [status]);

  useEffect(() => {
    let cancelled = false;
    queueMicrotask(() => {
      if (!cancelled) void load();
    });
    return () => {
      cancelled = true;
    };
  }, [load]);

  async function act(id: number, action: OpportunityActionName) {
    setBusyId(id);
    try {
      await actOnOpportunity(
        id,
        action,
        action === "snooze" ? { snooze_until: todayPlus(14) } : {},
      );
      await load();
      if (openId === id) setDetail(await getOpportunity(id));
    } catch (e) {
      setError(e instanceof Error ? e.message : "ثبت اقدام ناموفق بود");
    } finally {
      setBusyId(null);
    }
  }

  async function toggleDetail(id: number) {
    if (openId === id) {
      setOpenId(null);
      setDetail(null);
      return;
    }
    setOpenId(id);
    setDetail(null);
    try {
      setDetail(await getOpportunity(id));
    } catch (e) {
      setError(e instanceof Error ? e.message : "خطا در خواندن شواهد فرصت");
    }
  }

  if (data === null && error === null) {
    return (
      <Card>
        <Spinner label="در حال خواندن صندوق فرصت‌ها…" />
      </Card>
    );
  }

  if (data && !data.available) {
    return (
      <Card>
        <SectionTitle title="صندوق فرصت‌ها" />
        <Alert tone="info">{data.note_fa}</Alert>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      <Card>
        <SectionTitle
          title="صندوق فرصت‌ها"
          subtitle="کارهای پیشنهادی با ارزش مورد انتظار، شواهد و وضعیت ماندگار."
        />

        {error && (
          <div className="mb-3">
            <Alert tone="warn">{error}</Alert>
          </div>
        )}

        <div className="mb-4 flex flex-wrap items-center gap-2">
          {FILTER_TABS.map((s) => (
            <button
              key={s}
              onClick={() => setStatus(s)}
              className={`rounded-full px-3 py-1.5 text-sm font-medium transition ${
                status === s
                  ? "bg-brand-600 text-white"
                  : "bg-ink-100 text-ink-600 hover:bg-ink-200 dark:bg-ink-800 dark:text-ink-300"
              }`}
            >
              {STATUS_LABELS[s]}
              {data?.status_counts?.[s] != null && (
                <span className="ms-1 tnum">({toFa(String(data.status_counts[s]))})</span>
              )}
            </button>
          ))}
        </div>

        {data?.open_pipeline && (
          <div className="mb-4 rounded-xl border border-ink-200 p-3 text-sm dark:border-ink-700">
            <b>ارزش فرصت‌های باز:</b>{" "}
            <span className="tnum">{toFa(data.open_pipeline.display_text)}</span>
            <p className="mt-1 text-xs" style={{ color: "var(--muted)" }}>
              {data.economics_note_fa}
            </p>
          </div>
        )}

        {!data?.items.length ? (
          <p className="text-sm" style={{ color: "var(--muted)" }}>
            فرصتی با این وضعیت وجود ندارد.
          </p>
        ) : (
          <ul className="space-y-3">
            {data.items.map((o) => (
              <li
                key={o.id}
                className="rounded-xl border border-ink-200 p-3 text-sm dark:border-ink-700"
              >
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <b className="truncate">{o.title}</b>
                      <Badge tone={statusTone(o.status)}>{STATUS_LABELS[o.status] ?? o.status}</Badge>
                      <Badge tone={o.value_kind === "ارزش در معرض خطر" ? "rose" : "brand"}>
                        {o.value_kind}
                      </Badge>
                      {o.confidence && <Badge tone="gray">اطمینان: {o.confidence}</Badge>}
                    </div>
                    <p className="mt-1">{o.action}</p>
                    <p className="mt-1 text-xs" style={{ color: "var(--muted)" }}>
                      {o.reason}
                    </p>
                    <div
                      className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs tnum"
                      style={{ color: "var(--muted)" }}
                    >
                      <span>مشتری: {o.customer_name ?? o.customer_id ?? "—"}</span>
                      {o.due_date && <span>سررسید: {jalali(o.due_date)}</span>}
                      {o.expires_at && <span>اعتبار تا: {jalali(o.expires_at)}</span>}
                      {o.probability != null && (
                        <span>احتمال: {toFa(String(Math.round(o.probability * 100)))}٪</span>
                      )}
                      {o.owner_hint && <span>مسئول پیشنهادی: {o.owner_hint}</span>}
                      {o.assigned_to && <span>واگذارشده به: {o.assigned_to}</span>}
                    </div>
                  </div>

                  <div className="shrink-0 text-end">
                    {/* عدد ریالی هرگز خودش قالب‌بندی نمی‌شود؛ متن آماده رندر می‌شود */}
                    <div className="text-base font-bold tnum">
                      {toFa(o.expected_value.display_text)}
                    </div>
                    <div className="mt-2 flex flex-wrap justify-end gap-1.5">
                      {o.status !== "accepted" && (
                        <Button
                          variant="primary"
                          disabled={busyId === o.id}
                          onClick={() => void act(o.id, "accept")}
                        >
                          <Check size={14} /> پذیرش
                        </Button>
                      )}
                      {o.status === "accepted" && (
                        <Button
                          variant="primary"
                          disabled={busyId === o.id}
                          onClick={() => void act(o.id, "done")}
                        >
                          <Check size={14} /> انجام شد
                        </Button>
                      )}
                      {o.status !== "snoozed" && o.status !== "dismissed" && (
                        <Button
                          variant="outline"
                          disabled={busyId === o.id}
                          onClick={() => void act(o.id, "snooze")}
                        >
                          <Clock size={14} /> دو هفته بعد
                        </Button>
                      )}
                      {o.status !== "dismissed" ? (
                        <Button
                          variant="ghost"
                          disabled={busyId === o.id}
                          onClick={() => void act(o.id, "dismiss")}
                        >
                          <X size={14} /> رد
                        </Button>
                      ) : (
                        <Button
                          variant="ghost"
                          disabled={busyId === o.id}
                          onClick={() => void act(o.id, "reopen")}
                        >
                          <RotateCcw size={14} /> بازگشایی
                        </Button>
                      )}
                      <Button variant="ghost" onClick={() => void toggleDetail(o.id)}>
                        {openId === o.id ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                        شواهد
                      </Button>
                    </div>
                  </div>
                </div>

                {openId === o.id && (
                  <div className="mt-3 border-t border-ink-200 pt-3 dark:border-ink-700">
                    {detail === null ? (
                      <Spinner label="در حال خواندن شواهد…" />
                    ) : (
                      <Evidence opportunity={detail} />
                    )}
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

function Evidence({ opportunity }: { opportunity: Opportunity }) {
  const factors = opportunity.factors ?? [];
  const skipped = factors.filter((f) => f.outcome === "filter_skip");
  return (
    <div className="space-y-3 text-xs">
      {skipped.length > 0 && (
        <Alert tone="warn">
          <span className="inline-flex items-center gap-1">
            <ShieldQuestion size={14} />
            <b>{toFa(String(skipped.length))} بررسی انجام نشده است</b>
          </span>
          <span> — نبودِ داده به‌معنی «تأیید شد» نیست؛ جزئیات پایین آمده است.</span>
        </Alert>
      )}

      <div>
        <div className="mb-1 font-semibold">شواهد و بررسی‌ها</div>
        <ul className="space-y-1.5">
          {factors.map((f) => {
            const meta = OUTCOME_META[f.outcome];
            return (
              <li key={f.code} className="flex flex-wrap items-start gap-2">
                <Badge tone={meta.tone}>{meta.label}</Badge>
                <span className="font-medium">{f.label}</span>
                {f.value && <span className="tnum">{toFa(f.value)}</span>}
                {f.detail && (
                  <span style={{ color: "var(--muted)" }}>— {f.detail}</span>
                )}
              </li>
            );
          })}
        </ul>
      </div>

      <div className="rounded-lg bg-ink-50 p-2 dark:bg-ink-800">
        <b>اثر علّی:</b> {opportunity.causal_note_fa}
      </div>

      {opportunity.message && (
        <div>
          <div className="mb-1 font-semibold">متن پیشنهادی تماس</div>
          <p className="rounded-lg border border-ink-200 p-2 dark:border-ink-700">
            {opportunity.message}
          </p>
        </div>
      )}

      {opportunity.events && opportunity.events.length > 0 && (
        <div>
          <div className="mb-1 font-semibold">تاریخچه</div>
          <ul className="space-y-1" style={{ color: "var(--muted)" }}>
            {opportunity.events.map((e, i) => (
              <li key={i}>
                {e.note ?? e.type}
                {e.actor ? ` — ${e.actor}` : ""}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div style={{ color: "var(--muted)" }}>
        مولد: {opportunity.generator} (نسخه {toFa(String(opportunity.generator_version))}) ·
        دیده‌شده: {toFa(String(opportunity.seen_count))} بار
      </div>
    </div>
  );
}
