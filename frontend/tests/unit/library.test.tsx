import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import { FilterPanel } from "@/components/library/FilterPanel";
import { SearchSuggest } from "@/components/library/SearchSuggest";

import { server } from "../msw/server";

const { push } = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

function lastUrl() {
  return new URL(push.mock.calls[push.mock.calls.length - 1][0] as string, "http://x");
}

describe("FilterPanel", () => {
  it("keeps multi-value filters in the URL and resets paging", async () => {
    push.mockReset();
    const { rerender } = render(
      <FilterPanel basePath="/formulas" initial={{ page: ["2"], six_jing: ["太阳病"] }}
        groups={[{
          kind: "multi", key: "six_jing", label: "六经",
          options: ["太阳病", "阳明病", "少阳病"],
        }]} />,
    );

    await userEvent.click(screen.getByRole("checkbox", { name: "阳明病" }));
    const added = lastUrl();
    expect(added.pathname).toBe("/formulas");
    expect(added.searchParams.getAll("six_jing")).toEqual(["太阳病", "阳明病"]);
    expect(added.searchParams.get("page")).toBeNull();

    rerender(
      <FilterPanel basePath="/formulas"
        initial={{ page: ["2"], six_jing: ["太阳病", "阳明病"] }}
        groups={[{
          kind: "multi", key: "six_jing", label: "六经",
          options: ["太阳病", "阳明病", "少阳病"],
        }]} />,
    );
    await userEvent.click(screen.getByRole("checkbox", { name: "太阳病" }));
    expect(lastUrl().searchParams.getAll("six_jing")).toEqual(["阳明病"]);
    expect(lastUrl().searchParams.get("page")).toBeNull();
  });

  it("copies the current filter link", async () => {
    const writeText = vi.fn();
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText }, configurable: true,
    });
    render(<FilterPanel basePath="/herbs" initial={{}} groups={[]} />);
    await userEvent.click(screen.getByRole("button", { name: "复制当前筛选链接" }));
    expect(writeText).toHaveBeenCalledWith(window.location.href);
    expect(screen.getByRole("button", { name: "已复制筛选链接" })).toBeInTheDocument();
  });
});

describe("SearchSuggest", () => {
  it("groups hits as exact / literal / vector and commits on Enter", async () => {
    server.use(http.post("/api/search", async ({ request }) => {
      const body = await request.json() as { query: string };
      return HttpResponse.json({
        query: body.query,
        normalized_query: body.query,
        index_version: { id: 1, commit_hash: "x", embedding_model_version: null },
        hits: [
          { ref_type: "herb", ref_id: 12, title: "柴胡", snippet: "", score: 1,
            match: "exact", anchor: "药#柴胡" },
          { ref_type: "herb", ref_id: 3, title: "牡桂", snippet: "", score: 0.9,
            match: "literal", anchor: "药#牡桂" },
          { ref_type: "formula", ref_id: 9, title: "小柴胡汤", snippet: "", score: 0.4,
            match: "vector", anchor: "方#小柴胡汤" },
        ],
      });
    }));

    const commit = vi.fn();
    render(<SearchSuggest kinds={["herb"]} onCommit={commit} />);
    const input = screen.getByRole("searchbox", { name: "检索" });
    await userEvent.type(input, "柴胡");

    const suggest = await screen.findByTestId("suggest");
    const groups = within(suggest).getAllByTestId("suggest-group");
    expect(groups.map((group) => group.textContent)).toEqual([
      expect.stringContaining("精确"),
      expect.stringContaining("字面"),
      expect.stringContaining("语义相关"),
    ]);
    expect(within(suggest).getByRole("link", { name: "柴胡" }))
      .toHaveAttribute("href", "/herbs/12");

    await userEvent.type(input, "{Enter}");
    expect(commit).toHaveBeenCalledWith("柴胡");
  });
});
