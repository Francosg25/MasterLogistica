import { test, expect } from "@playwright/test";
import { spawn, ChildProcess } from "node:child_process";
import { once } from "node:events";
import { cp, mkdtemp, readFile, rm, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { demoCatalogs, demoOwners } from "../src/app/demo";
import { demoReport } from "../src/app/finance-demo";

test("an already running local server receives the complete theme through its original CSS entry", async ({ page }, testInfo) => {
  test.setTimeout(120_000);
  const source = resolve(__dirname, "..");
  const fixture = await mkdtemp(join(tmpdir(), "masterlogistica-styles-"));
  let server: ChildProcess | undefined;
  let output = "";
  try {
    for (const name of ["src", "public"]) await cp(join(source, name), join(fixture, name), { recursive: true });
    for (const name of ["angular.json", "package.json", "proxy.conf.json", "tsconfig.json", "tsconfig.app.json"]) await cp(join(source, name), join(fixture, name));
    await symlink(join(source, "node_modules"), join(fixture, "node_modules"), process.platform === "win32" ? "junction" : "dir");
    const configuration = JSON.parse(await readFile(join(fixture, "angular.json"), "utf8"));
    const base = await readFile(join(source, "src/base.css"), "utf8");
    const entry = await readFile(join(source, "src/styles.css"), "utf8");
    const layouts = JSON.parse(await readFile(join(source, "public/master-layouts.json"), "utf8")).layouts;
    // Reproduce an older session which knows only styles.css and its previous content.
    configuration.projects.web.architect.build.options.styles = ["src/styles.css"];
    await writeFile(join(fixture, "angular.json"), JSON.stringify(configuration));
    await writeFile(join(fixture, "src/styles.css"), base);
    server = spawn(process.execPath, [join(source, "node_modules/@angular/cli/bin/ng.js"), "serve", "--host", "127.0.0.1", "--port", "0", "--proxy-config", "proxy.conf.json"], { cwd: fixture, stdio: ["ignore", "pipe", "pipe"] });
    server.stdout!.on("data", chunk => { output += chunk.toString(); });
    server.stderr!.on("data", chunk => { output += chunk.toString(); });
    const address = () => output.replace(/\u001b\[[\d;]*m/g, "").match(/http:\/\/127\.0\.0\.1:(\d+)\//)?.[0];
    await expect.poll(() => { if (server!.exitCode !== null) throw new Error(output); return address(); }, { timeout: 60_000 }).toBeTruthy();
    const pid = server.pid;
    await page.route("**/api/v1/**", route => {
      const path = new URL(route.request().url()).pathname.replace("/api/v1", "");
      const json = (data: unknown) => route.fulfill({ json: data });
      if (path === "/auth/config") return json({ auth_mode: "development", storage: "sqlite", enabled: false, authority: null, frontend_client_id: null, scope: null });
      if (path === "/auth/me") return json({ id: demoOwners[0].id, role: "SUPER_ADMIN", analyst_code: demoOwners[0].analyst_code, display_name: "Usuario local", email: "local@example.invalid" });
      if (path === "/references/catalogs") return json({ ...demoCatalogs, master_layouts: layouts });
      if (path === "/masters/owners") return json(demoOwners);
      if (path === "/suppliers") return json({ items: [], total: 0 });
      if (path === "/workspace/overview") return json({ month: "2026-11-01", active_references: 4, live_provisions: 2, settled_provisions: 0, invoices_in_month: 0, pending_invoices: 0, totals: demoReport.totals, recent: [] });
      return route.fulfill({ status: 404, json: { detail: "Unexpected route " + path } });
    });
    await page.goto(address()!);
    await expect(page.getByRole("heading", { name: "Masters", exact: true })).toBeVisible();
    await expect(page.locator(".account-name")).toContainText("Usuario de pruebas");
    const first = page.locator(".master-file").first();
    await expect(first).toHaveCSS("display", "inline-block");
    const builds = () => (output.match(/Application bundle generation complete/g) ?? []).length;
    const initialBuilds = builds();
    // Angular keeps its startup build options when only the workspace configuration changes.
    configuration.projects.web.architect.build.options.styles = ["src/styles.css", "src/workspace.css", "src/design-system.css"];
    await writeFile(join(fixture, "angular.json"), JSON.stringify(configuration));
    await writeFile(join(fixture, "src/styles.css"), base + "\n/* configuration changed */\n");
    await expect.poll(builds, { timeout: 30_000 }).toBeGreaterThan(initialBuilds);
    await page.reload();
    await expect(first).toHaveCSS("display", "inline-block");
    // The updated entry imports every layer, so the same server can recover without a restart.
    await writeFile(join(fixture, "src/styles.css"), entry);
    await expect(first).toHaveCSS("display", "grid", { timeout: 30_000 });
    await expect(page.locator(".master-files")).toHaveCSS("list-style-type", "none");
    expect(Number.parseFloat(await page.getByRole("heading", { name: "Masters", exact: true }).evaluate(element => getComputedStyle(element).fontSize))).toBeGreaterThanOrEqual(40);
    expect((await first.boundingBox())!.width).toBeGreaterThan(900);
    expect(server.pid).toBe(pid);
    expect(server.exitCode).toBeNull();
    await page.screenshot({ path: testInfo.outputPath("local-styles-recovered.png"), fullPage: true, animations: "disabled" });
  } finally {
    if (server && server.exitCode === null && server.signalCode === null) {
      const stopped = once(server, "exit");
      const deadline = setTimeout(() => server!.kill("SIGKILL"), 5_000);
      server.kill("SIGTERM");
      await stopped;
      clearTimeout(deadline);
    }
    await rm(fixture, { recursive: true, force: true });
  }
});
