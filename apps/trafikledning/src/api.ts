// Trafikledningen's API in the hub: Den här hubben (contracts/hub.py), Driftens API
// (contracts/drift.py) and the meets from Planering, with the types generated from the
// contracts. Nothing here is typed by hand. The session is an HttpOnly cookie this page never
// sees; without it the page only looks (S1).
import type { components } from "../../../contracts/types";

type Schemas = components["schemas"];
export type HubInfo = Schemas["trainmeet.hub-1.info"];
export type Version = Schemas["trainmeet.hub-1.version"];
export type Now = Schemas["trainmeet.drift-1.now"];
export type Leg = Schemas["trainmeet.drift-1.now.LegNow"];
export type Clearance = Schemas["trainmeet.drift-1.now.Clearance"];
export type Weekday = Schemas["trainmeet.drift-1.now.Weekday"];
export type Client = Schemas["trainmeet.drift-1.client"];
export type DriftEvent = Schemas["trainmeet.drift-1.event"];
export type Actor = Schemas["trainmeet.drift-1.event.Actor"];
export type Refusal = Schemas["trainmeet.drift-1.refusal"];
export type Joining = Schemas["trainmeet.drift-1.joining"];
export type Automation = Schemas["trainmeet.drift-1.automation"];
export type AutomationSettings = Schemas["trainmeet.drift-1.automation-settings"];
export type AutomationPlace = Schemas["trainmeet.drift-1.automation.AutomationPlaceStatus"];
export type MeetSummary = Schemas["trainmeet.planning-1.meet-summary"];
export type StartMeet = Schemas["trainmeet.drift-1.start"];
export type ClockControl = Schemas["trainmeet.drift-1.clock"];
export type Assign = Schemas["trainmeet.drift-1.assign"];
export type Approve = Schemas["trainmeet.drift-1.approve"];
export type Revoke = Schemas["trainmeet.drift-1.revoke"];
export type ShowView = Schemas["trainmeet.screen-1.show"];
export type ChangePlace = Schemas["trainmeet.drift-1.automation-place"];
export type Preview = Schemas["trainmeet.drift-1.preview"];
export type PreviewLeg = Schemas["trainmeet.drift-1.preview.PreviewLeg"];
export type PreviewCase = Schemas["trainmeet.drift-1.preview.PreviewCase"];
export type PreviewClients = Schemas["trainmeet.drift-1.preview-clients"];
export type Command = Schemas["trainmeet.station-1.command"];

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

async function call<T>(path: string, body?: unknown): Promise<T> {
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

export const api = {
  hub: () => call<HubInfo>("/api/hub"),
  version: () => call<Version>("/api/version"),
  setUp: (name: string, pin: string) => call<unknown>("/api/hub/setup", { name, pin }),
  logIn: (pin: string) => call<unknown>("/api/hub/login", { pin }),
  logOut: () => call<unknown>("/api/hub/logout", {}),
  /** Nu, open to everyone who looks; null when no meet is started. */
  now: async (): Promise<Now | null> => {
    try {
      return await call<Now>(`${DRIFT}/now`);
    } catch (error) {
      if (error instanceof Problem && error.status === 404) return null;
      throw error;
    }
  },
  meets: () => call<MeetSummary[]>("/api/planering/1/meets"),
  start: (choice: StartMeet) => call<DriftEvent>(`${DRIFT}/start`, choice),
  clock: (control: ClockControl) => call<DriftEvent>(`${DRIFT}/clock`, control),
  clients: () => call<Client[]>(`${DRIFT}/clients`),
  assign: (change: Assign) => call<Client>(`${DRIFT}/clients/assign`, change),
  approve: (change: Approve) => call<Client>(`${DRIFT}/clients/approve`, change),
  revoke: (change: Revoke) => call<Client>(`${DRIFT}/clients/revoke`, change),
  view: (change: ShowView) => call<Client>(`${DRIFT}/clients/view`, change),
  connect: () => call<Joining>(`${DRIFT}/connect`),
  automation: () => call<Automation>(`${DRIFT}/automation`),
  setAutomation: (settings: AutomationSettings) => call<Automation>(`${DRIFT}/automation`, settings),
  changePlace: (change: ChangePlace) => call<Automation>(`${DRIFT}/automation/place`, change),
  log: (place: string | null, train: string | null) => {
    const query = new URLSearchParams();
    if (place) query.set("place", place);
    if (train) query.set("train", train);
    return call<DriftEvent[]>(`${DRIFT}/log?${query}`);
  },
  refusals: () => call<Refusal[]>(`${DRIFT}/refusals`),
};

const PROV = "/api/provbanan";

/** Provbanan: this browser's own run, in a cookie of its own (H51). */
export const provbanan = {
  /** The run, or null when this browser has none. */
  state: async (): Promise<Preview | null> => {
    try {
      return await call<Preview>(PROV);
    } catch (error) {
      if (error instanceof Problem && error.status === 404) return null;
      throw error;
    }
  },
  start: () => call<Preview>(`${PROV}/start`, { version: 1 }),
  clock: (control: ClockControl) => call<Preview>(`${PROV}/clock`, control),
  command: (command: Command) => call<Preview>(`${PROV}/command`, command),
  clients: () => call<PreviewClients>(`${PROV}/clients`),
  assign: (change: Assign) => call<PreviewClients>(`${PROV}/clients/assign`, change),
  approve: (change: Approve) => call<PreviewClients>(`${PROV}/clients/approve`, change),
  revoke: (change: Revoke) => call<PreviewClients>(`${PROV}/clients/revoke`, change),
};

/** The QR code for Anslut: the hub draws it, with the meet's code in the box's address. */
export const connectPicture = (at: number) => `${DRIFT}/connect.svg?${at}`;
