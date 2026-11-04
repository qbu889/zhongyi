"use client";

import Link from "next/link";
import { useCallback, useEffect, useState, type ReactNode } from "react";

import { LoginCard } from "@/components/admin/LoginCard";
import { adminErrorLabel, adminProbe, type AdminGate } from "@/lib/admin";

const NAV = [
  ["/admin", "概览"],
  ["/admin/quality", "质量报告"],
  ["/admin/pending", "候选方名"],
  ["/admin/logs", "问答日志"],
] as const;

export function AdminShell({ title, path = "", children }: {
  title: string;
  /** 当前路由，用于 aria-current；不给则不高亮（登录门测试不需要导航态）。 */
  path?: string;
  children: ReactNode;
}) {
  const [gate, setGate] = useState<AdminGate>("unknown");
  const [probeError, setProbeError] = useState("");
  const probe = useCallback(() => {
    setGate("unknown");
    adminProbe()
      .then((session) => setGate(!session.enabled ? "disabled" : session.authenticated ? "ready" : "locked"))
      .catch((error) => { setProbeError(adminErrorLabel(error)); setGate("disabled"); });
  }, []);
  useEffect(probe, [probe]);

  return (
    <div className="mx-auto max-w-6xl px-4 py-4">
      <h1 className="font-serif text-2xl">{title}</h1>
      <nav aria-label="管理端导航" data-testid="admin-nav" className="mt-2 flex flex-wrap gap-3 text-sm">
        {NAV.map(([href, label]) => (
          <Link key={href} href={href} aria-current={href === path ? "page" : undefined}
            className={href === path ? "font-semibold text-cinnabar underline" : "text-cinnabar underline"}>
            {label}
          </Link>
        ))}
      </nav>
      <div data-testid="admin-shell" className="mt-4">
        {gate === "unknown" && <p role="status" className="text-sm text-ink/70">检查管理端状态…</p>}
        {gate === "disabled" && (
          <p role="alert" className="rounded border border-cinnabar/40 bg-cinnabar/5 p-3 text-sm text-cinnabar">
            {probeError || "管理端未启用：请设置 ADMIN_TOKEN（至少 16 字符）"}
          </p>
        )}
        {gate === "locked" && <LoginCard onSignedIn={probe} />}
        {gate === "ready" && children}
      </div>
    </div>
  );
}
