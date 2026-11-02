import type { Metadata } from "next";

import { DisclaimerBar } from "@/components/shell/DisclaimerBar";
import { AppHeader } from "@/components/shell/AppHeader";

import "./globals.css";

export const metadata: Metadata = {
  title: "中医经方 RAG",
  description: "本地蒸馏语料检索与辨证参考",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body className="min-h-screen bg-paper pb-14 font-sans text-ink">
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:bg-paper focus:p-2"
        >
          跳到主内容
        </a>
        <AppHeader />
        <main id="main">{children}</main>
        <DisclaimerBar />
      </body>
    </html>
  );
}
