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
import { FormBuilder, FormControl, FormRecord, ReactiveFormsModule, Validators } from "@angular/forms";
import { masterValue } from "./master-layout";
import {
  Catalogs,
  EXCEL_OPERATION_LABELS,
  masterOperationValue,
  masterStatusValue,
  supplierValues,
  DEPARTMENTS,
  Identifier,
  OPERATIONS,
  PROCESSES,
  Shipment,
  STATUS,
  Supplier,
  MasterField,
  MasterLayout,
  MasterData,
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
  masterOwnerName = input.required<string>();
  suppliers = input<Supplier[]>([]);
  shipment = input<Shipment | null>(null);
  layout = input<MasterLayout | null>(null);
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
  excelOperations = EXCEL_OPERATION_LABELS;
  operations = OPERATIONS;
  processes = PROCESSES;
  departments = DEPARTMENTS;
  statusCodes = Object.keys(STATUS);
  unitCodes = computed(() => Object.keys(this.catalogs().business_units));
  profileSections = computed(() => {
    const fields = this.layout()?.fields ?? [];
    return [...new Set(fields.map(field => field.section || "Datos del master"))].map(name => ({
      name, fields: fields.filter(field => (field.section || "Datos del master") === name),
    }));
  });
  profileControls = new FormRecord<FormControl<string>>({});
  submitted = false;
  private fb = new FormBuilder().nonNullable;
  form = this.fb.group({
    reference_raw: ["", Validators.maxLength(160)],
    company_code: ["", [Validators.required, Validators.maxLength(32), Validators.pattern(/.*\S.*/)]],
    process_code: ["RM", Validators.required],
    operation_code: ["LI", [Validators.required, Validators.maxLength(100)]],
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
    department_code: [""],
    status: ["DRAFT", Validators.maxLength(100)],
    ship_date: [""],
    eta: [""],
    delivery_date: [""],
    sender: ["", Validators.maxLength(250)],
    origin: ["", Validators.maxLength(150)],
    consignee: ["", Validators.maxLength(250)],
    destination: ["", Validators.maxLength(150)],
    carrier_broker_id: ["", Validators.maxLength(250)],
    shipping_line_id: ["", Validators.maxLength(250)],
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
      for (const prefix of ["carrier_broker", "shipping_line"] as const) {
        const id = row[prefix === "carrier_broker" ? "carrier_broker_id" : "shipping_line_id"];
        const manual = row[prefix === "carrier_broker" ? "carrier_broker_name" : "shipping_line_name"];
        values[prefix + "_id"] = manual || this.suppliers().find(s => s.id === id)?.legal_name || id || "";
      }
      values["status"] = STATUS[row.status] ?? row.status;
      values["operation_code"] = OPERATIONS[row.operation_code ?? ""] ?? row.operation_code ?? "";
      this.form.patchValue(values);
      for (const key of ["process_code", "operation_code", "business_unit", "department_code", "reference_year"] as const) {
        this.form.controls[key].removeValidators(Validators.required);
        this.form.controls[key].updateValueAndValidity();
      }
    } else
      this.form.patchValue({ company_code: "", operation_code: "" });
    for (const field of this.layout()?.fields ?? []) {
      if (!field.key.startsWith("master.")) continue;
      const initial = row ? masterValue(row, field.key, this.masterOwnerName()) : field.key === "master.owner" ? this.masterOwnerName() : "";
      this.profileControls.addControl(field.key.slice(7), new FormControl(initial, {
        nonNullable: true, validators: [Validators.maxLength(field.max ?? 10000)],
      }));
    }
    if (this.readOnly()) { this.form.disable(); this.profileControls.disable(); }
  }
  ngAfterViewInit(): void {
    this.dialog.nativeElement.showModal();
  }
  get operation(): string {
    return masterOperationValue(this.form.controls.operation_code.value);
  }
  get sea(): boolean {
    return ["SI", "SE", "SEA IMPO", "SEA EXPO"].includes(this.operation.toUpperCase());
  }
  get compliance(): boolean {
    return ["VI", "VE", "A3", "F4", "F5", "R1"].includes(this.operation);
  }
  get invalid(): boolean {
    return this.submitted && (this.form.invalid || this.profileControls.invalid);
  }
  fieldControl(field: MasterField): FormControl<string> {
    return (field.key.startsWith("master.") ? this.profileControls.get(field.key.slice(7)) : this.form.get(field.key)) as FormControl<string>;
  }
  fieldRequired(field: MasterField): boolean {
    return !!field.required || (!this.shipment() && ["business_unit", "operation_code"].includes(field.key));
  }
  fieldList(field: MasterField): string | null {
    return ({ operation: "shipment-operation-options", status: "shipment-status-options", supplier: "shipment-supplier-options" } as Record<string, string>)[field.kind] ?? null;
  }
  acceptSaved(row: Shipment): void {
    this.form.patchValue({ reference_raw: row.reference_raw ?? "" });
    for (const field of this.layout()?.fields ?? []) {
      if (field.key.startsWith("master.")) this.fieldControl(field).setValue(masterValue(row, field.key, this.masterOwnerName()));
    }
    for (const key of ["process_code", "operation_code", "business_unit", "department_code", "reference_year"] as const) {
      this.form.controls[key].removeValidators(Validators.required);
      this.form.controls[key].updateValueAndValidity();
    }
    this.form.markAsPristine();
    this.profileControls.markAsPristine();
  }
  close(): void {
    if (this.busy()) return;
    if (
      (this.form.dirty || this.profileControls.dirty) &&
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
    if (this.form.invalid || this.profileControls.invalid) {
      this.form.markAllAsTouched();
      this.profileControls.markAllAsTouched();
      return;
    }
    if (this.layout()) { this.submitProfile(); return; }
    const values = this.form.getRawValue();
    if (
      values.expedited_status === "APPROVED" &&
      !values.pfa_approval_code.trim()
    ) {
      this.form.controls.pfa_approval_code.setErrors({ required: true });
      return;
    }
    const data: Record<string, unknown> = { ...values, company_code: values.company_code.trim(), operation_code: masterOperationValue(values.operation_code), status: masterStatusValue(values.status) };
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
      "reference_raw",
      "department_code",
    ]) {
      data[key] =
        typeof data[key] === "string"
          ? (data[key] as string).trim() || null
          : data[key];
    }
    if (values.expedited_status !== "APPROVED")
      data["pfa_approval_code"] = null;
    if (this.shipment()) {
      for (const key of Object.keys(data)) {
        const control = this.form.get(key);
        const dependentApproval = key === "pfa_approval_code" && this.form.controls.expedited_status.dirty;
        if (!control?.dirty && !dependentApproval) delete data[key];
      }
      if (data["reference_year"] === "") data["reference_year"] = null;
      for (const key of ["process_code", "operation_code", "business_unit", "department_code"])
        if (data[key] === "") data[key] = null;
      data["expected_version"] = this.shipment()!.row_version;
    } else {
      for (const key of [
        "damaged_material",
        "expedited_status",
        "pfa_approval_code",
        "reference_raw",
      ])
        delete data[key];
    }
    for (const prefix of ["carrier_broker", "shipping_line"] as const) {
      const key = prefix + "_id";
      if (key in data) Object.assign(data, supplierValues(data[key] as string | null, prefix, this.suppliers()));
    }
    this.saved.emit(data);
  }
  private submitProfile(): void {
    const data: Record<string, unknown> = {}, master: MasterData = {};
    for (const field of this.layout()!.fields) {
      const control = this.fieldControl(field);
      if (this.shipment() && !control.dirty) continue;
      let value: string | null = control.value.trim() || null;
      if (field.key.startsWith("master.")) {
        if (this.shipment() || value !== null) master[field.key.slice(7)] = value;
      } else if (field.key === "reference_raw") {
        if (this.shipment() || value !== null) data[field.key] = value;
      } else {
        if (field.key === "operation_code") value = value ? masterOperationValue(value) : null;
        if (field.key === "status") value = masterStatusValue(value ?? "");
        data[field.key] = value;
      }
    }
    if (Object.keys(master).length) data["master_data"] = master;
    for (const key of ["process_code", "reference_year", "department_code", "plant_code", "damaged_material", "expedited_status", "pfa_approval_code"] as const) {
      const control = this.form.controls[key];
      if (this.shipment() ? control.dirty : ["process_code", "reference_year", "department_code"].includes(key)) data[key] = typeof control.value === "boolean" ? control.value : control.value || null;
    }
    if (data["expedited_status"] && data["expedited_status"] !== "APPROVED") data["pfa_approval_code"] = null;
    if (data["expedited_status"] === "APPROVED") data["pfa_approval_code"] = this.form.controls.pfa_approval_code.value.trim() || null;
    for (const prefix of ["carrier_broker", "shipping_line"] as const) {
      const key = prefix + "_id";
      if (key in data) Object.assign(data, supplierValues(data[key] as string | null, prefix, this.suppliers()));
    }
    if (this.shipment()) data["expected_version"] = this.shipment()!.row_version;
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
