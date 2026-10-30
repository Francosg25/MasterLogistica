import { Injectable } from "@angular/core";
import { BUSINESS_UNITS, MasterData, MasterLayout, Shipment, ShipmentValues } from "./types";

type Patch = ShipmentValues;
interface PracticeStore {
  version: 1;
  rows: Record<string, { version: number; patch: Patch }>;
}

// A separate, fictional workbook. No token, API request or operational record is used here.
@Injectable({ providedIn: "root" })
export class MasterPracticeService {
  private readonly storageKey = "masterlogistica.master-practice.v1";
  private seed: Shipment[] = [];
  private saved: PracticeStore = { version: 1, rows: {} };
  private extraFields = new Map<string, { max?: number; kind: string }>();
  private readonly limits: Record<string, number> = {
    reference_raw: 160, company_code: 32, business_unit: 3, operation_code: 100,
    status: 100, ship_date: 10, eta: 10, delivery_date: 10,
    sender: 250, origin: 150, consignee: 250, destination: 150,
    plant_code: 32, carrier_broker_id: 64, shipping_line_id: 64, carrier_broker_name: 250, shipping_line_name: 250, comments: 10000,
  };

  configure(layouts: Record<string, MasterLayout>): void {
    this.extraFields = new Map(Object.values(layouts).flatMap(layout => layout.fields
      .filter(field => field.key.startsWith("master."))
      .map(field => [field.key.slice(7), field] as const)));
  }

  start(examples: Shipment[]): Shipment[] {
    this.seed = examples.flatMap((row, index) =>
      Array.from({ length: 12 }, (_, copy) => ({
        ...row,
        reference_sequence: copy * 8 + index % 8 + 1,
        id: `practice-${row.id}-${copy}`,
        reference_raw: row.reference_raw!.replace(/-\d{4}/, `-${String(copy * 8 + index % 8 + 1).padStart(4, "0")}`),
        comments: "Ejemplo de práctica. Los cambios se guardan solo en este navegador.",
      })),
    );
    this.saved = this.load();
    return this.rows;
  }

  get rows(): Shipment[] {
    return this.seed.map(row => ({
      ...row,
      ...this.saved.rows[row.id]?.patch,
      master_data: { ...row.master_data, ...this.saved.rows[row.id]?.patch["master_data"] as MasterData | undefined },
      row_version: this.saved.rows[row.id]?.version ?? 1,
    }));
  }

  private validate(patch: Patch): void {
    for (const [key, value] of Object.entries(patch)) {
      if (key === "master_data") {
        if (!value || typeof value !== "object" || Array.isArray(value) || Object.keys(value).length > 80) throw new Error("Los datos del master no son válidos.");
        for (const [name, text] of Object.entries(value)) {
          const field = this.extraFields.get(name);
          if (!field || (text !== null && (typeof text !== "string" || text.length > (field.max ?? 10000)))) throw new Error("La práctica contiene un campo o valor no válido.");
          if (field.kind === "date") this.validateDate(text);
        }
        continue;
      }
      if (!Object.hasOwn(this.limits, key) ||
          (value !== null && (typeof value !== "string" || value.length > this.limits[key])))
        throw new Error("La práctica contiene un campo o valor no válido.");
      if (key === "status" && value === null) throw new Error("El estado vacío se guarda como texto vacío.");
      if (key === "company_code" && !value?.trim()) throw new Error("Captura la empresa.");
      if (key === "business_unit" && value && !Object.hasOwn(BUSINESS_UNITS, value))
        throw new Error("Selecciona una BU del catálogo.");
      if (["ship_date", "eta", "delivery_date"].includes(key)) this.validateDate(value as string | null);
    }
  }
  private validateDate(value: string | null): void {
    if (!value) return;
    const date = new Date(`${value}T00:00:00Z`);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value) || Number.isNaN(date.getTime()) || date.toISOString().slice(0, 10) !== value)
      throw new Error("La práctica contiene una fecha no válida.");
  }

  private load(): PracticeStore {
    let text: string | null;
    try { text = localStorage.getItem(this.storageKey); }
    catch { throw new Error("El navegador no permite guardar la práctica. Habilita el almacenamiento de este sitio para utilizarla."); }
    if (!text) return { version: 1, rows: {} };
    try {
      if (text.length > 3000000) throw new Error();
      const store = JSON.parse(text) as PracticeStore;
      if (store.version !== 1 || !store.rows || typeof store.rows !== "object" || Array.isArray(store.rows)) throw new Error();
      const ids = new Set(this.seed.map(row => row.id));
      for (const [id, row] of Object.entries(store.rows)) {
        if (!ids.has(id) || !row || !Number.isSafeInteger(row.version) || row.version < 2 ||
            !row.patch || typeof row.patch !== "object" || Array.isArray(row.patch)) throw new Error();
        this.validate(row.patch);
      }
      return store;
    } catch { throw new Error("No se pudo leer la práctica guardada. Usa Restablecer práctica para volver a los ejemplos."); }
  }

  save(original: Shipment, patch: Patch): Shipment {
    const base = this.seed.find(row => row.id === original.id);
    if (!base) throw new Error("La fila no pertenece al libro de práctica.");
    this.validate(patch);
    const latest = this.load();
    const version = latest.rows[base.id]?.version ?? 1;
    if (version !== original.row_version)
      throw new Error("Esta práctica cambió en otra pestaña. Actualiza el master antes de guardar.");
    const merged = { ...latest.rows[base.id]?.patch, ...patch };
    if (patch["master_data"]) merged["master_data"] = {
      ...latest.rows[base.id]?.patch["master_data"] as MasterData | undefined, ...patch["master_data"] as MasterData,
    };
    latest.rows[base.id] = { version: version + 1, patch: merged };
    const content = JSON.stringify(latest);
    if (content.length > 3000000)
      throw new Error("La práctica alcanzó su límite de almacenamiento. Exporta los ejemplos que quieras conservar antes de restablecerla.");
    try { localStorage.setItem(this.storageKey, content); }
    catch { throw new Error("No se pudo guardar en este navegador. Conserva tus cambios y libera espacio antes de reintentar."); }
    this.saved = latest;
    return { ...base, ...merged, master_data: { ...base.master_data, ...merged["master_data"] as MasterData | undefined }, row_version: version + 1 } as Shipment;
  }

  refresh(): Shipment[] {
    this.saved = this.load();
    return this.rows;
  }

  reset(): Shipment[] {
    try { localStorage.removeItem(this.storageKey); }
    catch { throw new Error("No se pudo restablecer la práctica en este navegador."); }
    this.saved = { version: 1, rows: {} };
    return this.rows;
  }
}
