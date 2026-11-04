"use client";

import { useState } from "react";

import { useAdminReauth } from "@/components/admin/AdminShell";
import { FormulaPicker } from "@/components/admin/FormulaPicker";
import {
  adminErrorLabel, adminPost, isAdminUnauthorized, type DecisionResult, type PendingItem,
} from "@/lib/admin";
import type { SearchHit } from "@/lib/types";

/** 行内展开的草稿（指针 §4：不开弹窗，沿用 M4 侧栏确认风格）。三动作各自渲染一种表单；
 * 噪声那一路没有输入项，"展开面板 + 再按一次确认"就是它的二次确认。 */
type Draft = { mode: "merge" | "new" | "noise"; target?: SearchHit; name: string };

/** 指针 §1（R-M5-2 / §13-8 搬迁到此）：源文件与行号合成**一格**显示 `路径#行号`。
 * 行号缺失（`source_row_no` 可空）时只给路径——悬空的 `#` 是让维护者去找不存在的行号。 */
function sourcePath(item: PendingItem): string {
  return item.source_row_no === null || item.source_row_no === undefined
    ? item.doc
    : `${item.doc}#${item.source_row_no}`;
}

/** 表头 7 列：`源文件` 与 `行号` 合成一列后列数随之减一——`<th>` 数与 `<td>` 数必须相等，
 * 不等会被 axe 判死（R-M5-2 的原意）。 */
const HEADERS = ["候选方名", "源文件#行号", "原因", "建议母方", "置信度", "判定", "操作"];

export function PendingTable({ items, total, onChanged }: {
  items: PendingItem[];
  total: number;
  onChanged: () => void;
}) {
  const reprobe = useAdminReauth();
  const [draft, setDraft] = useState<{ id: number; value: Draft } | null>(null);
  const [message, setMessage] = useState("");
  /** 复制播报按行记 id：A 行的"已复制"不许串到 B 行的播报区。 */
  const [clipboard, setClipboard] = useState<{ id: number; text: string } | null>(null);

  async function submit(id: number, body: Record<string, unknown>) {
    setMessage("");
    try {
      await adminPost<DecisionResult>(`/api/admin/pending/${id}/decision`, body);
      setDraft(null);
      setMessage("已记录判定。");
      onChanged();
    } catch (error) {
      // 指针 §4：写动作（三动作全是 POST）的 401 = 会话过期，交回 AdminShell 重新探针；
      // 绝不进 adminErrorLabel——表里 admin_unauthorized 是「口令不正确」，对没输口令的人是误诊。
      if (isAdminUnauthorized(error)) { reprobe(); return; }
      setMessage(adminErrorLabel(error));
    }
  }

  /** 指针 §2（F-2 硬约束）：复制必须诚实——只在真成功时播报成功。 */
  async function copyPath(item: PendingItem) {
    const path = sourcePath(item);
    try {
      // 不许 `?.` 把缺失吞掉：非安全上下文/jsdom 下访问 navigator.clipboard 会抛 TypeError，
      // 正好落进下面的 catch 走失败分支。用可选链的话"什么都没做"会看起来像成功。
      await navigator.clipboard.writeText(path);
      setClipboard({ id: item.id, text: "已复制源路径" });
    } catch {
      // 闭集文案，逐字：它同时给出降级方案（select-all 让整段路径可选中，手动复制即可）。
      setClipboard({ id: item.id, text: "复制失败，请手动选择路径" });
    }
  }

  return (
    <div data-testid="pending-table">
      <p className="text-sm text-ink/70">
        共 {total} 条候选；判定只登记在本队列，不改写语料原文。
        归并会另写一条人工归并别名，形状见行内说明。
      </p>
      <table className="mt-2 w-full border-collapse text-sm">
        <caption className="text-left text-xs text-ink/70">待确认方名（D7 候选队列）</caption>
        <thead><tr className="border-b border-line">
          {HEADERS.map((header) => (
            <th key={header} scope="col" className="py-1 pr-2 text-left">{header}</th>
          ))}
        </tr></thead>
        <tbody>
          {items.map((row) => {
            const open = draft?.id === row.id ? draft.value : null;
            const path = sourcePath(row);
            return (
              <tr key={row.id} className="border-b border-line/60 align-top">
                <td className="py-1 pr-2">{row.raw_name}</td>
                {/* 合成格：可整段选中（select-all）+ 复制按钮；**不是链接**——浏览器打不开
                  * 服务器本地文件、语料 0600，做成跳转是超出证据的承诺（§13-8）。 */}
                <td className="py-1 pr-2">
                  <span className="select-all break-all">{path}</span>
                  <button type="button" className="ml-2 text-cinnabar underline"
                    aria-label="复制源文件路径" onClick={() => void copyPath(row)}>复制源文件路径</button>
                  <span role="status" aria-live="polite" className="ml-2 text-xs text-ink/70">
                    {clipboard?.id === row.id ? clipboard.text : ""}
                  </span>
                </td>
                <td className="py-1 pr-2">{row.reason ?? "—"}</td>
                <td className="py-1 pr-2">{row.suggested_parent ?? "—"}</td>
                <td className="py-1 pr-2">{row.confidence ?? "—"}</td>
                <td className="py-1 pr-2">{row.decision}{row.decided_name ? `：${row.decided_name}` : ""}</td>
                <td className="py-1">
                  <div className="flex flex-wrap gap-2">
                    <button type="button" className="text-cinnabar underline"
                      onClick={() => setDraft({ id: row.id, value: { mode: "merge", name: "" } })}>
                      归并到既有方</button>
                    <button type="button" className="text-cinnabar underline"
                      onClick={() => setDraft({ id: row.id, value: { mode: "new", name: "" } })}>
                      确认为独立方</button>
                    <button type="button" className="text-cinnabar underline"
                      onClick={() => setDraft({ id: row.id, value: { mode: "noise", name: "" } })}>
                      判为噪声</button>
                  </div>
                  {open?.mode === "merge" && (
                    <div className="mt-2 space-y-2">
                      <FormulaPicker legend="选择目标方"
                        onPick={(hit) => setDraft({ id: row.id, value: { ...open, target: hit } })} />
                      <p className="text-xs text-ink/70">
                        {open.target ? `目标：${open.target.title}` : "请先选择目标方"}
                      </p>
                      {/* 指针 §5 的两条后端事实，写在动作旁边而不是页脚：归并按 (name, doc) 移动
                        * 别名（admin.py:288-294），M5-A 没有撤销端点，所以这里不提供也**不暗示**按行撤销。 */}
                      <p className="text-xs text-ink/70">
                        归并立即写入 formula_alias（kind=人工归并），精确通道随之生效。
                        归并按「候选方名 + 源文件」移动人工归并别名：同名同文件的另一条候选行会被这次判定改写。
                      </p>
                      <button type="button" disabled={!open.target}
                        className="rounded bg-cinnabar px-2 py-1 text-xs text-paper disabled:opacity-50"
                        onClick={() => submit(row.id, { action: "merged", target_formula_id: open.target?.ref_id })}>
                        确认归并</button>
                    </div>
                  )}
                  {open?.mode === "new" && (
                    <div className="mt-2 space-y-1">
                      {/* 闭集文案，逐字（规格 §6：confirmed_new 只写 decided_name，不建 formula 行）。 */}
                      <p className="text-xs text-cinnabar">仅登记，不建方：ETL 读取判定结果建方属下一轮范围。</p>
                      <label className="block text-xs" htmlFor={`name-${row.id}`}>规范方名</label>
                      <input id={`name-${row.id}`} value={open.name}
                        className="w-40 rounded border border-line px-2 py-1 text-sm"
                        onChange={(event) => setDraft({ id: row.id, value: { ...open, name: event.target.value } })} />
                      <button type="button" disabled={!open.name.trim()}
                        className="block rounded bg-cinnabar px-2 py-1 text-xs text-paper disabled:opacity-50"
                        onClick={() => submit(row.id, { action: "confirmed_new", name: open.name.trim() })}>
                        登记判定</button>
                    </div>
                  )}
                  {open?.mode === "noise" && (
                    <div className="mt-2 space-y-1 text-xs">
                      {/* 展开面板本身是第一击，"确认判噪声"是第二击——两击之间不发请求。 */}
                      <p className="text-ink/70">判噪声只把这一行标记为 noise：不删语料、不建方、不建别名。</p>
                      <button type="button" className="rounded border border-cinnabar px-2 py-1 text-cinnabar"
                        onClick={() => submit(row.id, { action: "noise" })}>确认判噪声</button>
                    </div>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p role="status" aria-live="polite" className="mt-2 min-h-5 text-sm text-cinnabar">{message}</p>
    </div>
  );
}
