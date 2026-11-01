"use client";

import * as Dialog from "@radix-ui/react-dialog";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { ApiError, getEvidence } from "@/lib/api";
import { detailHref } from "@/lib/refs";
import type { Citation, EvidenceRef } from "@/lib/types";

type State =
  | { kind: "loading" }
  | { kind: "ready"; evidence: EvidenceRef }
  | { kind: "error"; message: string };

function highlight(text: string, snippet: string) {
  const index = snippet ? text.indexOf(snippet) : -1;
  if (index < 0) return text;
  return (
    <>
      {text.slice(0, index)}
      <mark className="bg-cinnabar/15">{snippet}</mark>
      {text.slice(index + snippet.length)}
    </>
  );
}

export function EvidenceDrawer({
  citation,
  onClose,
}: {
  citation: Citation | null;
  onClose: () => void;
}) {
  const [state, setState] = useState<State>({ kind: "loading" });
  // 抽屉没有 Dialog.Trigger，Radix 默认无法把焦点还给角标：
  // 打开时记住当前焦点元素，关闭时（含 Esc）显式还原（spec §7.4）。
  const openerRef = useRef<HTMLElement | null>(null);
  const key = citation ? `${citation.ref_type}:${citation.ref_id}` : null;

  useEffect(() => {
    if (!citation) {
      // 关闭时清空旧 ref 的内容，重新打开其他出处时不会闪现上一段原文。
      setState({ kind: "loading" });
      return;
    }
    let cancelled = false;
    setState({ kind: "loading" });
    getEvidence(citation.ref_type, citation.ref_id)
      .then((evidence) => {
        if (!cancelled) setState({ kind: "ready", evidence });
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        const message = error instanceof ApiError && error.code === "ref_not_found"
          ? "该出处在当前索引版本不存在"
          : "出处加载失败，请重试";
        setState({ kind: "error", message });
      });
    return () => { cancelled = true; };
    // 以稳定 key 为依赖：父组件传入同一 ref 的新对象时不应重复请求。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  const formulaId = state.kind === "ready" ? state.evidence.fields.formula_id : null;
  const href = citation ? detailHref(citation)
    : null;
  const fallbackHref = !href && typeof formulaId === "number"
    ? `/formulas/${formulaId}` : null;

  return (
    <Dialog.Root open={Boolean(citation)} onOpenChange={(open) => { if (!open) onClose(); }}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-30 bg-ink/30" />
        <Dialog.Content
          data-testid="evidence-drawer"
          aria-describedby={undefined}
          onOpenAutoFocus={() => {
            if (document.activeElement instanceof HTMLElement) {
              openerRef.current = document.activeElement;
            }
          }}
          onCloseAutoFocus={(event) => {
            event.preventDefault();
            openerRef.current?.focus();
          }}
          className="fixed inset-x-0 bottom-0 z-40 max-h-[85vh] overflow-y-auto rounded-t border-t border-line bg-paper p-4 shadow-xl md:inset-y-0 md:left-auto md:right-0 md:h-full md:max-h-none md:w-full md:max-w-md md:rounded-none md:border-l md:border-t-0"
        >
          <div className="flex items-start justify-between gap-3">
            <div>
              <Dialog.Title className="font-serif text-lg">
                {citation?.title ?? "出处"}
              </Dialog.Title>
              <p className="mt-1 text-xs text-ink/70">{citation?.anchor}</p>
            </div>
            <button type="button" onClick={onClose} aria-label="关闭溯源抽屉"
              className="rounded border border-line px-2 py-1 text-sm">关闭</button>
          </div>

          {state.kind === "loading" && (
            <p role="status" className="mt-4 text-sm text-ink/70">加载原文…</p>
          )}
          {state.kind === "error" && (
            <p role="alert" className="mt-4 text-sm text-cinnabar">{state.message}</p>
          )}
          {state.kind === "ready" && (
            <>
              <p className="mt-4 whitespace-pre-wrap font-serif leading-7">
                {highlight(state.evidence.text, citation?.snippet ?? "")}
              </p>
              <div className="mt-4 flex flex-wrap gap-3 text-sm">
                {(href ?? fallbackHref) && (
                  <Link className="text-cinnabar underline" href={(href ?? fallbackHref)!}>
                    在库详情页打开
                  </Link>
                )}
                <button type="button" className="text-cinnabar underline"
                  onClick={() => {
                    // 非安全上下文下 navigator.clipboard 为 undefined，避免 TypeError。
                    void navigator.clipboard?.writeText(
                      `${citation?.title}\n${citation?.anchor}\n\n${state.evidence.text}`);
                  }}>
                  复制引用
                </button>
              </div>
            </>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
