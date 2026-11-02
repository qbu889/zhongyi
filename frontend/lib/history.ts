import type { Turn } from "./chatReducer";
import type { Answer, ChatHistoryMessage } from "./types";

export function historyToTurns(messages: ChatHistoryMessage[]): Turn[] {
  const turns: Turn[] = [];
  messages.forEach((message, index) => {
    if (message.role !== "user") return;
    const next = messages[index + 1];
    const answer = next?.role === "assistant"
      ? (next.content as unknown as Answer)
      : null;
    const question = typeof message.content.text === "string" ? message.content.text : "";
    turns.push({
      id: `history-${index}`,
      question,
      phase: answer
        ? answer.status === "refused" ? "refused"
          : answer.status === "needs_more_info" ? "needs_more_info" : "done"
        : "interrupted",
      sessionId: null,
      messageId: null,
      intent: answer?.intent ?? "",
      progress: null,
      citations: answer?.citations ?? [],
      streamText: "",
      answer,
      error: null,
      intakeSkipped: false,
      intakeSubmitted: false,
    });
  });
  return turns;
}
