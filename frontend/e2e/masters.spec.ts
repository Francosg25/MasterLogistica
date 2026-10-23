import { expect, test, Page } from "@playwright/test";
import { demoCatalogs, demoShipments } from "../src/app/demo";
import { Supplier } from "../src/app/types";

const cell = (page: Page, row: number, field: string) =>
  page.locator(`td[data-row="${row}"][data-field="${field}"]`);

test("home navigation and expanded master preserve the sheet", async ({ page }) => {
  await mock(page);
  await page.getByRole("navigation", { name: "Secciones" }).getByRole("button", { name: "Inicio", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Tu espacio de trabajo." })).toBeVisible();
  await page.screenshot({ path: "test-results/home.png", fullPage: true });
  await page.locator(".home-grid").getByRole("button", { name: /Abrir masters/ }).click();
  const normal = await page.getByRole("region", { name: "Hoja del master" }).boundingBox();
  await page.getByRole("button", { name: "Ampliar master" }).click();
  await expect(page.getByRole("navigation", { name: "Secciones" })).toBeHidden();
  const expanded = await page.getByRole("region", { name: "Hoja del master" }).boundingBox();
  expect(expanded!.y).toBeLessThan(normal!.y);
  await expect(page.locator("tbody tr")).toHaveCount(8);
  await page.screenshot({ path: "test-results/master-expanded.png", fullPage: true });
  await page.getByRole("button", { name: "Salir de vista ampliada" }).click();
  await expect(page.getByRole("navigation", { name: "Secciones" })).toBeVisible();
});
async function pasteCells(
  page: Page,
  row: number,
  field: string,
  text: string,
) {
  const target = cell(page, row, field);
  await target.click();
  await target.evaluate((element, value) => {
    const clipboardData = new DataTransfer();
    clipboardData.setData("text/plain", value);
    element.dispatchEvent(
      new ClipboardEvent("paste", {
        clipboardData,
        bubbles: true,
        cancelable: true,
      }),
    );
  }, text);
}

async function mock(
  page: Page,
  options: {
    role?: string;
    empty?: boolean;
    failure?: boolean;
    conflict?: boolean;
    conflictId?: string;
    networkFailure?: boolean;
    count?: number;
    mixed?: boolean;
    noMaster?: boolean;
    collapsed?: boolean;
    accessDenied?: boolean;
    suppliers?: Supplier[];
  } = {},
) {
  let rows = options.empty
    ? []
    : Array.from({ length: options.count ?? 8 }, (_, i) => ({
        ...demoShipments[i % 8],
        id: `shipment-${i}`,
        owner_id: "owner-1",
      }));
  rows = options.mixed
    ? Array.from({ length: 5 }, (_, owner) =>
        rows.map((row) => ({
          ...row,
          id: `${owner}-${row.id}`,
          owner_id: `owner-${owner + 1}`,
          reference_raw: row.reference_raw!.replace("RM1-", `RM${owner + 1}-`),
        })),
      ).flat()
    : rows.map((row, i) => ({
        ...row,
        operation_code: "SI",
        reference_raw: `RM1-${String(i + 1).padStart(4, "0")}SI26-M01-MAT`,
      }));
  let identifiers: {
    id: string;
    kind: string;
    raw_value: string;
    normalized_value: string;
  }[] = [];
  const requests: {
    path: string;
    method: string;
    body: Record<string, unknown> | null;
  }[] = [];
  await page.route("**/api/v1/**", async (route) => {
    const req = route.request(),
      url = new URL(req.url()),
      path = url.pathname.replace("/api/v1", "");
    const body = req.postDataJSON();
    requests.push({ path, method: req.method(), body });
    const json = (data: unknown, status = 200) =>
      route.fulfill({ status, json: data });
    if (path === "/auth/me")
      return json({
        id: "owner-1",
        display_name: "Analista de prueba",
        email: "test@example.com",
        role: options.role ?? "OPERATOR",
        analyst_code: 1,
      });
    if (path === "/references/catalogs") return json({ ...demoCatalogs,
      ...(options.accessDenied ? { master_access: { can_edit: false, can_create: false, edit_scope: "NONE", read_only_reason: "La edición operativa no está habilitada para esta sesión." } } : {}),
    });
    if (path === "/masters/owners")
      return json(
        Array.from(
          {
            length:
              options.role === "MANAGER" || options.role === "SUPER_ADMIN"
                ? 5
                : 1,
          },
          (_, i) => ({
            id: `owner-${i + 1}`,
            display_name:
              i === 0 ? "Analista de prueba" : `Integrante ${i + 1}`,
            analyst_code: i + 1,
          }),
        ),
      );
    if (path === "/suppliers")
      return json({ items: options.suppliers ?? [], total: options.suppliers?.length ?? 0, limit: 100, offset: 0 });
    if (path.endsWith("/identifiers")) {
      if (req.method() === "POST") {
        const row = {
          ...body,
          id: "identifier-1",
          normalized_value: body.raw_value,
        };
        identifiers.push(row);
        return json(row, 201);
      }
      return json(identifiers);
    }
    if (req.method() === "POST" && path === "/shipments") {
      const row = {
        ...demoShipments[0],
        ...body,
        id: "created-1",
        row_version: 1,
        owner_id: "owner-1",
        reference_raw: `RM1-0009${body.operation_code}26-M01-MAT`,
      };
      rows = [row, ...rows];
      return json(row, 201);
    }
    if (path.startsWith("/shipments/") && path !== "/shipments/summary") {
      const id = path.split("/").pop(),
        row = rows.find((row) => row.id === id);
      if (req.method() === "PATCH") {
        if (options.networkFailure) return route.abort("failed");
        if (options.conflict || options.conflictId === id)
          return json({ detail: "Record changed" }, 409);
        const updated = { ...row, ...body, row_version: 2 };
        rows = rows.map((r) => (r.id === id ? updated : r));
        return json(updated);
      }
      return row ? json(row) : json({ detail: "Not found" }, 404);
    }
    if (path === "/masters/shipments" || path === "/masters/summary") {
      if (options.failure) return json({ detail: "Unavailable" }, 503);
      const filtered = rows.filter((row) =>
        [...url.searchParams].every(([key, value]) => {
          if (["offset", "limit"].includes(key)) return true;
          if (key === "q")
            return [row.reference_raw, row.sender, row.consignee].some((text) =>
              text?.toLowerCase().includes(value.toLowerCase()),
            );
          if (key === "ship_date_from")
            return !!row.ship_date && row.ship_date >= value;
          if (key === "ship_date_to")
            return !!row.ship_date && row.ship_date <= value;
          return row[key as keyof typeof row] === value;
        }),
      );
      if (path.endsWith("/summary")) {
        const by_status: Record<string, number> = {};
        filtered.forEach(
          (row) => (by_status[row.status] = (by_status[row.status] ?? 0) + 1),
        );
        return json({ total: filtered.length, by_status });
      }
      const offset = Number(url.searchParams.get("offset") ?? 0),
        limit = Number(url.searchParams.get("limit") ?? 20);
      return json({
        items: filtered.slice(offset, offset + limit),
        total: filtered.length,
        offset,
        limit,
      });
    }
    return json({ detail: "Unexpected request" }, 404);
  });
  await page.goto("/");
  await page.getByRole("navigation", { name: "Secciones" }).getByRole("button", { name: "Masters", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Masters de logística." }),
  ).toBeVisible();
  if (!options.noMaster) {
    await page
      .getByLabel("Responsable del master", { exact: true })
      .selectOption("owner-1");
    await page
      .getByRole("button", { name: "Abrir master", exact: true })
      .click();
    if (!options.collapsed) await page.getByRole("button", { name: "Mostrar filtros", exact: true }).click();
  }
  return requests;
}

test("filters and reset retain the selected master", async ({ page }) => {
  await mock(page);
  await expect(page.locator("tbody tr")).toHaveCount(8);
  await page.getByLabel("Estado", { exact: true }).selectOption("CUSTOMS");
  await page.getByRole("button", { name: "Aplicar", exact: true }).click();
  await expect(page.locator("tbody tr")).toHaveCount(2);
  await page
    .getByRole("button", { name: "Limpiar filtros", exact: true })
    .click();
  await expect(page.locator("tbody tr")).toHaveCount(8);
  await expect(page.getByLabel("Responsable del master", { exact: true })).toHaveValue("owner-1");
  await page.getByLabel("Estado", { exact: true }).selectOption("IN_TRANSIT");
  await page.getByRole("button", { name: "Aplicar", exact: true }).click();
  await expect(page.locator("tbody tr")).toHaveCount(2);
  await page
    .getByRole("button", { name: "Limpiar filtros", exact: true })
    .click();
  await expect(page.locator("tbody tr")).toHaveCount(8);
});
test("each responsible master contains its operations without mixing owners", async ({ page }) => {
  const requests = await mock(page, { role: "MANAGER", mixed: true, noMaster: true });
  expect(requests.some(req => req.path === "/masters/shipments")).toBeFalsy();
  const selector = page.getByLabel("Responsable del master", { exact: true });
  await expect(selector.locator("option")).toHaveCount(6);
  await selector.selectOption("owner-1");
  await page.getByRole("button", { name: "Abrir master", exact: true }).click();
  await expect(page.locator("tbody tr")).toHaveCount(8);
  await expect(page.locator("tbody")).toContainText("RM1-0001SI26");
  await expect(page.locator("tbody")).toContainText("RM1-0002AI26");
  await expect(page.locator("tbody")).not.toContainText("RM5-");
  await selector.selectOption("owner-5");
  await expect(page.locator("tbody tr")).toHaveCount(0);
  await page.getByRole("button", { name: "Abrir master", exact: true }).click();
  await expect(page.locator("tbody tr")).toHaveCount(8);
  await expect(page.locator("tbody")).toContainText("RM5-0002AI26");
  await expect(page.locator("tbody")).not.toContainText("RM1-");
});
test("operator can select only their own master", async ({ page }) => {
  const requests = await mock(page, { mixed: true, noMaster: true });
  expect(requests.some(req => req.path === "/masters/shipments")).toBeFalsy();
  const selector = page.getByLabel("Responsable del master", { exact: true });
  await expect(selector.locator("option")).toHaveCount(2);
  await expect(page.getByRole("button", { name: "Nuevo embarque" })).toBeDisabled();
  await selector.selectOption("owner-1");
  await page.getByRole("button", { name: "Abrir master", exact: true }).click();
  await expect(page.locator("tbody tr")).toHaveCount(8);
  await expect(page.locator("tbody")).not.toContainText("RM2-");
});
test("creates in the selected master with manual company and an allowed BU, then attaches a pedimento", async ({
  page,
}) => {
  const requests = await mock(page);
  await page.getByRole("button", { name: "Nuevo embarque" }).click();
  const dialog = page.getByRole("dialog");
  await dialog
    .getByRole("button", { name: "Crear embarque", exact: true })
    .click();
  await expect(dialog.getByRole("alert")).toContainText("Completa");
  await dialog.getByLabel("Empresa *", { exact: true }).fill("MXG");
  await dialog.getByLabel("Tipo de operación *", { exact: true }).selectOption("SI");
  await expect(dialog.getByLabel("Business unit *", { exact: true }).locator("option")).toHaveText(["Selecciona una BU", "M01", "M19", "M23", "M45", "M46"]);
  await dialog
    .getByLabel("Business unit *", { exact: true })
    .selectOption("M01");
  await dialog
    .getByRole("button", { name: "Crear embarque", exact: true })
    .click();
  await expect(
    dialog.getByRole("heading", { name: "RM1-0009SI26-M01-MAT" }),
  ).toBeVisible();
  const creation = requests.find(
    (r) => r.path === "/shipments" && r.method === "POST",
  )!;
  expect(creation.body?.["owner_id"]).toBe("owner-1");
  expect(creation.body?.["company_code"]).toBe("MXG");
  expect(creation.body).not.toHaveProperty("reference_raw");
  expect(creation.body?.["business_unit"]).toBe("M01");
  await dialog.getByLabel("Número de documento").fill("26 00 0000 0001234");
  await dialog.getByRole("button", { name: "Agregar", exact: true }).click();
  await expect(dialog.locator(".identifier-list")).toContainText(
    "26 00 0000 0001234",
  );
  await dialog.getByLabel("Comentarios").fill("Nueva información");
  await dialog.getByRole("button", { name: "Guardar cambios" }).click();
  await expect
    .poll(() => requests.filter((r) => r.method === "PATCH").length)
    .toBe(1);
  expect(
    requests.filter((r) => r.method === "POST" && r.path === "/shipments"),
  ).toHaveLength(1);
});
test("each shipment selects its own operation and specific fields", async ({ page }) => {
  await mock(page);
  await page.getByRole("button", { name: "Nuevo embarque" }).click();
  const dialog = page.getByRole("dialog");
  const operation = dialog.getByLabel("Tipo de operación *", { exact: true });
  await expect(operation).toHaveValue("");
  await operation.selectOption("SI");
  await expect(dialog.getByLabel("Naviera", { exact: true })).toBeVisible();
  await operation.selectOption("R1");
  await expect(dialog.getByLabel("Naviera", { exact: true })).toHaveCount(0);
  await expect(dialog.getByRole("heading", { name: "Seguimiento de la operación" })).toBeVisible();
});
test("conflict preserves edits and requires explicit reload before saving", async ({
  page,
}) => {
  const requests = await mock(page, { conflict: true });
  await page.locator(".reference-link").first().click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Comentarios").fill("Cambio en conflicto");
  await dialog.getByRole("button", { name: "Guardar cambios" }).click();
  await expect(dialog.getByRole("alert")).toContainText("conflicto");
  await expect(dialog.getByLabel("Comentarios")).toHaveValue(
    "Cambio en conflicto",
  );
  await expect(
    dialog.getByRole("button", { name: "Guardar cambios" }),
  ).toBeDisabled();
  const update = requests.find((r) => r.method === "PATCH")!;
  expect(update.body?.["expected_version"]).toBe(1);
  expect(update.body).not.toHaveProperty("process_code");
  page.once("dialog", (d) => d.accept());
  await dialog.getByRole("button", { name: "Recargar registro" }).click();
  await expect(
    page.getByRole("dialog").getByRole("button", { name: "Guardar cambios" }),
  ).toBeEnabled();
});
for (const role of ["MANAGER", "FINANCE"]) {
  test(`${role} can inspect but cannot create or edit`, async ({ page }) => {
    await mock(page, { role });
    await expect(
      page.getByRole("button", { name: "Nuevo embarque" }),
    ).toHaveCount(0);
    await page.locator(".reference-link").first().click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByLabel("Comentarios")).toBeDisabled();
    await expect(
      dialog.getByRole("button", { name: "Guardar cambios" }),
    ).toHaveCount(0);
  });
}
test("administrator can edit the consolidated master", async ({ page }) => {
  await mock(page, { role: "SUPER_ADMIN", mixed: true });
  await expect(page.getByRole("button", { name: "Nuevo embarque" })).toBeEnabled();
  await expect(page.locator("tbody tr")).toHaveCount(8);
  await page.locator(".reference-link").last().click();
  await expect(page.getByRole("dialog").getByLabel("Comentarios")).toBeEnabled();
});
test("pagination retains filters", async ({ page }) => {
  await mock(page, { count: 55 });
  await expect(page.locator("tbody tr")).toHaveCount(50);
  await page.getByRole("button", { name: "Página siguiente" }).click();
  await expect(page.locator("tbody tr")).toHaveCount(5);
  await expect(page.locator(".table-footer")).toContainText("51–55 de 55");
  await page.getByRole("button", { name: "Página anterior" }).click();
  await expect(page.locator("tbody tr")).toHaveCount(50);
});
test("database errors do not masquerade as empty success", async ({ page }) => {
  await mock(page, { failure: true });
  await expect(page.getByRole("alert")).toContainText(
    "servicio no está disponible",
  );
  await expect(page.getByText("No hay embarques para mostrar")).toHaveCount(0);
  await expect(page.getByRole("grid")).toHaveCount(0);
});
test("empty state and date range validation", async ({ page }) => {
  await mock(page, { empty: true });
  await expect(page.getByText("No hay embarques para mostrar")).toBeVisible();
  await page.locator("summary").click();
  await page.getByLabel("Embarque desde").fill("2026-10-20");
  await page.getByLabel("Embarque hasta").fill("2026-10-01");
  await page.getByRole("button", { name: "Aplicar", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("fecha inicial");
});
test("desktop and mobile render without script errors or page overflow", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await mock(page);
  await expect(page.locator("tbody tr")).toHaveCount(8);
  await expect(page.locator("tbody tr").first()).toContainText("01/10/2026");
  await page.screenshot({
    path: "test-results/masters-desktop.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  const controls = await page
    .locator(".filter-main > label, .filter-main > button")
    .evaluateAll((elements) =>
      elements.map((element) => {
        const box = element.getBoundingClientRect();
        return {
          left: box.left,
          right: box.right,
          top: box.top,
          bottom: box.bottom,
        };
      }),
    );
  for (let i = 0; i < controls.length; i++)
    for (let j = i + 1; j < controls.length; j++) {
      const a = controls[i],
        b = controls[j];
      expect(
        a.right <= b.left ||
          b.right <= a.left ||
          a.bottom <= b.top ||
          b.bottom <= a.top,
      ).toBeTruthy();
    }
  await page.screenshot({
    path: "test-results/masters-mobile.png",
    fullPage: true,
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBeTruthy();
  await page.locator(".reference-link").first().click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.screenshot({ path: "test-results/masters-detail.png" });
  expect(errors).toEqual([]);
});

test("compact master gives records most of the window without expanding the view", async ({ page }) => {
  await mock(page, { count: 60, collapsed: true });
  for (const viewport of [
    { width: 1920, height: 1080 },
    { width: 1366, height: 768 },
    { width: 1280, height: 600 },
  ]) {
    await page.setViewportSize(viewport);
    const first = await page.locator("tbody tr").first().boundingBox();
    const sheet = await page.locator(".sheet-scroll").boundingBox();
    const footer = await page.locator(".table-footer").boundingBox();
    expect(first!.y).toBeLessThan(240);
    expect(sheet!.height - 60).toBeGreaterThan(viewport.height / 2);
    expect(footer!.y + footer!.height).toBeLessThanOrEqual(viewport.height);
    await expect(page.getByLabel("Responsable del master", { exact: true })).toBeVisible();
    await expect(page.getByRole("navigation", { name: "Secciones" })).toBeVisible();
    await expect(page.locator("#master-filters")).toBeHidden();
    expect(await page.evaluate(() => window.scrollY)).toBe(0);
  }
  await page.setViewportSize({ width: 1366, height: 768 });
  await page.screenshot({ path: "docs/masters-preview.png", fullPage: true });
});

test("typing in a selected cell edits text, dates and catalog values immediately", async ({ page }) => {
  const requests = await mock(page, { collapsed: true, suppliers: [
    { id: "supplier-1", code: "TR001", legal_name: "Transportes de prueba", is_active: true },
  ] });
  const firstRowTop = (await page.locator("tbody tr").first().boundingBox())!.y;
  await cell(page, 0, "sender").click();
  await page.keyboard.type("Proveedor escrito directamente");
  await expect(page.getByLabel("Editar Remitente / Proveedor", { exact: true })).toHaveValue("Proveedor escrito directamente");
  await page.keyboard.press("Enter");
  await expect(cell(page, 1, "sender")).toBeFocused();

  await cell(page, 0, "ship_date").click();
  await page.keyboard.type("25/10/2026");
  await page.keyboard.press("Tab");
  await expect(cell(page, 0, "ship_date")).toHaveText("25/10/2026");
  await expect(cell(page, 0, "eta")).toBeFocused();

  await cell(page, 0, "status").click();
  await page.keyboard.type("Entregado");
  await page.keyboard.press("Tab");
  await expect(cell(page, 0, "status")).toHaveText("Entregado");

  await cell(page, 0, "carrier_broker_id").click();
  await page.keyboard.type("TR001");
  await page.keyboard.press("Enter");
  await expect(cell(page, 0, "carrier_broker_id")).toHaveText("Transportes de prueba");
  await expect(page.locator(".save-state")).toContainText("4 celdas sin guardar");
  expect(requests.filter(r => r.method === "PATCH")).toHaveLength(0);
  await page.keyboard.press("Control+s");
  await expect(page.locator(".save-state")).toContainText("Sin cambios pendientes");
  expect((await page.locator("tbody tr").first().boundingBox())!.y).toBe(firstRowTop);
  expect(requests.find(r => r.method === "PATCH")?.body).toEqual({
    sender: "Proveedor escrito directamente", ship_date: "2026-10-25", status: "DELIVERED",
    carrier_broker_id: "supplier-1", expected_version: 1,
  });
});

test("direct typing validates dates and catalogs and Escape restores the original cell", async ({ page }) => {
  const requests = await mock(page, { collapsed: true });
  await cell(page, 0, "ship_date").click();
  await page.keyboard.type("31/02/2026");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("alert")).toContainText("Fecha de embarque");
  await expect(page.getByLabel("Editar Fecha de embarque", { exact: true })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(cell(page, 0, "ship_date")).toHaveText("01/10/2026");
  await cell(page, 0, "status").click();
  await page.keyboard.type("Estado inexistente");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("alert")).toContainText("catálogo");
  await page.keyboard.press("Escape");
  await expect(cell(page, 0, "status")).toHaveText("En tránsito");
  await cell(page, 0, "operation_code").click();
  await page.keyboard.press("A");
  await expect(page.locator(".sheet-message")).toContainText("Tipo de operación: columna protegida");
  await expect(page.locator(".cell-input")).toHaveCount(0);
  await expect(page.locator(".save-state")).toContainText("Sin cambios pendientes");
  expect(requests.filter(r => r.method === "PATCH")).toHaveLength(0);
});

test("sheet stages keyboard edits and saves only changed fields with row versions", async ({
  page,
}) => {
  const requests = await mock(page);
  await cell(page, 0, "sender").dblclick();
  await page
    .getByLabel("Editar Remitente / Proveedor", { exact: true })
    .fill("Proveedor actualizado");
  await page
    .getByLabel("Editar Remitente / Proveedor", { exact: true })
    .press("Tab");
  await expect(cell(page, 0, "origin")).toBeFocused();
  await page.keyboard.press("Enter");
  await page.getByLabel("Editar Origen", { exact: true }).fill("Monterrey, MX");
  await page.getByLabel("Editar Origen", { exact: true }).press("Enter");
  await expect(cell(page, 1, "origin")).toBeFocused();
  await expect(page.locator(".save-state")).toContainText(
    "2 celdas sin guardar",
  );
  expect(requests.filter((r) => r.method === "PATCH")).toHaveLength(0);
  await page.getByRole("button", { name: "Guardar cambios" }).click();
  await expect(page.locator(".save-state")).toContainText(
    "Sin cambios pendientes",
  );
  expect(requests.find((r) => r.method === "PATCH")?.body).toEqual({
    sender: "Proveedor actualizado",
    origin: "Monterrey, MX",
    expected_version: 1,
  });
  await pasteCells(page, 0, "origin", "Saltillo, MX");
  await page.getByRole("button", { name: "Guardar cambios" }).click();
  await expect(page.locator(".save-state")).toContainText(
    "Sin cambios pendientes",
  );
  expect(
    requests.filter((r) => r.method === "PATCH")[1].body?.["expected_version"],
  ).toBe(2);
});

test("paste from Excel stages a rectangular range and undo restores it", async ({
  page,
}) => {
  const requests = await mock(page);
  await pasteCells(
    page,
    0,
    "ship_date",
    "12/10/2026\t2026-10-20\r\n13/10/2026\t2026-10-21\r\n",
  );
  await expect(cell(page, 0, "ship_date")).toHaveText("12/10/2026");
  await expect(cell(page, 1, "eta")).toHaveText("21/10/2026");
  await expect(page.locator(".save-state")).toContainText(
    "4 celdas sin guardar",
  );
  await page.keyboard.press("Control+z");
  await expect(cell(page, 0, "ship_date")).toHaveText("01/10/2026");
  await expect(page.locator(".save-state")).toContainText(
    "Sin cambios pendientes",
  );
  expect(requests.filter((r) => r.method === "PATCH")).toHaveLength(0);
});

test("invalid dates, protected columns and oversized pastes do not partially stage changes", async ({
  page,
}) => {
  await mock(page);
  await pasteCells(page, 0, "ship_date", "12/10/2026\t31/02/2026");
  await expect(page.getByRole("alert")).toContainText("ETA");
  await expect(cell(page, 0, "ship_date")).toHaveText("01/10/2026");
  await pasteCells(page, 0, "status", "Entregado\tM19");
  await expect(page.getByRole("alert")).toContainText("solo lectura");
  await expect(cell(page, 0, "status")).toContainText("En tránsito");
  await pasteCells(page, 7, "sender", "A\nB");
  await expect(page.getByRole("alert")).toContainText("excede");
  await expect(page.locator(".save-state")).toContainText(
    "Sin cambios pendientes",
  );
});

test("quoted multiline Excel cells and range copy preserve values", async ({
  page,
}) => {
  await mock(page);
  await pasteCells(page, 0, "sender", '"Proveedor\nNorte"\t"Ciudad\tCentro"');
  await cell(page, 0, "sender").click();
  await page.keyboard.press("Shift+ArrowRight");
  const copied = await cell(page, 0, "origin").evaluate((element) => {
    const clipboardData = new DataTransfer();
    element.dispatchEvent(
      new ClipboardEvent("copy", {
        clipboardData,
        bubbles: true,
        cancelable: true,
      }),
    );
    return clipboardData.getData("text/plain");
  });
  expect(copied).toBe('"Proveedor\nNorte"\t"Ciudad\tCentro"');
});

test("partial save preserves failed rows and prevents retrying a stale version", async ({
  page,
}) => {
  const requests = await mock(page, { conflictId: "shipment-1" });
  await pasteCells(page, 0, "sender", "Proveedor A\nProveedor B\nProveedor C");
  await page.getByRole("button", { name: "Guardar cambios" }).click();
  await expect(page.getByRole("alert")).toContainText("conflicto");
  await expect(page.locator(".save-state")).toContainText(
    "2 celdas sin guardar",
  );
  await expect(cell(page, 0, "sender")).not.toHaveClass(/dirty-cell/);
  await expect(cell(page, 1, "sender")).toHaveText("Proveedor B");
  await page.getByRole("button", { name: "Guardar cambios" }).click();
  await expect(page.locator(".save-state")).toContainText(
    "1 celdas sin guardar",
  );
  expect(
    requests.filter(
      (r) => r.method === "PATCH" && r.path.endsWith("shipment-1"),
    ),
  ).toHaveLength(1);
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Recargar fila" }).click();
  await expect(cell(page, 1, "sender")).toHaveText("Suministros Norte");
  await expect(page.locator(".save-state")).toContainText(
    "Sin cambios pendientes",
  );
});

test("unconfirmed network writes are retained and not submitted twice", async ({
  page,
}) => {
  const requests = await mock(page, { networkFailure: true });
  await pasteCells(page, 0, "origin", "Saltillo");
  await page.getByRole("button", { name: "Guardar cambios" }).click();
  await expect(page.getByRole("alert")).toContainText("sin confirmar");
  await page.getByRole("button", { name: "Guardar cambios" }).click();
  expect(requests.filter((r) => r.method === "PATCH")).toHaveLength(1);
  await expect(cell(page, 0, "origin")).toHaveText("Saltillo");
  await expect(
    page.getByRole("button", { name: "Recargar fila" }),
  ).toBeVisible();
});

test("pending edits survive a canceled master switch, refresh and page change", async ({
  page,
}) => {
  await mock(page, { role: "SUPER_ADMIN", count: 55, mixed: true });
  await pasteCells(page, 0, "origin", "Cambio pendiente");
  page.on("dialog", (dialog) => dialog.dismiss());
  await page.getByRole("button", { name: "Página siguiente" }).click();
  await expect(cell(page, 0, "origin")).toHaveText("Cambio pendiente");
  await page.getByRole("button", { name: "Actualizar", exact: true }).click();
  await expect(cell(page, 0, "origin")).toHaveText("Cambio pendiente");
  await page
    .getByLabel("Responsable del master", { exact: true })
    .selectOption("owner-2");
  await expect(
    page.getByLabel("Responsable del master", { exact: true }),
  ).toHaveValue("owner-1");
  await expect(cell(page, 0, "origin")).toHaveText("Cambio pendiente");
});

test("read-only roles cannot stage or submit spreadsheet changes", async ({
  page,
}) => {
  const requests = await mock(page, { role: "MANAGER" });
  await cell(page, 0, "origin").dblclick();
  await expect(page.locator(".cell-input")).toHaveCount(0);
  await page.keyboard.type("Escritura no permitida");
  await expect(page.locator(".cell-input")).toHaveCount(0);
  await pasteCells(page, 0, "origin", "Cambio no permitido");
  await page.keyboard.press("Delete");
  await expect(cell(page, 0, "origin")).toHaveText("Shanghái, CN");
  await expect(
    page.getByRole("button", { name: "Guardar cambios" }),
  ).toHaveCount(0);
  expect(requests.filter((r) => r.method === "PATCH")).toHaveLength(0);
});

test("CSV exports the displayed page and neutralizes spreadsheet formulas", async ({
  page,
}) => {
  await mock(page);
  await pasteCells(page, 0, "sender", '=HYPERLINK("https://example.com")');
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "Exportar página CSV" }).click();
  const download = await downloadPromise;
  const stream = await download.createReadStream();
  let csv = "";
  for await (const chunk of stream!) csv += chunk.toString();
  expect(download.suggestedFilename()).toBe("master-Analista de prueba-pagina-1.csv");
  expect(csv).toContain("'" + '=HYPERLINK(""https://example.com"")');
  expect(csv).toContain("Referencia,Estado,BU,Tipo de operación,Empresa,Fecha de embarque");
  expect(csv.split("\r\n")).toHaveLength(9);
});

test("cell actions support touch editing, Escape and save without leaving the editor", async ({
  page,
}) => {
  const requests = await mock(page);
  await cell(page, 0, "status").click();
  await page.keyboard.press("ArrowLeft");
  await page.keyboard.press("ArrowLeft");
  await expect(cell(page, 0, "reference_raw")).toBeFocused();
  await cell(page, 0, "sender").click();
  await page.getByRole("button", { name: "Editar celda" }).click();
  await page
    .getByLabel("Editar Remitente / Proveedor", { exact: true })
    .fill("Descartar esta edición");
  await page.keyboard.press("Escape");
  await expect(cell(page, 0, "sender")).toHaveText("Componentes Delta");
  await page.getByRole("button", { name: "Editar celda" }).click();
  await page
    .getByLabel("Editar Remitente / Proveedor", { exact: true })
    .fill("Proveedor final");
  await page.keyboard.press("Control+s");
  await expect(page.locator(".save-state")).toContainText(
    "Sin cambios pendientes",
  );
  await expect
    .poll(() => requests.filter((r) => r.method === "PATCH").length)
    .toBe(1);
  await expect(cell(page, 0, "sender")).toHaveText("Proveedor final");
});

test("rapid arrow navigation scrolls within the grid and clears frozen headers", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 768 });
  await mock(page, { count: 60, collapsed: true });
  const sheet = page.locator(".sheet-scroll");
  const size = await sheet.boundingBox();
  expect(size!.height).toBeGreaterThan(340);
  await cell(page, 0, "status").click();
  for (let i = 0; i < 45; i++) await page.keyboard.down("ArrowDown");
  await page.keyboard.up("ArrowDown");
  await expect(cell(page, 45, "status")).toBeFocused();
  await page.keyboard.press("End");
  await expect(cell(page, 45, "comments")).toBeFocused();
  const visible = await cell(page, 45, "comments").evaluate(element => {
    const viewport = element.closest(".sheet-scroll")!;
    const box = viewport.getBoundingClientRect(), cell = element.getBoundingClientRect();
    return cell.left >= viewport.querySelector("tbody .frozen")!.getBoundingClientRect().right &&
      cell.right <= box.left + viewport.clientWidth + 1 && cell.top >= box.top + 60 &&
      cell.bottom <= box.top + viewport.clientHeight + 1;
  });
  expect(visible).toBeTruthy();
  expect(await page.evaluate(() => window.scrollY)).toBe(0);
  await page.keyboard.press("Home");
  await page.keyboard.press("ArrowRight");
  await expect(cell(page, 45, "status")).toBeFocused();
  const left = await cell(page, 45, "status").boundingBox();
  const frozen = await cell(page, 45, "reference_raw").boundingBox();
  expect(left!.x).toBeGreaterThanOrEqual(frozen!.x + frozen!.width - 1);
  await page.keyboard.press("Control+Home");
  await expect(cell(page, 0, "reference_raw")).toBeFocused();
  await page.screenshot({ path: "test-results/master-large.png", fullPage: true });
});

test("zoom and expanded layout retain pending edits and keep keyboard navigation usable", async ({ page }) => {
  await mock(page, { collapsed: true });
  await pasteCells(page, 0, "origin", "Edición conservada");
  await page.getByLabel("Tamaño del master").selectOption("130");
  await expect(cell(page, 0, "origin")).toBeFocused();
  expect(await cell(page, 0, "origin").evaluate(e => parseFloat(getComputedStyle(e).fontSize))).toBeGreaterThan(18);
  await page.getByRole("button", { name: "Ampliar master", exact: true }).click();
  await expect(cell(page, 0, "origin")).toHaveText("Edición conservada");
  await cell(page, 0, "origin").click();
  await page.keyboard.press("PageDown");
  await expect(cell(page, 7, "origin")).toBeFocused();
  await page.keyboard.press("PageUp");
  await expect(cell(page, 0, "origin")).toBeFocused();
  await page.screenshot({ path: "test-results/master-zoom.png", fullPage: true });
});

test("master explains server permissions instead of enabling editing from the displayed role", async ({ page }) => {
  const requests = await mock(page, { accessDenied: true, collapsed: true });
  await expect(page.locator(".sheet-access-reason")).toContainText("no está habilitada");
  await cell(page, 0, "sender").dblclick();
  await expect(page.locator(".cell-input")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Guardar cambios" })).toHaveCount(0);
  expect(requests.filter(r => r.method === "PATCH")).toHaveLength(0);
});

test("wide cells at mobile zoom do not oscillate at the navigation boundary", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mock(page, { collapsed: true });
  await page.getByLabel("Tamaño del master").selectOption("130");
  await cell(page, 0, "status").click();
  await page.keyboard.press("End");
  await expect(cell(page, 0, "comments")).toBeFocused();
  const left = await page.locator(".sheet-scroll").evaluate(e => e.scrollLeft);
  for (let i = 0; i < 5; i++) await page.keyboard.press("ArrowRight");
  await expect(cell(page, 0, "comments")).toBeFocused();
  await expect.poll(() => page.locator(".sheet-scroll").evaluate(e => e.scrollLeft)).toBe(left);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
});

test("reference detail is accessible from the keyboard without trapping arrow navigation", async ({ page }) => {
  await mock(page, { collapsed: true });
  await cell(page, 0, "status").click();
  await page.keyboard.press("ArrowLeft");
  await expect(cell(page, 0, "reference_raw")).toBeFocused();
  await page.keyboard.press("ArrowRight");
  await expect(cell(page, 0, "status")).toBeFocused();
  await page.keyboard.press("Home");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("dialog")).toBeVisible();
  await expect(page.getByRole("dialog").getByLabel("Comentarios", { exact: true })).toBeEnabled();
});
