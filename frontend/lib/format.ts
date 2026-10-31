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
