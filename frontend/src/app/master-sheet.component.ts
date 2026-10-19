import {
  Component,
  ElementRef,
  HostListener,
  computed,
  inject,
  input,
  output,
  signal,
} from "@angular/core";
import { ApiError, ApiService } from "./api.service";
import { Shipment, STATUS, Supplier } from "./types";

interface Column {
  key: keyof Shipment;
  label: string;
  width: number;
  kind: "text" | "date" | "status" | "supplier" | "locked";
  max?: number;
}
type Changes = Record<string, Record<string, string | null>>;
interface Position {
  row: number;
  col: number;
}

@Component({
  selector: "master-sheet",
  standalone: true,
  templateUrl: "./master-sheet.component.html",
})
export class MasterSheetComponent {
  private api = inject(ApiService);
  private element: ElementRef<HTMLElement> = inject(ElementRef);
  rows = input.required<Shipment[]>();
  readOnly = input(true);
  offset = input(0);
  suppliers = input<Supplier[]>([]);
  operation = input("");
  opened = output<Shipment>();
  activity = output<Shipment>();
  updated = output<Shipment>();
  drafts = signal<Changes>({});
  saving = signal(false);
  error = signal("");
  notice = signal("");
  issues = signal<Record<string, string>>({});
  blocked = new Set<string>();
  active = signal<Position>({ row: 0, col: 0 });
  anchor = signal<Position>({ row: 0, col: 0 });
  editing = signal<Position | null>(null);
  editValue = "";
  private history: Changes[] = [];
  readonly status = STATUS;
  readonly statusCodes = Object.keys(STATUS);
  readonly columns = computed<Column[]>(() => [
    { key: "reference_raw", label: "Referencia", width: 265, kind: "locked" },
    { key: "status", label: "Estado", width: 144, kind: "status" },
    { key: "business_unit", label: "BU", width: 75, kind: "locked" },
    { key: "ship_date", label: "Fecha de embarque", width: 155, kind: "date" },
    { key: "eta", label: "ETA", width: 135, kind: "date" },
    {
      key: "delivery_date",
      label: "Fecha de entrega",
      width: 150,
      kind: "date",
    },
    {
      key: "sender",
      label: "Remitente / Proveedor",
      width: 210,
      kind: "text",
      max: 250,
    },
    { key: "origin", label: "Origen", width: 170, kind: "text", max: 150 },
    {
      key: "consignee",
      label: "Destinatario / Cliente",
      width: 210,
      kind: "text",
      max: 250,
    },
    {
      key: "destination",
      label: "Destino",
      width: 170,
      kind: "text",
      max: 150,
    },
    { key: "plant_code", label: "Planta", width: 100, kind: "text", max: 32 },
    {
      key: "carrier_broker_id",
      label: "Carrier / Agente",
      width: 200,
      kind: "supplier",
    },
    ...(["SI", "SE"].includes(this.operation())
      ? [
          {
            key: "shipping_line_id",
            label: "Naviera",
            width: 200,
            kind: "supplier",
          } as Column,
        ]
      : []),
    {
      key: "comments",
      label: "Comentarios",
      width: 320,
      kind: "text",
      max: 10000,
    },
  ]);
  dirtyCount = computed(() => Object.keys(this.drafts()).length);
  cellCount = computed(() =>
    Object.values(this.drafts()).reduce(
      (sum, row) => sum + Object.keys(row).length,
      0,
    ),
  );
  address = computed(
    () =>
      this.letter(this.active().col) + (this.offset() + this.active().row + 1),
  );
  activeColumn = computed(() => this.columns()[this.active().col]);
  activeValue = computed(() => {
    const row = this.rows()[this.active().row];
    return row ? this.display(row, this.activeColumn()) : "";
  });
  get canUndo(): boolean {
    return this.history.length > 0;
  }
  letter(index: number): string {
    return String.fromCharCode(65 + index);
  }
  value(row: Shipment, column: Column): string {
    const patch = this.drafts()[row.id];
    return String(
      (patch && column.key in patch ? patch[column.key] : row[column.key]) ??
        "",
    );
  }
  display(row: Shipment, column: Column): string {
    const value = this.value(row, column);
    if (column.kind === "status") return STATUS[value] ?? value;
    if (column.kind === "supplier")
      return this.suppliers().find((s) => s.id === value)?.legal_name ?? value;
    if (column.kind === "date" && /^\d{4}-\d{2}-\d{2}$/.test(value))
      return value.split("-").reverse().join("/");
    return value;
  }
  isSelected(row: number, col: number): boolean {
    const a = this.anchor(),
      b = this.active();
    return (
      row >= Math.min(a.row, b.row) &&
      row <= Math.max(a.row, b.row) &&
      col >= Math.min(a.col, b.col) &&
      col <= Math.max(a.col, b.col)
    );
  }
  isActive(row: number, col: number): boolean {
    return this.active().row === row && this.active().col === col;
  }
  isEditing(row: number, col: number): boolean {
    return this.editing()?.row === row && this.editing()?.col === col;
  }
  isDirty(row: Shipment, column: Column): boolean {
    return column.key in (this.drafts()[row.id] ?? {});
  }
  editable(row: number, col: number): boolean {
    return (
      !this.readOnly() &&
      !this.saving() &&
      this.columns()[col]?.kind !== "locked" &&
      !this.blocked.has(this.rows()[row]?.id)
    );
  }
  private focus(): void {
    const { row, col } = this.active();
    this.element.nativeElement
      .querySelector<HTMLElement>(`[data-row="${row}"][data-col="${col}"]`)
      ?.focus({ preventScroll: true });
    this.element.nativeElement
      .querySelector<HTMLElement>(`[data-row="${row}"][data-col="${col}"]`)
      ?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }
  pick(row: number, col: number, extend = false): void {
    if (!this.commit()) return;
    this.active.set({ row, col });
    if (!extend) this.anchor.set({ row, col });
    this.focus();
  }
  begin(row: number, col: number, initial?: string): void {
    if (!this.editable(row, col) || !this.commit()) return;
    this.active.set({ row, col });
    this.anchor.set({ row, col });
    this.editValue =
      initial ?? this.value(this.rows()[row], this.columns()[col]);
    this.editing.set({ row, col });
    setTimeout(() => {
      const control =
        this.element.nativeElement.querySelector<HTMLInputElement>(
          ".cell-input",
        );
      control?.focus();
      if (initial === undefined && control?.type === "text") control.select();
    });
  }
  private normalize(raw: string, column: Column): string | null {
    if (column.kind === "locked")
      throw new Error(`${column.label}: columna protegida.`);
    let value = raw.trim();
    if (column.kind === "status") {
      const code = Object.keys(STATUS).find(
        (key) =>
          key.toLowerCase() === value.toLowerCase() ||
          STATUS[key].toLowerCase() === value.toLowerCase(),
      );
      if (!code) throw new Error("Estado: selecciona un valor del catálogo.");
      return code;
    }
    if (!value) return null;
    if (column.kind === "date") {
      const match = /^(\d{1,2})\/(\d{1,2})\/(\d{4})$/.exec(value);
      if (match)
        value = `${match[3]}-${match[2].padStart(2, "0")}-${match[1].padStart(2, "0")}`;
      const date = new Date(`${value}T00:00:00Z`);
      if (
        !/^\d{4}-\d{2}-\d{2}$/.test(value) ||
        Number.isNaN(date.getTime()) ||
        date.toISOString().slice(0, 10) !== value
      )
        throw new Error(`${column.label}: usa dd/mm/aaaa o aaaa-mm-dd.`);
    }
    if (column.kind === "supplier") {
      const matches = this.suppliers().filter(
        (s) =>
          s.is_active &&
          [s.id, s.code, s.legal_name].some(
            (v) => v.toLowerCase() === value.toLowerCase(),
          ),
      );
      if (matches.length !== 1)
        throw new Error(
          `${column.label}: selecciona un proveedor activo del catálogo.`,
        );
      return matches[0].id;
    }
    if (column.max && value.length > column.max)
      throw new Error(`${column.label}: máximo ${column.max} caracteres.`);
    return value;
  }
  private stage(cells: { row: number; col: number; value: string }[]): boolean {
    if (this.readOnly() || this.saving()) return false;
    try {
      // Validate the complete paste before staging any cell, so invalid ranges never apply partially.
      const prepared = cells.map((cell) => {
        if (!this.rows()[cell.row] || !this.columns()[cell.col])
          throw new Error(
            "El pegado excede las filas o columnas de esta página.",
          );
        if (!this.editable(cell.row, cell.col))
          throw new Error(
            `${this.columns()[cell.col].label}: celda de solo lectura.`,
          );
        return {
          ...cell,
          value: this.normalize(cell.value, this.columns()[cell.col]),
        };
      });
      const next: Changes = structuredClone(this.drafts());
      for (const cell of prepared) {
        const row = this.rows()[cell.row],
          key = this.columns()[cell.col].key;
        next[row.id] ??= {};
        if ((row[key] ?? null) === cell.value) delete next[row.id][key];
        else next[row.id][key] = cell.value;
        if (!Object.keys(next[row.id]).length) delete next[row.id];
      }
      if (JSON.stringify(next) !== JSON.stringify(this.drafts())) {
        this.history.push(structuredClone(this.drafts()));
        if (this.history.length > 100) this.history.shift();
        this.drafts.set(next);
      }
      this.error.set("");
      this.notice.set("");
      return true;
    } catch (error) {
      this.error.set(
        error instanceof Error
          ? error.message
          : "No se pudo aplicar el cambio.",
      );
      return false;
    }
  }
  commit(): boolean {
    const cell = this.editing();
    if (!cell) return true;
    if (
      this.editValue ===
      this.value(this.rows()[cell.row], this.columns()[cell.col])
    ) {
      this.editing.set(null);
      return true;
    }
    if (!this.stage([{ ...cell, value: this.editValue }])) return false;
    this.editing.set(null);
    return true;
  }
  editorKey(event: KeyboardEvent): void {
    event.stopPropagation();
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
      event.preventDefault();
      void this.save();
      return;
    }
    if (event.key === "Escape") {
      event.preventDefault();
      this.editing.set(null);
      this.error.set("");
      this.focus();
    }
    if (event.key === "Enter" || event.key === "Tab") {
      event.preventDefault();
      if (this.commit())
        this.move(
          event.key === "Enter" ? (event.shiftKey ? -1 : 1) : 0,
          event.key === "Tab" ? (event.shiftKey ? -1 : 1) : 0,
          false,
          event.key === "Tab",
        );
    }
  }
  private move(dr: number, dc: number, extend = false, wrap = false): void {
    let row = this.active().row + dr,
      col = this.active().col + dc;
    if (wrap && col >= this.columns().length) {
      col = 0;
      row++;
    }
    if (wrap && col < 0) {
      col = this.columns().length - 1;
      row--;
    }
    this.pick(
      Math.max(0, Math.min(this.rows().length - 1, row)),
      Math.max(0, Math.min(this.columns().length - 1, col)),
      extend,
    );
  }
  key(event: KeyboardEvent): void {
    if (event.target instanceof HTMLButtonElement) return;
    const command = event.ctrlKey || event.metaKey;
    if (command && event.key.toLowerCase() === "s") {
      event.preventDefault();
      void this.save();
      return;
    }
    if (command && event.key.toLowerCase() === "z") {
      event.preventDefault();
      this.undo();
      return;
    }
    const arrows: Record<string, number[]> = {
      ArrowUp: [-1, 0],
      ArrowDown: [1, 0],
      ArrowLeft: [0, -1],
      ArrowRight: [0, 1],
    };
    if (arrows[event.key]) {
      event.preventDefault();
      this.move(arrows[event.key][0], arrows[event.key][1], event.shiftKey);
      return;
    }
    if (event.key === "Tab") {
      event.preventDefault();
      this.move(0, event.shiftKey ? -1 : 1, false, true);
      return;
    }
    if (["Enter", "F2"].includes(event.key)) {
      event.preventDefault();
      this.begin(this.active().row, this.active().col);
      return;
    }
    if (["Delete", "Backspace"].includes(event.key)) {
      event.preventDefault();
      this.stage(this.range().map((cell) => ({ ...cell, value: "" })));
      return;
    }
    if (
      !command &&
      !event.altKey &&
      event.key.length === 1 &&
      this.columns()[this.active().col].kind === "text"
    ) {
      event.preventDefault();
      this.begin(this.active().row, this.active().col, event.key);
    }
  }
  private range(): Position[] {
    const a = this.anchor(),
      b = this.active(),
      cells: Position[] = [];
    for (let row = Math.min(a.row, b.row); row <= Math.max(a.row, b.row); row++)
      for (
        let col = Math.min(a.col, b.col);
        col <= Math.max(a.col, b.col);
        col++
      )
        cells.push({ row, col });
    return cells;
  }
  copy(event: ClipboardEvent): void {
    if (this.editing()) return;
    const a = this.anchor(),
      b = this.active(),
      lines: string[] = [];
    for (let r = Math.min(a.row, b.row); r <= Math.max(a.row, b.row); r++) {
      const values: string[] = [];
      for (let c = Math.min(a.col, b.col); c <= Math.max(a.col, b.col); c++)
        values.push(
          this.quote(this.display(this.rows()[r], this.columns()[c]), "\t"),
        );
      lines.push(values.join("\t"));
    }
    event.preventDefault();
    event.clipboardData?.setData("text/plain", lines.join("\r\n"));
  }
  paste(event: ClipboardEvent): void {
    if (this.readOnly() || this.saving() || this.editing()) return;
    event.preventDefault();
    const text = event.clipboardData?.getData("text/plain");
    if (!text) return;
    try {
      const matrix = this.parseClipboard(text);
      const start = this.active();
      const cells = matrix.flatMap((row, r) =>
        row.map((value, c) => ({
          row: start.row + r,
          col: start.col + c,
          value,
        })),
      );
      if (this.stage(cells)) {
        this.anchor.set(start);
        this.active.set({
          row: start.row + matrix.length - 1,
          col: start.col + matrix[0].length - 1,
        });
        this.notice.set(
          `${cells.length} celdas pegadas. Pendientes de guardar.`,
        );
        this.focus();
      }
    } catch (error) {
      this.error.set(
        error instanceof Error ? error.message : "Formato de pegado no válido.",
      );
    }
  }
  private parseClipboard(text: string): string[][] {
    const rows: string[][] = [];
    let row: string[] = [],
      value = "",
      quoted = false;
    const input = text.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
    if (input.length > 1000000)
      throw new Error("Pega un máximo de 1 MB por operación.");
    for (let i = 0; i < input.length; i++) {
      const ch = input[i];
      if (ch === '"' && (quoted || value === "")) {
        if (quoted && input[i + 1] === '"') {
          value += '"';
          i++;
        } else quoted = !quoted;
      } else if (!quoted && (ch === "\t" || ch === "\n")) {
        row.push(value);
        value = "";
        if (ch === "\n") {
          rows.push(row);
          row = [];
        }
      } else value += ch;
    }
    if (quoted)
      throw new Error("El texto pegado contiene comillas sin cerrar.");
    if (value || row.length || !input.endsWith("\n")) {
      row.push(value);
      rows.push(row);
    }
    if (!rows.length || rows.some((r) => r.length !== rows[0].length))
      throw new Error(
        "El rango pegado debe tener el mismo número de columnas en cada fila.",
      );
    return rows;
  }
  undo(): void {
    if (this.saving()) return;
    this.editing.set(null);
    const previous = this.history.pop();
    if (previous) this.drafts.set(previous);
    this.error.set("");
  }
  discard(): void {
    if (
      this.saving() ||
      !window.confirm("¿Descartar los cambios pendientes de esta hoja?")
    )
      return;
    this.clear();
  }
  private clear(): void {
    this.drafts.set({});
    this.history = [];
    this.editing.set(null);
    this.error.set("");
    this.notice.set("");
  }
  canLeave(): boolean {
    if (this.saving()) return false;
    if (
      (this.dirtyCount() || this.editing()) &&
      !window.confirm("Hay cambios sin guardar. ¿Descartarlos y continuar?")
    )
      return false;
    this.clear();
    return true;
  }
  @HostListener("window:beforeunload", ["$event"])
  beforeUnload(event: BeforeUnloadEvent): void {
    if (this.dirtyCount() || this.editing() || this.saving()) {
      event.preventDefault();
      event.returnValue = "";
    }
  }
  async save(): Promise<void> {
    if (
      this.readOnly() ||
      this.saving() ||
      !this.commit() ||
      !this.dirtyCount()
    )
      return;
    this.saving.set(true);
    this.error.set("");
    this.notice.set("");
    this.history = [];
    let saved = 0;
    for (const [id, patch] of Object.entries(this.drafts())) {
      if (this.blocked.has(id)) continue;
      const original = this.rows().find((row) => row.id === id)!;
      try {
        const row = await this.api.request<Shipment>(
          `/shipments/${id}`,
          "PATCH",
          { ...patch, expected_version: original.row_version },
        );
        this.updated.emit(row);
        this.drafts.update((items) => {
          const next = { ...items };
          delete next[id];
          return next;
        });
        this.issues.update((items) => {
          const next = { ...items };
          delete next[id];
          return next;
        });
        saved++;
      } catch (error) {
        const message =
          error instanceof ApiError && error.status === 0
            ? "Guardado sin confirmar. Recarga esta fila para comprobar su estado antes de volver a editar."
            : error instanceof Error
              ? error.message
              : "No se pudo guardar.";
        this.issues.update((items) => ({ ...items, [id]: message }));
        if (error instanceof ApiError && [0, 409].includes(error.status))
          this.blocked.add(id);
        this.error.set(`No se guardó ${original.reference_raw}: ${message}`);
        break;
      }
    }
    this.saving.set(false);
    if (saved)
      this.notice.set(
        `${saved} ${saved === 1 ? "fila guardada" : "filas guardadas"}.${this.dirtyCount() ? ` Quedan ${this.dirtyCount()} pendientes.` : ""}`,
      );
  }
  async reloadRow(row: Shipment): Promise<void> {
    if (
      this.saving() ||
      !this.commit() ||
      !window.confirm(
        "Se descartarán los cambios de esta fila para cargar la versión del servidor. ¿Continuar?",
      )
    )
      return;
    this.saving.set(true);
    try {
      const fresh = await this.api.request<Shipment>(`/shipments/${row.id}`);
      if (
        fresh.owner_id !== row.owner_id ||
        fresh.operation_code !== row.operation_code
      )
        throw new Error("La fila no pertenece a este master.");
      this.updated.emit(fresh);
      this.drafts.update((items) => {
        const next = { ...items };
        delete next[row.id];
        return next;
      });
      this.issues.update((items) => {
        const next = { ...items };
        delete next[row.id];
        return next;
      });
      this.blocked.delete(row.id);
      this.history = [];
      this.error.set("");
    } catch (error) {
      this.error.set(
        error instanceof Error ? error.message : "No se pudo recargar la fila.",
      );
    } finally {
      this.saving.set(false);
    }
  }
  private quote(value: string, separator: string): string {
    return value.includes(separator) || /[\r\n"]/.test(value)
      ? `"${value.replace(/"/g, '""')}"`
      : value;
  }
  exportPage(): void {
    if (!this.commit()) return;
    const safe = (value: string) =>
      this.quote(/^[=+@\-\t\r]/.test(value) ? "'" + value : value, ",");
    const lines = [
      this.columns()
        .map((c) => safe(c.label))
        .join(","),
      ...this.rows().map((row) =>
        this.columns()
          .map((c) => safe(this.display(row, c)))
          .join(","),
      ),
    ];
    const url = URL.createObjectURL(
      new Blob(["\uFEFF" + lines.join("\r\n")], {
        type: "text/csv;charset=utf-8",
      }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = `master-${this.operation()}-pagina-${this.offset() + 1}.csv`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
}
