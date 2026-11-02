import Link from "next/link";

import type { AcupointDetail } from "@/lib/types";

export function AcupointCard({ point }: { point: AcupointDetail }) {
  return (
    <article data-testid="acupoint-card" className="mt-3 rounded border border-line p-3 text-sm">
      <h4 className="font-serif text-base font-semibold">
        {point.name}
        {point.role && <span className="ml-2 rounded bg-cinnabar/10 px-1 text-xs text-cinnabar">{point.role}</span>}
      </h4>
      <p className="mt-1 text-ink/70">{point.meridian ?? "经络未载"}</p>
      {point.location && <p className="mt-1">定位：{point.location}</p>}
      {point.actions && <p className="mt-1">主治：{point.actions}</p>}
      <Link className="mt-2 inline-block text-xs text-cinnabar underline" href={`/acupoints/${point.id}`}>
        在库详情页打开
      </Link>
    </article>
  );
}
