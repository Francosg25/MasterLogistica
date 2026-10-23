import {
  Component,
  Input,
  OnChanges,
  OnDestroy,
  HostListener,
  inject,
  signal,
  ViewChild,
} from "@angular/core";
import { FormBuilder, ReactiveFormsModule, Validators } from "@angular/forms";
import { ApiError, ApiService } from "./api.service";
import { InvoiceImportComponent } from "./invoice-import.component";
import { ReferenceActivityComponent } from "./reference-activity.component";
import {
  Catalogs,
  Owner,
  Page,
  Supplier,
  User,
  OPERATIONS,
  STATUS,
} from "./types";
import {
  Balance,
  CurrencyTotal,
  EVENTS,
  FIELDS,
  FINANCE_STATUS,
  HistoryRow,
  InvoiceRow,
  Report,
  Section,
} from "./finance.types";

interface ReferenceOption {
  id: string;
  reference: string;
  company_code: string;
  owner_name?: string;
  business_unit?: string;
}

@Component({
  selector: "finance-workspace",
  standalone: true,
  imports: [ReactiveFormsModule, InvoiceImportComponent, ReferenceActivityComponent],
  templateUrl: "./finance-workspace.component.html",
})
export class FinanceWorkspaceComponent implements OnChanges, OnDestroy {
  @ViewChild(InvoiceImportComponent) importer?: InvoiceImportComponent;
  importOpen = signal(false);
  activity = signal<{ id: string; reference: string } | null>(null);
  @Input({ required: true }) section!: Section;
  @Input({ required: true }) user!: User;
  @Input({ required: true }) catalogs!: Catalogs;
  @Input() suppliers: Supplier[] = [];
  @Input() demo = false;
  private api = inject(ApiService);
  private fb = new FormBuilder().nonNullable;
  loading = signal(false);
  busy = signal(false);
  error = signal("");
  notice = signal("");
  balances = signal<Balance[]>([]);
  invoices = signal<InvoiceRow[]>([]);
  history = signal<HistoryRow[]>([]);
  totals = signal<CurrencyTotal[]>([]);
  report = signal<Report | null>(null);
  owners = signal<Pick<Owner, "id" | "display_name">[]>([]);
  references = signal<ReferenceOption[]>([]);
  referenceOpen = signal(false);
  referenceLoading = signal(false);
  referenceError = signal("");
  activeReference = signal(-1);
  selectedReference = signal<ReferenceOption | null>(null);
  readonly concepts = ["FREIGHT", "BROKER", "STORAGE"];
  private referenceTimer?: ReturnType<typeof setTimeout>;
  private referenceController?: AbortController;
  total = signal(0);
  offset = signal(0);
  limit = 20;
  formOpen = signal(false);
  reportOpen = signal(false);
  cancelTarget = signal<InvoiceRow | null>(null);
  expandedInvoice = signal("");
  labels = FINANCE_STATUS;
  events = EVENTS;
  fields = FIELDS;
  operations = OPERATIONS;
  eventCodes = Object.keys(EVENTS);
  // API enforces these same roles; demo never sends operational requests.
  get canWrite() {
    return !this.demo && ["FINANCE", "SUPER_ADMIN"].includes(this.user.role);
  }
  get canReadInvoices() {
    return (
      this.demo ||
      ["FINANCE", "MANAGER", "SUPER_ADMIN"].includes(this.user.role)
    );
  }
  get title() {
    return this.section === "provisions"
      ? "Provisiones por referencia"
      : this.section === "invoices"
        ? "Facturas"
        : "Historial de cambios";
  }
  get month() {
    return this.filters.controls.month.value + "-01";
  }
  private today = new Date();
  private currentMonth = `${this.today.getFullYear()}-${String(this.today.getMonth() + 1).padStart(2, "0")}`;
  private day = `${this.currentMonth}-${String(this.today.getDate()).padStart(2, "0")}`;
  filters = this.fb.group({
    month: [this.currentMonth, Validators.required],
    q: [""],
    owner_id: [""],
    operation_code: [""],
    status: [""],
    actor: [""],
    action: [""],
    date_from: [""],
    date_to: [""],
  });
  provisionForm = this.fb.group({
    reference: ["", Validators.required],
    supplier_id: ["", Validators.required],
    charge_code: [
      "FREIGHT",
      [Validators.required, Validators.pattern(/^(FREIGHT|BROKER|STORAGE)$/)],
    ],
    line_no: [1, Validators.min(1)],
    provision_date: [this.day, Validators.required],
    amount: ["", [Validators.required, Validators.min(0)]],
    extra_charges: ["0", [Validators.required, Validators.min(0)]],
    currency: ["USD", Validators.required],
  });
  newLine() {
    return this.fb.group({
      reference: ["", Validators.required],
      charge_code: [
        "FREIGHT",
        [Validators.required, Validators.pattern(/^[A-Z0-9_-]+$/)],
      ],
      net_amount: ["", [Validators.required, Validators.min(0.0001)]],
      tax_amount: ["0", [Validators.required, Validators.min(0)]],
    });
  }
  invoiceForm = this.fb.group({
    supplier_id: ["", Validators.required],
    company_code: ["", Validators.required],
    invoice_number: ["", Validators.required],
    issue_date: [this.day, Validators.required],
    accounting_period: [this.currentMonth, Validators.required],
    currency: ["USD", Validators.required],
    lines: this.fb.array([this.newLine()]),
  });
  cancelForm = this.fb.group({
    period_month: [this.currentMonth, Validators.required],
    reason: ["", [Validators.required, Validators.minLength(3)]],
  });
  private requestNumber = 0;
  private refRequest = 0;
  private controller?: AbortController;
  private applied: Record<string, string> = {};
  get lines() {
    return this.invoiceForm.controls.lines;
  }
  ngOnChanges() {
    this.expandedInvoice.set("");
    this.importOpen.set(false);
    this.formOpen.set(false);
    this.reportOpen.set(false);
    this.report.set(null);
    this.cancelTarget.set(null);
    this.filters.controls.status.setValue("");
    this.error.set("");
    this.notice.set("");
    if (this.demo) this.filters.controls.month.setValue("2026-10");
    void this.apply();
    if (!this.demo) void this.loadOwners();
  }
  ngOnDestroy() {
    this.controller?.abort();
    this.referenceController?.abort();
    clearTimeout(this.referenceTimer);
    this.refRequest++;
    this.requestNumber++;
  }
  @HostListener("window:beforeunload", ["$event"])
  beforeUnload(event: BeforeUnloadEvent) {
    if (this.dirty() || this.busy()) {
      event.preventDefault();
      event.returnValue = "";
    }
  }
  dirty() {
    return (
      !!this.importer?.dirty() ||
      (this.formOpen() &&
        (this.section === "provisions"
          ? this.provisionForm.dirty
          : this.invoiceForm.dirty)) ||
      (!!this.cancelTarget() && this.cancelForm.dirty)
    );
  }
  canLeave() {
    return (
      !this.busy() &&
      (!this.dirty() ||
        window.confirm("Hay datos sin registrar. ¿Quieres descartarlos?"))
    );
  }
  async loadOwners() {
    try {
      this.owners.set(await this.api.request<Owner[]>("/finance/owners"));
    } catch (e) {
      this.error.set(this.message(e));
    }
  }
  message(e: unknown) {
    return e instanceof Error
      ? e.message
      : "No se pudo completar la operación.";
  }
  money(value: unknown) {
    const parts = String(value ?? "0").match(/^(-?)([0-9]+)(?:\.([0-9]+))?$/);
    if (!parts) return "—";
    const integer = new Intl.NumberFormat("es-MX", {
      maximumFractionDigits: 0,
    }).format(BigInt(parts[2]));
    const fraction = (parts[3] ?? "")
      .slice(0, 4)
      .replace(/0+$/, "")
      .padEnd(2, "0");
    return `${parts[1]}${integer}.${fraction}`;
  }
  dateTime(value: string) {
    return new Date(value).toLocaleString("es-MX", {
      timeZone: "America/Mexico_City",
    });
  }
  value(value: unknown) {
    if (value === null || value === undefined || value === "") return "Vacío";
    if (typeof value === "boolean") return value ? "Sí" : "No";
    if (typeof value === "object") return JSON.stringify(value);
    return this.labels[String(value)] || STATUS[String(value)] || String(value);
  }
  query(extra: Record<string, string> = {}) {
    return new URLSearchParams({ ...this.applied, ...extra }).toString();
  }
  async apply() {
    if (this.busy()) return;
    if (this.filters.invalid) {
      this.filters.markAllAsTouched();
      return;
    }
    const v = this.filters.getRawValue();
    const keys =
      this.section === "history"
        ? [
            "q",
            "actor",
            "action",
            "date_from",
            "date_to",
            "owner_id",
            "operation_code",
          ]
        : this.section === "invoices"
          ? ["q", "status"]
          : ["q", "owner_id", "operation_code", "status"];
    this.applied = Object.fromEntries(
      keys.map((k) => [k, v[k as keyof typeof v]]).filter(([, v]) => !!v),
    );
    if (this.section !== "history") this.applied["month"] = this.month;
    this.offset.set(0);
    this.report.set(null);
    this.reportOpen.set(false);
    await this.load();
  }
  async load() {
    this.controller?.abort();
    const controller = new AbortController();
    this.controller = controller;
    const generation = ++this.requestNumber;
    this.loading.set(true);
    this.error.set("");
    this.balances.set([]);
    this.invoices.set([]);
    this.history.set([]);
    this.totals.set([]);
    this.total.set(0);
    try {
      if (this.demo) {
        await this.loadDemo();
        return;
      }
      if (this.section === "invoices" && !this.canReadInvoices) return;
      const route =
        this.section === "provisions"
          ? "balances"
          : this.section === "invoices"
            ? "invoices"
            : "history";
      let result = await this.api.request<
        Page<Balance & InvoiceRow & HistoryRow> & { totals?: CurrencyTotal[] }
      >(
        `/finance/${route}?${this.query({ limit: String(this.limit), offset: String(this.offset()) })}`,
        "GET",
        undefined,
        controller.signal,
      );
      if (generation !== this.requestNumber) return;
      if (this.section === "provisions" && this.canWrite) {
        let activated = false;
        for (const row of result.items.filter(row => row.current_status === "DRAFT" && row.currency && Number(row.total_amount) > 0)) {
          if (generation !== this.requestNumber) return;
          try {
            await this.api.request(`/finance/provisions/${row.id}/approve`, "POST", { expected_version: row.row_version });
            activated = true;
          } catch (e) {
            this.notice.set("Una provisión anterior sigue pendiente: " + this.message(e));
          }
        }
        if (activated) result = await this.api.request(`/finance/${route}?${this.query({ limit: String(this.limit), offset: String(this.offset()) })}`, "GET", undefined, controller.signal);
        if (generation !== this.requestNumber) return;
      }
      this.total.set(result.total);
      if (this.section === "provisions") {
        this.balances.set(result.items);
        this.totals.set(result.totals ?? []);
      } else if (this.section === "invoices") this.invoices.set(result.items);
      else this.history.set(result.items);
    } catch (e) {
      if (
        generation === this.requestNumber &&
        !(e instanceof DOMException && e.name === "AbortError")
      )
        this.error.set(this.message(e));
    } finally {
      if (generation === this.requestNumber) this.loading.set(false);
    }
  }
  async page(direction: number) {
    this.offset.update((v) => Math.max(0, v + direction * this.limit));
    await this.load();
  }
  openForm() {
    if (!this.canWrite) return;
    this.provisionForm.reset({
      reference: "",
      supplier_id: "",
      charge_code: "FREIGHT",
      line_no: 1,
      provision_date: this.filters.controls.month.value === this.currentMonth ? this.day : "",
      amount: "",
      extra_charges: "0",
      currency: "USD",
    });
    this.invoiceForm.reset({
      supplier_id: "",
      company_code: this.catalogs.company_codes[0] ?? "",
      invoice_number: "",
      issue_date: this.day,
      accounting_period: this.filters.controls.month.value,
      currency: "USD",
    });
    this.lines.clear();
    this.lines.push(this.newLine());
    this.invoiceForm.markAsPristine();
    this.formOpen.set(true);
    this.references.set([]);
    this.selectedReference.set(null);
    this.referenceOpen.set(false);
    this.referenceError.set("");
    this.error.set("");
  }
  closeForm() {
    if (this.canLeave()) this.formOpen.set(false);
  }
  async lookup(value: string) {
    const request = ++this.refRequest;
    this.referenceController?.abort();
    if (this.demo) {
      this.references.set([]);
      return;
    }
    const controller = new AbortController();
    this.referenceController = controller;
    this.referenceLoading.set(true);
    this.referenceError.set("");
    try {
      const rows = await this.api.request<ReferenceOption[]>(
        "/finance/references?q=" + encodeURIComponent(value.trim()), "GET", undefined, controller.signal,
      );
      if (request === this.refRequest) this.references.set(rows);
    } catch (error) {
      if (request === this.refRequest && !controller.signal.aborted) {
        this.references.set([]);
        this.referenceError.set("No se pudieron cargar las referencias. Vuelve a buscar.");
      }
    } finally {
      if (request === this.refRequest) this.referenceLoading.set(false);
    }
  }
  searchProvisionReferences(immediate = false) {
    clearTimeout(this.referenceTimer);
    this.refRequest++;
    this.referenceController?.abort();
    this.references.set([]);
    this.referenceLoading.set(true);
    this.activeReference.set(-1);
    this.referenceOpen.set(true);
    const value = this.provisionForm.controls.reference.value;
    if (!immediate) this.selectedReference.set(null);
    if (immediate) void this.lookup(value);
    else this.referenceTimer = setTimeout(() => void this.lookup(value), 180);
  }
  selectReference(reference: ReferenceOption) {
    this.provisionForm.controls.reference.setValue(reference.reference);
    this.provisionForm.controls.reference.markAsDirty();
    this.selectedReference.set(reference);
    this.referenceOpen.set(false);
    this.activeReference.set(-1);
  }
  referenceDetails(reference: ReferenceOption) {
    return [reference.owner_name, reference.business_unit, reference.company_code].filter(Boolean).join(" · ");
  }
  referenceKey(event: KeyboardEvent) {
    if (event.key === "Escape") {
      this.referenceOpen.set(false);
      event.preventDefault();
    } else if (["ArrowDown", "ArrowUp"].includes(event.key)) {
      event.preventDefault();
      if (!this.referenceOpen()) { this.searchProvisionReferences(true); return; }
      const count = this.references().length;
      if (count) this.activeReference.set((this.activeReference() + (event.key === "ArrowDown" ? 1 : -1) + count) % count);
    } else if (event.key === "Enter" && this.referenceOpen() && this.activeReference() >= 0) {
      event.preventDefault();
      this.selectReference(this.references()[this.activeReference()]);
    }
  }
  referenceBlur(event: FocusEvent) {
    if (!(event.currentTarget as HTMLElement).contains(event.relatedTarget as Node | null)) {
      this.referenceOpen.set(false);
    }
  }
  async write(action: () => Promise<unknown>, success: string) {
    if (!this.canWrite || this.busy()) return;
    this.busy.set(true);
    this.error.set("");
    this.notice.set("");
    try {
      await action();
      this.notice.set(success);
      this.report.set(null);
      this.reportOpen.set(false);
      await this.load();
    } catch (e) {
      this.error.set(
        e instanceof ApiError && e.status === 0
          ? "No se confirmó el registro. Actualiza la lista y comprueba si aparece antes de reintentarlo; el folio de factura y la línea de provisión evitan duplicados."
          : this.message(e),
      );
    } finally {
      this.busy.set(false);
    }
  }
  async saveProvision() {
    if (this.provisionForm.invalid) {
      this.provisionForm.markAllAsTouched();
      return;
    }
    await this.write(async () => {
      const v = this.provisionForm.getRawValue();
      const rows = await this.api.request<{ id: string; reference: string }[]>(
        "/finance/references?q=" + encodeURIComponent(v.reference.trim()),
      );
      const reference = rows.find(
        (x) =>
          x.reference.replace(/\s/g, "").toUpperCase() ===
          v.reference.replace(/\s/g, "").toUpperCase(),
      );
      if (!reference)
        throw new Error("Selecciona una referencia existente del master.");
      const { reference: unused, ...data } = v;
      await this.api.request("/finance/provisions", "POST", {
        ...data,
        shipment_id: reference.id,
        month_accrued: v.provision_date.slice(0, 7) + "-01",
      });
      this.filters.controls.month.setValue(v.provision_date.slice(0, 7));
      this.applied["month"] = this.month;
      this.offset.set(0);
      this.provisionForm.markAsPristine();
      this.formOpen.set(false);
    }, "Provisión guardada y aprobada automáticamente.");
  }
  async saveInvoice() {
    if (this.invoiceForm.invalid) {
      this.invoiceForm.markAllAsTouched();
      return;
    }
    await this.write(async () => {
      const v = this.invoiceForm.getRawValue();
      await this.api.request<InvoiceRow>(
        "/finance/invoices",
        "POST",
        { ...v, accounting_period: v.accounting_period + "-01" },
      );
      this.filters.controls.month.setValue(v.accounting_period);
      this.applied["month"] = this.month;
      this.offset.set(0);
      this.invoiceForm.markAsPristine();
      this.formOpen.set(false);
      this.expandedInvoice.set("");
    }, "Factura guardada. Su importe se aplicó a las provisiones disponibles.");
  }
  async invoiceImported() {
    if (this.importer?.month) this.filters.controls.month.setValue(this.importer.month);
    await this.apply();
  }
  async reconcile(row: InvoiceRow) {
    await this.write(
      () =>
        this.api.request(`/finance/invoices/${row.id}/reconcile`, "POST", {
          expected_version: row.row_version,
          period_month: this.month,
        }),
      "Conciliación revisada. Los importes sin provisión compatible permanecen pendientes.",
    );
  }
  startCancel(row: InvoiceRow) {
    this.cancelTarget.set(row);
    this.cancelForm.reset({
      period_month: this.filters.controls.month.value,
      reason: "",
    });
  }
  async cancelInvoice() {
    const row = this.cancelTarget();
    if (!row || this.cancelForm.invalid) {
      this.cancelForm.markAllAsTouched();
      return;
    }
    await this.write(async () => {
      const v = this.cancelForm.getRawValue();
      await this.api.request(`/finance/invoices/${row.id}/cancel`, "POST", {
        expected_version: row.row_version,
        period_month: v.period_month + "-01",
        reason: v.reason,
      });
      this.cancelForm.markAsPristine();
      this.cancelTarget.set(null);
    }, "Factura cancelada. Se restituyeron las provisiones mediante movimientos de reversión.");
  }
  private reportParams = "";
  reportQuery() {
    // Capture the full visible filter scope; status intentionally omitted for a complete reconciliation.
    const scope =
      this.section === "provisions" ? this.applied : { month: this.month };
    const { status, ...rest } = scope;
    return new URLSearchParams(rest).toString();
  }
  async showReport() {
    if (this.busy() || this.loading()) return;
    this.busy.set(true);
    this.error.set("");
    try {
      this.reportParams = this.reportQuery();
      if (this.demo) {
        const { demoReport } = await import("./finance-demo");
        this.report.set(demoReport);
      } else
        this.report.set(
          await this.api.request<Report>(
            "/finance/report?" + this.reportParams,
          ),
        );
      this.reportOpen.set(true);
      setTimeout(
        () =>
          document
            .querySelector(".finance-report")
            ?.scrollIntoView({ behavior: "smooth", block: "start" }),
        0,
      );
    } catch (e) {
      this.error.set(this.message(e));
    } finally {
      this.busy.set(false);
    }
  }
  async exportReport() {
    if (this.demo || this.busy()) return;
    this.busy.set(true);
    this.error.set("");
    try {
      const blob = await this.api.request<Blob>(
        "/finance/report.csv?" + this.reportParams,
        "GET",
        undefined,
        undefined,
        "blob",
      );
      const url = URL.createObjectURL(blob),
        a = document.createElement("a");
      a.href = url;
      a.download = `conciliacion-${this.report()?.month.slice(0, 7) ?? this.filters.controls.month.value}.csv`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) {
      this.error.set(this.message(e));
    } finally {
      this.busy.set(false);
    }
  }
  async loadDemo() {
    const { demoReport, demoInvoices, demoHistory } =
      await import("./finance-demo");
    const q = (this.applied["q"] ?? "").toLowerCase(),
      status = this.applied["status"];
    if (this.section === "provisions") {
      const rows = demoReport.balances.filter(
        (r) =>
          r.reference.toLowerCase().includes(q) &&
          (!status || r.status === status),
      );
      this.balances.set(rows);
      this.totals.set(
        [...new Set(rows.map((r) => r.currency))].map((currency) => {
          const selected = rows.filter(
            (r) => r.currency === currency && r.status !== "DRAFT",
          );
          const sum = (
            key:
              | "opening_amount"
              | "new_amount"
              | "released_amount"
              | "adjustment_amount"
              | "closing_amount",
          ) => String(selected.reduce((value, r) => value + Number(r[key]), 0));
          return {
            currency,
            opening_amount: sum("opening_amount"),
            new_amount: sum("new_amount"),
            released_amount: sum("released_amount"),
            adjustment_amount: sum("adjustment_amount"),
            closing_amount: sum("closing_amount"),
          };
        }),
      );
      this.total.set(rows.length);
    } else if (this.section === "invoices") {
      const rows = demoInvoices.filter(
        (r) =>
          (r.invoice_number.toLowerCase().includes(q) ||
            r.lines.some((l) => l.reference.toLowerCase().includes(q))) &&
          (!status || r.status === status),
      );
      this.invoices.set(rows);
      this.total.set(rows.length);
    } else {
      const rows = demoHistory.filter(
        (r) =>
          (r.reference ?? "").toLowerCase().includes(q) &&
          (!this.applied["action"] || r.event_type === this.applied["action"]),
      );
      this.history.set(rows);
      this.total.set(rows.length);
    }
  }
}
