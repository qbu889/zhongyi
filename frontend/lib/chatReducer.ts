import type {
  Answer, AnswerStatus, ChatResponse, Citation, MetaEvent, Progress,
} from "./types";

export type TurnPhase =
  | "sending" | "intent" | "retrieving" | "streaming"
  | "done" | "refused" | "needs_more_info" | "error" | "interrupted";

export interface Turn {
  id: string;
  question: string;
  phase: TurnPhase;
  sessionId: number | null;
  messageId: number | null;
  intent: string;
  progress: Progress | null;
  citations: Citation[];
  streamText: string;
  answer: Answer | null;
  error: string | null;
  intakeSkipped: boolean;
  intakeSubmitted: boolean;
}

export interface ChatState {
  turns: Turn[];
  sessionId: number | null;
  pending: boolean;
}

export const initialChatState: ChatState = { turns: [], sessionId: null, pending: false };

export type ChatAction =
  | { type: "send"; id: string; question: string }
  | { type: "meta"; id: string; meta: MetaEvent }
  | { type: "progress"; id: string; progress: Progress }
  | { type: "citation"; id: string; citation: Citation }
  | { type: "token"; id: string; text: string }
  | { type: "done"; id: string; response: ChatResponse }
  | { type: "error"; id: string; message: string }
  | { type: "interrupt"; id: string }
  | { type: "skip_intake"; id: string }
  | { type: "submit_intake"; id: string }
  | { type: "hydrate"; sessionId: number; turns: Turn[] };

function phaseFor(status: AnswerStatus): TurnPhase {
  if (status === "refused") return "refused";
  if (status === "needs_more_info") return "needs_more_info";
  return "done";
}

function patchTurn(state: ChatState, id: string, patch: (turn: Turn) => Turn): ChatState {
  return { ...state, turns: state.turns.map((turn) => (turn.id === id ? patch(turn) : turn)) };
}

export function chatReducer(state: ChatState, action: ChatAction): ChatState {
  switch (action.type) {
    case "send":
      return {
        ...state,
        sessionId: state.sessionId,
        pending: true,
        turns: [...state.turns, {
          id: action.id,
          question: action.question,
          phase: "sending",
          sessionId: state.sessionId,
          messageId: null,
          intent: "",
          progress: null,
          citations: [],
          streamText: "",
          answer: null,
          error: null,
          intakeSkipped: false,
          intakeSubmitted: false,
        }],
      };
    case "meta":
      return {
        ...patchTurn(state, action.id, (turn) => ({
          ...turn, phase: "intent", intent: action.meta.intent, sessionId: action.meta.session_id,
        })),
        sessionId: action.meta.session_id,
      };
    case "progress":
      return patchTurn(state, action.id, (turn) =>
        ({ ...turn, phase: "retrieving", progress: action.progress }));
    case "citation":
      return patchTurn(state, action.id, (turn) => {
        const key = `${action.citation.ref_type}:${action.citation.ref_id}`;
        const exists = turn.citations.some(
          (item) => `${item.ref_type}:${item.ref_id}` === key);
        return exists ? turn : { ...turn, citations: [...turn.citations, action.citation] };
      });
    case "token":
      return patchTurn(state, action.id, (turn) =>
        ({ ...turn, phase: "streaming", streamText: turn.streamText + action.text }));
    case "done":
      return {
        ...patchTurn(state, action.id, (turn) => ({
          ...turn,
          phase: phaseFor(action.response.answer.status),
          sessionId: action.response.session_id,
          messageId: action.response.message_id,
          answer: action.response.answer,
          citations: action.response.answer.citations,
          streamText: "",
        })),
        sessionId: action.response.session_id,
        pending: false,
      };
    case "error":
      return {
        ...patchTurn(state, action.id, (turn) =>
          ({ ...turn, phase: "error", error: action.message })),
        pending: false,
      };
    case "interrupt":
      return {
        ...patchTurn(state, action.id, (turn) => ({ ...turn, phase: "interrupted" })),
        pending: false,
      };
    case "skip_intake":
      return patchTurn(state, action.id, (turn) => ({ ...turn, intakeSkipped: true }));
    case "submit_intake":
      return patchTurn(state, action.id, (turn) => ({ ...turn, intakeSubmitted: true }));
    case "hydrate":
      return { turns: action.turns, sessionId: action.sessionId, pending: false };
    default:
      return state;
  }
}
