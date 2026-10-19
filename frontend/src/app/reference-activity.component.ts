import { AfterViewInit, Component, ElementRef, EventEmitter, Input, OnDestroy, Output, ViewChild, inject, signal } from "@angular/core";
import { ApiService } from "./api.service";
import { EVENTS, FIELDS, FINANCE_STATUS, HistoryRow } from "./finance.types";

interface Activity {
  reference: string;
  provisions: { id: string; supplier: string; concept: string; month: string; currency: string; total: string; balance: string | null; status: string }[];
  invoices: { id: string; invoice_number: string; supplier: string; concept: string; month: string; currency: string; amount: string; applied: string; status: string; amount_basis: string }[];
  history: { items: HistoryRow[]; total: number };
}
@Component({
  selector: "reference-activity", standalone: true,
  templateUrl: "./reference-activity.component.html",
})
export class ReferenceActivityComponent implements AfterViewInit, OnDestroy {
  @Input() shipmentId = "";
  @Input() reference = "";
  @Input() demo = false;
  @Output() closed = new EventEmitter<void>();
  @ViewChild("dialog") dialog!: ElementRef<HTMLDialogElement>;
  private api = inject(ApiService);
  private controller = new AbortController();
  data = signal<Activity | null>(null);
  error = signal("");
  loading = signal(false);
  labels = FINANCE_STATUS; events = EVENTS; fields = FIELDS;
  ngAfterViewInit() { this.dialog.nativeElement.showModal(); void this.load(); }
  ngOnDestroy() { this.controller.abort(); }
  async load() {
    this.loading.set(true);
    try {
      if (this.demo) {
        const d = await import("./finance-demo");
        const balances = d.demoReport.balances.filter(r => r.reference === this.reference);
        const invoices = d.demoInvoices.flatMap(i => i.lines.filter(l => l.reference === this.reference).map(l => ({ id: l.id, invoice_number: i.invoice_number, supplier: i.supplier_name, concept: l.charge_code, month: i.accounting_period, currency: i.currency, amount: l.net_amount, applied: l.applied_amount, status: i.status, amount_basis: "NET" })));
        const events = d.demoHistory.filter(h => h.reference === this.reference);
        this.data.set({ reference: this.reference, provisions: balances.map(b => ({ id: b.id, supplier: b.supplier_name, concept: b.charge_code, month: b.month_accrued, currency: b.currency, total: b.total_amount, balance: b.closing_amount, status: b.status })), invoices, history: { items: events, total: events.length } });
      } else this.data.set(await this.api.request<Activity>(`/finance/references/${this.shipmentId}/activity`, "GET", undefined, this.controller.signal));
    } catch (e) { if (!this.controller.signal.aborted) this.error.set(e instanceof Error ? e.message : "No se pudieron cargar los movimientos."); }
    finally { this.loading.set(false); }
  }
  async more() {
    const data = this.data(); if (!data || this.loading()) return;
    this.loading.set(true);
    try {
      const next = await this.api.request<{ items: HistoryRow[]; total: number }>(`/finance/history?shipment_id=${this.shipmentId}&limit=100&offset=${data.history.items.length}`, "GET", undefined, this.controller.signal);
      this.data.set({ ...data, history: { items: [...data.history.items, ...next.items], total: next.total } });
    } catch (e) { this.error.set(e instanceof Error ? e.message : "No se pudo cargar el historial."); }
    finally { this.loading.set(false); }
  }
  money(value: string | null) { return value === null ? "No aplicable" : Number(value).toLocaleString("es-MX", { minimumFractionDigits: 2, maximumFractionDigits: 4 }); }
  date(value: string) { return new Date(value).toLocaleString("es-MX", { timeZone: "America/Mexico_City" }); }
  value(value: unknown): string { return value == null || value === "" ? "Vacío" : typeof value === "object" ? JSON.stringify(value) : this.labels[String(value)] || String(value); }
}
