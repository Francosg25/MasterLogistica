import { test, expect, Page } from "@playwright/test";
import { demoCatalogs } from "../src/app/demo";
import { demoReport, demoInvoices, demoHistory } from "../src/app/finance-demo";

test("Excel preview imports only ready invoices and requires refreshing changed mappings", async ({ page }) => {
  await setup(page);
  let confirmed = false;
  let previewFailure = false;
  let submitted: any;
  await page.route("**/api/v1/finance/import/*", async route => {
    if (route.request().url().endsWith("/confirm")) {
      submitted = route.request().postDataJSON(); confirmed = true;
      return route.fulfill({ status: 201, json: { imported: 1 } });
    }
    if (previewFailure) return route.fulfill({ status: 503, json: { detail: "No se pudo actualizar la vista previa" } });
    return route.fulfill({ json: {
      sheet: "CONSOLIDADO 2026", row_count: 3, invoice_count: 3,
      counts: { READY: confirmed ? 0 : 1, REVIEW: 1, DUPLICATE: confirmed ? 1 : 0, OUTSIDE: 1 },
      companies: ["DEMO"], suppliers: ["TRANSPORTES DEMO"],
      groups: [
        { key: "ready", invoice_number: "EXCEL-001", company: "DEMO", supplier_name: "Transportes Demo", source_supplier: "TRANSPORTES DEMO", source_company: "DEMO", status: confirmed ? "DUPLICATE" : "READY", usd_amount: "500", issues: [], rows: [{ row: 2, reference: "RM1-0001LI26-M01-MAT", charge_code: "FREIGHT", usd_amount: "500" }] },
        { key: "review", invoice_number: "EXCEL-002", company: "DEMO", supplier_name: "Transportes Demo", source_supplier: "TRANSPORTES DEMO", source_company: "DEMO", status: "REVIEW", usd_amount: "0", issues: ["Importe cero: revisar reparto"], rows: [{ row: 3, reference: "PAQUETERIA", charge_code: "FREIGHT", usd_amount: "0" }] },
      ],
    } });
  });
  await section(page, "Facturas");
  await page.getByRole("button", { name: "Cargar Excel" }).click();
  await page.getByLabel("Mes del consolidado").fill("2026-10");
  await page.getByLabel("Archivo consolidado (.xlsx)").setInputFiles({ name: "consolidado.xlsx", mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", buffer: Buffer.from("synthetic upload; parser tested on backend") });
  await expect(page.getByRole("button", { name: "Guardar 1 facturas" })).toBeEnabled();
  previewFailure = true;
  await page.getByRole("button", { name: "Revisar archivo" }).click();
  await expect(page.getByRole("alert")).toContainText("El servicio no está disponible");
  await expect(page.getByRole("button", { name: "Guardar 1 facturas" })).toBeDisabled();
  previewFailure = false;
  await page.getByRole("button", { name: "Revisar archivo" }).click();
  await expect(page.getByRole("button", { name: "Guardar 1 facturas" })).toBeEnabled();
  await page.getByText("Corregir nombres del Excel").click();
  await page.getByLabel("Compañía para DEMO", { exact: true }).selectOption("DEMO");
  await expect(page.getByRole("button", { name: "Guardar 1 facturas" })).toBeDisabled();
  await page.getByRole("button", { name: "Revisar archivo" }).click();
  await page.getByLabel("Mostrar facturas del Excel", { exact: true }).selectOption("REVIEW");
  await expect(page.getByText("Importe cero: revisar reparto")).toBeVisible();
  await page.screenshot({ path: "test-results/import-preview.png", fullPage: true });
  await page.getByRole("button", { name: "Guardar 1 facturas" }).click();
  await expect(page.getByText("1 facturas registradas.", { exact: false })).toBeVisible();
  expect(submitted.selected).toEqual(["ready"]);
  expect(submitted.period_month).toBe("2026-10-01");
  expect(submitted.company_map).toEqual({ DEMO: "DEMO" });
  await expect(page.getByRole("button", { name: "Guardar 0 facturas" })).toBeDisabled();
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
});

test("reference detail shows its provisions invoices and audit trail", async ({ page }) => {
  await setup(page);
  await page.route("**/api/v1/finance/references/*/activity", route => route.fulfill({ json: {
    reference: demoReport.balances[0].reference,
    provisions: [{ id: "p1", supplier: "Transportes Demo", concept: "FREIGHT", month: "2026-05-01", currency: "USD", total: "500", balance: "200", status: "PARTIALLY_MATCHED" }],
    invoices: [{ id: "l1", invoice_number: "EXCEL-01", supplier: "Transportes Demo", concept: "FREIGHT", month: "2026-10-01", currency: "USD", amount: "300", applied: "300", status: "APPROVED", amount_basis: "USD_AMOUNT" }],
    history: { items: demoHistory, total: demoHistory.length },
  } }));
  await section(page, "Provisiones");
  await page.locator(".reference-link").first().click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("200.00 USD");
  await expect(dialog).toContainText("EXCEL-01");
  await expect(dialog).toContainText("USD AMOUNT completo");
  await page.screenshot({ path: "test-results/reference-activity.png", fullPage: true });
  await dialog.getByRole("button", { name: "Cerrar movimientos" }).click();
  await expect(dialog).toHaveCount(0);
});
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
  await page.locator(".finance-tools summary").click();
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
  await section(page, "Facturas");
  await page
    .getByRole("button", { name: "Agregar factura", exact: true })
    .click();
  await page.getByLabel("Folio de factura").fill("F-003");
  await page.getByLabel("Periodo de registro", { exact: true }).fill("2026-11");
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
    .getByRole("button", { name: "Guardar factura", exact: true })
    .click();
  await expect(page.locator(".success[role=status]")).toContainText(
    "Factura guardada",
  );
  const body = writes.find((w) => w.path === "/finance/invoices")!.body;
  expect(body.lines).toHaveLength(2);
  expect(body.lines[0].net_amount).toBe("500.1234");
  expect(body.accounting_period).toBe("2026-11-01");
  await expect(page.getByLabel("Mes contable", { exact: true })).toHaveValue("2026-11");
  expect(new URL((await page.requests()).filter(request => request.url().includes("/finance/invoices?")).at(-1)!.url()).searchParams.get("month")).toBe("2026-11-01");
});
test("provision is saved with automatic approval and preserves unsaved navigation warning", async ({ page }) => {
  const writes = await setup(page);
  await section(page, "Provisiones");
  await page
    .getByRole("button", { name: "Nueva provisión", exact: true })
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
  await page.getByLabel("Fecha de provisión", { exact: true }).fill("2026-11-23");
  await page.getByLabel("Concepto", { exact: true }).selectOption("BROKER");
  await page.getByLabel("Importe neto", { exact: true }).fill("500");
  await page.getByRole("button", { name: "Guardar provisión" }).click();
  await expect(page.locator(".success[role=status]")).toContainText(
    "Provisión guardada y aprobada automáticamente",
  );
  expect(writes[0].body.shipment_id).toBe("shipment-1");
  expect(writes[0].body.amount).toBe("500");
  expect(writes[0].body.provision_date).toBe("2026-11-23");
  expect(writes[0].body.month_accrued).toBe("2026-11-01");
  expect(writes[0].body.charge_code).toBe("BROKER");
  await expect(page.getByLabel("Mes contable", { exact: true })).toHaveValue("2026-11");
  expect(new URL((await page.requests()).filter(request => request.url().includes("/finance/balances?")).at(-1)!.url()).searchParams.get("month")).toBe("2026-11-01");
});
test("invoice cancellation requires reason and accounting month", async ({
  page,
}) => {
  const writes = await setup(page);
  await section(page, "Facturas");
  await page.getByRole("button", { name: "Detalle", exact: true }).first().click();
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
    page.getByRole("button", { name: "Nueva provisión" }),
  ).toHaveCount(0);
  await section(page, "Facturas");
  await expect(
    page.getByRole("button", { name: "Agregar factura" }),
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


test("provision reference picker lists existing references and supports keyboard selection", async ({ page }) => {
  await setup(page);
  await section(page, "Provisiones");
  await page.getByRole("button", { name: "Nueva provisión", exact: true }).click();
  const input = page.getByRole("combobox", { name: "Referencia del master" });
  await input.focus();
  await expect(page.getByRole("listbox", { name: "Referencias disponibles" })).toBeVisible();
  await expect(page.getByRole("option", { name: new RegExp(demoReport.balances[0].reference) })).toBeVisible();
  await input.press("ArrowDown");
  await input.press("Enter");
  await expect(input).toHaveValue(demoReport.balances[0].reference);
  await expect(page.getByRole("listbox")).toHaveCount(0);
  await expect(page.getByLabel("Concepto", { exact: true }).locator("option")).toHaveText(["FREIGHT", "BROKER", "STORAGE"]);
  await expect(page.getByLabel("Fecha de provisión")).toHaveAttribute("type", "date");
  await input.fill("SIN-COINCIDENCIAS");
  await input.press("Escape");
  await expect(page.getByRole("listbox")).toHaveCount(0);
  await page.screenshot({ path: "test-results/new-provision.png", fullPage: true });
});

test("invoice workspace starts with a compact table and shows special actions only in its detail", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 768 });
  await setup(page);
  await page.route("**/api/v1/finance/invoices?**", route => route.fulfill({ json: {
    items: demoInvoices.map((row, i) => i ? { ...row, status: "UNDER_REVIEW", applied_amount: "150", pending_amount: "150" } : row), total: demoInvoices.length,
  } }));
  await section(page, "Facturas");
  await expect(page.getByRole("button", { name: "Cargar Excel", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Agregar factura", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Cancelar factura", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Aplicar a provisiones", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Abrir periodo", exact: true })).toHaveCount(0);
  await expect(page.locator(".finance-tools p")).toBeHidden();
  expect((await page.locator(".finance-table tbody tr").first().boundingBox())!.y).toBeLessThan(260);
  await page.screenshot({ path: "docs/invoices-simple-preview.png", fullPage: true });
  await page.getByRole("button", { name: "Detalle", exact: true }).last().click();
  await expect(page.getByRole("button", { name: "Cancelar factura", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Aplicar a provisiones", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Cargar Excel", exact: true }).click();
  await expect(page.locator(".finance-table-scroll")).toBeHidden();
  await expect(page.getByLabel("Archivo consolidado (.xlsx)")).toBeVisible();
});

test("complete provisions saved before automatic approval activate without an approval button", async ({ page }) => {
  await setup(page);
  let approvals = 0;
  const row = demoReport.balances[0];
  await page.route("**/api/v1/finance/balances?**", route => route.fulfill({ json: { items: [{ ...row, status: approvals ? "OPEN" : "DRAFT", current_status: approvals ? "OPEN" : "DRAFT" }], total: 1, totals: demoReport.totals } }));
  await page.route("**/api/v1/finance/provisions/*/approve", route => {
    approvals++;
    return route.fulfill({ json: { id: row.id, status: "OPEN", row_version: 2 } });
  });
  await section(page, "Provisiones");
  await expect(page.locator(".finance-status")).toHaveText("Viva");
  expect(approvals).toBe(1);
  await expect(page.getByRole("button", { name: "Aprobar", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Consultar", exact: true }).click();
  await expect(page.locator(".finance-status")).toHaveText("Viva");
  expect(approvals).toBe(1);
});

test("invoice references are visible and each line saves its selected concept", async ({ page }) => {
  const writes = await setup(page);
  const longReference = "RM1-REFERENCIA-COMPLETA-" + "IMPORTACION-TERRESTRE-".repeat(4) + "M01-MAT";
  const references = [
    { id: "ref-long", reference: longReference, company_code: "DEMO", owner_name: "DENI", business_unit: "M01" },
    { id: "ref-second", reference: "RM2-SEGUNDA-REFERENCIA-M19-MAT", company_code: "DEMO", owner_name: "MAG", business_unit: "M19" },
  ];
  const queries: string[] = [];
  await page.route("**/api/v1/finance/references?**", route => {
    queries.push(new URL(route.request().url()).searchParams.get("company_code") ?? "");
    return route.fulfill({ json: references });
  });
  await section(page, "Facturas");
  await page.getByRole("button", { name: "Agregar factura", exact: true }).click();
  await page.getByLabel("Folio de factura").fill("F-OTHER");
  await page.getByLabel("Proveedor de factura", { exact: true }).selectOption("supplier-1");
  const first = page.getByRole("combobox", { name: "Referencia 1", exact: true });
  await first.focus();
  await page.getByRole("option", { name: new RegExp(longReference) }).click();
  await expect(first).toHaveValue(longReference);
  await expect(page.locator(".reference-current strong")).toHaveText(longReference);
  await expect(page.getByLabel("Concepto 1", { exact: true }).locator("option")).toHaveText(["FREIGHT", "BROKER", "STORAGE", "OTROS"]);
  await page.getByLabel("Concepto 1", { exact: true }).selectOption({ label: "OTROS" });
  await page.getByLabel("Neto 1", { exact: true }).fill("125.1234");
  await page.getByRole("button", { name: "+ Otra referencia", exact: true }).click();
  const second = page.getByRole("combobox", { name: "Referencia 2", exact: true });
  await second.focus();
  await expect(page.getByRole("listbox").getByRole("option")).toHaveCount(2);
  await second.press("ArrowDown");
  await second.press("ArrowDown");
  await second.press("Enter");
  await expect(second).toHaveValue(references[1].reference);
  await expect(first).toHaveValue(longReference);
  await page.getByLabel("Concepto 2", { exact: true }).selectOption("BROKER");
  await page.getByLabel("Neto 2", { exact: true }).fill("200");
  for (const viewport of [{ width: 1366, height: 768 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport);
    expect(await page.locator(".reference-current strong").first().evaluate(el => el.scrollWidth <= el.clientWidth)).toBeTruthy();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  }
  await page.setViewportSize({ width: 1366, height: 768 });
  await page.screenshot({ path: "test-results/invoice-capture-references.png", fullPage: true });
  await page.getByRole("button", { name: "Guardar factura", exact: true }).click();
  await expect(page.locator(".success")).toContainText("Factura guardada");
  const payload = writes.find(w => w.path === "/finance/invoices")!.body;
  expect(payload.lines.map((line: any) => [line.reference, line.charge_code, line.net_amount])).toEqual([
    [longReference, "OTHER", "125.1234"], [references[1].reference, "BROKER", "200"],
  ]);
  expect(queries.length).toBeGreaterThanOrEqual(2);
  expect(queries.every(company => company === "DEMO")).toBeTruthy();
});

test("reference searches keep the latest result and closing a line cancels its suggestions", async ({ page }) => {
  await setup(page);
  let finishSlow!: () => void;
  const slow = new Promise<void>(resolve => finishSlow = resolve);
  let slowStarted = false;
  await page.route("**/api/v1/finance/references?**", async route => {
    const q = new URL(route.request().url()).searchParams.get("q");
    if (q === "LENTA") { slowStarted = true; await slow; }
    await route.fulfill({ json: [{ id: q || "initial", reference: q === "LENTA" ? "REF-ANTERIOR" : "REF-ACTUAL", company_code: "DEMO" }] }).catch(() => {});
  });
  await section(page, "Facturas");
  await page.getByRole("button", { name: "Agregar factura", exact: true }).click();
  const input = page.getByRole("combobox", { name: "Referencia 1", exact: true });
  await input.fill("LENTA");
  await expect.poll(() => slowStarted).toBeTruthy();
  await input.fill("RAPIDA");
  await expect(page.getByRole("option", { name: /REF-ACTUAL/ })).toBeVisible();
  finishSlow();
  await expect(page.getByRole("option", { name: /REF-ANTERIOR/ })).toHaveCount(0);
  await input.press("Escape");
  await expect(page.getByRole("listbox")).toHaveCount(0);
  await page.getByRole("button", { name: "+ Otra referencia", exact: true }).click();
  const second = page.getByRole("combobox", { name: "Referencia 2", exact: true });
  await second.focus();
  await expect(page.getByRole("listbox")).toBeVisible();
  await page.getByRole("button", { name: "Quitar línea 2", exact: true }).click();
  await expect(page.getByRole("listbox")).toHaveCount(0);
  await expect(page.getByRole("combobox", { name: "Referencia 1", exact: true })).toHaveValue("RAPIDA");
});
