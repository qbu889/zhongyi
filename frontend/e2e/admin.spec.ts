import { expect, test, type Locator, type Page } from "@playwright/test";

import { blocking } from "./a11y-helpers";

// —— 顺序是契约，不是巧合（F-2 / 规格 §11:154 把这套件就叫 serial）——
// 本文件多条用例共享同一个可变库（zhongyi_e2e）与同一份索引，彼此有真实的声明顺序依赖：
//   1) 「管理端无障碍 /admin/pending（含已判定行…）」扫的是 merged 留痕态，那条已判定行是
//      「归并即时生效…（全程不重建）」用例写入的——见文件末尾该 axe 用例前的注释；
//   2) 「重建 preview 到确认（reused）」读的是刚 bootstrap 的索引基线，
//      「强制重建走 UI（force）」会把 ready 版本 retire、另起新行，两者都在动同一份索引。
// 之前只靠 playwright.config.ts 的 workers:1 + fullyParallel:false 兜底成立；一句 `-j 2`、
// `--shuffle` 或 `-g "管理端无障碍"` 就能把它打破，共享可变库上并发重建还会撞 REINDEX_LOCK 出 409。
// 用 test.describe.configure({ mode: "serial" }) 把"按声明顺序、一次一条"变成显式契约
// （与 M4 的 e2e/chat.spec.ts 同一写法），任何断言内容都不因此改动。
test.describe.configure({ mode: "serial" });

// —— 口令（R-M5-24 / T15 指针 §1）——
// 本文件零口令字面量：TOKEN 只从 process.env.E2E_ADMIN_TOKEN 取。
// 后端 fail-closed（未设置或 <16 字符 → /api/admin/* 全 503 admin_disabled），
// 所以登录前必须断言"启用但未登录"态（登录卡在位、"管理端未启用"文案不在）；
// 断言失败时 message 直接点名的就是"口令太短/未设置"。playwright.config.ts 已按
// 同一口径把 admin project 整组排除，这里是第二道防线（比如有人改 config 单跑本文件）。
const TOKEN = process.env.E2E_ADMIN_TOKEN ?? "";

// 剪贴板权限整文件授予：Chromium 默认拒绝 navigator.clipboard.writeText，
// 不授权的话复制按钮只能走失败分支，"真实结果"（指针 §3.3）永远测不到。
// 失败分支文案仍会被如实断言——若本环境把权限也拒了，用例会以实际 DOM 报错，
// 而不是假装成功。
test.use({ permissions: ["clipboard-read", "clipboard-write"] });

/** 登录门三态判别（规格 §9/§11 的"未启用/未登录/加载失败"三态三文案）：
 * 先确认是 locked（登录卡出现），而不是 disabled（未启用文案）。 */
async function tokenBox(page: Page): Promise<Locator> {
  const box = page.getByRole("textbox", { name: "管理端口令" });
  await expect(
    box,
    "管理端未启用：E2E_ADMIN_TOKEN 未设置或长度 <16，后端 fail-closed（全 503 admin_disabled），登录卡不会出现",
  ).toBeVisible();
  await expect(page.getByText("管理端未启用")).toHaveCount(0);
  return box;
}

async function login(page: Page) {
  await page.goto("/admin");
  const box = await tokenBox(page);
  await box.fill(TOKEN);
  await page.getByRole("button", { name: "进入管理端" }).click();
  // 登录成功后门重新探针：locked 态的登录卡必须消失（换成内容区），
  // 否则后面的用例都会对着登录卡空断言。
  await expect(box).toBeHidden();
}

// —— 登录门不变量（规格 §9；指针 §4：不得退化成"只断言有登录卡"）——
// 未登录访问 /admin/*：只见登录门；页面文本里不得出现任何报告/队列/日志内容
// （AdminShell 在未登录时根本不渲染子页，数据端点一个都不该发出去）。
const GATE_ROUTES: Array<{ path: string; title: string; forbidden: [string, string] }> = [
  { path: "/admin", title: "管理端概览", forbidden: ["重建索引", "版本历史"] },
  {
    path: "/admin/quality",
    title: "质量报告",
    forbidden: ["① 药材差异", "⑦ 待确认方名候选队列"],
  },
  {
    path: "/admin/pending",
    title: "候选方名审核",
    forbidden: ["按判定筛选", "待确认方名（D7 候选队列）"],
  },
  {
    path: "/admin/logs",
    title: "问答日志",
    forbidden: ["日志含用户主诉原文", "高频拒答词"],
  },
];

for (const { path, title, forbidden } of GATE_ROUTES) {
  test(`重建与审核需要登录：${path} 未登录只见登录门、看不到任何管理数据`, async ({ page }) => {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1, name: title })).toBeVisible();
    await expect(page.getByText("管理端登录")).toBeVisible();
    for (const text of forbidden) {
      await expect(page.getByText(text)).toHaveCount(0);
    }
    // 服务端不变量：数据端点在登录门前一律 401（未启用时才是 503，所以这条
    // 同时反向证明了"口令已配置、门是真门"）。
    const report = await page.request.get("/api/admin/quality-report");
    expect(report.status()).toBe(401);
  });
}

test("口令错误保留 401 文案", async ({ page }) => {
  await page.goto("/admin");
  const box = await tokenBox(page);
  // "definitely-wrong-token" 是错误口令哨兵值，不是凭据（R-M5-24 禁的是真口令字面量）。
  await box.fill("definitely-wrong-token");
  await page.getByRole("button", { name: "进入管理端" }).click();
  await expect(page.getByRole("status")).toContainText("口令不正确");
});

test("质量报告七张清单渲染，且导出链接可用", async ({ page }) => {
  await login(page);
  await page.goto("/admin/quality");
  const report = page.getByTestId("quality-report");
  await expect(report).toBeVisible();
  // 七节各按 region（section 的 aria-labelledby 名）断言，不用裸 getByText：
  // 同名文本同时出现在 h2 与 <caption> 里，getByText 会撞 strict mode。
  for (const marker of [
    /^① 药材差异/, /^② 剂量偏差>50%/, /^③ 解析失败/, /^④ 注记被误抽为药味/,
    /^⑤ herb_id 悬空/, /^⑥ 换算状态五态分布/, /^⑦ 待确认方名候选队列/,
  ]) {
    await expect(report.getByRole("region", { name: marker })).toBeVisible();
  }
  // 规格 §4.1：七个数据面只有四个行清单可导；③ 的文案逐字「导出明细 CSV」。
  await expect(report.getByRole("link", { name: "导出 CSV", exact: true })).toHaveCount(3);
  const detailExport = report.getByRole("link", { name: "导出明细 CSV" });
  await expect(detailExport).toHaveCount(1);
  await expect(detailExport).toHaveAttribute(
    "href", "/api/admin/quality-report/export?list=parse_failure_details");

  // CSV 真下载（page.request 复用浏览器上下文的登录 cookie）：首行表头逐字对齐后端。
  const csv = await page.request.get("/api/admin/quality-report/export?list=herb_diff");
  expect(csv.status()).toBe(200);
  expect(csv.headers()["content-type"]).toContain("text/csv");
  expect((await csv.text()).split("\n")[0]).toBe("方名,pair_id,仅古制有,仅克数本有");
});

/** 与 LogsDashboard.tsx 的 formatRate 同一镜像实现：断言"卡上数字由响应导出"时，
 * 0 也要诚实地渲染成 0%，0<rate<0.005 渲染成 <1%，不许塌成 0。 */
function formatRefusalRate(rate: number): string {
  const pct = rate * 100;
  if (rate > 0 && pct < 1) return "<1%";
  return `${Math.round(pct)}%`;
}

test("问答日志页：四卡数字来自响应本身，含拒答榜、明细表与隐私提示", async ({ page }) => {
  await login(page);
  await page.goto("/admin/logs");
  const dash = page.getByTestId("logs-dashboard");
  await expect(dash).toBeVisible();

  // 规格 §8 的隐私提示：工程侧主动提示日志含主诉原文。
  await expect(dash.getByText("日志含用户主诉原文，属敏感信息")).toBeVisible();

  // 四张卡的数字一律与 /logs/summary 响应逐一对齐（指针 §2：组件不自数、不自算）。
  const summary = await (await page.request.get("/api/admin/logs/summary?window_days=7")).json();
  const cards = dash.getByRole("list", { name: "概览指标" }).getByRole("listitem");
  await expect(cards).toHaveCount(4);
  const cardTexts = await cards.allInnerTexts();
  expect(cardTexts[0]).toContain("累计提问");
  expect(cardTexts[0]).toContain(String(summary.queries_total));
  expect(cardTexts[1]).toContain(`近 ${summary.window_days} 日`);
  expect(cardTexts[1]).toContain(String(summary.queries_recent));
  expect(cardTexts[2]).toContain("拒答率");
  expect(cardTexts[2]).toContain(formatRefusalRate(summary.refusal_rate));
  expect(cardTexts[3]).toContain("平均命中");
  expect(cardTexts[3]).toContain(String(summary.avg_hit_count));

  // 拒答榜：渲染必须与 /logs/refusals 响应同形（有行则有表，无行则有诚实空态）。
  const refusals = await (await page.request.get("/api/admin/logs/refusals?window_days=7")).json();
  await expect(dash.getByRole("heading", { name: "高频拒答词（语料补缺清单）" })).toBeVisible();
  if (refusals.items.length > 0) {
    const top = refusals.items[0];
    const topRows = dash.getByRole("row").filter({ hasText: top.query });
    await expect(topRows).not.toHaveCount(0);
    await expect(topRows.first()).toContainText(String(top.count));
  } else {
    await expect(dash.getByText("窗口内没有拒答记录。")).toBeVisible();
  }

  // 明细表：标题的"最近 N 条"与合计"N 条"都取响应回显值（limit/total），不是写死的 50。
  const logs = await (await page.request.get("/api/admin/logs?limit=50")).json();
  await expect(dash.getByRole("heading", { name: `最近 ${logs.limit} 条` })).toBeVisible();
  if (logs.items.length > 0) {
    await expect(dash.getByText(`共 ${logs.total} 条`)).toBeVisible();
    const first = logs.items[0];
    const detailRows = dash.getByRole("row").filter({ hasText: first.query });
    await expect(detailRows).not.toHaveCount(0);
    await expect(detailRows.first()).toContainText(first.intent);
  } else {
    await expect(dash.getByText("本库暂无问答日志。")).toBeVisible();
  }
});

test("重建 preview 到确认：hash 未变时明确报告无需重建", async ({ page }) => {
  await login(page);
  await page.goto("/admin");
  // 1818 = e2e 库重建基线的切片数（scripts/e2e_bootstrap.py 全量重建后实测值）。
  await expect(page.getByTestId("version-table")).toContainText("1818");
  const panel = page.getByTestId("reindex-panel");

  await page.getByRole("button", { name: "预览重建影响" }).click();
  const dialog = page.getByRole("group", { name: "重建确认" });
  await expect(dialog).toBeVisible();
  // 刚 bootstrap 完的库语料四元组未变：preview 必须是"无变化"而不是"有变化"。
  await expect(dialog).toContainText("无变化 · 目标 commit");
  const forceBox = page.getByRole("checkbox", { name: "强制重建（即使语料与规则未变化）" });
  await expect(forceBox).not.toBeChecked();

  await page.getByRole("button", { name: "确认重建" }).click();
  await expect(panel.getByRole("status")).toContainText("无需重建");
  // 指针 §3.1：默认路径（不勾选）走后端 reused，播报必须是"无需重建"，
  // **不得**被断言/渲染成"重建完成"——那是谎称数据换过了。
  await expect(panel).not.toContainText("重建完成");
});

/** 队列内容定位选行（M4 教训：不依赖列表顺序）：在 pending 视图里找一个
 * `raw_name` 不与任何现存方名重名、且在表内唯一命中该行的候选。
 * avoidNames 用于防串扰：重名候选归并后会改变别的用例看到的精确命中集合。
 * 行集锚在 `data-testid="pending-row"`（PendingTable 的主行 <tr>）上而不是"任意 <tr>"：
 * 已判定行渲染主行+colSpan 留痕行两个 <tr>，"row 含文本"的定位把命中集合绑死在两行
 * 文本的拼接形状上——修复轮 2 起全文件不再用 `getByRole("row")` 判别候选行。
 * 注意 `filter({ has })` 的内层 locator 必须以 page 为根（实测 1.64.1：以 table
 * 为根的 has 恒 0 命中——has 在候选行内部再解一次，外层 base 与它无关）。 */
async function pickPendingCandidate(table: Locator, page: Page, avoidNames: Set<string>) {
  const actionable = table
    .getByTestId("pending-row")
    .filter({ has: page.getByRole("button", { name: "归并到既有方" }) });
  const count = await actionable.count();
  expect(count, "候选队列 pending 视图应有可操作行").toBeGreaterThan(0);
  let row: Locator | undefined;
  let candidate = "";
  for (let index = 0; index < count; index += 1) {
    const name = (await actionable.nth(index).locator("td").first().innerText()).trim();
    if (!name || avoidNames.has(name)) continue;
    const matches = actionable.filter({ hasText: name });
    if ((await matches.count()) !== 1) continue;
    row = matches;
    candidate = name;
    break;
  }
  expect(candidate, "队列里应能找到一条不与现存方名重名、可唯一定位的候选方名").toBeTruthy();
  return { row: row as Locator, candidate };
}

/** 从版本表 innerText 抠四类计数（渲染形状：`方 N · 药 N · 穴 N · 案 N · 切片 N`）。 */
function parseCounts(text: string) {
  const grab = (label: string): number => {
    const matched = new RegExp(`${label} (\\d+)`).exec(text);
    expect(matched, `版本表应渲染「${label} N」计数`).toBeTruthy();
    return Number((matched as RegExpExecArray)[1]);
  };
  return { formula: grab("方"), herb: grab("药"), acupoint: grab("穴"), case: grab("案") };
}

test("归并即时生效：审核后的别名能在四大库检索里精确命中目标方（全程不重建）", async ({
  page, request,
}) => {
  await login(page);

  // 现存方名全集（/api/formulas 的 limit 上限 100，翻页拿全）：候选名撞名的行不进归并。
  const existingNames = new Set<string>();
  for (let offset = 0; ; offset += 100) {
    const list = await (await request.get(`/api/formulas?limit=100&offset=${offset}`)).json();
    for (const item of list.items) existingNames.add(item.canonical_name);
    if (list.items.length < 100) break;
  }
  // 归并目标沿用 M4 用例的挑法：limit 取够后按 canonical_name 精确挑，不拿 items[0]。
  const targetList = await (await request.get("/api/formulas?q=桂枝汤&limit=100")).json();
  const target = targetList.items.find(
    (item: { canonical_name: string }) => item.canonical_name === "桂枝汤",
  );
  expect(target, "e2e 库应有桂枝汤").toBeTruthy();

  await page.goto("/admin/pending");
  const table = page.getByTestId("pending-table");
  await expect(table).toBeVisible();
  const { row, candidate } = await pickPendingCandidate(table, page, existingNames);

  // —— 以下全部走 UI：三动作 + 确认步，中间不碰 decision API、不点任何重建 ——
  await row.getByRole("button", { name: "归并到既有方" }).click();
  await row.getByRole("searchbox", { name: "检索" }).fill(target.canonical_name);
  await row.getByRole("button", { name: `选择 ${target.canonical_name}` }).click();
  await expect(row.getByText(`目标：${target.canonical_name}`, { exact: true })).toBeVisible();
  // 成功播报（"已记录判定。"）只活一次提交：onChanged 让队列重取、PendingTable 整棵
  // 卸载重挂、message 归零——真网络时序下断这条瞬时态必竞态。断言换成**可持久验证**的
  // 三件套：UI 触发的那次 POST 响应（waitForResponse，不发自己的请求）、队列状态迁移、
  // "已归并"筛选下的留痕行。失败分支的播报（不触发重载）本来就持久，归本组件单测覆盖。
  const decisionResponse = page.waitForResponse((res) =>
    res.url().endsWith("/decision") && res.request().method() === "POST");
  await row.getByRole("button", { name: "确认归并" }).click();
  const decision = await (await decisionResponse).json();
  expect(decision.item.decision).toBe("merged");
  expect(decision.item.decided_by).toBe("admin");
  expect(decision.alias_created, "新候选第一次归并应真的插入别名行").toBe(true);
  // 队列刷新：该候选离开 pending 视图（默认筛选下不再出现）。锚主行 testid。
  await expect(
    table.getByTestId("pending-row").filter({ hasText: candidate }),
  ).toHaveCount(0);
  // —— 修复轮 2 加的 settle-wait，修复轮 3 之后它的职责要说清（别让下一位读者以为缺了它就红）——
  // 它现在等的是**网络往返**：onChanged → page.tsx 的 nonce 重载发出去的那条 GET decision=pending
  // 真的落地、表体重新渲染出来，于是上面的 toHaveCount(0) 是在"重载后的数据"上验证的，
  // 而不是在 setData(null) 造成的整棵卸载"零行"窗口里假过（那一窗口里候选主行本来就不在 DOM）。
  // 它**不再**是用来绕开"旧响应覆盖新筛选"的：那个产品缺陷已在修复轮 3 于 page.tsx 里用
  // 自增序号的陈旧响应守卫堵死（晚到的旧筛选结果整条丢弃），并由
  // tests/unit/admin-pending.test.tsx「陈旧响应守卫」一条确定性单测钉住（去掉守卫必翻红）。
  // 也就是说：即使删掉本行，merged 视图也不会再被旧 pending 列表覆盖——本行保留的理由是上面那句
  // "让离场断言不可假过"，属于正当的稳健化，不是掩盖。根因时间线见 task-15-report.md 修复轮 2/3。
  await expect(table).toBeVisible();

  // 已判定状态在"已归并（merged）"筛选下持久可见：判定列 merged + 次级留痕行。
  // 定位不再依赖"两行怎么拆、哪行含文本"：主行 testid + 候选名唯一锚定主行本身，
  // 留痕行（colSpan=7）另行独立断言存在。
  await page.getByRole("combobox", { name: "按判定筛选" }).selectOption("merged");
  const decidedRow = table.getByTestId("pending-row").filter({ hasText: candidate });
  await expect(decidedRow).toHaveCount(1);
  await expect(decidedRow).toContainText("merged");
  await expect(table.getByText("判定留痕：")).not.toHaveCount(0);

  // 规格 §14-4 的核心证明：归并后**不重建索引**，精确通道（直查 formula_alias）就能命中。
  const hits = await (await request.post("/api/search", {
    data: { query: candidate, kind: ["formula"], top: 5 },
  })).json();
  const exact = (hits.hits as { title: string; match: string }[]).find(
    (hit) => hit.title === target.canonical_name,
  );
  expect(exact, `归并后「${candidate}」应精确命中 ${target.canonical_name}`).toBeTruthy();
  expect(exact?.match, "必须走精确通道（exact），不是向量/字面兜出来的").toBe("exact");

  // UI 检索证明：方剂库检索框输入候选名 → 联想面板"精确"组出现目标方 → 点进详情。
  await page.goto("/formulas");
  await page.getByRole("searchbox", { name: "检索" }).fill(candidate);
  const suggest = page.getByTestId("suggest");
  await expect(suggest).toBeVisible();
  await expect(suggest.getByText("精确")).toBeVisible();
  await suggest.getByRole("link", { name: target.canonical_name }).click();
  await expect(page.getByTestId("formula-detail")).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`/formulas/${target.id}\\b`));
});

test("路径#行号合成格：真实浏览器里可整段选中，复制按钮给真实结果", async ({ page }) => {
  await login(page);
  await page.goto("/admin/pending");
  const table = page.getByTestId("pending-table");
  await expect(table).toBeVisible();
  const { row } = await pickPendingCandidate(table, page, new Set());

  // select-all 必须在浏览器里验（jsdom 拿不到计算样式，T13 评审推到本轮）：
  // 合成格 span 的计算样式 userSelect === "all"。
  const pathSpan = row.locator(".select-all");
  expect(
    await pathSpan.evaluate((el) => getComputedStyle(el).userSelect),
    "路径#行号合成格应可整段选中",
  ).toBe("all");

  // 第二种验法：程序化选中后，document.getSelection() 文本 == 该格文本。
  const spanText = (await pathSpan.innerText()).trim();
  expect(spanText, "e2e 库候选行都带行号，合成格应是 `路径#行号` 形状").toMatch(/\S#\d+/);
  await pathSpan.evaluate((el) => {
    const range = document.createRange();
    range.selectNodeContents(el);
    const selection = window.getSelection();
    selection?.removeAllRanges();
    selection?.addRange(range);
  });
  expect(await page.evaluate(() => window.getSelection()?.toString() ?? "")).toBe(spanText);

  // 复制按钮的真实结果：本文件已授予 clipboard-write/read，成功分支必须给
  // "已复制源路径"，且剪贴板内容与合成格文本逐字相等。
  await row.getByRole("button", { name: "复制源文件路径" }).click();
  await expect(row.getByRole("status")).toHaveText("已复制源路径");
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(spanText);
});

test("强制重建走 UI：勾选 → 确认 → 版本行 +1、四类计数不减少", async ({ page }) => {
  // —— 超时按"实测 × 有依据的余量"定（F-3），别把两件事混成一个数 ——
  // 本机这一轮实测（本地 embedder、无网络）：
  //   • 冷启动 bootstrap：start_e2e.sh 里的 drop_all + create_all + run_reindex 整库重建，
  //     实测 ~3.0s（`e2e db ready: version=1 chunks=1818`）。它由 backend webServer 触发、
  //     受 playwright.config.ts 的 webServer.timeout(180s) 约束，**不在本用例里、也不需要本
  //     用例的 timeout 覆盖**——之前注释写的"整库重建实测约 3 分钟"是把指针的估计当成了实测，
  //     控制人已采纳量级更正，T16 runbook 按这个 3 秒级拆分写。
  //   • 在 UI 里点一次 force 重建（本用例）：整条用例（登录+预览+同步重建+版本表校验）实测 ~3.1s，
  //     同步重建是其中主项，量级同样是秒级。
  // test.setTimeout 收到 120s：它必须大于本用例内部的「重建等待 60s」+「新版本行 ready 重取 30s」
  //   + 登录/预览的几秒，故取 120s（≈3.1s 实测的 ~40×，覆盖语料较 1818 基线增长后重建耗时线性上升、
  //   机器负载/CI 冷缓存的放大），同时把"真挂住"暴露时间从原来的 600s（白等 9 分钟）压到 ≤2 分钟。
  test.setTimeout(120_000);
  await login(page);
  await page.goto("/admin");
  const panel = page.getByTestId("reindex-panel");
  const table = page.getByTestId("version-table");
  await expect(table).toContainText("（ready）");
  const rowsBefore = await table.getByRole("row").count();
  const countsBefore = parseCounts(await table.innerText());

  await page.getByRole("button", { name: "预览重建影响" }).click();
  const dialog = page.getByRole("group", { name: "重建确认" });
  await expect(dialog).toBeVisible();
  // R-M5-17：force 的唯一 UI 归属就是这个勾选框——本用例全程不发 request.post，
  // 只有"勾选 + 确认重建"一次写库路径。
  const forceBox = page.getByRole("checkbox", { name: "强制重建（即使语料与规则未变化）" });
  await expect(forceBox).not.toBeChecked();
  await forceBox.check();
  await page.getByRole("button", { name: "确认重建" }).click();

  // 重建结果等待收到 60s：本机一次 force 重建实测 ~3s，60s ≈20×（覆盖语料增长使重建耗时随 chunk
  // 数线性上升 + 冷/负载机放大）。刻意 < test.setTimeout(120s)，真挂住先在这里给可读报错而非撞总时限。
  await expect(panel.getByRole("status")).toContainText(/重建完成：版本 #\d+/, {
    timeout: 60_000,
  });
  const doneText = await panel.innerText();
  const newVersion = /重建完成：版本 #(\d+)/.exec(doneText)?.[1];
  expect(newVersion, "重建完成播报应带新版本号").toBeTruthy();

  // 播报之后 onDone 触发版本表重取：新行 ready、行数 +1、四类计数不减少、单 ready 不变量。
  await expect(table).toContainText(`${newVersion}（ready）`, { timeout: 30_000 });
  expect(await table.getByRole("row").count()).toBe(rowsBefore + 1);
  const countsAfter = parseCounts(await table.innerText());
  expect(countsAfter.formula).toBeGreaterThanOrEqual(countsBefore.formula);
  expect(countsAfter.herb).toBeGreaterThanOrEqual(countsBefore.herb);
  expect(countsAfter.acupoint).toBeGreaterThanOrEqual(countsBefore.acupoint);
  expect(countsAfter.case).toBeGreaterThanOrEqual(countsBefore.case);
  // 旧版本转 retired、屏上只剩唯一一行 ready（（ready）只在"当前索引"dl 里出现）。
  await expect(table.getByText("（ready）")).toHaveCount(1);
  await expect(table).toContainText("retired");
});

// —— axe 扫描（指针 §3.2）：管理端四个路由都扫，且 /admin/pending 必须扫到
// "含已判定行"的状态——Task 13 的 colSpan 留痕行是全计划唯一没被 axe 验证过的
// DOM 形状，只扫全 pending 的队列等于没扫。这里的"已判定"状态不是凭空造的：它依赖
// 前面的「归并即时生效：审核后的别名能在四大库检索里精确命中目标方（全程不重建）」用例
// 先真判定一条（该用例把候选归并到 桂枝汤、留下 merged 决策 + colSpan 留痕行）；
// serial 声明保证它先于本条 axe 用例执行，不再只是"排在上面"的巧合。
for (const [path, testid] of [
  ["/admin", "version-table"],
  ["/admin/quality", "quality-report"],
  ["/admin/logs", "logs-dashboard"],
] as const) {
  test(`管理端无障碍 ${path}`, async ({ page }) => {
    await login(page);
    await page.goto(path);
    await expect(page.getByTestId("admin-shell")).toBeVisible();
    // 等内容面渲染完再扫：对着"读取中…"骨架做 axe 什么都证明不了。
    await expect(page.getByTestId(testid)).toBeVisible();
    expect(await blocking(page)).toEqual([]);
  });
}

test("管理端无障碍 /admin/pending（含已判定行与判定留痕行）", async ({ page }) => {
  await login(page);
  await page.goto("/admin/pending");
  const table = page.getByTestId("pending-table");
  await expect(table).toBeVisible();
  // 判定筛选切到"已归并（merged）"：屏上是已判定行 + colSpan 留痕行。
  await page.getByRole("combobox", { name: "按判定筛选" }).selectOption("merged");
  await expect(table.getByText("判定留痕：")).not.toHaveCount(0);
  // 留痕行形状证据（读属性，不是断列表顺序）：次级行的 td 跨全部 7 列。
  expect(await table.getByText("判定留痕：").first().evaluate(
    (el) => (el as HTMLTableCellElement).colSpan,
  )).toBe(7);
  expect(await blocking(page)).toEqual([]);
});

// —— F-1（§14-11 第三态）：重建确认卡从没被 axe 扫过 ——
// 概览/质量/日志/待审四个面扫了，但规格 §14-11 点名的第三个状态——ReindexPanel.tsx:96 那个
// role="group" aria-label="重建确认"（本轮新加了 input#reindex-force + label 的地方）——只在
// 功能用例里被点过、没被无障碍扫过。这里取 F-1 的第二种方案（加第 5 条 axe 用例）而不是往既有
// 重建用例里塞一行断言，理由：① 它把"§14 三态都扫过"做成一条独立、可命名的交付物，和上面四条
// axe 用例同组；② 用例显式断言确认卡"可见"后才扫描——预览只发一个 GET /reindex/preview（只读、
// 不写库、不点确认），phase 停在 confirm、卡片不会自关，扫描一定发生在卡片在屏的时刻（可判别，
// 不会退化成"卡关了再扫"）；③ 只读预览不碰归并/force 的写库顺序，与 serial 声明互不干扰。
test("管理端无障碍 /admin 重建确认卡（§14-11 第三态：含 force 勾选框与 label）", async ({ page }) => {
  await login(page);
  await page.goto("/admin");
  const panel = page.getByTestId("reindex-panel");
  await expect(panel).toBeVisible();

  await page.getByRole("button", { name: "预览重建影响" }).click();
  const dialog = page.getByRole("group", { name: "重建确认" });
  // 断言之前的状态里确认卡确实可见（卡片含目标 commit 文案 + 本轮新增的 force 勾选框）。
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText("· 目标 commit");
  const forceBox = page.getByRole("checkbox", { name: "强制重建（即使语料与规则未变化）" });
  await expect(forceBox).toBeVisible();
  // 卡片在屏时扫描：原生 checkbox 由 htmlFor label 取得可访问名、group 有 aria-label，
  // 这正是本轮交付要证明"扫到了卡片本身"而非扫过登录后的空概览。
  expect(await blocking(page)).toEqual([]);
});
