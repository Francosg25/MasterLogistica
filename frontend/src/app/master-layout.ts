import { Catalogs, MasterData, MasterLayout, Owner, Shipment, ShipmentValues } from "./types";

export function ownerLayout(catalog: Catalogs | null, owner: Owner | undefined): MasterLayout | null {
  const codes: Record<number, string> = { 1: "MAG", 2: "ALEXA", 3: "DENI", 4: "ANDREA", 5: "NAT" };
  const code = owner?.layout_code || codes[owner?.analyst_code ?? 0];
  return catalog?.master_layouts?.[code] ?? null;
}

export function masterValue(row: Shipment, key: string, owner = ""): string {
  if (!key.startsWith("master.")) return String(row[key as keyof Shipment] ?? "");
  const name = key.slice(7), data = row.master_data ?? {};
  if (Object.hasOwn(data, name)) return data[name] ?? "";
  const date = row.ship_date && /^\d{4}-\d{2}-\d{2}$/.test(row.ship_date) ? row.ship_date : "";
  const defaults: Record<string, string> = {
    sec: String(row.reference_sequence ?? ""), owner,
    day: date ? String(Number(date.slice(8, 10))) : "",
    month: date ? String(Number(date.slice(5, 7))) : "",
    year: date.slice(0, 4), io: row.direction ?? "",
    damaged_material: row.damaged_material === true ? "Sí" : row.damaged_material === false ? "No" : "",
    ocean_bl: data["transport_document"] ?? "",
    pfa_number: row.pfa_approval_code ?? "",
  };
  if (name === "week" && date) {
    const current = new Date(date + "T00:00:00Z"), first = new Date(Date.UTC(current.getUTCFullYear(), 0, 1));
    // Excel WEEKNUM's Sunday-based convention. A manually captured value wins.
    return String(Math.floor(((current.getTime() - first.getTime()) / 86400000 + first.getUTCDay()) / 7) + 1);
  }
  return defaults[name] ?? "";
}

export function shipmentValues(draft: Record<string, string | null>): ShipmentValues {
  const values: ShipmentValues = {}, master: MasterData = {};
  for (const [key, value] of Object.entries(draft)) {
    if (key.startsWith("master.")) master[key.slice(7)] = value;
    else values[key] = value;
  }
  if (Object.keys(master).length) values["master_data"] = master;
  return values;
}
