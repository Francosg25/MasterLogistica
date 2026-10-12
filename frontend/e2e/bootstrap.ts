// Only the explicitly selected E2E build imports this provider. Production uses src/main.ts.
import { registerLocaleData } from "@angular/common";
import localeEs from "@angular/common/locales/es-MX";
import { bootstrapApplication } from "@angular/platform-browser";
import { AppComponent } from "../src/app/app.component";
import { AuthService } from "../src/app/auth.service";
registerLocaleData(localeEs);
bootstrapApplication(AppComponent, {
  providers: [
    {
      provide: AuthService,
      useValue: {
        configured: true,
        initialize: async () => true,
        token: async () => "synthetic-e2e-token",
        login: async () => {},
        logout: async () => {},
      },
    },
  ],
}).catch(console.error);
