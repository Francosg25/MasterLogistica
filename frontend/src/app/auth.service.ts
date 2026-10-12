import { Injectable } from "@angular/core";
import {
  InteractionRequiredAuthError,
  PublicClientApplication,
} from "@azure/msal-browser";
import { AuthConfig } from "./types";

@Injectable({ providedIn: "root" })
export class AuthService {
  private client: PublicClientApplication | null = null;
  private scope = "";
  config: AuthConfig | null = null;

  async initialize(): Promise<boolean> {
    const response = await fetch("/api/v1/auth/config", { cache: "no-store" });
    if (!response.ok)
      throw new Error("No se pudo conectar con el servicio de acceso.");
    this.config = (await response.json()) as AuthConfig;
    const { enabled, authority, frontend_client_id, scope } = this.config;
    if (!enabled || !authority || !frontend_client_id || !scope) return false;
    this.scope = scope;
    this.client = new PublicClientApplication({
      auth: {
        clientId: frontend_client_id,
        authority,
        redirectUri: window.location.origin + "/",
        postLogoutRedirectUri: window.location.origin + "/",
        navigateToLoginRequestUrl: false,
      },
      cache: { cacheLocation: "sessionStorage" },
    });
    await this.client.initialize();
    const result = await this.client.handleRedirectPromise();
    const accounts = this.client.getAllAccounts();
    // Do not silently select another identity if several accounts remain in the cache.
    this.client.setActiveAccount(
      result?.account ??
        this.client.getActiveAccount() ??
        (accounts.length === 1 ? accounts[0] : null),
    );
    return !!this.client.getActiveAccount();
  }

  get configured(): boolean {
    return !!this.client;
  }
  async login(): Promise<void> {
    if (!this.client)
      throw new Error("Microsoft Entra ID aún no está configurado.");
    await this.client.loginRedirect({
      scopes: [this.scope],
      prompt: "select_account",
    });
  }
  async token(): Promise<string> {
    const account = this.client?.getActiveAccount();
    if (!this.client || !account)
      throw new Error("Inicia sesión para continuar.");
    try {
      return (
        await this.client.acquireTokenSilent({ account, scopes: [this.scope] })
      ).accessToken;
    } catch (error) {
      if (error instanceof InteractionRequiredAuthError) {
        await this.client.acquireTokenRedirect({
          account,
          scopes: [this.scope],
        });
        throw new Error("Renovando tu sesión…");
      }
      throw new Error("No se pudo renovar tu sesión. Vuelve a iniciar sesión.");
    }
  }
  async logout(): Promise<void> {
    await this.client?.logoutRedirect({
      account: this.client.getActiveAccount(),
    });
  }
}
