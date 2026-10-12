import { registerLocaleData } from "@angular/common";
import localeEs from "@angular/common/locales/es-MX";
registerLocaleData(localeEs);
import { bootstrapApplication } from "@angular/platform-browser";
import { AppComponent } from "./app/app.component";
bootstrapApplication(AppComponent).catch(() => {
  document.body.textContent =
    "No se pudo iniciar MasterLogistica. Recarga la página.";
});
