import Link from "next/link";

import { NAV_ITEMS } from "@/lib/constants";

export function AppHeader() {
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
                <Link href={item.href} className="hover:text-cinnabar">
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
