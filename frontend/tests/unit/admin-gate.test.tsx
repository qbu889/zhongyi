import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import { AdminShell } from "@/components/admin/AdminShell";
import { server } from "../msw/server";

function okSession(authenticated: boolean) {
  return HttpResponse.json({ enabled: true, authenticated, expires_at: authenticated ? 1 : null });
}

describe("AdminShell 登录门", () => {
  it("管理端未启用时只给 fail-closed 文案，绝不尝试拉数据", async () => {
    const data = vi.fn();
    server.use(
      http.get("/api/admin/session", () =>
        HttpResponse.json({ enabled: false, authenticated: false, expires_at: null })),
      http.get("/api/admin/quality-report", data),
    );
    render(<AdminShell title="质量报告"><p>报告体</p></AdminShell>);
    expect(await screen.findByText(/管理端未启用/)).toBeInTheDocument();
    expect(screen.queryByText("报告体")).not.toBeInTheDocument();
    expect(data).not.toHaveBeenCalled();
  });

  it("未登录时可完成登录，成功后渲染子内容", async () => {
    const user = userEvent.setup();
    let authed = false;
    server.use(
      http.get("/api/admin/session", () => okSession(authed)),
      http.post("/api/admin/session", () => {
        authed = true;
        return HttpResponse.json({ enabled: true, authenticated: true, expires_at: 1 });
      }),
    );
    render(<AdminShell title="质量报告"><p>报告体</p></AdminShell>);
    const box = await screen.findByRole("textbox", { name: "管理端口令" });
    await user.type(box, "0123456789abcdef0123456789");
    await user.click(screen.getByRole("button", { name: "进入管理端" }));
    await waitFor(() => expect(screen.getByText("报告体")).toBeInTheDocument());
  });

  it("口令错误保留 401 文案且不清空表单", async () => {
    const user = userEvent.setup();
    server.use(
      http.get("/api/admin/session", () => okSession(false)),
      http.post("/api/admin/session", () =>
        HttpResponse.json({ detail: { code: "admin_unauthorized", message: "口令不正确" } },
          { status: 401 })),
    );
    render(<AdminShell title="概览"><p>不该出现</p></AdminShell>);
    await user.type(await screen.findByRole("textbox", { name: "管理端口令" }), "wrong");
    await user.click(screen.getByRole("button", { name: "进入管理端" }));
    expect(await screen.findByRole("status")).toHaveTextContent("口令不正确");
    expect(screen.getByRole("textbox", { name: "管理端口令" })).toHaveValue("wrong");
  });
});
