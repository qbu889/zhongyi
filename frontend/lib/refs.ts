import type { Citation } from "./types";

export function detailHref(citation: Citation): string | null {
  switch (citation.ref_type) {
    case "formula": return `/formulas/${citation.ref_id}`;
    case "herb": return `/herbs/${citation.ref_id}`;
    case "acupoint": return `/acupoints/${citation.ref_id}`;
    case "case": return `/cases/${citation.ref_id}`;
    default: return null;
  }
}
