import { inject, Injectable } from "@angular/core";
import { AuthService } from "./auth.service";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public requestId: string | null = null,
  ) {
    super(message);
  }
}
@Injectable({ providedIn: "root" })
export class ApiService {
  private auth = inject(AuthService);
  async request<T>(
    path: string,
    method = "GET",
    body?: unknown,
    signal?: AbortSignal,
    responseType: "json" | "blob" = "json",
  ): Promise<T> {
    if (!path.startsWith("/") || path.startsWith("//"))
      throw new Error("Ruta no válida.");
    const token = await this.auth.token();
    let response: Response;
    try {
      response = await fetch("/api/v1" + path, {
        method,
        signal,
        cache: "no-store",
        headers: {
          Authorization: `Bearer ${token}`,
          ...(body === undefined ? {} : { "Content-Type": "application/json" }),
        },
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      });
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError")
        throw error;
      throw new ApiError(
        0,
        "No hay conexión con el servidor. Comprueba tu conexión antes de reintentar.",
      );
    }
    if (!response.ok) {
      const data = (await response.json().catch(() => ({}))) as {
        detail?: string | { loc: string[]; msg: string }[];
      };
      const messages: Record<number, string> = {
        401: "Tu sesión ya no es válida. Vuelve a iniciar sesión.",
        403: "Tu usuario no está habilitado o no tiene permiso para esta acción.",
        404: "El registro no está disponible para tu usuario.",
        409: "El registro cambió o existe un conflicto. Recarga los datos antes de continuar.",
        503: "El servicio no está disponible. Consulta al administrador y reintenta más tarde.",
      };
      let message =
        messages[response.status] ?? "No se pudo completar la operación.";
      if (response.status === 422)
        message = Array.isArray(data.detail)
          ? "Revisa estos campos: " +
            data.detail
              .map((item) => item.loc.filter((p) => p !== "body").join("."))
              .join(", ")
          : "Los datos no cumplen las reglas de captura. Revisa los campos y los catálogos.";
      if (
        path.startsWith("/finance/") &&
        [409, 422].includes(response.status) &&
        typeof data.detail === "string"
      )
        message = data.detail;
      throw new ApiError(
        response.status,
        message,
        response.headers.get("X-Request-ID"),
      );
    }
    return (
      responseType === "blob" ? response.blob() : response.json()
    ) as Promise<T>;
  }
}
