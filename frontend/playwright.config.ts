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
      env: { E2E_PORT: "8001" },
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
  projects: [{
    name: "chromium",
    use: {
      ...devices["Desktop Chrome"],
      ...(channel ? { channel } : {}),
    },
  }],
});
