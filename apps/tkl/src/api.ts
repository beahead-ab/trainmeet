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
export type PanelTable = Schemas["trainmeet.tkl-1.track-plan.PanelTable"];
// Rita (#85): the station drawn on the grid, the model with its panel plan, kept as a draft.
export type Drawing = Schemas["trainmeet.tkl-1.drawing"];
export type Rita = Schemas["trainmeet.tkl-1.rita"];
export type RitaState = Schemas["trainmeet.tkl-1.rita.TklDrawingState"];
export type Finding = Schemas["trainmeet.tkl-1.rita.TklFinding"];
export type ObjectRef = Schemas["trainmeet.tkl-1.rita.TklObjectRef"];
export type Model = Schemas["trainmeet.tkl-1.drawing.StationModel"];
export type ModelNode = Schemas["trainmeet.tkl-1.drawing.Node"];
export type NodeType = Schemas["trainmeet.tkl-1.drawing.NodeType"];
export type Piece = Schemas["trainmeet.tkl-1.drawing.TrackPiece"];
export type Switch = Schemas["trainmeet.tkl-1.drawing.Switch"];
export type SwitchType = Schemas["trainmeet.tkl-1.drawing.SwitchType"];
export type SwitchControl = Schemas["trainmeet.tkl-1.drawing.SwitchControl"];
export type Signal = Schemas["trainmeet.tkl-1.drawing.Signal"];
export type SignalType = Schemas["trainmeet.tkl-1.drawing.SignalType"];
export type Lever = Schemas["trainmeet.tkl-1.drawing.Lever"];
export type Position = Schemas["trainmeet.tkl-1.drawing.Position"];
export type LineExit = Schemas["trainmeet.tkl-1.drawing.LineExit"];
export type StationTrack = Schemas["trainmeet.tkl-1.drawing.StationTrack"];
export type TrackCircuit = Schemas["trainmeet.tkl-1.drawing.TrackCircuit"];
export type Origin = Schemas["trainmeet.tkl-1.drawing.Origin"];
export type Plan = Schemas["trainmeet.tkl-1.drawing.PanelPlan"];
export type PlanTrack = Schemas["trainmeet.tkl-1.drawing.PanelTrack"];
export type Placement = Schemas["trainmeet.tkl-1.drawing.PanelPlacement"];
export type TrackName = Schemas["trainmeet.tkl-1.drawing.PanelTrackName"];
// Manöver, the owner's free panel (STV-46): station settings, versioned with the model.
export type Manover = Schemas["trainmeet.tkl-1.manover"];
export type ManoverSymbols = Schemas["trainmeet.tkl-1.manover.ManoverSymbols"];
export type ManoverShown = Schemas["trainmeet.tkl-1.manover.TklManoverShown"];
export type ManoverLabels = Schemas["trainmeet.tkl-1.manover.TklManoverLabels"];
// Stream Deck (#86 del a): the models, a deck's profile, and every key's face for the deck now.
export type DeckModel = Schemas["trainmeet.tkl-1.deck-model"];
export type DeckModelId = DeckModel["id"];
export type DeckProfile = Schemas["trainmeet.tkl-1.deck-profile"];
export type DeckView = Schemas["trainmeet.tkl-1.deck-view"];
export type DeckFace = Schemas["trainmeet.tkl-1.deck-view.TklDeckFace"];
export type DeckTile = Schemas["trainmeet.tkl-1.deck-view.TklDeckTile"];
export type DeckStrip = Schemas["trainmeet.tkl-1.deck-view.TklDeckStrip"];
export type DeckFavourites = Schemas["trainmeet.tkl-1.deck-favourites"];
// Stream Deck (#86 del b): real decks, over USB in a local TKL or with WebHID in the browser.
export type DeckOpen = Schemas["trainmeet.tkl-1.deck-open"];
export type DeckGrid = Schemas["trainmeet.tkl-1.deck-open.TklDeckGrid"];
export type DeckConnection = Schemas["trainmeet.tkl-1.deck-open.DeckConnection"];
export type Decks = Schemas["trainmeet.tkl-1.decks"];
export type DeckStatus = Schemas["trainmeet.tkl-1.decks.TklDeckStatus"];
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
  // Rita (#85): the drawing is saved as a draft, problems and all, until it is taken into use.
  rita: () => call<Rita>(`${TKL}/studio/rita`),
  saveDrawing: (drawing: Drawing) => call<Rita>(`${TKL}/studio/rita`, "PUT", drawing),
  useDrawing: () => call<Rita>(`${TKL}/studio/rita/use`, "POST"),
  forgetDrawing: () => call<Rita>(`${TKL}/studio/rita`, "DELETE"),
  manover: () => call<Manover>(`${TKL}/studio/manover`),
  saveManover: (settings: Manover) => call<Manover>(`${TKL}/studio/manover`, "PUT", settings),
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
  // Stream Deck (#86 del a): the same API for the deck on the screen and, later, a real deck.
  deckModels: () => call<DeckModel[]>(`${TKL}/deck/models`),
  deckOpen: (serial: string, model: DeckModelId) => call<DeckView>(`${TKL}/deck/${encodeURIComponent(serial)}`, "POST", { model }),
  deck: (serial: string) => call<DeckView>(`${TKL}/deck/${encodeURIComponent(serial)}`),
  deckPress: (serial: string, key: number, hold: boolean) => call<DeckView>(`${TKL}/deck/${encodeURIComponent(serial)}/press`, "POST", { key, hold }),
  deckDial: (serial: string, dial: number, turn: number, press: boolean) =>
    call<DeckView>(`${TKL}/deck/${encodeURIComponent(serial)}/dial`, "POST", { dial, turn, press }),
  deckTouch: (serial: string, point: -1 | 1) => call<DeckView>(`${TKL}/deck/${encodeURIComponent(serial)}/touch`, "POST", { point }),
  deckWait: (serial: string, after: number, seconds = 25) =>
    call<InterlockingWait>(`${TKL}/deck/${encodeURIComponent(serial)}/wait?after=${after}&seconds=${seconds}`),
  // Stream Deck (#86 del b): a real deck, its status, and every key as a picture TKL draws.
  decks: () => call<Decks>(`${TKL}/decks`),
  deckOpenReal: (serial: string, open: DeckOpen) => call<DeckView>(`${TKL}/deck/${encodeURIComponent(serial)}`, "POST", open),
  deckClose: (serial: string) => call<void>(`${TKL}/deck/${encodeURIComponent(serial)}/close`, "POST"),
  deckFavourites: () => call<DeckFavourites>(`${TKL}/deck-favoriter`),
  deckPin: (start: string, end: string, kind: RouteKind, pinned: boolean) =>
    call<DeckFavourites>(`${TKL}/deck-favoriter`, "POST", { start, end, kind, pinned }),
};
