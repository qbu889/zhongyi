import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AdminOverviewPage from "@/app/admin/page";
import AdminLogsPage from "@/app/admin/logs/page";
import AdminQualityPage from "@/app/admin/quality/page";
import { AdminShell } from "@/components/admin/AdminShell";
import { LogsDashboard } from "@/components/admin/LogsDashboard";
import { QualitySection } from "@/components/admin/QualitySection";
import { ReindexPanel } from "@/components/admin/ReindexPanel";
import { VersionTable } from "@/components/admin/VersionTable";
import type {
  IndexVersionInfo, IndexVersions, QualityReport, ReindexPreview, ReindexReport,
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
/** 真重建成功路径的 asdict(ReindexReport)（非复用：counts 有值、chunks 是新写入数）。 */
const freshReport: ReindexReport = {
  ...reusedReport, reused: false, version_id: 8, chunks: 1822, elapsed_ms: 1634,
  counts: { formula: 424, herb: 379, acupoint: 346, case: 30 },
  skipped: { pair_missing_variant: 4 },
};

/** 质量报告夹具：类型一律用 lib/admin.ts（T10 逐键对后端核过）。七个数据面各给≥1行，
 * 保证成功用例里七张 `<table>` 都在（QualitySection 空 rows 走空态、不出表）。 */
const qualityReport: QualityReport = {
  index_version: { id: 7, status: "ready" },
  herb_diff: [{ formula: "五苓散", pair_id: 1, missing_in_gram: ["猪苓"], missing_in_ancient: ["泽泻"] }],
  dose_deviation: [{
    formula: "麻黄汤", pair_id: 2, worst_pct: 650,
    items: { 麻黄: { ancient_g: 4, gram_g: 30, deviation_pct: 650 } },
  }],
  parse_failures: [{ reason: "multi_name_row", count: 3 }],
  parse_failure_details: [{
    raw_name: "甲", doc: "03-金匮/方剂库.md", source_row_no: 12, reason: "multi_name_row", decision: "pending",
  }],
  annotation_items: [{ herb_text: "（洗）", variant_id: 3, formula_item_id: 4 }],
  dangling_herbs: { rows: 5, distinct_terms: 2, top: [["桂枝", 3], ["麻黄", 2]] },
  dose_state_distribution: { exact: 1, approx: 2, count_only: 0, absent: 0, unknown_unit: 0 },
  pending_queue: { total: 64, by_decision: { pending: 64 }, by_reason: { no_formula_name: 57 } },
  counters: {
    herb_total: 379, herb_without_taste: 0, herb_without_flavor: 0,
    formula_total: 423, variant_gram: 200, variant_ancient: 200, item_total: 900,
  },
};
/** 空报告：四个行清单为空、聚合视图（③ 计数与 ⑤⑥⑦）为空——每条空态断言的对照面。
 * R-M5-19 后 ③ 屏面改渲染 parse_failures 计数，故这里也要清空，空态才覆盖到 ③。 */
const emptyQualityReport: QualityReport = {
  ...qualityReport,
  herb_diff: [], dose_deviation: [], parse_failures: [], parse_failure_details: [], annotation_items: [],
  dangling_herbs: { rows: 0, distinct_terms: 0, top: [] },
  dose_state_distribution: {},
  pending_queue: { total: 0, by_decision: {}, by_reason: {} },
};
/** R-M5-19 判别夹具：③ 的按原因计数给两行（57/3，取值用裁定原文给的示例聚合）。
 * 注：后端 quality.py:78-81 会把 no_formula_name 排除出 ③，这里只是渲染层夹具——
 * 屏面断言"组件把响应里的计数照原样渲染出来"，与后端筛选口径无关。 */
const countQualityReport: QualityReport = {
  ...qualityReport,
  parse_failures: [{ reason: "no_formula_name", count: 57 }, { reason: "multi_name_row", count: 3 }],
};
/** ③ 的节标题逐字（caption=可访问名=标题，指针 §4/concern 4 裁定）：判别用例锁串不锁形状。 */
const FAILURES_TITLE = "③ 解析失败（按原因计数）";

/** F-A 的两行逐字文案。这里刻意再写一遍字面量而不是从组件导入常量：
 * 用例要钉住的是"页面上出现的就是控制人给定的那串"，导入常量会让文案改动悄悄跟着跑。 */
const FORCE_LABEL = "强制重建（即使语料与规则未变化）";
const FORCE_HINT = "强制重建会新起一个索引版本；同步执行期间页面不可用。";

beforeEach(() => {
  // Vitest 5：简写箭头体的 beforeEach 会被当成 teardown，必须用块体。
  vi.restoreAllMocks();
});

describe("VersionTable", () => {
  it("渲染当前索引四元组与构建摘要", () => {
    render(<VersionTable data={versions} />);
    expect(screen.getByTestId("version-table")).toHaveTextContent("1818");
    expect(screen.getByText("hashing-2026.10")).toBeInTheDocument();
    expect(screen.getByText("chunk-2026.10.1")).toBeInTheDocument();
    expect(screen.getByText("identity-2026.10")).toBeInTheDocument();
    expect(screen.getByText(/pair_missing_variant: 4/)).toBeInTheDocument();
    // F-E：notes 里除 skipped 还有 noise_tokens/dangling_herb_items/pair_count
    // （reindex.py:184-185），标签必须是能盖住整个值的「构建摘要」，不是「skipped」。
    expect(screen.getByText("构建摘要")).toBeInTheDocument();
    expect(screen.queryByText("skipped", { exact: true })).not.toBeInTheDocument();
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
    // F-G：面板自己的 data-testid 也被断言（此前只有 version-table 断言过）。
    expect(screen.getByTestId("reindex-panel")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "预览重建影响" }));

    const dialog = await screen.findByRole("group", { name: "重建确认" });
    expect(dialog).toHaveTextContent("无变化");
    // F-A：force 的 UI 归属——默认不勾选，label 即该控件的可访问名（不靠 group 的名字）。
    const forceBox = within(dialog).getByRole("checkbox", { name: FORCE_LABEL });
    expect(forceBox).not.toBeChecked();
    expect(within(dialog).getByText(FORCE_HINT)).toBeInTheDocument();
    // 指针 §1 的钉住断言：源侧行数里"药"的数字必须等于响应 corpus_counts.herbs 的真实值，
    // 且不得退化成占位符"—"（错键 `herb` 的静默信息丢失就死在这条上）。
    const counts = within(dialog).getByText(/源侧行数/);
    expect(counts).toHaveTextContent(`药 ${preview.corpus_counts.herbs}`);
    expect(counts).not.toHaveTextContent("药 —");

    await user.click(screen.getByRole("button", { name: "确认重建" }));
    // 先等到终态再读请求体：断言的时点确定，捕获的仍是同一次 POST 的体。
    const status = await screen.findByRole("status");
    // 指针 §2 + 规格 §8-验收13：不勾选就是非 force，才让后端复用语义可达。
    expect(postedBody).toEqual({ force: false });
    expect(status).toHaveTextContent("无需重建");
    // 复用路径的空值不许被播报成一次真实重建。
    expect(status).not.toHaveTextContent("重建完成");
    expect(screen.queryByText(/0 个 chunk/)).not.toBeInTheDocument();
    expect(screen.queryByText(/旧版本已 retired/)).not.toBeInTheDocument();
    // F-D：终态里不得残留写前的 preview 卡（「无变化 · 目标 commit abc123de」）。
    expect(screen.queryByRole("group", { name: "重建确认" })).not.toBeInTheDocument();
  });

  it("非复用成功播报版本/切片/耗时并回调 onDone", async () => {
    const user = userEvent.setup();
    const onDone = vi.fn();
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
    // F-D：done 终态同样不残留写前 preview 卡。
    expect(screen.queryByRole("group", { name: "重建确认" })).not.toBeInTheDocument();
  });

  it("勾选强制重建 → 同一条 POST 发 {force: true}，且 preview 报「无变化」也照样如实播报重建", async () => {
    // R-M5-17：preview 说无变化（will_reuse=true）时，维护者的"我不管，重来一遍"出口。
    // 后端 `reindex.py:157` 的复用短路 gate 在 `not force`，`admin.py:346` 原样透传，
    // 所以勾选后必须全量重建并新起版本行——播报也就不能是「无需重建」。
    const user = userEvent.setup();
    let postedBody: unknown;
    server.use(
      http.get("/api/admin/reindex/preview", () => HttpResponse.json(preview)),
      http.post("/api/admin/reindex", async ({ request }) => {
        postedBody = await request.json();
        return HttpResponse.json(freshReport);
      }),
    );
    render(<ReindexPanel onDone={() => {}} />);
    await user.click(screen.getByRole("button", { name: "预览重建影响" }));
    const dialog = await screen.findByRole("group", { name: "重建确认" });
    expect(dialog).toHaveTextContent("无变化");

    const forceBox = within(dialog).getByRole("checkbox", { name: FORCE_LABEL });
    await user.click(forceBox);
    expect(forceBox).toBeChecked();
    // 只有一个发请求的按钮：勾选不新增第二个入口。
    expect(screen.getAllByRole("button", { name: "确认重建" })).toHaveLength(1);

    await user.click(screen.getByRole("button", { name: "确认重建" }));
    const status = await screen.findByRole("status");
    expect(postedBody).toEqual({ force: true });
    expect(status).toHaveTextContent("重建完成：版本 #8");
    expect(status).not.toHaveTextContent("无需重建");
  });

  it("强制重建是一次性升级：请求返回后勾选复位，第二次确认不再 force", async () => {
    // 控制人裁定：勾选是「这一次强制重建」，不是「以后都强制」。若让它粘住，
    // 下一次点「确认重建」会在用户以为走复用路径的情况下再把整库强制重建一遍。
    const user = userEvent.setup();
    const bodies: unknown[] = [];
    server.use(
      http.get("/api/admin/reindex/preview", () => HttpResponse.json(preview)),
      http.post("/api/admin/reindex", async ({ request }) => {
        bodies.push(await request.json());
        return HttpResponse.json(freshReport);
      }),
    );
    render(<ReindexPanel onDone={() => {}} />);

    await user.click(screen.getByRole("button", { name: "预览重建影响" }));
    const first = await screen.findByRole("group", { name: "重建确认" });
    await user.click(within(first).getByRole("checkbox", { name: FORCE_LABEL }));
    await user.click(screen.getByRole("button", { name: "确认重建" }));
    expect(await screen.findByRole("status")).toHaveTextContent("重建完成：版本 #8");
    expect(bodies[0]).toEqual({ force: true });

    await user.click(screen.getByRole("button", { name: "预览重建影响" }));
    const second = await screen.findByRole("group", { name: "重建确认" });
    expect(within(second).getByRole("checkbox", { name: FORCE_LABEL })).not.toBeChecked();
    await user.click(screen.getByRole("button", { name: "确认重建" }));
    // 等到第二次请求落地再断言，避免读到还没 push 的数组长度。
    await vi.waitFor(() => expect(bodies).toHaveLength(2));
    expect(bodies[1]).toEqual({ force: false });
  });

  it("409 并发锁给出专门文案而不是通用失败，且不把状态机停在 running", async () => {
    const user = userEvent.setup();
    server.use(
      http.get("/api/admin/reindex/preview", () =>
        HttpResponse.json({ ...preview, changed: true })),
      // 后端 409 的真实 message 是「已有重建在跑，请稍后再试」（admin.py:343-344），
      // 与标签串一字不差。夹具刻意只写更短的那截：message 与标签相等时，
      // 「渲染标签」和「渲染原文」在断言上不可区分，F-C 要拦的那类回归就没法拦。
      http.post("/api/admin/reindex", () => HttpResponse.json(
        { detail: { code: "reindex_in_progress", message: "已有重建在跑" } }, { status: 409 })),
    );
    render(<ReindexPanel onDone={() => {}} />);
    await user.click(screen.getByRole("button", { name: "预览重建影响" }));
    await screen.findByRole("group", { name: "重建确认" });
    await user.click(screen.getByRole("button", { name: "确认重建" }));
    // F-C：断言 ADMIN_ERROR_LABELS.reindex_in_progress 的闭集全串，而不是 mock message
    // （「已有重建在跑」）的子串。`toHaveTextContent` 做的是子串匹配，只断言子串时
    // 「绕开标签表直接渲染 error.message」的回归照样全绿；整串相等才拦得住。
    const locked = await screen.findByRole("status");
    expect(locked).toHaveTextContent("已有重建在跑，请稍后再试");
    expect(locked.textContent).toBe("已有重建在跑，请稍后再试");
    // 指针 §5：409 后不得残留"进行中"的进行态；退回 confirm 允许再按一次。
    expect(screen.queryByText(/重建进行中/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "确认重建" })).toBeEnabled();
  });

  it("500 reindex_failed 显示闭集文案并进入 failed 终态", async () => {
    const user = userEvent.setup();
    server.use(
      http.get("/api/admin/reindex/preview", () =>
        HttpResponse.json({ ...preview, changed: true })),
      // 后端 500 的 message 是 f"重建失败：{exc}"（admin.py:351-352），比标签长，
      // 所以「整串等于标签」与「后端原文没泄漏」两条一起把「直接渲染 error.message」拦住。
      http.post("/api/admin/reindex", () => HttpResponse.json(
        { detail: { code: "reindex_failed", message: "重建失败：注入异常" } }, { status: 500 })),
    );
    render(<ReindexPanel onDone={() => {}} />);
    await user.click(screen.getByRole("button", { name: "预览重建影响" }));
    await screen.findByRole("group", { name: "重建确认" });
    await user.click(screen.getByRole("button", { name: "确认重建" }));
    // F-C：ADMIN_ERROR_LABELS.reindex_failed 的闭集全串（表里就是「重建失败」四个字，
    // 不是 mock message 的前缀截取）。整串相等 + 原文不泄漏，两条缺一不可判别。
    const status = await screen.findByRole("status");
    expect(status).toHaveTextContent("重建失败");
    expect(status.textContent).toBe("重建失败");
    expect(status).not.toHaveTextContent("注入异常");
    expect(screen.queryByText(/重建进行中/)).not.toBeInTheDocument();
    // 终态：确认按钮不再可点，回到可重新预览的入口。
    expect(screen.queryByRole("button", { name: "确认重建" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "预览重建影响" })).toBeInTheDocument();
    // F-D：failed 终态同样不残留写前 preview 卡。
    expect(screen.queryByRole("group", { name: "重建确认" })).not.toBeInTheDocument();
  });

  // —— F-B：`running` 是规格 §9:123 列为不可合并的独立状态面，此前一条断言都没有 ——
  it("running 态：延迟响应期间按钮禁用、标签与原因行都在，resolve 后进入终态", async () => {
    const user = userEvent.setup();
    // 真·延迟：handler 持有由测试释放的 promise，不用计时器（计时器测的是自己的 setTimeout）。
    let release!: () => void;
    const pending = new Promise<void>((resolve) => { release = resolve; });
    server.use(
      http.get("/api/admin/reindex/preview", () =>
        HttpResponse.json({ ...preview, changed: true, will_reuse: false })),
      http.post("/api/admin/reindex", async () => {
        await pending;
        return HttpResponse.json(freshReport);
      }),
    );
    render(<ReindexPanel onDone={() => {}} />);
    await user.click(screen.getByRole("button", { name: "预览重建影响" }));
    await screen.findByRole("group", { name: "重建确认" });
    await user.click(screen.getByRole("button", { name: "确认重建" }));

    // 请求在途：确认按钮仍在位但必须禁用，标签换成「重建中…」，并给出不合并的进行原因。
    const running = await screen.findByRole("button", { name: "重建中…" });
    expect(running).toBeDisabled();
    expect(screen.queryByRole("button", { name: "确认重建" })).not.toBeInTheDocument();
    expect(screen.getByText(/重建进行中（同步执行，整库约数秒）…/)).toBeInTheDocument();
    // F-A 第 4 点：running 期间 force 勾选框同样禁用，避免在途时改参数。
    expect(within(screen.getByRole("group", { name: "重建确认" }))
      .getByRole("checkbox", { name: FORCE_LABEL })).toBeDisabled();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();

    release();
    expect(await screen.findByRole("status")).toHaveTextContent("重建完成：版本 #8");
    expect(screen.queryByText(/重建进行中/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "重建中…" })).not.toBeInTheDocument();
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

  it("重建端点 401：POST 也走重新探针，不落到标签表也不停在 running/confirm", async () => {
    // 指针 §4 三条端点里此前唯一没测的一条（preview GET、index-versions GET 已有用例）。
    const user = userEvent.setup();
    let probes = 0;
    server.use(
      http.get("/api/admin/session", () => {
        probes += 1;
        // 第一次探针已登录（否则挂不上 children）；会话过期后重新探针 → locked。
        return HttpResponse.json(
          { enabled: true, authenticated: probes < 2, expires_at: probes < 2 ? 1 : null });
      }),
      http.get("/api/admin/reindex/preview", () => HttpResponse.json(preview)),
      http.post("/api/admin/reindex", () => HttpResponse.json(
        { detail: { code: "admin_unauthorized", message: "请先登录管理端" } }, { status: 401 })),
    );
    render(
      <AdminShell title="管理端概览" path="/admin">
        <ReindexPanel onDone={() => {}} />
      </AdminShell>,
    );
    await user.click(await screen.findByRole("button", { name: "预览重建影响" }));
    await screen.findByRole("group", { name: "重建确认" });
    expect(probes).toBe(1);
    await user.click(screen.getByRole("button", { name: "确认重建" }));
    // 探针由 1 次变 2 次 = 写操作路径也把 401 交回 AdminShell 的唯一探针入口。
    await waitFor(() => expect(probes).toBe(2));
    expect(await screen.findByRole("textbox", { name: "管理端口令" })).toBeInTheDocument();
    // 门接管后既不许出现登录卡的「口令不正确」，也不许残留写前的确认卡/进行中。
    expect(screen.queryByText("口令不正确")).not.toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "重建确认" })).not.toBeInTheDocument();
    expect(screen.queryByText(/重建进行中/)).not.toBeInTheDocument();
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

  // —— F-B 第 3 点：page.tsx 的失败+重试分支此前只被反向断言过（断言它不出现） ——
  it("index-versions 500：渲染失败文案与重试按钮，点重试重新发请求", async () => {
    const user = userEvent.setup();
    let versionRequests = 0;
    server.use(
      http.get("/api/admin/session", () => HttpResponse.json(
        { enabled: true, authenticated: true, expires_at: 1 })),
      // 该端点没有 try/except（admin.py:555-568），崩溃时是框架的纯文本 500：
      // parseApiError 拿不到 JSON 就保持 `http_error` + `HTTP 500`，
      // adminErrorLabel 对表里没有的 code 回落到 message——正是这条兜底路径需要正向覆盖。
      http.get("/api/admin/index-versions", () => {
        versionRequests += 1;
        return new HttpResponse("Internal Server Error", { status: 500 });
      }),
    );
    render(<AdminOverviewPage />);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("索引信息加载失败：HTTP 500");
    expect(within(alert).getByRole("button", { name: "重试" })).toBeInTheDocument();
    // 失败态不渲染版本表（ReindexPanel 独立可用，与数据加载失败是两面）。
    expect(screen.queryByTestId("version-table")).not.toBeInTheDocument();
    expect(screen.getByTestId("reindex-panel")).toBeInTheDocument();

    await user.click(within(alert).getByRole("button", { name: "重试" }));
    await waitFor(() => expect(versionRequests).toBe(2));
    expect(await screen.findByRole("alert")).toHaveTextContent("索引信息加载失败");
  });

  it("index-versions 成功：版本表渲染、不出现失败分支", async () => {
    server.use(
      http.get("/api/admin/session", () => HttpResponse.json(
        { enabled: true, authenticated: true, expires_at: 1 })),
      http.get("/api/admin/index-versions", () => HttpResponse.json(versions)),
    );
    render(<AdminOverviewPage />);
    expect(await screen.findByTestId("version-table")).toHaveTextContent("1818");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});

describe("QualitySection", () => {
  it("caption 即节标题、作为表格可访问名；表头数与单元格数相等", () => {
    render(<QualitySection id="herb_diff" title="① 药材差异"
      headers={["方名", "仅古制有", "仅克数本有"]}
      rows={[["五苓散", "猪苓", ""]]} exportList="herb_diff" />);
    const table = screen.getByRole("table");
    // 指针 §4：caption 就是节标题，不附加"不二次计算"之类后缀（否则可访问名对不上）。
    expect(table).toHaveAccessibleName("① 药材差异");
    expect(within(table).getByRole("columnheader", { name: "方名" })).toBeInTheDocument();
    expect(within(table).getAllByRole("columnheader")).toHaveLength(3);
    expect(within(table).getAllByRole("cell")).toHaveLength(3);
  });

  it("可导出的节给 CSV 链接，href 来自 adminCsvHref（不手写 ?list=）", () => {
    render(<QualitySection id="herb_diff" title="① 药材差异"
      headers={["方名"]} rows={[["五苓散"]]} exportList="herb_diff" />);
    expect(screen.getByRole("link", { name: "导出 CSV" }))
      .toHaveAttribute("href", "/api/admin/quality-report/export?list=herb_diff");
  });

  it("不可导出的聚合节不显示导出链接", () => {
    render(<QualitySection id="pending_queue" title="⑦ 待确认方名候选队列"
      headers={["维度", "取值", "数量"]} rows={[["判定", "pending", "64"]]} />);
    expect(screen.queryByRole("link", { name: "导出 CSV" })).not.toBeInTheDocument();
  });

  it("空数据给诚实的「本库暂无」，且不渲染成失败面", () => {
    render(<QualitySection id="herb_diff" title="① 药材差异"
      headers={["方名"]} rows={[]} exportList="herb_diff" />);
    expect(screen.getByText("本库暂无记录。")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("源文件#行号合成一格：列数仍等于表头、复制的是路径本身、且不是链接", async () => {
    const user = userEvent.setup();
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { clipboard: { writeText } });
    render(<QualitySection id="parse_failure_details" title="③ 解析失败明细"
      headers={["候选方名", "源文件#行号", "原因", "判定"]} pathColumn={1}
      rows={[["甲", "03-金匮/方剂库.md", "12", "multi_name_row", "pending"]]}
      exportList="parse_failure_details" />);
    const table = screen.getByRole("table");
    // R-M5-2：源行号被并进路径格，不出第五列——表头 4、单元格 4，相等才不被 axe 判死。
    expect(within(table).getAllByRole("columnheader")).toHaveLength(4);
    expect(within(table).getAllByRole("cell")).toHaveLength(4);
    expect(within(table).getByText("03-金匮/方剂库.md#12")).toBeInTheDocument();
    // §13-8：降级为"显示路径 + 行号 + 可复制"，绝不做成跳源文件的链接。
    expect(within(table).queryByRole("link", { name: /方剂库/ })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "复制源文件路径" }));
    expect(writeText).toHaveBeenCalledWith("03-金匮/方剂库.md#12");
    expect(await screen.findByRole("status")).toHaveTextContent("已复制源路径");
    vi.unstubAllGlobals();
  });
});

describe("质量报告页", () => {
  it("成功渲染七张表：恰好四张带 CSV 导出、三张聚合不带", async () => {
    server.use(
      http.get("/api/admin/session", () => HttpResponse.json(
        { enabled: true, authenticated: true, expires_at: 1 })),
      http.get("/api/admin/quality-report", () => HttpResponse.json(qualityReport)),
    );
    render(<AdminQualityPage />);
    await screen.findByTestId("quality-report");
    expect(screen.getAllByRole("table")).toHaveLength(7);
    // R-M5-19：③ 的文案改逐字「导出明细 CSV」（屏上计数、下载明细，文案不说谎），
    // 匹配串扩成两类文案的并集；链接仍恰好 4 条、href 集合一字未松。
    const exportLinks = screen.getAllByRole("link", { name: /导出(明细)? CSV/ });
    // 规格 §4.1：只有 herb_diff / dose_deviation / parse_failure_details / annotation_items 可导。
    expect(exportLinks).toHaveLength(4);
    const hrefs = exportLinks.map((link) => link.getAttribute("href"));
    expect(new Set(hrefs)).toEqual(new Set([
      "/api/admin/quality-report/export?list=herb_diff",
      "/api/admin/quality-report/export?list=dose_deviation",
      "/api/admin/quality-report/export?list=parse_failure_details",
      "/api/admin/quality-report/export?list=annotation_items",
    ]));
    // 三张聚合视图（⑤⑥⑦）不给导出——伪列名的下载不在本页承诺内。
    expect(hrefs).not.toContain("/api/admin/quality-report/export?list=dangling_herbs");
    expect(hrefs).not.toContain("/api/admin/quality-report/export?list=pending_queue");
  });

  // —— R-M5-19：③「计数在屏、明细在导出」的三条判别用例 ——
  it("③ 屏上渲染按原因计数表：57 在单元格内，明细表的列头与行不在页面上", async () => {
    server.use(
      http.get("/api/admin/session", () => HttpResponse.json(
        { enabled: true, authenticated: true, expires_at: 1 })),
      http.get("/api/admin/quality-report", () => HttpResponse.json(countQualityReport)),
    );
    render(<AdminQualityPage />);
    await screen.findByTestId("quality-report");
    const table = screen.getByRole("table", { name: FAILURES_TITLE });
    expect(within(table).getAllByRole("columnheader").map((h) => h.textContent)).toEqual(["原因", "数量"]);
    expect(within(table).getByRole("cell", { name: "57" })).toBeInTheDocument();
    // 裁定默认的行序：条数降序、再按原因字典型序——逐格断言渲染顺序。
    expect(within(table).getAllByRole("cell").map((c) => c.textContent))
      .toEqual(["no_formula_name", "57", "multi_name_row", "3"]);
    // 明细面整体缺席：R-M5-2 合成格若还在屏上，必然带这两列表头与「路径#行号」行。
    expect(screen.queryByRole("columnheader", { name: "候选方名" })).not.toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "源文件#行号" })).not.toBeInTheDocument();
    expect(screen.queryByText("03-金匮/方剂库.md#12")).not.toBeInTheDocument();
    // 分工说明行逐字在场。
    expect(within(table.closest("section") as HTMLElement)
      .getByText("屏上按原因计数，导出给到可下钻的明细行。")).toBeInTheDocument();
  });

  it("③ 的导出链接 href 仍来自 adminCsvHref(\"parse_failure_details\")", async () => {
    server.use(
      http.get("/api/admin/session", () => HttpResponse.json(
        { enabled: true, authenticated: true, expires_at: 1 })),
      http.get("/api/admin/quality-report", () => HttpResponse.json(qualityReport)),
    );
    render(<AdminQualityPage />);
    await screen.findByTestId("quality-report");
    const section = screen.getByRole("table", { name: FAILURES_TITLE }).closest("section") as HTMLElement;
    // ③ 恰好一条导出链接（getByRole 复数命中即失败），href 指向可下钻的明细清单。
    const link = within(section).getByRole("link");
    expect(link).toHaveAttribute("href", "/api/admin/quality-report/export?list=parse_failure_details");
  });

  it("③ 的链接文案逐字是「导出明细 CSV」而不是「导出 CSV」", async () => {
    server.use(
      http.get("/api/admin/session", () => HttpResponse.json(
        { enabled: true, authenticated: true, expires_at: 1 })),
      http.get("/api/admin/quality-report", () => HttpResponse.json(qualityReport)),
    );
    render(<AdminQualityPage />);
    await screen.findByTestId("quality-report");
    const section = screen.getByRole("table", { name: FAILURES_TITLE }).closest("section") as HTMLElement;
    // 可访问名逐字匹配（getByRole name 默认全等）：锁住「文案不说谎」——
    // 若实现退回「导出 CSV」，第一条就命中不到；若两处都渲染，第二条就失败。
    expect(within(section).getByRole("link", { name: "导出明细 CSV" })).toBeInTheDocument();
    expect(within(section).queryByRole("link", { name: "导出 CSV" })).not.toBeInTheDocument();
  });

  it("② 剂量偏差三键必填照渲染（不降级成占位符 —）", async () => {
    server.use(
      http.get("/api/admin/session", () => HttpResponse.json(
        { enabled: true, authenticated: true, expires_at: 1 })),
      http.get("/api/admin/quality-report", () => HttpResponse.json(qualityReport)),
    );
    render(<AdminQualityPage />);
    await screen.findByTestId("quality-report");
    const table = screen.getByRole("table", { name: "② 剂量偏差>50%" });
    expect(within(table).getByRole("cell", { name: "麻黄" })).toBeInTheDocument();
    expect(within(table).getByRole("cell", { name: "4" })).toBeInTheDocument();
    expect(within(table).getByRole("cell", { name: "30" })).toBeInTheDocument();
    expect(within(table).getByRole("cell", { name: "650" })).toBeInTheDocument();
    // 指针 §4：ancient_g/gram_g/deviation_pct 是必填三键，渲染的是值本身，不是占位符。
    expect(within(table).queryByRole("cell", { name: "—" })).not.toBeInTheDocument();
  });

  it("quality-report 500：正向渲染失败文案与重试按钮，绝不静默成空表", async () => {
    const user = userEvent.setup();
    let requests = 0;
    server.use(
      http.get("/api/admin/session", () => HttpResponse.json(
        { enabled: true, authenticated: true, expires_at: 1 })),
      http.get("/api/admin/quality-report", () => {
        requests += 1;
        return new HttpResponse("Internal Server Error", { status: 500 });
      }),
    );
    render(<AdminQualityPage />);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("报告加载失败：HTTP 500");
    expect(within(alert).getByRole("button", { name: "重试" })).toBeInTheDocument();
    expect(screen.queryAllByRole("table")).toHaveLength(0);
    await user.click(within(alert).getByRole("button", { name: "重试" }));
    await waitFor(() => expect(requests).toBe(2));
  });

  it("quality-report 空数据：诚实空态存在且不是失败文案（正向，两条独立面）", async () => {
    server.use(
      http.get("/api/admin/session", () => HttpResponse.json(
        { enabled: true, authenticated: true, expires_at: 1 })),
      http.get("/api/admin/quality-report", () => HttpResponse.json(emptyQualityReport)),
    );
    render(<AdminQualityPage />);
    expect((await screen.findAllByText("本库暂无记录。")).length).toBeGreaterThan(0);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByText(/报告加载失败/)).not.toBeInTheDocument();
  });

  it("quality-report 401：交回 AdminShell 重新探针，不查标签表也不显示加载失败", async () => {
    let probes = 0;
    server.use(
      http.get("/api/admin/session", () => {
        probes += 1;
        return HttpResponse.json(
          { enabled: true, authenticated: probes < 2, expires_at: probes < 2 ? 1 : null });
      }),
      http.get("/api/admin/quality-report", () => HttpResponse.json(
        { detail: { code: "admin_unauthorized", message: "请先登录管理端" } }, { status: 401 })),
    );
    render(<AdminQualityPage />);
    await waitFor(() => expect(probes).toBe(2));
    expect(await screen.findByRole("textbox", { name: "管理端口令" })).toBeInTheDocument();
    expect(screen.queryByText("口令不正确")).not.toBeInTheDocument();
    expect(screen.queryByText(/报告加载失败/)).not.toBeInTheDocument();
  });
});

describe("LogsDashboard", () => {
  it("四卡/窗口/limit 全部取响应值：queries_total 与明细条数故意不等、window_days 不是写死的 7", async () => {
    server.use(
      // queries_total=999 而明细只有 1 条：若组件自数条数会渲染成 1，指针 §2 要的就是这条判别。
      http.get("/api/admin/logs/summary", () => HttpResponse.json(
        { queries_total: 999, queries_recent: 5, refusal_rate: 0.6, avg_hit_count: 3.8, window_days: 30 })),
      // RefusalList 顶层带 window_days/limit（指针 §3），内联 {items} 会丢掉这俩回显。
      http.get("/api/admin/logs/refusals", () => HttpResponse.json(
        { window_days: 30, limit: 10, items: [{ query: "量子针灸", count: 2, top_score_max: 0.281 }] })),
      http.get("/api/admin/logs", () => HttpResponse.json({
        total: 5, limit: 25, offset: 0,
        items: [{ id: 1, created_at: "2026-11-02T00:00:00", session_id: null,
          query: "桂枝汤", intent: "B", refused: false, top_score: 1, hit_count: 10 }] })),
    );
    render(<LogsDashboard />);
    const dash = screen.getByTestId("logs-dashboard");
    // wrapper 首帧即渲染，testid 只能证存在； awaited 到数据驱动的卡片才算加载完成。
    expect(dash).toBeInTheDocument();
    await within(dash).findByText("累计提问");
    // 累计提问卡渲染的是响应 999，不是明细条数 1（看板不自我印证——规格 §8）。
    expect(within(dash).getByText("累计提问").closest("li")).toHaveTextContent("999");
    expect(within(dash).getByText("平均命中").closest("li")).toHaveTextContent("3.8");
    expect(within(dash).getByText("拒答率").closest("li")).toHaveTextContent("60%");
    // 窗口取响应 window_days=30，不是硬编码 7。
    expect(within(dash).getByText("近 30 日")).toBeInTheDocument();
    expect(within(dash).queryByText("近 7 日")).not.toBeInTheDocument();
    // limit 取明细响应回显的 25，不是写死的 50。
    expect(within(dash).getByText(/最近 25 条/)).toBeInTheDocument();
    expect(within(dash).queryByText(/最近 50 条/)).not.toBeInTheDocument();
    // 拒答榜窗口/limit 来自 RefusalList 回显——证明用的是 RefusalList 而非内联 {items}。
    expect(within(dash).getByText(/近 30 日 · 前 10 名/)).toBeInTheDocument();
    // 拒答榜按原文渲染（不归一化：错字/繁简归一是 E3 未决，规格 §8）。
    await within(dash).findByText("量子针灸");
    expect(within(dash).getByText("0.281")).toBeInTheDocument();
    // 隐私提示行（§8）。
    expect(within(dash).getByText(/日志含用户主诉原文/)).toBeInTheDocument();
  });

  it("非零拒答率不被四舍五入成 0%（诚实播报）", async () => {
    server.use(
      http.get("/api/admin/logs/summary", () => HttpResponse.json(
        { queries_total: 200, queries_recent: 100, refusal_rate: 0.004, avg_hit_count: 0, window_days: 7 })),
      http.get("/api/admin/logs/refusals", () => HttpResponse.json({ window_days: 7, limit: 50, items: [] })),
      http.get("/api/admin/logs", () => HttpResponse.json({ total: 0, limit: 50, offset: 0, items: [] })),
    );
    render(<LogsDashboard />);
    const dash = screen.getByTestId("logs-dashboard");
    await within(dash).findByText("拒答率");
    const rateCard = within(dash).getByText("拒答率").closest("li");
    expect(rateCard).toHaveTextContent("<1%");
    expect(rateCard).not.toHaveTextContent("0%");
  });

  it("意图筛选改的是请求参数，不是本地过滤", async () => {
    const user = userEvent.setup();
    const urls: string[] = [];
    server.use(
      http.get("/api/admin/logs/summary", () => HttpResponse.json(
        { queries_total: 1, queries_recent: 1, refusal_rate: 0, avg_hit_count: 0, window_days: 7 })),
      http.get("/api/admin/logs/refusals", () => HttpResponse.json({ window_days: 7, limit: 50, items: [] })),
      http.get("/api/admin/logs", ({ request }) => {
        urls.push(request.url);
        return HttpResponse.json({ total: 0, limit: 50, offset: 0, items: [] });
      }),
    );
    render(<LogsDashboard />);
    await screen.findByTestId("logs-dashboard");
    await user.selectOptions(screen.getByRole("combobox", { name: "按意图筛选" }), "F");
    await waitFor(() => expect(urls.at(-1)).toContain("intent=F"));
  });

  it("空数据：明细与拒答榜都空时给诚实空态，且不是失败文案（正向两条独立面）", async () => {
    server.use(
      http.get("/api/admin/logs/summary", () => HttpResponse.json(
        { queries_total: 0, queries_recent: 0, refusal_rate: 0, avg_hit_count: 0, window_days: 7 })),
      http.get("/api/admin/logs/refusals", () => HttpResponse.json({ window_days: 7, limit: 50, items: [] })),
      http.get("/api/admin/logs", () => HttpResponse.json({ total: 0, limit: 50, offset: 0, items: [] })),
    );
    render(<LogsDashboard />);
    const dash = screen.getByTestId("logs-dashboard");
    expect(await within(dash).findByText("本库暂无问答日志。")).toBeInTheDocument();
    expect(within(dash).getByText("窗口内没有拒答记录。")).toBeInTheDocument();
    expect(within(dash).queryByRole("alert")).not.toBeInTheDocument();
    expect(within(dash).queryByText(/日志加载失败/)).not.toBeInTheDocument();
  });

  it("加载失败（500）：失败文案与重试按钮存在，绝不静默成空看板（正向）", async () => {
    const user = userEvent.setup();
    let requests = 0;
    server.use(
      http.get("/api/admin/logs/summary", () => {
        requests += 1;
        return new HttpResponse("Internal Server Error", { status: 500 });
      }),
      http.get("/api/admin/logs/refusals", () => HttpResponse.json({ window_days: 7, limit: 50, items: [] })),
      http.get("/api/admin/logs", () => HttpResponse.json({ total: 0, limit: 50, offset: 0, items: [] })),
    );
    render(<LogsDashboard />);
    const dash = screen.getByTestId("logs-dashboard");
    const alert = await within(dash).findByRole("alert");
    expect(alert).toHaveTextContent("日志加载失败：HTTP 500");
    expect(within(alert).getByRole("button", { name: "重试" })).toBeInTheDocument();
    await user.click(within(alert).getByRole("button", { name: "重试" }));
    await waitFor(() => expect(requests).toBe(2));
  });
});

describe("问答日志页", () => {
  it("logs 端点 401：交回 AdminShell 重新探针，不查标签表也不显示加载失败", async () => {
    let probes = 0;
    const unauthorized = () => HttpResponse.json(
      { detail: { code: "admin_unauthorized", message: "请先登录管理端" } }, { status: 401 });
    server.use(
      http.get("/api/admin/session", () => {
        probes += 1;
        return HttpResponse.json(
          { enabled: true, authenticated: probes < 2, expires_at: probes < 2 ? 1 : null });
      }),
      http.get("/api/admin/logs/summary", unauthorized),
      http.get("/api/admin/logs/refusals", unauthorized),
      http.get("/api/admin/logs", unauthorized),
    );
    render(<AdminLogsPage />);
    await waitFor(() => expect(probes).toBe(2));
    expect(await screen.findByRole("textbox", { name: "管理端口令" })).toBeInTheDocument();
    expect(screen.queryByText("口令不正确")).not.toBeInTheDocument();
    expect(screen.queryByText(/日志加载失败/)).not.toBeInTheDocument();
  });
});
