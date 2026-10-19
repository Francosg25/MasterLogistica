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
  await expect(page.locator("tbody tr")).toHaveCount(0);
  await page.getByRole("navigation", { name: "Secciones" }).getByRole("button", { name: "Masters", exact: true }).click();
  await page
    .getByLabel("Tipo de operación del master", { exact: true })
    .selectOption("SI");
  await page.getByRole("button", { name: "Abrir master", exact: true }).click();
  await expect(page.locator("tbody tr")).toHaveCount(5);
  await expect(page.locator("tbody tr").first()).toContainText("01/10/2026");
  await expect(
    page.getByRole("button", { name: "Nuevo embarque" }),
  ).toHaveCount(0);
  await page.screenshot({ path: "test-results/preview.png", fullPage: true });
  await page.locator(".reference-link").first().click();
  await expect(
    page.getByRole("dialog").getByLabel("Comentarios"),
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
