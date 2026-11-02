import Link from "next/link";

import type { HerbDetail } from "@/lib/types";

export function HerbCard({ herb }: { herb: HerbDetail }) {
  return (
    <article data-testid="herb-card" className="mt-3 rounded border border-line p-3 text-sm">
      <h4 className="font-serif text-base font-semibold">{herb.name}</h4>
      <p className="mt-1">
        性味：{herb.flavor_state === "missing" ? "本经未载性味" : herb.flavor}
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
      </p>
      {herb.effects && <p className="mt-1">功效：{herb.effects}</p>}
      {herb.indications && <p className="mt-1">主治：{herb.indications}</p>}
      {herb.taboo && <p className="mt-1">禁忌：{herb.taboo}</p>}
      <Link className="mt-2 inline-block text-xs text-cinnabar underline" href={`/herbs/${herb.id}`}>
        在库详情页打开
      </Link>
    </article>
  );
}
