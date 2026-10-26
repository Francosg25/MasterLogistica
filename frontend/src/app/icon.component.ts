import { Component, input } from "@angular/core";

export type IconName = "home" | "grid" | "wallet" | "document" | "history" | "arrow" | "plus" | "filter" | "expand" | "save" | "undo" | "download" | "upload" | "sign-out" | "keyboard" | "search";

// Small, local SVGs keep controls sharp at every scale without loading a font.
@Component({
  selector: "app-icon",
  standalone: true,
  host: { "aria-hidden": "true" },
  template: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round" focusable="false" aria-hidden="true"><path [attr.d]="paths[name()]" /></svg>`,
})
export class IconComponent {
  name = input<IconName>("grid");
  readonly paths: Record<IconName, string> = {
    home: "m3 10 9-7 9 7M5 9v11h5v-6h4v6h5V9",
    grid: "M4 4h16v16H4zM4 9h16M4 14h16M10 4v16",
    wallet: "M4 6h14a2 2 0 0 1 2 2v11H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h13v2M20 11h-5v5h5M16 13.5h.01",
    document: "M14 3H5v18h14V8l-5-5v5h5M8 12h8M8 16h6",
    history: "M3 10a9 9 0 1 1 2 8M3 4v6h6M12 7v5l3 2",
    arrow: "M5 12h14m-5-5 5 5-5 5",
    plus: "M12 5v14M5 12h14",
    filter: "M4 7h16M7 12h10M10 17h4",
    expand: "M9 4H4v5M15 4h5v5M20 15v5h-5M4 15v5h5",
    save: "M5 3h13l3 3v15H3V3h2M7 3v6h10V3M7 21v-8h10v8",
    undo: "m8 4-5 5 5 5M3 9h11a6 6 0 0 1 0 12",
    download: "M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5",
    upload: "M12 16V4m-5 5 5-5 5 5M4 16v5h16v-5",
    "sign-out": "M10 4H4v16h6M10 12h11m-5-5 5 5-5 5",
    keyboard: "M3 6h18v13H3zM7 10h.01M11 10h.01M15 10h.01M18 10h.01M7 14h.01M10 15h7",
    search: "M10.5 3a7.5 7.5 0 1 0 0 15 7.5 7.5 0 0 0 0-15m5.5 13 5 5",
  };
}
