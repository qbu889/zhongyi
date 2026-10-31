import Link from "next/link";

import type { HerbDetail } from "@/lib/types";

import { DetailFrame } from "./DetailFrame";

export function HerbDetailView({ herb }: { herb: HerbDetail }) {
  return (
    <DetailFrame refType="herb" refId={herb.id} title={herb.name}
      summary={herb.alias.length ? `别名：${herb.alias.join("、")}` : null}>
      <dl className="grid grid-cols-[5rem_1fr] gap-x-3 gap-y-2 text-sm">
        <dt className="text-ink/70">性味</dt>
        <dd>
          {herb.flavor_state === "missing" ? "本经未载性味" : herb.flavor}
          {herb.taste_group && (
            <Link className="ml-2 text-cinnabar underline"
              href={`/herbs?taste_group=${encodeURIComponent(herb.taste_group)}`}>
              {herb.taste_group}味
            </Link>
          )}
          {herb.organ_group && (
            <Link className="ml-2 text-cinnabar underline"
              href={`/herbs?organ_group=${encodeURIComponent(herb.organ_group)}`}>
              归{herb.organ_group}
            </Link>
          )}
        </dd>
        <dt className="text-ink/70">功效</dt>
        <dd>{herb.effects ?? "—"}</dd>
        <dt className="text-ink/70">主治</dt>
        <dd>{herb.indications ?? "—"}</dd>
        <dt className="text-ink/70">用量</dt>
        <dd>{herb.dosage_note ?? "—"}</dd>
        <dt className="text-ink/70">炮制</dt>
        <dd>{herb.preparation ?? "—"}</dd>
        <dt className="text-ink/70">禁忌</dt>
        <dd>{herb.taboo ?? "—"}</dd>
      </dl>

      {herb.raw_note && (
        <section aria-labelledby="raw-note-heading">
          <h2 id="raw-note-heading" className="font-serif text-lg font-semibold">本经原注</h2>
          <blockquote className="mt-1 border-l-2 border-cinnabar pl-3 font-serif text-sm">
            {herb.raw_note}
          </blockquote>
        </section>
      )}

      <section aria-labelledby="formulas-heading">
        <h2 id="formulas-heading" className="font-serif text-lg font-semibold">
          含方（{herb.formula_count}）
        </h2>
        {herb.formulas.length === 0 ? (
          <p className="mt-1 text-sm text-ink/70">本库暂无含此药的方剂。</p>
        ) : (
          <ul className="mt-1 flex flex-wrap gap-3 text-sm">
            {herb.formulas.map((formula) => (
              <li key={formula.id}>
                <Link className="text-cinnabar underline" href={`/formulas/${formula.id}`}>
                  {formula.canonical_name}
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>
    </DetailFrame>
  );
}
