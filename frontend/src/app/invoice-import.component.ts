import { conceptLabel } from "./finance.types";
import { Component, Input, Output, EventEmitter, OnChanges, SimpleChanges, inject, signal, computed } from "@angular/core";
import { FormsModule } from "@angular/forms";
import { ApiService } from "./api.service";
import { Supplier } from "./types";

interface ReferenceMatch { status: string; shipment_id?: string; reference?: string; company?: string; owner_name?: string; }
interface ImportRow { row: number; reference: string; charge_code: string; usd_amount: string | null; issue_date: string | null; source_period?: string | null; reference_match?: ReferenceMatch; }
interface ImportGroup {
  key: string; invoice_number: string; supplier_name: string; source_supplier: string;
  source_company: string; company: string; status: string; usd_amount: string; issues: string[];
  source_periods?: string[];
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
export class InvoiceImportComponent implements OnChanges {
  readonly conceptLabel = conceptLabel;
  @Input() suppliers: Supplier[] = [];
  @Input() companies: string[] = [];
  @Input() month = "";
  @Output() imported = new EventEmitter<void>();
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
  private analyzedMonth = "";
  companyMap: Record<string, string> = {};
  supplierMap: Record<string, string> = {};
  filter = signal("READY");
  search = signal("");
  offset = signal(0);
  labels: Record<string, string> = { FOUND: "Encontradas", ALL: "Todas", READY: "Listas", REVIEW: "Revisar", DUPLICATE: "Ya registradas", OUTSIDE: "Otros meses" };
  found = computed(() => this.preview()?.groups.filter(group => group.rows.some(row => this.referenceFound(row))) ?? []);
  filtered = computed(() => {
    const query = this.searchKey(this.search());
    return this.preview()?.groups.filter(group =>
      (this.filter() === "ALL" || (this.filter() === "FOUND" ? group.rows.some(row => this.referenceFound(row)) : group.status === this.filter())) &&
      (!query || [group.invoice_number, ...group.rows.flatMap(row => [row.reference, row.reference_match?.reference ?? ""])].some(value => this.searchKey(value).includes(query)))
    ) ?? [];
  });
  visible = computed(() => this.filtered().slice(this.offset(), this.offset() + 20));
  statuses = ["FOUND", "ALL", "READY", "REVIEW", "DUPLICATE", "OUTSIDE"];
  periodMismatch = computed(() => !!this.preview()?.available_periods?.length && !this.preview()!.available_periods!.some(period => period.period_month.startsWith(this.analyzedMonth)));
  hasIssues = computed(() => this.preview()?.groups.some(group => group.issues.length > 0) ?? false);
  referenceFound(row: ImportRow): boolean { return ["MATCHED", "OTHER_COMPANY"].includes(row.reference_match?.status ?? ""); }
  private searchKey(value: string): string { return value.normalize("NFKC").replace(/\s/g, "").toUpperCase(); }
  count(status: string): number { return status === "ALL" ? this.preview()?.invoice_count ?? 0 : status === "FOUND" ? this.found().length : this.preview()?.counts[status] ?? 0; }
  matchLabel(row: ImportRow): string {
    const match = row.reference_match;
    return match?.status === "MATCHED" ? `Encontrada · Master de ${match.owner_name || "responsable"} · ${match.company}` : match?.status === "OTHER_COMPANY" ? `Encontrada en otra empresa: ${match.company}` : match?.status === "AMBIGUOUS" ? "Varias coincidencias · Requiere revisión" : "Sin coincidencia en los masters";
  }
  monthLabel(value: string): string {
    return new Intl.DateTimeFormat("es-MX", { month: "long", year: "numeric", timeZone: "UTC" }).format(new Date(value.slice(0, 7) + "-01T00:00:00Z"));
  }
  async usePeriod(value: string) { if (!value) return; this.month = value.slice(0, 7); this.invalidate(); await this.analyze(); }
  pending = false;
  fxRate = "";
  fxDate = "";
  ngOnChanges(changes: SimpleChanges) { if (changes['month'] && this.preview() && this.month !== this.analyzedMonth) this.invalidate(); }
  dirty() { return this.pending; }
  setBusy(value: boolean) { this.busy.set(value); this.working.emit(value); }
  payload(selected: string[] = []) {
    return { filename: this.filename, content_base64: this.content, period_month: this.month + "-01", company_map: Object.fromEntries(Object.entries(this.companyMap).filter(([, value]) => value)), supplier_map: Object.fromEntries(Object.entries(this.supplierMap).filter(([, value]) => value)), selected, ...(this.fxRate.trim() ? { fx: { mxn_per_usd: this.fxRate.trim(), rate_date: this.fxDate, source: "Captura manual del lote Excel" } } : {}) };
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
    const firstAnalysis = !this.preview();
    try {
      const result = await this.api.request<Preview>("/finance/import/preview", "POST", this.payload());
      this.analyzedMonth = this.month;
      this.preview.set(result);
      if (firstAnalysis) this.filter.set(this.found().length ? "FOUND" : ["READY", "REVIEW", "OUTSIDE", "DUPLICATE"].find(status => result.counts[status] > 0) ?? "ALL");
      this.stale.set(false);
      this.offset.set(0);
    } catch (e) { this.error.set(this.message(e)); }
    finally { this.setBusy(false); }
  }
  async confirm() {
    if (this.busy() || this.stale()) return;
    const keys = this.preview()?.groups.filter(g => g.status === "READY").map(g => g.key) ?? [];
    if (!keys.length) return;
    this.setBusy(true); this.error.set(""); this.notice.set(""); let count = 0;
    let failure = "";
    try {
      for (let index = 0; index < keys.length; index += 100) {
        const result = await this.api.request<{ imported: number }>("/finance/import/confirm", "POST", this.payload(keys.slice(index, index + 100)));
        count += result.imported;
        this.notice.set(`Registradas ${count} de ${keys.length} facturas. Aplicando USD AMOUNT…`);
      }
      this.pending = false;
      this.notice.set(`${count} facturas registradas. Se aplicó USD AMOUNT a las provisiones compatibles${this.fxRate ? ' usando el tipo de cambio indicado para saldos en MXN' : '; los saldos en MXN requieren completar el tipo de cambio en Detalle'}.`);
    } catch (e) {
      failure = `${count} facturas confirmadas en este intento. ${this.message(e)} Revisa la vista previa antes de reintentar; las ya registradas se detectan como duplicadas.`;
    } finally {
      this.setBusy(false);
      this.imported.emit();
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
