import { ApiError, parseApiError } from "./api";
import type { ChatResponse, Citation, MetaEvent, Progress } from "./types";

export interface SseHandlers {
  onMeta?: (meta: MetaEvent) => void;
  onProgress?: (progress: Progress) => void;
  onCitation?: (citation: Citation) => void;
  onToken?: (text: string) => void;
  onDone?: (response: ChatResponse) => void;
  onError?: (error: { code: string; message: string }) => void;
}

export function parseSseFrame(frame: string): { event: string; data: unknown } | null {
  let event = "message";
  const data: string[] = [];
  for (const raw of frame.split("\n")) {
    const line = raw.trimEnd();
    if (!line || line.startsWith(":")) continue;
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) data.push(line.slice(5).replace(/^ /, ""));
  }
  if (!data.length) return null;
  const text = data.join("\n");
  let parsed: unknown = text;
  try {
    parsed = JSON.parse(text);
  } catch {
    // 非 JSON data 保留原字符串
  }
  return { event, data: parsed };
}

export async function streamChat(
  question: string,
  sessionId: number | null,
  handlers: SseHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch("/api/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify({ question, session_id: sessionId }),
    signal,
  });
  if (!res.ok) throw await parseApiError(res);
  if (!res.body) throw new ApiError("no_body", "流式响应不可读", 0);

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let sawTerminal = false;

  const handleFrame = (frame: string) => {
    const parsed = parseSseFrame(frame);
    if (!parsed) return;
    // done/error 的 data 必须是完整 JSON 对象；退化为字符串说明 JSON 在流中断处被截断，
    // 此时不得视为终帧，交由末尾的 sawTerminal 检查报 stream_truncated。
    const terminal = typeof parsed.data === "object" && parsed.data !== null;
    switch (parsed.event) {
      case "meta": handlers.onMeta?.(parsed.data as MetaEvent); break;
      case "progress": handlers.onProgress?.(parsed.data as Progress); break;
      case "citation": handlers.onCitation?.(parsed.data as Citation); break;
      case "token": {
        // 只派发能解析为字符串的 token，避免截断帧吐出 undefined。
        const text = typeof parsed.data === "string"
          ? parsed.data
          : (parsed.data as { text?: unknown })?.text;
        if (typeof text === "string") handlers.onToken?.(text);
        break;
      }
      case "done":
        if (!terminal) break;
        sawTerminal = true;
        handlers.onDone?.(parsed.data as ChatResponse);
        break;
      case "error":
        if (!terminal) break;
        sawTerminal = true;
        handlers.onError?.(parsed.data as { code: string; message: string });
        break;
      default: break;
    }
  };

  // 用户主动中止（AbortError）会从 reader.read()/fetch 直接抛出，保持原样向上传递。
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let index = buffer.indexOf("\n\n");
    while (index >= 0) {
      const frame = buffer.slice(0, index);
      buffer = buffer.slice(index + 2);
      handleFrame(frame);
      index = buffer.indexOf("\n\n");
    }
  }

  // 末尾没有空行收尾的残余帧（如 done/error）也要派发，再判断流是否正常结束。
  buffer += decoder.decode();
  if (buffer.trim()) handleFrame(buffer);
  if (!sawTerminal) throw new ApiError("stream_truncated", "流式响应未正常结束", 0);
}
