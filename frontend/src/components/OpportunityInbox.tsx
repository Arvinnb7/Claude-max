"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Check,
  ChevronDown,
  ChevronUp,
  Clock,
  FlaskConical,
  RotateCcw,
  ShieldQuestion,
  X,
} from "lucide-react";

import {
  actOnOpportunity,
  createCampaign,
  getCostCoverage,
  decideOffer,
  getMarginFloor,
  getOfferPolicy,
  getOpportunity,
  listDismissReasons,
  listOpportunities,
  setMarginFloor,
  setOfferPolicy,
  type CostCoverage,
  type DismissReason,
  type MarginFloor,
  type OfferPolicy,
  type Opportunity,
  type OpportunityActionName,
  type OpportunityFactor,
} from "@/lib/apiV1";
import { toFa } from "@/lib/format";

import { Alert, Badge, Button, Card, SectionTitle, Spinner } from "./ui";

/** همان رشته‌ای که سرور در `relationship_value_kind` می‌فرستد (§۱۸.۵). */
const RELATIONSHIP_VALUE_KIND = "بدون عدد ریالی";

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
  const [showCampaign, setShowCampaign] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [dismissId, setDismissId] = useState<number | null>(null);
  const [reasons, setReasons] = useState<DismissReason[]>([]);

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

  // دلایل رد یک بار خوانده می‌شوند؛ فهرست ثابتی است
  useEffect(() => {
    let cancelled = false;
    queueMicrotask(() => {
      if (cancelled) return;
      void listDismissReasons()
        .then((res) => {
          if (!cancelled) setReasons(res.items);
        })
        .catch(() => {
          /* بدون فهرست دلیل، رد همچنان ممکن است */
        });
    });
    return () => {
      cancelled = true;
    };
  }, []);

  async function decide(id: number, decision: "approve" | "reject") {
    setBusyId(id);
    setError(null);
    try {
      await decideOffer(id, decision, {});
      await load();
      if (openId === id) setDetail(await getOpportunity(id));
    } catch (e) {
      setError(e instanceof Error ? e.message : "ثبت تصمیم درباره‌ی تخفیف انجام نشد");
    } finally {
      setBusyId(null);
    }
  }

  async function act(id: number, action: OpportunityActionName, reasonCode?: string) {
    setBusyId(id);
    try {
      const body: { snooze_until?: string; reason_code?: string } = {};
      if (action === "snooze") body.snooze_until = todayPlus(14);
      if (reasonCode) body.reason_code = reasonCode;
      await actOnOpportunity(id, action, body);
      setDismissId(null);
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
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <b>ارزش فرصت‌های باز:</b>{" "}
                <span className="tnum">{toFa(data.open_pipeline.display_text)}</span>
              </div>
              {status === "open" && !!data.items.length && (
                <Button variant="primary" onClick={() => setShowCampaign((v) => !v)}>
                  <FlaskConical size={14} /> ساخت کمپین از این فهرست
                </Button>
              )}
            </div>
            <p className="mt-1 text-xs" style={{ color: "var(--muted)" }}>
              {data.economics_note_fa}
            </p>
            {!!data.relationship_open_count && (
              <p className="mt-1 text-xs" style={{ color: "var(--muted)" }}>
                <b>اقدام رابطه‌ای با مشتریان کلیدی آینده:</b>{" "}
                <span className="tnum">
                  {toFa(String(data.relationship_open_count))} مشتری
                </span>{" "}
                — {data.relationship_note_fa}
              </p>
            )}
          </div>
        )}

        <MarginPolicyPanel />

        {showCampaign && (
          <CampaignForm
            onCancel={() => setShowCampaign(false)}
            onCreated={(message) => {
              setShowCampaign(false);
              setNotice(message);
              void load();
            }}
          />
        )}

        {notice && (
          <div className="mb-3">
            <Alert tone="info">{notice}</Alert>
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
                      {o.offer && <OfferBadge offer={o.offer} />}
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
                    {/*
                      عدد ریالی هرگز خودش قالب‌بندی نمی‌شود؛ متن آماده رندر می‌شود.
                      اقدام رابطه‌ای عمداً مبلغ ندارد و نشان‌دادنِ «۰ تومان» برایش
                      دروغ است — پس به‌جای عدد، ماهیتش نوشته می‌شود.
                    */}
                    <div className="text-base font-bold tnum">
                      {o.value_kind === RELATIONSHIP_VALUE_KIND
                        ? "—"
                        : toFa(o.expected_value.display_text)}
                    </div>
                    {o.value_kind === RELATIONSHIP_VALUE_KIND && (
                      <div className="text-xs" style={{ color: "var(--muted)" }}>
                        بدون عدد ریالی
                      </div>
                    )}
                    <div className="mt-2 flex flex-wrap justify-end gap-1.5">
                      {o.offer && (o.offer.status === "suggested" || o.offer.status === "stale") && (
                        <>
                          <Button
                            variant="outline"
                            disabled={busyId === o.id}
                            onClick={() => void decide(o.id, "approve")}
                          >
                            <Check size={14} /> تأیید تخفیف {toFa(o.offer.suggested_discount_text)}
                          </Button>
                          <Button
                            variant="ghost"
                            disabled={busyId === o.id}
                            onClick={() => void decide(o.id, "reject")}
                          >
                            رد تخفیف
                          </Button>
                        </>
                      )}
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
                          onClick={() => setDismissId(dismissId === o.id ? null : o.id)}
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

                {dismissId === o.id && (
                  <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-ink-200 pt-3 text-xs dark:border-ink-700">
                    <span style={{ color: "var(--muted)" }}>چرا رد می‌کنید؟</span>
                    {reasons.map((reason) => (
                      <button
                        key={reason.code}
                        disabled={busyId === o.id}
                        onClick={() => void act(o.id, "dismiss", reason.code)}
                        className="rounded-full bg-ink-100 px-3 py-1 font-medium transition hover:bg-ink-200 disabled:opacity-50 dark:bg-ink-800 dark:hover:bg-ink-700"
                      >
                        {reason.label}
                      </button>
                    ))}
                  </div>
                )}

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

/** فرم ساخت کمپین — گروه کنترل پیش‌فرض دارد، چون بدون آن اثر قابل اثبات نیست. */
function CampaignForm({
  onCancel,
  onCreated,
}: {
  onCancel: () => void;
  onCreated: (message: string) => void;
}) {
  const [name, setName] = useState("");
  // ۲۰٪ پیشنهاد می‌شود چون آماری کاراتر از ۱۰٪ است: برای همان قدرت تفکیک،
  // کل کمپین حدود نصف می‌شود. تا پیش از این، این فرم ۱۰٪ را «پیشنهاد»
  // برچسب می‌زد در حالی که طراح آزمایش ۲۰٪ را توصیه می‌کرد.
  const [holdout, setHoldout] = useState(20);
  const [windowDays, setWindowDays] = useState(30);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    if (!name.trim()) {
      setError("نام کمپین لازم است.");
      return;
    }
    setBusy(true);
    try {
      const created = await createCampaign({
        name: name.trim(),
        holdout_pct: holdout,
        analysis_window_days: windowDays,
      });
      onCreated(
        `کمپین «${created.name}» ساخته شد: ${toFa(String(created.treatment_size))} نفر ` +
          `گروه آزمایش و ${toFa(String(created.control_size))} نفر گروه کنترل. ` +
          "فهرست تماس را از تب «اثر کمپین‌ها» دانلود کنید.",
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "ساخت کمپین ناموفق بود");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mb-4 rounded-xl border border-brand-200 p-3 dark:border-brand-500/40">
      <div className="mb-2 font-semibold">ساخت کمپین</div>
      {error && (
        <div className="mb-2">
          <Alert tone="warn">{error}</Alert>
        </div>
      )}
      <div className="flex flex-wrap items-end gap-3 text-sm">
        <label className="flex min-w-48 flex-1 flex-col gap-1">
          <span className="text-xs" style={{ color: "var(--muted)" }}>
            نام کمپین
          </span>
          <input
            className="rounded-lg border border-ink-200 bg-transparent px-3 py-2 dark:border-ink-700"
            placeholder="مثلاً یادآوری چرخه — مهر"
            value={name}
            maxLength={80}
            onChange={(e) => setName(e.target.value)}
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs" style={{ color: "var(--muted)" }}>
            گروه کنترل
          </span>
          <select
            className="rounded-lg border border-ink-200 bg-transparent px-3 py-2 dark:border-ink-700"
            value={holdout}
            onChange={(e) => setHoldout(Number(e.target.value))}
          >
            <option value={20}>۲۰٪ (پیشنهاد)</option>
            <option value={10}>۱۰٪</option>
            <option value={0}>بدون گروه کنترل</option>
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs" style={{ color: "var(--muted)" }}>
            پنجره‌ی سنجش
          </span>
          <select
            className="rounded-lg border border-ink-200 bg-transparent px-3 py-2 dark:border-ink-700"
            value={windowDays}
            onChange={(e) => setWindowDays(Number(e.target.value))}
          >
            <option value={14}>۱۴ روز</option>
            <option value={30}>۳۰ روز</option>
            <option value={60}>۶۰ روز</option>
          </select>
        </label>
        <div className="flex gap-2">
          <Button variant="primary" disabled={busy} onClick={() => void submit()}>
            ساخت
          </Button>
          <Button variant="ghost" onClick={onCancel}>
            انصراف
          </Button>
        </div>
      </div>
      <p className="mt-2 text-xs" style={{ color: "var(--muted)" }}>
        {holdout === 0
          ? "بدون گروه کنترل، فقط می‌شود گفت چه اتفاقی افتاد — نه اینکه به‌خاطر تماس شما بوده است."
          : `${toFa(String(holdout))}٪ از مخاطبان عمداً تماس نمی‌گیرند تا اثر واقعی تماس قابل اندازه‌گیری باشد.${
              holdout === 20
                ? " گروه کنترل بزرگ‌تر آماری کاراتر است: برای دیدن همان اثر، کل کمپین کوچک‌تر می‌شود."
                : ""
            }`}
      </p>
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


/**
 * سیاستِ حاشیه — پوششِ بها (که می‌گوید سود اصلاً محاسبه‌شدنی هست یا نه) و
 * کفِ حاشیه (که **کاربر** تعیینش می‌کند).
 *
 * چرا کنار هم: تا وقتی بها نباشد، کف حاشیه هیچ کاری نمی‌کند؛ و تا وقتی کف
 * تعیین نشده، فیلترِ حاشیه در گزارشِ هر فرصت «بررسی نشد» ثبت می‌شود. نشان‌دادن
 * یکی بدون دیگری، کاربر را به این گمان می‌اندازد که حاشیه کنترل شده است.
 */
const OFFER_STATUS_LABEL: Record<string, string> = {
  suggested: "در انتظار تأیید",
  approved: "مصوب — قابل ارسال",
  rejected: "رد شده",
  stale: "کهنه — تأیید دوباره لازم است",
  withdrawn: "برداشته شد",
};

const OFFER_STATUS_TONE: Record<string, "brand" | "accent" | "green" | "rose" | "gray"> = {
  suggested: "accent",
  approved: "green",
  rejected: "gray",
  stale: "rose",
  withdrawn: "gray",
};

/**
 * نشانِ تخفیفِ پیشنهادی (§۲۰.۳). قاعده‌ی سخت: تا وقتی «مصوب» نباشد، هیچ پیامکی
 * با تخفیف نمی‌رود — و همین را روی خودِ نشان می‌گوید تا کسی گمان نکند «پیشنهاد»
 * یعنی «اعمال‌شده».
 */
function OfferBadge({ offer }: { offer: NonNullable<Opportunity["offer"]> }) {
  const label = OFFER_STATUS_LABEL[offer.status] ?? offer.status;
  return (
    <Badge tone={OFFER_STATUS_TONE[offer.status] ?? "gray"}>
      تخفیف {toFa(offer.suggested_discount_text)} · {label}
    </Badge>
  );
}


function MarginPolicyPanel() {
  const [coverage, setCoverage] = useState<CostCoverage | null>(null);
  const [floor, setFloor] = useState<MarginFloor | null>(null);
  const [policy, setPolicy] = useState<OfferPolicy | null>(null);
  const [ladderDraft, setLadderDraft] = useState("");
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);

  const load = useCallback(async () => {
    try {
      const [c, f, p] = await Promise.all([
        getCostCoverage(),
        getMarginFloor(),
        // نصبِ قدیمی این مسیر را ندارد؛ نبودش نباید پنلِ حاشیه را بخواباند
        getOfferPolicy().catch(() => null),
      ]);
      setCoverage(c);
      setFloor(f);
      setPolicy(p);
      setLadderDraft(p?.ladder_bp ? p.ladder_bp.map((bp) => String(bp / 100)).join("، ") : "");
      setDraft(f.margin_floor_bp == null ? "" : String(f.margin_floor_bp / 100));
    } catch (e) {
      setError(e instanceof Error ? e.message : "خطا در خواندن سیاست حاشیه");
    }
  }, []);

  // همان الگوی بقیه‌ی این فایل: خواندن بیرون از رندرِ همگام انجام می‌شود
  useEffect(() => {
    let cancelled = false;
    queueMicrotask(() => {
      if (!cancelled) void load();
    });
    return () => {
      cancelled = true;
    };
  }, [load]);

  async function saveLadder(raw: string) {
    setBusy(true);
    setError(null);
    try {
      const rungs = raw
        .split(/[،,\s]+/)
        .map((part) => part.trim())
        .filter(Boolean)
        .map((part) =>
          Math.round(Number(part.replace(/[۰-۹]/g, (d) => String("۰۱۲۳۴۵۶۷۸۹".indexOf(d)))) * 100),
        );
      if (rungs.some((r) => Number.isNaN(r))) {
        setError("پله‌ها باید عدد باشند؛ مثلاً «۵، ۱۰، ۱۵»");
        return;
      }
      const next = await setOfferPolicy({ ladder_bp: rungs });
      setPolicy(next);
      setLadderDraft(next.ladder_bp ? next.ladder_bp.map((bp) => String(bp / 100)).join("، ") : "");
    } catch (e) {
      setError(e instanceof Error ? e.message : "خطا در ثبت نردبان تخفیف");
    } finally {
      setBusy(false);
    }
  }

  async function save(bp: number | null) {
    setBusy(true);
    setError(null);
    try {
      const next = await setMarginFloor(bp);
      setFloor(next);
      setDraft(next.margin_floor_bp == null ? "" : String(next.margin_floor_bp / 100));
    } catch (e) {
      setError(e instanceof Error ? e.message : "خطا در ثبت کف حاشیه");
    } finally {
      setBusy(false);
    }
  }

  if (!coverage || !floor) return null;

  const percent = Math.round((coverage.coverage ?? 0) * 100);
  return (
    <div className="mb-4 rounded-xl border border-ink-200 p-3 text-sm dark:border-ink-700">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <b>پوشش بهای تمام‌شده:</b>{" "}
          <span className="tnum">{toFa(String(percent))}٪</span>
          {floor.margin_floor_bp != null && (
            <>
              {" · "}
              <b>کف حاشیه:</b>{" "}
              <span className="tnum">{toFa(String(floor.margin_floor_bp / 100))}٪</span>
            </>
          )}
        </div>
        <Button variant="ghost" onClick={() => setOpen((v) => !v)}>
          {open ? <ChevronUp size={14} /> : <ChevronDown size={14} />} کف حاشیه
        </Button>
      </div>
      <p className="mt-1 text-xs" style={{ color: "var(--muted)" }}>
        {toFa(coverage.note_fa)}
      </p>
      <p className="mt-1 text-xs" style={{ color: "var(--muted)" }}>
        {toFa(floor.note_fa)}
      </p>

      {open && (
        <div className="mt-3 space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <label className="text-xs" htmlFor="margin-floor">
              کف حاشیه (درصد)
            </label>
            <input
              id="margin-floor"
              type="number"
              min={0}
              max={100}
              step={0.5}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              className="w-24 rounded-lg border border-ink-200 px-2 py-1 tnum dark:border-ink-700 dark:bg-ink-900"
            />
            <Button
              variant="primary"
              disabled={busy || draft.trim() === ""}
              onClick={() => save(Math.round(Number(draft) * 100))}
            >
              ثبت
            </Button>
            <Button
              variant="ghost"
              disabled={busy || floor.margin_floor_bp == null}
              onClick={() => save(null)}
            >
              برداشتن کف
            </Button>
          </div>
          <p className="text-xs" style={{ color: "var(--muted)" }}>
            تا وقتی کف تعیین نشده، هیچ پیشنهادی به‌خاطر حاشیه رد نمی‌شود و در
            شواهدِ هر فرصت «بررسی نشد» ثبت می‌ماند — نه «قبول».
          </p>
          {!!floor.products_below_floor?.length && (
            <p className="text-xs" style={{ color: "var(--muted)" }}>
              با این کف، این کالاها کنار می‌روند:{" "}
              {floor.products_below_floor.slice(0, 8).join("، ")}
              {floor.products_below_floor.length > 8 ? " …" : ""}
            </p>
          )}
          {policy && (
            <div className="mt-3 space-y-2 border-t border-ink-200 pt-3 dark:border-ink-700">
              <div className="flex flex-wrap items-center gap-2">
                <label className="text-xs" htmlFor="offer-ladder">
                  نردبان تخفیف (درصد، با ویرگول)
                </label>
                <input
                  id="offer-ladder"
                  type="text"
                  dir="ltr"
                  value={ladderDraft}
                  onChange={(e) => setLadderDraft(e.target.value)}
                  placeholder="۵، ۱۰، ۱۵"
                  className="w-40 rounded-lg border border-ink-200 px-2 py-1 tnum dark:border-ink-700 dark:bg-ink-900"
                />
                <Button
                  variant="primary"
                  disabled={busy || ladderDraft.trim() === ""}
                  onClick={() => saveLadder(ladderDraft)}
                >
                  ثبت نردبان
                </Button>
                <Button
                  variant="ghost"
                  disabled={busy || !policy.ladder_bp}
                  onClick={() => saveLadder("")}
                >
                  برداشتن نردبان
                </Button>
              </div>
              <p className="text-xs" style={{ color: "var(--muted)" }}>
                {toFa(policy.note_fa)}
              </p>
              {policy.ladder_bp && policy.open_opportunities != null && (
                <p className="text-xs tnum" style={{ color: "var(--muted)" }}>
                  دسترسیِ نردبان: {toFa(String(policy.reachable_by_ladder ?? 0))} از{" "}
                  {toFa(String(policy.open_opportunities))} فرصتِ باز (کالای با حاشیه:{" "}
                  {toFa(String(policy.with_product_margin ?? 0))} · مشتری با طبقه‌ی معلوم:{" "}
                  {toFa(String(policy.with_known_tier ?? 0))})
                </p>
              )}
              <p className="text-xs" style={{ color: "var(--muted)" }}>
                سیستم فقط <b>پیشنهاد</b> می‌کند: کوچک‌ترین پله‌ای که حاشیه‌ی پس از تخفیف را
                روی کف نگه دارد. هیچ تخفیفی بدون تأییدِ شما روی کارتِ فرصت ارسال نمی‌شود.
              </p>
            </div>
          )}
          {error && <Alert tone="warn">{error}</Alert>}
        </div>
      )}
    </div>
  );
}
