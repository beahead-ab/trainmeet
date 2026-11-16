// The hub's API behind the header: Den här hubben (contracts/hub.py), Nu and the clients from
// Driftens API (contracts/drift.py), and the meets from Planering, with the types generated
// from the contracts. Nothing here is typed by hand. The session is an HttpOnly cookie the
// pages never see; without it a page only looks (S1).
import type { components } from "../../../contracts/types";

type Schemas = components["schemas"];
export type HubInfo = Schemas["trainmeet.hub-1.info"];
export type Version = Schemas["trainmeet.hub-1.version"];
export type AiService = Schemas["trainmeet.hub-1.ai-service"];
export type AiServiceChange = Schemas["trainmeet.hub-1.ai-service-change"];
export type Now = Schemas["trainmeet.drift-1.now"];
export type Weekday = Schemas["trainmeet.drift-1.now.Weekday"];
export type Client = Schemas["trainmeet.drift-1.client"];
export type DriftEvent = Schemas["trainmeet.drift-1.event"];
export type Joining = Schemas["trainmeet.drift-1.joining"];
export type MeetSummary = Schemas["trainmeet.planning-1.meet-summary"];
export type StartMeet = Schemas["trainmeet.drift-1.start"];

export const DRIFT = "/api/drift/1";

/** What the hub said no to, in its own words, or that it could not be reached (status 0). */
export class Problem extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

const detail = (answer: unknown, otherwise: string) => {
  const said = (answer as { detail?: unknown } | null)?.detail;
  return typeof said === "string" ? said : otherwise;
};

/** One call to the hub: GET without a body, POST with one; a no becomes a Problem. */
export async function call<T>(path: string, body?: unknown): Promise<T> {
  const sending = body !== undefined;
  const response = await fetch(path, {
    method: sending ? "POST" : "GET",
    headers: sending ? { "Content-Type": "application/json" } : {},
    body: sending ? JSON.stringify(body) : undefined,
    credentials: "same-origin",
    cache: "no-store",
  }).catch(() => null);
  if (!response) throw new Problem("Kontakten med Hubben bröts. Försöker igen …", 0);
  const answer: unknown = await response.json().catch(() => ({}));
  if (!response.ok) throw new Problem(detail(answer, "Det gick inte."), response.status);
  return answer as T;
}

export const hub = {
  info: () => call<HubInfo>("/api/hub"),
  version: () => call<Version>("/api/version"),
  setUp: (name: string, pin: string) => call<unknown>("/api/hub/setup", { name, pin }),
  logIn: (pin: string) => call<unknown>("/api/hub/login", { pin }),
  logOut: () => call<unknown>("/api/hub/logout", {}),
  // Egen AI under Den här hubben (H58): the key goes in and is never shown again.
  ai: () => call<AiService>("/api/hub/ai"),
  connectAi: (change: AiServiceChange) => call<AiService>("/api/hub/ai", change),
  disconnectAi: () => call<unknown>("/api/hub/ai/disconnect", {}),
  /** Nu, open to everyone who looks; null when no meet is started. */
  now: async (): Promise<Now | null> => {
    try {
      return await call<Now>(`${DRIFT}/now`);
    } catch (error) {
      if (error instanceof Problem && error.status === 404) return null;
      throw error;
    }
  },
  clients: () => call<Client[]>(`${DRIFT}/clients`),
  connect: () => call<Joining>(`${DRIFT}/connect`),
  meets: () => call<MeetSummary[]>("/api/planering/1/meets"),
  start: (choice: StartMeet) => call<DriftEvent>(`${DRIFT}/start`, choice),
};

/** The QR code for Anslut: the hub draws it, with the meet's code in the box's address. */
export const connectPicture = (at: number) => `${DRIFT}/connect.svg?${at}`;
