import type { Metadata } from "next";
import { Noto_Sans_SC, Playfair_Display } from "next/font/google";

import { AppChrome } from "../features/auth/app-chrome";
import { Providers } from "./providers";
import "./globals.css";

const notoSansSc = Noto_Sans_SC({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-body",
  display: "swap",
});

const playfairDisplay = Playfair_Display({
  subsets: ["latin"],
  weight: ["600", "700"],
  variable: "--font-display",
  display: "swap",
});

export const metadata: Metadata = {
  title: "PM 研究工作台",
  description: "面向产品团队的研究管理、证据沉淀与报告工作台。",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN" className={`${notoSansSc.variable} ${playfairDisplay.variable}`}>
      <body className="min-h-screen bg-[color:var(--bg)] font-[family-name:var(--font-body)] text-[color:var(--ink)]">
        <Providers>
          <AppChrome>{children}</AppChrome>
        </Providers>
      </body>
    </html>
  );
}
