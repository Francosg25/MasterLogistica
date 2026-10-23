import { Component, Input, Output, EventEmitter, OnChanges, SimpleChanges, inject, signal, computed } from "@angular/core";
import { FormsModule } from "@angular/forms";
import { ApiService } from "./api.service";
import { Supplier } from "./types";

interface ImportGroup {
  key: string; invoice_number: string; supplier_name: string; source_supplier: string;
  source_company: string; company: string; status: string; usd_amount: string; issues: string[];
  rows: { row: number; reference: string; charge_code: string; usd_amount: string | null; issue_date: string | null }[];
}
interface Preview {
  sheet: string; row_count: number; invoice_count: number; counts: Record<string, number>;
  companies: string[]; suppliers: string[]; groups: ImportGroup[];
}
@Component({
  selector: "invoice-import", standalone: true, imports: [FormsModule],
  templateUrl: "./invoice-import.component.html",
})
export class InvoiceImportComponent implements OnChanges {
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
  offset = signal(0);
  labels: Record<string, string> = { READY: "Listas", REVIEW: "Revisar", DUPLICATE: "Ya registradas", OUTSIDE: "Otros meses" };
  filtered = computed(() => this.preview()?.groups.filter(g => g.status === this.filter()) ?? []);
  visible = computed(() => this.filtered().slice(this.offset(), this.offset() + 20));
  statuses = ["READY", "REVIEW", "DUPLICATE", "OUTSIDE"];
  pending = false;
  ngOnChanges(changes: SimpleChanges) { if (changes['month'] && this.preview() && this.month !== this.analyzedMonth) this.invalidate(); }
  dirty() { return this.pending; }
  setBusy(value: boolean) { this.busy.set(value); this.working.emit(value); }
  payload(selected: string[] = []) {
    return { filename: this.filename, content_base64: this.content, period_month: this.month + "-01", company_map: Object.fromEntries(Object.entries(this.companyMap).filter(([, value]) => value)), supplier_map: Object.fromEntries(Object.entries(this.supplierMap).filter(([, value]) => value)), selected };
  }
  async choose(event: Event) {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    if (!file || this.busy()) return;
    input.value = "";
    this.error.set(""); this.preview.set(null); this.notice.set("");
    this.content = ""; this.filename = ""; this.pending = false;
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
    try {
      this.preview.set(await this.api.request<Preview>("/finance/import/preview", "POST", this.payload()));
      this.analyzedMonth = this.month;
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
      this.notice.set(`${count} facturas registradas. Se aplicó USD AMOUNT a las provisiones USD compatibles; los saldos restantes siguen pendientes.`);
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
