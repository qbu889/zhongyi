"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { deleteSession, getSessions } from "@/lib/api";
import type { SessionItem } from "@/lib/types";

export function SessionSidebar({
  currentId,
  refreshKey = 0,
}: {
  currentId: number | null;
  refreshKey?: number;
}) {
  const router = useRouter();
  const [items, setItems] = useState<SessionItem[]>([]);
  const [confirming, setConfirming] = useState<number | null>(null);
  const [failed, setFailed] = useState(false);

  const load = useCallback(() => {
    getSessions()
      .then((data) => { setItems(data.items); setFailed(false); })
      .catch(() => setFailed(true));
  }, []);

  useEffect(load, [load, refreshKey]);

  async function remove(id: number) {
    await deleteSession(id);
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
        <Link href="/chat" className="text-cinnabar underline">新会话</Link>
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
              <span className="mt-1 flex gap-2 text-xs">
                确认删除？
                <button type="button" onClick={() => remove(item.id)}
                  className="text-cinnabar underline">确认</button>
                <button type="button" onClick={() => setConfirming(null)}
                  className="underline">取消</button>
              </span>
            ) : (
              <button type="button" aria-label={`删除会话 ${item.title}`}
                onClick={() => setConfirming(item.id)}
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
