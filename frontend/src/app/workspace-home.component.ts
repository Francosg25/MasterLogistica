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
import { Catalogs, Owner, STATUS } from "./types";
import { ownerLayout } from "./master-layout";

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
  @Input() owners: Owner[] = [];
  @Input() catalogs: Catalogs | null = null;
  @Input() selectedOwner = "";
  @Output() masterOpened = new EventEmitter<string>();
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
  view = signal<"masters" | "recent">("masters");
  search = signal("");
  status = STATUS;
  today = new Date();
  month = `${this.today.getFullYear()}-${String(this.today.getMonth() + 1).padStart(2, "0")}-01`;
  ngOnInit() {
    void this.load();
  }
  ngOnDestroy() {
    this.controller.abort();
  }
  visibleOwners(): Owner[] {
    const query = this.search().trim().toLocaleLowerCase("es-MX");
    return this.owners.filter(owner => owner.display_name.toLocaleLowerCase("es-MX").includes(query));
  }
  layout(owner: Owner) { return ownerLayout(this.catalogs, owner); }
  columnPreview(owner: Owner): string {
    const structure = this.layout(owner);
    if (!structure) return "Columnas propias de este master";
    const others = Object.values(this.catalogs?.master_layouts ?? {}).filter(layout => layout.code !== structure.code);
    const distinctive = structure.fields.filter(field => others.filter(layout => layout.fields.some(other => other.key === field.key)).length <= 1);
    return (distinctive.length ? distinctive : structure.fields.slice(7)).slice(0, 4).map(field => field.label).join(" · ");
  }
  recent() {
    const query = this.search().trim().toLocaleLowerCase("es-MX");
    return (this.data()?.recent ?? []).filter(row => `${row.reference} ${row.owner_name} ${row.business_unit}`.toLocaleLowerCase("es-MX").includes(query));
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
  monthLabel(value: string): string {
    return new Intl.DateTimeFormat("es-MX", {
      month: "long",
      year: "numeric",
      timeZone: "America/Mexico_City",
    }).format(new Date(value + "T12:00:00Z"));
  }
  money(value: string) {
    return Number(value).toLocaleString("es-MX", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 4,
    });
  }
}
