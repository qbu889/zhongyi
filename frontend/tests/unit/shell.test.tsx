import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import NotFound from "@/app/not-found";
import { AppHeader } from "@/components/shell/AppHeader";
import { DisclaimerBar } from "@/components/shell/DisclaimerBar";
import { GLOBAL_DISCLAIMER } from "@/lib/constants";

describe("global shell", () => {
  it("marks framework and admin as M5-disabled", () => {
    render(<AppHeader />);
    expect(screen.getByText("辨证框架")).toHaveAttribute("aria-disabled", "true");
    expect(screen.getByText("管理")).toHaveAttribute("aria-disabled", "true");
    expect(screen.getByRole("link", { name: "方剂库" })).toHaveAttribute("href", "/formulas");
  });

  it("renders the persistent disclaimer", () => {
    render(<DisclaimerBar />);
    expect(screen.getByTestId("disclaimer-global")).toHaveTextContent(GLOBAL_DISCLAIMER);
  });

  it("renders 404 with a link back to chat", () => {
    render(<NotFound />);
    expect(screen.getByRole("heading", { level: 1, name: "页面不存在" })).toBeVisible();
    expect(screen.getByRole("link", { name: "返回对话页" })).toHaveAttribute("href", "/chat");
  });
});
