import type { Citation, Section } from "./types";

export function citationKey(citation: Citation): string {
  return `${citation.ref_type}:${citation.ref_id}`;
}

export function numberCitations(citations: Citation[]): Map<string, number> {
  const numbers = new Map<string, number>();
  for (const citation of citations) {
    const key = citationKey(citation);
    if (!numbers.has(key)) numbers.set(key, numbers.size + 1);
  }
  return numbers;
}

export function numbersForLine(
  line: string,
  citations: Citation[],
  numbers: Map<string, number>,
): number[] {
  const found = new Set<number>();
  for (const citation of citations) {
    if (citation.title && line.includes(citation.title)) {
      const number = numbers.get(citationKey(citation));
      if (number) found.add(number);
    }
  }
  return [...found].sort((a, b) => a - b);
}

export function unmatchedCitations(sections: Section[], citations: Citation[]): Citation[] {
  const seen = new Set<string>();
  const unmatched: Citation[] = [];
  for (const citation of citations) {
    const key = citationKey(citation);
    if (seen.has(key)) continue;
    seen.add(key);
    const hit = sections.some((section) =>
      section.lines.some((line) => citation.title && line.includes(citation.title)));
    if (!hit) unmatched.push(citation);
  }
  return unmatched;
}
