"use client";

import Link from "next/link";
import { useState } from "react";

import { DOSE_STATE_LABELS, doseCell } from "@/lib/dose";
import type { FormulaDetail, FormulaVariant } from "@/lib/types";

import { DoseToggle, type DoseMode } from "./DoseToggle";

const PAIR_DIFF_LABELS: Record<string, string> = {
  missing_in_gram: "仅古制有",
  missing_in_ancient: "仅克数本有",
};

export function VariantTable({ variant, mode }: { variant: FormulaVariant; mode: DoseMode }) {
  return (
    <div className="mt-3 overflow-x-auto">
      <p className="text-xs text-ink/70">{variant.source_doc}</p>
      <table className="w-full border-collapse text-left text-sm">
        <thead>
          <tr className="border-b border-line">
            <th className="py-1 pr-2">药味</th>
            {mode === "gram" && <th className="py-1 pr-2">克数</th>}
            <th className="py-1 pr-2">古制原量</th>
            <th className="py-1">换算留痕</th>
          </tr>
        </thead>
        <tbody>
          {variant.items.map((item, index) => {
            const cell = doseCell(item);
            return (
              <tr key={`${variant.id}-${index}`} className="border-b border-line/60">
                <td className="py-1 pr-2">{item.herb_text}</td>
                {mode === "gram" && (
                  <td data-testid="dose-cell" className="py-1 pr-2"
                    title={item.conversion_note ?? DOSE_STATE_LABELS[item.dose_state] ?? item.dose_state}>
                    <span className={cell.tone === "approx" ? "text-cinnabar" : undefined}>
                      {cell.text}
                    </span>
                    {cell.tone === "none" && (
                      <span className="ml-1 text-xs text-ink/70">
                        （{DOSE_STATE_LABELS[item.dose_state] ?? item.dose_state}）
                      </span>
                    )}
                  </td>
                )}
                <td className="py-1 pr-2">{item.dose_text ?? "—"}</td>
                <td className="py-1 text-xs text-ink/70">{item.conversion_note ?? ""}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function FormulaCard({ formula }: { formula: FormulaDetail }) {
  const [mode, setMode] = useState<DoseMode>("gram");
  const pair = formula.pairs[0];
  const diff = (pair?.herb_diff ?? {}) as Record<string, string[]>;
  const diffEntries = Object.entries(diff).filter(([, herbs]) => herbs.length > 0);
  const badge = !pair
    ? { text: "未交叉校验", tone: "text-azurite" }
    : diffEntries.length > 0
      ? { text: "变体有差异", tone: "text-cinnabar" }
      : { text: "✓ 变体一致", tone: "text-ink/70" };

  return (
    <article data-testid="formula-card" className="mt-3 rounded border border-line bg-paper p-3">
      <header className="flex flex-wrap items-center justify-between gap-2">
        <h4 className="font-serif text-base font-semibold">{formula.canonical_name}</h4>
        <span data-testid="variant-badge" className={badge.tone}>{badge.text}</span>
      </header>
      {formula.dose_complete === false && (
        <p className="mt-1 text-xs text-cinnabar">本方剂量不完全可执行</p>
      )}
      {pair && diffEntries.length > 0 && (
        <details open data-testid="pair-diff"
          className="mt-1 rounded border border-cinnabar/40 bg-cinnabar/5 p-2 text-xs">
          <summary className="cursor-pointer text-cinnabar">
            交叉校验差异（{pair.variant_a} ↔ {pair.variant_b}）
          </summary>
          <ul className="mt-1 list-disc pl-5">
            {diffEntries.map(([key, herbs]) => (
              <li key={key}>
                {PAIR_DIFF_LABELS[key] ?? key}：{herbs.join("、")}
              </li>
            ))}
          </ul>
        </details>
      )}
      {formula.lineage.parent && (
        <p className="mt-1 text-xs">
          母方：
          <Link className="text-cinnabar underline" href={`/formulas/${formula.lineage.parent.id}`}>
            {formula.lineage.parent.canonical_name}
          </Link>
        </p>
      )}
      <div className="mt-2"><DoseToggle mode={mode} onChange={setMode} /></div>
      {formula.variants.map((variant) => (
        <VariantTable key={variant.id} variant={variant} mode={mode} />
      ))}
      {mode === "ancient" && (
        <p className="mt-2 text-xs text-ink/70">换算标准：1两≈15g</p>
      )}
      <footer className="mt-3 flex flex-wrap items-center justify-between gap-2 text-xs text-ink/70">
        <span>
          出处：
          {formula.evidence.map((item) =>
            `${item.source_doc}${item.six_jing ? `·${item.six_jing}` : ""}${item.clause_no ? `·${item.clause_no}` : ""}`,
          ).join("；")}
        </span>
        <Link className="text-cinnabar underline" href={`/formulas/${formula.id}`}>
          在库详情页打开
        </Link>
      </footer>
    </article>
  );
}
