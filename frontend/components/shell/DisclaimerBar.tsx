import { GLOBAL_DISCLAIMER } from "@/lib/constants";

export function DisclaimerBar() {
  return (
    <footer
      data-testid="disclaimer-global"
      className="fixed inset-x-0 bottom-0 z-20 border-t border-line bg-paper px-4 py-2 text-center text-xs text-ink/80"
    >
      {GLOBAL_DISCLAIMER}
    </footer>
  );
}
