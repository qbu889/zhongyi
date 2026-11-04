"use client";

import { useCallback, useEffect, useState } from "react";

import { useAdminReauth } from "@/components/admin/AdminShell";
import {
  adminErrorLabel, adminGet, isAdminUnauthorized,
  type LogList, type LogsSummary, type RefusalList,
} from "@/lib/admin";

// 请求窗口（发出去的参数）：后端会钳制到 [1,365] 后回显生效值（R-M5-13），
// 页面上出现的"近 N 日"一律取响应 window_days，而不是这里写死的请求值。
const REQUEST_WINDOW_DAYS = 7;
const REQUEST_LIMIT = 50;

const INTENTS = ["", "A", "B", "C", "D", "E", "F"];

/** 拒答率格式化：指针 §2——不得四舍五入成"0%"掩盖非零值。0<rate<0.005 时 round 会塌成 0，
 * 那等于对维护者谎称"零拒答"，这里显式给 <1%。 */
function formatRate(rate: number): string {
  const pct = rate * 100;
  if (rate > 0 && pct < 1) return "<1%";
  return `${Math.round(pct)}%`;
}

export function LogsDashboard() {
  const reprobe = useAdminReauth();
  const [summary, setSummary] = useState<LogsSummary | null>(null);
  const [refusals, setRefusals] = useState<RefusalList | null>(null);
  const [list, setList] = useState<LogList | null>(null);
  const [intent, setIntent] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(() => {
    setError("");
    Promise.all([
      adminGet<LogsSummary>(`/api/admin/logs/summary?window_days=${REQUEST_WINDOW_DAYS}`),
      adminGet<RefusalList>(`/api/admin/logs/refusals?window_days=${REQUEST_WINDOW_DAYS}`),
      adminGet<LogList>(
        `/api/admin/logs?limit=${REQUEST_LIMIT}${intent ? `&intent=${intent}` : ""}`),
    ])
      .then(([sum, rank, rows]) => {
        setSummary(sum); setRefusals(rank); setList(rows);
      })
      .catch((caught: unknown) => {
        // 指针 §1：三端点任一 401 = 会话过期，交回 AdminShell 重新探针，不查标签表。
        if (isAdminUnauthorized(caught)) { reprobe(); return; }
        setError(adminErrorLabel(caught));
      });
  }, [intent, reprobe]);
  useEffect(load, [load]);

  return (
    <div data-testid="logs-dashboard">
      {/* 规格 §8：工程侧主动提示日志含主诉原文，属敏感信息，不等产品催。 */}
      <p className="rounded border border-dashed border-line bg-ink/5 p-2 text-xs text-ink/70">
        日志含用户主诉原文，属敏感信息：勿截图外传；保留期与删除权待 E2 定义。
      </p>

      {error && (
        <p role="alert" className="mt-2 text-sm text-cinnabar">日志加载失败：{error}
          <button type="button" onClick={load} className="ml-2 underline">重试</button></p>
      )}
      {!error && !summary && <p role="status" className="mt-3 text-sm text-ink/70">读取问答日志…</p>}

      {!error && summary && (
        // 指针 §2：四张卡的值全部来自 /logs/summary 响应字段，组件不自数条数、不自算比率/平均值。
        <ul aria-label="概览指标" className="mt-3 flex flex-wrap gap-3 text-sm">
          <li className="rounded border border-line px-3 py-2">
            <p className="text-xs text-ink/70">累计提问</p>
            <p className="font-serif text-lg">{String(summary.queries_total)}</p>
          </li>
          <li className="rounded border border-line px-3 py-2">
            <p className="text-xs text-ink/70">近 {summary.window_days} 日</p>
            <p className="font-serif text-lg">{String(summary.queries_recent)}</p>
          </li>
          <li className="rounded border border-line px-3 py-2">
            <p className="text-xs text-ink/70">拒答率</p>
            <p className="font-serif text-lg">{formatRate(summary.refusal_rate)}</p>
          </li>
          <li className="rounded border border-line px-3 py-2">
            <p className="text-xs text-ink/70">平均命中</p>
            <p className="font-serif text-lg">{String(summary.avg_hit_count)}</p>
          </li>
        </ul>
      )}

      <label className="mt-4 block text-sm" htmlFor="logs-intent">按意图筛选</label>
      <select id="logs-intent" value={intent}
        onChange={(event) => setIntent(event.target.value)}
        className="mt-1 w-full max-w-xs rounded border border-line bg-paper px-2 py-1 text-sm">
        {INTENTS.map((value) => (
          <option key={value || "all"} value={value}>{value || "全部"}</option>
        ))}
      </select>

      <h2 className="mt-5 font-serif text-lg">高频拒答词（语料补缺清单）</h2>
      {refusals && refusals.items.length === 0 && (
        <p className="mt-1 text-sm text-ink/70">窗口内没有拒答记录。</p>
      )}
      {refusals && refusals.items.length > 0 && (
        <table className="mt-1 w-full border-collapse text-sm">
          {/* 窗口与 limit 取 RefusalList 回显（指针 §2/§3），不归一化查询原文（规格 §8）。 */}
          <caption className="text-left text-xs text-ink/70">
            按原文分组计数，不做归一化（错字/繁简归一属 E3 未决）· 近 {refusals.window_days} 日 · 前 {refusals.limit} 名
          </caption>
          <thead><tr className="border-b border-line">
            <th scope="col" className="py-1 pr-2 text-left">提问原文</th>
            <th scope="col" className="py-1 pr-2 text-left">次数</th>
            <th scope="col" className="py-1 pr-2 text-left">最高分</th></tr></thead>
          <tbody>{refusals.items.map((row) => (
            <tr key={row.query} className="border-b border-line/60 align-top">
              <td className="py-1 pr-2 break-all">{row.query}</td>
              <td className="py-1 pr-2">{row.count}</td>
              <td className="py-1 pr-2">{row.top_score_max ?? "—"}</td>
            </tr>
          ))}</tbody>
        </table>
      )}

      {/* limit 取明细响应回显值，不是写死的 50（指针 §2）。 */}
      <h2 className="mt-5 font-serif text-lg">最近 {list ? list.limit : REQUEST_LIMIT} 条</h2>
      {list && list.items.length === 0 && (
        <p className="mt-1 text-sm text-ink/70">本库暂无问答日志。</p>
      )}
      {list && list.items.length > 0 && (
        <table className="mt-1 w-full border-collapse text-sm">
          <caption className="text-left text-xs text-ink/70">共 {list.total} 条</caption>
          <thead><tr className="border-b border-line">
            {["时间", "意图", "拒答", "最高分", "命中", "提问"].map((header) => (
              <th key={header} scope="col" className="py-1 pr-2 text-left">{header}</th>))}
          </tr></thead>
          <tbody>{list.items.map((row) => (
            <tr key={row.id} className="border-b border-line/60 align-top">
              <td className="py-1 pr-2">{row.created_at ? new Date(row.created_at).toLocaleString("zh-CN") : "—"}</td>
              <td className="py-1 pr-2">{row.intent}</td>
              <td className="py-1 pr-2">{row.refused ? "是" : "否"}</td>
              <td className="py-1 pr-2">{row.top_score ?? "—"}</td>
              <td className="py-1 pr-2">{row.hit_count}</td>
              <td className="py-1 break-all">{row.query}</td>
            </tr>
          ))}</tbody>
        </table>
      )}
    </div>
  );
}
