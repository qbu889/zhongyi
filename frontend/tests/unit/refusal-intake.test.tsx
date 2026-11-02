import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { RefusalCard } from "@/components/chat/RefusalCard";
import { IntakeCard } from "@/components/intake/IntakeCard";
import type { Answer } from "@/lib/types";

const refusal: Answer = {
  intent: "B",
  status: "refused",
  headline: "本地库未收录该问题对应的方/药/穴证据。",
  sections: [],
  citations: [],
  dose_complete: null,
  candidates: [
    { ref_type: "formula", ref_id: 1, title: "桂枝汤", anchor: "方#桂枝汤", snippet: "" },
    { ref_type: "herb", ref_id: 2, title: "牡桂", anchor: "药#牡桂", snippet: "" },
  ],
  followup: [],
  general_note: null,
  disclaimer: "本回答基于本地蒸馏语料整理，仅供学习与检索参考；诊断与用药请由执业中医师面诊决定。",
  prose: "",
  top_score: 0.281,
};

describe("RefusalCard", () => {
  it("shows candidates and a disabled originals button without prose", () => {
    render(<RefusalCard answer={refusal} question="量子针灸能治癌症吗" onAsk={vi.fn()} />);
    expect(screen.getByTestId("refusal-card"))
      .toHaveTextContent("本地库未收录「量子针灸能治癌症吗」");
    expect(screen.getByTestId("refusal-card")).toHaveTextContent("0.281");
    expect(screen.queryByTestId("answer-body")).not.toBeInTheDocument();
    const originals = screen.getByRole("button", { name: "在原文 text/ 搜一下" });
    expect(originals).toBeDisabled();
    expect(originals).toHaveAttribute("title", "原文检索 FR-14 将在 M5 开放");
  });

  it("sends the candidate title when a chip is clicked", async () => {
    const onAsk = vi.fn();
    render(<RefusalCard answer={refusal} question="量子针灸能治癌症吗" onAsk={onAsk} />);
    await userEvent.click(screen.getByRole("button", { name: "桂枝汤" }));
    expect(onAsk).toHaveBeenCalledWith("桂枝汤");
  });
});

describe("IntakeCard", () => {
  it("prefills from the question and submits a structured summary", async () => {
    const onSubmit = vi.fn();
    render(<IntakeCard followup={["有没有怕冷？"]} initialText="纳差、怕冷、无汗"
      onSubmit={onSubmit} onSkip={vi.fn()} />);

    const stomach = screen.getByRole("radiogroup", { name: "胃口" });
    expect(within(stomach).getByText("已从您的描述提取")).toBeInTheDocument();

    await userEvent.click(within(stomach).getByRole("radio", { name: "异常" }));
    await userEvent.type(screen.getByRole("textbox", { name: "胃口补充说明" }), "饭后胀");
    await userEvent.click(screen.getByRole("button", { name: "提交主诉补充" }));

    const summary = onSubmit.mock.calls[0][0] as string;
    expect(summary).toContain("主诉补充（问诊卡）：");
    expect(summary).toContain("寒热=异常（怕冷）");
    expect(summary).toContain("胃口=异常（饭后胀）");
  });

  it("supports keyboard selection and skip", async () => {
    const onSkip = vi.fn();
    render(<IntakeCard followup={[]} initialText="" onSubmit={vi.fn()} onSkip={onSkip} />);
    const sleep = screen.getByRole("radiogroup", { name: "睡眠" });
    const normal = within(sleep).getByRole("radio", { name: "正常" });
    normal.focus();
    await userEvent.keyboard(" ");
    expect(normal).toHaveAttribute("aria-checked", "true");
    await userEvent.click(screen.getByRole("button", { name: "跳过，直接看回答" }));
    expect(onSkip).toHaveBeenCalled();
  });
});
