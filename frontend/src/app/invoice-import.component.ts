import { conceptLabel } from "./finance.types";
import { Component, Input, Output, EventEmitter, inject, signal, computed } from "@angular/core";
import { FormsModule } from "@angular/forms";
import { ApiService } from "./api.service";
import { Supplier } from "./types";

interface ReferenceMatch { status: string; shipment_id?: string; reference?: string; company?: string; owner_name?: string; }
interface ImportRow { row: number; reference: string; charge_code: string; usd_amount: string | null; issue_date: string | null; source_period?: string | null; reference_match?: ReferenceMatch; }
interface ImportGroup {
  key: string; invoice_number: string; supplier_name: string; source_supplier: string;
  source_company: string; company: string; status: string; usd_amount: string; issues: string[];
  source_periods?: string[]; supplier_action?: string;
  rows: ImportRow[];
}
interface Preview {
  sheet: string; row_count: number; invoice_count: number; counts: Record<string, number>;
  companies: string[]; suppliers: string[]; groups: ImportGroup[];
  reference_counts?: Record<string, number>;
  available_periods?: { period_month: string; row_count: number; invoice_count: number }[];
}
@Component({
  selector: "invoice-import", standalone: true, imports: [FormsModule],
  templateUrl: "./invoice-import.component.html",
})
export class InvoiceImportComponent {
  readonly conceptLabel = conceptLabel;
  @Input() suppliers: Supplier[] = [];
  @Input() companies: string[] = [];
  @Input() month = "";
  @Output() imported = new EventEmitter<string>();
  @Output() closed = new EventEmitter<void>();
  @Output() working = new EventEmitter<boolean>();
  private api = inject(ApiService);
  preview = signal<Preview | null>(null);
  stale = signal(false);
  busy = signal(false);
  error = signal("");
  notice = signal("");
  filename = "";
  private content = "";
  companyMap: Record<string, string> = {};
  supplierMap: Record<string, string> = {};
  filter = signal("FOUND");
  search = signal("");
  offset = signal(0);
  labels: Record<string, string> = { FOUND: "Coincidencias", REVIEW: "Por revisar", DUPLICATE: "Ya registradas", UNMATCHED: "Sin referencia", READY: "Lista para consolidar", OUTSIDE: "Otro mes" };
  groupFound(group: ImportGroup): boolean { return group.status === "READY" || group.rows.some(row => this.referenceFound(row)); }
  found = computed(() => this.preview()?.groups.filter(group => this.groupFound(group)) ?? []);
  ready = computed(() => this.preview()?.groups.filter(group => group.status === "READY").sort((a, b) => (a.source_periods?.[0] ?? "").localeCompare(b.source_periods?.[0] ?? "") || a.key.localeCompare(b.key)) ?? []);
  matchesFilter(group: ImportGroup, filter: string): boolean {
    if (filter === "FOUND") return this.groupFound(group) && group.status !== "DUPLICATE";
    if (filter === "UNMATCHED") return !this.groupFound(group) && group.status !== "DUPLICATE";
    return group.status === filter && (filter !== "REVIEW" || this.groupFound(group));
  }
  filtered = computed(() => {
    const query = this.searchKey(this.search());
    return this.preview()?.groups.filter(group => this.matchesFilter(group, this.filter()) &&
      (!query || [group.invoice_number, ...group.rows.flatMap(row => [row.reference, row.reference_match?.reference ?? ""])].some(value => this.searchKey(value).includes(query)))
    ) ?? [];
  });
  visible = computed(() => this.filtered().slice(this.offset(), this.offset() + 20));
  statuses = ["FOUND", "REVIEW", "DUPLICATE", "UNMATCHED"];
  referenceFound(row: ImportRow): boolean { return ["MATCHED", "OTHER_COMPANY"].includes(row.reference_match?.status ?? ""); }
  private searchKey(value: string): string { return value.normalize("NFKC").replace(/\s/g, "").toUpperCase(); }
  count(status: string): number { return this.preview()?.groups.filter(group => this.matchesFilter(group, status)).length ?? 0; }
  async mapSupplier(group: ImportGroup, value: string) { this.supplierMap[group.source_supplier] = value; this.invalidate(); await this.analyze(); }
  async mapCompany(group: ImportGroup, value: string) { this.companyMap[group.source_company] = value; this.invalidate(); await this.analyze(); }
  matchLabel(row: ImportRow): string {
    const match = row.reference_match;
    return match?.status === "MATCHED" ? `Encontrada · Master de ${match.owner_name || "responsable"} · ${match.company}` : match?.status === "OTHER_COMPANY" ? `Encontrada en otra empresa: ${match.company}` : match?.status === "AMBIGUOUS" ? "Varias coincidencias · Requiere revisión" : "Sin coincidencia en los masters";
  }
  monthLabel(value: string): string {
    return new Intl.DateTimeFormat("es-MX", { month: "long", year: "numeric", timeZone: "UTC" }).format(new Date(value.slice(0, 7) + "-01T00:00:00Z"));
  }
  pending = false;
  fxRate = "";
  fxDate = "";
  dirty() { return this.pending; }
  setBusy(value: boolean) { this.busy.set(value); this.working.emit(value); }
  payload(selected: string[] = []) {
    return { filename: this.filename, content_base64: this.content, period_month: this.month + "-01", use_source_period: true, create_suppliers: true, company_map: Object.fromEntries(Object.entries(this.companyMap).filter(([, value]) => value)), supplier_map: Object.fromEntries(Object.entries(this.supplierMap).filter(([, value]) => value)), selected, ...(this.fxRate.trim() ? { fx: { mxn_per_usd: this.fxRate.trim(), rate_date: this.fxDate, source: "Captura manual del lote Excel" } } : {}) };
  }
  async choose(event: Event) {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    if (!file || this.busy()) return;
    input.value = "";
    this.error.set(""); this.preview.set(null); this.notice.set("");
    this.content = ""; this.filename = ""; this.pending = false;
    this.search.set("");
    this.fxRate = ""; this.fxDate = "";
    if (!/\.xlsx$/i.test(file.name) || file.size > 10 * 1024 * 1024) {
      this.error.set("Selecciona un .xlsx de hasta 10 MB."); return;
    }
    this.setBusy(true);
    try {
      this.content = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result).split(",")[1]);
        reader.onerror = () => reject(new Error("No se pudo leer el archivo"));
        reader.readAsDataURL(file);
      });
      this.filename = file.name; this.pending = true;
      this.companyMap = {}; this.supplierMap = {};
    } catch (e) { this.error.set(this.message(e)); }
    finally { this.setBusy(false); }
    if (this.content && this.month) await this.analyze();
  }
  invalidate() { this.stale.set(true); this.pending = true; }
  async analyze() {
    if (this.busy() || !this.content || !/^\d{4}-\d{2}$/.test(this.month)) return;
    this.setBusy(true); this.stale.set(true); this.error.set("");
    if (this.fxRate.trim() && (!this.fxDate || !Number.isFinite(Number(this.fxRate)) || Number(this.fxRate) <= 0)) {
      this.error.set("Completa un tipo de cambio positivo y su fecha."); this.setBusy(false); return;
    }
    const firstAnalysis = !this.preview();
    try {
      const result = await this.api.request<Preview>("/finance/import/preview", "POST", this.payload());
      this.preview.set(result);
      if (firstAnalysis) this.filter.set(this.count("FOUND") ? "FOUND" : this.count("DUPLICATE") ? "DUPLICATE" : "UNMATCHED");
      this.stale.set(false);
      this.offset.set(0);
    } catch (e) { this.error.set(this.message(e)); }
    finally { this.setBusy(false); }
  }
  async confirm() {
    if (this.busy() || this.stale()) return;
    const keys = this.ready().map(g => g.key);
    if (!keys.length) return;
    this.setBusy(true); this.error.set(""); this.notice.set(""); let count = 0;
    let failure = "";
    const latestMonth = this.ready().flatMap(g => g.source_periods ?? []).sort().at(-1)?.slice(0, 7) ?? this.month;
    try {
      for (let index = 0; index < keys.length; index += 100) {
        const result = await this.api.request<{ imported: number }>("/finance/import/confirm", "POST", this.payload(keys.slice(index, index + 100)));
        count += result.imported;
        this.notice.set(`Consolidando ${count} de ${keys.length} facturas…`);
      }
      this.pending = false;
      this.notice.set(`${count} ${count === 1 ? "factura consolidada" : "facturas consolidadas"}. Consulta el saldo de cada referencia en el reporte mensual.`);
    } catch (e) {
      failure = `${count} facturas confirmadas en este intento. ${this.message(e)} Revisa la vista previa antes de reintentar; las ya registradas se detectan como duplicadas.`;
    } finally {
      this.setBusy(false);
      if (count) this.imported.emit(latestMonth);
      await this.analyze();
      if (failure) this.error.set(failure);
    }
  }
  close() {
    if (!this.busy() && (!this.pending || window.confirm("¿Cerrar la vista previa sin importar los pendientes?"))) this.closed.emit();
  }
  money(value: string | null) { return value === null ? "Sin importe" : Number(value).toLocaleString("es-MX", { minimumFractionDigits: 2, maximumFractionDigits: 4 }); }
  message(e: unknown) { return e instanceof Error ? e.message : "No se pudo procesar el archivo."; }
}
