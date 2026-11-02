"use client";

import { Suspense, useEffect, useState } from "react";

import { useSearchParams } from "next/navigation";

import { ChatPanel } from "@/components/chat/ChatPanel";
import { getEvidence } from "@/lib/api";
import { prefillFromEvidence } from "@/lib/format";

function ChatPageInner() {
  const searchParams = useSearchParams();
  const ref = searchParams.get("ref");
  const [question, setQuestion] = useState("");

  useEffect(() => {
    if (!ref) return;
    const [refType, rawId] = ref.split(":");
    if (!refType || !rawId || !/^\d+$/.test(rawId)) return;
    let cancelled = false;
    getEvidence(refType, Number(rawId))
      .then((evidence) => { if (!cancelled) setQuestion(prefillFromEvidence(evidence)); })
      .catch(() => { if (!cancelled) setQuestion(""); });
    return () => { cancelled = true; };
  }, [ref]);

  return <ChatPanel initialQuestion={question} />;
}

export default function ChatPage() {
  return (
    <Suspense fallback={<p className="p-4 text-sm text-ink/70">加载…</p>}>
      <ChatPageInner />
    </Suspense>
  );
}
