import Link from "next/link";

import type { FilterGroup } from "@/components/library/FilterPanel";
import { LibraryShell } from "@/components/library/LibraryShell";
import { ResultRow } from "@/components/library/ResultRow";
import { serverGet } from "@/lib/api";
import { PAGE_SIZE } from "@/lib/constants";
import { buildQuery, paramsFrom } from "@/lib/filters";
import type { AcupointListResponse } from "@/lib/types";

const MERIDIANS = [
  "手太阴肺经", "手阳明大肠经", "足阳明胃经", "足太阴脾经", "手少阴心经",
  "手太阳小肠经", "足太阳膀胱经", "足少阴肾经", "手厥阴心包经",
  "手少阳三焦经", "足少阳胆经", "足厥阴肝经", "督脉", "任脉",
];
const ROLES = ["井", "荥", "输", "经", "合", "原", "络", "郄", "募", "背俞"];

const FILTERS = [
  { kind: "suggest", key: "q", label: "检索", kinds: ["acupoint"] },
  { kind: "single", key: "meridian", label: "经络",
    options: MERIDIANS.map((value) => ({ value, label: value })) },
  { kind: "single", key: "role", label: "角色",
    options: ROLES.map((value) => ({ value, label: value })) },
  { kind: "text", key: "symptom", label: "按症取穴", placeholder: "如：项强" },
] satisfies FilterGroup[];

export default async function AcupointsPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const raw = await searchParams;
  const params = paramsFrom(raw);
  const page = Number(params.get("page") ?? "1") || 1;
  const query = buildQuery({
    q: params.get("q"),
    meridian: params.get("meridian"),
    role: params.get("role"),
    symptom: params.get("symptom"),
    limit: PAGE_SIZE,
    offset: (page - 1) * PAGE_SIZE,
  });

  let data: AcupointListResponse;
  try {
    data = await serverGet<AcupointListResponse>(`/api/acupoints${query}`);
  } catch {
    return (
      <p className="mx-auto max-w-7xl px-4 py-6 text-sm text-cinnabar">
        列表加载失败，
        <Link href={`/acupoints${params.toString() ? `?${params}` : ""}`} className="underline">
          重试
        </Link>
      </p>
    );
  }

  return (
    <LibraryShell title="针灸" total={data.total} basePath="/acupoints"
      params={params} groups={FILTERS}>
      {data.items.map((item) => (
        <ResultRow key={item.id} href={`/acupoints/${item.id}`} title={item.name}
          badges={item.role
            ? <span className="rounded bg-cinnabar/10 px-1 text-xs text-cinnabar">{item.role}</span>
            : null}
          meta={`${item.meridian ?? "经络未载"} · ${item.symptom_count} 条主治症状${
            item.actions ? ` · ${item.actions}` : ""}`} />
      ))}
    </LibraryShell>
  );
}
