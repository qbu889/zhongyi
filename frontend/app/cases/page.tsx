import Link from "next/link";

import type { FilterGroup } from "@/components/library/FilterPanel";
import { LibraryShell } from "@/components/library/LibraryShell";
import { ResultRow } from "@/components/library/ResultRow";
import { serverGet } from "@/lib/api";
import { PAGE_SIZE } from "@/lib/constants";
import { buildQuery, pageFrom, paramsFrom } from "@/lib/filters";
import type { CaseListResponse } from "@/lib/types";

const FILTERS = [
  { kind: "suggest", key: "q", label: "检索", kinds: ["case"] },
  { kind: "single", key: "category", label: "病类",
    options: [
      "经典方症类", "辨证思路示范类", "重症/癌症类",
      "针灸即时取效类", "妇科/疑难类",
    ].map((value) => ({ value, label: value })) },
] satisfies FilterGroup[];

export default async function CasesPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const raw = await searchParams;
  const params = paramsFrom(raw);
  const page = pageFrom(params);
  const query = buildQuery({
    q: params.get("q"),
    category: params.get("category"),
    limit: PAGE_SIZE,
    offset: (page - 1) * PAGE_SIZE,
  });

  let data: CaseListResponse;
  try {
    data = await serverGet<CaseListResponse>(`/api/cases${query}`);
  } catch {
    return (
      <p className="mx-auto max-w-7xl px-4 py-6 text-sm text-cinnabar">
        列表加载失败，
        <Link href={`/cases${params.toString() ? `?${params}` : ""}`} className="underline">
          重试
        </Link>
      </p>
    );
  }

  return (
    <LibraryShell title="医案" total={data.total} basePath="/cases"
      params={params} groups={FILTERS}>
      {data.items.map((item) => (
        <ResultRow key={item.id} href={`/cases/${item.id}`} title={item.no}
          badges={item.category
            ? <span className="rounded bg-line px-1 text-xs text-ink/70">{item.category}</span>
            : null}
          meta={(
            <>
              <span>{item.chief_complaint ?? "主诉未载"}</span>
              {item.treatment_formulas.length > 0 && (
                <span className="ml-2">
                  治方：
                  {item.treatment_formulas.map((formula) => (
                    <Link key={formula.id} href={`/formulas/${formula.id}`}
                      className="ml-1 text-cinnabar underline">{formula.canonical_name}</Link>
                  ))}
                </span>
              )}
            </>
          )} />
      ))}
    </LibraryShell>
  );
}
