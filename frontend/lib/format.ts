import type { EvidenceRef } from "./types";

export function cn(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}

export function prefillFromFormula(
  name: string,
  evidence: { source_doc: string; six_jing: string | null; clause_no: string | null }[],
): string {
  const first = evidence[0];
  const where = first
    ? [first.source_doc, first.six_jing, first.clause_no].filter(Boolean).join("·")
    : "";
  return `关于 ${name}${where ? `（${where}）` : ""}：`;
}

export function prefillFromEvidence(ref: EvidenceRef): string {
  const formula = ref.fields.formula as { canonical_name?: string } | undefined;
  const name = formula?.canonical_name
    ?? (typeof ref.fields.name === "string" ? ref.fields.name : undefined)
    ?? (typeof ref.fields.no === "string" ? ref.fields.no : undefined)
    ?? "";
  const evidence = Array.isArray(ref.fields.evidence)
    ? (ref.fields.evidence as {
        source_doc: string; six_jing: string | null; clause_no: string | null;
      }[])
    : [];
  if (evidence[0]) return prefillFromFormula(name, evidence);
  return `关于 ${name}（${ref.anchor}）：`;
}
