"use client";

import { useEffect, useState } from "react";

import { apiGet } from "@/lib/api";
import { citationKey } from "@/lib/citations";
import type {
  AcupointDetail, CaseDetail, Citation, FormulaDetail, HerbDetail,
} from "@/lib/types";

type CardState =
  | { kind: "formula"; data: FormulaDetail }
  | { kind: "herb"; data: HerbDetail }
  | { kind: "acupoint"; data: AcupointDetail }
  | { kind: "case"; data: CaseDetail }
  | { kind: string; error: true };

function load(citation: Citation): Promise<CardState> {
  switch (citation.ref_type) {
    case "formula":
      return apiGet<FormulaDetail>(`/api/formulas/${citation.ref_id}`)
        .then((data) => ({ kind: "formula", data }));
    case "herb":
      return apiGet<HerbDetail>(`/api/herbs/${citation.ref_id}`)
        .then((data) => ({ kind: "herb", data }));
    case "acupoint":
      return apiGet<AcupointDetail>(`/api/acupoints/${citation.ref_id}`)
        .then((data) => ({ kind: "acupoint", data }));
    case "case":
      return apiGet<CaseDetail>(`/api/cases/${citation.ref_id}`)
        .then((data) => ({ kind: "case", data }));
    default:
      return Promise.resolve({ kind: citation.ref_type, error: true });
  }
}

export function useCards(citations: Citation[]) {
  const [cards, setCards] = useState<Record<string, CardState>>({});
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    let cancelled = false;
    const seen = new Set<string>();
    const targets = citations.filter((citation) => {
      if (citation.ref_type === "evidence" || citation.ref_type === "framework") return false;
      const key = citationKey(citation);
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
    Promise.all(targets.map(async (citation) => {
      const key = citationKey(citation);
      try {
        return [key, await load(citation)] as const;
      } catch {
        return [key, { kind: citation.ref_type, error: true }] as const;
      }
    })).then((entries) => {
      if (!cancelled) setCards(Object.fromEntries(entries));
    });
    return () => { cancelled = true; };
  }, [citations, nonce]);

  return { cards, reload: () => setNonce((value) => value + 1) };
}
