import { notFound } from "next/navigation";

import { ChatPanel } from "@/components/chat/ChatPanel";
import { ApiError, serverGet } from "@/lib/api";
import { historyToTurns } from "@/lib/history";
import type { ChatHistory } from "@/lib/types";

export default async function SessionPage({
  params,
}: {
  params: Promise<{ sessionId: string }>;
}) {
  const { sessionId } = await params;
  // 只接受纯数字段：Number() 会放行 "0x10" / "1e2" / " 5 " 这类写法，必须先把它们挡在 notFound()。
  if (!/^\d+$/.test(sessionId)) notFound();
  const id = Number(sessionId);
  if (!Number.isInteger(id) || id <= 0) notFound();

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
