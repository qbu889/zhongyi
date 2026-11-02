export function GeneralNote({ text }: { text: string }) {
  return (
    <aside className="mt-3 rounded border border-dashed border-line bg-ink/5 p-3 text-sm text-ink/70">
      通用框架说明（非本库内容）：{text}
    </aside>
  );
}
