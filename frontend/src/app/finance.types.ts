export type Section = "home" | "masters" | "provisions" | "invoices" | "history";
export interface Balance {
  shipment_id?: string;
  id: string;
  row_version: number;
  reference: string;
  supplier_name: string;
  owner_name: string;
  owner_id: string;
  operation_code: string;
  company_code: string;
  charge_code: string;
  line_no: number;
  month_accrued: string;
  provision_date?: string | null;
  period_month: string;
  currency: string;
  total_amount: string;
  opening_amount: string;
  new_amount: string;
  released_amount: string;
  adjustment_amount: string;
  closing_amount: string;
  status: string;
  current_status: string;
}
export interface CurrencyTotal {
  currency: string;
  opening_amount: string;
  new_amount: string;
  released_amount: string;
  adjustment_amount: string;
  closing_amount: string;
}
export interface InvoiceRow {
  amount_basis?: string;
  source_data?: { filename?: string; sheet?: string; row_numbers?: number[] };
  id: string;
  row_version: number;
  invoice_number: string;
  supplier_name: string;
  company_code: string;
  currency: string;
  issue_date: string;
  accounting_period: string;
  status: string;
  net_amount: string;
  tax_amount: string;
  gross_amount: string;
  applied_amount: string;
  pending_amount: string;
  lines: {
    shipment_id?: string;
    id: string;
    reference: string;
    charge_code: string;
    net_amount: string;
    tax_amount: string;
    applied_amount: string;
    pending_amount: string;
  }[];
}
export interface HistoryRow {
  id: string;
  reference: string | null;
  event_type: string;
  occurred_at: string;
  actor_name: string;
  actor_email: string;
  changes: { field: string; before: unknown; after: unknown }[];
}
export interface Movement {
  id?: string;
  reference: string;
  invoice_number: string;
  supplier_name: string;
  currency: string;
  period_month: string;
  month_accrued?: string;
  amount: string;
  entry_type: string;
  actor_name?: string;
}
export interface Report {
  month: string;
  balances: Balance[];
  totals: CurrencyTotal[];
  movements: Movement[];
  pending_invoices: Movement[];
}
export const FINANCE_STATUS: Record<string, string> = {
  DRAFT: "Borrador",
  OPEN: "Viva",
  PARTIALLY_MATCHED: "Parcial",
  CLOSED: "Liquidada",
  CANCELLED: "Cancelada",
  RECEIVED: "Recibida",
  UNDER_REVIEW: "Por conciliar",
  APPROVED: "Conciliada",
  REJECTED: "Rechazada",
};
export const EVENTS: Record<string, string> = {
  SHIPMENT_CREATED: "Creó un embarque",
  SHIPMENT_UPDATED: "Modificó el master",
  IDENTIFIER_ADDED: "Agregó un documento",
  USER_CREATED: "Creó un usuario",
  USER_UPDATED: "Modificó un usuario",
  SUPPLIER_CREATED: "Agregó un proveedor",
  SUPPLIER_UPDATED: "Modificó un proveedor",
  PERIOD_CREATED: "Abrió un periodo",
  PROVISION_DRAFT_CREATED: "Creó una provisión",
  PROVISION_DRAFT_UPDATED: "Editó una provisión",
  PROVISION_APPROVED: "Aprobó una provisión",
  INVOICE_REGISTERED: "Registró una factura",
  INVOICE_MATCHED: "Aplicó una factura",
  INVOICE_REVERSED: "Restituyó una provisión",
  INVOICE_CANCELLED: "Canceló una factura",
};
export const FIELDS: Record<string, string> = {
  amount_basis: "Base de conciliación",
  source_file: "Archivo de origen",
  source_rows: "Filas de origen",
  status: "Estado",
  balance: "Saldo",
  amount: "Importe",
  currency: "Moneda",
  net_amount: "Importe neto",
  tax_amount: "Impuestos",
  total_amount: "Provisión total",
  extra_charges: "Cargos extra",
  month_accrued: "Mes de origen",
  provision_date: "Fecha de provisión",
  accounting_period: "Periodo contable",
  period_month: "Mes del movimiento",
  invoice_number: "Factura",
  reference: "Referencia",
  reference_raw: "Referencia",
  reason: "Motivo",
  sender: "Remitente",
  origin: "Origen",
  consignee: "Destinatario",
  destination: "Destino",
  ship_date: "Fecha de embarque",
  eta: "ETA",
  delivery_date: "Fecha de entrega",
  comments: "Comentarios",
  kind: "Tipo de documento",
  raw_value: "Documento",
  charge_code: "Concepto",
  line_no: "Línea",
  damaged_material: "Material dañado",
  expedited_status: "Expedite",
  pfa_approval_code: "Código PFA",
  company_code: "Empresa",
  operation_code: "Operación",
  business_unit: "BU",
  department_code: "Departamento",
};
