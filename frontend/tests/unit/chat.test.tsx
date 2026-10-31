import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ChatPanel } from "@/components/chat/ChatPanel";
import { chatReducer, initialChatState, type ChatAction, type ChatState } from "@/lib/chatReducer";
import { streamChat, type SseHandlers } from "@/lib/sse";
import type { Answer } from "@/lib/types";

vi.mock("@/lib/sse", () => ({ streamChat: vi.fn() }));
const mockedStream = vi.mocked(streamChat);

const answer: Answer = {
  intent: "B",
  status: "answered",
  headline: "桂枝汤",
  sections: [{ title: "组成", lines: ["桂枝三两"] }],
  citations: [],
  dose_complete: null,
  candidates: [],
  followup: [],
  general_note: null,
  disclaimer: "本回答基于本地蒸馏语料整理，仅供学习与检索参考；诊断与用药请由执业中医师面诊决定。",
  prose: "组成：桂枝三两",
  top_score: 1,
};

const done = { session_id: 7, message_id: 9, answer };

function apply(state: ChatState, ...actions: ChatAction[]): ChatState {
  return actions.reduce(chatReducer, state);
}

describe("chatReducer", () => {
  it("walks sending → intent → retrieving → streaming → done", () => {
    const sent = apply(initialChatState, { type: "send", id: "t1", question: "桂枝汤" });
    expect(sent.turns[0].phase).toBe("sending");
    expect(sent.pending).toBe(true);

    const meta = apply(sent, {
      type: "meta", id: "t1",
      meta: { session_id: 7, intent: "B", status: "answered" },
    });
    expect(meta.turns[0].phase).toBe("intent");
    expect(meta.turns[0].intent).toBe("B");
    expect(meta.sessionId).toBe(7);

    const progress = apply(meta, {
      type: "progress", id: "t1", progress: { total: 2, by_type: { formula: 2 } },
    });
    expect(progress.turns[0].phase).toBe("retrieving");

    const streaming = apply(progress, { type: "token", id: "t1", text: "桂枝" });
    expect(streaming.turns[0].phase).toBe("streaming");
    expect(streaming.turns[0].streamText).toBe("桂枝");

    const finished = apply(streaming, { type: "done", id: "t1", response: done });
    expect(finished.turns[0].phase).toBe("done");
    expect(finished.turns[0].answer?.headline).toBe("桂枝汤");
    expect(finished.pending).toBe(false);
  });

  it("keeps progress on error and preserves partial text on interrupt", () => {
    const base = apply(initialChatState,
      { type: "send", id: "t1", question: "桂枝汤" },
      { type: "progress", id: "t1", progress: { total: 1, by_type: { herb: 1 } } },
      { type: "token", id: "t1", text: "部分" });
    const errored = apply(base, { type: "error", id: "t1", message: "生成失败" });
    expect(errored.turns[0].phase).toBe("error");
    expect(errored.turns[0].progress?.total).toBe(1);
    expect(errored.pending).toBe(false);

    const interrupted = apply(base, { type: "interrupt", id: "t1" });
    expect(interrupted.turns[0].phase).toBe("interrupted");
    expect(interrupted.turns[0].streamText).toBe("部分");
  });

  it("marks a skipped intake without rewriting the answer", () => {
    const state = apply(initialChatState,
      { type: "send", id: "t1", question: "我不舒服" },
      { type: "done", id: "t1",
        response: { ...done, answer: { ...answer, status: "needs_more_info", sections: [] } } },
      { type: "skip_intake", id: "t1" });
    expect(state.turns[0].intakeSkipped).toBe(true);
    expect(state.turns[0].answer?.status).toBe("needs_more_info");
  });

  it("marks a submitted intake without dropping the answer", () => {
    const state = apply(initialChatState,
      { type: "send", id: "t1", question: "我不舒服" },
      { type: "done", id: "t1",
        response: { ...done, answer: { ...answer, status: "needs_more_info", sections: [] } } },
      { type: "submit_intake", id: "t1" });
    expect(state.turns[0].intakeSubmitted).toBe(true);
    expect(state.turns[0].answer?.status).toBe("needs_more_info");
  });
});

describe("ChatPanel", () => {
  // 块体箭头：Vitest 会把 hook 返回的函数当作 teardown 钩子，而 mockReset() 返回 mock 本身，
  // 直接返回会让 Vitest 在用例结束后以零参调用 mock，导致 mockImplementation 崩在 handlers 上。
  beforeEach(() => { mockedStream.mockReset(); });

  it("renders tokens while streaming and sections only after done", async () => {
    let release: () => void = () => {};
    const gate = new Promise<void>((resolve) => { release = resolve; });
    mockedStream.mockImplementation(async (_question, _sid, handlers: SseHandlers) => {
      handlers.onMeta?.({ session_id: 7, intent: "B", status: "answered" });
      handlers.onProgress?.({ total: 2, by_type: { formula: 2 } });
      handlers.onToken?.("桂枝汤：");
      await gate;
      handlers.onDone?.(done);
    });

    render(<ChatPanel />);
    const composer = screen.getByTestId("composer");
    await userEvent.type(composer, "桂枝汤{Enter}");

    expect(await screen.findByTestId("intent-badge")).toHaveTextContent("B 方剂");
    expect(screen.getByText("命中 2 条本地证据")).toBeInTheDocument();
    expect(screen.getByText(/桂枝汤：/)).toBeInTheDocument();
    expect(screen.queryByTestId("answer-body")).not.toBeInTheDocument();

    release();
    expect(await screen.findByTestId("answer-body")).toHaveTextContent("组成");
    expect(screen.queryByText(/桂枝汤：/)).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("回答已完成");
  });

  it("shows the refusal card and the intake card from terminal status", async () => {
    mockedStream.mockImplementation(async (_question, _sid, handlers: SseHandlers) => {
      handlers.onDone?.({
        ...done,
        answer: { ...answer, status: "refused", sections: [], prose: "" },
      });
    });
    render(<ChatPanel />);
    await userEvent.type(screen.getByTestId("composer"), "库外问题{Enter}");
    expect(await screen.findByTestId("refusal-card")).toBeInTheDocument();
    expect(screen.queryByTestId("answer-body")).not.toBeInTheDocument();

    mockedStream.mockImplementation(async (_question, _sid, handlers: SseHandlers) => {
      handlers.onDone?.({
        ...done,
        answer: {
          ...answer,
          status: "needs_more_info",
          sections: [],
          followup: ["胃口如何？", "睡眠如何？", "大便如何？"],
        },
      });
    });
    await userEvent.type(screen.getByTestId("composer"), "我不舒服{Enter}");
    const intake = await screen.findByTestId("intake-card");
    await userEvent.click(within(intake).getByRole("button", { name: "跳过，直接看回答" }));
    expect(screen.getByTestId("intake-skip-note"))
      .toHaveTextContent("基于不完整信息，以下辨证仅供参考");
    expect(screen.queryByTestId("intake-card")).not.toBeInTheDocument();
  });

  it("marks an aborted turn as interrupted", async () => {
    mockedStream.mockImplementation((_question, _sid, _handlers, signal) =>
      new Promise((_resolve, reject) => {
        signal?.addEventListener("abort", () =>
          reject(new DOMException("Aborted", "AbortError")));
      }));
    render(<ChatPanel />);
    await userEvent.type(screen.getByTestId("composer"), "桂枝汤{Enter}");
    await userEvent.click(await screen.findByRole("button", { name: "停止" }));
    expect(await screen.findByText("已中断")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重试" })).toBeInTheDocument();
  });

  it("retries once when the network fails before the first token", async () => {
    mockedStream
      .mockRejectedValueOnce(new Error("network"))
      .mockImplementationOnce(async (_question, _sid, handlers: SseHandlers) => {
        handlers.onMeta?.({ session_id: 7, intent: "B", status: "answered" });
        handlers.onDone?.(done);
      });
    render(<ChatPanel />);
    await userEvent.type(screen.getByTestId("composer"), "桂枝汤{Enter}");
    await waitFor(() => expect(mockedStream).toHaveBeenCalledTimes(2));
    expect(await screen.findByTestId("answer-body")).toBeInTheDocument();
  });

  it("keeps Shift+Enter as a newline", async () => {
    mockedStream.mockImplementation(async () => {});
    render(<ChatPanel />);
    const composer = screen.getByTestId("composer");
    await userEvent.type(composer, "第一行{Shift>}{Enter}{/Shift}第二行");
    expect(composer).toHaveValue("第一行\n第二行");
    expect(mockedStream).not.toHaveBeenCalled();
  });
});
