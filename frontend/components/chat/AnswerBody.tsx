"use client";

import { Cards } from "@/components/cards/Cards";
import { citationKey, numberCitations, numbersForLine, unmatchedCitations } from "@/lib/citations";
import type { Answer, Citation } from "@/lib/types";

import { AnswerActions } from "./AnswerActions";
import { CitationSup } from "./CitationSup";
import { GeneralNote } from "./GeneralNote";

export function AnswerBody({
  answer,
  onOpenCitation,
}: {
  answer: Answer;
  onOpenCitation: (citation: Citation) => void;
}) {
  const numbers = numberCitations(answer.citations);
  const unmatched = unmatchedCitations(answer.sections, answer.citations);
  // 编号 → 引用只建一次；重复 ref 保留首个，与原先 find 的结果一致。
  const citationsByNumber = new Map<number, Citation>();
  for (const citation of answer.citations) {
    const number = numbers.get(citationKey(citation));
    if (number !== undefined && !citationsByNumber.has(number)) {
      citationsByNumber.set(number, citation);
    }
  }

  return (
    <div data-testid="answer-body">
      <h3 className="font-serif text-lg font-semibold">{answer.headline}</h3>
      {answer.sections.map((section) => (
        <section key={section.title} className="mt-3">
          <h4 className="text-sm font-semibold text-cinnabar">{section.title}</h4>
          <ul className="mt-1 space-y-1">
            {section.lines.map((line, index) => (
              <li key={`${section.title}-${index}`}>
                {line}
                {numbersForLine(line, answer.citations, numbers).map((n) => {
                  const citation = citationsByNumber.get(n)!;
                  return (
                    <CitationSup key={`${n}-${citationKey(citation)}`} n={n}
                      citation={citation} onOpen={onOpenCitation} />
                  );
                })}
              </li>
            ))}
          </ul>
        </section>
      ))}
      {unmatched.length > 0 && (
        <p className="mt-2 text-xs text-ink/70">
          出处：
          {unmatched.map((citation) => (
            <CitationSup key={citationKey(citation)}
              n={numbers.get(citationKey(citation))!}
              citation={citation} onOpen={onOpenCitation} />
          ))}
        </p>
      )}
      {answer.general_note && <GeneralNote text={answer.general_note} />}
      {answer.status === "answered" && <Cards citations={answer.citations} />}
      <AnswerActions answer={answer} />
      <p className="mt-3 text-xs text-ink/70">{answer.disclaimer}</p>
    </div>
  );
}
