"use client";

import { useEffect, useState } from "react";
import { BarChart3, BrainCircuit, Target, X } from "lucide-react";

import { analyze, getHealthWithRetry, getSessionInfo } from "@/lib/api";
import type {
  AnalyzeResponse,
  CampaignResponse,
  HealthResponse,
  StrategyResponse,
  UploadResponse,
} from "@/lib/types";
import Dashboard from "@/components/Dashboard";
import { MappingStep, Stepper, UploadStep } from "@/components/steps";
import { ThemeToggle } from "@/components/ThemeToggle";
import { Alert, ProgressBar, Spinner } from "@/components/ui";

type Stage = "upload" | "mapping" | "dashboard";

const SS_SESSION = "mkt.session_id";
const SS_STAGE = "mkt.stage";

function saveStage(sessionId: string | null, stage: Stage) {
  try {
    if (sessionId) {
      sessionStorage.setItem(SS_SESSION, sessionId);
      sessionStorage.setItem(SS_STAGE, stage);
    } else {
      sessionStorage.removeItem(SS_SESSION);
      sessionStorage.removeItem(SS_STAGE);
    }
  } catch {
    /* sessionStorage در دسترس نیست (مثلاً حالت خصوصی) — بدون ذخیره ادامه بده */
  }
}

export default function Home() {
  const [booting, setBooting] = useState(true);
  const [stage, setStage] = useState<Stage>("upload");
  const [upload, setUpload] = useState<UploadResponse | null>(null);
  const [analysis, setAnalysis] = useState<AnalyzeResponse | null>(null);
  const [strategy, setStrategy] = useState<StrategyResponse | null>(null);
  const [campaign, setCampaign] = useState<CampaignResponse | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [progress, setProgress] = useState<{ pct: number; stage: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [serverDown, setServerDown] = useState(false);
  const [bannerDismissed, setBannerDismissed] = useState(false);
  const [restoreNotice, setRestoreNotice] = useState<string | null>(null);

  // سلامت سرور با retry — تا یک قطعی لحظه‌ای بنر خطا نیاورد
  useEffect(() => {
    let cancelled = false;
    getHealthWithRetry(3)
      .then((h) => {
        if (!cancelled) {
          setHealth(h);
          setServerDown(false);
        }
      })
      .catch(() => {
        if (!cancelled) setServerDown(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // بازیابی نشست بعد از reload — رفع «برگشتن به صفحه‌ی اول»
  useEffect(() => {
    let cancelled = false;
    let sid: string | null = null;
    try {
      sid = sessionStorage.getItem(SS_SESSION);
    } catch {
      /* noop */
    }
    const restore = sid
      ? getSessionInfo(sid)
          .then((info) => {
            if (cancelled) return;
            if (!info.exists) {
              saveStage(null, "upload");
              return;
            }
            if (!info.columns_payload) {
              // آپلود قبلی هرگز کامل نشد (مثلاً سرور وسط کار متوقف شد)
              setRestoreNotice(
                "پردازش قبلی فایل ناتمام ماند (احتمالاً سرور در میانه‌ی کار متوقف شد)؛ لطفاً فایل را دوباره بارگذاری کنید.",
              );
              saveStage(null, "upload");
              return;
            }
            setUpload(info.columns_payload);
            if (info.analysis) {
              setAnalysis(info.analysis);
              setStrategy(info.strategy ?? null);
              setCampaign(info.campaign ?? null);
              setStage("dashboard");
            } else {
              setStage("mapping");
            }
          })
          .catch(() => {
            /* سرور در دسترس نیست یا نشست منقضی شده — از صفحه‌ی آپلود شروع می‌شود */
          })
      : Promise.resolve();
    restore.finally(() => {
      if (!cancelled) setBooting(false);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  async function handleConfirm(mapping: Record<string, string>) {
    if (!upload) return;
    setError(null);
    setAnalyzing(true);
    setProgress({ pct: 0, stage: "در صف پردازش…" });
    try {
      const res = await analyze(
        {
          session_id: upload.session_id,
          mapping,
          horizon: 6,
          balanced_uplift: 0.1,
        },
        (pct, stg) => setProgress({ pct, stage: stg }),
      );
      setAnalysis(res);
      setStage("dashboard");
      saveStage(upload.session_id, "dashboard");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setAnalyzing(false);
      setProgress(null);
    }
  }

  function reset() {
    setUpload(null);
    setAnalysis(null);
    setStrategy(null);
    setCampaign(null);
    setError(null);
    setStage("upload");
    saveStage(null, "upload");
  }

  const stepIndex = stage === "upload" ? 0 : stage === "mapping" ? 1 : 2;

  return (
    <main className="min-h-screen">
      <header className="hero-gradient border-b" style={{ borderColor: "var(--border)" }}>
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-4">
          <div className="flex items-center gap-3">
            <span className="grid h-10 w-10 place-items-center rounded-2xl bg-brand-600 text-white shadow">
              <BrainCircuit size={22} />
            </span>
            <div>
              <h1 className="text-lg font-extrabold">هوش فروش</h1>
              <p className="text-xs" style={{ color: "var(--muted)" }}>
                تحلیل داده، پیش‌بینی و استراتژی مارکتینگ
              </p>
            </div>
          </div>
          <div className="flex items-center gap-4">
            <div
              className="hidden items-center gap-4 text-sm md:flex"
              style={{ color: "var(--muted)" }}
            >
              <span className="flex items-center gap-1.5">
                <BarChart3 size={16} className="text-brand-500" /> تحلیل آماری
              </span>
              <span className="flex items-center gap-1.5">
                <Target size={16} className="text-accent-500" /> تارگت‌گذاری
              </span>
              <span className="flex items-center gap-1.5">
                <BrainCircuit size={16} className="text-emerald-500" /> استراتژی AI
              </span>
            </div>
            <ThemeToggle />
          </div>
        </div>
      </header>

      {/* بنر ثابت خطای اتصال — بدون جابجا کردن محتوای صفحه */}
      {serverDown && !bannerDismissed && (
        <div className="fixed inset-x-4 bottom-4 z-50 mx-auto max-w-2xl">
          <div className="flex items-start justify-between gap-3 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800 shadow-lg dark:border-rose-500/30 dark:bg-ink-900 dark:text-rose-200">
            <span>
              اتصال به سرور API برقرار نشد. مطمئن شوید backend در حال اجراست (
              <code>uvicorn api.main:app</code>) و آدرس آن در{" "}
              <code>NEXT_PUBLIC_API_URL</code> درست است.
            </span>
            <button
              onClick={() => setBannerDismissed(true)}
              className="shrink-0 rounded-lg p-1 hover:bg-rose-100 dark:hover:bg-ink-800"
              aria-label="بستن"
            >
              <X size={16} />
            </button>
          </div>
        </div>
      )}

      <div className="mx-auto max-w-6xl px-4 py-8">
        {booting ? (
          <Spinner label="در حال بازیابی نشست قبلی…" />
        ) : (
          <>
            {stage !== "dashboard" && <Stepper active={stepIndex} />}

            {restoreNotice && (
              <div className="mb-6">
                <Alert tone="warn">
                  <div className="flex items-start justify-between gap-3">
                    <span>{restoreNotice}</span>
                    <button
                      onClick={() => setRestoreNotice(null)}
                      className="shrink-0 rounded-lg p-1 hover:bg-amber-100 dark:hover:bg-ink-800"
                      aria-label="بستن"
                    >
                      <X size={16} />
                    </button>
                  </div>
                </Alert>
              </div>
            )}

            {error && (
              <div className="mb-6">
                <Alert tone="error">{error}</Alert>
              </div>
            )}

            {stage === "upload" && (
              <div className="animate-fade-up">
                <div className="mb-8 text-center">
                  <h2 className="text-2xl font-extrabold sm:text-3xl">
                    داده‌ی فروش‌تان را به استراتژی تبدیل کنید
                  </h2>
                  <p
                    className="mx-auto mt-3 max-w-2xl text-sm leading-7"
                    style={{ color: "var(--muted)" }}
                  >
                    فایل فروش را بارگذاری کنید تا سیستم مثل یک مدیر مارکتینگ سنیور، عوامل مؤثر را
                    تحلیل کند، فروش را پیش‌بینی کند، تارگت بگذارد و برنامه‌ی عملیاتی بدهد.
                  </p>
                </div>
                <UploadStep
                  onSession={(sid) => saveStage(sid, "upload")}
                  onLoaded={(r) => {
                    setUpload(r);
                    setStage("mapping");
                    saveStage(r.session_id, "mapping");
                  }}
                />
              </div>
            )}

            {stage === "mapping" && upload && (
              <div className="animate-fade-up">
                {analyzing && progress ? (
                  <ProgressBar
                    pct={progress.pct}
                    stage={progress.stage}
                    label="در حال تحلیل داده — این صفحه را باز نگه دارید"
                  />
                ) : (
                  <MappingStep
                    data={upload}
                    loading={analyzing}
                    onBack={reset}
                    onConfirm={handleConfirm}
                  />
                )}
              </div>
            )}

            {stage === "dashboard" && analysis && upload && (
              <div className="animate-fade-up">
                <Dashboard
                  data={analysis}
                  sessionId={upload.session_id}
                  aiAvailable={health?.ai_available ?? false}
                  smsEnabled={health?.sms_enabled ?? false}
                  initialStrategy={strategy}
                  initialCampaign={campaign}
                  onReset={reset}
                />
              </div>
            )}
          </>
        )}
      </div>

      <footer
        className="mt-10 border-t py-6 text-center text-xs"
        style={{ color: "var(--muted)", borderColor: "var(--border)" }}
      >
        ساخته‌شده با هسته‌ی تحلیل mktcore + هوش مصنوعی Claude
      </footer>
    </main>
  );
}
