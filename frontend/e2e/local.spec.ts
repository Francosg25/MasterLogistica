import { expect, test } from "@playwright/test";

test("local configuration creates and edits real records without corporate login", async ({ page, browser }) => {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  const authorization: string[] = [];
  page.on("request", request => {
    if (request.url().includes("/api/") && request.headers()["authorization"]) authorization.push(request.headers()["authorization"]);
  });
  await page.goto("/");
  await expect(page.locator(".local-banner")).toContainText("SQLite");
  await expect(page.getByRole("heading", { name: "Acceso al sistema" })).toHaveCount(0);
  await page.getByRole("navigation", { name: "Secciones" }).getByRole("button", { name: "Masters", exact: true }).click();
  await page.getByLabel("Tipo de operación del master", { exact: true }).selectOption("SI");
  await page.getByRole("button", { name: "Abrir master", exact: true }).click();
  await page.getByRole("button", { name: "Nuevo embarque" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Proceso *", { exact: true }).selectOption("RM");
  await dialog.getByLabel("Business unit *", { exact: true }).selectOption("T01");
  await dialog.getByLabel("Departamento *", { exact: true }).selectOption("MAT");
  await dialog.getByLabel("Año de operación *", { exact: true }).fill("2026");
  await dialog.getByRole("button", { name: "Crear embarque", exact: true }).click();
  await expect(dialog.getByRole("heading", { name: "RM1-0001SI26-T01-MAT" })).toBeVisible();
  await dialog.getByLabel("Comentarios").fill("Nota persistente de la API local");
  await dialog.getByRole("button", { name: "Guardar cambios", exact: true }).click();
  await dialog.getByRole("button", { name: "Cerrar detalle", exact: true }).click();
  const origin = page.locator('td[data-row="0"][data-field="origin"]');
  await origin.dblclick();
  await page.getByLabel("Editar Origen", { exact: true }).fill("Origen guardado en SQLite");
  await page.getByLabel("Editar Origen", { exact: true }).press("Enter");
  await page.getByRole("button", { name: "Guardar cambios", exact: false }).click();
  await expect(page.locator(".save-state")).toHaveText("Sin cambios pendientes");
  // A fresh browser context has no localStorage/sessionStorage from the editing context.
  const context = await browser.newContext();
  const reopened = await context.newPage();
  await reopened.goto("http://127.0.0.1:4200/");
  await expect(reopened.locator(".local-banner")).toBeVisible();
  await reopened.getByRole("navigation", { name: "Secciones" }).getByRole("button", { name: "Masters", exact: true }).click();
  await reopened.getByLabel("Tipo de operación del master", { exact: true }).selectOption("SI");
  await reopened.getByRole("button", { name: "Abrir master", exact: true }).click();
  await expect(reopened.locator('td[data-row="0"][data-field="origin"]')).toHaveText("Origen guardado en SQLite");
  await reopened.locator(".reference-link").first().click();
  await expect(reopened.getByRole("dialog").getByLabel("Comentarios")).toHaveValue("Nota persistente de la API local");
  await context.close();
  expect(errors).toEqual([]);
  expect(authorization).toEqual([]);
});
