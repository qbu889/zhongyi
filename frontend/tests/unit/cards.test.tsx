import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { FormulaCard } from "@/components/cards/FormulaCard";
import type { FormulaDetail } from "@/lib/types";

const formula: FormulaDetail = {
  id: 61, canonical_name: "测试方", status: "confirmed", kind: "single",
  anchor: "方#61", note: null, aliases: [],
  lineage: { parent: null, children: [] },
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
  pairs: [],
  components: [],
  evidence: [{ id: 1, source_doc: "02-伤寒论/伤寒六经方库.md", six_jing: "太阳病",
    bing_duan: null, clause_no: "1", formula_no: null, original_text: "原文" }],
  cases: [], dose_complete: false,
};

describe("FormulaCard", () => {
  it("marks approximate and missing doses without inventing grams", () => {
    render(<FormulaCard formula={formula} />);
    expect(screen.getByText("~15g")).toBeInTheDocument();
    expect(screen.getByText("—")).toBeInTheDocument();
    expect(screen.getByText("本方剂量不完全可执行")).toBeInTheDocument();
    expect(screen.getByText("未交叉校验")).toBeInTheDocument();
  });

  it("switches to ancient mode and hides the gram column", async () => {
    const user = userEvent.setup();
    render(<FormulaCard formula={formula} />);
    expect(screen.getByText("~15g")).toBeInTheDocument();
    await user.click(screen.getByRole("switch", { name: "古制" }));
    expect(screen.queryByText("~15g")).not.toBeInTheDocument();
    expect(screen.getByText("一枚(炮)")).toBeInTheDocument();
  });

  it("expands pair differences when herb_diff is non-empty", () => {
    render(
      <FormulaCard
        formula={{
          ...formula,
          pairs: [{
            variant_a: 1, variant_b: 2,
            variant_a_source: "伤寒论", variant_b_source: "金匮要略",
            herb_diff: { missing_in_gram: ["细辛"], missing_in_ancient: [] },
            dose_dev: {}, score: 0.92, pairing_method: "algorithmic",
            algorithm_version: "v1", verified_at: null,
          }],
        }}
      />,
    );
    expect(screen.getByTestId("pair-diff")).toHaveTextContent("仅古制有：细辛");
    expect(screen.getByTestId("variant-badge")).toHaveTextContent("变体有差异");
  });
});
