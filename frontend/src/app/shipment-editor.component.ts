import {
  AfterViewInit,
  OnInit,
  Component,
  ElementRef,
  ViewChild,
  computed,
  input,
  output,
} from "@angular/core";
import { FormBuilder, ReactiveFormsModule, Validators } from "@angular/forms";
import {
  Catalogs,
  DEPARTMENTS,
  Identifier,
  OPERATIONS,
  PROCESSES,
  Shipment,
  STATUS,
  Supplier,
} from "./types";

@Component({
  selector: "shipment-editor",
  standalone: true,
  imports: [ReactiveFormsModule],
  templateUrl: "./shipment-editor.component.html",
})
export class ShipmentEditorComponent implements AfterViewInit, OnInit {
  @ViewChild("dialog") dialog!: ElementRef<HTMLDialogElement>;
  catalogs = input.required<Catalogs>();
  masterOperation = input.required<string>();
  masterOwnerName = input.required<string>();
  suppliers = input<Supplier[]>([]);
  shipment = input<Shipment | null>(null);
  identifiers = input<Identifier[]>([]);
  readOnly = input(false);
  busy = input(false);
  error = input("");
  conflict = input(false);
  identifierError = input("");
  identifiersLoading = input(false);
  closed = output<void>();
  saved = output<Record<string, unknown>>();
  reload = output<void>();
  addIdentifier = output<{ kind: string; raw_value: string }>();
  status = STATUS;
  operations = OPERATIONS;
  processes = PROCESSES;
  departments = DEPARTMENTS;
  statusCodes = Object.keys(STATUS);
  unitCodes = computed(() => Object.keys(this.catalogs().business_units));
  submitted = false;
  private fb = new FormBuilder().nonNullable;
  form = this.fb.group({
    company_code: ["", Validators.required],
    process_code: ["RM", Validators.required],
    operation_code: ["LI", Validators.required],
    reference_year: [
      new Date().getFullYear(),
      [
        Validators.required,
        Validators.min(2000),
        Validators.max(2099),
        Validators.pattern(/^\d{4}$/),
      ],
    ],
    business_unit: ["", Validators.required],
    department_code: ["MAT", Validators.required],
    status: ["DRAFT", Validators.required],
    ship_date: [""],
    eta: [""],
    delivery_date: [""],
    sender: ["", Validators.maxLength(250)],
    origin: ["", Validators.maxLength(150)],
    consignee: ["", Validators.maxLength(250)],
    destination: ["", Validators.maxLength(150)],
    carrier_broker_id: [""],
    shipping_line_id: [""],
    plant_code: ["", Validators.maxLength(32)],
    comments: ["", Validators.maxLength(10000)],
    damaged_material: [false],
    expedited_status: ["NONE"],
    pfa_approval_code: ["", Validators.pattern(/^CS[0-9]{1,32}$/)],
  });
  identifierForm = this.fb.group({
    kind: ["PEDIMENTO", Validators.required],
    raw_value: ["", [Validators.required, Validators.maxLength(200)]],
  });
  ngOnInit(): void {
    const row = this.shipment();
    if (row) {
      const values = Object.fromEntries(
        Object.keys(this.form.controls).map((key) => [
          key,
          row[key as keyof Shipment] ??
            (key === "damaged_material" ? false : ""),
        ]),
      );
      this.form.patchValue(values);
    } else
      this.form.patchValue({
        company_code: this.catalogs().company_codes[0] ?? "",
        operation_code: this.masterOperation(),
      });
    if (this.readOnly()) this.form.disable();
  }
  ngAfterViewInit(): void {
    this.dialog.nativeElement.showModal();
  }
  get operation(): string {
    return this.form.controls.operation_code.value;
  }
  get sea(): boolean {
    return ["SI", "SE"].includes(this.operation);
  }
  get compliance(): boolean {
    return ["VI", "VE", "A3", "F4", "F5", "R1"].includes(this.operation);
  }
  get invalid(): boolean {
    return this.submitted && this.form.invalid;
  }
  close(): void {
    if (this.busy()) return;
    if (
      this.form.dirty &&
      !this.readOnly() &&
      !window.confirm("¿Descartar los cambios sin guardar?")
    )
      return;
    this.closed.emit();
  }
  reloadRecord(): void {
    if (
      window.confirm(
        "Se descartarán tus cambios para cargar la versión actual. ¿Continuar?",
      )
    )
      this.reload.emit();
  }
  submit(): void {
    this.submitted = true;
    if (this.readOnly() || this.busy() || this.conflict()) return;
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }
    const values = this.form.getRawValue();
    if (
      values.expedited_status === "APPROVED" &&
      !values.pfa_approval_code.trim()
    ) {
      this.form.controls.pfa_approval_code.setErrors({ required: true });
      return;
    }
    const data: Record<string, unknown> = { ...values };
    for (const key of [
      "sender",
      "origin",
      "consignee",
      "destination",
      "plant_code",
      "comments",
      "carrier_broker_id",
      "shipping_line_id",
      "ship_date",
      "eta",
      "delivery_date",
      "pfa_approval_code",
    ]) {
      data[key] =
        typeof data[key] === "string"
          ? (data[key] as string).trim() || null
          : data[key];
    }
    if (values.expedited_status !== "APPROVED")
      data["pfa_approval_code"] = null;
    if (this.shipment()) {
      for (const key of [
        "company_code",
        "process_code",
        "operation_code",
        "reference_year",
        "business_unit",
        "department_code",
      ])
        delete data[key];
      data["expected_version"] = this.shipment()!.row_version;
    } else {
      for (const key of [
        "damaged_material",
        "expedited_status",
        "pfa_approval_code",
      ])
        delete data[key];
      if (!this.sea) data["shipping_line_id"] = null;
    }
    this.saved.emit(data);
  }
  submitIdentifier(): void {
    if (this.readOnly() || this.busy()) return;
    if (
      this.identifierForm.invalid ||
      !this.identifierForm.controls.raw_value.value.trim()
    ) {
      this.identifierForm.markAllAsTouched();
      return;
    }
    this.addIdentifier.emit(this.identifierForm.getRawValue());
  }
  resetApproval(): void {
    if (this.form.controls.expedited_status.value !== "APPROVED")
      this.form.controls.pfa_approval_code.reset("");
  }
  clearIdentifier(): void {
    this.identifierForm.controls.raw_value.reset();
  }
}
