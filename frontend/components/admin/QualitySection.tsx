"use client";

import { useState } from "react";

import { adminCsvHref } from "@/lib/admin";

type Cell = string | number | null;

/** 质量报告的「一节」：一张 `<table>` + `<caption>`（caption 逐字为节标题——指针 §4，
 * 可访问名要对得上用例里的 `toHaveAccessibleName`）。可导出的四节各带一条 `导出 CSV` 链接，
 * `href` 一律走 `adminCsvHref(list)`，不手写 `?list=`。不可导出的三节不出现该链接（用例断缺席）。
 *
 * `pathColumn`（R-M5-2）：把该列的「源文件」与其右邻的「行号」合成**一格**显示为
 * `路径#行号`，表头保持原列数——合并后右邻那格不再单独出格，故 `<th>` 数与 `<td>` 数恒相等
 * （不等会被 axe 判死）。该格可复制、但**不是链接**：§13-8 已把「跳源文件」降级为
 * 「显示路径 + 行号 + 可复制」（浏览器打不开服务器本地文件、语料 0600 权限）。 */
export function QualitySection({ id, title, headers, rows, exportList, pathColumn }: {
  id: string;
  title: string;
  headers: string[];
  rows: Cell[][];
  exportList?: string;
  /** 该列渲染成「路径#行号 + 复制按钮」；不新增列，表头与单元格数必须相等。 */
  pathColumn?: number;
}) {
  const [copied, setCopied] = useState("");

  // 合并路径格：复制/显示的都是「路径本身 + #行号」，不含 #行号之外的装饰（指针 §4）。
  const mergedPath = (row: Cell[]): string => {
    const base = String(row[pathColumn as number] ?? "");
    const line = row[(pathColumn as number) + 1];
    return line === null || line === undefined || line === "" ? base : `${base}#${line}`;
  };

  return (
    <section className="mt-6" aria-labelledby={`q-${id}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id={`q-${id}`} className="font-serif text-lg">{title}（{rows.length} 行）</h2>
        {exportList && (
          <a className="text-sm text-cinnabar underline" href={adminCsvHref(exportList)}
            download={`${exportList}.csv`}>导出 CSV</a>
        )}
      </div>
      {rows.length === 0 ? (
        // 空态与失败态是两条独立面（指针 §6）：这里是诚实的「本库暂无」，绝不复用失败文案。
        <p className="mt-2 text-sm text-ink/70">本库暂无记录。</p>
      ) : (
        <table className="mt-2 w-full border-collapse text-sm">
          <caption className="text-left text-xs text-ink/70">{title}</caption>
          <thead><tr className="border-b border-line">
            {headers.map((header) => (
              <th key={header} scope="col" className="py-1 pr-2 text-left">{header}</th>
            ))}
          </tr></thead>
          <tbody>
            {rows.map((row, index) => (
              <tr key={index} className="border-b border-line/60 align-top">
                {row.map((cell, cellIndex) => {
                  if (pathColumn !== undefined && cellIndex === pathColumn) {
                    const path = mergedPath(row);
                    return (
                      <td key={cellIndex} className="py-1 pr-2">
                        <span className="select-all break-all">{path}</span>
                        <button type="button" className="ml-2 text-cinnabar underline"
                          aria-label="复制源文件路径"
                          onClick={async () => {
                            await navigator.clipboard?.writeText(path);
                            setCopied("已复制源路径");
                          }}>复制源文件路径</button>
                      </td>
                    );
                  }
                  // 行号已被并进「源文件#行号」那一格，不再单独出格——列数与表头始终相等。
                  if (pathColumn !== undefined && cellIndex === pathColumn + 1) return null;
                  return <td key={cellIndex} className="py-1 pr-2">{cell ?? "—"}</td>;
                })}
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <p role="status" aria-live="polite" className="min-h-5 text-xs text-ink/70">{copied}</p>
    </section>
  );
}
