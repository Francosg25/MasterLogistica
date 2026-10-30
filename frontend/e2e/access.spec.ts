import { expect, test } from "@playwright/test";

test("production build uses real access flow and offers an isolated read-only preview", async ({
  page,
}) => {
  const apiCalls: string[] = [];
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/api/v1/**", (route) => {
    apiCalls.push(route.request().url());
    if (route.request().url().endsWith("/auth/config"))
      return route.fulfill({
        json: {
          enabled: false,
          authority: null,
          frontend_client_id: null,
          scope: null,
        },
      });
    return route.fulfill({ status: 401, json: { detail: "Unauthorized" } });
  });
  await page.goto("http://127.0.0.1:4301/");
  await expect(
    page.getByRole("heading", { name: "Acceso al sistema" }),
  ).toBeVisible();
  await expect(
    page.getByText("El acceso corporativo aún no está disponible.", {
      exact: false,
    }),
  ).toBeVisible();
  await page.screenshot({
    path: "test-results/login-desktop.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "Ver demostración" }).click();
  await expect(page.locator(".demo-banner")).toBeVisible();
  await expect(page.locator(".account-name")).toContainText("Usuario de pruebas");
  await expect(page.locator(".user-avatar")).toHaveText("UP");
  await expect(page.locator(".masters-panel tbody tr")).toHaveCount(0);
  await page.getByRole("navigation", { name: "Secciones" }).getByRole("button", { name: "Referencias", exact: true }).click();
  await page
    .getByLabel("Responsable del master", { exact: true })
    .selectOption("demo-owner-1");
  await expect(page.locator("tbody tr")).toHaveCount(8);
  await expect(page.locator("tbody tr").first()).toContainText("01/10/2026");
  await expect(
    page.getByRole("button", { name: "Nuevo embarque" }),
  ).toHaveCount(0);
  await page.screenshot({ path: "test-results/preview.png", fullPage: true });
  await page.locator(".reference-link").first().click();
  await expect(
    page.getByRole("dialog").getByLabel("Comentarios", { exact: true }),
  ).toBeDisabled();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Cerrar", exact: true })
    .click();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.locator(".demo-banner")).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBeTruthy();
  await page.getByRole("button", { name: "Salir de demo" }).click();
  await expect(
    page.getByRole("button", { name: "Ver demostración" }),
  ).toBeVisible();
  expect(apiCalls).toHaveLength(1);
  expect(errors).toEqual([]);
});

test("practice edits persist only in the browser, survive reopening and can be reset", async ({ page }) => {
  const apiCalls: string[] = [];
  await page.route("**/api/v1/**", route => {
    apiCalls.push(route.request().method() + " " + route.request().url());
    return route.fulfill({ json: { enabled: false, authority: null, frontend_client_id: null, scope: null } });
  });
  await page.goto("http://127.0.0.1:4301/");
  await page.getByRole("button", { name: "Practicar con el master", exact: true }).click();
  await expect(page.locator(".demo-banner")).toContainText("Guardado en este navegador");
  const origin = page.locator('td[data-row="0"][data-field="origin"]');
  await expect(page.locator("tbody tr")).toHaveCount(50);
  await origin.dblclick();
  await page.getByLabel("Editar Origin", { exact: true }).fill("Origen ficticio modificado");
  await page.getByLabel("Editar Origin", { exact: true }).press("Enter");
  for (const [field, value] of [["reference_raw", "REFERENCIA DE PRACTICA"], ["company_code", "MXT"], ["business_unit", "M46"], ["operation_code", "R1"]]) {
    await page.locator(`td[data-row="0"][data-field="${field}"]`).click();
    if (field === "reference_raw") await page.keyboard.type(value);
    else {
      await page.keyboard.press("F2");
      await page.locator(".cell-input").selectOption(value);
    }
    await page.keyboard.press("Enter");
  }
  await page.getByRole("button", { name: "Guardar cambios", exact: false }).click();
  await expect(page.locator(".sheet-message")).toContainText("en este navegador");
  await page.reload();
  await page.getByRole("button", { name: "Practicar con el master", exact: true }).click();
  await expect(origin).toHaveText("Origen ficticio modificado");
  await expect(page.locator('td[data-row="0"][data-field="reference_raw"] .cell-text')).toHaveText("REFERENCIA DE PRACTICA");
  await expect(page.locator('td[data-row="0"][data-field="company_code"]')).toHaveText("MXT");
  await expect(page.locator('td[data-row="0"][data-field="business_unit"]')).toHaveText("M46");
  await expect(page.locator('td[data-row="0"][data-field="operation_code"]')).toHaveText("Rectificación de pedimento");
  await page.getByRole("button", { name: "Mostrar filtros", exact: true }).click();
  await page.getByRole("button", { name: "Actualizar", exact: true }).click();
  await expect(origin).toHaveText("Origen ficticio modificado");
  await page.getByRole("button", { name: "Ampliar master", exact: true }).click();
  await expect(page.locator(".practice-label")).toBeVisible();
  await page.screenshot({ path: "test-results/practice-master.png", fullPage: true });
  await page.getByRole("button", { name: "Salir de vista ampliada", exact: true }).click();
  page.once("dialog", dialog => dialog.accept());
  await page.getByRole("button", { name: "Restablecer práctica", exact: true }).click();
  await expect(origin).toHaveText("Shanghái, CN");
  expect(apiCalls.every(call => call.startsWith("GET ") && call.endsWith("/auth/config"))).toBeTruthy();
  await page.getByRole("button", { name: "Salir de demo", exact: true }).click();
  await page.getByRole("button", { name: "Ver demostración", exact: true }).click();
  await expect(page.locator(".demo-banner")).toContainText("Solo lectura");
});

test("practice retains unsaved cells when browser storage cannot confirm the write", async ({ page }) => {
  await page.route("**/api/v1/**", route => route.fulfill({ json: { enabled: false } }));
  await page.goto("http://127.0.0.1:4301/");
  await page.getByRole("button", { name: "Practicar con el master", exact: true }).click();
  await page.locator('td[data-row="0"][data-field="origin"]').dblclick();
  await page.getByLabel("Editar Origin", { exact: true }).fill("Conservar este cambio");
  await page.getByLabel("Editar Origin", { exact: true }).press("Enter");
  await page.evaluate(() => {
    const setItem = Storage.prototype.setItem;
    Storage.prototype.setItem = function(key, value) {
      if (key === "masterlogistica.master-practice.v1") throw new DOMException("Storage full", "QuotaExceededError");
      return setItem.call(this, key, value);
    };
  });
  await page.getByRole("button", { name: "Guardar cambios", exact: false }).click();
  await expect(page.getByRole("alert")).toContainText("No se pudo guardar en este navegador");
  await expect(page.locator(".save-state")).toContainText("1 celdas sin guardar");
  await expect(page.locator('td[data-row="0"][data-field="origin"]')).toHaveText("Conservar este cambio");
});

test("corrupted practice reports the problem and can recover without touching the API", async ({ page }) => {
  await page.route("**/api/v1/**", route => route.fulfill({ json: { enabled: false } }));
  await page.goto("http://127.0.0.1:4301/");
  await page.evaluate(() => localStorage.setItem("masterlogistica.master-practice.v1", "invalid stored data"));
  await page.getByRole("button", { name: "Practicar con el master", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("No se pudo leer la práctica guardada");
  page.once("dialog", dialog => dialog.accept());
  await page.getByRole("button", { name: "Restablecer práctica", exact: true }).click();
  await expect(page.locator("tbody tr")).toHaveCount(50);
  await expect(page.getByRole("button", { name: "Guardar cambios", exact: false })).toBeDisabled();
});
