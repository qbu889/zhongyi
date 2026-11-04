"use client";

import { useCallback, useEffect, useState } from "react";

import { AdminShell, useAdminReauth } from "@/components/admin/AdminShell";
import { ReindexPanel } from "@/components/admin/ReindexPanel";
import { VersionTable } from "@/components/admin/VersionTable";
import { adminErrorLabel, adminGet, isAdminUnauthorized, type IndexVersions } from "@/lib/admin";

export default function AdminOverviewPage() {
  return (
    <AdminShell title="管理端概览" path="/admin">
      <Overview />
    </AdminShell>
  );
}

function Overview() {
  const reprobe = useAdminReauth();
  const [data, setData] = useState<IndexVersions | null>(null);
  const [error, setError] = useState("");
  const [nonce, setNonce] = useState(0);
  const load = useCallback(() => {
    setError("");
    adminGet<IndexVersions>("/api/admin/index-versions")
      .then(setData)
      .catch((caught: unknown) => {
        // 指针 §4：401 = 会话过期，交回 AdminShell 重新探针（门会接管成登录卡），
        // 绝不进 adminErrorLabel——那会对什么都没输的维护者说「口令不正确」。
        if (isAdminUnauthorized(caught)) { reprobe(); return; }
        setError(adminErrorLabel(caught));
      });
  }, [reprobe]);
  useEffect(load, [load, nonce]);

  return (
    <>
      {error && <p role="alert" className="text-sm text-cinnabar">索引信息加载失败：{error}
        <button type="button" onClick={load} className="ml-2 underline">重试</button></p>}
      {data && <VersionTable data={data} />}
      <ReindexPanel onDone={() => setNonce((n) => n + 1)} />
    </>
  );
}
