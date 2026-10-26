import {
  Component,
  OnInit,
  ViewChild,
  computed,
  inject,
  signal,
} from "@angular/core";
import { FormBuilder, ReactiveFormsModule } from "@angular/forms";
import { NgTemplateOutlet } from "@angular/common";
import { IconComponent, IconName } from "./icon.component";
import { ApiError, ApiService } from "./api.service";
import { FinanceWorkspaceComponent } from "./finance-workspace.component";
import { Section } from "./finance.types";
import { ReferenceActivityComponent } from "./reference-activity.component";
import { AuthService } from "./auth.service";
import { ShipmentEditorComponent } from "./shipment-editor.component";
import { MasterSheetComponent } from "./master-sheet.component";
import { MasterPracticeService } from "./master-practice.service";
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
  imports: [
    ReactiveFormsModule,
    NgTemplateOutlet,
    IconComponent,
    ShipmentEditorComponent,
    MasterSheetComponent,
    FinanceWorkspaceComponent,
    ReferenceActivityComponent,
  ],
  templateUrl: "./app.component.html",
})
export class AppComponent implements OnInit {
  activity = signal<Shipment | null>(null);
  @ViewChild(FinanceWorkspaceComponent) finance?: FinanceWorkspaceComponent;
  section = signal<Section>("home");
  readonly sections: { id: Section; label: string; icon: IconName }[] = [
    { id: "home", label: "Inicio", icon: "home" },
    { id: "masters", label: "Masters", icon: "grid" },
    { id: "provisions", label: "Provisiones", icon: "wallet" },
    { id: "invoices", label: "Facturas", icon: "document" },
    { id: "history", label: "Historial", icon: "history" },
  ];
  changeSection(section: Section) {
    if (section === this.section() || this.saving() || this.sheet?.saving())
      return;
    if (this.sheet && !this.sheet.canLeave()) return;
    if (this.finance && !this.finance.canLeave()) return;
    this.section.set(section);
  }
  @ViewChild(ShipmentEditorComponent) editor?: ShipmentEditorComponent;
  @ViewChild(MasterSheetComponent) sheet?: MasterSheetComponent;
  readonly auth = inject(AuthService);
  private api = inject(ApiService);
  private practiceStore = inject(MasterPracticeService);
  phase = signal<"loading" | "login" | "workspace">("loading");
  user = signal<User | null>(null);
  userInitials = computed(() => (this.user()?.display_name ?? "M").trim().split(/\s+/).slice(0, 2).map(part => part[0] ?? "").join("").toUpperCase());
  demo = signal(false);
  practice = signal(false);
  filtersVisible = signal(false);
  catalog = signal<Catalogs | null>(null);
  suppliers = signal<Supplier[]>([]);
  owners = signal<Owner[]>([]);
  rows = signal<Shipment[]>([]);
  summary = signal<Summary | null>(null);
  total = signal(0);
  offset = signal(0);
  limit = 50;
  focusedSheet = signal(false);
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
  get statusCodes(): string[] { return [...new Set([...Object.keys(STATUS), ...this.catalog()?.shipment_statuses ?? [], ...Object.keys(this.summary()?.by_status ?? {}).filter(Boolean)])]; }
  canWrite = computed(
    () =>
      !this.demo() &&
      ["OPERATOR", "SUPER_ADMIN"].includes(this.user()?.role ?? "") &&
      this.catalog()?.master_access?.can_edit !== false,
  );
  canEditSheet = computed(() => this.canWrite() || (this.demo() && this.practice()));
  readOnlyReason = computed(() => {
    if (this.demo()) return "Estás en una demostración con datos ficticios. Activa la práctica para editar una copia en este navegador. Para guardar operaciones reales, inicia sesión con Microsoft y conecta la base de desarrollo.";
    return this.catalog()?.master_access?.read_only_reason ??
      `Tu perfil de ${this.roleName()} permite consultar los masters. La edición operativa corresponde a Operaciones y Administración.`;
  });
  masterOwner = signal("");
  masterReady = computed(
    () => !!this.masterOwner(),
  );
  masterSelection = new FormBuilder().nonNullable.group({
    owner_id: [""],
  });
  logisticsOwners = computed(() =>
    this.owners().filter(
      (owner) =>
        owner.analyst_code != null &&
        owner.analyst_code >= 1 &&
        owner.analyst_code <= 5,
    ),
  );
  otherOwners = computed(() =>
    this.owners().filter(
      (owner) => !this.logisticsOwners().some((item) => item.id === owner.id),
    ),
  );
  resetMaster(): boolean {
    if (this.sheet && !this.sheet.canLeave()) {
      this.masterSelection.patchValue({
        owner_id: this.masterOwner(),
      });
      return false;
    }
    this.abort?.abort();
    this.listRequest++;
    this.detailRequest++;
    this.masterOwner.set("");
    this.rows.set([]);
    this.summary.set(null);
    this.total.set(0);
    this.offset.set(0);
    this.loading.set(false);
    this.detailLoading.set(false);
    this.modal.set(false);
    this.selected.set(null);
    this.notice.set("");
    this.error.set("");
    this.filters.reset();
    this.applied = {};
    this.activeStatus.set("");
    return true;
  }
  async chooseMaster(): Promise<void> {
    const selection = this.masterSelection.getRawValue();
    const owner = selection.owner_id;
    if (!this.resetMaster()) return;
    if (!owner) {
      return;
    }
    if (
      !this.logisticsOwners().some(item => item.id === owner)
    )
      return;
    this.masterOwner.set(owner ?? "");
    await this.apply();
  }
  canCreate = computed(
    () =>
      this.canWrite() &&
      this.catalog()?.master_access?.can_create !== false &&
      this.masterReady() &&
      (this.user()?.role === "SUPER_ADMIN" || this.masterOwner() === this.user()?.id) &&
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
    status: [""],
    business_unit: [""],
    company_code: [""],
    operation_code: [""],
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
    if (this.finance && !this.finance.canLeave()) return;
    if (this.sheet && !this.sheet.canLeave()) return;
    if (this.demo()) {
      this.demo.set(false);
      this.practice.set(false);
      this.user.set(null);
      this.catalog.set(null);
      this.rows.set([]);
      this.section.set("home");
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
    this.resetMaster();
    this.masterSelection.reset({
      owner_id: this.consolidated() ? "" : this.user()!.id,
    });
    this.phase.set("workspace");
  }
  async preview(practice = false): Promise<void> {
    const data = await import("./demo");
    this.demo.set(true);
    this.practice.set(false);
    this.user.set(data.demoUser);
    this.catalog.set(data.demoCatalogs);
    this.owners.set(data.demoOwners);
    this.suppliers.set([]);
    this.demoRows = data.masterDemoShipments;
    this.filters.reset();
    this.applied = {};
    this.activeStatus.set("");
    this.offset.set(0);
    this.error.set("");
    this.notice.set("");
    this.resetMaster();
    this.masterSelection.reset();
    this.phase.set("workspace");
    if (practice) await this.enablePractice();
  }
  async enablePractice(): Promise<void> {
    if (!this.demo() || (this.sheet && !this.sheet.canLeave())) return;
    this.section.set("masters");
    try {
      this.demoRows = this.practiceStore.start(this.demoRows);
      this.practice.set(true);
      if (this.masterReady()) await this.refresh();
      else {
        this.masterSelection.patchValue({ owner_id: this.logisticsOwners()[0]?.id ?? "" });
        await this.chooseMaster();
      }
    } catch (error) { this.error.set(this.message(error)); }
  }
  async resetPractice(): Promise<void> {
    if (!this.demo() || (this.sheet && !this.sheet.canLeave())) return;
    if (!window.confirm("¿Restablecer los datos ficticios? Se borrarán solo los cambios de práctica de este navegador.")) return;
    try {
      const data = await import("./demo");
      this.practiceStore.reset();
      this.demoRows = data.masterDemoShipments;
      await this.enablePractice();
    } catch (error) { this.error.set(this.message(error)); }
  }
  async apply(): Promise<void> {
    if (!this.masterReady()) return;
    const values = this.filters.getRawValue();
    if (
      values.ship_date_from &&
      values.ship_date_to &&
      values.ship_date_from > values.ship_date_to
    ) {
      this.error.set("La fecha inicial no puede ser posterior a la final.");
      return;
    }
    if (this.sheet && !this.sheet.canLeave()) return;
    this.activeStatus.set(values.status);
    this.applied = Object.fromEntries(
      Object.entries(values)
        .map(([key, value]) => [key, value.trim()])
        .filter(([, value]) => value !== ""),
    );
    if (this.masterOwner()) this.applied["owner_id"] = this.masterOwner();
    this.offset.set(0);
    await this.refresh();
  }
  async clear(): Promise<void> {
    this.filters.reset();
    await this.apply();
  }
  async changePage(direction: number): Promise<void> {
    if (this.sheet && !this.sheet.canLeave()) return;
    this.offset.update((value) => Math.max(0, value + direction * this.limit));
    await this.refresh();
  }
  async refresh(): Promise<void> {
    if (!this.masterReady()) return;
    if (this.sheet && !this.sheet.canLeave()) return;
    this.abort?.abort();
    const controller = new AbortController();
    this.abort = controller;
    const request = ++this.listRequest;
    this.loading.set(true);
    this.error.set("");
    this.summary.set(null);
    try {
      if (this.demo()) {
        if (this.practice()) this.demoRows = this.practiceStore.refresh();
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
            `/masters/shipments?${query}&limit=${this.limit}&offset=${this.offset()}`,
            "GET",
            undefined,
            controller.signal,
          ),
          this.api.request<Summary>(
            `/masters/summary?${query}`,
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
    if (this.sheet && !this.sheet.canLeave()) return;
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
    if (this.sheet && !this.sheet.canLeave()) return;
    const request = ++this.detailRequest;
    this.detailLoading.set(true);
    this.error.set("");
    try {
      const fresh = this.demo()
        ? row
        : await this.api.request<Shipment>(`/shipments/${row.id}`);
      if (request !== this.detailRequest) return;
      if (
        fresh.owner_id !== this.masterOwner()
      )
        throw new Error("El registro no pertenece al master seleccionado.");
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
  private rememberOperation(operation: string | null): void {
    if (operation && this.catalog() && !this.catalog()!.operation_codes.includes(operation))
      this.catalog.update(catalog => ({ ...catalog!, operation_codes: [...catalog!.operation_codes, operation] }));
  }
  updateSheetRow(row: Shipment): void {
    if (this.demo() && this.practice()) this.demoRows = this.practiceStore.rows;
    const previous = this.rows().find((item) => item.id === row.id);
    if (
      !previous ||
      row.owner_id !== this.masterOwner()
    )
      return;
    this.rememberOperation(row.operation_code);
    if (this.catalog() && !this.catalog()!.company_codes.includes(row.company_code)) {
      this.catalog.update(catalog => ({ ...catalog!, company_codes: [...catalog!.company_codes, row.company_code] }));
    }
    this.rows.update((items) =>
      items.map((item) => (item.id === row.id ? row : item)),
    );
    if (previous.status !== row.status)
      this.summary.update((summary) => {
        if (!summary) return summary;
        const by_status = { ...summary.by_status };
        by_status[previous.status] = Math.max(
          0,
          (by_status[previous.status] ?? 0) - 1,
        );
        by_status[row.status] = (by_status[row.status] ?? 0) + 1;
        return { ...summary, by_status };
      });
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
    if (
      !previous &&
      (!this.canCreate() || !this.catalog()?.operation_codes.includes(String(data["operation_code"])))
    ) {
      this.editorError.set(
        "Selecciona un tipo de operación válido para el nuevo embarque.",
      );
      this.saving.set(false);
      return;
    }
    try {
      if (!previous) data["owner_id"] = this.masterOwner();
      const row = await this.api.request<Shipment>(
        previous ? `/shipments/${previous.id}` : "/shipments",
        previous ? "PATCH" : "POST",
        data,
      );
      this.selected.set(row);
      this.rememberOperation(row.operation_code);
      this.editor?.form.patchValue({ reference_raw: row.reference_raw ?? "" });
      if (!this.catalog()!.company_codes.includes(row.company_code)) {
        this.catalog.update(catalog => ({ ...catalog!, company_codes: [...catalog!.company_codes, row.company_code] }));
      }
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
