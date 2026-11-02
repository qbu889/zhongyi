import Link from "next/link";
import type { ReactNode } from "react";

import { ANSWER_DISCLAIMER } from "@/lib/constants";

import { AskLink, type DetailRefType } from "./AskLink";

const LIST_PATH: Record<DetailRefType, string> = {
  formula: "/formulas",
  herb: "/herbs",
  acupoint: "/acupoints",
  case: "/cases",
};

export function DetailFrame({
  refType, refId, title, summary, children,
}: {
  refType: DetailRefType;
  refId: number;
  title: string;
  summary?: string | null;
  children: ReactNode;
}) {
  return (
    <article data-testid={`${refType}-detail`} className="mx-auto max-w-4xl px-4 py-6">
      <nav aria-label="面包屑" className="text-xs">
        <Link href={LIST_PATH[refType]} className="text-cinnabar underline">返回列表</Link>
      </nav>
      <header className="mt-2 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="font-serif text-2xl font-semibold">{title}</h1>
          {summary && <p className="mt-1 text-sm text-ink/70">{summary}</p>}
        </div>
        <AskLink refType={refType} refId={refId} />
      </header>
      <div className="mt-4 space-y-5">{children}</div>
      <p data-testid="detail-disclaimer" className="mt-8 border-t border-line pt-3 text-xs text-ink/70">
        {ANSWER_DISCLAIMER}
      </p>
    </article>
  );
}
