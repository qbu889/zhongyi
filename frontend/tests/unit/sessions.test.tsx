import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import { SessionSidebar } from "@/components/chat/SessionSidebar";
import { historyToTurns } from "@/lib/history";
import { prefillFromEvidence } from "@/lib/format";
import type { Answer, ChatHistoryMessage, EvidenceRef } from "@/lib/types";

import { server } from "../msw/server";

const { push, refresh } = vi.hoisted(() => ({ push: vi.fn(), refresh: vi.fn() }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, refresh }),
}));

const answer: Answer = {
  intent: "B", status: "answered", headline: "桂枝汤", sections: [], citations: [],
  dose_complete: null, candidates: [], followup: [], general_note: null,
  disclaimer: "免责", prose: "", top_score: 1,
};

const messages: ChatHistoryMessage[] = [
  { role: "user", content: { text: "桂枝汤" }, created_at: "2026-10-31T10:00:00" },
  { role: "assistant", content: answer as unknown as Record<string, unknown>,
    created_at: "2026-10-31T10:00:01" },
  { role: "user", content: { text: "风池" }, created_at: "2026-10-31T10:00:02" },
];

const evidence: EvidenceRef = {
  ref_type: "formula",
  ref_id: 61,
  anchor: "方剂库-经方组成.md#桂枝汤",
  text: "",
  fields: {
    formula: { canonical_name: "桂枝汤" },
    evidence: [{ source_doc: "02-伤寒论/伤寒六经方库.md", six_jing: "太阳病", clause_no: "12" }],
  },
};

describe("history and prefill", () => {
  it("replays stored answers without re-asking", () => {
    const turns = historyToTurns(messages);
    expect(turns).toHaveLength(2);
    expect(turns[0].phase).toBe("done");
    expect(turns[0].question).toBe("桂枝汤");
    expect(turns[0].answer?.headline).toBe("桂枝汤");
    expect(turns[1].phase).toBe("interrupted");
  });

  it("builds a prefilled question from an evidence ref", () => {
    expect(prefillFromEvidence(evidence))
      .toBe("关于 桂枝汤（02-伤寒论/伤寒六经方库.md·太阳病·12）：");
    expect(prefillFromEvidence({ ...evidence, fields: { no: "问11" } }))
      .toBe("关于 问11（方剂库-经方组成.md#桂枝汤）：");
  });
});

describe("SessionSidebar", () => {
  it("lists sessions, marks the current one, and deletes after confirmation", async () => {
    server.use(
      http.get("/api/chat/sessions", () => HttpResponse.json({
        total: 2, limit: 50, offset: 0,
        items: [
          { id: 2, title: "桂枝汤", last_activity_at: "2026-10-31T10:00:00", message_count: 4 },
          { id: 1, title: "风池", last_activity_at: "2026-10-30T10:00:00", message_count: 2 },
        ],
      })),
      http.delete("/api/chat/2", () => new HttpResponse(null, { status: 204 })),
    );

    render(<SessionSidebar currentId={2} />);
    const current = await screen.findByRole("link", { name: "桂枝汤" });
    expect(current).toHaveAttribute("href", "/chat/2");
    expect(current).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "新会话" })).toHaveAttribute("href", "/chat");

    const row = screen.getByRole("link", { name: "桂枝汤" }).closest("li")!;
    await userEvent.click(within(row).getByRole("button", { name: "删除会话 桂枝汤" }));
    await userEvent.click(within(row).getByRole("button", { name: "确认" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/chat"));
    expect(refresh).toHaveBeenCalled();
  });
});
