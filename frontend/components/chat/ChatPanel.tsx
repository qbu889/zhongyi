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
    if (!state.sessionId) return;
    const path = `/chat/${state.sessionId}`;
    if (window.location.pathname !== path) {
      window.history.replaceState(null, "", path);
    }
  }, [state.sessionId]);

  const lastTurn = state.turns[state.turns.length - 1];
  const announcement = announcementFor(lastTurn);

  return (
    <div className="mx-auto grid max-w-7xl gap-6 px-4 py-4 md:grid-cols-[240px_1fr]">
      <SessionSidebar currentId={state.sessionId} refreshKey={sidebarKey} />
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
