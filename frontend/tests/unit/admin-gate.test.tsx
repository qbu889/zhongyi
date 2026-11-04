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

  it("探针 500 给可重试的连不上态：不并入未启用文案、不挂 children、不拉数据", async () => {
    const user = userEvent.setup();
    const data = vi.fn();
    let probes = 0;
    server.use(
      http.get("/api/admin/session", () => {
        probes += 1;
        // 真实后端 500 的形状仍是 {"detail":{"code","message"}}（规格 §12）。
        return HttpResponse.json({ detail: { code: "internal_error", message: "服务器内部错误" } },
          { status: 500 });
      }),
      http.get("/api/admin/quality-report", data),
      http.get("/api/admin/pending", data),
      http.get("/api/admin/logs", data),
    );
    render(<AdminShell title="质量报告"><p>报告体</p></AdminShell>);

    expect(await screen.findByRole("alert")).toHaveTextContent(/管理端暂时连不上/);
    // 误诊方向的锁：连不上绝不等于「未启用」，也不出现登录卡里的闭集文案。
    expect(screen.queryByText(/管理端未启用/)).not.toBeInTheDocument();
    expect(screen.queryByText("口令不正确")).not.toBeInTheDocument();
    // 带诊断线索：错误码与 HTTP 状态都必须在页面上可见。
    expect(screen.getByRole("alert")).toHaveTextContent("internal_error");
    expect(screen.getByRole("alert")).toHaveTextContent("HTTP 500");
    // fail-closed：不挂 children，且一个数据请求都没发。
    expect(screen.queryByText("报告体")).not.toBeInTheDocument();
    expect(data).not.toHaveBeenCalled();
    expect(probes).toBe(1);

    await user.click(screen.getByRole("button", { name: "重试" }));
    await waitFor(() => expect(probes).toBe(2));
    expect(await screen.findByRole("alert")).toHaveTextContent(/管理端暂时连不上/);
    expect(screen.queryByText("报告体")).not.toBeInTheDocument();
    expect(data).not.toHaveBeenCalled();
  });

  it("探针 503 admin_disabled 仍走未启用闭集文案，且不给重试按钮", async () => {
    const data = vi.fn();
    server.use(
      http.get("/api/admin/session", () => HttpResponse.json(
        { detail: { code: "admin_disabled", message: "管理端未启用：请设置 ADMIN_TOKEN（至少 16 字符）" } },
        { status: 503 })),
      http.get("/api/admin/quality-report", data),
    );
    render(<AdminShell title="质量报告"><p>报告体</p></AdminShell>);

    expect(await screen.findByText(/管理端未启用/)).toBeInTheDocument();
    // 反面对照：这是「后端明确说没开」，不是连不上，所以没有可重试态。
    expect(screen.queryByText(/管理端暂时连不上/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "重试" })).not.toBeInTheDocument();
    expect(screen.queryByText("报告体")).not.toBeInTheDocument();
    expect(data).not.toHaveBeenCalled();
  });
});
