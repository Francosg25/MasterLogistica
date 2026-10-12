import { test, expect, Page } from "@playwright/test";
import { demoCatalogs } from "../src/app/demo";
import { demoReport, demoInvoices, demoHistory } from "../src/app/finance-demo";
async function setup(page: Page, role = "FINANCE") {
  const writes: { path: string; body: any }[] = [];
  await page.route("**/api/v1/**", async (route) => {
    const req = route.request(),
      path = new URL(req.url()).pathname.replace("/api/v1", "");
    const json = (data: unknown, status = 200) =>
      route.fulfill({ json: data, status });
    if (path === "/auth/me")
      return json({
        id: "owner-1",
        display_name: "Finanzas",
        email: "f@example.com",
        role,
        analyst_code: null,
      });
    if (path === "/references/catalogs") return json(demoCatalogs);
    if (["/masters/owners", "/finance/owners"].includes(path))
      return json([
        { id: "owner-1", display_name: "Responsable 1", analyst_code: 1 },
      ]);
    if (path === "/suppliers")
      return json({
        items: [
          {
            id: "supplier-1",
            legal_name: "Transportes Demo",
            code: "DEMO",
            is_active: true,
          },
        ],
        total: 1,
        limit: 100,
        offset: 0,
      });
    if (req.method() === "POST") {
      writes.push({ path, body: req.postDataJSON() });
      return json(
        path === "/finance/invoices"
          ? demoInvoices[0]
          : { id: "new", row_version: 1 },
        201,
      );
    }
    if (path === "/finance/references")
      return json([
        {
          id: "shipment-1",
          reference: demoReport.balances[0].reference,
          company_code: "DEMO",
        },
      ]);
    if (path === "/finance/balances")
      return json({
        items: demoReport.balances,
        total: 4,
        limit: 20,
        offset: 0,
        totals: demoReport.totals,
      });
    if (path === "/finance/invoices")
      return json({ items: demoInvoices, total: 2, limit: 20, offset: 0 });
    if (path === "/finance/history")
      return json({ items: demoHistory, total: 2, limit: 20, offset: 0 });
    if (path === "/finance/report") return json(demoReport);
    if (path === "/finance/report.csv")
      return route.fulfill({
        contentType: "text/csv",
        body: "Tipo,Referencia,Factura\r\nMATCH,RM1,DEMO-001",
      });
    return json({ detail: "unexpected " + path }, 404);
  });
  await page.goto("/");
  await expect(
    page.getByRole("navigation", { name: "Secciones" }),
  ).toBeVisible();
  return writes;
}
async function section(page: Page, name: string) {
  await page
    .getByRole("navigation", { name: "Secciones" })
    .getByRole("button", { name, exact: true })
    .click();
}
test("carry-forward totals and full report export", async ({ page }) => {
  await setup(page);
  await section(page, "Provisiones");
  await expect(page.locator(".finance-summary").first()).toContainText(
    "700.00",
  );
  await expect(page.locator(".finance-summary").first()).toContainText(
    "8,000.00",
  );
  await expect(page.getByText("2026-05")).toBeVisible();
  await page
    .getByRole("button", { name: "Reporte mensual", exact: true })
    .click();
  await expect(
    page.getByRole("region", { name: "Reporte de conciliación" }),
  ).toContainText("DEMO-001");
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Descargar CSV para Excel" }).click();
  const stream = await (await download).createReadStream();
  let csv = "";
  for await (const c of stream!) csv += c.toString();
  expect(csv).toContain("DEMO-001");
  await page.screenshot({
    path: "test-results/finance-report.png",
    fullPage: true,
  });
});
test("history identifies actor and cleared fields", async ({ page }) => {
  await setup(page);
  await section(page, "Historial");
  await page.getByText("2 campos · Ver antes y después").click();
  await expect(page.locator("details[open] .audit-changes")).toContainText(
    "Monterrey",
  );
  await expect(page.locator("details[open] .audit-changes")).toContainText(
    "Saltillo",
  );
  await expect(page.locator("details[open] .audit-changes")).toContainText(
    "Vacío",
  );
  await expect(page.locator(".history-table")).toContainText(
    "integrante1@example.com",
  );
  await page.screenshot({ path: "test-results/history.png", fullPage: true });
});
test("multi-reference invoice preserves decimal values", async ({ page }) => {
  const writes = await setup(page);
  await section(page, "Facturas y conciliación");
  await page
    .getByRole("button", { name: "+ Registrar factura", exact: true })
    .click();
  await page.getByLabel("Folio de factura").fill("F-003");
  await page
    .getByLabel("Proveedor de factura", { exact: true })
    .selectOption("supplier-1");
  await page
    .getByLabel("Referencia 1", { exact: true })
    .fill(demoReport.balances[0].reference);
  await page.getByLabel("Neto 1", { exact: true }).fill("500.1234");
  await page
    .getByRole("button", { name: "+ Otra referencia", exact: true })
    .click();
  await page
    .getByLabel("Referencia 2", { exact: true })
    .fill(demoReport.balances[1].reference);
  await page.getByLabel("Neto 2", { exact: true }).fill("300");
  await page
    .getByRole("button", { name: "Registrar y conciliar", exact: true })
    .click();
  await expect(page.locator(".success[role=status]")).toContainText(
    "Factura registrada",
  );
  const body = writes.find((w) => w.path === "/finance/invoices")!.body;
  expect(body.lines).toHaveLength(2);
  expect(body.lines[0].net_amount).toBe("500.1234");
  expect(body.accounting_period).toMatch(/^\d{4}-\d{2}-01$/);
});
test("provision draft and unsaved navigation warning", async ({ page }) => {
  const writes = await setup(page);
  await section(page, "Provisiones");
  await page
    .getByRole("button", { name: "+ Nueva provisión", exact: true })
    .click();
  await page
    .getByLabel("Referencia del master")
    .fill(demoReport.balances[0].reference);
  page.once("dialog", (d) => d.dismiss());
  await section(page, "Historial");
  await expect(
    page.getByRole("heading", { name: "Provisiones por referencia" }),
  ).toBeVisible();
  await page
    .getByLabel("Proveedor", { exact: true })
    .selectOption("supplier-1");
  await page.getByLabel("Importe neto", { exact: true }).fill("500");
  await page.getByRole("button", { name: "Guardar borrador" }).click();
  await expect(page.locator(".success[role=status]")).toContainText(
    "Provisión guardada en borrador",
  );
  expect(writes[0].body.shipment_id).toBe("shipment-1");
  expect(writes[0].body.amount).toBe("500");
});
test("invoice cancellation requires reason and accounting month", async ({
  page,
}) => {
  const writes = await setup(page);
  await section(page, "Facturas y conciliación");
  await page
    .getByRole("button", { name: "Cancelar factura", exact: true })
    .first()
    .click();
  await expect(
    page.getByRole("button", { name: "Confirmar cancelación" }),
  ).toBeDisabled();
  await page.getByLabel("Mes de reversión").fill("2026-11");
  await page.getByLabel("Motivo de cancelación").fill("Factura sustituida");
  await page.getByRole("button", { name: "Confirmar cancelación" }).click();
  await expect(page.locator(".success[role=status]")).toContainText(
    "Factura cancelada",
  );
  expect(writes[0].body.period_month).toBe("2026-11-01");
  expect(writes[0].body.expected_version).toBe(1);
});
test("manager has read-only finance and mobile contains tables", async ({
  page,
}) => {
  await setup(page, "MANAGER");
  await section(page, "Provisiones");
  await expect(
    page.getByRole("button", { name: "+ Nueva provisión" }),
  ).toHaveCount(0);
  await section(page, "Facturas y conciliación");
  await expect(
    page.getByRole("button", { name: "+ Registrar factura" }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Cancelar factura", exact: true }),
  ).toHaveCount(0);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth + 1,
    ),
  ).toBeTruthy();
  await page.screenshot({
    path: "test-results/finance-mobile.png",
    fullPage: true,
  });
});
test("production demo finance never calls operational endpoints", async ({
  page,
}) => {
  const paths: string[] = [];
  await page.route("**/api/v1/**", (route) => {
    paths.push(new URL(route.request().url()).pathname);
    return route.fulfill({
      json: {
        enabled: false,
        authority: null,
        frontend_client_id: null,
        scope: null,
      },
    });
  });
  await page.goto("http://127.0.0.1:4301");
  await page.getByRole("button", { name: "Ver demostración" }).click();
  await section(page, "Provisiones");
  await expect(page.locator(".finance-table")).toContainText("Liquidada");
  await section(page, "Historial");
  await expect(page.locator(".history-table")).toContainText(
    "Finanzas · Demostración",
  );
  expect(paths).toEqual(["/api/v1/auth/config"]);
});
