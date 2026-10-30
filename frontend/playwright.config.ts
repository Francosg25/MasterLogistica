import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./e2e",
  timeout: 30000,
  fullyParallel: true,
  workers: 2,
  use: {
    baseURL: "http://127.0.0.1:4300",
    viewport: { width: 1440, height: 1000 },
    launchOptions: {
      ...(process.env["CHROMIUM_PATH"]
        ? { executablePath: process.env["CHROMIUM_PATH"] }
        : {}),
      args: ["--no-sandbox"],
    },
    trace: "retain-on-failure",
  },
  projects: [
    { name: "workspace", testMatch: "workspace.spec.ts" },
    { name: "finance", testMatch: "finance.spec.ts" },
    { name: "masters", testMatch: "masters.spec.ts" },
    { name: "production-access", testMatch: "access.spec.ts" },
  ],
  webServer: [
    {
      command: "npx ng serve --configuration=e2e --host 127.0.0.1 --port 4300",
      url: "http://127.0.0.1:4300",
      reuseExistingServer: !process.env["CI"],
      timeout: 60000,
    },
    {
      command: "node e2e/serve.mjs",
      url: "http://127.0.0.1:4301",
      reuseExistingServer: !process.env["CI"],
    },
  ],
  reporter: "list",
});
