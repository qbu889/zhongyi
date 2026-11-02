"use client";

import * as Tooltip from "@radix-ui/react-tooltip";

import type { Citation } from "@/lib/types";

export function CitationSup({
  n,
  citation,
  onOpen,
}: {
  n: number;
  citation: Citation;
  onOpen: (citation: Citation) => void;
}) {
  return (
    <Tooltip.Provider delayDuration={350}>
      <Tooltip.Root>
        <Tooltip.Trigger asChild>
          <button
            type="button"
            data-testid="citation-sup"
            aria-label={`查看出处 ${citation.title}`}
            onClick={() => onOpen(citation)}
            className="ml-0.5 align-super text-xs text-cinnabar underline"
          >
            [{n}]
          </button>
        </Tooltip.Trigger>
        <Tooltip.Portal>
          <Tooltip.Content sideOffset={4}
            className="z-50 max-w-xs rounded border border-line bg-paper p-2 text-xs shadow">
            <p className="font-medium">{citation.title}</p>
            <p className="mt-0.5 text-ink/70">{citation.anchor}</p>
            {citation.snippet && <p className="mt-1">{citation.snippet.slice(0, 60)}</p>}
            <Tooltip.Arrow className="fill-paper" />
          </Tooltip.Content>
        </Tooltip.Portal>
      </Tooltip.Root>
    </Tooltip.Provider>
  );
}
