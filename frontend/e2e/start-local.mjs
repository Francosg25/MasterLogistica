// Exercise the documented manual API + Angular commands with a disposable database.
import { spawn, spawnSync } from "node:child_process";
import { existsSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { resolve, join } from "node:path";

const backend = resolve("../backend");
if (existsSync(join(backend, ".env"))) throw new Error("La prueba requiere backend sin .env; conserva tu configuración y usa una copia aislada.");
const folder = mkdtempSync(join(tmpdir(), "masterlogistica-e2e-"));
const env = { ...process.env };
const settings = ["APP_ENV", "DATABASE_URL", "MIGRATION_DATABASE_URL", "AUTH_MODE", "ENTRA_TENANT_ID", "ENTRA_API_CLIENT_ID", "ENTRA_FRONTEND_CLIENT_ID", "ENTRA_ALLOWED_CLIENT_IDS", "ALLOWED_HOSTS", "ALLOWED_ORIGINS", "ENFORCE_HTTPS", "TRUSTED_PROXY_IPS", "BUSINESS_UNITS", "COMPANY_CODES"];
for (const key of Object.keys(env)) if (settings.includes(key.toUpperCase())) delete env[key];
Object.assign(env, {
  APP_ENV: "development", AUTH_MODE: "development",
  DATABASE_URL: "sqlite+pysqlite:///" + join(folder, "local.db").replaceAll("\\", "/"),
  ALLOWED_HOSTS: '["127.0.0.1","localhost"]',
  ALLOWED_ORIGINS: '["http://127.0.0.1:4200","http://localhost:4200"]',
});
const python = process.env.LOCAL_TEST_PYTHON || "python";
const check = spawnSync(python, ["-c", "import fastapi,uvicorn,sqlalchemy; print('listo')"], { encoding: "utf8" });
if (check.status !== 0) throw new Error("Instala backend/requirements.lock en LOCAL_TEST_PYTHON.");
const children = [
  spawn(python, ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000", "--no-proxy-headers"], { cwd: backend, env, stdio: "inherit" }),
  spawn(process.execPath, [resolve("node_modules/@angular/cli/bin/ng.js"), "serve", "--host", "127.0.0.1", "--port", "4200", "--proxy-config", "proxy.conf.json"], { env, stdio: "inherit" }),
];
let stopping = false;
function stop(code = 0) {
  if (stopping) return;
  stopping = true;
  for (const child of children) if (child.exitCode === null) child.kill("SIGTERM");
  Promise.all(children.map(child => child.exitCode !== null ? null : new Promise(done => child.once("exit", done)))).then(() => {
    rmSync(folder, { recursive: true, force: true });
    process.exit(code);
  });
}
for (const child of children) {
  child.on("error", () => stop(1));
  child.on("exit", code => { if (!stopping) stop(code || 1); });
}
process.on("SIGINT", () => stop());
process.on("SIGTERM", () => stop());
