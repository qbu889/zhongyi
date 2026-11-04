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
/** 真重建成功路径的 asdict(ReindexReport)（非复用：counts 有值、chunks 是新写入数）。 */
const freshReport: ReindexReport = {
  ...reusedReport, reused: false, version_id: 8, chunks: 1822, elapsed_ms: 1634,
  counts: { formula: 424, herb: 379, acupoint: 346, case: 30 },
  skipped: { pair_missing_variant: 4 },
};

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
