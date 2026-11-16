// The screen's API in the hub, with the types generated from the contracts (contracts/screen.py
// -> contracts/openapi.json -> contracts/types.d.ts). Nothing here is typed by hand.
import type { components } from "../../../contracts/types";

type Schemas = components["schemas"];
export type ScreenPicture = Schemas["trainmeet.screen-1.picture"];
export type ScreenLogin = Schemas["trainmeet.screen-1.login"];
export type ScreenSession = Schemas["trainmeet.screen-1.session"];
export type Package = Schemas["trainmeet.meet-1"];

/** The key lives in sessionStorage and goes as Authorization: Bearer, never in the address. */
export const STORE = "trainmeet-skarm";

export function savedKey(): string | null {
  try {
    return sessionStorage.getItem(STORE);
  } catch {
    return null;
  }
}

export function saveKey(key: string | null): void {
  try {
    if (key) sessionStorage.setItem(STORE, key);
    else sessionStorage.removeItem(STORE);
  } catch {
    // Private browsing without storage: the screen joins again after a reload.
  }
}

/** What the hub said: the picture, that the key is no longer known, or nothing (out of reach). */
export type Fetched = { picture: ScreenPicture } | { gone: true } | null;

export async function fetchPicture(key: string): Promise<Fetched> {
  const response = await fetch("/api/screen/picture", { headers: { Authorization: `Bearer ${key}` } }).catch(() => null);
  if (!response) return null;
  if (response.status === 401) return { gone: true };
  if (!response.ok) return null;
  return { picture: (await response.json()) as ScreenPicture };
}

/** Join with the meet's code: the key, or what the hub said went wrong. */
export async function join(login: ScreenLogin): Promise<{ key: string } | { problem: string }> {
  const response = await fetch("/api/screen/session", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(login),
  }).catch(() => null);
  if (!response) return { problem: "Hubben svarar inte." };
  const answer = (await response.json().catch(() => ({}))) as Partial<ScreenSession> & { detail?: unknown };
  if (!response.ok || !answer.session_key) return { problem: typeof answer.detail === "string" ? answer.detail : "Det gick inte." };
  return { key: answer.session_key };
}

/** The package the views draw on, fetched once and again when the picture's key changes. */
export async function fetchPackage(key: string): Promise<Package | null> {
  const response = await fetch("/api/screen/package", { headers: { Authorization: `Bearer ${key}` } }).catch(() => null);
  if (!response?.ok) return null;
  return (await response.json()) as Package;
}
