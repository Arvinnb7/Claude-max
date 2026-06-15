"use client";

import { useSyncExternalStore } from "react";
import { Moon, Sun } from "lucide-react";

function subscribe(callback: () => void): () => void {
  const observer = new MutationObserver(callback);
  observer.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ["class"],
  });
  return () => observer.disconnect();
}

const isDarkClient = () => document.documentElement.classList.contains("dark");

export function ThemeToggle() {
  // خواندن وضعیت تم از DOM به‌صورت idiomatic (بدون setState در effect)
  const dark = useSyncExternalStore(subscribe, isDarkClient, () => false);

  function toggle() {
    const next = !document.documentElement.classList.contains("dark");
    document.documentElement.classList.toggle("dark", next);
    try {
      localStorage.setItem("theme", next ? "dark" : "light");
    } catch {
      /* noop */
    }
  }

  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={dark ? "حالت روشن" : "حالت تاریک"}
      title={dark ? "حالت روشن" : "حالت تاریک"}
      suppressHydrationWarning
      className="grid h-10 w-10 place-items-center rounded-xl border border-ink-200 text-ink-600 transition hover:bg-ink-50 dark:border-ink-700 dark:text-ink-300 dark:hover:bg-ink-800"
    >
      {dark ? <Sun size={18} /> : <Moon size={18} />}
    </button>
  );
}
