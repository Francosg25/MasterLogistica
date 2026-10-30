import { FormsModule } from "@angular/forms";
import { Shipment, STATUS } from "./types";
import { IconComponent } from "./icon.component";
import { conceptLabel, InvoiceApplication } from "./finance.types";
import {
  AfterViewInit,
  Component,
  ElementRef,
  EventEmitter,
  Input,
  OnDestroy,
  Output,
  ViewChild,
  inject,
  signal,
} from "@angular/core";
import { ApiService } from "./api.service";
import { EVENTS, FIELDS, FINANCE_STATUS, HistoryRow } from "./finance.types";

interface Activity {
  reference: string;
  provisions: {
    id: string;
    supplier: string;
    concept: string;
    month: string;
    provision_date?: string | null;
    currency: string;
    total: string;
    balance: string | null;
    status: string;
  }[];
  invoices: {
    id: string;
    invoice_number: string;
    supplier: string;
    concept: string;
    month: string;
    currency: string;
    amount: string;
    applied: string;
    status: string;
    amount_basis: string;
    applications?: InvoiceApplication[];
  }[];
  history: { items: HistoryRow[]; total: number };
}
@Component({
  selector: "reference-activity",
  standalone: true,
  imports: [FormsModule, IconComponent],
  templateUrl: "./reference-activity.component.html",
})
export class ReferenceActivityComponent implements AfterViewInit, OnDestroy {
  readonly conceptLabel = conceptLabel;
  @Input() shipmentId = "";
  @Input() reference = "";
  @Input() demo = false;
  @Input() canCreate = false;
  @Input() canFinance = false;
  @Output() capture = new EventEmitter<{
    kind: "provision" | "invoice";
    reference: string;
    company: string;
  }>();
  requestCapture(kind: "provision" | "invoice") {
    this.capture.emit({
      kind,
      reference: this.reference,
      company: this.family()?.root.company_code ?? "",
    });
  }
  @Output() created = new EventEmitter<void>();
  tab = signal("overview");
  family = signal<{
    root: Shipment;
    can_add_movements?: boolean;
    members: {
      id: string;
      reference: string;
      owner_name: string;
      status: string;
      movement_number: number | null;
      is_current: boolean;
    }[];
    classification: {
      process: string;
      operation: string;
      year: number;
      business_unit: string;
      department: string | null;
    };
  } | null>(null);
  familyError = signal("");
  creating = signal(false);
  createOpen = signal(false);
  description = "";
  carrier = "";
  movementOwner = "";
  owners = signal<{ id: string; display_name: string }[]>([]);
  notice = signal("");
  operationalStatus = STATUS;
  async selectMember(member: { id: string; reference: string }) {
    if (this.creating()) return;
    this.shipmentId = member.id;
    this.reference = member.reference;
    this.createOpen.set(false);
    this.notice.set("");
    await this.load();
  }
  async openMovement() {
    this.familyError.set("");
    try {
      const owners =
        await this.api.request<{ id: string; display_name: string }[]>(
          "/masters/owners",
        );
      this.owners.set(owners);
      this.movementOwner = this.family()?.root.owner_id ?? owners[0]?.id ?? "";
      this.description = "";
      this.carrier = "";
      this.createOpen.set(true);
    } catch (e) {
      this.familyError.set(
        e instanceof Error
          ? e.message
          : "No se pudieron cargar los responsables.",
      );
    }
  }
  async createMovement() {
    const root = this.family()?.root;
    if (!root || !this.movementOwner || this.creating()) return;
    this.creating.set(true);
    this.familyError.set("");
    try {
      const row = await this.api.request<Shipment>("/shipments", "POST", {
        parent_shipment_id: root.id,
        owner_id: this.movementOwner,
        company_code: root.company_code,
        process_code: root.process_code,
        operation_code: root.operation_code,
        reference_year: root.reference_year,
        business_unit: root.business_unit,
        department_code: root.department_code,
        comments: this.description.trim() || null,
        carrier_broker_name: this.carrier.trim() || null,
      });
      this.createOpen.set(false);
      this.notice.set(`Movimiento ${row.reference_raw} creado.`);
      this.created.emit();
      await this.load();
    } catch (e) {
      this.familyError.set(
        e instanceof Error ? e.message : "No se pudo crear el movimiento.",
      );
    } finally {
      this.creating.set(false);
    }
  }

  @Output() closed = new EventEmitter<void>();
  @ViewChild("dialog") dialog!: ElementRef<HTMLDialogElement>;
  private api = inject(ApiService);
  private controller = new AbortController();
  private generation = 0;
  data = signal<Activity | null>(null);
  error = signal("");
  loading = signal(false);
  labels = FINANCE_STATUS;
  events = EVENTS;
  fields = FIELDS;
  ngAfterViewInit() {
    this.dialog.nativeElement.showModal();
    void this.load();
  }
  ngOnDestroy() {
    this.generation++;
    this.controller.abort();
  }
  async load() {
    this.controller.abort();
    this.controller = new AbortController();
    const controller = this.controller,
      generation = ++this.generation;
    this.data.set(null);
    this.family.set(null);
    this.loading.set(true);
    this.error.set("");
    this.familyError.set("");
    try {
      if (this.demo) {
        const d = await import("./finance-demo");
        const balances = d.demoReport.balances.filter(
          (r) => r.reference === this.reference,
        );
        const invoices = d.demoInvoices.flatMap((i) =>
          i.lines
            .filter((l) => l.reference === this.reference)
            .map((l) => ({
              id: l.id,
              invoice_number: i.invoice_number,
              supplier: i.supplier_name,
              concept: l.charge_code,
              month: i.accounting_period,
              currency: i.currency,
              amount: l.net_amount,
              applied: l.applied_amount,
              status: i.status,
              amount_basis: "NET",
            })),
        );
        const events = d.demoHistory.filter(
          (h) => h.reference === this.reference,
        );
        if (generation !== this.generation) return;
        this.data.set({
          reference: this.reference,
          provisions: balances.map((b) => ({
            id: b.id,
            supplier: b.supplier_name,
            concept: b.charge_code,
            month: b.month_accrued,
            currency: b.currency,
            total: b.total_amount,
            balance: b.closing_amount,
            status: b.status,
          })),
          invoices,
          history: { items: events, total: events.length },
        });
      } else {
        const [activity, family] = await Promise.allSettled([
          this.api.request<Activity>(
            `/finance/references/${this.shipmentId}/activity`,
            "GET",
            undefined,
            this.controller.signal,
          ),
          this.api.request<NonNullable<ReturnType<typeof this.family>>>(
            `/shipments/${this.shipmentId}/family`,
            "GET",
            undefined,
            this.controller.signal,
          ),
        ]);
        if (generation !== this.generation) return;
        if (activity.status === "fulfilled") this.data.set(activity.value);
        else throw activity.reason;
        if (family.status === "fulfilled") this.family.set(family.value);
        else {
          this.family.set(null);
          this.familyError.set(
            "No se pudo cargar la familia de referencias. Puedes consultar los movimientos financieros.",
          );
        }
      }
    } catch (e) {
      if (generation === this.generation && !controller.signal.aborted)
        this.error.set(
          e instanceof Error
            ? e.message
            : "No se pudieron cargar los movimientos.",
        );
    } finally {
      if (generation === this.generation) this.loading.set(false);
    }
  }
  async more() {
    const data = this.data(),
      generation = this.generation;
    if (!data || this.loading()) return;
    this.loading.set(true);
    try {
      const next = await this.api.request<{
        items: HistoryRow[];
        total: number;
      }>(
        `/finance/history?shipment_id=${this.shipmentId}&limit=100&offset=${data.history.items.length}`,
        "GET",
        undefined,
        this.controller.signal,
      );
      if (generation !== this.generation) return;
      this.data.set({
        ...data,
        history: {
          items: [...data.history.items, ...next.items],
          total: next.total,
        },
      });
    } catch (e) {
      if (generation === this.generation)
        this.error.set(
          e instanceof Error ? e.message : "No se pudo cargar el historial.",
        );
    } finally {
      if (generation === this.generation) this.loading.set(false);
    }
  }
  money(value: string | null) {
    return value === null
      ? "No aplicable"
      : Number(value).toLocaleString("es-MX", {
          minimumFractionDigits: 2,
          maximumFractionDigits: 4,
        });
  }
  date(value: string) {
    return new Date(value).toLocaleString("es-MX", {
      timeZone: "America/Mexico_City",
    });
  }
  value(value: unknown): string {
    return value == null || value === ""
      ? "Vacío"
      : typeof value === "object"
        ? JSON.stringify(value)
        : this.labels[String(value)] || String(value);
  }
}
