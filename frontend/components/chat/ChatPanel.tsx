"use client";

import { useCallback, useEffect, useReducer, useRef, useState } from "react";

import { AnswerBody } from "@/components/chat/AnswerBody";
import { Composer } from "@/components/chat/Composer";
import { IntentBadge } from "@/components/chat/IntentBadge";
import { MessageBubble } from "@/components/chat/MessageBubble";
import { RetrievalProgress } from "@/components/chat/RetrievalProgress";
import { EvidenceDrawer } from "@/components/drawer/EvidenceDrawer";
import { IntakeCard } from "@/components/intake/IntakeCard";
import { RefusalCard } from "@/components/chat/RefusalCard";
import { SessionSidebar } from "@/components/chat/SessionSidebar";
import { useChatTurn } from "@/components/chat/useChatTurn";
import {
  chatReducer, initialChatState, type ChatState, type Turn,
} from "@/lib/chatReducer";
import type { Citation } from "@/lib/types";

function announcementFor(turn: Turn | undefined): string {
  switch (turn?.phase) {
    case "done": return "回答已完成";
    case "refused": return "已按证据门禁拒答";
    case "needs_more_info": return "需要补充问诊信息";
    case "error": return "生成失败";
    case "interrupted": return "回答已中断";
    default: return "";
  }
}

function historyState(): unknown {
  // replaceState 必须带上 Next 写在 history entry 上的路由数据；传 null 会把它抹掉，
  // 于是地址栏与 router.state 脱钩，站内「新会话」退化成同树导航。
  return { ...(window.history.state ?? {}) };
}

export function ChatPanel({
  initialSessionId = null,
  initialTurns = [],
  initialQuestion = "",
}: {
  initialSessionId?: number | null;
  initialTurns?: Turn[];
  initialQuestion?: string;
}) {
  const [state, dispatch] = useReducer(chatReducer, {
    ...initialChatState,
    sessionId: initialSessionId,
    turns: initialTurns,
  } satisfies ChatState);
  const [activeCitation, setActiveCitation] = useState<Citation | null>(null);
  const [sidebarKey, setSidebarKey] = useState(0);
  const nextId = useRef(0);
  const refreshSessions = useCallback(() => setSidebarKey((key) => key + 1), []);
  const { run, stop } = useChatTurn(dispatch, refreshSessions);

  const sendQuestion = useCallback((question: string) => {
    if (state.pending) return;
    const id = `turn-${Date.now()}-${nextId.current++}`;
    dispatch({ type: "send", id, question });
    void run(id, question, state.sessionId);
  }, [run, state.pending, state.sessionId]);

  useEffect(() => {
    const pathname = window.location.pathname;
    if (state.sessionId === null) {
      // 复位到「新会话」后地址栏已是 /chat：什么也不做（不写回、不刷 history）。
      if (pathname === "/chat") return;
      // 仍停在 /chat/<id>（侧栏与 router 状态脱钩的兜底）：写回 /chat。
      // 有轮次在飞时绝不改 URL，也绝不动这一轮的数据。
      if (state.pending || !/^\/chat\/\d+$/.test(pathname)) return;
      window.history.replaceState(historyState(), "", "/chat");
      return;
    }
    const path = `/chat/${state.sessionId}`;
    if (pathname !== path) {
      window.history.replaceState(historyState(), "", path);
    }
  }, [state.pending, state.sessionId]);

  // 侧栏「新会话」的本地复位：站内跳转不会重挂载面板，reducer 会留着上一个会话的轮次
  // 与 sessionId（spec §7.7 的「新建」要求空转录 + 侧栏取消高亮）。
  const startNewSession = useCallback(() => {
    if (state.pending) return;
    dispatch({ type: "hydrate", sessionId: null, turns: [] });
    const pathname = window.location.pathname;
    if (/^\/chat\/\d+$/.test(pathname)) {
      window.history.replaceState(historyState(), "", "/chat");
    }
  }, [state.pending]);

  const lastTurn = state.turns[state.turns.length - 1];
  const announcement = announcementFor(lastTurn);

  return (
    <div className="mx-auto grid max-w-7xl gap-6 px-4 py-4 md:grid-cols-[240px_1fr]">
      <SessionSidebar currentId={state.sessionId} refreshKey={sidebarKey}
        onNewSession={startNewSession} />
      <div>
        <h1 className="sr-only">对话</h1>
        <div data-testid="chat-transcript">
          {state.turns.map((turn) => (
            <div key={turn.id}>
              <MessageBubble role="user">{turn.question}</MessageBubble>
              <MessageBubble role="assistant">
                <div className="flex flex-wrap items-center gap-2">
                  <IntentBadge intent={turn.intent} />
                  {turn.phase === "sending" && (
                    <span data-testid="sending" className="text-xs text-ink/60">正在检索本地语料…</span>
                  )}
                </div>
                {turn.progress && (
                  <RetrievalProgress progress={turn.progress} citations={turn.citations} />
                )}
                {!turn.answer && (turn.phase === "streaming"
                  || turn.phase === "interrupted"
                  || turn.phase === "error") && (
                  <p data-testid="stream-text" className="mt-2 whitespace-pre-wrap text-sm">{turn.streamText}</p>
                )}
                {turn.answer?.status === "refused" && (
                  <RefusalCard answer={turn.answer} question={turn.question}
                    onAsk={sendQuestion} />
                )}
                {turn.answer?.status === "needs_more_info"
                  && !turn.intakeSkipped && !turn.intakeSubmitted && (
                  <IntakeCard followup={turn.answer.followup} initialText={turn.question}
                    onSubmit={(summary) => {
                      // 提交后清空卡片，摘要作为新的用户消息重新进入辨证链（spec §8.4）。
                      dispatch({ type: "submit_intake", id: turn.id });
                      sendQuestion(summary);
                    }}
                    onSkip={() => dispatch({ type: "skip_intake", id: turn.id })} />
                )}
                {turn.intakeSkipped && (
                  <p data-testid="intake-skip-note"
                    className="mt-2 rounded border border-dashed border-line bg-ink/5 p-2 text-xs text-ink/70">
                    基于不完整信息，以下辨证仅供参考
                  </p>
                )}
                {turn.answer && turn.answer.status === "answered" && (
                  <AnswerBody answer={turn.answer} onOpenCitation={setActiveCitation} />
                )}
                {turn.phase === "error" && (
                  <div className="mt-2 flex items-center gap-2 text-sm text-cinnabar">
                    生成失败
                    <button type="button" onClick={() => sendQuestion(turn.question)}
                      className="underline">重试</button>
                  </div>
                )}
                {turn.phase === "interrupted" && (
                  <div className="mt-2 flex items-center gap-2 text-sm text-ink/60">
                    已中断
                    <button type="button" onClick={() => sendQuestion(turn.question)}
                      className="underline">重试</button>
                  </div>
                )}
              </MessageBubble>
            </div>
          ))}
        </div>
        <Composer pending={state.pending} initialValue={initialQuestion}
          onSend={sendQuestion} onStop={stop} />
        <div role="status" aria-live="polite" className="sr-only">{announcement}</div>
        <EvidenceDrawer citation={activeCitation} onClose={() => setActiveCitation(null)} />
      </div>
    </div>
  );
}
