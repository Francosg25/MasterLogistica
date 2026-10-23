export type Role = "OPERATOR" | "FINANCE" | "MANAGER" | "SUPER_ADMIN";
export interface User {
  id: string;
  display_name: string;
  email: string;
  role: Role;
  analyst_code: number | null;
}
export interface AuthConfig {
  enabled: boolean;
  authority: string | null;
  frontend_client_id: string | null;
  scope: string | null;
}
export interface Catalogs {
  master_access?: {
    can_edit: boolean;
    can_create: boolean;
    edit_scope: "ALL" | "OWN" | "NONE";
    read_only_reason: string | null;
  };
  version: string;
  process_codes: string[];
  operation_codes: string[];
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
  shipping_line_id: string | null;
  plant_code: string | null;
  comments: string | null;
  damaged_material: boolean | null;
  expedited_status: string;
  pfa_approval_code: string | null;
}
export const STATUS: Record<string, string> = {
  DRAFT: "Borrador",
  PLANNED: "Programado",
  IN_TRANSIT: "En tránsito",
  AT_PORT: "En puerto",
  CUSTOMS: "En aduana",
  DELIVERED: "Entregado",
  CANCELLED: "Cancelado",
};
export const OPERATIONS: Record<string, string> = {
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
};
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
