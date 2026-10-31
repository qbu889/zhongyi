import type { Citation, Progress } from "@/lib/types";

const TYPE_LABELS: Record<string, string> = {
  formula: "方剂", herb: "中药", acupoint: "穴位",
  case: "医案", evidence: "原文", framework: "框架",
};

export function RetrievalProgress({
  progress,
  citations,
}: {
  progress: Progress;
  citations: Citation[];
}) {
  const parts = Object.entries(progress.by_type)
    .filter(([, count]) => count > 0)
    .map(([kind, count]) => `${TYPE_LABELS[kind] ?? kind} ${count}`);

  return (
    <details data-testid="progress" className="mt-2 text-xs text-ink/70">
      <summary className="cursor-pointer">
        命中 {progress.total} 条本地证据
        {parts.length > 0 && <span>（{parts.join(" / ")}）</span>}
      </summary>
      {citations.length > 0 && (
        <ul className="mt-1 space-y-0.5 pl-4">
          {citations.map((citation) => (
            <li key={`${citation.ref_type}:${citation.ref_id}`}>
              {citation.title}（{citation.anchor}）
            </li>
          ))}
        </ul>
      )}
    </details>
  );
}
