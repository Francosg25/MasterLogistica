import {
  Component,
  EventEmitter,
  Input,
  OnDestroy,
  OnInit,
  Output,
  inject,
  signal,
} from "@angular/core";
import { ApiService } from "./api.service";
import { IconComponent } from "./icon.component";
import { CurrencyTotal, Section } from "./finance.types";
import { STATUS } from "./types";

interface Overview {
  month: string;
  active_references: number;
  live_provisions: number;
  settled_provisions: number;
  invoices_in_month: number;
  pending_invoices: number;
  totals: CurrencyTotal[];
  recent: {
    id: string;
    reference: string;
    owner_name: string;
    business_unit: string;
    status: string;
    updated_at?: string;
  }[];
}
@Component({
  selector: "workspace-home",
  standalone: true,
  imports: [IconComponent],
  templateUrl: "./workspace-home.component.html",
})
export class WorkspaceHomeComponent implements OnInit, OnDestroy {
  @Input() demo = false;
  @Output() navigate = new EventEmitter<Section>();
  @Output() referenceOpened = new EventEmitter<{
    id: string;
    reference: string;
  }>();
  private api = inject(ApiService);
  private controller = new AbortController();
  data = signal<Overview | null>(null);
  error = signal("");
  loading = signal(false);
  status = STATUS;
  today = new Date();
  month = `${this.today.getFullYear()}-${String(this.today.getMonth() + 1).padStart(2, "0")}-01`;
  dateLabel = new Intl.DateTimeFormat("es-MX", {
    weekday: "long",
    day: "numeric",
    month: "long",
  }).format(this.today);
  ngOnInit() {
    void this.load();
  }
  ngOnDestroy() {
    this.controller.abort();
  }
  async load() {
    this.loading.set(true);
    this.error.set("");
    try {
      if (this.demo) {
        const [d, f] = await Promise.all([
          import("./demo"),
          import("./finance-demo"),
        ]);
        this.data.set({
          month: "2026-10-01",
          active_references: d.masterDemoShipments.length,
          live_provisions: f.demoReport.balances.filter((b) =>
            ["OPEN", "PARTIALLY_MATCHED"].includes(b.status),
          ).length,
          settled_provisions: 1,
          invoices_in_month: f.demoInvoices.length,
          pending_invoices: 0,
          totals: f.demoReport.totals,
          recent: d.masterDemoShipments
            .slice(0, 6)
            .map((s) => ({
              id: s.id,
              reference: s.reference_raw ?? "Sin referencia",
              owner_name:
                d.demoOwners.find((o) => o.id === s.owner_id)?.display_name ??
                "Responsable",
              business_unit: s.business_unit ?? "",
              status: s.status,
            })),
        });
      } else
        this.data.set(
          await this.api.request<Overview>(
            `/workspace/overview?month=${this.month}`,
            "GET",
            undefined,
            this.controller.signal,
          ),
        );
    } catch (e) {
      if (!this.controller.signal.aborted)
        this.error.set(
          e instanceof Error ? e.message : "No se pudo cargar el resumen.",
        );
    } finally {
      this.loading.set(false);
    }
  }
  money(value: string) {
    return Number(value).toLocaleString("es-MX", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 4,
    });
  }
}
