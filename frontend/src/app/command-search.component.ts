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
import { IconComponent } from "./icon.component";
interface Result {
  id: string;
  reference: string;
  company_code: string;
  owner_name?: string;
  business_unit?: string;
}
@Component({
  selector: "command-search",
  standalone: true,
  imports: [IconComponent],
  template: ` <dialog
    #dialog
    class="command-dialog"
    aria-labelledby="command-title"
    (cancel)="$event.preventDefault(); closed.emit()"
  >
    <div class="command-head">
      <app-icon name="search" />
      <h2 id="command-title" class="sr-only">Buscar referencia</h2>
      <input
        #input
        aria-label="Buscar referencia en todos los masters"
        placeholder="Escribe una referencia…"
        autocomplete="off"
        maxlength="160"
        (input)="search(input.value)"
        (keydown)="key($event)"
      /><button class="button subtle" (click)="closed.emit()">Cerrar</button>
    </div>
    <div
      class="command-results"
      role="listbox"
      aria-label="Resultados de referencias"
      [attr.aria-busy]="loading()"
    >
      @if (loading()) {
        <p role="status">Buscando referencias…</p>
      } @else if (error()) {
        <p class="error" role="alert">{{ error() }}</p>
      } @else {
        @for (row of results(); track row.id; let i = $index) {
          <button
            role="option"
            [attr.aria-selected]="active() === i"
            [class.current]="active() === i"
            (click)="selected.emit(row)"
          >
            <app-icon name="document" /><span
              ><strong>{{ row.reference }}</strong
              ><small
                >{{ row.owner_name || row.company_code }} ·
                {{ row.business_unit || row.company_code }}</small
              ></span
            ><app-icon name="arrow" />
          </button>
        } @empty {
          <div class="command-empty">
            <app-icon name="search" />
            <p>No hay referencias para esta búsqueda.</p>
            <small
              >Busca la referencia actual o una referencia anterior
              registrada.</small
            >
          </div>
        }
      }
    </div>
    <footer>
      <span>↑ ↓ navegar</span><span>Enter abrir</span><span>Esc cerrar</span>
    </footer>
  </dialog>`,
})
export class CommandSearchComponent implements AfterViewInit, OnDestroy {
  @Input() demo = false;
  @Output() selected = new EventEmitter<Result>();
  @Output() closed = new EventEmitter<void>();
  @ViewChild("dialog") dialog!: ElementRef<HTMLDialogElement>;
  @ViewChild("input") input!: ElementRef<HTMLInputElement>;
  private api = inject(ApiService);
  private controller?: AbortController;
  private timer?: ReturnType<typeof setTimeout>;
  private generation = 0;
  results = signal<Result[]>([]);
  error = signal("");
  loading = signal(false);
  active = signal(0);
  ngAfterViewInit() {
    this.dialog.nativeElement.showModal();
    this.input.nativeElement.focus();
    this.search("");
  }
  ngOnDestroy() {
    clearTimeout(this.timer);
    this.controller?.abort();
    this.generation++;
  }
  search(query: string) {
    clearTimeout(this.timer);
    this.controller?.abort();
    const generation = ++this.generation;
    this.loading.set(true);
    this.timer = setTimeout(() => void this.load(query, generation), 160);
  }
  private async load(query: string, generation: number) {
    this.controller = new AbortController();
    this.error.set("");
    try {
      let rows: Result[];
      if (this.demo) {
        const d = await import("./demo");
        rows = d.masterDemoShipments
          .filter((s) =>
            (s.reference_raw ?? "")
              .toUpperCase()
              .includes(query.trim().toUpperCase()),
          )
          .slice(0, 30)
          .map((s) => ({
            id: s.id,
            reference: s.reference_raw ?? "",
            company_code: s.company_code,
            business_unit: s.business_unit ?? "",
            owner_name: d.demoOwners.find((o) => o.id === s.owner_id)
              ?.display_name,
          }));
      } else
        rows = await this.api.request<Result[]>(
          `/finance/references?q=${encodeURIComponent(query)}`,
          "GET",
          undefined,
          this.controller.signal,
        );
      if (generation === this.generation) {
        this.results.set(rows);
        this.active.set(0);
      }
    } catch (e) {
      if (generation === this.generation && !this.controller.signal.aborted)
        this.error.set(e instanceof Error ? e.message : "No se pudo buscar.");
    } finally {
      if (generation === this.generation) this.loading.set(false);
    }
  }
  key(event: KeyboardEvent) {
    const rows = this.results();
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      this.active.set(
        rows.length
          ? (this.active() +
              (event.key === "ArrowDown" ? 1 : -1) +
              rows.length) %
              rows.length
          : 0,
      );
    }
    if (event.key === "Enter" && !this.loading() && rows[this.active()]) {
      event.preventDefault();
      this.selected.emit(rows[this.active()]);
    }
  }
}
