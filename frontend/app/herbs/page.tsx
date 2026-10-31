import Link from "next/link";

import type { FilterGroup } from "@/components/library/FilterPanel";
import { LibraryShell } from "@/components/library/LibraryShell";
import { ResultRow } from "@/components/library/ResultRow";
import { serverGet } from "@/lib/api";
import { PAGE_SIZE } from "@/lib/constants";
import { buildQuery, paramsFrom, readList } from "@/lib/filters";
import type { HerbListResponse } from "@/lib/types";

const FILTERS = [
  { kind: "suggest", key: "q", label: "检索", kinds: ["herb"] },
  { kind: "multi", key: "taste_group", label: "五味",
    options: ["酸", "苦", "甘", "辛", "咸", "未归"] },
  { kind: "single", key: "organ_group", label: "五脏归经",
    options: ["肝", "心", "脾", "肺", "肾", "未归"].map((value) => ({ value, label: value })) },
  { kind: "single", key: "flavor_state", label: "性味状态",
    options: [
      { value: "present", label: "本经有载" },
      { value: "missing", label: "本经未载" },
    ] },
] satisfies FilterGroup[];

export default async function HerbsPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const raw = await searchParams;
  const params = paramsFrom(raw);
  const page = Number(params.get("page") ?? "1") || 1;
  const query = buildQuery({
    q: params.get("q"),
    taste_group: readList(params, "taste_group"),
    organ_group: params.get("organ_group"),
    flavor_state: params.get("flavor_state"),
    limit: PAGE_SIZE,
    offset: (page - 1) * PAGE_SIZE,
  });

  let data: HerbListResponse;
  try {
    data = await serverGet<HerbListResponse>(`/api/herbs${query}`);
  } catch {
    return (
      <p className="mx-auto max-w-7xl px-4 py-6 text-sm text-cinnabar">
        列表加载失败，
        <Link href={`/herbs${params.toString() ? `?${params}` : ""}`} className="underline">
          重试
        </Link>
      </p>
    );
  }

  return (
    <LibraryShell title="中药库" total={data.total} basePath="/herbs"
      params={params} groups={FILTERS}>
      {data.items.map((item) => (
        <ResultRow key={item.id} href={`/herbs/${item.id}`} title={item.name}
          badges={(
            <>
              {item.taste_group && (
                <Link href={`/herbs?taste_group=${encodeURIComponent(item.taste_group)}`}
                  className="rounded bg-cinnabar/10 px-1 text-xs text-cinnabar">
                  {item.taste_group}味
                </Link>
              )}
              {item.organ_group && (
                <Link href={`/herbs?organ_group=${encodeURIComponent(item.organ_group)}`}
                  className="rounded bg-line px-1 text-xs text-ink/70">
                  归{item.organ_group}
                </Link>
              )}
            </>
          )}
          meta={`性味：${item.flavor_state === "missing" ? "本经未载" : item.flavor} · 含方 ${item.formula_count}`} />
      ))}
    </LibraryShell>
  );
}
