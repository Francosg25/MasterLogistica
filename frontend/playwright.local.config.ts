import { defineConfig } from "@playwright/test";
import base from "./playwright.config";

export default defineConfig({
  testDir: "./e2e",
  testMatch: "local.spec.ts",
  outputDir: "test-results/local",
  workers: 1,
  use: { ...base.use, baseURL: "http://127.0.0.1:4200" },
  webServer: {
    command: "node e2e/start-local.mjs",
    url: "http://127.0.0.1:4200",
    reuseExistingServer: false,
    timeout: 60000,
  },
  reporter: "list",
});
