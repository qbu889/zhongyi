import path from "node:path";

import { defineConfig, devices } from "@playwright/test";

// 配置按 CJS 加载（frontend/package.json 未声明 "type": "module"）
const backendDir = path.resolve(__dirname, "../backend");
const frontendDir = __dirname;

// 端口现实（终审 R20）：8000 被本机无关应用长期占用，绝不可用。
// e2e 后端固定 8001——`backend/scripts/start_e2e.sh` 认 E2E_PORT，默认库 zhongyi_e2e。
export const BACKEND_ORIGIN = "http://127.0.0.1:8001";
export const FRONTEND_ORIGIN = "http://127.0.0.1:3000";

// 浏览器获取（终审 R21）：本机没有 Playwright 浏览器缓存，但装了系统 Chrome。
// 设 PW_BROWSER_CHANNEL=chrome 用系统浏览器跑；不设则回落到 Playwright 自带的 chromium
// （需先 `npx playwright install chromium`）。
const channel = process.env.PW_BROWSER_CHANNEL;

// —— 管理端口令（R-M5-24 / T15 指针 §1，覆盖 plan brief 里的兜底字面量写法）——
// 仓库里**任何文件**都不许出现口令字面量，"测试值"也不行：口令只从环境变量
// E2E_ADMIN_TOKEN 读，原样注入后端 webServer 的 ADMIN_TOKEN。
// 后端 fail-closed：ADMIN_TOKEN 未设置或短于 16 字符时 /api/admin/* 全 503
// admin_disabled，管理端用例必败——所以这一条是运行前提：
//   export E2E_ADMIN_TOKEN=…（≥16 字符）
// （T16 的 runbook 会把它写进文档。）
// 未满足时的处置（**整枝评审 F-7 改了裁定**，规格 §11/§13-17 已同步）：
//   • `process.env.CI` 存在 → **抛错、非零退出**。原处置是"排除 admin project 并打印原因"，
//     本地照旧能只跑 app 那 26 条；但未来的 CI 只要忘了 export，就会**用 26/43 报绿**——
//     "少跑一整个 project 的绿"比"红"危险得多，终审定的就是 CI 必须失败。
//   • 本地（不设 CI）→ 保持原处置：从 projects 里去掉 admin + 打印一行原因，
//     跑 M4 的 app 用例不该被管理端环境变量的缺失连坐拦下。
// 两种情形都**不静默**：原因行照打，`--list` 的用例总数照常反映（本地 26 条/3 文件）。
const adminToken = process.env.E2E_ADMIN_TOKEN ?? "";
const adminReady = adminToken.length >= 16;
if (!adminReady) {
  const reason = "E2E_ADMIN_TOKEN 未设置或短于 16 字符：管理端在后端是 fail-closed（全 503 admin_disabled），" +
    "先 export E2E_ADMIN_TOKEN=…（≥16 字符）。";
  if (process.env.CI) {
    throw new Error(
      `[playwright] ${reason}本次是 CI 运行（process.env.CI 已设），不接受"把 admin project 整组排除"后` +
        `用 26/43 报绿：这里直接非零退出。要跑管理端 e2e 请在 CI 的 secret 里注入该变量。`,
    );
  }
  console.error(
    `[playwright] ${reason}本次运行已排除 admin project（e2e/admin.spec.ts 整组）；app project 不受影响。`,
  );
}

// 浏览器构造提成常量，两个 project 共用（brief Step 3）。
const browserUse = {
  ...devices["Desktop Chrome"],
  ...(channel ? { channel } : {}),
};

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  timeout: 90_000,
  expect: { timeout: 15_000 },
  reporter: [["list"]],
  use: {
    baseURL: FRONTEND_ORIGIN,
    // 本配置没有 retries（workers:1、serial 对话套件），on-first-retry 是死配置；
    // 改为失败即保留 trace，便于事后定位。
    trace: "retain-on-failure",
    locale: "zh-CN",
  },
  webServer: [
    {
      command: "bash scripts/start_e2e.sh",
      cwd: backendDir,
      // 口令经 env 注入（R-M5-24：没有兜底字面量）。未设置/过短时不注入，
      // 后端保持 fail-closed——那一情形下 admin project 已被排除（见上）。
      env: {
        E2E_PORT: "8001",
        ...(adminReady ? { ADMIN_TOKEN: adminToken } : {}),
      },
      url: `${BACKEND_ORIGIN}/healthz`,
      reuseExistingServer: !process.env.CI,
      timeout: 180_000,
    },
    {
      command: "npm run dev -- --hostname 127.0.0.1 --port 3000",
      cwd: frontendDir,
      url: `${FRONTEND_ORIGIN}/chat`,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      env: { BACKEND_ORIGIN },
    },
  ],
  // Playwright 按声明顺序串行调度 project（workers=1）。管理端用例会写库
  // （归并写 formula_alias、force 重建新起索引版本），必须排在 app 之后，
  // 否则字母序把 admin.spec.ts 排到 chat/library 前面，写库会影响 app 用例看到的命中集合
  // （T15 指针 §3.1；brief Step 3 的 project 顺序方案）。
  projects: [
    {
      name: "app",
      use: { ...browserUse },
      testIgnore: /admin\.spec\.ts/,
    },
    // 口令前提不满足时整组缺席——缺席本身就是信号，原因行已在配置加载时打到 stderr。
    ...(adminReady
      ? [
          {
            name: "admin",
            use: { ...browserUse },
            testMatch: /admin\.spec\.ts/,
          },
        ]
      : []),
  ],
});
