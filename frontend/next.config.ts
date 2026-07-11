import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // خروجی standalone برای اجرای سبک داخل Docker (بدون node_modules کامل)
  output: "standalone",
};

export default nextConfig;
