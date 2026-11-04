"use client";

import { Fragment, useRef, useState } from "react";

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
  /** 指针 §9:123「写操作进行中」状态面：POST 在途时该行的动作按钮与提交按钮一律禁用，
   * `busy` 驱动禁用与原因文案；`busyRef` 是同步护栏——它挡住同一渲染周期内的第二次点击，
   * 不依赖 React 把 `disabled` 落到 DOM 之后才生效（`disabled` 只在重渲染后可见，双击会抢在前面）。
   * 与仓库既有做法同一形状（`LoginCard` 的 `busy`、`ReindexPanel` 的 `phase === "running"`），非新发明。 */
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);

  async function submit(id: number, body: Record<string, unknown>) {
    if (busyRef.current) return;   // 双击/竞态护栏：在途期间不再发第二次写。
    busyRef.current = true;
    setBusy(true);
    // 指针 §9:123 + F-2 第 2 点：清空状态行只是收起上一轮的播报，**不**是一次播报；
    // 在途的"进行中"状态面由下面的原因文案承担，进入终态才 setMessage 播报结果。
    setMessage("");
    try {
      const result = await adminPost<DecisionResult>(`/api/admin/pending/${id}/decision`, body);
      setDraft(null);
      // 规格 §14-5：`merged` 分支读 `alias_created`（后端幂等分支 admin.py:304-310 回 false）。
      // false → 判定**已记录**、只是 alias **未新增**（该别名已存在），不能让维护者以为整次操作失败；
      // true 或其余动作 → 保持原播报。闭集逐字：`该别名已存在`。
      setMessage(body.action === "merged" && result.alias_created === false
        ? "判定已记录，该别名已存在。"
        : "已记录判定。");
      onChanged();
    } catch (error) {
      // 指针 §4：写动作（三动作全是 POST）的 401 = 会话过期，交回 AdminShell 重新探针；
      // 绝不进 adminErrorLabel——表里 admin_unauthorized 是「口令不正确」，对没输口令的人是误诊。
      if (isAdminUnauthorized(error)) { reprobe(); return; }
      setMessage(adminErrorLabel(error));
    } finally {
      busyRef.current = false;
      setBusy(false);
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
            // 规格 §9「已判定行默认展开留痕」：已判定 = decision 不是 pending。后端写入判定时
            // 必写 decided_by（DECIDED_BY，admin.py:305）与 decided_at（func.now()，:309），
            // 未判定（pending）两值皆 null——所以按 decision 判定，pending 行不留任何空壳。
            const decided = row.decision !== "pending";
            return (
              <Fragment key={row.id}>
                <tr className="border-b border-line/60 align-top">
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
                      <button type="button" className="text-cinnabar underline" disabled={busy}
                        onClick={() => setDraft({ id: row.id, value: { mode: "merge", name: "" } })}>
                        归并到既有方</button>
                      <button type="button" className="text-cinnabar underline" disabled={busy}
                        onClick={() => setDraft({ id: row.id, value: { mode: "new", name: "" } })}>
                        确认为独立方</button>
                      <button type="button" className="text-cinnabar underline" disabled={busy}
                        onClick={() => setDraft({ id: row.id, value: { mode: "noise", name: "" } })}>
                        判为噪声</button>
                    </div>
                    {/* F-2（§9:123）：在途状态面 = 禁用 + 原因。展开面板即被提交的那一行的面板，
                      * 所以在途期间这段一定在屏上，逐字说明按钮为何禁用。 */}
                    {busy && open && (
                      <p role="status" aria-live="polite" className="mt-1 text-xs text-ink/70">
                        判定提交中，请稍候…（提交进行中，按钮已禁用，请勿重复点击）
                      </p>
                    )}
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
                        <button type="button" disabled={!open.target || busy}
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
                        <button type="button" disabled={!open.name.trim() || busy}
                          className="block rounded bg-cinnabar px-2 py-1 text-xs text-paper disabled:opacity-50"
                          onClick={() => submit(row.id, { action: "confirmed_new", name: open.name.trim() })}>
                          登记判定</button>
                      </div>
                    )}
                    {open?.mode === "noise" && (
                      <div className="mt-2 space-y-1 text-xs">
                        {/* 展开面板本身是第一击，"确认判噪声"是第二击——两击之间不发请求。 */}
                        <p className="text-ink/70">判噪声只把这一行标记为 noise：不删语料、不建方、不建别名。</p>
                        <button type="button" disabled={busy}
                          className="rounded border border-cinnabar px-2 py-1 text-cinnabar disabled:opacity-50"
                          onClick={() => submit(row.id, { action: "noise" })}>确认判噪声</button>
                      </div>
                    )}
                  </td>
                </tr>
                {/* 规格 §9 留痕：已判定行在下一行补 `decided_by` 与 `decided_at`（次级行，不开弹窗）。
                  * 时间沿用 M4 既有本地化口径 `new Date(…).toLocaleString("zh-CN")`
                  * （LogsDashboard.tsx:135 / SessionSidebar.tsx:83），不新造格式化函数。
                  * 未判定行没有这一行——不显示 decided_by/decided_at 的空壳。 */}
                {decided && (
                  <tr className="border-b border-line/60 align-top">
                    <td className="py-1 pr-2 text-xs text-ink/70" colSpan={HEADERS.length}>
                      判定留痕：<span>{row.decided_by ?? "—"}</span> · <span>{row.decided_at ? new Date(row.decided_at).toLocaleString("zh-CN") : "—"}</span>
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
      <p role="status" aria-live="polite" className="mt-2 min-h-5 text-sm text-cinnabar">{message}</p>
    </div>
  );
}
