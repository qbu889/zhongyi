import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import NotFound from "@/app/not-found";
import { AppHeader } from "@/components/shell/AppHeader";
import { DisclaimerBar } from "@/components/shell/DisclaimerBar";
import { GLOBAL_DISCLAIMER } from "@/lib/constants";

// AppHeader 用 usePathname 做当前项高亮（M4 既有 aria-current 写法）：jsdom 下打桩模块，
// 只补桩不改断言方向。Vitest 5 的 beforeEach 必须块体，简写箭头体会被当成 teardown。
let mockPathname = "/chat";
vi.mock("next/navigation", () => ({ usePathname: () => mockPathname }));

beforeEach(() => {
  mockPathname = "/chat";
});

describe("global shell", () => {
  it("marks framework as disabled and the admin entry as reachable to /admin", () => {
    render(<AppHeader />);
    expect(screen.getByText("辨证框架")).toHaveAttribute("aria-disabled", "true");
    // 旧断言是 toHaveAttribute("aria-disabled","true")——T11 认领入口后事实已变成可点，
    // 断言跟着需求改（管理端可达性，规格 §9/§14），这是更新不是放宽。
    expect(screen.getByRole("link", { name: "管理" })).toHaveAttribute("href", "/admin");
    expect(screen.getByRole("link", { name: "方剂库" })).toHaveAttribute("href", "/formulas");
  });

  it("高亮当前项：/admin 子路由下「管理」带 aria-current", () => {
    mockPathname = "/admin/quality";
    render(<AppHeader />);
    expect(screen.getByRole("link", { name: "管理" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "对话" })).not.toHaveAttribute("aria-current");
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
