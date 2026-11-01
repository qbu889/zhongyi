import { expect, test, type Page } from "@playwright/test";

test.describe.configure({ mode: "serial" });

async function ask(page: Page, question: string) {
  await page.goto("/chat");
  // 提交走 Composer 的 Enter 分支（非 Shift 且非输入法组合态即提交，见
  // components/chat/Composer.tsx），不用鼠标；`send` 按钮本身仍由 e2e/a11y.spec.ts
  // 的 `getByTestId("send").click()` 覆盖（两处用例各一次）。
  const composer = page.getByTestId("composer");
  await composer.fill(question);
  await composer.press("Enter");
}

test("状态机、进度、角标与抽屉", async ({ page }) => {
  await ask(page, "咳嗽气喘痰白不能平躺");
  await expect(page.getByTestId("intent-badge")).toContainText("A 辨证");
  await expect(page.getByTestId("progress")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("answer-body")).toBeVisible();
  await expect(page.getByTestId("answer-body")).toContainText("射干麻黄汤");
  await expect(page.getByTestId("answer-body")).toContainText("本回答基于本地蒸馏语料整理");

  const firstSup = page.getByTestId("citation-sup").first();
  const citationTitle = ((await firstSup.getAttribute("aria-label")) ?? "").replace("查看出处 ", "");
  expect(citationTitle).not.toBe("");
  await firstSup.hover();
  await expect(page.getByRole("tooltip")).toContainText(citationTitle);
  // Radix 的可悬停 tooltip 在 trigger 的 pointerleave 上先建「 grace area」，
  // 关闭要靠其后的一次 document pointermove（监听器是 React commit 之后才挂上的）。
  // 真实的鼠标移动总是一连串事件，Playwright 的单次 move 只有一帧，所以要补第二次移动，
  // 断言的仍是产品行为：指针移开后摘要卡必须消失。
  await page.mouse.move(0, 0);
  await page.mouse.move(1, 1);
  await expect(page.getByRole("tooltip")).toHaveCount(0);

  await firstSup.click();
  const drawer = page.getByTestId("evidence-drawer");
  await expect(drawer).toBeVisible();
  // 问11 的 case citation 带出原文；[1] 去重后保留的是首条 case:11（snippet 为空）。
  await expect(drawer).toContainText("服西药多年不愈");
  // 终审 R22 实测：后端 `builders.py` 只给 evidence citation 写 snippet，
  // case/framework citation 的 snippet 为空串/非原文子串。spec §7.4 的契约是
  // 「citation.snippet 是原文子串才高亮，否则不高亮」，因此这里 0 个 mark 才是
  // 规格正确的断言（高亮的命中分支由下一条用例在 evidence 出处上正向验证）。
  await expect(drawer.locator("mark")).toHaveCount(0);
  await expect(drawer.getByRole("link", { name: "在库详情页打开" })).toBeVisible();
  await expect(drawer.getByRole("button", { name: "复制引用" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(drawer).not.toBeVisible();
  await expect(firstSup).toBeFocused();
});

test("方剂卡与详情页剂量一致", async ({ page }) => {
  await ask(page, "桂枝汤");
  const card = page.getByTestId("formula-card");
  await expect(card).toBeVisible({ timeout: 30_000 });
  await expect(card).toContainText("换算留痕");
  const cardValue = (await card.getByTestId("dose-cell").first().innerText()).trim();

  // §7.4 高亮的命中分支（正向）：evidence 出处的 snippet 就是原文本身 → 必须出现 mark。
  await page.getByRole("button", { name: "查看出处 桂枝汤（太阳病）" }).click();
  const drawer = page.getByTestId("evidence-drawer");
  await expect(drawer).toBeVisible();
  await expect(drawer.locator("mark")).toHaveCount(1);
  await expect(drawer.locator("mark")).toContainText("啬啬恶寒");
  await page.keyboard.press("Escape");
  await expect(drawer).not.toBeVisible();

  await card.getByRole("link", { name: "在库详情页打开" }).click();
  await expect(page.getByTestId("formula-detail")).toBeVisible();
  await expect(page.getByTestId("dose-cell").first()).toHaveText(cardValue);

  await page.getByTestId("dose-toggle").click();
  await expect(page.getByTestId("dose-cell")).toHaveCount(0);
  // §6.7 第 3 项的「古制列出留痕」：断到实际存库的古制原量整串
  // （zhongyi_e2e：formula 110 桂枝汤 / 经方组成 / 大枣 = `十二枚(劈)`，括号为半角）。
  await expect(page.getByTestId("formula-detail")).toContainText("十二枚(劈)");
});

test("剂量诚实：非 exact 药味不臆造克数", async ({ page }) => {
  await ask(page, "一物瓜蒂汤");
  const card = page.getByTestId("formula-card");
  await expect(card).toBeVisible({ timeout: 30_000 });
  await expect(card).toContainText("本方剂量不完全可执行");

  const cells = card.getByTestId("dose-cell");
  const count = await cells.count();
  expect(count).toBeGreaterThan(0);
  for (let index = 0; index < count; index += 1) {
    // 非 exact 药味：克数列只出现 —，且状态中文在相邻括号内
    await expect(cells.nth(index)).toContainText("—");
    await expect(cells.nth(index)).not.toContainText(/\d+g/);
  }

  await card.getByTestId("dose-toggle").click();
  await expect(card.getByTestId("dose-cell")).toHaveCount(0);
  await expect(card).toContainText("二十个");

  await ask(page, "五苓散");
  const mixed = page.getByTestId("formula-card").first();
  await expect(mixed).toBeVisible({ timeout: 30_000 });
  // 混合方的诚实性按「行」呈现：`半两`=exact 有克数，`十八铢`=unknown_unit 只有 —+中文状态。
  const mixedCells = mixed.getByTestId("dose-cell");
  const mixedValues = await mixedCells.allInnerTexts();
  expect(mixedValues.some((value) => /\d+(\.\d+)?g/.test(value))).toBe(true);
  const dashCells = mixedValues.filter((value) => value.includes("—"));
  expect(dashCells.length).toBeGreaterThan(0);
  // 显示 — 的行绝不允许同时出现克数（FR-3：不臆造）。
  for (const value of dashCells) {
    expect(value).not.toMatch(/\d+(\.\d+)?g/);
  }
  await expect(mixedCells.filter({ hasText: "—" }).first()).toContainText("未换算");
  // 表头级的「本方剂量不完全可执行」由详情接口的 formula 级 dose_complete 驱动，
  // 而后端口径是「任一变体全 exact 即完整」（五苓散的 经典配方 克数本全 exact）→ 卡片不挂该提示；
  // 本轮回答的不完整提示来自 Answer（按所展示的古制变体聚合），实测确实出现。
  await expect(page.getByTestId("answer-body")).toContainText("本方剂量不完全可执行");
});

test("医案回答与抽屉原文", async ({ page }) => {
  await ask(page, "问11");
  await expect(page.getByTestId("intent-badge")).toContainText("E 医案");
  await expect(page.getByTestId("case-card")).toBeVisible({ timeout: 30_000 });

  await page.getByRole("button", { name: "查看出处 问11" }).first().click();
  const drawer = page.getByTestId("evidence-drawer");
  await expect(drawer).toContainText("服西药多年不愈");
  // 后端 case citation 的 snippet 为空：按 §7.4「找不到则不高亮」如实呈现
  await expect(drawer.locator("mark")).toHaveCount(0);
  await expect(drawer.getByRole("link", { name: "在库详情页打开" }))
    .toHaveAttribute("href", /\/cases\/\d+/);
});

test("拒答卡：无自由发挥、兜底按钮置灰、候选 chips 对齐后端", async ({ page, request }) => {
  await ask(page, "乳腺癌靶向药有哪些");
  const refusal = page.getByTestId("refusal-card");
  await expect(refusal).toBeVisible({ timeout: 30_000 });
  await expect(refusal).toContainText("本地库未收录");
  await expect(refusal.getByRole("button", { name: "在原文 text/ 搜一下" })).toBeDisabled();
  await expect(page.getByTestId("answer-body")).toHaveCount(0);

  // §6.7 第 2 项的「候选 chips」：数量与标题都必须等于这一轮后端下发的 answer.candidates，
  // 所以从已落定的会话 URL 回读历史，而不是在测试里写死名字。
  await expect(page).toHaveURL(/\/chat\/\d+$/, { timeout: 30_000 });
  const sessionId = Number(/\/chat\/(\d+)$/.exec(page.url())?.[1]);
  expect(sessionId, "拒答轮也要落定会话语句 URL").toBeGreaterThan(0);
  const history = await (await request.get(`/api/chat/${sessionId}`)).json();
  const assistant = [...history.messages].reverse()
    .find((item: { role: string }) => item.role === "assistant");
  const candidates = assistant?.content?.candidates ?? [];
  expect(candidates.length, "e2e 库这一轮应有候选命中").toBeGreaterThan(0);

  // 「在原文 text/ 搜一下」带 disabled 属性，因此启用状态的按钮就是候选 chips。
  const chips = refusal.locator("button:not([disabled])");
  await expect(chips).toHaveCount(candidates.length);
  const chipTitles = (await chips.allInnerTexts()).map((title) => title.trim());
  expect(chipTitles).toEqual(candidates.map((item: { title: string }) => item.title));

  // 点击候选 chip 会以该标题发起新一轮：多出一条用户消息，且新轮进入 answered 正文
  // （首个候选是 framework 精确命中项，实测 status=answered）。
  const firstTitle = chipTitles[0];
  const userTurns = await page.getByTestId("message-user").count();
  await chips.first().click();
  await expect(page.getByTestId("message-user")).toHaveCount(userTurns + 1);
  await expect(page.getByTestId("message-user").last()).toContainText(firstTitle);
  await expect(page.getByTestId("answer-body")).toBeVisible({ timeout: 30_000 });
});

test("问诊卡：键盘选择并提交", async ({ page }) => {
  await ask(page, "不舒服");
  const intake = page.getByTestId("intake-card");
  await expect(intake).toBeVisible({ timeout: 30_000 });

  const sleep = intake.getByRole("radiogroup", { name: "睡眠" });
  const normal = sleep.getByRole("radio", { name: "正常" });
  await normal.focus();
  await page.keyboard.press("Space");
  await expect(normal).toHaveAttribute("aria-checked", "true");

  // 提交同样只用键盘：焦点移到 type=submit 的「提交主诉补充」后按 Enter（浏览器原生
  // 触发表单 submit）。这里刻意不用 Tab + Enter——Tab 会落到同组的下一个 radio，
  // 反而把刚选好的三态改掉。
  const submit = intake.getByRole("button", { name: "提交主诉补充" });
  await submit.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("message-user").last()).toContainText("主诉补充（问诊卡）");
});

test("会话：URL 落定、回放与删除", async ({ page }) => {
  await ask(page, "桂枝汤");
  await expect(page).toHaveURL(/\/chat\/\d+$/, { timeout: 30_000 });
  await expect(page.getByTestId("answer-body")).toBeVisible();

  const current = page.getByTestId("session-item").first();
  await current.getByRole("link").click();
  await expect(page.getByTestId("answer-body")).toContainText("桂枝");

  const before = await page.getByTestId("session-item").count();
  await current.getByRole("button", { name: /删除会话/ }).click();
  await page.getByRole("button", { name: "确认" }).click();
  await expect(page).toHaveURL(/\/chat$/);
  await expect(page.getByTestId("session-item")).toHaveCount(before - 1);
});

// b60335b 修的是一个真实浏览器缺陷：replaceState 只挪地址栏，Next 的 router.state 仍是 /chat，
// 于是「新会话」是同树导航，转录与侧栏高亮都留在上一轮——jsdom 里导航本身没实现，证不了这件事。
// 已知边界（终审 R14）：URL 由 replaceState 同步，所以 Back 不会回到那个从未挂载过的 phantom /chat
// 入口；本用例刻意不断言 Back/Forward 语义。
test("新会话：真实浏览器里清空转录并重启会话机制", async ({ page }) => {
  await ask(page, "桂枝汤");
  await expect(page).toHaveURL(/\/chat\/\d+$/, { timeout: 30_000 });
  await expect(page.getByTestId("answer-body")).toBeVisible();
  const firstId = /\/chat\/(\d+)$/.exec(page.url())?.[1];
  expect(firstId, "首问后要落定会话语句 URL").toBeTruthy();

  const currentRow = page.locator('[data-testid="session-item"] a[aria-current="page"]');
  await expect(currentRow).toHaveCount(1);

  await page.getByRole("link", { name: "新会话" }).click();

  await expect(page.getByTestId("chat-transcript").getByTestId("message-user")).toHaveCount(0);
  await expect(page.getByTestId("answer-body")).toHaveCount(0);
  await expect(page).toHaveURL(/\/chat$/);
  await expect(currentRow).toHaveCount(0);

  // 复位没有打断会话机制：从干净状态再问一次，新的一轮落到另一个会话 id 上。
  await ask(page, "问11");
  await expect(page).toHaveURL(/\/chat\/\d+$/, { timeout: 30_000 });
  await expect(page.getByTestId("answer-body")).toBeVisible();
  const secondId = /\/chat\/(\d+)$/.exec(page.url())?.[1];
  expect(secondId).toBeTruthy();
  expect(secondId).not.toBe(firstId);
  await expect(page.getByTestId("chat-transcript").getByTestId("message-user")).toHaveCount(1);
});
