import { notFound } from "next/navigation";

import { ChatPanel } from "@/components/chat/ChatPanel";
import { ApiError, serverGet } from "@/lib/api";
import { parseId } from "@/lib/detail";
import { historyToTurns } from "@/lib/history";
import type { ChatHistory } from "@/lib/types";

export default async function SessionPage({
  params,
}: {
  params: Promise<{ sessionId: string }>;
}) {
  const { sessionId } = await params;
  // 与四大库详情同一把尺（R17）：Number() + Number.isInteger 会放行 20–21 位写法
  // （Number.isInteger(1e20) 为 true），那种段会打到后端 bigint 越界、在公开路由上
  // 变成 Next 的崩溃页；parseId 用 /^\d+$/ + Number.isSafeInteger 一律挡在 notFound()。
  const id = parseId(sessionId);

  let history: ChatHistory;
  try {
    history = await serverGet<ChatHistory>(`/api/chat/${id}`);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    throw error;
  }

  // 服务端把已存答案重放为完整轮次，绝不重新提问（spec §7.7）。
  return (
    <ChatPanel initialSessionId={id} initialTurns={historyToTurns(history.messages)} />
  );
}
