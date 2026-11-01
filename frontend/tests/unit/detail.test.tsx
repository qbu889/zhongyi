import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import { AcupointDetailView } from "@/components/library/AcupointDetailView";
import { CaseDetailView } from "@/components/library/CaseDetailView";
import { FormulaDetailView } from "@/components/library/FormulaDetailView";
import { HerbDetailView } from "@/components/library/HerbDetailView";
import { ANSWER_DISCLAIMER } from "@/lib/constants";
import { loadDetail, parseId } from "@/lib/detail";
import type { AcupointDetail, CaseDetail, FormulaDetail, HerbDetail } from "@/lib/types";

import { server } from "../msw/server";

vi.mock("next/navigation", () => ({
  notFound: () => {
    throw new Error("NEXT_NOT_FOUND");
  },
}));

const formula: FormulaDetail = {
  id: 61, canonical_name: "测试方", status: "confirmed", kind: "modified",
  anchor: "方#61", note: "注记",
  aliases: [{ name: "别名方", doc: "经方组成", kind: "加减写法" }],
  lineage: {
    parent: { id: 60, canonical_name: "母方" },
    children: [{ id: 62, canonical_name: "子方" }],
  },
  variants: [{
    id: 1, source_doc: "经方组成", dose_basis: "ancient", ordinal: 0,
    source_row_no: 1, raw_composition: null, dose_complete: false,
    items: [
      { herb_text: "附子", herb_name: "附子", dose_text: "一枚(炮)", dose_g: 15,
        dose_state: "approx", preparation: "炮", conversion_note: "一枚约15g" },
      { herb_text: "猪苓", herb_name: "猪苓", dose_text: "十八铢", dose_g: null,
        dose_state: "unknown_unit", preparation: null, conversion_note: null },
    ],
  }],
  pairs: [{
    variant_a: 1, variant_b: 2, variant_a_source: "经方组成", variant_b_source: "汉方计量",
    herb_diff: { missing_in_gram: ["细辛"], missing_in_ancient: ["干姜"] },
    dose_dev: { 附子: { ancient_g: 15, gram_g: 9, deviation_pct: 66.7 } },
    score: 0.87, pairing_method: "algorithmic", algorithm_version: "v1", verified_at: null,
  }],
  components: [],
  evidence: [{
    id: 1, source_doc: "02-伤寒论/伤寒六经方库.md", six_jing: "太阳病",
    bing_duan: null, clause_no: "1", formula_no: null, original_text: "原文",
  }],
  cases: [{ id: 11, no: "问11", category: "咳嗽" }],
  dose_complete: false,
};

const herb: HerbDetail = {
  id: 6, name: "牡桂", alias: ["桂枝"], flavor: null, flavor_state: "missing",
  flavor_source_state: "absent", taste_group: null, organ_group: "心",
  formula_count: 1, effects: "发汗", indications: "中风", dosage_note: null,
  taboo: null, preparation: null, raw_note: "本经原注",
  formulas: [{ id: 61, canonical_name: "桂枝汤" }],
};

const point: AcupointDetail = {
  id: 3, name: "合谷", meridian: "手阳明大肠经", role: "原",
  location: "手背第一、二掌骨间", actions: "齿痛", symptom_count: 1,
  symptoms: [{ symptom: "头痛", source_doc: "05-针灸/针灸取穴.md" }],
};

const caseItem: CaseDetail = {
  id: 11, no: "问11", category: "咳嗽", chief_complaint: "咳嗽气喘",
  treatment: "射干麻黄汤加桔梗", treatment_formulas: [{ id: 61, canonical_name: "射干麻黄汤" }],
  added_herbs: ["桔梗"], pathogenesis: "寒饮郁肺", tips: "忌生冷",
  raw_md: "服西药多年不愈",
};

describe("detail loaders", () => {
  it("rejects non-positive ids with notFound", () => {
    expect(parseId("61")).toBe(61);
    expect(() => parseId("0")).toThrow("NEXT_NOT_FOUND");
    expect(() => parseId("abc")).toThrow("NEXT_NOT_FOUND");
  });

  // R17：只接受纯十进制数字段，Number() 放行的写法一律 notFound()。
  it("rejects non-decimal and unsafe ids with notFound", () => {
    expect(() => parseId("0x10")).toThrow("NEXT_NOT_FOUND");
    expect(() => parseId("1e2")).toThrow("NEXT_NOT_FOUND");
    expect(() => parseId(" 5 ")).toThrow("NEXT_NOT_FOUND");
    expect(() => parseId("99999999999999999999")).toThrow("NEXT_NOT_FOUND");
  });

  it("maps a 404 to notFound and rethrows other errors", async () => {
    server.use(
      http.get("http://localhost:8000/api/herbs/999", () =>
        HttpResponse.json({ detail: { code: "herb_not_found" } }, { status: 404 })),
      http.get("http://localhost:8000/api/herbs/998", () =>
        HttpResponse.json({ detail: { code: "boom" } }, { status: 500 })),
    );
    await expect(loadDetail("/api/herbs/999")).rejects.toThrow("NEXT_NOT_FOUND");
    await expect(loadDetail("/api/herbs/998")).rejects.toThrow("HTTP 500");
  });
});

describe("FormulaDetailView", () => {
  it("shows lineage separately from pair diffs and never invents grams", async () => {
    const user = userEvent.setup();
    render(<FormulaDetailView formula={formula} />);

    expect(screen.getByTestId("formula-detail")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: "测试方" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "母方" })).toHaveAttribute("href", "/formulas/60");
    expect(screen.getByRole("link", { name: "子方" })).toHaveAttribute("href", "/formulas/62");
    expect(screen.getByText(/仅古制有：细辛/)).toBeInTheDocument();
    expect(screen.getByText(/仅克数本有：干姜/)).toBeInTheDocument();
    expect(screen.getByText(/附子：古制 15g \/ 克数本 9g/)).toBeInTheDocument();
    expect(screen.getByText("~15g")).toBeInTheDocument();
    expect(screen.getByText("本方剂量不完全可执行")).toBeInTheDocument();
    expect(screen.getByTestId("detail-disclaimer")).toHaveTextContent(ANSWER_DISCLAIMER);
    expect(screen.getByTestId("variant-badge")).toHaveTextContent("变体有差异");
    expect(screen.getByRole("link", { name: "就本条提问" }))
      .toHaveAttribute("href", "/chat?ref=formula:61");

    await user.click(screen.getByRole("switch", { name: "古制" }));
    expect(screen.queryByText("~15g")).not.toBeInTheDocument();
    expect(screen.getByText("一枚(炮)")).toBeInTheDocument();
  });
});

describe("library detail views", () => {
  it("herb detail marks missing flavor and links containing formulas", () => {
    render(<HerbDetailView herb={herb} />);
    expect(screen.getByTestId("herb-detail")).toHaveTextContent("本经未载性味");
    expect(screen.getByRole("link", { name: "桂枝汤" })).toHaveAttribute("href", "/formulas/61");
    expect(screen.getByRole("link", { name: "就本条提问" }))
      .toHaveAttribute("href", "/chat?ref=herb:6");
    // §9.2 组成反查的产出端：herb 详情给出 /formulas?herb=<药名>（后端参数名同名）。
    expect(decodeURIComponent(screen.getByRole("link", { name: "查含此药的方" })
      .getAttribute("href") ?? "")).toBe("/formulas?herb=牡桂");
  });

  it("acupoint detail lists the recorded symptoms", () => {
    render(<AcupointDetailView point={point} />);
    expect(screen.getByTestId("acupoint-detail")).toHaveTextContent("手阳明大肠经");
    expect(screen.getByText("头痛")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "就本条提问" }))
      .toHaveAttribute("href", "/chat?ref=acupoint:3");
    expect(decodeURIComponent(screen.getByRole("link", { name: "同经穴位" })
      .getAttribute("href") ?? "")).toBe("/acupoints?meridian=手阳明大肠经");
  });

  it("case detail keeps question/answer/treatment/tips and the raw text", () => {
    render(<CaseDetailView caseItem={caseItem} />);
    expect(screen.getByTestId("case-detail")).toHaveTextContent("问11");
    expect(screen.getByRole("link", { name: "射干麻黄汤" }))
      .toHaveAttribute("href", "/formulas/61");
    expect(screen.getByText("加味：桔梗")).toBeInTheDocument();
    expect(decodeURIComponent(screen.getByRole("link", { name: "同病类医案" })
      .getAttribute("href") ?? "")).toBe("/cases?category=咳嗽");
    expect(screen.getByText("服西药多年不愈")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "就本条提问" }))
      .toHaveAttribute("href", "/chat?ref=case:11");
  });
});
