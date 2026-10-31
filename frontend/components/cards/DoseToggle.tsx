"use client";

import * as Switch from "@radix-ui/react-switch";

export type DoseMode = "gram" | "ancient";

export function DoseToggle({ mode, onChange }: { mode: DoseMode; onChange: (mode: DoseMode) => void }) {
  return (
    <label className="flex items-center gap-2 text-sm">
      古制
      <Switch.Root
        checked={mode === "ancient"}
        aria-label="古制"
        onCheckedChange={(checked) => onChange(checked ? "ancient" : "gram")}
        className="relative h-5 w-9 rounded-full bg-line data-[state=checked]:bg-cinnabar"
      >
        <Switch.Thumb className="block h-4 w-4 translate-x-0.5 rounded-full bg-paper transition-transform data-[state=checked]:translate-x-4" />
      </Switch.Root>
    </label>
  );
}
