import type { Answer } from "./types";
import { citationKey } from "./citations";

export function answerToMarkdown(answer: Answer): string {
  const body = answer.sections
    .map((section) => `### ${section.title}\n${section.lines.join("\n")}`)
    .join("\n\n");
  const seen = new Set<string>();
  const refs = answer.citations
    .filter((citation) => {
      const key = citationKey(citation);
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    })
    .map((citation, index) => `[${index + 1}] ${citation.title}（${citation.anchor}）`)
    .join("\n");
  return `# ${answer.headline}\n\n${body}\n\n## 出处\n${refs}\n\n---\n${answer.disclaimer}\n`;
}
