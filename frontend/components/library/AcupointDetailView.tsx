import type { AcupointDetail } from "@/lib/types";

import { DetailFrame } from "./DetailFrame";

export function AcupointDetailView({ point }: { point: AcupointDetail }) {
  return (
    <DetailFrame refType="acupoint" refId={point.id} title={point.name}
      summary={point.meridian ?? "经络未载"}>
      <dl className="grid grid-cols-[5rem_1fr] gap-x-3 gap-y-2 text-sm">
        <dt className="text-ink/70">角色</dt>
        <dd>{point.role ?? "未标注"}</dd>
        <dt className="text-ink/70">定位</dt>
        <dd>{point.location ?? "—"}</dd>
        <dt className="text-ink/70">主治</dt>
        <dd>{point.actions ?? "—"}</dd>
        <dt className="text-ink/70">症状数</dt>
        <dd>{point.symptom_count}</dd>
      </dl>

      <section aria-labelledby="symptoms-heading">
        <h2 id="symptoms-heading" className="font-serif text-lg font-semibold">按症取穴记录</h2>
        {point.symptoms.length === 0 ? (
          <p className="mt-1 text-sm text-ink/70">本库暂无按症取穴记录。</p>
        ) : (
          <ul className="mt-1 list-disc pl-5 text-sm">
            {point.symptoms.map((symptom, index) => (
              <li key={`${symptom.symptom}-${index}`}>
                {symptom.symptom}
                {symptom.source_doc && (
                  <span className="ml-1 text-xs text-ink/70">{symptom.source_doc}</span>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
    </DetailFrame>
  );
}
