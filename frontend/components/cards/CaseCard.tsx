import Link from "next/link";

import type { CaseDetail } from "@/lib/types";

export function CaseCard({ caseItem }: { caseItem: CaseDetail }) {
  return (
    <article data-testid="case-card" className="mt-3 rounded border border-line p-3 text-sm">
      <h4 className="font-serif text-base font-semibold">{caseItem.no}</h4>
      <p className="mt-1 text-ink/70">{caseItem.category ?? "病类未载"}</p>
      <details open className="mt-2"><summary className="cursor-pointer">问</summary>
        <p className="mt-1">{caseItem.chief_complaint ?? "—"}</p></details>
      <details className="mt-1"><summary className="cursor-pointer">答</summary>
        <p className="mt-1">{caseItem.pathogenesis ?? "—"}</p></details>
      <details open className="mt-1"><summary className="cursor-pointer">治</summary>
        <p className="mt-1">{caseItem.treatment ?? "—"}</p>
        {caseItem.added_herbs.length > 0 && <p className="mt-1">加味：{caseItem.added_herbs.join("、")}</p>}</details>
      <details className="mt-1"><summary className="cursor-pointer">要诀</summary>
        <p className="mt-1">{caseItem.tips ?? "—"}</p></details>
      <div className="mt-2 flex gap-3 text-xs">
        <Link className="text-cinnabar underline" href={`/cases/${caseItem.id}`}>在库详情页打开</Link>
        {caseItem.category && (
          <Link className="text-cinnabar underline"
            href={`/cases?category=${encodeURIComponent(caseItem.category)}`}>同病类医案</Link>
        )}
      </div>
    </article>
  );
}
