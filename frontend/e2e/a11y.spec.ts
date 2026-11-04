import { expect, test } from "@playwright/test";

import { blocking } from "./a11y-helpers";

for (const path of [
  "/chat", "/formulas", "/herbs", "/acupoints", "/cases",
  "/framework", "/admin", "/this-route-does-not-exist",
]) {
  test(`无障碍扫描 ${path}`, async ({ page }) => {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1 }).first()).toBeVisible();
    expect(await blocking(page)).toEqual([]);
  });
}

test("无障碍扫描：回答完成态与方剂详情", async ({ page, request }) => {
  await page.goto("/chat");
  await page.getByTestId("composer").fill("桂枝汤");
  await page.getByTestId("send").click();
  await expect(page.getByTestId("answer-body")).toBeVisible({ timeout: 30_000 });
  expect(await blocking(page)).toEqual([]);

  // 同 library.spec：列表按 id 升序，整名命中不在首页，取够 limit 再精确挑。
  const list = await (await request.get("/api/formulas?q=桂枝汤&limit=100")).json();
  const target = list.items.find(
    (item: { canonical_name: string }) => item.canonical_name === "桂枝汤",
  );
  expect(target, "e2e 库应有桂枝汤").toBeTruthy();
  await page.goto(`/formulas/${target.id}`);
  await expect(page.getByTestId("formula-detail")).toBeVisible();
  expect(await blocking(page)).toEqual([]);
});

test("无障碍扫描：问诊卡", async ({ page }) => {
  await page.goto("/chat");
  await page.getByTestId("composer").fill("不舒服");
  await page.getByTestId("send").click();
  await expect(page.getByTestId("intake-card")).toBeVisible({ timeout: 30_000 });
  expect(await blocking(page)).toEqual([]);
});
