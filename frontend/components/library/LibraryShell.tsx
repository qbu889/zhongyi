import Link from "next/link";
import type { ReactNode } from "react";

import { PAGE_SIZE } from "@/lib/constants";
import { pageHref } from "@/lib/filters";

import { FilterPanel, type FilterGroup } from "./FilterPanel";

export function LibraryShell({
  title, total, basePath, params, groups, children,
}: {
  title: string;
  total: number;
  basePath: string;
  params: URLSearchParams;
  groups: FilterGroup[];
  children: ReactNode;
}) {
  const page = Number(params.get("page") ?? "1") || 1;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const initial: Record<string, string[]> = {};
  params.forEach((value, key) => {
    if (key === "page") return;
    (initial[key] ??= []).push(value);
  });

  return (
    <div className="mx-auto grid max-w-7xl gap-6 px-4 py-4 md:grid-cols-[240px_1fr]">
      <FilterPanel basePath={basePath} groups={groups} initial={initial} />
      <section>
        <h1 className="font-serif text-2xl">{title}</h1>
        <p className="mt-1 text-sm text-ink/60">共 {total} 条</p>
        {total === 0 ? (
          <p className="mt-4 text-sm text-ink/60">
            没有匹配结果，换个筛选，或者
            <Link href="/chat" className="ml-1 text-cinnabar underline">去对话页问</Link>
          </p>
        ) : (
          <ul className="mt-2">{children}</ul>
        )}
        {pages > 1 && (
          <nav aria-label="分页" className="mt-4 flex items-center gap-3 text-sm">
            {page > 1 && <Link href={pageHref(basePath, params, page - 1)}>上一页</Link>}
            <span>第 {page} / {pages} 页</span>
            {page < pages && <Link href={pageHref(basePath, params, page + 1)}>下一页</Link>}
          </nav>
        )}
      </section>
    </div>
  );
}
