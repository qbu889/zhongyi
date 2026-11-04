"use client";

import { useCallback, useEffect, useRef, useState } from "react";

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
  /** 修复轮 3：陈旧响应守卫（自增序号制，不选 AbortController——理由记在 task-15-report.md「修复轮 3」）。
   *
   * 缺陷本体：`load()` 每次先 `setData(null)`（收起上一屏的行），PendingTable 随之整棵卸载，而上一张
   * 列表的 GET 还在途。真实网络下那条旧 GET（`decision=pending` 全量 63 行、limit=200）常常比新筛选的
   * 小响应**晚 15–21ms** 落地，`.then(setData)` 不分先后、后到者赢 ⇒ 筛选框停在「已归并」、屏上却是
   * 待审队列，且这个覆盖是持久的（e2e #35「归并即时生效」间歇翻红的根因即此）。维护者看到的就是
   * "数据不见了"，所以这是产品缺陷，不该由 e2e 的等待策略长期掩盖。
   *
   * 修法：发出请求前取一个自增序号，响应落地（成功或失败）时先比对"这还是最新那次请求吗"，
   * 不是就整条丢弃。两个入口——筛选变更（decision/reason → 新的 load）与 `onChanged()` 触发的
   * nonce 重取——都汇聚到本函数，所以一处守卫同时管住。
   * 不用 `setTimeout`/固定延时去"等旧请求过去"：那只是把一种竞态换成另一种竞态。 */
  const generation = useRef(0);
  const load = useCallback(() => {
    const current = ++generation.current;
    setError("");
    // 换筛选/重新加载时先收起上一屏的行：加载中、失败、空、有数据是四面，不同时出现。
    setData(null);
    const params = new URLSearchParams({ decision });
    if (reason) params.set("reason", reason);
    // F-3（规格 §9:123 截断面）：显式要 `limit=200`（端点钳制到 [1,200] 并回显，admin.py:130-139 /
    // list_pending 的 max 常量），让 pending 队列一次就装得下当前全量（真实基线 64 行、单原因筛选仍 >50）。
    // 缺省 limit=50 时「请用筛选缩小范围」是给不到剩余行的建议；真超过 200 时的分页 UI 登记 T16。
    params.set("limit", "200");
    adminGet<PendingList>(`${PENDING_PATH}?${params.toString()}`)
      .then((payload) => {
        // 陈旧响应丢弃：晚到的旧筛选结果不许覆盖最新一次的视图。
        if (current !== generation.current) return;
        setData(payload);
      })
      .catch((caught: unknown) => {
        if (current !== generation.current) return;
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
