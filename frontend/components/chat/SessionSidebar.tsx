"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { deleteSession, getSessions } from "@/lib/api";
import type { SessionItem } from "@/lib/types";

export function SessionSidebar({
  currentId,
  refreshKey = 0,
  onNewSession,
}: {
  currentId: number | null;
  refreshKey?: number;
  // 「新会话」被点时让父级面板复位状态。不 preventDefault：路由同步时
  // 仍然走真实的 /chat 服务端导航（spec §7.7）。
  onNewSession?: () => void;
}) {
  const router = useRouter();
  const [items, setItems] = useState<SessionItem[]>([]);
  const [confirming, setConfirming] = useState<number | null>(null);
  const [failed, setFailed] = useState(false);
  // 删除在飞中的会话 id：只允许一个 DELETE，避免双击重复删除。
  const [deletingId, setDeletingId] = useState<number | null>(null);
  // 删除失败：行留在确认态并给出行内错误，用户可重试或取消。
  const [deleteFailed, setDeleteFailed] = useState(false);

  const load = useCallback(() => {
    getSessions()
      .then((data) => { setItems(data.items); setFailed(false); })
      .catch(() => setFailed(true));
  }, []);

  useEffect(load, [load, refreshKey]);

  async function remove(id: number) {
    if (deletingId !== null) return;
    setDeletingId(id);
    setDeleteFailed(false);
    try {
      await deleteSession(id);
    } catch {
      // 失败兜底：不 push、不 refresh、不重载列表，否则用户会以为删成功了。
      setDeleteFailed(true);
      return;
    } finally {
      setDeletingId(null);
    }
    setConfirming(null);
    if (id === currentId) {
      router.push("/chat");
      router.refresh();
    }
    load();
  }

  return (
    <aside aria-label="会话列表" data-testid="session-sidebar" className="text-sm">
      <div className="flex items-center justify-between">
        <h2 className="font-serif text-base">历史会话</h2>
        <Link href="/chat" onClick={onNewSession} className="text-cinnabar underline">新会话</Link>
      </div>
      {failed && (
        <p className="mt-2 text-cinnabar">
          会话加载失败
          <button type="button" onClick={load} className="ml-1 underline">重试</button>
        </p>
      )}
      <ul className="mt-2 space-y-2">
        {items.map((item) => (
          <li key={item.id} data-testid="session-item"
            className={`rounded border p-2 ${
              item.id === currentId ? "border-cinnabar bg-cinnabar/5" : "border-line"
            }`}>
            <Link href={`/chat/${item.id}`}
              aria-current={item.id === currentId ? "page" : undefined}
              className="block truncate font-medium hover:text-cinnabar">
              {item.title}
            </Link>
            <p className="mt-0.5 text-xs text-ink/50">
              {new Date(item.last_activity_at).toLocaleString("zh-CN")} · {item.message_count} 条
            </p>
            {confirming === item.id ? (
              <span className="mt-1 flex flex-wrap items-center gap-2 text-xs">
                确认删除？
                <button type="button" onClick={() => remove(item.id)}
                  disabled={deletingId !== null}
                  className="text-cinnabar underline disabled:cursor-not-allowed">确认</button>
                <button type="button"
                  onClick={() => { setConfirming(null); setDeleteFailed(false); }}
                  disabled={deletingId !== null}
                  className="underline disabled:cursor-not-allowed">取消</button>
                {deleteFailed && <span role="alert" className="text-cinnabar">删除失败</span>}
              </span>
            ) : (
              <button type="button" aria-label={`删除会话 ${item.title}`}
                onClick={() => { setDeleteFailed(false); setConfirming(item.id); }}
                className="mt-1 text-xs text-ink/50 underline">删除</button>
            )}
          </li>
        ))}
        {!failed && items.length === 0 && (
          <li className="text-xs text-ink/50">还没有会话</li>
        )}
      </ul>
    </aside>
  );
}
