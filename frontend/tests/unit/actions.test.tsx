import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AnswerActions } from "@/components/chat/AnswerActions";
import type { Answer } from "@/lib/types";

const answer: Answer = {
  intent: "B", status: "answered", headline: "桂枝汤",
  sections: [{ title: "组成", lines: ["桂枝 45g（三两）"] }],
  citations: [{ ref_type: "formula", ref_id: 61, title: "桂枝汤", anchor: "方#61", snippet: "" }],
  dose_complete: true, candidates: [], followup: [], general_note: null,
  disclaimer: "本回答基于本地蒸馏语料整理，仅供学习与检索参考；诊断与用药请由执业中医师面诊决定。",
  prose: "", top_score: 1,
};

afterEach(() => vi.unstubAllGlobals());

describe("AnswerActions", () => {
  it("copies the full markdown including the server disclaimer", async () => {
    const user = userEvent.setup();
    render(<AnswerActions answer={answer} />);
    await user.click(screen.getByRole("button", { name: "复制全文" }));
    await expect(navigator.clipboard.readText()).resolves.toContain("仅供学习与检索参考");
    expect(await screen.findByRole("status")).toHaveTextContent("已复制");
  });

  it("downloads a markdown file named after the headline", async () => {
    const createObjectURL = vi.fn(() => "blob:answer");
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("URL", { createObjectURL, revokeObjectURL });
    let downloaded = "";
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      downloaded = this.download;
    });

    const user = userEvent.setup();
    render(<AnswerActions answer={answer} />);
    await user.click(screen.getByRole("button", { name: "导出 Markdown" }));

    expect(createObjectURL).toHaveBeenCalledOnce();
    expect(downloaded).toBe("桂枝汤.md");
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:answer");
    expect(await screen.findByRole("status")).toHaveTextContent("已导出");
  });
});
