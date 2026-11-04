"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { NAV_ITEMS } from "@/lib/constants";

export function AppHeader() {
  // 当前项高亮沿用 M4 既有写法（SessionSidebar/AdminShell 的 aria-current="page"）：
  // T11 认领「管理」入口时按同一口径补高亮，前缀匹配让 /admin/quality 等子页也点亮入口。
  const pathname = usePathname();
  const isActive = (href: string) => pathname === href || pathname.startsWith(`${href}/`);
  return (
    <header className="border-b border-line bg-paper">
      <nav aria-label="主导航" className="mx-auto flex max-w-7xl flex-wrap items-center gap-4 px-4 py-3">
        <Link href="/chat" className="font-serif text-lg font-bold text-cinnabar">
          中医经方
        </Link>
        <ul className="flex flex-wrap items-center gap-3 text-sm">
          {NAV_ITEMS.map((item) => (
            <li key={item.href}>
              {item.disabled ? (
                <span aria-disabled="true" title="M5 交付" className="cursor-not-allowed text-ink/70 line-through">
                  {item.label}
                </span>
              ) : (
                <Link href={item.href} aria-current={isActive(item.href) ? "page" : undefined}
                  className={isActive(item.href) ? "font-semibold text-cinnabar" : "hover:text-cinnabar"}>
                  {item.label}
                </Link>
              )}
            </li>
          ))}
        </ul>
      </nav>
    </header>
  );
}
