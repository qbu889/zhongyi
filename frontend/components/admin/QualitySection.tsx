"use client";

import { adminCsvHref } from "@/lib/admin";

type Cell = string | number | null;

/** 质量报告的「一节」：一张 `<table>` + `<caption>`（caption 逐字为节标题——指针 §4，
 * 可访问名要对得上用例里的 `toHaveAccessibleName`）。可导出的四节各带一条导出链接，
 * `href` 一律走 `adminCsvHref(list)`，不手写 `?list=`。不可导出的三节不出现该链接（用例断缺席）。
 *
 * R-M5-19（规格 §4.1 的分工）：③ 屏上渲染的是 `parse_failures` 按原因计数表，导出的却是
 * 可下钻的明细行（`list=parse_failure_details`）。下载内容与屏上表格不一致时，链接文案
 * 不许说谎——该节 `exportLabel` 用逐字「导出明细 CSV」（其余节默认「导出 CSV」），并配一行
 * `hint` 说明「屏上按原因计数，导出给到可下钻的明细行」。
 *
 * R-M5-20（修复轮 1，F-1）：本组件此前自带的 `pathColumn`「路径#行号 + 复制按钮」合成格
 * 已随 ③ 改回计数表而失去屏上调用者，整段删除——R-M5-2 与 §13-8 的需求不消失，
 * 改由 T13（`/admin/pending` 明细行）承载。
 *
 * F-6（评审 Minor 13）：`hint` 用 `aria-describedby` 关联到本节的 `<table>`——读表格的
 * 辅助技术用户要同时听到「屏与下载形状不同」这句分工说明；空态下表格不存在，
 * 该说明行也不渲染（描述不存在的东西是谎）。 */
export function QualitySection({ id, title, headers, rows, exportList, exportLabel, hint }: {
  id: string;
  title: string;
  headers: string[];
  rows: Cell[][];
  exportList?: string;
  /** 导出链接文案；默认「导出 CSV」。屏上与下载内容不同形时（R-M5-19 的 ③）必须显式给。 */
  exportLabel?: string;
  /** 该节的一行说明（如 ③ 的「屏上按原因计数，导出给到可下钻的明细行。」）。
   * 非空态时经 `aria-describedby` 指给表格；空态不渲染。 */
  hint?: string;
}) {
  const hintId = `q-${id}-hint`;

  return (
    <section className="mt-6" aria-labelledby={`q-${id}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id={`q-${id}`} className="font-serif text-lg">{title}（{rows.length} 行）</h2>
        {exportList && (
          <a className="text-sm text-cinnabar underline" href={adminCsvHref(exportList)}
            download={`${exportList}.csv`}>{exportLabel ?? "导出 CSV"}</a>
        )}
      </div>
      {rows.length === 0 ? (
        // 空态与失败态是两条独立面（指针 §6）：这里是诚实的「本库暂无」，绝不复用失败文案。
        // F-6：空态下不渲染 hint——表格不存在，分工说明无处可附。
        <p className="mt-2 text-sm text-ink/70">本库暂无记录。</p>
      ) : (
        <>
          {/* R-M5-19：③ 用这一行说清屏上表格与下载文件不是同一形状（逐字文案被用例钉住）。
              F-6：id 供表格 aria-describedby 引用。 */}
          {hint && <p id={hintId} className="mt-2 text-xs text-ink/70">{hint}</p>}
          <table className="mt-2 w-full border-collapse text-sm"
            aria-describedby={hint ? hintId : undefined}>
            <caption className="text-left text-xs text-ink/70">{title}</caption>
            <thead><tr className="border-b border-line">
              {headers.map((header) => (
                <th key={header} scope="col" className="py-1 pr-2 text-left">{header}</th>
              ))}
            </tr></thead>
            <tbody>
              {rows.map((row, index) => (
                <tr key={index} className="border-b border-line/60 align-top">
                  {row.map((cell, cellIndex) => (
                    <td key={cellIndex} className="py-1 pr-2">{cell ?? "—"}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </section>
  );
}
