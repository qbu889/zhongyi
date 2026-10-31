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
}: {
  kinds: string[];
  initialQuery?: string;
  onCommit: (query: string) => void;
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
                <p className="text-xs text-ink/60">{label}</p>
                <ul>
                  {group.map((hit) => {
                    const href = refHref(hit.ref_type, hit.ref_id);
                    return (
                      <li key={`${hit.ref_type}:${hit.ref_id}`}>
                        {href ? (
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
