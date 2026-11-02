import type { ReactNode } from "react";

export function MessageBubble({ role, children }: {
  role: "user" | "assistant";
  children: ReactNode;
}) {
  return (
    <div data-testid={`message-${role}`}
      className={role === "user"
        ? "ml-auto mt-3 max-w-[85%] whitespace-pre-wrap rounded bg-cinnabar/10 px-3 py-2 text-sm"
        : "mt-3 max-w-full rounded border border-line bg-paper px-3 py-2"}>
      {children}
    </div>
  );
}
