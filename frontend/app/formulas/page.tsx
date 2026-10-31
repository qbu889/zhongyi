import Link from "next/link";

import { LibraryShell } from "@/components/library/LibraryShell";
import { ResultRow } from "@/components/library/ResultRow";
import type { FilterGroup } from "@/components/library/FilterPanel";
import { serverGet } from "@/lib/api";
import { PAGE_SIZE } from "@/lib/constants";
import { buildQuery, pageFrom, paramsFrom, readList } from "@/lib/filters";
import type { FormulaListResponse } from "@/lib/types";

const FILTERS = [
  { kind: "suggest", key: "q", label: "检索", kinds: ["formula"] },
  { kind: "multi", key: "six_jing", label: "六经",
    options: ["太阳病", "阳明病", "少阳病", "太阴病", "少阴病", "厥阴病"] },
  { kind: "single", key: "source_doc", label: "出处文档",
    options: [
      { value: "02-伤寒论/伤寒六经方库.md", label: "伤寒六经方库" },
      { value: "03-金匮/金匮方剂库.md", label: "金匮方剂库" },
    ] },
  { kind: "single", key: "status", label: "身份状态",
    options: [
      { value: "confirmed", label: "已确认" },
      { value: "candidate", label: "待确认" },
    ] },
  { kind: "single", key: "kind", label: "方剂类型",
    options: [
      { value: "single", label: "单方" },
      { value: "pair", label: "合方" },
    ] },
] satisfies FilterGroup[];

export default async function FormulasPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const raw = await searchParams;
  const params = paramsFrom(raw);
  const page = pageFrom(params);
  const query = buildQuery({
    q: params.get("q"),
    six_jing: readList(params, "six_jing"),
    source_doc: params.get("source_doc"),
    status: params.get("status"),
    kind: params.get("kind"),
    herb: params.get("herb"),
    limit: PAGE_SIZE,
    offset: (page - 1) * PAGE_SIZE,
  });

  let data: FormulaListResponse;
  try {
    data = await serverGet<FormulaListResponse>(`/api/formulas${query}`);
  } catch {
    return (
      <p className="mx-auto max-w-7xl px-4 py-6 text-sm text-cinnabar">
        列表加载失败，
        <Link href={`/formulas${params.toString() ? `?${params}` : ""}`} className="underline">
          重试
        </Link>
      </p>
    );
  }

  return (
    <LibraryShell title="方剂库" total={data.total} basePath="/formulas"
      params={params} groups={FILTERS}>
      {data.items.map((item) => (
        <ResultRow key={item.id} href={`/formulas/${item.id}`}
          title={item.canonical_name}
          badges={item.status === "candidate"
            ? <span className="rounded bg-line px-1 text-xs text-ink/60">身份待确认</span>
            : null}
          meta={`${item.variant_count} 个剂量变体 · ${item.evidence_count} 条出处 · ${
            item.dose_complete === false ? "剂量不完全"
              : item.dose_complete === true ? "剂量完整" : "剂量状态未知"}`} />
      ))}
    </LibraryShell>
  );
}
