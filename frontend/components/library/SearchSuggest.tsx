"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { search } from "@/lib/api";
import { refHref } from "@/lib/refs";
import type { SearchHit } from "@/lib/types";

const GROUPS = [
  ["exact", "精确"],
  ["literal", "字面"],
  ["vector", "语义相关"],
] as const;

export function SearchSuggest({
  kinds,
  initialQuery = "",
  onCommit,
  onPick,
}: {
  kinds: string[];
  initialQuery?: string;
  onCommit: (query: string) => void;
  /** 可选：给了就把命中项渲染成「选择 X」按钮（M5 的归并目标选择器用），
   * 不给则**完全保持 M4 的跳转链接行为**——`tests/unit/library.test.tsx` 一字未改仍通过，
   * 那条回归锁不是可选优化。 */
  onPick?: (hit: SearchHit) => void;
}) {
  const [query, setQuery] = useState(initialQuery);
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const text = query.trim();
    if (!text) {
      setHits([]);
      setOpen(false);
      return;
    }
    let cancelled = false;
    const timer = setTimeout(() => {
      search(text, kinds)
        .then((response) => {
          if (cancelled) return;
          setHits(response.hits);
          setOpen(true);
        })
        .catch(() => {
          if (cancelled) return;
          setHits([]);
          setOpen(false);
        });
    }, 250);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [query, kinds]);

  return (
    <div className="relative">
      <form role="search" onSubmit={(event) => {
        event.preventDefault();
        onCommit(query.trim());
        setOpen(false);
      }}>
        <label htmlFor="library-search" className="font-semibold">检索</label>
        <input id="library-search" type="search" aria-label="检索" value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => { if (event.key === "Escape") setOpen(false); }}
          placeholder="方名 / 药名 / 穴位 / 症状"
          className="mt-1 w-full rounded border border-line bg-paper px-2 py-1" />
      </form>
      {open && hits.length > 0 && (
        <div data-testid="suggest"
          className="absolute z-20 mt-1 w-full rounded border border-line bg-paper p-2 shadow">
          {GROUPS.map(([match, label]) => {
            const group = hits.filter((hit) => hit.match === match);
            if (!group.length) return null;
            return (
              <div key={match} data-testid="suggest-group">
                <p className="text-xs text-ink/70">{label}</p>
                <ul>
                  {group.map((hit) => {
                    const href = refHref(hit.ref_type, hit.ref_id);
                    return (
                      <li key={`${hit.ref_type}:${hit.ref_id}`}>
                        {onPick ? (
                          // 选择模式（M5 归并目标）：命中项是按钮不是链接——点击的意义是
                          // "把这条写进表单"，不是"跳详情页"。收起面板的逻辑与 M4 一致。
                          <button type="button" onClick={() => { onPick(hit); setOpen(false); }}
                            className="text-sm hover:text-cinnabar">
                            选择 {hit.title}
                          </button>
                        ) : href ? (
                          <Link href={href} onClick={() => setOpen(false)}
                            className="text-sm hover:text-cinnabar">{hit.title}</Link>
                        ) : <span className="text-sm">{hit.title}</span>}
                      </li>
                    );
                  })}
                </ul>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
