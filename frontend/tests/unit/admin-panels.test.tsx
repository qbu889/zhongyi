import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AdminOverviewPage from "@/app/admin/page";
import { AdminShell } from "@/components/admin/AdminShell";
import { ReindexPanel } from "@/components/admin/ReindexPanel";
import { VersionTable } from "@/components/admin/VersionTable";
import type {
  IndexVersionInfo, IndexVersions, ReindexPreview, ReindexReport,
} from "@/lib/admin";

import { server } from "../msw/server";

/** 夹具一律用 lib/admin.ts 的类型声明（T10 已逐键对着后端核过）：
 * IndexVersionInfo 13 键、ReindexReport 11 键全必填。计划稿里的缺键字面量
 * 在这里会直接 typecheck 失败——这正是指针 §5 要的"不符必须显式暴露"。 */
const currentReady: IndexVersionInfo = {
  id: 7, status: "ready", commit_hash: "abc123def456", chunk_count: 1818,
  formula_count: 423, herb_count: 379, acupoint_count: 346, case_count: 30,
  embedding_model_version: "hashing-2026.10", chunking_version: "chunk-2026.10.1",
  extract_rule_version: "identity-2026.10",
  notes: { skipped: { pair_missing_variant: 4 } },
  created_at: "2026-11-02T00:00:00+00:00",
};
const versions: IndexVersions = {
  current: currentReady,
  target_commit_hash: "abc123def456",
  versions: [currentReady, { ...currentReady, id: 6, status: "retired" }],
};
/** 草药键是复数 `herbs`（build_corpus() 的原样键，backend/app/admin/reindex.py:97-110）；
 * 计划 1982 行的 `herb` 是错键，会静默渲染成"药 —"。 */
const preview: ReindexPreview = {
  changed: false, will_reuse: true, target_commit_hash: "abc123def456",
  corpus_counts: {
    herbs: 379, vocab: 379, ancient: 242, classic: 96, evidence: 118,
    framework: 6, cases: 30, acupoints: 346, acupoint_symptoms: 120,
    pairs: 511, aliases: 88,
  },
  current: currentReady,
};
/** 复用短路路径的 asdict(ReindexReport)：四元组命中时 counts/skipped 为空 dict、
 * chunks 等为 0——页面上绝不许把这些空值播报成"重建了 0 个 chunk"（指针 §2）。 */
const reusedReport: ReindexReport = {
  version_id: 7, commit_hash: "abc123def456", status: "ready", reused: true,
  embedding_model_version: "hashing-2026.10",
  counts: {}, skipped: {}, chunks: 0, noise_tokens: 0, dangling_herb_items: 0,
  elapsed_ms: 0,
};

beforeEach(() => {
  // Vitest 5：简写箭头体的 beforeEach 会被当成 teardown，必须用块体。
  vi.restoreAllMocks();
});

describe("VersionTable", () => {
  it("渲染当前索引四元组与 skipped 摘要", () => {
    render(<VersionTable data={versions} />);
    expect(screen.getByTestId("version-table")).toHaveTextContent("1818");
    expect(screen.getByText("hashing-2026.10")).toBeInTheDocument();
    expect(screen.getByText("chunk-2026.10.1")).toBeInTheDocument();
    expect(screen.getByText("identity-2026.10")).toBeInTheDocument();
    expect(screen.getByText(/pair_missing_variant: 4/)).toBeInTheDocument();
    // 版本历史逐行渲染，id 作 key（重复 key 只在浏览器里暴露，这里保证唯一）。
    expect(screen.getByRole("cell", { name: "retired" })).toBeInTheDocument();
  });

  it("无 ready 索引时给引导文案而不是空表", () => {
    render(<VersionTable data={{ ...versions, current: null }} />);
    expect(screen.getByText("尚无 ready 索引，请先重建。")).toBeInTheDocument();
  });
});

describe("ReindexPanel", () => {
  it("preview → 二次确认 → 完成，且 reused 路径不谎称发布了新版本", async () => {
    const user = userEvent.setup();
    let postedBody: unknown;
    server.use(
      http.get("/api/admin/reindex/preview", () => HttpResponse.json(preview)),
      http.post("/api/admin/reindex", async ({ request }) => {
        postedBody = await request.json();
        return HttpResponse.json(reusedReport);
      }),
    );
    render(<ReindexPanel onDone={() => {}} />);
    await user.click(screen.getByRole("button", { name: "预览重建影响" }));

    const dialog = await screen.findByRole("group", { name: "重建确认" });
    expect(dialog).toHaveTextContent("无变化");
    // 指针 §1 的钉住断言：源侧行数里"药"的数字必须等于响应 corpus_counts.herbs 的真实值，
    // 且不得退化成占位符"—"（错键 `herb` 的静默信息丢失就死在这条上）。
    const counts = within(dialog).getByText(/源侧行数/);
    expect(counts).toHaveTextContent(`药 ${preview.corpus_counts.herbs}`);
    expect(counts).not.toHaveTextContent("药 —");

    await user.click(screen.getByRole("button", { name: "确认重建" }));
    // 指针 §2 + 规格 §8-验收13：默认非 force，才让后端复用语义可达。
    expect(postedBody).toEqual({ force: false });
    expect(await screen.findByRole("status")).toHaveTextContent("无需重建");
    // 复用路径的空值不许被播报成一次真实重建。
    expect(screen.getByRole("status")).not.toHaveTextContent("重建完成");
    expect(screen.queryByText(/0 个 chunk/)).not.toBeInTheDocument();
    expect(screen.queryByText(/旧版本已 retired/)).not.toBeInTheDocument();
  });

  it("非复用成功播报版本/切片/耗时并回调 onDone", async () => {
    const user = userEvent.setup();
    const onDone = vi.fn();
    const freshReport: ReindexReport = {
      ...reusedReport, reused: false, version_id: 8, chunks: 1822, elapsed_ms: 1634,
      counts: { formula: 424, herb: 379, acupoint: 346, case: 30 },
      skipped: { pair_missing_variant: 4 },
    };
    server.use(
      http.get("/api/admin/reindex/preview", () =>
        HttpResponse.json({ ...preview, changed: true, will_reuse: false })),
      http.post("/api/admin/reindex", () => HttpResponse.json(freshReport)),
    );
    render(<ReindexPanel onDone={onDone} />);
    await user.click(screen.getByRole("button", { name: "预览重建影响" }));
    expect(await screen.findByRole("group", { name: "重建确认" }))
      .toHaveTextContent("语料或规则有变化");
    await user.click(screen.getByRole("button", { name: "确认重建" }));
    expect(await screen.findByRole("status")).toHaveTextContent("重建完成：版本 #8");
    expect(screen.getByRole("status")).toHaveTextContent("切片 1822");
    expect(screen.getByRole("status")).toHaveTextContent("耗时 1634ms");
    expect(screen.getByText(/旧版本已 retired，新版本 #8 现为唯一 ready/)).toBeInTheDocument();
    expect(onDone).toHaveBeenCalled();
  });

  it("409 并发锁给出专门文案而不是通用失败，且不把状态机停在 running", async () => {
    const user = userEvent.setup();
    server.use(
      http.get("/api/admin/reindex/preview", () =>
        HttpResponse.json({ ...preview, changed: true })),
      http.post("/api/admin/reindex", () => HttpResponse.json(
        { detail: { code: "reindex_in_progress", message: "已有重建在跑" } }, { status: 409 })),
    );
    render(<ReindexPanel onDone={() => {}} />);
    await user.click(screen.getByRole("button", { name: "预览重建影响" }));
    await screen.findByRole("group", { name: "重建确认" });
    await user.click(screen.getByRole("button", { name: "确认重建" }));
    expect(await screen.findByRole("status")).toHaveTextContent("已有重建在跑");
    // 指针 §5：409 后不得残留"进行中"的进行态；退回 confirm 允许再按一次。
    expect(screen.queryByText(/重建进行中/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "确认重建" })).toBeEnabled();
  });

  it("500 reindex_failed 显示闭集文案并进入 failed 终态", async () => {
    const user = userEvent.setup();
    server.use(
      http.get("/api/admin/reindex/preview", () =>
        HttpResponse.json({ ...preview, changed: true })),
      http.post("/api/admin/reindex", () => HttpResponse.json(
        { detail: { code: "reindex_failed", message: "重建失败：注入异常" } }, { status: 500 })),
    );
    render(<ReindexPanel onDone={() => {}} />);
    await user.click(screen.getByRole("button", { name: "预览重建影响" }));
    await screen.findByRole("group", { name: "重建确认" });
    await user.click(screen.getByRole("button", { name: "确认重建" }));
    expect(await screen.findByRole("status")).toHaveTextContent("重建失败");
    expect(screen.queryByText(/重建进行中/)).not.toBeInTheDocument();
    // 终态：确认按钮不再可点，回到可重新预览的入口。
    expect(screen.queryByRole("button", { name: "确认重建" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "预览重建影响" })).toBeInTheDocument();
  });

  it("预览端点 401：重新探针回登录态，绝不查标签表显示「口令不正确」", async () => {
    const user = userEvent.setup();
    let probes = 0;
    server.use(
      http.get("/api/admin/session", () => {
        probes += 1;
        // 第一次探针已登录（否则挂不上 children）；重新探针时会话已过期 → locked。
        return HttpResponse.json(
          { enabled: true, authenticated: probes < 2, expires_at: probes < 2 ? 1 : null });
      }),
      http.get("/api/admin/reindex/preview", () => HttpResponse.json(
        { detail: { code: "admin_unauthorized", message: "请先登录管理端" } }, { status: 401 })),
    );
    render(
      <AdminShell title="管理端概览" path="/admin">
        <ReindexPanel onDone={() => {}} />
      </AdminShell>,
    );
    await user.click(await screen.findByRole("button", { name: "预览重建影响" }));
    // 探针由 1 次变 2 次 = 状态机走回 AdminShell（唯一探针入口），不是页面自己 adminProbe()。
    await waitFor(() => expect(probes).toBe(2));
    expect(await screen.findByRole("textbox", { name: "管理端口令" })).toBeInTheDocument();
    expect(screen.queryByText("口令不正确")).not.toBeInTheDocument();
  });
});

describe("管理端概览页", () => {
  it("index-versions 401：整页重新探针回登录态，不渲染误导的错误码文案", async () => {
    let probes = 0;
    server.use(
      http.get("/api/admin/session", () => {
        probes += 1;
        return HttpResponse.json(
          { enabled: true, authenticated: probes < 2, expires_at: probes < 2 ? 1 : null });
      }),
      http.get("/api/admin/index-versions", () => HttpResponse.json(
        { detail: { code: "admin_unauthorized", message: "请先登录管理端" } }, { status: 401 })),
    );
    render(<AdminOverviewPage />);
    await waitFor(() => expect(probes).toBe(2));
    expect(await screen.findByRole("textbox", { name: "管理端口令" })).toBeInTheDocument();
    // ADMIN_ERROR_LABELS.admin_unauthorized =「口令不正确」只属于登录卡；数据端点 401
    // 若被喂进标签表，维护者会以为是自己口令输了。
    expect(screen.queryByText("口令不正确")).not.toBeInTheDocument();
    expect(screen.queryByText(/索引信息加载失败/)).not.toBeInTheDocument();
  });
});
