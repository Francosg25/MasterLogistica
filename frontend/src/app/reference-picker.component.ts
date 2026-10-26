import { Component, ElementRef, OnChanges, OnDestroy, SimpleChanges, inject, input, signal } from "@angular/core";
import { FormControl, ReactiveFormsModule } from "@angular/forms";
import { ApiService } from "./api.service";
import { IconComponent } from "./icon.component";

interface ReferenceOption {
  id: string;
  reference: string;
  company_code: string;
  owner_name?: string;
  business_unit?: string;
}

let nextPicker = 0;

@Component({
  selector: "reference-picker",
  standalone: true,
  imports: [ReactiveFormsModule, IconComponent],
  host: { class: "reference-picker", "(focusout)": "blur($event)" },
  template: `
    <label [for]="id">{{ label() }}</label>
    <div class="reference-input-wrap">
      <app-icon name="search" />
      <input [id]="id" [formControl]="control()" role="combobox" aria-autocomplete="list"
        [attr.aria-controls]="id + '-options'" [attr.aria-expanded]="open()"
        [attr.aria-activedescendant]="open() && active() >= 0 ? id + '-option-' + active() : null"
        [attr.aria-describedby]="control().value ? id + '-current' : null"
        autocomplete="off" required maxlength="160" placeholder="Busca o selecciona una referencia"
        (focus)="search(true)" (input)="search()" (keydown)="key($event)" />
    </div>
    @if (control().value) {
      <div class="reference-current" [id]="id + '-current'">
        <strong>{{ control().value }}</strong>
        @if (selected(); as reference) { <small>{{ details(reference) }}</small> }
      </div>
    }
    @if (open()) {
      <div class="reference-options" [id]="id + '-options'" role="listbox" aria-label="Referencias disponibles" [attr.aria-busy]="loading()">
        @if (loading()) { <p role="status">Buscando referencias…</p> }
        @else if (error()) { <p role="alert">{{ error() }}</p> }
        @else {
          @for (reference of options(); track reference.id; let i = $index) {
            <button type="button" role="option" tabindex="-1" [id]="id + '-option-' + i"
              [attr.aria-selected]="active() === i" (pointerdown)="$event.preventDefault()" (click)="select(reference)">
              <strong>{{ reference.reference }}</strong><small>{{ details(reference) }}</small>
            </button>
          } @empty { <p>No hay referencias para esta búsqueda{{ companyCode() ? ' en la empresa seleccionada' : '' }}.</p> }
          @if (options().length >= 30) { <p>Se muestran 30 coincidencias. Escribe más para precisar la búsqueda.</p> }
        }
      </div>
    }
  `,
})
export class ReferencePickerComponent implements OnChanges, OnDestroy {
  control = input.required<FormControl<string>>();
  label = input("Referencia del master");
  companyCode = input("");
  readonly id = "reference-picker-" + ++nextPicker;
  private api = inject(ApiService);
  private element = inject<ElementRef<HTMLElement>>(ElementRef);
  options = signal<ReferenceOption[]>([]);
  selected = signal<ReferenceOption | null>(null);
  open = signal(false);
  loading = signal(false);
  error = signal("");
  active = signal(-1);
  private generation = 0;
  private timer?: ReturnType<typeof setTimeout>;
  private controller?: AbortController;
  private frame = 0;

  ngOnChanges(changes: SimpleChanges) {
    if (changes["companyCode"] && !changes["companyCode"].firstChange) {
      this.cancel();
      this.options.set([]);
      this.selected.set(null);
      this.active.set(-1);
      if (this.open()) this.search(true);
    }
  }
  ngOnDestroy() { this.cancel(); cancelAnimationFrame(this.frame); }
  private cancel() {
    clearTimeout(this.timer);
    this.controller?.abort();
    this.generation++;
    this.loading.set(false);
  }
  search(immediate = false) {
    this.cancel();
    this.options.set([]);
    this.active.set(-1);
    this.error.set("");
    if (!immediate) this.selected.set(null);
    this.open.set(true);
    this.loading.set(true);
    if (immediate) void this.lookup();
    else this.timer = setTimeout(() => void this.lookup(), 180);
  }
  private async lookup() {
    const generation = ++this.generation;
    const controller = new AbortController();
    this.controller = controller;
    const query = new URLSearchParams({ q: this.control().value.trim() });
    if (this.companyCode()) query.set("company_code", this.companyCode());
    try {
      const references = await this.api.request<ReferenceOption[]>("/finance/references?" + query, "GET", undefined, controller.signal);
      if (generation === this.generation) this.options.set(references);
    } catch {
      if (generation === this.generation && !controller.signal.aborted)
        this.error.set("No se pudieron cargar las referencias. Vuelve a buscar.");
    } finally {
      if (generation === this.generation) this.loading.set(false);
    }
  }
  details(reference: ReferenceOption) {
    return [reference.owner_name, reference.business_unit, reference.company_code].filter(Boolean).join(" · ");
  }
  select(reference: ReferenceOption) {
    this.control().setValue(reference.reference);
    this.control().markAsDirty();
    this.selected.set(reference);
    this.close();
  }
  close() { this.open.set(false); this.active.set(-1); this.cancel(); }
  blur(event: FocusEvent) {
    if (!(event.currentTarget as HTMLElement).contains(event.relatedTarget as Node | null)) this.close();
  }
  key(event: KeyboardEvent) {
    if (event.key === "Escape") { event.preventDefault(); this.close(); }
    else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (!this.open()) { this.search(true); return; }
      const count = this.options().length;
      if (count) {
        this.active.set((this.active() + (event.key === "ArrowDown" ? 1 : -1) + count) % count);
        cancelAnimationFrame(this.frame);
        this.frame = requestAnimationFrame(() => this.element.nativeElement.querySelector<HTMLElement>("[aria-selected='true']")?.scrollIntoView({ block: "nearest" }));
      }
    } else if (event.key === "Enter" && this.open()) {
      event.preventDefault();
      const reference = this.options()[this.active()];
      if (reference) this.select(reference);
    }
  }
}
