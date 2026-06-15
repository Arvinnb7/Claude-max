"use client";

import { useEffect, useState } from "react";
import { BarChart3, BrainCircuit, Target } from "lucide-react";

import { analyze, getHealth } from "@/lib/api";
import type { AnalyzeResponse, UploadResponse } from "@/lib/types";
import Dashboard from "@/components/Dashboard";
import { MappingStep, Stepper, UploadStep } from "@/components/steps";
import { ThemeToggle } from "@/components/ThemeToggle";
import { Alert } from "@/components/ui";

type Stage = "upload" | "mapping" | "dashboard";

export default function Home() {
  const [stage, setStage] = useState<Stage>("upload");
  const [upload, setUpload] = useState<UploadResponse | null>(null);
  const [analysis, setAnalysis] = useState<AnalyzeResponse | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [aiAvailable, setAiAvailable] = useState(false);
  const [serverDown, setServerDown] = useState(false);

  useEffect(() => {
    getHealth()
      .then((h) => setAiAvailable(h.ai_available))
      .catch(() => setServerDown(true));
  }, []);

  async function handleConfirm(mapping: Record<string, string>) {
    if (!upload) return;
    setError(null);
    setAnalyzing(true);
    try {
      const res = await analyze({
        session_id: upload.session_id,
        mapping,
        horizon: 6,
        balanced_uplift: 0.1,
      });
      setAnalysis(res);
      setStage("dashboard");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setAnalyzing(false);
    }
  }

  function reset() {
    setUpload(null);
    setAnalysis(null);
    setError(null);
    setStage("upload");
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

      <div className="mx-auto max-w-6xl px-4 py-8">
        {serverDown && (
          <div className="mb-6">
            <Alert tone="error">
              اتصال به سرور API برقرار نشد. مطمئن شوید backend در حال اجراست (
              <code>uvicorn api.main:app</code>) و آدرس آن در{" "}
              <code>NEXT_PUBLIC_API_URL</code> درست است.
            </Alert>
          </div>
        )}

        {stage !== "dashboard" && <Stepper active={stepIndex} />}

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
              onLoaded={(r) => {
                setUpload(r);
                setStage("mapping");
              }}
            />
          </div>
        )}

        {stage === "mapping" && upload && (
          <div className="animate-fade-up">
            <MappingStep
              data={upload}
              loading={analyzing}
              onBack={reset}
              onConfirm={handleConfirm}
            />
          </div>
        )}

        {stage === "dashboard" && analysis && upload && (
          <div className="animate-fade-up">
            <Dashboard
              data={analysis}
              sessionId={upload.session_id}
              aiAvailable={aiAvailable}
              onReset={reset}
            />
          </div>
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
