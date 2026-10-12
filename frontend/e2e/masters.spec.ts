import { expect, test, Page } from "@playwright/test";
import { demoCatalogs, demoShipments } from "../src/app/demo";

async function mock(
  page: Page,
  options: {
    role?: string;
    empty?: boolean;
    failure?: boolean;
    conflict?: boolean;
    count?: number;
  } = {},
) {
  let rows = options.empty
    ? []
    : Array.from({ length: options.count ?? 8 }, (_, i) => ({
        ...demoShipments[i % 8],
        id: `shipment-${i}`,
        owner_id: "owner-1",
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
    if (path === "/references/catalogs") return json(demoCatalogs);
    if (path === "/masters/owners")
      return json([{ id: "owner-1", display_name: "Analista de prueba" }]);
    if (path === "/suppliers")
      return json({ items: [], total: 0, limit: 100, offset: 0 });
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
        reference_raw: "RM1-0009LI26-T01-MAT",
      };
      rows = [row, ...rows];
      return json(row, 201);
    }
    if (path.startsWith("/shipments/") && path !== "/shipments/summary") {
      const id = path.split("/").pop(),
        row = rows.find((row) => row.id === id);
      if (req.method() === "PATCH") {
        if (options.conflict) return json({ detail: "Record changed" }, 409);
        const updated = { ...row, ...body, row_version: 2 };
        rows = rows.map((r) => (r.id === id ? updated : r));
        return json(updated);
      }
      return row ? json(row) : json({ detail: "Not found" }, 404);
    }
    if (path === "/shipments" || path === "/shipments/summary") {
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
  await expect(
    page.getByRole("heading", { name: "Masters de logística." }),
  ).toBeVisible();
  return requests;
}

test("lists scoped data and applies operation filters to list and totals", async ({
  page,
}) => {
  await mock(page);
  await expect(page.locator("tbody tr")).toHaveCount(8);
  await page.getByLabel("Operación", { exact: true }).selectOption("R1");
  await page.getByRole("button", { name: "Aplicar", exact: true }).click();
  await expect(page.locator("tbody tr")).toHaveCount(1);
  await expect(page.locator(".metric").first().locator("strong")).toHaveText(
    "1",
  );
  await page
    .getByRole("button", { name: "Limpiar filtros", exact: true })
    .click();
  await expect(page.locator("tbody tr")).toHaveCount(8);
  const views = page.getByRole("navigation", { name: "Vistas de embarques" });
  await views.getByRole("button", { name: "En tránsito", exact: true }).click();
  await expect(page.locator("tbody tr")).toHaveCount(2);
  await expect(
    views.getByRole("button", { name: "En tránsito", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  await views.getByRole("button", { name: "Todas", exact: true }).click();
  await expect(page.locator("tbody tr")).toHaveCount(8);
});
test("creates on server, never sends owner/reference, then attaches a pedimento", async ({
  page,
}) => {
  const requests = await mock(page);
  await page.getByRole("button", { name: "Nuevo embarque" }).click();
  const dialog = page.getByRole("dialog");
  await dialog
    .getByRole("button", { name: "Crear embarque", exact: true })
    .click();
  await expect(dialog.getByRole("alert")).toContainText("Completa");
  await dialog
    .getByLabel("Business unit *", { exact: true })
    .selectOption("T01");
  await dialog
    .getByRole("button", { name: "Crear embarque", exact: true })
    .click();
  await expect(
    dialog.getByRole("heading", { name: "RM1-0009LI26-T01-MAT" }),
  ).toBeVisible();
  const creation = requests.find(
    (r) => r.path === "/shipments" && r.method === "POST",
  )!;
  expect(creation.body).not.toHaveProperty("owner_id");
  expect(creation.body).not.toHaveProperty("reference_raw");
  expect(creation.body?.["business_unit"]).toBe("T01");
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
test("sea-specific form and compliance operation are available", async ({
  page,
}) => {
  await mock(page);
  await page.getByRole("button", { name: "Nuevo embarque" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Tipo de operación *").selectOption("SI");
  await expect(dialog.getByLabel("Naviera", { exact: true })).toBeVisible();
  await dialog.getByLabel("Tipo de operación *").selectOption("R1");
  await expect(dialog.getByLabel("Naviera", { exact: true })).toHaveCount(0);
  await expect(
    dialog.getByRole("heading", { name: "Seguimiento de la operación" }),
  ).toBeVisible();
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
test("manager can inspect but cannot create or edit", async ({ page }) => {
  await mock(page, { role: "MANAGER" });
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
test("pagination retains filters", async ({ page }) => {
  await mock(page, { count: 25 });
  await expect(page.locator("tbody tr")).toHaveCount(20);
  await page.getByRole("button", { name: "Página siguiente" }).click();
  await expect(page.locator("tbody tr")).toHaveCount(5);
  await expect(page.locator(".table-footer")).toContainText("21–25 de 25");
  await page.getByRole("button", { name: "Página anterior" }).click();
  await expect(page.locator("tbody tr")).toHaveCount(20);
});
test("database errors do not masquerade as empty success", async ({ page }) => {
  await mock(page, { failure: true });
  await expect(page.getByRole("alert")).toContainText(
    "servicio no está disponible",
  );
  await expect(page.getByText("No hay embarques para mostrar")).toHaveCount(0);
  await expect(page.locator(".metric").first().locator("strong")).toHaveText(
    "—",
  );
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
  await expect(page.locator("tbody tr").first()).toContainText("01 oct 2026");
  await page.screenshot({
    path: "test-results/masters-desktop.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
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
