"use client";

import { useState } from "react";

import { useAdminReauth } from "@/components/admin/AdminShell";
import { ApiError } from "@/lib/api";
import {
  adminErrorLabel, adminGet, adminPost, isAdminUnauthorized,
  type ReindexPreview, type ReindexReport,
} from "@/lib/admin";

/** 闭集七态（Interfaces 声明的 `idle → previewing → confirm → running → done|reused|failed`；
 * 计划 Step 4 片段里缺 `reused`/`failed` 两终态，指针 §2 点名 reused 必须单独播报，补齐）。 */
type Phase = "idle" | "previewing" | "confirm" | "running" | "done" | "reused" | "failed";

const TERMINAL: ReadonlySet<Phase> = new Set<Phase>(["done", "reused", "failed"]);

export function ReindexPanel({ onDone }: { onDone: () => void }) {
  const reprobe = useAdminReauth();
  const [phase, setPhase] = useState<Phase>("idle");
  const [preview, setPreview] = useState<ReindexPreview | null>(null);
  const [report, setReport] = useState<ReindexReport | null>(null);
  const [message, setMessage] = useState("");

  async function loadPreview() {
    setPhase("previewing"); setMessage(""); setReport(null);
    try {
      setPreview(await adminGet<ReindexPreview>("/api/admin/reindex/preview"));
      setPhase("confirm");
    } catch (error) {
      // 指针 §4：数据端点 401 是会话过期（后端 message「请先登录管理端」），不查标签表——
      // ADMIN_ERROR_LABELS.admin_unauthorized 是给登录卡的「口令不正确」，在这里全是误导。
      // 动作只有一个：交回 AdminShell 重新探针，门会把渲染接管成登录卡。
      if (isAdminUnauthorized(error)) { setPhase("idle"); reprobe(); return; }
      setMessage(adminErrorLabel(error));
      setPhase("idle");
    }
  }

  async function run() {
    setPhase("running"); setMessage("");
    try {
      // force 恒为 false（规格 §8-13/验收 13）：POST 与 preview 共用四元组复用谓词，
      // 未变化时后端回 reused=true——reused 终态由此可达。计划片段写死 force:true 会让
      // reused 分支永不可达（force 跳过短路必全量重建），与指针 §2 直接矛盾，按指针修正。
      const result = await adminPost<ReindexReport>("/api/admin/reindex", { force: false });
      setReport(result);
      if (result.reused) {
        // 复用路径后端给 counts={}、chunks=0；谎称「重建完成 / 0 个 chunk」会让维护者
        // 以为数据换过了，所以这里是独立的 reused 终态文案，且 below 的 ready 换行播报不渲染。
        setMessage("无需重建：语料与规则四元组未变化，沿用当前索引。");
        setPhase("reused");
      } else {
        setMessage(`重建完成：版本 #${result.version_id}，切片 ${result.chunks}，耗时 ${result.elapsed_ms}ms。`);
        setPhase("done");
      }
      onDone();
    } catch (error) {
      if (isAdminUnauthorized(error)) { setPhase("confirm"); reprobe(); return; }
      setMessage(adminErrorLabel(error));
      // 500 reindex_failed（事务已回滚）进 failed 终态；409 等可重试错误退回 confirm——
      // 两条路径都必须离开 running，页面上不许残留「重建进行中」。
      setPhase(error instanceof ApiError && error.code === "reindex_failed" ? "failed" : "confirm");
    }
  }

  return (
    <section data-testid="reindex-panel" className="mt-6 rounded border border-line bg-paper p-3">
      <h2 className="font-serif text-lg">重建索引</h2>
      {(phase === "idle" || TERMINAL.has(phase)) && (
        <button type="button" onClick={loadPreview}
          className="mt-2 rounded border border-cinnabar px-3 py-1 text-sm text-cinnabar">
          预览重建影响
        </button>
      )}
      {preview && phase !== "idle" && (
        <div role="group" aria-label="重建确认" className="mt-2 text-sm">
          <p>{preview.changed ? "语料或规则有变化" : "无变化"} · 目标 commit {preview.target_commit_hash.slice(0, 8)}</p>
          {/* 键名是 build_corpus() 的原样键（复数 herbs，backend/app/admin/reindex.py:97-110）；
              写成 `herb` 会静默命中 ?? "—"，把「药 379」丢成「药 —」。 */}
          <p className="mt-1 text-ink/70">源侧行数：药 {preview.corpus_counts.herbs ?? "—"}
            · 古方 {preview.corpus_counts.ancient ?? "—"} · 克数本 {preview.corpus_counts.classic ?? "—"}
            · 穴 {preview.corpus_counts.acupoints ?? "—"}</p>
          <p className="mt-1 text-xs text-ink/70">一期不提供逐实体 +N/−N 差值（需 dry-run 整套 loaders）。</p>
        </div>
      )}
      {(phase === "previewing" || phase === "confirm" || phase === "running") && (
        <button type="button" onClick={run} disabled={phase !== "confirm"}
          className="mt-2 rounded bg-cinnabar px-3 py-1 text-sm text-paper disabled:opacity-50">
          {phase === "running" ? "重建中…" : "确认重建"}
        </button>
      )}
      {phase === "running" && <p className="mt-2 text-sm text-ink/70">重建进行中（同步执行，整库约数秒）…</p>}
      <p role="status" aria-live="polite" className="mt-2 min-h-5 text-sm text-cinnabar">{message}</p>
      {report && !report.reused && (
        <p className="mt-1 text-xs text-ink/70">旧版本已 retired，新版本 #{report.version_id} 现为唯一 ready。</p>
      )}
    </section>
  );
}
