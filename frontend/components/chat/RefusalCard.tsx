"use client";

import type { Answer } from "@/lib/types";

export function RefusalCard({
  answer,
  question,
  onAsk,
}: {
  answer: Answer;
  question: string;
  onAsk: (text: string) => void;
}) {
  return (
    <section data-testid="refusal-card"
      className="mt-3 rounded border border-cinnabar/40 bg-cinnabar/5 p-3">
      <h3 className="font-serif text-lg">本地库未收录「{question}」</h3>
      <p className="mt-1 text-sm text-ink/70">{answer.headline}</p>
      {answer.top_score !== null && (
        <p className="mt-1 text-xs text-ink/70">最高相关度 {answer.top_score.toFixed(3)}</p>
      )}
      {answer.candidates.length > 0 && (
        <div className="mt-3">
          <p className="text-xs text-ink/70">也许是这些？（点击直接提问）</p>
          <div className="mt-1 flex flex-wrap gap-2">
            {answer.candidates.map((candidate) => (
              <button key={`${candidate.ref_type}:${candidate.ref_id}`} type="button"
                onClick={() => onAsk(candidate.title)}
                className="rounded-full border border-line px-3 py-1 text-sm hover:border-cinnabar">
                {candidate.title}
              </button>
            ))}
          </div>
        </div>
      )}
      <button type="button" disabled title="原文检索 FR-14 将在 M5 开放"
        className="mt-3 cursor-not-allowed rounded border border-line px-3 py-1 text-sm text-ink/70">
        在原文 text/ 搜一下
      </button>
      <p className="mt-3 text-xs text-ink/70">{answer.disclaimer}</p>
    </section>
  );
}
