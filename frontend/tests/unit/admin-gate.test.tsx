import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { useEffect, useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { AdminShell } from "@/components/admin/AdminShell";
import { adminGet } from "@/lib/admin";

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

  it("登出入口只在 ready 态出现：disabled 与 locked 两态都不给（没有会话可退）", async () => {
    server.use(
      http.get("/api/admin/session", () => HttpResponse.json(
        { enabled: false, authenticated: false, expires_at: null })),
    );
    render(<AdminShell title="概览"><p>报告体</p></AdminShell>);
    await screen.findByText(/管理端未启用/);
    expect(screen.queryByRole("button", { name: "退出登录" })).not.toBeInTheDocument();

    // 换一趟探针为"已启用未登录"（locked）：登录卡在屏上，但同样不给登出入口。
    server.use(http.get("/api/admin/session", () => okSession(false)));
    render(<AdminShell title="概览"><p>报告体</p></AdminShell>);
    await screen.findByRole("textbox", { name: "管理端口令" });
    expect(screen.queryByRole("button", { name: "退出登录" })).not.toBeInTheDocument();
    expect(screen.queryByText("报告体")).not.toBeInTheDocument();
  });
});

/* ————————————————————————————————————————————————————————————
   整枝评审 F-2：登出此前"被规定（规格 §4）、被实现（admin.py:86-89）、被单测锁住
   （test_admin_gate.py::test_login_logout_round_trip，:97 断言登出 204）、被 lib/admin.ts:155 的 adminLogout 备好"，但全前端**零消费者**。
   cookie 是 `max_age=1800` 的持久 cookie（关浏览器也活 30 分钟），没有入口时共用机器的
   维护者没有任何办法提前结束会话。下面四条（连同上一段"登出入口只在 ready 态出现"共五条）钉住接进
   `AdminShell` 全局导航区后的行为契约：
   成功 → 发那一发 POST 且门回登录卡；回落后**不再渲染任何已登录态数据**（fail-closed 方向）；
   失败 → 不清态、不回登录卡、给行内可重试错误。写法沿用本文件的 msw 探针桩，
   在途态用**测试持有的 promise** 驱动（不引入假定时器——本计划已两次否决）。
   ———————————————————————————————————————————————————————————— */
describe("AdminShell 登出入口", () => {
  it("点登出：发出 POST /api/admin/session/logout，随后回到登录卡", async () => {
    const user = userEvent.setup();
    let signedIn = true;
    const logoutPaths: string[] = [];
    server.use(
      http.get("/api/admin/session", () => okSession(signedIn)),
      http.post("/api/admin/session/logout", ({ request }) => {
        logoutPaths.push(new URL(request.url).pathname);
        // 服务端在这里真的清 cookie；门随后重新探针就会看到未登录。
        signedIn = false;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    render(<AdminShell title="质量报告" path="/admin/quality"><p>报告体</p></AdminShell>);
    await screen.findByText("报告体");

    await user.click(screen.getByRole("button", { name: "退出登录" }));

    await waitFor(() => expect(logoutPaths).toEqual(["/api/admin/session/logout"]));
    // 逐字对上后端路径：发到别处（或根本不发）都算这条锁失败——adminLogout 是全仓唯一出口。
    expect(await screen.findByRole("textbox", { name: "管理端口令" })).toBeInTheDocument();
    expect(screen.getByText("管理端登录")).toBeInTheDocument();
  });

  it("登出后不再有已登录态的数据渲染：children 整棵卸载，且不再发任何数据请求", async () => {
    const user = userEvent.setup();
    let signedIn = true;
    let dataGets = 0;
    server.use(
      http.get("/api/admin/session", () => okSession(signedIn)),
      http.get("/api/admin/quality-report", () => {
        dataGets += 1;
        return HttpResponse.json({ ok: true });
      }),
      http.post("/api/admin/session/logout", () => {
        signedIn = false;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    // children 自己拉数据：这样"登出后不再有已登录态渲染"验的是真数据面，不是一句占位文本。
    function ReportBody() {
      const [state, setState] = useState<string>("读取中");
      useEffect(() => {
        adminGet("/api/admin/quality-report").then(() => setState("报告体已渲染"));
      }, []);
      return <p>{state}</p>;
    }
    render(<AdminShell title="质量报告" path="/admin/quality"><ReportBody /></AdminShell>);
    expect(await screen.findByText("报告体已渲染")).toBeInTheDocument();
    expect(dataGets).toBe(1);

    await user.click(screen.getByRole("button", { name: "退出登录" }));
    await screen.findByRole("textbox", { name: "管理端口令" });

    // fail-closed 方向：已登录态的数据面整棵不在屏上，且没有新的数据请求发出去
    //（门不给 children 挂载机会，所以连"读一次再收起来"都不会发生）。
    expect(screen.queryByText("报告体已渲染")).not.toBeInTheDocument();
    expect(screen.queryByText("报告体")).not.toBeInTheDocument();
    expect(dataGets).toBe(1);
    // 登出入口随 ready 态一起收起：未登录时不给"再退一次"的按钮。
    expect(screen.queryByRole("button", { name: "退出登录" })).not.toBeInTheDocument();
  });

  it("登出失败（500）：不清本地态、不回登录卡，给行内可重试错误", async () => {
    const user = userEvent.setup();
    let logouts = 0;
    let probes = 0;
    server.use(
      http.get("/api/admin/session", () => {
        probes += 1;
        return okSession(true);
      }),
      http.post("/api/admin/session/logout", () => {
        logouts += 1;
        return new HttpResponse("Internal Server Error", { status: 500 });
      }),
    );
    render(<AdminShell title="质量报告" path="/admin/quality"><p>报告体</p></AdminShell>);
    await screen.findByText("报告体");
    expect(probes).toBe(1);

    await user.click(screen.getByRole("button", { name: "退出登录" }));

    await waitFor(() => expect(logouts).toBe(1));
    // 服务端没答应清 cookie，前端就不许谎称已退出：会话态与 children 一律原样留着。
    expect(screen.getByText("报告体")).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "管理端口令" })).not.toBeInTheDocument();
    // 失败面用行内 role=alert（不用 window.alert/confirm——产品面纪律），带诊断线索。
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("退出登录失败");
    expect(alert).toHaveTextContent("HTTP 500");
    // 只报技术标识，**不**过 ADMIN_ERROR_LABELS：`admin_unauthorized` 的标签是「口令不正确」，
    // 对一个刚点登出的人说"口令错了"是误诊（与本文件 unreachable 那条同一约束）。
    expect(alert).not.toHaveTextContent("口令不正确");
    // 失败路径不重新探针：没有"悄悄换一次状态"这回事（probes 仍是 1）。
    expect(probes).toBe(1);
    // 可重试：点错误行里的重试再发一次登出，而不是把维护者困在假就绪态。
    await user.click(within(alert).getByRole("button", { name: "重试" }));
    await waitFor(() => expect(logouts).toBe(2));
    // 这一句是失败面的"不谎称"承诺：会话还在，屏上数据也没被收走。
    expect(alert).toHaveTextContent("会话仍然有效，未退出的数据照原样显示");
  });

  it("登出在途时入口禁用，双击只发一次 POST（与写动作在途同一口径）", async () => {
    let release!: () => void;
    const gate = new Promise<void>((resolve) => { release = resolve; });
    let logouts = 0;
    let signedIn = true;
    server.use(
      http.get("/api/admin/session", () => okSession(signedIn)),
      http.post("/api/admin/session/logout", async () => {
        logouts += 1;
        signedIn = false;          // 服务端先清 cookie，再让响应落地
        await gate;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    render(<AdminShell title="质量报告" path="/admin/quality"><p>报告体</p></AdminShell>);
    await screen.findByText("报告体");
    const logoutButton = screen.getByRole("button", { name: "退出登录" });

    fireEvent.click(logoutButton);   // 第一击：POST 在途
    fireEvent.click(logoutButton);   // 双击：同批第二个 click（user-event 会跳过 disabled 目标，测不到这一层）
    expect(logoutButton).toBeDisabled();
    await waitFor(() => expect(logouts).toBe(1));
    expect(logouts).toBe(1);
    // 在途期间不提前谎称已退出：屏上还是已登录内容。
    expect(screen.getByText("报告体")).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "管理端口令" })).not.toBeInTheDocument();

    release();
    // 放行之后才回登录态（门重新探针 → locked → 登录卡）。
    expect(await screen.findByRole("textbox", { name: "管理端口令" })).toBeInTheDocument();
    expect(screen.queryByText("报告体")).not.toBeInTheDocument();
  });
});
