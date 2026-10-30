export type Role = "OPERATOR" | "FINANCE" | "MANAGER" | "SUPER_ADMIN";
export interface User {
  id: string;
  display_name: string;
  email: string;
  role: Role;
  analyst_code: number | null;
}
export interface AuthConfig {
  auth_mode?: "development" | "entra";
  storage?: "sqlite";
  enabled: boolean;
  authority: string | null;
  frontend_client_id: string | null;
  scope: string | null;
}
export interface Catalogs {
  master_layouts?: Record<string, MasterLayout>;
  master_access?: {
    can_edit: boolean;
    can_create: boolean;
    edit_scope: "ALL" | "OWN" | "NONE";
    read_only_reason: string | null;
  };
  version: string;
  process_codes: string[];
  operation_codes: string[];
  shipment_statuses?: string[];
  department_codes: string[];
  business_units: Record<string, string>;
  business_units_configured: boolean;
  company_codes: string[];
}
export interface Supplier {
  id: string;
  code: string;
  legal_name: string;
  is_active: boolean;
}
export interface Owner {
  layout_code?: string | null;
  analyst_code: number | null;
  id: string;
  display_name: string;
}
export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}
export interface Summary {
  total: number;
  by_status: Record<string, number>;
}
export interface Identifier {
  id: string;
  kind: string;
  raw_value: string;
  normalized_value: string;
}
export interface Shipment {
  parent_shipment_id?: string | null;
  movement_number?: number | null;
  master_data?: Record<string, string | null>;
  reference_sequence?: number | null;
  direction?: string;
  id: string;
  row_version: number;
  owner_id: string;
  reference_raw: string | null;
  company_code: string;
  process_code: string | null;
  operation_code: string | null;
  reference_year: number | null;
  business_unit: string | null;
  department_code: string | null;
  status: string;
  ship_date: string | null;
  eta: string | null;
  delivery_date: string | null;
  sender: string | null;
  origin: string | null;
  consignee: string | null;
  destination: string | null;
  carrier_broker_id: string | null;
  carrier_broker_name?: string | null;
  shipping_line_id: string | null;
  shipping_line_name?: string | null;
  plant_code: string | null;
  comments: string | null;
  damaged_material: boolean | null;
  expedited_status: string;
  pfa_approval_code: string | null;
}
export interface MasterField {
  key: string;
  label: string;
  source_column?: string;
  kind: "text" | "date" | "status" | "supplier" | "unit" | "operation" | "choice" | "sequence";
  options?: { value: string; label: string }[];
  max?: number;
  width: number;
  section?: string;
  required?: boolean;
}
export interface MasterLayout { code: string; label: string; fields: MasterField[]; }
export type MasterData = Record<string, string | null>;
export type ShipmentValues = Record<string, string | null | MasterData>;
export const STATUS: Record<string, string> = Object.assign(Object.create(null), {
  DRAFT: "Borrador",
  PLANNED: "Programado",
  IN_TRANSIT: "En tránsito",
  AT_PORT: "En puerto",
  CUSTOMS: "En aduana",
  DELIVERED: "Entregado",
  CANCELLED: "Cancelado",
});
export const OPERATIONS: Record<string, string> = Object.assign(Object.create(null), {
  AI: "Aéreo · Importación",
  AE: "Aéreo · Exportación",
  SI: "Marítimo · Importación",
  SE: "Marítimo · Exportación",
  LI: "Terrestre · Importación",
  LE: "Terrestre · Exportación",
  PI: "Paquetería · Importación",
  PE: "Paquetería · Exportación",
  VI: "Virtual · Importación",
  VE: "Virtual · Exportación",
  A3: "Regularización",
  F4: "Cambio por CTM / Scrap",
  F5: "Cambio de régimen · Maquinaria",
  R1: "Rectificación de pedimento",
});
export const PROCESSES: Record<string, string> = {
  RM: "Materia prima",
  AF: "Activo fijo",
  FG: "Producto terminado",
  CR: "Cambio de régimen",
  FA: "Fracción arancelaria",
};
export const DEPARTMENTS: Record<string, string> = {
  PRJ: "Proyectos",
  MAT: "Materiales",
  QUA: "Calidad",
  MAI: "Mantenimiento",
  HUM: "Recursos humanos",
  FIX: "Activo fijo",
  RAW: "Materia prima",
  CTM: "Transferencia",
  SCR: "Scrap",
};

// Preserve historical labels on read; new capture uses the operation catalog.
export const EXCEL_OPERATION_LABELS = ["LAND IMPO", "LAND EXPO", "AIR IMPO", "AIR EXPO", "SEA IMPO", "SEA EXPO"];
export function masterOperationValue(value: string): string {
  const text = value.trim();
  const excelCodes: Record<string, string> = { LANDIMPO: "LI", LANDEXPO: "LE", AIRIMPO: "AI", AIREXPO: "AE", SEAIMPO: "SI", SEAEXPO: "SE" };
  const excel = excelCodes[text.replace(/\s+/g, "").toUpperCase()];
  if (excel) return excel;
  return Object.keys(OPERATIONS).find(code => code.toLowerCase() === text.toLowerCase() || OPERATIONS[code].toLowerCase() === text.toLowerCase()) ?? text;
}
export function masterStatusValue(value: string): string {
  const text = value.trim();
  return Object.keys(STATUS).find(code => code.toLowerCase() === text.toLowerCase() || STATUS[code].toLowerCase() === text.toLowerCase()) ?? text;
}
export function supplierValues(value: string | null, prefix: "carrier_broker" | "shipping_line", suppliers: Supplier[]): Record<string, string | null> {
  const text = (value ?? "").trim();
  const matches = text ? suppliers.filter(s => s.is_active && [s.id, s.code, s.legal_name].some(v => v.toLowerCase() === text.toLowerCase())) : [];
  return matches.length === 1
    ? { [prefix + "_id"]: matches[0].id, [prefix + "_name"]: null }
    : { [prefix + "_id"]: null, [prefix + "_name"]: text || null };
}

export const BUSINESS_UNITS: Record<string,string> = { M00:"Varias BU", M01:"BM", M19:"PC", M20:"BC", M23:"ETM", M45:"IPG", M46:"AS", M65:"IPG" };
