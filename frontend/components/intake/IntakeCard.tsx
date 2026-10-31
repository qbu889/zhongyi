"use client";

import * as Tabs from "@radix-ui/react-tabs";
import { useState } from "react";

import {
  formatIntakeSummary,
  prefillIntake,
  TRI_LABELS,
  type IntakeDraft,
  type IntakeField,
  type TriState,
} from "@/lib/intake";

const STATES: Exclude<TriState, "">[] = ["normal", "abnormal", "unknown"];

function FieldRow({ field, onChange }: {
  field: IntakeField;
  onChange: (next: IntakeField) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2 border-b border-line/60 py-2">
      <span className="w-24 text-sm">{field.key}</span>
      <div role="radiogroup" aria-label={field.key} className="flex gap-1">
        {STATES.map((state) => (
          <button key={state} type="button" role="radio" aria-checked={field.state === state}
            onClick={() => onChange({
              ...field,
              state,
              note: state === "abnormal" ? field.note : "",
              source: null,
            })}
            className={`rounded border px-2 py-1 text-sm ${
              field.state === state
                ? "border-cinnabar bg-cinnabar/10 text-cinnabar"
                : "border-line text-ink/70"
            }`}>
            {TRI_LABELS[state]}
          </button>
        ))}
        {field.source === "typed" && (
          <span className="self-center text-xs text-cinnabar">已从您的描述提取</span>
        )}
        {field.source === "history" && (
          <span className="self-center text-xs text-ink/50">已从历史对话提取</span>
        )}
      </div>
      {field.state === "abnormal" && (
        <input aria-label={`${field.key}补充说明`} value={field.note}
          onChange={(event) => onChange({ ...field, note: event.target.value, source: null })}
          // 提取出的说明是整段替换的对象，聚焦时全选，避免追加成「纳差饭后胀」。
          onFocus={(event) => event.currentTarget.select()}
          placeholder="具体表现（选填）"
          className="w-40 rounded border border-line bg-paper px-2 py-1 text-sm" />
      )}
    </div>
  );
}

function FieldGroup({ title, fields, onChange }: {
  title: string;
  fields: IntakeField[];
  onChange: (index: number, next: IntakeField) => void;
}) {
  return (
    <fieldset className="mt-3">
      <legend className="text-sm font-semibold text-cinnabar">{title}</legend>
      {fields.map((field, index) => (
        <FieldRow key={field.key} field={field} onChange={(next) => onChange(index, next)} />
      ))}
    </fieldset>
  );
}

export function IntakeCard({
  followup,
  initialText,
  onSubmit,
  onSkip,
}: {
  followup: string[];
  initialText: string;
  onSubmit: (summary: string) => void;
  onSkip: () => void;
}) {
  const [draft, setDraft] = useState<IntakeDraft>(() => prefillIntake(initialText));

  const update = (kind: "baselines" | "questions") => (index: number, next: IntakeField) =>
    setDraft((prev) => ({
      ...prev,
      [kind]: prev[kind].map((field, i) => (i === index ? next : field)),
    }));

  const hasAny = [...draft.baselines, ...draft.questions].some((field) => field.state);

  return (
    <form data-testid="intake-card"
      className="mt-3 rounded border border-line bg-paper p-3"
      onSubmit={(event) => {
        event.preventDefault();
        if (hasAny) onSubmit(formatIntakeSummary(draft));
      }}>
      <h3 className="font-serif text-lg">补充问诊信息</h3>
      {followup.length > 0 && (
        <ul className="mt-1 list-disc pl-5 text-sm text-ink/70">
          {followup.map((item) => <li key={item}>{item}</li>)}
        </ul>
      )}
      <Tabs.Root defaultValue="baseline" className="mt-3">
        <Tabs.List aria-label="问诊分类" className="flex gap-2 border-b border-line">
          <Tabs.Trigger value="baseline"
            className="px-2 py-1 text-sm data-[state=active]:border-b-2 data-[state=active]:border-cinnabar">
            七条基准
          </Tabs.Trigger>
          <Tabs.Trigger value="questions"
            className="px-2 py-1 text-sm data-[state=active]:border-b-2 data-[state=active]:border-cinnabar">
            十问
          </Tabs.Trigger>
        </Tabs.List>
        <Tabs.Content value="baseline">
          <FieldGroup title="七条基准" fields={draft.baselines} onChange={update("baselines")} />
        </Tabs.Content>
        <Tabs.Content value="questions">
          <FieldGroup title="十问" fields={draft.questions} onChange={update("questions")} />
        </Tabs.Content>
      </Tabs.Root>
      <div className="mt-3 flex flex-wrap gap-2">
        <button type="submit" disabled={!hasAny}
          className="rounded bg-cinnabar px-3 py-1 text-sm text-paper disabled:opacity-50">
          提交主诉补充
        </button>
        <button type="button" onClick={onSkip}
          className="rounded border border-line px-3 py-1 text-sm text-ink/70">
          跳过，直接看回答
        </button>
      </div>
      <p className="mt-2 text-xs text-ink/60">
        只做结构化记录，不生成诊断结论；Tab 遍历、空格选择、Enter 提交。
      </p>
    </form>
  );
}
