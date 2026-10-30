import { test, expect, Page } from "@playwright/test";
import { demoCatalogs } from "../src/app/demo";
import { demoReport, demoInvoices, demoHistory } from "../src/app/finance-demo";

test("simple consolidation uses source months and keeps failed or changed previews from being saved", async ({ page }) => {
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
      sheet: "CONSOLIDADO 2026", row_count: 2, invoice_count: 2,
      counts: { READY: confirmed ? 0 : 1, REVIEW: 1, DUPLICATE: confirmed ? 1 : 0, OUTSIDE: 0 },
      companies: ["DEMO"], suppliers: ["TRANSPORTES DEMO"],
      groups: [
        { key: "ready", invoice_number: "EXCEL-001", company: "DEMO", supplier_name: "Transportes Demo", source_supplier: "TRANSPORTES DEMO", source_company: "DEMO", status: confirmed ? "DUPLICATE" : "READY", usd_amount: "500", issues: [], source_periods: ["2026-09-01"], rows: [{ row: 2, reference: "RM1-0001LI26-M01-MAT", charge_code: "FREIGHT", usd_amount: "500", reference_match: { status: "MATCHED" } }] },
        { key: "review", invoice_number: "EXCEL-002", company: "DEMO", supplier_name: "Transportes Demo", source_supplier: "TRANSPORTES DEMO", source_company: "DEMO", status: "REVIEW", usd_amount: "0", issues: ["Importe cero: revisar reparto"], rows: [{ row: 3, reference: "RM1-0002LI26-M01-MAT", charge_code: "FREIGHT", usd_amount: "0", reference_match: { status: "MATCHED" } }] },
      ],
    } });
  });
  await section(page, "Facturas");
  await page.getByRole("button", { name: "Cargar Excel" }).click();
  await expect(page.getByLabel("Mes del consolidado")).toHaveCount(0);
  await page.getByLabel("Archivo consolidado (.xlsx)").setInputFiles({ name: "consolidado.xlsx", mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", buffer: Buffer.from("synthetic upload; parser tested on backend") });
  const save = page.getByRole("button", { name: "Consolidar 1 factura", exact: true });
  await expect(save).toBeEnabled();
  await page.getByText("Tipo de cambio para provisiones en pesos", { exact: true }).click();
  await page.getByLabel("Tipo de cambio del lote (MXN por USD)", { exact: true }).fill("20");
  await page.getByLabel("Fecha del tipo de cambio del lote", { exact: true }).fill("2026-09-27");
  await expect(save).toBeDisabled();
  previewFailure = true;
  await page.getByRole("button", { name: "Actualizar revisión" }).click();
  await expect(page.getByRole("alert")).toContainText("El servicio no está disponible");
  await expect(save).toBeDisabled();
  previewFailure = false;
  await page.getByRole("button", { name: "Actualizar revisión" }).click();
  await expect(save).toBeEnabled();
  await page.getByText("Ajustar proveedor o empresa", { exact: true }).click();
  await page.getByLabel("Empresa para DEMO", { exact: true }).first().selectOption("DEMO");
  await expect(save).toBeEnabled();
  await page.getByRole("button", { name: "Por revisar 1", exact: true }).click();
  await expect(page.getByText("Importe cero: revisar reparto")).toBeVisible();
  await save.click();
  await expect(page.locator(".import-panel .success")).toContainText("1 factura consolidada");
  expect(submitted.selected).toEqual(["ready"]);
  expect(submitted.fx.mxn_per_usd).toBe("20");
  expect(submitted.use_source_period).toBe(true);
  expect(submitted.create_suppliers).toBe(true);
  expect(submitted.company_map).toEqual({ DEMO: "DEMO" });
  await expect(page.getByRole("button", { name: "Consolidar 0 facturas" })).toBeDisabled();
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
  await dialog.getByRole("button", { name: "Provisiones y facturas", exact: true }).click();
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
  const menu=page.getByRole("button",{name:"Abrir navegación",exact:true});
  if(await menu.isVisible()) await menu.click();
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
    .getByRole("button", { name: "Ver reporte de este mes", exact: true })
    .click();
  await expect(
    page.getByRole("region", { name: "Reporte de conciliación" }),
  ).toContainText("Liquidada");
  await page.getByRole("button", { name: "Facturas aplicadas", exact: true }).click();
  await expect(page.locator(".report-movements")).toContainText("DEMO-001");
  await expect(page.locator(".report-movements")).toContainText("08/10/2026");
  await expect(page.locator(".report-movements")).toContainText("12/10/2026");
  await expect(page.locator(".report-movements")).toContainText("Liquidada");
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
  await expect(page.getByLabel("Mes", { exact: true })).toHaveValue("2026-11");
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
  await expect(page.getByLabel("Mes", { exact: true })).toHaveValue("2026-11");
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

test("manual invoice captures MXN per USD and its date without changing the original invoice currency", async ({ page }) => {
  const writes = await setup(page);
  await section(page, "Facturas");
  await page.getByRole("button", { name: "Agregar factura", exact: true }).click();
  await page.getByLabel("Folio de factura", { exact: true }).fill("FX-MANUAL-TEST");
  await page.getByLabel("Proveedor de factura", { exact: true }).selectOption("supplier-1");
  await page.getByLabel("Moneda de factura", { exact: true }).selectOption("MXN");
  await page.getByLabel("Tipo de cambio (MXN por USD)", { exact: true }).fill("19.87654321");
  await page.getByLabel("Fecha del tipo de cambio", { exact: true }).fill("2026-10-27");
  await page.getByLabel("Referencia 1", { exact: true }).fill(demoReport.balances[0].reference);
  await page.getByLabel("Neto 1", { exact: true }).fill("5600");
  await page.getByRole("button", { name: "Guardar factura", exact: true }).click();
  await expect(page.locator(".success[role=status]")).toContainText("Factura guardada");
  const body = writes.find(write => write.path === "/finance/invoices")!.body;
  expect(body.currency).toBe("MXN");
  expect(body.lines[0].net_amount).toBe("5600");
  expect(body.fx).toEqual({ mxn_per_usd: "19.87654321", rate_date: "2026-10-27" });
  expect(body).not.toHaveProperty("fx_mxn_per_usd");
});

test("pending invoice detail requests the missing rate and shows both applied currencies", async ({ page }) => {
  await setup(page);
  let submitted: any;
  let row = { ...demoInvoices[0], currency: "MXN", status: "UNDER_REVIEW", fx_required: true, fx: null as any, net_amount: "5600", applied_amount: "0", pending_amount: "5600", lines: [{ ...demoInvoices[0].lines[0], net_amount: "5600", applied_amount: "0", pending_amount: "5600", applications: [] as any[] }] };
  await page.route("**/api/v1/finance/invoices**", async route => {
    if (route.request().method() === "POST") {
      submitted = route.request().postDataJSON();
      row = { ...row, status: "APPROVED", fx_required: false, fx: submitted.fx, applied_amount: "5600", pending_amount: "0", lines: [{ ...row.lines[0], applied_amount: "5600", pending_amount: "0", applications: [{ id: "a-fx", provision_id: "p-fx", provision_amount: "280", provision_currency: "USD", invoice_amount: "5600", fx: submitted.fx }] }] };
      return route.fulfill({ json: row });
    }
    return route.fulfill({ json: { items: [row], total: 1, limit: 20, offset: 0 } });
  });
  await section(page, "Facturas");
  await expect(page.locator(".finance-table tbody")).toContainText("Falta tipo de cambio");
  await page.getByRole("button", { name: "Detalle", exact: true }).click();
  const detail = page.locator(".invoice-detail");
  await detail.getByLabel("Tipo de cambio (MXN por USD)", { exact: true }).fill("20");
  await detail.getByLabel("Fecha del tipo de cambio", { exact: true }).fill("2026-10-27");
  await detail.getByRole("button", { name: "Aplicar a provisiones", exact: true }).click();
  await expect(detail).toContainText("5,600.00 MXN descontaron 280.00 USD");
  expect(submitted.fx).toEqual({ mxn_per_usd: "20", rate_date: "2026-10-27" });
  await expect(page.locator(".finance-status")).toHaveText("Aplicada");
});

test("known Excel references are ready in their source month without a month selector", async ({ page }) => {
  await setup(page);
  await page.route("**/api/v1/finance/import/preview", async route => {
    const outside = !route.request().postDataJSON().use_source_period;
    await route.fulfill({ json: {
      sheet: "CONSOLIDADO 2026", row_count: 2, invoice_count: 2,
      counts: { READY: outside ? 0 : 1, REVIEW: outside ? 0 : 1, DUPLICATE: 0, OUTSIDE: outside ? 2 : 0 },
      reference_counts: { MATCHED: 1, OTHER_COMPANY: 0, NOT_FOUND: 1, AMBIGUOUS: 0 },
      available_periods: [{ period_month: "2026-09-01", row_count: 2, invoice_count: 2 }],
      companies: ["DEMO"], suppliers: ["TRANSPORTES DEMO"],
      groups: [
        { key: "found", invoice_number: "DETECTED-TEST", company: "DEMO", supplier_name: "Transportes Demo", source_supplier: "TRANSPORTES DEMO", source_company: "DEMO", status: outside ? "OUTSIDE" : "READY", usd_amount: "500", issues: [], source_periods: ["2026-09-01"], rows: [{ row: 2, reference: "SYNTHETIC-FOUND-REFERENCE", charge_code: "FREIGHT", usd_amount: "500", source_period: "2026-09-01", reference_match: { status: "MATCHED", shipment_id: "ship-1", reference: "SYNTHETIC-FOUND-REFERENCE", company: "DEMO", owner_name: "Analista de prueba" } }] },
        { key: "missing", invoice_number: "MISSING-TEST", company: "DEMO", supplier_name: "Transportes Demo", source_supplier: "TRANSPORTES DEMO", source_company: "DEMO", status: outside ? "OUTSIDE" : "REVIEW", usd_amount: "100", issues: ["Referencia sin coincidencia"], source_periods: ["2026-09-01"], rows: [{ row: 3, reference: "SYNTHETIC-MISSING", charge_code: "BROKER", usd_amount: "100", source_period: "2026-09-01", reference_match: { status: "NOT_FOUND" } }] },
      ],
    } });
  });
  await section(page, "Facturas");
  await page.getByRole("button", { name: "Cargar Excel", exact: true }).click();
  await page.getByLabel("Archivo consolidado (.xlsx)", { exact: true }).setInputFiles({ name: "synthetic.xlsx", mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", buffer: Buffer.from("synthetic; parser tested separately") });
  await expect(page.getByRole("button", { name: "Coincidencias 1", exact: true })).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator(".import-review-bar")).toContainText("1 factura lista");
  await expect(page.locator(".import-table")).toContainText("septiembre de 2026");
  await expect(page.locator(".import-table tbody")).toContainText("SYNTHETIC-FOUND-REFERENCE");
  await expect(page.locator(".import-match")).toHaveText("Encontrada · Master de Analista de prueba · DEMO");
  await expect(page.getByRole("button", { name: "Consolidar 1 factura", exact: true })).toBeEnabled();
  await page.getByLabel("Buscar referencia o factura en el Excel", { exact: true }).fill(" synthetic- found-reference ");
  await expect(page.locator(".import-table tbody tr")).toHaveCount(1);
  await expect(page.getByLabel("Mes del consolidado")).toHaveCount(0);
  await page.getByLabel("Buscar referencia o factura en el Excel", { exact: true }).fill("");
  await page.screenshot({ path: "test-results/simple-consolidation.png", fullPage: true });
  await page.getByRole("button", { name: "Sin referencia 1", exact: true }).click();
  await expect(page.locator(".import-table tbody")).toContainText("SYNTHETIC-MISSING");
  await page.screenshot({ path: "test-results/import-reference-detection.png", fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
});

test("unmatched invoices are visible without a catalog of irrelevant supplier mappings", async ({ page }) => {
  await setup(page);
  await page.route("**/api/v1/finance/import/preview", route => route.fulfill({ json: {
    sheet: "CONSOLIDADO 2026", row_count: 1, invoice_count: 1, counts: { READY: 0, REVIEW: 0, DUPLICATE: 0, OUTSIDE: 1 }, companies: ["DEMO"], suppliers: [],
    available_periods: [{ period_month: "2026-09-01", row_count: 1, invoice_count: 1 }],
    groups: [{ key: "outside", invoice_number: "VISIBLE-OUTSIDE-TEST", company: "DEMO", supplier_name: "Pendiente", source_company: "DEMO", source_supplier: "PENDIENTE", status: "OUTSIDE", usd_amount: "100", issues: ["Vincula el proveedor"], source_periods: ["2026-09-01"], rows: [{ row: 2, reference: "SYNTHETIC-MISSING", charge_code: "FREIGHT", usd_amount: "100", reference_match: { status: "NOT_FOUND" } }] }],
  } }));
  await section(page, "Facturas");
  await page.getByRole("button", { name: "Cargar Excel", exact: true }).click();
  await page.getByLabel("Archivo consolidado (.xlsx)", { exact: true }).setInputFiles({ name: "synthetic.xlsx", mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", buffer: Buffer.from("synthetic preview") });
  await expect(page.getByRole("button", { name: "Sin referencia 1", exact: true })).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator(".import-table tbody")).toContainText("VISIBLE-OUTSIDE-TEST");
  await expect(page.getByText("Corregir nombres del Excel", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Consolidar 0 facturas", exact: true })).toBeDisabled();
});


test("monthly report opens from invoices and refreshes month and reference together", async ({ page }) => {
  await setup(page);
  const queries: URLSearchParams[] = [];
  await page.route("**/api/v1/finance/report?**", route => {
    const query = new URL(route.request().url()).searchParams;
    queries.push(query);
    return route.fulfill({ json: { ...demoReport, month: query.get("month") } });
  });
  await section(page, "Facturas");
  await page.getByLabel("Factura o referencia", { exact: true }).fill("DEMO-001");
  await page.getByRole("button", { name: "Ver reporte de este mes", exact: true }).click();
  await expect(page.locator(".report-balances")).toContainText("Viva · parcial");
  expect(queries[0].get("q")).toBeNull();
  await page.getByLabel("Mes", { exact: true }).fill("2026-09");
  await page.getByLabel("Referencia", { exact: true }).fill("RM1");
  await page.getByRole("button", { name: "Consultar", exact: true }).click();
  await expect(page.locator(".report-overview")).toContainText("2026-09");
  expect(queries.at(-1)!.get("q")).toBe("RM1");
  expect(queries.at(-1)!.get("month")).toBe("2026-09-01");
  await page.getByRole("button", { name: "Volver a facturas", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Facturas", exact: true })).toBeVisible();
});
