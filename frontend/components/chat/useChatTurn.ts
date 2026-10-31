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
        onDone: (response) => dispatch({ type: "done", id, response }),
        onError: (error) => dispatch({ type: "error", id, message: error.message }),
      }, controllerRef.current.signal);
    };

    try {
      try {
        await attempt();
      } catch (first) {
        if (controllerRef.current?.signal.aborted) {
          dispatch({ type: "interrupt", id });
          return;
        }
        if (sawToken) {
          dispatch({
            type: "error", id,
            message: first instanceof Error ? first.message : "生成失败",
          });
          return;
        }
        try {
          await attempt();
        } catch (second) {
          if (controllerRef.current?.signal.aborted) {
            dispatch({ type: "interrupt", id });
            return;
          }
          dispatch({
            type: "error", id,
            message: second instanceof Error ? second.message : "生成失败",
          });
        }
      }
    } finally {
      onSettled?.();
    }
  }, [dispatch, onSettled]);

  const stop = useCallback(() => controllerRef.current?.abort(), []);

  return { run, stop };
}
