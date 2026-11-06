"use client";

import { useState } from "react";

import { adminErrorLabel, adminLogin } from "@/lib/admin";

export function LoginCard({ onSignedIn }: { onSignedIn: () => void }) {
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  return (
    <form className="mt-4 max-w-sm rounded border border-line bg-paper p-4"
      onSubmit={async (event) => {
        event.preventDefault();
        setBusy(true);
        setError("");
        try {
          await adminLogin(token);
          setToken("");
          onSignedIn();
        } catch (caught) {
          setError(adminErrorLabel(caught));
        } finally {
          setBusy(false);
        }
      }}>
      <h2 className="font-serif text-lg">管理端登录</h2>
      <label className="mt-2 block text-sm" htmlFor="admin-token">管理端口令</label>
      {/* role=textbox 不是冗余：HTML-AAM 里 type=password 没有隐式 textbox 角色，
          testing-library 的 getByRole("textbox") 会查不到它；显式 textbox 是 ARIA in HTML
          对 password 状态允许的角色，axe 也不会报 aria-allowed-role。 */}
      <input id="admin-token" type="password" role="textbox" autoComplete="off" value={token}
        onChange={(event) => setToken(event.target.value)}
        className="mt-1 w-full rounded border border-line bg-paper px-2 py-1 text-sm" />
      <button type="submit" disabled={busy || !token}
        className="mt-3 rounded bg-cinnabar px-3 py-1 text-sm text-paper disabled:opacity-50">
        进入管理端
      </button>
      {busy && <span className="ml-2 text-xs text-ink/70">校验中…</span>}
      <p role="status" aria-live="polite" className="mt-2 min-h-4 text-sm text-cinnabar">{error}</p>
    </form>
  );
}
