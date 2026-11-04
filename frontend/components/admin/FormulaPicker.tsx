"use client";

import { SearchSuggest } from "@/components/library/SearchSuggest";
import type { SearchHit } from "@/lib/types";

/** `kinds` 必须是模块级常量：SearchSuggest 的 effect 依赖 `[query, kinds]`，JSX 里内联数组
 * 字面量每次渲染都是新引用 → 每次 `setHits` 都重跑 effect → 无限重发 /api/search。
 * M4 的四个库页同样是模块级常量（`app/formulas/page.tsx` 的 FILTERS）。 */
const FORMULA_KINDS = ["formula"];

/** 归并目标选择器：复用 M4 的联想组件，靠 `onPick`（可选参数）把命中项从跳转链接
 * 变成"写进表单"的按钮。检索在浏览器侧走 POST /api/search，不落库、不建方。
 *
 * `onCommit` 是 SearchSuggest 的必填 prop（M4 靠它把检索词写进 URL）。选择器里没有
 * "提交检索词"这个动作——归并目标必须落在一条具体命中上（后端要 `target_formula_id`），
 * 所以这里给显式 no-op，而不是把 M4 的签名改成可选去掩盖这件事。 */
export function FormulaPicker({ legend, onPick }: {
  legend: string;
  onPick: (hit: SearchHit) => void;
}) {
  return (
    <fieldset className="rounded border border-line p-2">
      <legend className="text-sm font-semibold">{legend}</legend>
      <SearchSuggest kinds={FORMULA_KINDS} onCommit={() => {}} onPick={onPick} />
      <p className="mt-1 text-xs text-ink/70">选中即写入归并目标；检索走 /api/search 精确通道。</p>
    </fieldset>
  );
}
