import type { Citation } from "./types";

export function refHref(refType: string, refId: number): string | null {
  switch (refType) {
    case "formula": return `/formulas/${refId}`;
    case "herb": return `/herbs/${refId}`;
    case "acupoint": return `/acupoints/${refId}`;
    case "case": return `/cases/${refId}`;
    default: return null;
  }
}

export function detailHref(citation: Citation): string | null {
  return refHref(citation.ref_type, citation.ref_id);
}
