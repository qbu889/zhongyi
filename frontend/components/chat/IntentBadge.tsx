const INTENT_LABELS: Record<string, string> = {
  A: "辨证", B: "方剂", C: "中药", D: "取穴", E: "医案", F: "综合",
};

export function IntentBadge({ intent }: { intent: string }) {
  if (!intent) return null;
  return (
    <span data-testid="intent-badge"
      className="rounded-full border border-cinnabar/40 bg-cinnabar/10 px-2 py-0.5 text-xs text-cinnabar">
      {intent} {INTENT_LABELS[intent] ?? "综合"}
    </span>
  );
}
