// Catalog's API with the types generated from the contracts (CAT-36,
// contracts/catalog.openapi.json -> contracts/catalog.d.ts). Nothing here is typed by hand.
import type { components } from "../../../contracts/catalog";

type Schemas = components["schemas"];
export type CatalogVersion = Schemas["trainmeet.catalog-1.version"];
export type Session = Schemas["trainmeet.catalog-1.session"];
export type Account = Schemas["trainmeet.catalog-1.account"];
export type TrialLogin = Schemas["trainmeet.catalog-1.trial-login"];

export class ApiError extends Error {
  constructor(readonly status: number) {
    super(`Catalog svarade ${status}`);
  }
}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method, credentials: "same-origin", headers: { Accept: "application/json" } };
  if (body !== undefined) {
    init.headers = { ...init.headers, "Content-Type": "application/json" };
    init.body = JSON.stringify(body);
  }
  const response = await fetch(path, init);
  if (!response.ok) throw new ApiError(response.status);
  return (await response.json()) as T;
}

export const api = {
  version: () => call<CatalogVersion>("GET", "/api/version"),
  session: () => call<Session>("GET", "/api/catalog/1/session"),
  logOut: () => call<Session>("DELETE", "/api/catalog/1/session"),
  trialAccounts: () => call<Account[]>("GET", "/api/catalog/1/trial/accounts"),
  trialLogIn: (login: TrialLogin) => call<Session>("POST", "/api/catalog/1/trial/login", login),
};
