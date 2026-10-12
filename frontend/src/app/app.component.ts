import {
  Component,
  OnInit,
  ViewChild,
  computed,
  inject,
  signal,
} from "@angular/core";
import { DatePipe } from "@angular/common";
import { FormBuilder, ReactiveFormsModule } from "@angular/forms";
import { ApiError, ApiService } from "./api.service";
import { AuthService } from "./auth.service";
import { ShipmentEditorComponent } from "./shipment-editor.component";
import {
  Catalogs,
  Identifier,
  OPERATIONS,
  Owner,
  Page,
  Shipment,
  STATUS,
  Summary,
  Supplier,
  User,
} from "./types";

@Component({
  selector: "app-root",
  standalone: true,
  imports: [DatePipe, ReactiveFormsModule, ShipmentEditorComponent],
  templateUrl: "./app.component.html",
})
export class AppComponent implements OnInit {
  @ViewChild(ShipmentEditorComponent) editor?: ShipmentEditorComponent;
  readonly auth = inject(AuthService);
  private api = inject(ApiService);
  phase = signal<"loading" | "login" | "workspace">("loading");
  user = signal<User | null>(null);
  demo = signal(false);
  catalog = signal<Catalogs | null>(null);
  suppliers = signal<Supplier[]>([]);
  owners = signal<Owner[]>([]);
  rows = signal<Shipment[]>([]);
  summary = signal<Summary | null>(null);
  total = signal(0);
  offset = signal(0);
  limit = 20;
  loading = signal(false);
  error = signal("");
  notice = signal("");
  modal = signal(false);
  selected = signal<Shipment | null>(null);
  identifiers = signal<Identifier[]>([]);
  saving = signal(false);
  detailLoading = signal(false);
  editorError = signal("");
  identifierError = signal("");
  identifiersLoading = signal(false);
  conflict = signal(false);
  readonly views = [
    { status: "", label: "Todas" },
    { status: "IN_TRANSIT", label: "En tránsito" },
    { status: "CUSTOMS", label: "En aduana" },
    { status: "DELIVERED", label: "Entregadas" },
  ];
  activeStatus = signal("");
  async selectStatus(status: string): Promise<void> {
    this.filters.controls.status.setValue(status);
    await this.apply();
  }
  status = STATUS;
  operations = OPERATIONS;
  statusCodes = Object.keys(STATUS);
  canWrite = computed(
    () =>
      !this.demo() &&
      ["OPERATOR", "FINANCE", "SUPER_ADMIN"].includes(this.user()?.role ?? ""),
  );
  canCreate = computed(
    () =>
      this.canWrite() &&
      this.user()?.analyst_code != null &&
      !!this.catalog()?.business_units_configured,
  );
  consolidated = computed(() =>
    ["MANAGER", "SUPER_ADMIN"].includes(this.user()?.role ?? ""),
  );
  unitCodes = computed(() => Object.keys(this.catalog()?.business_units ?? {}));
  lastItem = computed(() => Math.min(this.offset() + this.limit, this.total()));
  roleName = computed(
    () =>
      ({
        OPERATOR: "Operaciones",
        FINANCE: "Finanzas",
        MANAGER: "Gerencia",
        SUPER_ADMIN: "Administración",
      })[this.user()?.role ?? "OPERATOR"],
  );
  filters = new FormBuilder().nonNullable.group({
    q: [""],
    operation_code: [""],
    status: [""],
    business_unit: [""],
    company_code: [""],
    owner_id: [""],
    ship_date_from: [""],
    ship_date_to: [""],
  });
  private applied: Record<string, string> = {};
  private abort?: AbortController;
  private detailRequest = 0;
  private listRequest = 0;
  private demoRows: Shipment[] = [];
  async ngOnInit(): Promise<void> {
    try {
      if (await this.auth.initialize()) await this.enter();
      else this.phase.set("login");
    } catch (error) {
      this.error.set(this.message(error));
      this.phase.set("login");
    }
  }
  message(error: unknown): string {
    return error instanceof Error
      ? error.message
      : "Ocurrió un error. Intenta nuevamente.";
  }
  async login(): Promise<void> {
    this.error.set("");
    try {
      await this.auth.login();
    } catch (error) {
      this.error.set(this.message(error));
    }
  }
  async logout(): Promise<void> {
    if (this.demo()) {
      this.demo.set(false);
      this.user.set(null);
      this.catalog.set(null);
      this.rows.set([]);
      this.phase.set("login");
      return;
    }
    try {
      await this.auth.logout();
    } catch (error) {
      this.error.set(this.message(error));
    }
  }
  private async enter(): Promise<void> {
    this.user.set(await this.api.request<User>("/auth/me"));
    const [catalog, owners] = await Promise.all([
      this.api.request<Catalogs>("/references/catalogs"),
      this.api.request<Owner[]>("/masters/owners"),
    ]);
    const suppliers: Supplier[] = [];
    let offset = 0;
    let total = 1;
    while (offset < total) {
      const page = await this.api.request<Page<Supplier>>(
        `/suppliers?limit=100&offset=${offset}`,
      );
      suppliers.push(...page.items);
      total = page.total;
      offset += 100;
    }
    this.catalog.set(catalog);
    this.owners.set(owners);
    this.suppliers.set(suppliers);
    this.phase.set("workspace");
    await this.refresh();
  }
  async preview(): Promise<void> {
    const data = await import("./demo");
    this.demo.set(true);
    this.user.set(data.demoUser);
    this.catalog.set(data.demoCatalogs);
    this.owners.set([{ id: "demo", display_name: "Usuario de demostración" }]);
    this.suppliers.set([]);
    this.demoRows = data.demoShipments;
    this.filters.reset();
    this.applied = {};
    this.activeStatus.set("");
    this.offset.set(0);
    this.error.set("");
    this.notice.set("");
    this.phase.set("workspace");
    await this.refresh();
  }
  async apply(): Promise<void> {
    const values = this.filters.getRawValue();
    if (
      values.ship_date_from &&
      values.ship_date_to &&
      values.ship_date_from > values.ship_date_to
    ) {
      this.error.set("La fecha inicial no puede ser posterior a la final.");
      return;
    }
    this.activeStatus.set(values.status);
    this.applied = Object.fromEntries(
      Object.entries(values)
        .map(([key, value]) => [key, value.trim()])
        .filter(([, value]) => value !== ""),
    );
    this.offset.set(0);
    await this.refresh();
  }
  async clear(): Promise<void> {
    this.filters.reset();
    await this.apply();
  }
  async changePage(direction: number): Promise<void> {
    this.offset.update((value) => Math.max(0, value + direction * this.limit));
    await this.refresh();
  }
  async refresh(): Promise<void> {
    this.abort?.abort();
    const controller = new AbortController();
    this.abort = controller;
    const request = ++this.listRequest;
    this.loading.set(true);
    this.error.set("");
    this.summary.set(null);
    try {
      if (this.demo()) {
        const rows = this.demoRows.filter((row) =>
          Object.entries(this.applied).every(([key, value]) => {
            if (key === "q")
              return [row.reference_raw, row.sender, row.consignee].some(
                (text) => text?.toLowerCase().includes(value.toLowerCase()),
              );
            if (key === "ship_date_from")
              return !!row.ship_date && row.ship_date >= value;
            if (key === "ship_date_to")
              return !!row.ship_date && row.ship_date <= value;
            return row[key as keyof Shipment] === value;
          }),
        );
        this.total.set(rows.length);
        this.rows.set(rows.slice(this.offset(), this.offset() + this.limit));
        const by_status: Record<string, number> = {};
        rows.forEach(
          (row) => (by_status[row.status] = (by_status[row.status] ?? 0) + 1),
        );
        this.summary.set({ total: rows.length, by_status });
      } else {
        const query = new URLSearchParams(this.applied);
        const [page, summary] = await Promise.all([
          this.api.request<Page<Shipment>>(
            `/shipments?${query}&limit=${this.limit}&offset=${this.offset()}`,
            "GET",
            undefined,
            controller.signal,
          ),
          this.api.request<Summary>(
            `/shipments/summary?${query}`,
            "GET",
            undefined,
            controller.signal,
          ),
        ]);
        if (request !== this.listRequest) return;
        if (this.offset() > 0 && this.offset() >= page.total) {
          this.offset.set(0);
          await this.refresh();
          return;
        }
        this.rows.set(page.items);
        this.total.set(page.total);
        this.summary.set(summary);
      }
    } catch (error) {
      if (request !== this.listRequest) return;
      if (error instanceof DOMException && error.name === "AbortError") return;
      this.rows.set([]);
      this.total.set(0);
      this.error.set(this.message(error));
    } finally {
      if (request === this.listRequest) this.loading.set(false);
    }
  }
  ownerName(id: string): string {
    return (
      this.owners().find((owner) => owner.id === id)?.display_name ?? "Usuario"
    );
  }
  count(status: string): string {
    return this.summary()
      ? String(this.summary()!.by_status[status] ?? 0)
      : "—";
  }
  openCreate(): void {
    if (!this.canCreate()) return;
    this.selected.set(null);
    this.resetEditor();
    this.modal.set(true);
  }
  private resetEditor(): void {
    this.editorError.set("");
    this.identifierError.set("");
    this.conflict.set(false);
    this.identifiers.set([]);
  }
  async open(row: Shipment): Promise<void> {
    const request = ++this.detailRequest;
    this.detailLoading.set(true);
    this.error.set("");
    try {
      const fresh = this.demo()
        ? row
        : await this.api.request<Shipment>(`/shipments/${row.id}`);
      if (request !== this.detailRequest) return;
      this.selected.set(fresh);
      this.resetEditor();
      this.modal.set(true);
      await this.loadIdentifiers();
    } catch (error) {
      this.error.set(this.message(error));
    } finally {
      if (request === this.detailRequest) this.detailLoading.set(false);
    }
  }
  closeEditor(): void {
    this.modal.set(false);
    this.detailRequest++;
  }
  async reloadDetail(): Promise<void> {
    const row = this.selected();
    if (row) {
      this.modal.set(false);
      await this.open(row);
    }
  }
  async loadIdentifiers(): Promise<void> {
    const id = this.selected()?.id;
    if (!id || this.demo()) return;
    this.identifiersLoading.set(true);
    this.identifierError.set("");
    try {
      const data = await this.api.request<Identifier[]>(
        `/shipments/${id}/identifiers`,
      );
      if (this.selected()?.id === id) this.identifiers.set(data);
    } catch (error) {
      if (this.selected()?.id === id)
        this.identifierError.set(this.message(error));
    } finally {
      if (this.selected()?.id === id) this.identifiersLoading.set(false);
    }
  }
  async save(data: Record<string, unknown>): Promise<void> {
    if (!this.canWrite() || this.saving() || this.conflict()) return;
    this.saving.set(true);
    this.editorError.set("");
    const previous = this.selected();
    try {
      const row = await this.api.request<Shipment>(
        previous ? `/shipments/${previous.id}` : "/shipments",
        previous ? "PATCH" : "POST",
        data,
      );
      this.selected.set(row);
      this.editor?.form.markAsPristine();
      this.notice.set(
        previous
          ? "Cambios guardados."
          : `Embarque creado: ${row.reference_raw}. Ya puedes agregar sus documentos.`,
      );
      // Switch the existing form to edit mode immediately: a later read failure must never resubmit a creation.
      await this.loadIdentifiers();
      await this.refresh();
    } catch (error) {
      this.editorError.set(this.message(error));
      if (error instanceof ApiError && error.status === 409 && previous)
        this.conflict.set(true);
      if (error instanceof ApiError && error.status === 0)
        this.editorError.set(
          "No se confirmó el guardado. Cierra el detalle y actualiza la lista para comprobar si se registró antes de intentarlo otra vez.",
        );
    } finally {
      this.saving.set(false);
    }
  }
  async addIdentifier(data: {
    kind: string;
    raw_value: string;
  }): Promise<void> {
    const id = this.selected()?.id;
    if (!id || !this.canWrite() || this.saving()) return;
    this.saving.set(true);
    this.identifierError.set("");
    try {
      const row = await this.api.request<Identifier>(
        `/shipments/${id}/identifiers`,
        "POST",
        data,
      );
      this.identifiers.update((items) => [...items, row]);
      this.editor?.clearIdentifier();
    } catch (error) {
      this.identifierError.set(this.message(error));
    } finally {
      this.saving.set(false);
    }
  }
}
