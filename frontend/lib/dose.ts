export const DOSE_STATE_LABELS: Record<string, string> = {
  approx: "近似",
  count_only: "仅计数",
  unknown_unit: "未换算",
  absent: "未记载",
};

export function doseCell(item: { dose_g: number | null; dose_state: string }): {
  text: string;
  tone: "exact" | "approx" | "none";
} {
  if (item.dose_g !== null && item.dose_state === "exact") {
    return { text: `${item.dose_g}g`, tone: "exact" };
  }
  if (item.dose_g !== null && item.dose_state === "approx") {
    return { text: `~${item.dose_g}g`, tone: "approx" };
  }
  return { text: "—", tone: "none" };
}
