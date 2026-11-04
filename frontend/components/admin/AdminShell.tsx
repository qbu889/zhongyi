"use client";

import Link from "next/link";
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";

import { LoginCard } from "@/components/admin/LoginCard";
import { ApiError } from "@/lib/api";
import { adminErrorLabel, adminLogout, adminProbe, type AdminGate } from "@/lib/admin";

const NAV = [
  ["/admin", "概览"],
  ["/admin/quality", "质量报告"],
  ["/admin/pending", "候选方名"],
  ["/admin/logs", "问答日志"],
] as const;

/** `unreachable` 态与登出失败面都只报技术标识（错误码 + HTTP 状态），刻意**不**过 `ADMIN_ERROR_LABELS`：
 * 表里 `admin_unauthorized` → 「口令不正确」，探针若拿到 401 就会对一个还没输入过口令的人
 * 说"你口令错了"；登出拿到 401 同理——它说的是"会话已经不在了"，不是"你把口令打错了"。
 * 这一条与 T11–T14 的「数据端点 401 不查标签表」是同一约束。 */
function technicalDetail(error: unknown): string {
  return error instanceof ApiError ? `${error.code} · HTTP ${error.status}` : "请求未送达或响应无法解析";
}

/** 数据端点 401（cookie TTL 1800s 会话中途过期）时，子页请求「重新探针」的唯一通道。
 * 门状态机只有 AdminShell 这一份探针（`probe()` 不对外暴露），页面里自己调
 * `adminProbe()` 会让状态分叉（T10 评审立的规矩，T11 指针 §4 是第一个消费者）。
 * 默认值是 no-op：脱离 AdminShell 的独立组件单测（admin-panels.test 前几例）不因此报错；
 * 401 行为本身由带 AdminShell 的用例覆盖。 */
export const AdminReauthContext = createContext<() => void>(() => {});

/** 子页在 catch 里命中 `isAdminUnauthorized(error)` 后调用返回值：
 * 回到登录态由门自己接管渲染，页面不显示任何错误码标签。 */
export function useAdminReauth(): () => void {
  return useContext(AdminReauthContext);
}

export function AdminShell({ title, path = "", children }: {
  title: string;
  /** 当前路由，用于 aria-current；不给则不高亮（登录门测试不需要导航态）。 */
  path?: string;
  children: ReactNode;
}) {
  const [gate, setGate] = useState<AdminGate>("checking");
  const [probeError, setProbeError] = useState("");
  /** F-2：登出是门上的第二个写动作。会话态只有 `gate` 这一份、探针只有 `probe()` 这一个入口
   * （T10 评审立的规矩），所以登出成功后的"回登录态"必须走 `probe()`，不在组件里另存一份
   * "已登出"标志——那是状态分叉的第二个来源。
   * `logoutError` 非空 = 登出失败面：此时**不**清任何本地态、**不**探针、**不**收起 children，
   * 维护者看到的还是刚才那一屏（规格 §4：HttpOnly cookie 前端删不掉，服务端没答应清 cookie 时
   * 会话就是还活着；谎称"已退出"比留一个可重试的失败面危险得多）。 */
  const [logoutError, setLogoutError] = useState("");
  const [loggingOut, setLoggingOut] = useState(false);
  const probe = useCallback(() => {
    setGate("checking");
    setProbeError("");
    adminProbe()
      .then((session) => setGate(!session.enabled ? "disabled" : session.authenticated ? "ready" : "locked"))
      .catch((error: unknown) => {
        // 只有后端自己点名「未启用」的 503 才进 disabled 闭集文案；其余失败一律 unreachable。
        // 判据用 code + status 两个条件，缺一条都可能把网关错误读成"你没配 ADMIN_TOKEN"。
        if (error instanceof ApiError && error.status === 503 && error.code === "admin_disabled") {
          setProbeError(adminErrorLabel(error));
          setGate("disabled");
        } else {
          setProbeError(technicalDetail(error));
          setGate("unreachable");
        }
      });
  }, []);
  useEffect(probe, [probe]);

  const logout = useCallback(() => {
    setLoggingOut(true);
    setLogoutError("");
    adminLogout()
      .then(() => probe())
      .catch((error: unknown) => setLogoutError(technicalDetail(error)))
      .finally(() => setLoggingOut(false));
  }, [probe]);

  return (
    <div className="mx-auto max-w-6xl px-4 py-4">
      <h1 className="font-serif text-2xl">{title}</h1>
      <nav aria-label="管理端导航" data-testid="admin-nav" className="mt-2 flex flex-wrap items-center gap-3 text-sm">
        {NAV.map(([href, label]) => (
          <Link key={href} href={href} aria-current={href === path ? "page" : undefined}
            className={href === path ? "font-semibold text-cinnabar underline" : "text-cinnabar underline"}>
            {label}
          </Link>
        ))}
        {/* 整枝评审 F-2：登出此前"被规定（规格 §4）、被实现（admin.py:86-89）、被单测锁住
          （test_admin_gate.py::test_login_logout_round_trip，:97 断言登出 204）、被 lib/admin.ts:155 的 adminLogout 备好"，但全前端零消费者。
          cookie 是 max_age=1800 的**持久** cookie，关掉浏览器也活 30 分钟——共用机器的维护者
          原本没有任何办法提前结束会话。入口只在 ready 态出现（未登录时没有会话可退），
          位置按裁定的"全局导航区"放在 nav 行尾。 */}
        {gate === "ready" && (
          <button type="button" onClick={logout} disabled={loggingOut}
            data-testid="admin-logout"
            className="ml-auto rounded border border-line px-3 py-1 text-sm text-cinnabar disabled:opacity-50">
            退出登录
          </button>
        )}
      </nav>
      {logoutError && (
        <p role="alert" className="mt-2 text-sm text-cinnabar">退出登录失败：{logoutError}
          （会话仍然有效，未退出的数据照原样显示）
          <button type="button" onClick={logout} className="ml-2 underline">重试</button></p>
      )}
      <div data-testid="admin-shell" className="mt-4">
        {gate === "checking" && <p role="status" className="text-sm text-ink/70">检查管理端状态…</p>}
        {gate === "disabled" && (
          <p role="alert" className="rounded border border-cinnabar/40 bg-cinnabar/5 p-3 text-sm text-cinnabar">
            {probeError || "管理端未启用：请设置 ADMIN_TOKEN（至少 16 字符）"}
          </p>
        )}
        {gate === "unreachable" && (
          <div role="alert" className="rounded border border-cinnabar/40 bg-cinnabar/5 p-3">
            <p className="text-sm text-cinnabar">管理端暂时连不上：{probeError}</p>
            <button type="button" onClick={probe}
              className="mt-2 rounded bg-cinnabar px-3 py-1 text-sm text-paper">
              重试
            </button>
          </div>
        )}
        {gate === "locked" && <LoginCard onSignedIn={probe} />}
        {gate === "ready" && (
          <AdminReauthContext.Provider value={probe}>{children}</AdminReauthContext.Provider>
        )}
      </div>
    </div>
  );
}
