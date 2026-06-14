import type { Metadata } from "next";
import { Vazirmatn } from "next/font/google";
import "./globals.css";

const vazirmatn = Vazirmatn({
  subsets: ["arabic", "latin"],
  variable: "--font-vazir",
  display: "swap",
});

export const metadata: Metadata = {
  title: "هوش فروش — تحلیل داده و استراتژی مارکتینگ",
  description:
    "سیستم اتوماسیون تحلیل داده، پیش‌بینی فروش، تارگت‌گذاری و استراتژی مارکتینگ با هوش مصنوعی",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="fa" dir="rtl" className={vazirmatn.variable}>
      <body className="min-h-screen antialiased">{children}</body>
    </html>
  );
}
