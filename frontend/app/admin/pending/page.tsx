"use client";

import { useCallback, useEffect, useState } from "react";

import { AdminShell, useAdminReauth } from "@/components/admin/AdminShell";
import { PendingTable } from "@/components/admin/PendingTable";
import {
  PENDING_PATH, adminErrorLabel, adminGet, isAdminUnauthorized, type PendingList,
} from "@/lib/admin";

const REASONS = ["", "no_formula_name", "multi_name_row", "no_composition", "pair_without_composition"];
/** 指针 §5：`GET /api/admin/pending` 缺省只回 `decision=pending` 的行，显式传值按该值过滤，
 * 而 `?decision=`（显式空串）是唯一的**全量**通道。本页只发这里列出的具体值，永不发空串，
 * 所以 `PENDING_ALL_PATH` 在本页用不上——"看已判定"是一条条判定值看，不是把全表捞回来。 */
const DECISIONS = [
  { value: "pending", label: "待审（pending）" },
  { value: "merged", label: "已归并（merged）" },
  { value: "confirmed_new", label: "已确认独立方（confirmed_new）" },
  { value: "noise", label: "已判噪声（noise）" },
];

export default function AdminPendingPage() {
  return (
    <AdminShell title="候选方名审核" path="/admin/pending">
      <PendingBody />
    </AdminShell>
  );
}

function PendingBody() {
  const reprobe = useAdminReauth();
  const [reason, setReason] = useState("");
  const [decision, setDecision] = useState("pending");
  const [data, setData] = useState<PendingList | null>(null);
  const [error, setError] = useState("");
  const [nonce, setNonce] = useState(0);
  const load = useCallback(() => {
    setError("");
    // 换筛选/重新加载时先收起上一屏的行：加载中、失败、空、有数据是四面，不同时出现。
    setData(null);
    const params = new URLSearchParams({ decision });
    if (reason) params.set("reason", reason);
    adminGet<PendingList>(`${PENDING_PATH}?${params.toString()}`)
      .then(setData)
      .catch((caught: unknown) => {
        // 指针 §1/§4：数据端点 401 = 会话过期，交回 AdminShell 重新探针，不查标签表。
        if (isAdminUnauthorized(caught)) { reprobe(); return; }
        setError(adminErrorLabel(caught));
      });
  }, [decision, reason, reprobe]);
  useEffect(load, [load, nonce]);

  return (
    <>
      <div className="flex flex-wrap gap-3">
        <div>
          <label className="block text-sm" htmlFor="pending-decision">按判定筛选</label>
          <select id="pending-decision" value={decision}
            onChange={(event) => setDecision(event.target.value)}
            className="mt-1 w-full max-w-xs rounded border border-line bg-paper px-2 py-1">
            {DECISIONS.map(({ value, label }) => <option key={value} value={value}>{label}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-sm" htmlFor="pending-reason">按原因筛选</label>
          <select id="pending-reason" value={reason}
            onChange={(event) => setReason(event.target.value)}
            className="mt-1 w-full max-w-xs rounded border border-line bg-paper px-2 py-1">
            {REASONS.map((value) => <option key={value || "all"} value={value}>{value || "全部"}</option>)}
          </select>
        </div>
      </div>
      {error && (
        <p role="alert" className="mt-2 text-sm text-cinnabar">队列加载失败：{error}
          <button type="button" onClick={load} className="ml-2 underline">重试</button></p>
      )}
      {!error && !data && <p role="status" className="mt-3 text-sm text-ink/70">读取候选队列…</p>}
      {!error && data && (data.items.length === 0
        ? <p className="mt-2 text-sm text-ink/70">该筛选下没有候选行。</p>
        : <>
          {/* limit 由后端钳制到 [1,200] 并回显实际生效值（admin.py:150）；本屏装不下整条队列时
            * 说明白截断，不让维护者以为审完看到的那几十条就是全部。 */}
          {data.items.length < data.total && (
            <p className="mt-2 text-xs text-ink/70">后端 limit 上限 200：共 {data.total} 条，此屏载入前 {data.items.length} 条（limit {data.limit}）。请用筛选缩小范围。</p>
          )}
          <div className="mt-2 overflow-x-auto">
            <PendingTable items={data.items} total={data.total}
              onChanged={() => setNonce((n) => n + 1)} />
          </div>
        </>)}
    </>
  );
}
