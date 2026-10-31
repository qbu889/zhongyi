"use client";

import type { Citation } from "@/lib/types";

import { AcupointCard } from "./AcupointCard";
import { CaseCard } from "./CaseCard";
import { FormulaCard } from "./FormulaCard";
import { HerbCard } from "./HerbCard";
import { useCards } from "./useCards";

export function Cards({ citations }: { citations: Citation[] }) {
  const { cards, reload } = useCards(citations);
  const entries = Object.entries(cards);

  if (entries.length === 0) return null;

  return (
    <div data-testid="cards" className="mt-3 space-y-2">
      {entries.map(([key, card]) => {
        if ("error" in card) {
          return (
            <div key={key} className="rounded border border-line p-2 text-sm text-ink/60">
              卡片加载失败
              <button type="button" className="ml-2 text-cinnabar underline" onClick={reload}>重试</button>
            </div>
          );
        }
        if (card.kind === "formula") return <FormulaCard key={key} formula={card.data} />;
        if (card.kind === "herb") return <HerbCard key={key} herb={card.data} />;
        if (card.kind === "acupoint") return <AcupointCard key={key} point={card.data} />;
        return <CaseCard key={key} caseItem={card.data} />;
      })}
    </div>
  );
}
