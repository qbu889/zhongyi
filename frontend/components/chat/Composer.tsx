"use client";

import { useEffect, useState } from "react";

export function Composer({
  pending,
  initialValue = "",
  onSend,
  onStop,
}: {
  pending: boolean;
  initialValue?: string;
  onSend: (text: string) => void;
  onStop: () => void;
}) {
  const [value, setValue] = useState(initialValue);

  useEffect(() => setValue(initialValue), [initialValue]);

  const submit = () => {
    const text = value.trim();
    if (!text || pending) return;
    onSend(text);
    setValue("");
  };

  return (
    <form className="sticky bottom-12 mt-4 border-t border-line bg-paper p-2"
      onSubmit={(event) => { event.preventDefault(); submit(); }}>
      <label htmlFor="composer" className="sr-only">提问</label>
      <textarea id="composer" data-testid="composer" rows={2} value={value}
        onChange={(event) => setValue(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
            event.preventDefault();
            submit();
          }
        }}
        placeholder="用一句话描述症状，或输入方名 / 药名 / 穴位"
        className="w-full resize-y rounded border border-line bg-paper px-3 py-2 text-sm" />
      <div className="mt-1 flex items-center justify-between">
        <span className="text-xs text-ink/50">Enter 发送，Shift+Enter 换行</span>
        {pending ? (
          <button type="button" onClick={onStop}
            className="rounded border border-cinnabar px-3 py-1 text-sm text-cinnabar">
            停止
          </button>
        ) : (
          <button type="submit" data-testid="send"
            className="rounded bg-cinnabar px-3 py-1 text-sm text-paper">
            发送
          </button>
        )}
      </div>
    </form>
  );
}
