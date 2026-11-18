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
export type IdState = Schemas["trainmeet.tkl-1.id-state"];
// Spårplan (#83): the station's model, the reference stations and the panel.
export type TrackPlan = Schemas["trainmeet.tkl-1.track-plan"];
export type Reference = Schemas["trainmeet.tkl-1.reference"];
export type Panel = Schemas["trainmeet.tkl-1.track-plan.Panel"];
export type PanelLine = Schemas["trainmeet.tkl-1.track-plan.PanelLine"];
export type PanelSignal = Schemas["trainmeet.tkl-1.track-plan.PanelSignal"];
export type Route = Schemas["trainmeet.tkl-1.track-plan.TklRoute"];
export type Checks = Schemas["trainmeet.tkl-1.track-plan.TklChecks"];
export type Saved = Schemas["trainmeet.tkl-1.saved"];
// Ställverket at level 1–2 (#84): the interlocking's state and the answer to every operation.
export type Interlocking = Schemas["trainmeet.tkl-1.interlocking"];
export type SetRoute = Schemas["trainmeet.tkl-1.interlocking.TklSetRoute"];
export type InterlockingTrain = Schemas["trainmeet.tkl-1.interlocking.TklTrain"];
export type TrainNumberShown = Schemas["trainmeet.tkl-1.interlocking.TklNumber"];
export type Aspect = Schemas["trainmeet.tkl-1.interlocking.TklAspect"];
export type InterlockingAnswer = Schemas["trainmeet.tkl-1.interlocking-answer"];
export type InterlockingWait = Schemas["trainmeet.tkl-1.interlocking-wait"];
export type Targets = Schemas["trainmeet.tkl-1.interlocking-targets"];
export type RouteKind = Schemas["trainmeet.tkl-1.route-ask.RouteKind"];
export type TrainPut = Schemas["trainmeet.tkl-1.train-put"];
// The panel functions from the catalogue (STV-04, STV-53): their state, and how one is operated.
export type FunctionShown = Schemas["trainmeet.tkl-1.interlocking.TklFunctionShown"];
export type FunctionAsk = Schemas["trainmeet.tkl-1.function-ask"];
export type PanelFunctionButton = Schemas["trainmeet.tkl-1.track-plan.PanelFunctionButton"];
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

/** What TKL or the hub said no to, in its own words; status 0 when TKL could not be reached.
 * A refused station model also lists its problems. */
export class Problem extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly problems: string[] = [],
  ) {
    super(message);
  }
}

export async function call<T>(path: string, method = "GET", body?: unknown, raw?: string): Promise<T> {
  const response = await fetch(path, {
    method,
    headers: body === undefined && raw === undefined ? {} : { "Content-Type": "application/json" },
    body: raw ?? (body === undefined ? undefined : JSON.stringify(body)),
    credentials: "same-origin",
    cache: "no-store",
  }).catch(() => null);
  if (!response) throw new Problem("Ingen kontakt med TKL. Försöker igen …", 0);
  if (response.status === 204) return undefined as T;
  const answer: unknown = await response.json().catch(() => ({}));
  if (!response.ok) {
    const said = (answer as { detail?: unknown } | null)?.detail;
    if (said && typeof said === "object" && typeof (said as { message?: unknown }).message === "string") {
      const told = said as { message: string; problems?: unknown };
      const problems = Array.isArray(told.problems) ? told.problems.filter((p): p is string => typeof p === "string") : [];
      throw new Problem(told.message, response.status, problems);
    }
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
  // TrainMeet ID och molnet (TKL18, SYNK-30): the login goes through TKL's server.
  idState: () => call<IdState>(`${TKL}/id`),
  idLogOut: () => call<IdState>(`${TKL}/id/logout`, "POST"),
  saveInCloud: (onTop: number | null) => call<Saved>(`${TKL}/id/save`, "POST", onTop === null ? {} : { on_top: onTop }),
  // Spårplan (#83): the station's model, imported or copied from a reference station.
  stationModel: async () => {
    try {
      return await call<TrackPlan>(`${TKL}/studio/model`);
    } catch (error) {
      if (error instanceof Problem && error.status === 404) return null;
      throw error;
    }
  },
  importModel: (text: string) => call<TrackPlan>(`${TKL}/studio/model`, "PUT", undefined, text),
  forgetModel: () => call<Studio>(`${TKL}/studio/model`, "DELETE"),
  references: () => call<Reference[]>(`${TKL}/referens`),
  reference: (id: string) => call<TrackPlan>(`${TKL}/referens/${encodeURIComponent(id)}`),
  useReference: (id: string) => call<TrackPlan>(`${TKL}/referens/${encodeURIComponent(id)}/use`, "POST"),
  answerExit: async (place: string, section: string, exit: string) =>
    viewed(await call<RawView>(`${TKL}/places/${encodeURIComponent(place)}/exits`, "POST", { section, exit })),
  // Ställverket (#84): every operation answers yes, or no with the reason, and the state.
  interlocking: () => call<Interlocking>(`${TKL}/stallverk`),
  interlockingWait: (after: number, seconds = 25) =>
    call<InterlockingWait>(`${TKL}/stallverk/wait?after=${after}&seconds=${seconds}`),
  targets: (start: string) => call<Targets>(`${TKL}/stallverk/targets?start=${encodeURIComponent(start)}`),
  setRoute: (start: string, end: string, kind: RouteKind | null = null) =>
    call<InterlockingAnswer>(`${TKL}/stallverk/route`, "POST", { start, end, kind }),
  release: (route: number) => call<InterlockingAnswer>(`${TKL}/stallverk/release`, "POST", { route }),
  emergencyRelease: (route: number, confirm: boolean) =>
    call<InterlockingAnswer>(`${TKL}/stallverk/emergency-release`, "POST", { route, confirm }),
  layLever: (sw: string, position: "+" | "-" | null = null) =>
    call<InterlockingAnswer>(`${TKL}/stallverk/lever`, "POST", { switch: sw, position }),
  step: (route: number) => call<InterlockingAnswer>(`${TKL}/stallverk/step`, "POST", { route }),
  arrive: (route: number) => call<InterlockingAnswer>(`${TKL}/stallverk/arrive`, "POST", { route }),
  depart: (route: number) => call<InterlockingAnswer>(`${TKL}/stallverk/depart`, "POST", { route }),
  putTrain: (put: TrainPut) => call<InterlockingAnswer>(`${TKL}/stallverk/train`, "POST", put),
  removeTrain: (train: number) => call<InterlockingAnswer>(`${TKL}/stallverk/train/remove`, "POST", { train }),
  resetInterlocking: (confirm: boolean, trains = false) =>
    call<InterlockingAnswer>(`${TKL}/stallverk/reset`, "POST", { confirm, trains }),
  panelFunction: (ask: FunctionAsk) => call<InterlockingAnswer>(`${TKL}/stallverk/function`, "POST", ask),
};
