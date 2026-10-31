import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import { AnswerBody } from "@/components/chat/AnswerBody";
import { EvidenceDrawer } from "@/components/drawer/EvidenceDrawer";
import { server } from "../msw/server";

const citation = {
  ref_type: "case" as const,
  ref_id: 11,
  title: "问11",
  anchor: "医案#问11",
  snippet: "服西药多年不愈",
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
    expect(screen.getByText(/通用框架说明（非本库内容）：肺主宣发肃降/)).toBeInTheDocument();
    expect(screen.getByText(/仅供学习与检索参考/)).toBeInTheDocument();
    expect(screen.queryByTestId("citation-sup")).not.toBeInTheDocument();
  });
});
