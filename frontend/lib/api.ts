import type {
  ChatHistory,
  ChatResponse,
  EvidenceRef,
  SearchResponse,
  SessionListResponse,
} from "./types";

const SERVER_BASE = process.env.BACKEND_ORIGIN ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(public code: string, message: string, public status: number) {
    super(message);
    this.name = "ApiError";
  }
}

export async function parseApiError(res: Response): Promise<ApiError> {
  let code = "http_error";
  let message = `HTTP ${res.status}`;
  try {
    const body = (await res.json()) as { detail?: { code?: string; message?: string } };
    code = body.detail?.code ?? code;
    message = body.detail?.message ?? message;
  } catch {
    // 非 JSON 错误体保持默认文案
  }
  return new ApiError(code, message, res.status);
}

export async function serverGet<T>(path: string): Promise<T> {
  const res = await fetch(`${SERVER_BASE}${path}`, { cache: "no-store" });
  if (!res.ok) throw await parseApiError(res);
  return (await res.json()) as T;
}

export async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(path, { cache: "no-store" });
  if (!res.ok) throw await parseApiError(res);
  return (await res.json()) as T;
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw await parseApiError(res);
  return (await res.json()) as T;
}

export async function getSessions(limit = 50): Promise<SessionListResponse> {
  return apiGet(`/api/chat/sessions?limit=${limit}`);
}

export async function getHistory(sessionId: number): Promise<ChatHistory> {
  return apiGet(`/api/chat/${sessionId}`);
}

export async function deleteSession(sessionId: number): Promise<void> {
  const res = await fetch(`/api/chat/${sessionId}`, { method: "DELETE" });
  if (!res.ok) throw await parseApiError(res);
}

export async function getEvidence(refType: string, refId: number): Promise<EvidenceRef> {
  return apiGet(`/api/evidence/${refType}:${refId}`);
}

export async function search(query: string, kinds: string[] = [], top = 8): Promise<SearchResponse> {
  // 后端 SearchRequest 的字段是单数 `kind`
  return apiPost("/api/search", { query, kind: kinds.length ? kinds : null, top });
}

export async function createChat(payload: {
  question: string;
  session_id?: number | null;
}): Promise<ChatResponse> {
  return apiPost("/api/chat", payload);
}
