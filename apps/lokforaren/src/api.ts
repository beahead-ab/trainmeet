// Förarnas API (trainmeet.driver/1, contracts/driver.py), with the types generated from the
// contracts: nothing here is typed by hand. The phone's key is the HttpOnly cookie the join
// sets, limited to /api/drift/1/drivers; the app never sees it after the join and never writes
// it anywhere. Lokföraren owns nothing (LOK-06): Drift says, the app shows.
import type { components } from "../../../contracts/types";

type Schemas = components["schemas"];
export type DriverMe = Schemas["trainmeet.driver-1.me"];
export type Driver = Schemas["trainmeet.driver-1.me.Driver"];
export type ServiceOffer = Schemas["trainmeet.driver-1.services.ServiceOffer"];
export type ServiceList = Schemas["trainmeet.driver-1.services"];
export type Start = Schemas["trainmeet.driver-1.me.Start"];
export type CheckedIn = Schemas["trainmeet.driver-1.me.CheckedIn"];
export type Korplan = Schemas["trainmeet.driver-1.korplan"];
export type KorplanRow = Schemas["trainmeet.driver-1.korplan.KorplanRow"];
export type TrainPosition = Schemas["trainmeet.driver-1.train-position"];
export type Clock = Schemas["trainmeet.driver-1.clock.Clock"];
export type DriverClock = Schemas["trainmeet.driver-1.clock"];
export type Presence = Schemas["trainmeet.driver-1.presence"];
export type Wait = Schemas["trainmeet.driver-1.wait"];
export type Instructions = Schemas["trainmeet.driver-1.instructions"];
export type DriverMessage = Schemas["trainmeet.driver-1.message"];
export type Session = Schemas["trainmeet.driver-1.session"];
export type Join = Schemas["trainmeet.driver-1.join"];
/** Fields left out are not changed (contracts/driver.py DriverProfile). */
export type Profile = Partial<Schemas["trainmeet.driver-1.profile"]>;
export type ServiceRef = Schemas["trainmeet.drift-1.service"];
export type Level = Driver["level"];
export type DriverState = NonNullable<Driver["state"]>;
export type MessageKind = Schemas["trainmeet.driver-1.message-send"]["kind"];
export type ClaimedBy = NonNullable<DriverMe["claimed_by"]>;
export type Now = Schemas["trainmeet.drift-1.now"];
export type HubInfo = Schemas["trainmeet.hub-1.info"];

export const DRIVERS = "/api/drift/1/drivers";
export const LEVELS: Level[] = ["easy", "medium", "experienced"];
export const MESSAGE_KINDS: MessageKind[] = ["delayed", "stopped_on_line", "needs_help", "engine_trouble"];
/** The reminders before the start, in game minutes (contracts/driver.py REMINDERS, LOK-41). */
export const REMINDERS = [20, 10] as const;
/** How long Ändrat stays, in game minutes (contracts/driver.py CHANGED_MINUTES, LOK-41). */
export const CHANGED_MINUTES = 10;

/** What the hub said no to, in its own words and with its reason, or that it could not be
 * reached (status 0). */
export class Problem extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly reason: string | null = null,
  ) {
    super(message);
  }
}

type Send = { body?: unknown; raw?: Blob; signal?: AbortSignal };

/** One call to the hub: GET without a body, POST with JSON or a picture's bytes. */
export async function call<T>(path: string, send: Send = {}): Promise<T> {
  const posting = send.body !== undefined || send.raw !== undefined;
  const headers: Record<string, string> = {};
  if (send.body !== undefined) headers["Content-Type"] = "application/json";
  if (send.raw !== undefined) headers["Content-Type"] = send.raw.type || "application/octet-stream";
  const response = await fetch(path, {
    method: posting ? "POST" : "GET",
    headers,
    body: send.raw ?? (send.body !== undefined ? JSON.stringify(send.body) : undefined),
    credentials: "same-origin",
    cache: "no-store",
    signal: send.signal,
  }).catch((error: unknown) => {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    return null;
  });
  if (!response) throw new Problem("", 0);
  if (response.status === 204) return undefined as T;
  const answer: unknown = await response.json().catch(() => ({}));
  if (!response.ok) {
    const said = (answer as { detail?: unknown } | null)?.detail;
    throw new Problem(typeof said === "string" ? said : "", response.status, response.headers.get("X-Reason"));
  }
  return answer as T;
}

const json = (body: unknown) => ({ body });

export const api = {
  join: (join: Join) => call<Session>(`${DRIVERS}/join`, json(join)),
  me: () => call<DriverMe>(`${DRIVERS}/me`),
  profile: (profile: Profile) => call<DriverMe>(`${DRIVERS}/me`, json(profile)),
  photo: (picture: Blob) => call<DriverMe>(`${DRIVERS}/me/photo`, { raw: picture }),
  removePhoto: () => call<DriverMe>(`${DRIVERS}/me/photo/remove`, json({})),
  services: (query = "") => call<ServiceList>(`${DRIVERS}/services${query.trim() ? `?${new URLSearchParams({ q: query.trim() })}` : ""}`),
  claim: (service: ServiceRef) => call<DriverMe>(`${DRIVERS}/claim`, json(service)),
  release: () => call<DriverMe>(`${DRIVERS}/release`, json({})),
  korplan: () => call<Korplan>(`${DRIVERS}/korplan`),
  checkIn: (place: string, track: string | null) => call<DriverMe>(`${DRIVERS}/checkin`, json({ place, track })),
  framme: (callId: string) => call<DriverMe>(`${DRIVERS}/framme`, json({ call: callId })),
  send: (kind: MessageKind) => call<DriverMessage>(`${DRIVERS}/messages`, json({ kind })),
  clock: () => call<DriverClock>(`${DRIVERS}/clock`),
  trains: () => call<TrainPosition[]>(`${DRIVERS}/trains`),
  list: () => call<Presence[]>(`${DRIVERS}/list`),
  wait: (after: number, signal?: AbortSignal) => call<Wait>(`${DRIVERS}/wait?after=${after}`, { signal }),
  instructions: () => call<Instructions>(`${DRIVERS}/instructions`),
  leave: () => call<void>(`${DRIVERS}/leave`, json({})),
  /** Nu is open to everyone and holds no names (B13): the meet's name and its places. */
  now: () => call<Now>("/api/drift/1/now"),
  hub: () => call<HubInfo>("/api/hub"),
};

/** TrainMeet ID through the hub's own login, back to Lokföraren (LOK-16). */
export const idLoginAddress = (next: string, language: string) => `/api/hub/id/login?${new URLSearchParams({ next, lang: language })}`;

export const refKey = (ref: ServiceRef) => `${ref.kind}:${ref.id}`;

/** The lists the hub always sends, though the contract gives them defaults. */
export const rowsOf = (korplan: Korplan | null | undefined): KorplanRow[] => korplan?.rows ?? [];
export const trainsOf = (offer: ServiceOffer | null | undefined): string[] => offer?.trains ?? [];
