import Link from "next/link";

import type { CaseDetail } from "@/lib/types";

import { DetailFrame } from "./DetailFrame";

export function CaseDetailView({ caseItem }: { caseItem: CaseDetail }) {
  return (
    <DetailFrame refType="case" refId={caseItem.id} title={caseItem.no}
      summary={caseItem.category ?? "病类未载"}>
      <section aria-labelledby="question-heading">
        <h2 id="question-heading" className="font-serif text-lg font-semibold">问</h2>
        <p className="mt-1 text-sm">{caseItem.chief_complaint ?? "—"}</p>
      </section>

      <section aria-labelledby="answer-heading">
        <h2 id="answer-heading" className="font-serif text-lg font-semibold">答</h2>
        <p className="mt-1 text-sm">{caseItem.pathogenesis ?? "—"}</p>
      </section>

      <section aria-labelledby="treatment-heading">
        <h2 id="treatment-heading" className="font-serif text-lg font-semibold">治</h2>
        <p className="mt-1 text-sm">{caseItem.treatment ?? "—"}</p>
        {caseItem.treatment_formulas.length > 0 && (
          <p className="mt-1 text-sm">
            主方：
            {caseItem.treatment_formulas.map((formula, index) => (
              <span key={formula.id}>
                {index > 0 && "、"}
                <Link className="text-cinnabar underline" href={`/formulas/${formula.id}`}>
                  {formula.canonical_name}
                </Link>
              </span>
            ))}
          </p>
        )}
        {caseItem.added_herbs.length > 0 && (
          <p className="mt-1 text-sm">加味：{caseItem.added_herbs.join("、")}</p>
        )}
        {caseItem.category && (
          <p className="mt-1 text-sm">
            关联：
            <Link className="text-cinnabar underline"
              href={`/cases?category=${encodeURIComponent(caseItem.category)}`}>
              同病类医案
            </Link>
          </p>
        )}
      </section>

      <section aria-labelledby="tips-heading">
        <h2 id="tips-heading" className="font-serif text-lg font-semibold">要诀</h2>
        <p className="mt-1 text-sm">{caseItem.tips ?? "—"}</p>
      </section>

      {caseItem.raw_md && (
        <section aria-labelledby="raw-heading">
          <h2 id="raw-heading" className="font-serif text-lg font-semibold">医案原文</h2>
          <pre className="mt-1 whitespace-pre-wrap font-serif text-sm">{caseItem.raw_md}</pre>
        </section>
      )}
    </DetailFrame>
  );
}
