"use client";

import { useCallback, useRef, type Dispatch } from "react";

import { streamChat } from "@/lib/sse";

import type { ChatAction } from "@/lib/chatReducer";

export function useChatTurn(
  dispatch: Dispatch<ChatAction>,
  onSettled?: () => void,
) {
  const controllerRef = useRef<AbortController | null>(null);

  const run = useCallback(async (id: string, question: string, sessionId: number | null) => {
    let sawToken = false;
    let activeSession = sessionId;
    // 每一轮 run 只允许一个终态（spec §7.8）：done/error/interrupt 一旦派发即视为已结算。
    // streamChat 在终帧之后仍会继续读流，其后连接断开抛出的异常不得再改写这一轮——
    // 否则会给已完成轮补发 error、给拒答/问诊轮触发自动重试（重复 POST 与重复落库）。
    let settled = false;

    const attempt = async () => {
      controllerRef.current = new AbortController();
      await streamChat(question, activeSession, {
        onMeta: (meta) => {
          activeSession = meta.session_id;
          dispatch({ type: "meta", id, meta });
        },
        onProgress: (progress) => dispatch({ type: "progress", id, progress }),
        onCitation: (citation) => dispatch({ type: "citation", id, citation }),
        onToken: (text) => {
          sawToken = true;
          dispatch({ type: "token", id, text });
        },
        onDone: (response) => {
          settled = true;
          dispatch({ type: "done", id, response });
        },
        onError: (error) => {
          settled = true;
          dispatch({ type: "error", id, message: error.message });
        },
      }, controllerRef.current.signal);
    };

    try {
      try {
        await attempt();
      } catch (first) {
        if (settled) return;
        if (controllerRef.current?.signal.aborted) {
          settled = true;
          dispatch({ type: "interrupt", id });
          return;
        }
        if (sawToken) {
          settled = true;
          dispatch({
            type: "error", id,
            message: first instanceof Error ? first.message : "生成失败",
          });
          return;
        }
        try {
          await attempt();
        } catch (second) {
          if (settled) return;
          if (controllerRef.current?.signal.aborted) {
            settled = true;
            dispatch({ type: "interrupt", id });
            return;
          }
          settled = true;
          dispatch({
            type: "error", id,
            message: second instanceof Error ? second.message : "生成失败",
          });
        }
      }
    } finally {
      onSettled?.();
    }

    // 兜底：适配层 resolve 却不派发终帧时，pending 不能永久卡在 true。
    if (!settled) {
      settled = true;
      dispatch({ type: "error", id, message: "生成失败" });
    }
  }, [dispatch, onSettled]);

  const stop = useCallback(() => controllerRef.current?.abort(), []);

  return { run, stop };
}
