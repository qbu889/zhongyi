import { expect, test } from "@playwright/test";

test("方剂筛选写入 URL 且刷新后保持", async ({ page }) => {
  await page.goto("/formulas");
  await expect(page.getByRole("heading", { level: 1, name: "方剂库" })).toBeVisible();

  // 复选框是 URL 驱动的控制态（spec §9.1「筛选写 URL」）：点击后由 router.push 触发
  // 服务端重渲染才回勾，Playwright 的 check() 会在这一帧之前就断言，故用 click()+断言。
  await page.getByRole("checkbox", { name: "太阳病" }).click();
  await expect(page).toHaveURL(/six_jing=/);
  await expect(page.getByRole("checkbox", { name: "太阳病" })).toBeChecked();
  await page.reload();
  await expect(page.getByRole("checkbox", { name: "太阳病" })).toBeChecked();
});

test("柴胡与牡桂都走精确通道", async ({ request }) => {
  for (const query of ["柴胡", "牡桂"]) {
    const response = await request.post("/api/search", {
      data: { query, kind: ["herb"], top: 5 },
    });
    expect(response.ok()).toBeTruthy();
    const body = await response.json();
    const top = body.hits.find((hit: { ref_type: string }) => hit.ref_type === "herb");
    expect(top, `${query} 应有中药命中`).toBeTruthy();
    expect(["exact", "literal"]).toContain(top.match);
  }
});

test("中药联想进入详情并预填提问", async ({ page }) => {
  await page.goto("/herbs");
  await page.getByRole("searchbox", { name: "检索" }).fill("牡桂");
  const suggest = page.getByTestId("suggest");
  await expect(suggest).toBeVisible();

  await suggest.getByRole("link", { name: "牡桂" }).click();
  await expect(page.getByTestId("herb-detail")).toBeVisible();
  await expect(page.getByTestId("detail-disclaimer")).toBeVisible();
  await page.getByRole("link", { name: "就本条提问" }).click();

  await expect(page).toHaveURL(/\/chat\?ref=herb:\d+/);
  await expect(page.getByTestId("composer")).toHaveValue(/关于 牡桂/);
});

test("方剂详情：变体与加减方分离", async ({ page, request }) => {
  // 列表接口按 id 升序返回、不做「整名优先」重排（M2 口径），桂枝汤在第 15 条，
  // 所以取够 limit 再按 canonical_name 精确挑——这不是产品缺陷，是浏览列表的分页语义。
  const list = await (await request.get("/api/formulas?q=桂枝汤&limit=100")).json();
  const target = list.items.find(
    (item: { canonical_name: string }) => item.canonical_name === "桂枝汤",
  );
  expect(target, "e2e 库应有桂枝汤").toBeTruthy();
  const detail = await (await request.get(`/api/formulas/${target.id}`)).json();

  await page.goto(`/formulas/${target.id}`);
  await expect(page.getByTestId("formula-detail")).toBeVisible();
  // NFR-5 免责三处之一：详情页必须带免责尾注（另两处见对话页与导出物单测）。
  await expect(page.getByTestId("detail-disclaimer")).toBeVisible();
  await expect(page.getByTestId("variant-badge")).toBeVisible();
  await expect(page.getByRole("heading", { name: "加减方谱系" })).toBeVisible();
  await expect(page.locator("table")).toHaveCount(detail.variants.length);

  // §6.7 第 5 项的口径是「变体列表中不得出现加减方」，故按剂量变体区断言（D6）；
  // 加减方作为独立 formula 必须出现在「加减方谱系」里，两处都是规格要求。
  const variants = page.getByRole("region", { name: "剂量变体" });
  const variantText = await variants.innerText();
  expect(variantText).not.toContain("桂枝加葛根汤");
  expect(variantText).not.toContain("桂枝加厚朴杏仁汤");
  const lineage = page.getByRole("region", { name: "加减方谱系" });
  await expect(lineage).toContainText("桂枝加葛根汤");
  await expect(lineage).toContainText("桂枝加厚朴杏仁汤");
});

test("乌梅丸身份归一：列表仅一条，古制与克数变体同属一方", async ({ request }) => {
  const list = await (await request.get("/api/formulas?q=乌梅丸&limit=20")).json();
  const matches = list.items.filter(
    (item: { canonical_name: string }) => item.canonical_name === "乌梅丸",
  );
  expect(matches, "乌梅丸/乌梅丸方 应归一为一条").toHaveLength(1);

  const detail = await (await request.get(`/api/formulas/${matches[0].id}`)).json();
  const bases = new Set(detail.variants.map((variant: { dose_basis: string }) => variant.dose_basis));
  expect(bases.has("ancient"), "应有古制变体").toBe(true);
  expect(bases.has("gram"), "应有克数变体").toBe(true);
});

test("医案详情：问11 四段与原文", async ({ page, request }) => {
  const list = await (await request.get("/api/cases?limit=100")).json();
  const target = list.items.find((item: { no: string }) => item.no === "问11");
  expect(target, "e2e 库应有问11").toBeTruthy();

  await page.goto(`/cases/${target.id}`);
  const detail = page.getByTestId("case-detail");
  await expect(detail).toBeVisible();
  await expect(detail.getByTestId("detail-disclaimer")).toBeVisible();
  await expect(detail).toContainText("服西药多年不愈");
  await expect(detail).toContainText("加味");
});

test("针灸详情：从列表数据进入", async ({ page, request }) => {
  const list = await (await request.get("/api/acupoints?limit=1")).json();
  const target = list.items[0];
  expect(target, "e2e 库应有穴位").toBeTruthy();

  await page.goto(`/acupoints/${target.id}`);
  const detail = page.getByTestId("acupoint-detail");
  await expect(detail).toBeVisible();
  await expect(detail.getByTestId("detail-disclaimer")).toBeVisible();
  await expect(detail).toContainText(target.name);
});
