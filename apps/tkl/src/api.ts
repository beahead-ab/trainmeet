// TKL's own API (contracts/tkl.py), with the types generated from the contracts. Nothing here is
// typed by hand. The session is an HttpOnly cookie the page never sees, and the key from the
// approval stays in TKL's server (H31).
import type { components } from "../../../contracts/tkl";

type Schemas = components["schemas"];
export type State = Schemas["trainmeet.tkl-1.state"];
export type SetUp = Schemas["trainmeet.tkl-1.setup"];
export type Studio = Schemas["trainmeet.tkl-1.studio"];
export type Outside = Schemas["trainmeet.station-outside-1"];
export type Track = Schemas["trainmeet.station-outside-1.StationTrack"];
export type Exit = Schemas["trainmeet.station-outside-1.Exit"];
export type FoundHub = Schemas["trainmeet.tkl-1.found-hub"];
export type Connection = Schemas["trainmeet.tkl-1.connection"];
type RawView = Schemas["trainmeet.tkl-1.view"];
type RawSnapshot = Schemas["trainmeet.tkl-1.view.Snapshot"];
type RawCall = Schemas["trainmeet.tkl-1.view.CallHere"];
type Listed<K extends keyof RawSnapshot> = { [Key in K]-?: NonNullable<RawSnapshot[Key]> };
/** The snapshot with its lists always there: the hub always sends them, the schema has defaults. */
export type CallHere = RawCall & { allowed_actions: NonNullable<RawCall["allowed_actions"]> };
export type Snapshot = RawSnapshot &
  Listed<"sections" | "on_the_way" | "have_left" | "clearances" | "line_messages" | "neighbours" | "all_places" | "questions"> & { calls: CallHere[] };
export type View = RawView & { snapshot: Snapshot | null };
export type Clearance = Schemas["trainmeet.tkl-1.view.Clearance"];
export type SectionHere = Schemas["trainmeet.tkl-1.view.SectionHere"];
export type TrainOnSection = Schemas["trainmeet.tkl-1.view.TrainOnSection"];
export type Neighbour = Schemas["trainmeet.tkl-1.view.Neighbour"];
export type Question = Schemas["trainmeet.tkl-1.view.ExitQuestion"];
export type Command = Schemas["trainmeet.tkl-1.command"];
export type Reply = Schemas["trainmeet.station-1.reply"];
export type Action = Command["action"];

export const TKL = "/api/tkl/1";

export function full(snapshot: RawSnapshot): Snapshot {
  return {
    ...snapshot,
    sections: snapshot.sections ?? [],
    calls: (snapshot.calls ?? []).map((call) => ({ ...call, allowed_actions: call.allowed_actions ?? [] })),
    on_the_way: snapshot.on_the_way ?? [],
    have_left: snapshot.have_left ?? [],
    clearances: snapshot.clearances ?? [],
    line_messages: snapshot.line_messages ?? [],
    neighbours: snapshot.neighbours ?? [],
    all_places: snapshot.all_places ?? [],
    questions: snapshot.questions ?? [],
  };
}

const viewed = (view: RawView): View => ({ ...view, snapshot: view.snapshot ? full(view.snapshot) : null });

/** What TKL or the hub said no to, in its own words; status 0 when TKL could not be reached. */
export class Problem extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

export async function call<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  const response = await fetch(path, {
    method,
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    credentials: "same-origin",
    cache: "no-store",
  }).catch(() => null);
  if (!response) throw new Problem("Ingen kontakt med TKL. Försöker igen …", 0);
  if (response.status === 204) return undefined as T;
  const answer: unknown = await response.json().catch(() => ({}));
  if (!response.ok) {
    const said = (answer as { detail?: unknown } | null)?.detail;
    throw new Problem(typeof said === "string" ? said : "Något gick fel. Försök igen.", response.status);
  }
  return answer as T;
}

export const api = {
  state: () => call<State>(`${TKL}/state`),
  setUp: (change: SetUp) => call<State>(`${TKL}/setup`, "POST", change),
  unlock: (pin: string) => call<State>(`${TKL}/unlock`, "POST", { pin }),
  lock: () => call<State>(`${TKL}/lock`, "POST"),
  changePin: (old: string, pin: string) => call<void>(`${TKL}/pin`, "POST", { old, new: pin }),
  studio: () => call<Studio>(`${TKL}/studio`),
  saveList: (outside: Outside) => call<Studio>(`${TKL}/studio`, "PUT", outside),
  newVersion: () => call<Studio>(`${TKL}/studio/version`, "POST"),
  hubs: () => call<FoundHub[]>(`${TKL}/hubs`),
  connection: () => call<Connection>(`${TKL}/connection`),
  connect: (address: string, code: string | null) => call<Connection>(`${TKL}/connection`, "POST", { address, code }),
  disconnect: () => call<Connection>(`${TKL}/connection`, "DELETE"),
  place: async (place: string) => viewed(await call<RawView>(`${TKL}/places/${encodeURIComponent(place)}`)),
  command: (command: Command) => call<Reply>(`${TKL}/commands`, "POST", command),
  answerExit: async (place: string, section: string, exit: string) =>
    viewed(await call<RawView>(`${TKL}/places/${encodeURIComponent(place)}/exits`, "POST", { section, exit })),
};
