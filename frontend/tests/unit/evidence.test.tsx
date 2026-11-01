import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AnswerBody } from "@/components/chat/AnswerBody";
import { EvidenceDrawer } from "@/components/drawer/EvidenceDrawer";
import type { Answer, Citation } from "@/lib/types";
import { server } from "../msw/server";

const citation: Citation = {
  ref_type: "case",
  ref_id: 11,
  title: "问11",
  anchor: "医案#问11",
  snippet: "服西药多年不愈",
};

// AnswerBody 在 answered 时会回填实体卡；这里给引用对应的医案一个最小响应。
beforeEach(() => {
  server.use(http.get("/api/cases/11", () =>
    HttpResponse.json({
      id: 11, no: "问11", category: null, chief_complaint: "咳嗽气喘",
      treatment: null, treatment_formulas: [], added_herbs: [],
      pathogenesis: null, tips: null, raw_md: null,
    })));
});

// 行内包含 citation.title，角标才会挂到该行。
const answerWithCitation: Answer = {
  intent: "C", status: "answered", headline: "总览",
  sections: [{ title: "辨证", lines: ["问11：咳嗽气喘痰白不能平躺。"] }],
  citations: [citation], dose_complete: null, candidates: [], followup: [],
  general_note: null,
  disclaimer: "本回答基于本地蒸馏语料整理，仅供学习与检索参考；诊断与用药请由执业中医师面诊决定。",
  prose: "", top_score: 0.4,
};

// 按页面实际接法组合：正文角标打开抽屉，抽屉关闭后 citation 归 null。
function DrawerHarness() {
  const [selected, setSelected] = useState<Citation | null>(null);
  return (
    <>
      <AnswerBody answer={answerWithCitation} onOpenCitation={(item) => setSelected(item)} />
      <EvidenceDrawer citation={selected} onClose={() => setSelected(null)} />
    </>
  );
}

const evidencePayload = {
  ref_type: "case", ref_id: 11, anchor: "医案#问11",
  text: "咳嗽气喘痰白不能平躺，服西药多年不愈。",
  fields: { no: "问11" },
};

describe("EvidenceDrawer", () => {
  it("fetches the full text and highlights the snippet", async () => {
    server.use(http.get("/api/evidence/case:11", () =>
      HttpResponse.json({
        ref_type: "case", ref_id: 11, anchor: "医案#问11",
        text: "咳嗽气喘痰白不能平躺，服西药多年不愈。",
        fields: { no: "问11" },
      })));

    render(<EvidenceDrawer citation={citation} onClose={vi.fn()} />);
    expect(await screen.findByTestId("evidence-drawer")).toHaveTextContent("服西药多年不愈");
    expect(screen.getByText("服西药多年不愈").tagName).toBe("MARK");
    expect(screen.getByRole("link", { name: "在库详情页打开" }))
      .toHaveAttribute("href", "/cases/11");
  });

  it("shows a readable message when the ref is gone", async () => {
    server.use(http.get("/api/evidence/case:11", () =>
      HttpResponse.json({ detail: { code: "ref_not_found" } }, { status: 404 })));

    render(<EvidenceDrawer citation={citation} onClose={vi.fn()} />);
    expect(await screen.findByText("该出处在当前索引版本不存在")).toBeInTheDocument();
  });

  it("closes on Escape and returns focus to the badge that opened it", async () => {
    server.use(http.get("/api/evidence/case:11", () => HttpResponse.json(evidencePayload)));
    const user = userEvent.setup();

    render(<DrawerHarness />);
    const badge = screen.getByRole("button", { name: "查看出处 问11" });
    await user.click(badge);

    expect(await screen.findByTestId("evidence-drawer")).toBeInTheDocument();
    expect(await screen.findByText("服西药多年不愈")).toBeInTheDocument();

    await user.keyboard("{Escape}");
    await waitFor(() =>
      expect(screen.queryByTestId("evidence-drawer")).not.toBeInTheDocument());
    // Radix 在 setTimeout(0) 里触发 onCloseAutoFocus，需等待焦点归还。
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "查看出处 问11" })).toHaveFocus());
  });
});

describe("AnswerBody", () => {
  it("renders the general note as a non-cited aside and keeps the disclaimer", () => {
    render(
      <AnswerBody
        answer={{
          intent: "C", status: "answered", headline: "总览",
          sections: [{ title: "辨证", lines: ["寒饮郁肺"] }],
          citations: [], dose_complete: null, candidates: [], followup: [],
          general_note: "肺主宣发肃降",
          disclaimer: "本回答基于本地蒸馏语料整理，仅供学习与检索参考；诊断与用药请由执业中医师面诊决定。",
          prose: "", top_score: 0.4,
        }}
        onOpenCitation={vi.fn()}
      />,
    );
    expect(screen.getByTestId("answer-body")).toHaveTextContent("寒饮郁肺");
    const aside = screen.getByText(/通用框架说明（非本库内容）：肺主宣发肃降/);
    expect(aside).toBeInTheDocument();
    // 灰底虚线框的样式契约（components/chat/GeneralNote.tsx 的 className）
    expect(aside).toHaveClass(/border-dashed/);
    expect(aside.tagName).toBe("ASIDE");
    expect(screen.getByText(/仅供学习与检索参考/)).toBeInTheDocument();
    expect(screen.queryByTestId("citation-sup")).not.toBeInTheDocument();
  });

  it("renders an accessible badge and opens the citation on click", async () => {
    const user = userEvent.setup();
    const onOpenCitation = vi.fn();

    render(<AnswerBody answer={answerWithCitation} onOpenCitation={onOpenCitation} />);
    const badge = screen.getByRole("button", { name: "查看出处 问11" });
    expect(badge).toHaveTextContent("[1]");

    await user.click(badge);
    expect(onOpenCitation).toHaveBeenCalledTimes(1);
    expect(onOpenCitation).toHaveBeenCalledWith(citation);
  });

  it("shows title, anchor and snippet in the tooltip after hovering the badge", async () => {
    const user = userEvent.setup();

    render(<AnswerBody answer={answerWithCitation} onOpenCitation={vi.fn()} />);
    await user.hover(screen.getByRole("button", { name: "查看出处 问11" }));

    const tooltip = await screen.findByRole("tooltip", {}, { timeout: 2000 });
    expect(tooltip).toHaveTextContent("问11");
    expect(tooltip).toHaveTextContent("医案#问11");
    expect(tooltip).toHaveTextContent("服西药多年不愈");
  });
});
