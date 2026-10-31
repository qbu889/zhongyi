import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SessionSidebar } from "@/components/chat/SessionSidebar";
import { historyToTurns } from "@/lib/history";
import { prefillFromEvidence } from "@/lib/format";
import type { Answer, ChatHistoryMessage, EvidenceRef } from "@/lib/types";

import { server } from "../msw/server";

const { push, refresh } = vi.hoisted(() => ({ push: vi.fn(), refresh: vi.fn() }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, refresh }),
}));

// 每个用例都从干净的 router 桩开始：新增用例要断言 push/refresh「没有」被调用，
// 不能撞上上一个用例留下的记录。既有断言一字未改。
beforeEach(() => {
  push.mockClear();
  refresh.mockClear();
});

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

  it("keeps the row in confirm mode with an inline error when the delete fails", async () => {
    let sessionsCalls = 0;
    server.use(
      http.get("/api/chat/sessions", () => {
        sessionsCalls += 1;
        return HttpResponse.json({
          total: 1, limit: 50, offset: 0,
          items: [{ id: 2, title: "桂枝汤", last_activity_at: "2026-10-31T10:00:00", message_count: 4 }],
        });
      }),
      http.delete("/api/chat/2", () => new HttpResponse(null, { status: 500 })),
    );

    // 只观察 console.error，不断言它：真正的守卫是「rejection 被 catch 住，
    // 用例得以带着错误文案正常跑完」——未处理的 rejection 会让 Vitest 直接判失败。
    const errorLog = vi.spyOn(console, "error");

    render(<SessionSidebar currentId={2} />);
    const row = (await screen.findByRole("link", { name: "桂枝汤" })).closest("li")!;
    await userEvent.click(within(row).getByRole("button", { name: "删除会话 桂枝汤" }));
    await userEvent.click(within(row).getByRole("button", { name: "确认" }));

    expect(await within(row).findByText("删除失败")).toBeInTheDocument();
    // 行留在确认态，用户可重试或取消。
    expect(within(row).getByText("确认删除？")).toBeInTheDocument();
    expect(within(row).getByRole("button", { name: "确认" })).toBeEnabled();
    expect(within(row).getByRole("button", { name: "取消" })).toBeEnabled();
    // 失败绝不跳转、绝不刷新路由、绝不重载列表。
    expect(push).not.toHaveBeenCalled();
    expect(refresh).not.toHaveBeenCalled();
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(sessionsCalls).toBe(1);

    errorLog.mockRestore();
  });

  it("reloads the list without navigating when a non-current session is deleted", async () => {
    let sessionsCalls = 0;
    let deleteCalls = 0;
    server.use(
      http.get("/api/chat/sessions", () => {
        sessionsCalls += 1;
        return HttpResponse.json({
          total: 2, limit: 50, offset: 0,
          items: [
            { id: 2, title: "桂枝汤", last_activity_at: "2026-10-31T10:00:00", message_count: 4 },
            { id: 1, title: "风池", last_activity_at: "2026-10-30T10:00:00", message_count: 2 },
          ],
        });
      }),
      http.delete("/api/chat/1", () => {
        deleteCalls += 1;
        return new HttpResponse(null, { status: 204 });
      }),
    );

    render(<SessionSidebar currentId={2} />);
    const row = (await screen.findByRole("link", { name: "风池" })).closest("li")!;
    await userEvent.click(within(row).getByRole("button", { name: "删除会话 风池" }));
    await userEvent.click(within(row).getByRole("button", { name: "确认" }));

    await waitFor(() => expect(deleteCalls).toBe(1));
    // 删的不是当前会话：重载列表，但停在原页面。
    await waitFor(() => expect(sessionsCalls).toBe(2));
    expect(push).not.toHaveBeenCalled();
    expect(refresh).not.toHaveBeenCalled();
  });

  it("calls onNewSession when the 新会话 link is clicked, keeping its /chat href", async () => {
    const onNewSession = vi.fn();
    render(<SessionSidebar currentId={2} onNewSession={onNewSession} />);

    const link = await screen.findByRole("link", { name: "新会话" });
    expect(link).toHaveAttribute("href", "/chat");
    await userEvent.click(link);
    expect(onNewSession).toHaveBeenCalledTimes(1);
  });

  it("issues a single DELETE when 确认 is clicked twice while the request is in flight", async () => {
    let deleteCalls = 0;
    let release: () => void = () => {};
    const hanging = new Promise<void>((resolve) => { release = resolve; });
    server.use(
      http.get("/api/chat/sessions", () => HttpResponse.json({
        total: 1, limit: 50, offset: 0,
        items: [{ id: 2, title: "桂枝汤", last_activity_at: "2026-10-31T10:00:00", message_count: 4 }],
      })),
      http.delete("/api/chat/2", async () => {
        deleteCalls += 1;
        await hanging;
        return new HttpResponse(null, { status: 204 });
      }),
    );

    render(<SessionSidebar currentId={2} />);
    const row = (await screen.findByRole("link", { name: "桂枝汤" })).closest("li")!;
    await userEvent.click(within(row).getByRole("button", { name: "删除会话 桂枝汤" }));
    await userEvent.click(within(row).getByRole("button", { name: "确认" }));
    await waitFor(() => expect(deleteCalls).toBe(1));

    // 请求在飞：两个确认区按钮都禁用，第二次点击打不出去。
    expect(within(row).getByRole("button", { name: "确认" })).toBeDisabled();
    expect(within(row).getByRole("button", { name: "取消" })).toBeDisabled();
    await userEvent.click(within(row).getByRole("button", { name: "确认" }));
    expect(deleteCalls).toBe(1);

    release();
    await waitFor(() => expect(push).toHaveBeenCalledWith("/chat"));
    expect(refresh).toHaveBeenCalled();
  });
});
