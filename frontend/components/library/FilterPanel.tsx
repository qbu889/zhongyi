"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { buildQuery, type FilterValue } from "@/lib/filters";

import { SearchSuggest } from "./SearchSuggest";

export type FilterGroup =
  | { kind: "suggest"; key: string; label: string; kinds: string[] }
  | { kind: "multi"; key: string; label: string; options: string[] }
  | { kind: "single"; key: string; label: string; options: { value: string; label: string }[] }
  | { kind: "text"; key: string; label: string; placeholder?: string };

function TextFilter({ label, placeholder, value, onCommit }: {
  label: string;
  placeholder?: string;
  value: string;
  onCommit: (value: string) => void;
}) {
  const [text, setText] = useState(value);

  useEffect(() => {
    if (text === value) return;
    const timer = setTimeout(() => onCommit(text), 250);
    return () => clearTimeout(timer);
  }, [text, value, onCommit]);

  return (
    <label className="block">
      <span className="font-semibold">{label}</span>
      <input type="search" aria-label={label} value={text} placeholder={placeholder}
        onChange={(event) => setText(event.target.value)}
        className="mt-1 w-full rounded border border-line bg-paper px-2 py-1" />
    </label>
  );
}

export function FilterPanel({
  basePath,
  groups,
  initial,
}: {
  basePath: string;
  groups: FilterGroup[];
  initial: Record<string, string[]>;
}) {
  const router = useRouter();
  const [copied, setCopied] = useState(false);
  // R15：复制提示的 1500ms 复位定时器挂在 ref 上并在卸载时清理，
  // 否则定时器活过 unmount，会打到下一个测试/下一次挂载上。
  const copyTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => {
    if (copyTimer.current) clearTimeout(copyTimer.current);
  }, []);

  const push = (patch: Record<string, FilterValue>) => {
    router.push(`${basePath}${buildQuery({ ...initial, ...patch, page: null })}`);
  };

  async function copyLink() {
    await navigator.clipboard.writeText(window.location.href);
    setCopied(true);
    if (copyTimer.current) clearTimeout(copyTimer.current);
    copyTimer.current = setTimeout(() => setCopied(false), 1500);
  }

  return (
    <aside aria-label="筛选" className="space-y-4 text-sm">
      {groups.map((group) => {
        if (group.kind === "suggest") {
          return (
            <SearchSuggest key={group.key} kinds={group.kinds}
              initialQuery={initial[group.key]?.[0] ?? ""}
              onCommit={(query) => push({ [group.key]: query || null })} />
          );
        }
        if (group.kind === "text") {
          return (
            <TextFilter key={group.key} label={group.label} placeholder={group.placeholder}
              value={initial[group.key]?.[0] ?? ""}
              onCommit={(value) => push({ [group.key]: value || null })} />
          );
        }
        if (group.kind === "multi") {
          const values = initial[group.key] ?? [];
          return (
            <fieldset key={group.key}>
              <legend className="font-semibold">{group.label}</legend>
              <div className="mt-1 space-y-1">
                {group.options.map((option) => {
                  const checked = values.includes(option);
                  return (
                    <label key={option} className="flex items-center gap-2">
                      <input type="checkbox" checked={checked}
                        onChange={() => push({
                          [group.key]: checked
                            ? values.filter((value) => value !== option)
                            : [...values, option],
                        })} />
                      {option}
                    </label>
                  );
                })}
              </div>
            </fieldset>
          );
        }
        return (
          <label key={group.key} className="block">
            <span className="font-semibold">{group.label}</span>
            <select aria-label={group.label} value={initial[group.key]?.[0] ?? ""}
              onChange={(event) => push({ [group.key]: event.target.value || null })}
              className="mt-1 w-full rounded border border-line bg-paper px-2 py-1">
              <option value="">全部</option>
              {group.options.map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </select>
          </label>
        );
      })}
      <button type="button" onClick={copyLink}
        className="rounded border border-line px-2 py-1 text-xs">
        {copied ? "已复制筛选链接" : "复制当前筛选链接"}
      </button>
    </aside>
  );
}
