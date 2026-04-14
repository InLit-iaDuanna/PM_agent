import type { Metadata } from "next";

import { AppChrome } from "../features/auth/app-chrome";
import { Providers } from "./providers";
import "./globals.css";

export const metadata: Metadata = {
  title: "PM 研究工作台",
  description: "面向产品团队的研究管理、证据沉淀与报告工作台。",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>
        <Providers>
          <AppChrome>{children}</AppChrome>
        </Providers>
      </body>
    </html>
  );
}
