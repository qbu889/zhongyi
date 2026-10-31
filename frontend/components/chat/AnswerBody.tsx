"use client";

import { citationKey, numberCitations, numbersForLine, unmatchedCitations } from "@/lib/citations";
import type { Answer, Citation } from "@/lib/types";

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
                  const citation = answer.citations.find(
                    (item) => numbers.get(citationKey(item)) === n)!;
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
        <p className="mt-2 text-xs text-ink/60">
          出处：
          {unmatched.map((citation) => (
            <CitationSup key={citationKey(citation)}
              n={numbers.get(citationKey(citation))!}
              citation={citation} onOpen={onOpenCitation} />
          ))}
        </p>
      )}
      {answer.general_note && <GeneralNote text={answer.general_note} />}
      <p className="mt-3 text-xs text-ink/60">{answer.disclaimer}</p>
    </div>
  );
}
