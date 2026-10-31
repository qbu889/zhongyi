"use client";

import Link from "next/link";
import { useState } from "react";

import { DoseToggle, type DoseMode } from "@/components/cards/DoseToggle";
import { VariantTable } from "@/components/cards/FormulaCard";
import { DOSE_STATE_LABELS, doseCell } from "@/lib/dose";
import type { FormulaDetail } from "@/lib/types";

import { DetailFrame } from "./DetailFrame";

const STATUS_LABELS: Record<string, string> = {
  confirmed: "身份已确认",
  candidate: "身份待确认",
  split_parent: "拆分母方",
};

const KIND_LABELS: Record<string, string> = {
  single: "单方",
  modified: "加减方",
  pair: "合方",
};

export function FormulaDetailView({ formula }: { formula: FormulaDetail }) {
  const [mode, setMode] = useState<DoseMode>("gram");
  const summary = `${STATUS_LABELS[formula.status] ?? formula.status} · ${
    KIND_LABELS[formula.kind] ?? formula.kind}`;
  const pair = formula.pairs[0];
  const diffCount = pair
    ? Object.values((pair.herb_diff ?? {}) as Record<string, string[]>)
        .filter((herbs) => herbs.length > 0).length
    : 0;
  const badge = !pair
    ? { text: "未交叉校验", tone: "text-azurite" }
    : diffCount > 0
      ? { text: "变体有差异", tone: "text-cinnabar" }
      : { text: "✓ 变体一致", tone: "text-ink/70" };

  return (
    <DetailFrame refType="formula" refId={formula.id} title={formula.canonical_name}
      summary={summary}>
      {formula.aliases.length > 0 && (
        <p className="text-sm text-ink/70">
          别名：
          {formula.aliases.map((alias) => `${alias.name}（${alias.doc}·${alias.kind}）`).join("、")}
        </p>
      )}
      {formula.note && <p className="text-sm text-ink/70">{formula.note}</p>}
      {formula.dose_complete === false && (
        <p className="text-sm text-cinnabar">本方剂量不完全可执行</p>
      )}

      <section aria-labelledby="variants-heading">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 id="variants-heading" className="font-serif text-lg font-semibold">剂量变体</h2>
          <div className="flex items-center gap-3">
            <span data-testid="variant-badge" className={badge.tone}>{badge.text}</span>
            <DoseToggle mode={mode} onChange={setMode} />
          </div>
        </div>
        {formula.kind === "pair" && (
          <p className="mt-1 text-xs text-ink/70">合方不参与变体剂量对照；下列为合方行自身组成。</p>
        )}
        {formula.variants.length === 0 && (
          <p className="mt-1 text-sm text-ink/70">本库未存该方组成。</p>
        )}
        {formula.variants.map((variant) => (
          <VariantTable key={variant.id} variant={variant} mode={mode} />
        ))}
      </section>

      <section aria-labelledby="lineage-heading">
        <h2 id="lineage-heading" className="font-serif text-lg font-semibold">加减方谱系</h2>
        <p className="mt-1 text-sm">
          母方：
          {formula.lineage.parent ? (
            <Link className="text-cinnabar underline" href={`/formulas/${formula.lineage.parent.id}`}>
              {formula.lineage.parent.canonical_name}
            </Link>
          ) : "无（本方为谱系起点）"}
        </p>
        <p className="mt-1 text-sm">
          子方：
          {formula.lineage.children.length > 0
            ? formula.lineage.children.map((child, index) => (
                <span key={child.id}>
                  {index > 0 && "、"}
                  <Link className="text-cinnabar underline" href={`/formulas/${child.id}`}>
                    {child.canonical_name}
                  </Link>
                </span>
              ))
            : "无"}
        </p>
      </section>

      <section aria-labelledby="pairs-heading">
        <h2 id="pairs-heading" className="font-serif text-lg font-semibold">变体交叉校验</h2>
        {formula.pairs.length === 0 && (
          <p className="mt-1 text-sm text-ink/70">暂无配对结果（未交叉校验）。</p>
        )}
        {formula.pairs.map((pair, index) => {
          const diff = (pair.herb_diff ?? {}) as {
            missing_in_gram?: string[];
            missing_in_ancient?: string[];
          };
          const deviations = Object.entries(
            (pair.dose_dev ?? {}) as Record<string, {
              ancient_g?: number;
              gram_g?: number;
              deviation_pct?: number;
            }>,
          );
          return (
            <div key={`${pair.variant_a}-${pair.variant_b}-${index}`}
              className="mt-2 rounded border border-line p-3 text-sm">
              <p className="text-xs text-ink/70">
                {pair.variant_a_source ?? `变体 ${pair.variant_a}`}
                {" ↔ "}
                {pair.variant_b_source ?? `变体 ${pair.variant_b}`}
                {pair.score !== null && `（相似度 ${pair.score.toFixed(2)}）`}
              </p>
              <p className="mt-1">
                仅古制有：{diff.missing_in_gram?.length ? diff.missing_in_gram.join("、") : "无"}
              </p>
              <p className="mt-1">
                仅克数本有：{diff.missing_in_ancient?.length
                  ? diff.missing_in_ancient.join("、")
                  : "无"}
              </p>
              {deviations.length > 0 && (
                <ul className="mt-1 list-disc pl-5">
                  {deviations.map(([item, dev]) => (
                    <li key={item}>
                      {item}：古制 {dev.ancient_g ?? "—"}g / 克数本 {dev.gram_g ?? "—"}g，
                      偏差 {dev.deviation_pct ?? "—"}%
                    </li>
                  ))}
                </ul>
              )}
            </div>
          );
        })}
      </section>

      {formula.components.length > 0 && (
        <section aria-labelledby="components-heading">
          <h2 id="components-heading" className="font-serif text-lg font-semibold">合方成分</h2>
          {formula.components.map((component) => (
            <div key={component.id} className="mt-2 rounded border border-line p-3 text-sm">
              <Link className="text-cinnabar underline" href={`/formulas/${component.id}`}>
                {component.canonical_name}
              </Link>
              <ul className="mt-1 list-disc pl-5">
                {component.items.map((item, index) => {
                  const cell = doseCell(item);
                  return (
                    <li key={`${component.id}-${index}`}>
                      {item.herb_text}
                      {mode === "gram" ? cell.text : item.dose_text ?? "—"}
                      {mode === "gram" && cell.tone === "none" && (
                        <span className="ml-1 text-xs text-ink/70">
                          （{DOSE_STATE_LABELS[item.dose_state] ?? item.dose_state}）
                        </span>
                      )}
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
        </section>
      )}

      <section aria-labelledby="evidence-heading">
        <h2 id="evidence-heading" className="font-serif text-lg font-semibold">出处原文</h2>
        {formula.evidence.length === 0 && <p className="mt-1 text-sm text-ink/70">暂无出处原文。</p>}
        {formula.evidence.map((item) => (
          <blockquote key={item.id}
            className="mt-2 border-l-2 border-cinnabar pl-3 font-serif text-sm">
            <p className="text-xs text-ink/70">
              {[item.source_doc, item.six_jing, item.clause_no].filter(Boolean).join("·")}
            </p>
            <p className="mt-1 whitespace-pre-wrap">{item.original_text ?? "—"}</p>
          </blockquote>
        ))}
      </section>

      {formula.cases.length > 0 && (
        <section aria-labelledby="cases-heading">
          <h2 id="cases-heading" className="font-serif text-lg font-semibold">相关医案</h2>
          <ul className="mt-1 text-sm">
            {formula.cases.map((item) => (
              <li key={item.id}>
                <Link className="text-cinnabar underline" href={`/cases/${item.id}`}>{item.no}</Link>
                {item.category && <span className="ml-1 text-ink/70">{item.category}</span>}
              </li>
            ))}
          </ul>
        </section>
      )}
    </DetailFrame>
  );
}
