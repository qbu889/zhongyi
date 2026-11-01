"use client";

import { useState } from "react";

import { answerToMarkdown } from "@/lib/export";
import type { Answer } from "@/lib/types";

export function AnswerActions({ answer }: { answer: Answer }) {
  const [status, setStatus] = useState("");

  async function copy() {
    // 非安全上下文下 navigator.clipboard 是 undefined：先挡住，避免 TypeError；
    // 失败也只落到提示文案，不打断阅读（spec §10）。
    if (!navigator.clipboard) {
      setStatus("复制失败，请手动选择正文");
      return;
    }
    try {
      await navigator.clipboard.writeText(answerToMarkdown(answer));
      setStatus("已复制到剪贴板");
    } catch {
      setStatus("复制失败，请手动选择正文");
    }
  }

  function download() {
    const markdown = answerToMarkdown(answer);
    const blob = new Blob([markdown], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${(answer.headline || "answer").replace(/[\\/:*?"<>|]/g, "_")}.md`;
    anchor.click();
    URL.revokeObjectURL(url);
    setStatus("已导出 Markdown");
  }

  return (
    <div data-testid="answer-actions" className="mt-3 flex flex-wrap items-center gap-3 text-sm">
      <button type="button" onClick={copy} className="text-cinnabar underline">复制全文</button>
      <button type="button" onClick={download} className="text-cinnabar underline">
        导出 Markdown
      </button>
      <span role="status" aria-live="polite" className="text-xs text-ink/70">{status}</span>
    </div>
  );
}
