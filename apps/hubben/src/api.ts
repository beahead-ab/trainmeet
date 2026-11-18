// The hub's API behind the header: Den här hubben (contracts/hub.py), Nu and the clients from
// Driftens API (contracts/drift.py), and the meets from Planering, with the types generated
// from the contracts. Nothing here is typed by hand. The session is an HttpOnly cookie the
// pages never see; without it a page only looks (S1).
import type { components } from "../../../contracts/types";

type Schemas = components["schemas"];
export type HubInfo = Schemas["trainmeet.hub-1.info"];
export type OneTimeCode = Schemas["trainmeet.hub-1.one-time-code"];
export type LoggedOut = Schemas["trainmeet.hub-1.logged-out"];
export type LetIn = Schemas["trainmeet.hub-1.let-in"];
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
export type CloudLink = Schemas["trainmeet.sync-1.cloud-link"];
export type WifiStatus = Schemas["trainmeet.hub-1.wifi-status"];
export type WifiProfile = Schemas["trainmeet.hub-1.wifi-status.WifiProfile"];
export type WifiProfileChange = Schemas["trainmeet.hub-1.wifi-profile-change"];
export type WifiAction = Schemas["trainmeet.hub-1.wifi-action"];
export type UpdateStatus = Schemas["trainmeet.hub-1.update-status"];
export type MeetWifi = Schemas["trainmeet.hub-1.meet-wifi"];
export type MeetWifiChange = Schemas["trainmeet.hub-1.meet-wifi-change"];
export type ClockSource = Schemas["trainmeet.hub-1.clock-source"];
export type ClockSourceChange = Schemas["trainmeet.hub-1.clock-source-change"];
export type Participant = Schemas["trainmeet.hub-1.participant"];
export type WifiVerb = "scan" | "delete" | "order" | "connect" | "confirm" | "rollback";
const NETWORK = { "X-TrainMeet-Network": "1" };
export type CloudLinkChange = Schemas["trainmeet.sync-1.cloud-link-change"];

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
export async function call<T>(path: string, body?: unknown, extra: Record<string, string> = {}): Promise<T> {
  const sending = body !== undefined;
  const response = await fetch(path, {
    method: sending ? "POST" : "GET",
    headers: sending ? { "Content-Type": "application/json", ...extra } : extra,
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
  /** Engångskoden från trafikledningen (H56): a role in the meet that runs, and only there. */
  logInWithCode: (code: string) => call<unknown>("/api/hub/login/code", { code }),
  /** On the meet's Pi: Logga in igen with the ticket from ID, without internet (KONTO-11). */
  logInAgain: () => call<unknown>("/api/hub/id/again", {}),
  // På den här hubben (SYNK-07): the hub's name, and a new PIN with the current one first.
  rename: (name: string) => call<HubInfo>("/api/hub/name", { name }),
  changePin: (pin: string, newPin: string) => call<unknown>("/api/hub/pin", { pin, new_pin: newPin }),
  /** Logga ut; after a login with ID the browser goes to ID to log out there too (KONTO-01). */
  logOut: () => call<LoggedOut>("/api/hub/logout", {}),
  // Pi:ns nät (SYNK-26): a change carries the hub's own mark; a password never comes back.
  wifi: () => call<WifiStatus>("/api/hub/wifi"),
  // Uppdateringen (SYNK-23): on a Pi, on the button, never during a meet.
  update: () => call<UpdateStatus>("/api/hub/update"),
  startUpdate: () => call<UpdateStatus>("/api/hub/update", {}, NETWORK),
  saveWifi: (change: Partial<WifiProfileChange> & Pick<WifiProfileChange, "ssid" | "security">) => call<WifiStatus>("/api/hub/wifi/save", change, NETWORK),
  wifiAction: (action: WifiVerb, given: Partial<WifiAction>) => call<WifiStatus>(`/api/hub/wifi/${action}`, given, NETWORK),
  // Träffens Wi-Fi (H45): what participants and screens show; the password never comes back.
  meetWifi: () => call<MeetWifi>("/api/hub/meet-wifi"),
  saveMeetWifi: (change: Partial<MeetWifiChange>) => call<MeetWifi>("/api/hub/meet-wifi", change),
  clockSource: () => call<ClockSource>("/api/hub/clock-source"),
  saveClockSource: (change: ClockSourceChange) => call<ClockSource>("/api/hub/clock-source", change),
  // Deltagarna (S8): what the participant page may show the one who looks.
  participant: () => call<Participant>("/api/deltagare"),
  // Egen AI under Den här hubben (H58): the key goes in and is never shown again.
  ai: () => call<AiService>("/api/hub/ai"),
  connectAi: (change: AiServiceChange) => call<AiService>("/api/hub/ai", change),
  disconnectAi: () => call<unknown>("/api/hub/ai/disconnect", {}),
  // Molnet (SYNK-02): the Pi follows meets in the cloud; the key never comes back here.
  cloud: () => call<CloudLink[]>("/api/hub/cloud"),
  connectCloud: (change: CloudLinkChange) => call<CloudLink[]>("/api/hub/cloud", change),
  disconnectCloud: (meet: string) => call<CloudLink[]>(`/api/hub/cloud/${encodeURIComponent(meet)}/disconnect`, {}),
  // Träffens hem (H35): to the Pi before the meet, back to the cloud after.
  takeHome: (meet: string) => call<CloudLink[]>(`/api/hub/cloud/${encodeURIComponent(meet)}/take`, {}),
  handBack: (meet: string) => call<CloudLink[]>(`/api/hub/cloud/${encodeURIComponent(meet)}/back`, {}),
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
  // Släpp in en person (H56, KONTO-19): six digits, once, for 15 minutes; never shown again.
  giveCode: (name: string) => call<OneTimeCode>(`${DRIFT}/codes`, name.trim() ? { name: name.trim() } : {}),
  letIn: () => call<LetIn[]>(`${DRIFT}/let-in`),
  takeAway: (person: string) => call<unknown>(`${DRIFT}/let-in/${encodeURIComponent(person)}/remove`, {}),
};

/** Logga in med TrainMeet ID (#78): the hub sends the browser to ID and back to the page. */
export const idLoginAddress = (next: string, language = "sv") => `/api/hub/id/login?${new URLSearchParams({ next, lang: language })}`;

/** The QR code for Anslut: the hub draws it, with the meet's code in the box's address. */
export const connectPicture = (at: number) => `${DRIFT}/connect.svg?${at}`;
