import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { FunctionShown, Interlocking, InterlockingAnswer, Panel, Snapshot, Targets, TrackPlan } from "./api";
import { Panelen } from "./Panelen";
import { changeScreen, readScreen, saveScreen, screenNumber, SKIN_ORDER, skinOf, STANDARD, type Screen, type SkinId } from "./skal";
import { Stallverk12 } from "./Stallverk12";
import { act, arrows, busyLines, clickPoint, clickSwitch, clickToggle, cut, drawing, emergency, escape, filled, fromKnot, functionCall, goals, guidance, NOTHING, routeEnds, type Calls, type Valet } from "./stallverk";
import { readLanguage, text, TEXTS, type Say } from "./texter";

// A made-up station on the grid, as TKL's server sends it: the line from the exit V, the entry
// signal In, switch 1 with track 1 straight on and track 2 diverging, the exit signal Ut on track
// 1 and a buffer stop at the end of track 2. Nothing here names a real station (RS13).
const panel: Panel = {
  source: "engine",
  width: 30,
  height: 9,
  cell: [24, 24],
  angle: "45",
  rows: 2,
  shortened: false,
  fields: [],
  lines: [
    { piece: "a", track: null, cells: [[3, 2], [6, 2]], real: [], free: false },
    { piece: "a2", track: null, cells: [[6, 2], [10, 2]], real: [], free: false },
    { piece: "b", track: "1", cells: [[10, 2], [27, 2]], real: [], free: false },
    { piece: "c", track: "2", cells: [[10, 2], [13, 5], [20, 5]], real: [], free: false },
  ],
  nodes: [
    { id: "V", type: "line_exit", cell: [3, 2], real: null },
    { id: "1", type: "switch", cell: [10, 2], real: null },
    { id: "O", type: "line_exit", cell: [27, 2], real: null },
    { id: "S", type: "buffer_stop", cell: [20, 5], real: null },
  ],
  switches: [{ number: "1", type: "ordinary", node: "1", cell: [10, 2], real: null, trunk: "a2", straight: "b", diverging: "c", pieces: [], label: [10, 0.9], laid: true }],
  signals: [
    { name: "In", type: "hdvsi", node: "In", cell: [6, 2], toward: [1, 0], symbol: [6, 2], label: [6, 0.9], side: "over", planned: false, real: null, real_toward: null },
    { name: "Ut", type: "hsi", node: "Ut", cell: [24, 2], toward: [1, 0], symbol: [24, 2], label: [24, 0.9], side: "over", planned: false, real: null, real_toward: null },
  ],
  labels: [
    { text: "V", kind: "exit", cell: [2.4, 2.35], anchor: "end", real: null },
    { text: "S", kind: "point", cell: [20.6, 5.35], anchor: "start", real: null },
  ],
  track_names: [
    { name: "1", cell: [18, 1.4], train_number: [18.6, 0.6], real: null },
    { name: "2", cell: [18, 4.4], train_number: [18.6, 3.6], real: null },
  ],
  tables: [],
  platforms: [],
  building: null,
  real_box: null,
};

const plan: TrackPlan = {
  summary: { station_id: "provby", name: "Provby", level: 2, pieces: 4, switches: 1, levers: 1, signals: 2, track_circuits: 3, station_tracks: ["Spår 1", "Spår 2"], line_exits: ["V", "O"], turntables: 0, plan: false },
  checks: { problems: [], notes: [] },
  routes: { train: 2, shunting: 1 },
  route_list: [
    { kind: "train", start: "In", end: "Ut", pieces: ["a2", "b"], positions: { "1": "+" }, turntable: null },
    { kind: "shunting", start: "In", end: "Ut", pieces: ["a2", "b"], positions: { "1": "+" }, turntable: null },
    { kind: "shunting", start: "In", end: "S", pieces: ["a2", "c"], positions: { "1": "-" }, turntable: null },
  ],
  panel,
};

const quiet: Interlocking = {
  station_id: "provby",
  level: 2,
  model: "abc",
  revision: 1,
  problem: null,
  switches: { "1": { position: "+", control: "tkl", routes: [], protection: false, local: false, function: null, state: null, reported: null } },
  levers: { "1": "+" },
  routes: [],
  trains: [],
  signals: { In: { aspect: "stop", end: false, blocked: false, state: null, reported: null }, Ut: { aspect: "stop", end: false, blocked: false, state: null, reported: null } },
  pieces: {},
  numbers: [],
  exits: [{ exit: "V", outside: "v", pieces: ["a"], aspect: "stop" }],
  tracks: { "Spår 1": "1", "Spår 2": "2" },
  sections: { "Linje V": ["a"], Vx1: ["a2"], "Spår 1": ["b"], "Spår 2": ["c"] },
  events: [],
  last_id: 0,
  field: null,
};

const route = (id: number, kind: "train" | "shunting", extra: Partial<NonNullable<Interlocking["routes"]>[number]> = {}): NonNullable<Interlocking["routes"]>[number] => ({
  id,
  kind,
  start: "In",
  end: "Ut",
  chain: null,
  sections: [
    { section: "Spår 1", pieces: ["a2", "b"], released: false },
  ],
  positions: { "1": "+" },
  locked: { "1": "+" },
  protection: [],
  crossings: [],
  turntable: null,
  train: null,
  at: -1,
  aspect: kind === "train" ? "proceed" : "shunt",
  held: null,
  passed: [],
  leaves: "O",
  enters: null,
  set_at: "2026-11-18T12:00:00Z",
  waiting: [],
  waiting_since: null,
  came_from: null,
  part: null,
  request: null,
  ...extra,
});

// A train route In → Ut with train 41 on the line at V: red on the line, green on track 1.
const running: Interlocking = {
  ...quiet,
  revision: 2,
  switches: { "1": { position: "+", control: "tkl", routes: [7], protection: false, local: false, function: null, state: null, reported: null } },
  routes: [route(7, "train", { train: 3 })],
  trains: [{ id: 3, number: "41", call: null, section: null, exit: "V" }],
  signals: { In: { aspect: "proceed", end: false, blocked: false, state: null, reported: null }, Ut: { aspect: "stop", end: true, blocked: false, state: null, reported: null } },
  pieces: { a: { state: "occupied", route: null }, a2: { state: "train", route: 7 }, b: { state: "train", route: 7 } },
  numbers: [
    { number: "41", train: 3, colour: "red", section: null, exit: "V", pieces: ["a"], track: null, route: null, estimated: true },
    { number: "41", train: 3, colour: "green", section: "Spår 1", exit: null, pieces: ["b"], track: "1", route: 7, estimated: true },
  ],
  events: [{ at: "2026-11-18T12:00:01Z", text: "Tågväg In → Ut lagd. Tåg 41 tar vägen.", by: null }],
};

const answer = (state: Interlocking, message: string, accepted = true, routeId: number | null = null): InterlockingAnswer => ({ accepted, message, route: routeId, state, reports: [] });

const targets: Targets = {
  start: "In",
  kinds: ["train", "shunting"],
  targets: [
    { end: "Ut", kind: "train", via: [], pieces: ["a2", "b"], possible: true, reason: null, route: null },
    { end: "Ut", kind: "shunting", via: [], pieces: ["a2", "b"], possible: true, reason: null, route: null },
    { end: "S", kind: "shunting", via: [], pieces: ["a2", "c"], possible: false, reason: "Spårledningen Spår 2 är belagd av tåg 9103.", route: null },
  ],
};

/** The interlocking's API, pretend: it says what it is asked and answers from a script. */
function pretend(answers: Partial<Record<keyof Calls, (...args: never[]) => Promise<unknown>>> = {}) {
  const asked: string[] = [];
  const reply = (name: keyof Calls, fallback: () => Promise<unknown>) =>
    ((...args: unknown[]) => {
      asked.push(`${name}(${args.map((a) => JSON.stringify(a)).join(", ")})`);
      const scripted = answers[name] as ((...args: unknown[]) => Promise<unknown>) | undefined;
      return scripted ? scripted(...args) : fallback();
    }) as never;
  const ok = () => Promise.resolve(answer(running, "Ja."));
  const calls: Calls = {
    targets: reply("targets", () => Promise.resolve(targets)),
    setRoute: reply("setRoute", () => Promise.resolve(answer(running, "Tågväg In → Ut lagd.", true, 7))),
    release: reply("release", ok),
    emergencyRelease: reply("emergencyRelease", ok),
    layLever: reply("layLever", ok),
    step: reply("step", ok),
    arrive: reply("arrive", ok),
    depart: reply("depart", ok),
    putTrain: reply("putTrain", ok),
    removeTrain: reply("removeTrain", ok),
    panelFunction: reply("panelFunction", ok),
  };
  return { calls, asked };
}

const say: Say = (key, vars) => text("sv", key, vars);
const NOON = () => new Date("2026-11-18T12:00:00Z");
const ends = routeEnds(plan.route_list ?? []);

describe("Ställverket at level 1–2: the click flow", () => {
  it("chooses a start, lights its goals and sets the route to the goal clicked (STV-01)", async () => {
    const { calls, asked } = pretend();
    const first = await clickPoint(NOTHING, "In", calls, say, NOON);
    expect(asked).toEqual(['targets("In")']);
    expect(first.valet.choice?.kind).toBe("train");
    expect(goals(first.valet.choice).map((t) => t.end)).toEqual(["Ut"]);
    expect(guidance(first.valet, say)).toBe("Tågväg från In: klicka på målet. Klicka på In igen för växlingsväg. Esc avbryter.");
    const html = renderToStaticMarkup(<Panelen panel={panel} drawn={drawing(panel, filled(quiet), new Set(), ends)} skin={skinOf("85")} say={say} choice={first.valet.choice} />);
    expect(html).toContain('data-start="In" data-kind="train"');
    expect(html).toContain('stroke="#2256c3"');
    expect(html).toContain('data-goal="Ut"');
    const second = await clickPoint(first.valet, "Ut", calls, say, NOON);
    expect(asked[1]).toBe('setRoute("In", "Ut", "train")');
    expect(second.valet.choice).toBeNull();
    expect(second.valet.route).toBe(7);
    expect(second.state?.revision).toBe(2);
    expect(second.valet.said).toEqual({ text: "Tågväg In → Ut lagd.", ok: true, at: "2026-11-18T12:00:00.000Z" });
  });

  it("makes it a shunting route with a second click on the start, and the ring turns yellow (STV-24)", async () => {
    const { calls, asked } = pretend();
    const first = await clickPoint(NOTHING, "In", calls, say, NOON);
    const second = await clickPoint(first.valet, "In", calls, say, NOON);
    expect(second.valet.choice?.kind).toBe("shunting");
    expect(goals(second.valet.choice).map((t) => [t.end, t.possible])).toEqual([
      ["Ut", true],
      ["S", false],
    ]);
    expect(guidance(second.valet, say)).toBe("Växlingsväg från In: klicka på målet. Klicka på In igen för att avbryta.");
    const html = renderToStaticMarkup(<Panelen panel={panel} drawn={drawing(panel, filled(quiet), new Set(), ends)} skin={skinOf("85")} say={say} choice={second.valet.choice} />);
    expect(html).toContain('data-start="In" data-kind="shunting"');
    expect(html).toContain('stroke="#d9a400"');
    expect(html).toContain("Spårledningen Spår 2 är belagd av tåg 9103.");
    await clickPoint(second.valet, "Ut", calls, say, NOON);
    expect(asked.at(-1)).toBe('setRoute("In", "Ut", "shunting")');
    const third = await clickPoint(second.valet, "In", calls, say, NOON);
    expect(third.valet.choice).toBeNull();
  });

  it("cancels the choice with Esc, and a waiting confirmation too (STV-03)", async () => {
    const { calls } = pretend();
    const chosen = (await clickPoint(NOTHING, "In", calls, say, NOON)).valet;
    expect(escape(chosen).choice).toBeNull();
    const confirming: Valet = { ...NOTHING, route: 7, confirm: 7 };
    expect(escape(confirming)).toEqual({ ...confirming, confirm: null });
  });

  it("shows a no with its Swedish reason, in the answer line and the event row", async () => {
    const reason = "Spårledningen Spår 1 är låst i vägen In → Ut.";
    const { calls } = pretend({ setRoute: () => Promise.resolve(answer(quiet, reason, false)) });
    const chosen = (await clickPoint(NOTHING, "In", calls, say, NOON)).valet;
    const done = await clickPoint(chosen, "Ut", calls, say, NOON);
    expect(done.refused).toEqual({ text: reason, ok: false, at: "2026-11-18T12:00:00.000Z" });
    expect(done.valet.choice).toBeNull();
    expect(done.state).toBe(quiet);
    const none = await clickPoint(NOTHING, "Ut", pretend({ targets: () => Promise.resolve({ start: "Ut", kinds: [], targets: [] }) }).calls, say, NOON);
    expect(none.refused?.text).toBe("Inga vägar börjar vid Ut.");
    const html = renderToStaticMarkup(
      <Stallverk12 {...page} state={quiet} initial={{ plan, state: quiet, valet: done.valet, refusals: [done.refused ?? { text: "", ok: false, at: "" }] }} />,
    );
    expect(html).toContain('class="stv-svar nej" role="alert"><b>Nej: </b>Spårledningen Spår 1 är låst i vägen In → Ut.</p>');
    expect(html).toMatch(/<li class="nej"><span class="tm-mono">[^<]+<\/span> <b>Nej: <\/b>Spårledningen Spår 1 är låst i vägen In → Ut\.<\/li>/);
  });

  it("lays the whole lever with a click on a switch (STV-01, STV-52)", async () => {
    const { calls, asked } = pretend({ layLever: () => Promise.resolve(answer({ ...quiet, switches: { "1": { position: "-", control: "tkl", routes: [], protection: false, local: false, function: null, state: null, reported: null } } }, "Spaken 1 lagd i −.")) });
    const done = await clickSwitch(NOTHING, "1", calls, NOON);
    expect(asked).toEqual(['layLever("1")']);
    expect(done.valet.said?.text).toBe("Spaken 1 lagd i −.");
    const html = renderToStaticMarkup(<Panelen panel={panel} drawn={drawing(panel, filled(done.state ?? quiet), new Set(), ends)} skin={skinOf("85")} say={say} />);
    expect(html).toContain('aria-label="Växel 1" data-position="-"');
  });

  it("sends Kör, Ankommit and Avgått for the chosen route, and Nödutlös only when confirmed (STV-06, STV-16)", async () => {
    const { calls, asked } = pretend();
    const chosen: Valet = { ...NOTHING, route: 7 };
    const routes = running.routes ?? [];
    for (const what of ["step", "arrive", "depart", "release"] as const) await act(chosen, what, routes, calls, NOON);
    expect(asked).toEqual(["step(7)", "arrive(7)", "depart(7)", "release(7)"]);
    expect((await act(NOTHING, "step", routes, calls, NOON)).valet).toEqual(NOTHING);
    const asking = await emergency(chosen, false, calls, NOON);
    expect(asking.valet.confirm).toBe(7);
    expect(asked).toHaveLength(4);
    await emergency(asking.valet, true, calls, NOON);
    expect(asked.at(-1)).toBe("emergencyRelease(7, true)");
  });

  it("follows the train onto the next route when Kör takes it past the end", async () => {
    const onward: Interlocking = { ...running, routes: [route(9, "train", { start: "Ut", end: "O", train: 3, at: 0 })] };
    const { calls } = pretend({ step: () => Promise.resolve(answer(onward, "Tåg 41 kör Ut → O.")) });
    const done = await act({ ...NOTHING, route: 7 }, "step", running.routes ?? [], calls, NOON);
    expect(done.valet.route).toBe(9);
  });
});

describe("Ställverket at level 1–2: the drawing in skin 85", () => {
  it("draws pieces in their state's colour, the same width, and the gap in the leg a switch does not lie in", () => {
    const drawn = drawing(panel, filled(running), new Set(), ends);
    expect(drawn.lines.map((l) => [l.piece, l.state])).toEqual([
      ["a", "occupied"],
      ["a2", "train"],
      ["b", "train"],
      ["c", "free"],
    ]);
    expect(drawn.lines.find((l) => l.piece === "c")?.cut).toEqual({ start: true, end: false });
    const html = renderToStaticMarkup(<Panelen panel={panel} drawn={drawn} skin={skinOf("85")} say={say} />);
    expect(html).toContain('data-piece="b" data-state="train" points="240,48 648,48" stroke="#98cc00"');
    expect(html).toContain('data-piece="a" data-state="occupied"');
    expect(html).toContain('stroke="#fe0000"');
    expect(html).not.toContain('points="240,48 312,120 480,120"');
    expect(cut([[0, 0], [10, 0]], 1, 0)).toEqual([[1, 0], [10, 0]]);
    expect(fromKnot([[13, 5], [10, 2]], [10, 2], 1)[0]).toEqual([10, 2]);
  });

  it("shows the signals' aspects: green in proceed, red as the end, the dwarf arrow behind the triangle", () => {
    const drawn = drawing(panel, filled(running), new Set(), ends);
    expect(drawn.signals.map((s) => [s.name, s.aspect, s.end])).toEqual([
      ["In", "proceed", false],
      ["Ut", "stop", true],
    ]);
    const html = renderToStaticMarkup(<Panelen panel={panel} drawn={drawn} skin={skinOf("85")} say={say} />);
    expect(html).toContain('data-signal="In" data-aspect="proceed"');
    expect(html).toMatch(/data-signal="Ut" data-aspect="stop" data-end="ja"[^>]*><polygon[^>]*stroke:#fe0000/);
    const look = skinOf("85").signal({ type: "hdvsi", aspect: "shunt", end: false, blocked: false });
    expect(look.shapes.map((s) => [s.fill, s.stroke])).toEqual([
      ["#98cc00", null],
      ["#000000", "#969696"],
    ]);
  });

  it("draws the numbers red where the train is and green ahead, five digits, and hides the track's name (STV-06, STV-21, STV-57)", () => {
    const drawn = drawing(panel, filled(running), new Set(), ends);
    expect(drawn.numbers.map((n) => [n.colour, n.at, n.anchor])).toEqual([
      ["red", [2.4, 2.35], "end"],
      ["green", [20.1, 1.15], "middle"],
    ]);
    expect(drawn.names).toEqual([
      { name: "1", cell: [18, 1.4], hidden: true },
      { name: "2", cell: [18, 4.4], hidden: false },
    ]);
    const html = renderToStaticMarkup(<Panelen panel={panel} drawn={drawn} skin={skinOf("85")} say={say} />);
    expect(html).toContain('data-number="41" data-colour="red"');
    expect(html).toMatch(/data-colour="red"[^>]*>(<rect[^>]*><\/rect>)?<text[^>]*fill="#fe0000">00041/);
    expect(html).toMatch(/data-colour="green"[^>]*>(<rect[^>]*><\/rect>)?<text[^>]*fill="#98cc00">00041/);
    expect(html).toContain("00041 · uppskattad position");
    expect(html).not.toContain('data-track-name="1"');
    expect(html).toContain('data-track-name="2"');
    expect(skinOf("85").numberText("9103")).toBe("09103");
  });

  it("shows the line's state on the piece outside the entry signal, never the route's colour (STV-54)", () => {
    const state = filled({ ...quiet, pieces: { a: { state: "train", route: 7 } } });
    const free = drawing(panel, state, new Set(), ends);
    expect(free.lines.find((l) => l.piece === "a")).toMatchObject({ state: "free", route: null, line: true });
    const snapshot = { sections: [{ section: "s", other_place: "x", other_code: "X", tracks: "single", clearance_mode: "requested", side: "left", exit: "v", occupied: true }] } as unknown as Snapshot;
    const busy = drawing(panel, state, busyLines(state, snapshot), ends);
    expect(busy.lines.find((l) => l.piece === "a")?.state).toBe("occupied");
  });

  it("marks a switch locked as protection with short yellow at the knot (STV-20, a Förslag)", () => {
    const state = filled({ ...quiet, switches: { "1": { position: "-", control: "tkl", routes: [7], protection: true, local: false, function: null, state: null, reported: null } } });
    const drawn = drawing(panel, state, new Set(), ends);
    expect(drawn.lines.find((l) => l.piece === "b")?.cut).toEqual({ start: true, end: false });
    const html = renderToStaticMarkup(<Panelen panel={panel} drawn={drawn} skin={skinOf("85")} say={say} />);
    expect(html).toMatch(/data-protection="1"[^>]*stroke="#feff00"/);
  });

  it("makes the buffer stop a goal to click, red when a route ends there", () => {
    const drawn = drawing(panel, filled({ ...quiet, routes: [route(8, "shunting", { end: "S", leaves: null })] }), new Set(), ends);
    expect(drawn.points).toEqual([{ name: "S", cell: [20, 5] }]);
    expect(drawn.buffers).toEqual([{ id: "S", cell: [20, 5], toward: [1, 0], end: true }]);
    expect(drawn.labels.find((l) => l.text === "S")?.end).toBe(true);
  });
});

const page = {
  level: 2,
  view: null,
  hubNote: "TKL är inte ansluten till en träff.",
  outside: null,
  journal: [],
  sounds: { request: false, coming: false, alarm: false },
  busy: false,
  onSend: () => undefined,
  onExit: () => undefined,
  plan,
  panel,
  onState: () => undefined,
};

describe("Ställverket at level 1–2: the page and its screens", () => {
  it("shows the panel, the set routes and the bottom row Tåg · Klarering · Händelser (STV-07)", () => {
    const html = renderToStaticMarkup(<Stallverk12 {...page} state={running} initial={{ plan, state: running, valet: { ...NOTHING, route: 7 } }} />);
    expect(html).toContain("Nivå 2");
    expect(html).toContain('class="stv-panel skal-85"');
    expect(html).toContain("Tågväg In → Ut");
    for (const button of ["Kör", "Ankommit", "Avgått", "Lös ut", "Nödutlös"]) expect(html).toContain(`>${button}</button>`);
    expect(html).toContain('id="kol-tag"');
    expect(html).toContain('id="kol-klarering"');
    expect(html).toContain('id="kol-handelser"');
    expect(html).toContain("Tågväg In → Ut lagd. Tåg 41 tar vägen.");
    expect(html).toContain("på linjen vid V");
    expect(html).toContain('<option value="section:Spår 2">Spår 2</option>');
    expect(html).toContain('data-chosen="In"');
  });

  it("keeps the skin, the proportion and the view per screen in the browser; all five skins can be chosen (STV-05, STV-12)", () => {
    const kept = new Map<string, string>();
    const storage = { getItem: (k: string) => kept.get(k) ?? null, setItem: (k: string, v: string) => void kept.set(k, v) };
    expect(screenNumber("?skarm=2")).toBe(2);
    expect(screenNumber("?skarm=nej")).toBe(1);
    expect(readScreen(1, storage)).toEqual({ view: "all", skin: "85", proportion: 62 });
    saveScreen(2, { view: "row", skin: "85", proportion: 40 }, storage);
    expect(readScreen(2, storage)).toEqual({ view: "row", skin: "85", proportion: 40 });
    expect(readScreen(1, storage).view).toBe("all");
    kept.set("tkl.skarm.3", JSON.stringify({ view: "panel", skin: "95", proportion: 400 }));
    expect(readScreen(3, storage)).toEqual({ view: "panel", skin: "95", proportion: 90 });
    kept.set("tkl.skarm.4", "{inte json");
    expect(readScreen(4, storage).skin).toBe("85");
    kept.set("tkl.skarm.5", JSON.stringify({ skin: "foto" }));
    expect(readScreen(5, storage).skin).toBe("foto");
    kept.set("tkl.skarm.6", JSON.stringify({ skin: "68" }));
    expect(readScreen(6, storage).skin).toBe("85");
    expect(SKIN_ORDER).toEqual(["85", "95", "59", "manover", "foto"]);
    expect(Object.keys(STANDARD).sort()).toEqual(["59", "85", "95"]);
    const html = renderToStaticMarkup(<Stallverk12 {...page} state={quiet} initial={{ plan, state: quiet, screen: { view: "all", skin: "85", proportion: 50 } }} />);
    expect(html).toContain('aria-pressed="true" title="85">85</button>');
    expect(html).toContain('aria-pressed="false" title="95">95</button>');
    expect(html).toContain('aria-pressed="false" title="59">59</button>');
    expect(html).toContain('aria-pressed="false" title="Manöver · ägarens fria panel, symboler ur 85. Ändras i Studio › Spårplan.">Manöver</button>');
    // Provby has no real shape: Foto is greyed, with the reason (STV-18).
    expect(html).toContain('aria-pressed="false" class="gratt" title="Foto · Foto kräver stationens verkliga form (från CAD)">Foto</button>');
    expect(html).not.toContain("disabled=\"\"");
    expect(html).toContain("max-height:50vh");
    const row = renderToStaticMarkup(<Stallverk12 {...page} state={quiet} initial={{ plan, state: quiet, screen: { view: "row", skin: "85", proportion: 50 } }} />);
    expect(row).not.toContain("stv-panel");
    expect(row).toContain('id="kol-klarering"');
    const only = renderToStaticMarkup(<Stallverk12 {...page} state={quiet} initial={{ plan, state: quiet, screen: { view: "panel", skin: "85", proportion: 50 } }} />);
    expect(only).toContain("stv-panel");
    expect(only).not.toContain('id="kol-klarering"');
  });

  it("speaks Swedish, and English when chosen; every text has both", () => {
    for (const [key, both] of Object.entries(TEXTS)) {
      expect(both.sv, key).not.toBe("");
      expect(both.en, key).not.toBe("");
    }
    expect(readLanguage(null)).toBe("sv");
    expect(readLanguage({ getItem: () => "en" })).toBe("en");
    const html = renderToStaticMarkup(<Stallverk12 {...page} state={running} initial={{ plan, state: running, language: "en", valet: { ...NOTHING, route: 7 } }} />);
    expect(html).toContain('lang="en"');
    expect(html).toContain(">Run</button>");
    expect(html).toContain("Trains");
    expect(html).toContain('aria-label="Signal In"');
    expect(html).toContain('aria-label="Switch 1"');
  });
});

// The station's panel functions as TKL's server sends them (STV-04, STV-53).
const fn = (name: string, type: FunctionShown["type"], extra: Partial<FunctionShown> = {}): FunctionShown => ({
  name,
  type,
  on: false,
  mode: null,
  modes: [],
  pieces: [],
  signals: [],
  blocked: [],
  switches: [],
  locked: {},
  at: null,
  codes: {},
  note: null,
  ...extra,
});
const stationFunctions: FunctionShown[] = [
  fn("Signalstopp väster", "signal_stop", { signals: ["In"] }),
  fn("Lokalfrigivningsautomat", "local_release", { switches: ["1"], codes: { "59": "L1", "85": "L01", "95": "L01" }, pieces: ["c"] }),
  fn("Körström spår 2", "traction_current", { mode: "2R", modes: [{ value: "2R", label: "2R" }, { value: "3R", label: "3R" }] }),
  fn("Vändskivan", "turntable", { modes: [{ value: "t1", label: "Stall 1" }] }),
  fn("Spår 2 prog", "programming_track", { at: "S", pieces: ["c"] }),
];

describe("Ställverket at level 1–2: skins 95 and 59 (STV-12, STV-13, STV-36, STV-37, STV-45)", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("draws 95 after TDOK 2021:0552: its colours and widths, open symbols, and the ids' colours (STV-37)", () => {
    const drawn = drawing(panel, filled(running), new Set(), ends);
    const html = renderToStaticMarkup(<Panelen panel={panel} drawn={drawn} skin={skinOf("95")} say={say} />);
    expect(html).toContain('class="stv-panel skal-95"');
    // Ledigt 4 enheter i ljusgrått, tågväg 7 enheter i grönt, belagt rött (s. 65–75).
    expect(html).toContain('data-piece="b" data-state="train" points="240,48 648,48" stroke="#2db84c" stroke-width="7"');
    expect(html).toContain('data-piece="c" data-state="free" points="247.13,55.13 312,120 480,120" stroke="#d3d6d9" stroke-width="4"');
    expect(html).toMatch(/data-piece="a" data-state="occupied"[^>]*stroke="#e8312a"/);
    // Kombinerad signal i kör: vinkeln bakom triangeln, öppen, i grönt; slutpunkten röd (s. 84–89).
    expect(html).toMatch(/data-signal="In" data-aspect="proceed"[^>]*><polyline[^>]*stroke:#2db84c[^>]*><\/polyline><polygon[^>]*stroke:#2db84c/);
    expect(html).toMatch(/data-signal="Ut" data-aspect="stop" data-end="ja"[^>]*><polygon[^>]*fill:#000000;stroke:#e8312a/);
    // TKL37: spårnummer gula, signal-id grå, växelnummer vita.
    expect(html).toMatch(/data-track-name="2"[^>]*fill="#f5d90a"/);
    expect(html).toMatch(/<text[^>]*fill="#c4c8cc"[^>]*>In<\/text>/);
    expect(html).toMatch(/<text[^>]*fill="#f2f4f5"[^>]*>1<\/text>/);
    // Tågnummer utan nollor, ljusare rött och grönt med mörk kant (s. 130).
    expect(html).toMatch(/data-colour="red"[^>]*><rect[^>]*stroke="#000000"[^>]*><\/rect><text[^>]*fill="#ff4b3e" stroke="#2a2e32"[^>]*>41/);
    expect(html).toMatch(/data-colour="green"[^>]*>(<rect[^>]*><\/rect>)?<text[^>]*fill="#47d870"[^>]*>41/);
    const page95 = renderToStaticMarkup(<Stallverk12 {...page} state={running} initial={{ plan, state: running, screen: { view: "all", skin: "95", proportion: 50 } }} />);
    expect(page95).toContain("95 · efter Trafikverkets TDOK 2021:0552");
    expect(page95).toContain("Huvudsignal triangel, dvärgsignal vinkel, rött = slutpunkt");
    const page59 = renderToStaticMarkup(<Stallverk12 {...page} state={running} initial={{ plan, state: running, screen: { view: "all", skin: "59", proportion: 50 } }} />);
    expect(page59).toContain("59 · efter SJ:s signalställverk modell 59");
    expect(page59).toContain("Fäll startsignalens ställare och sedan målets.");
    const blocked = skinOf("95").signal({ type: "hsi", aspect: "stop", end: false, blocked: true });
    expect(blocked.shapes[0]?.fill).toBe("#e8312a");
    const dwarf = skinOf("95").signal({ type: "dvsi", aspect: "stop", end: false, blocked: true });
    expect([dwarf.shapes[0]?.fill, dwarf.shapes[0]?.closed]).toEqual(["#f5d90a", true]);
  });

  it("draws 59 as model 59's illuminated plan: lamps, the blue position lamp, two arrows per route, symbols at a mast", () => {
    const drawn = drawing(panel, filled(running), new Set(), ends);
    const round2 = (c: [number, number]) => c.map((v) => Math.round(v * 100) / 100);
    expect(arrows(panel, filled(running)).map((a) => [a.kind, round2(a.at), a.toward])).toEqual([
      ["train", [6.62, 2], [1, 0]],
      ["train", [26.28, 2], [1, 0]],
    ]);
    const html = renderToStaticMarkup(<Panelen panel={panel} drawn={drawn} skin={skinOf("59")} say={say} title="Provby" />);
    expect(html).toContain('class="stv-panel skal-59"');
    expect(html).toContain(">PROVBY</text>");
    // Ljusa spårlinjer, 6 enheter, utan glapp vid växeln: tillståndet syns i lamporna.
    expect(html).toContain('data-piece="c" data-state="free" points="240,48 312,120 480,120" stroke="#d3d3cb" stroke-width="6"');
    // En till fyra vita lampor per spårledning, släckt där tåget är; avbrott mellan spårledningarna.
    expect(drawn.lamps.map((l) => [l.section, l.free])).toEqual([
      ["Linje V", false],
      ["Vx1", true],
      ["Spår 1", true],
      ["Spår 1", true],
      ["Spår 1", true],
      ["Spår 2", true],
      ["Spår 2", true],
    ]);
    expect(drawn.boundaries).toEqual([{ at: [6, 2], toward: [-1, 0] }]);
    expect(html).toMatch(/data-lamp="Linje V" data-free="nej"><g><circle[^>]*><\/circle><circle[^>]*fill="#3c4041"/);
    expect(html).toContain('fill="#fff4d6"');
    expect(html).toContain('fill="#4f8fff"');
    expect(html.match(/data-arrow="train"/g)).toHaveLength(2);
    expect(html).toMatch(/data-signal="In" data-aspect="proceed"[^>]*>.*fill:#46f57a/);
    expect(html).toMatch(/data-signal="Ut" data-aspect="stop"[^>]*>.*fill:#ff3b2e/);
    // Vippställarna, fällda vid vägens start och mål, och en vid växeln.
    expect(html.match(/class="vippa" data-folded="ja"/g)?.length).toBe(3);
    expect(html).toContain('aria-label="Signal In" data-toggle="ja"');
    // Tågnummerfönstret (TKL-tillägg): svart fönster, ljusa siffror, inget grönt nummer.
    expect(html).toMatch(/data-colour="red"[^>]*><rect[^>]*fill="#050606" stroke="#4a4e50"[^>]*><\/rect><text[^>]*fill="#d8d3c3">41/);
    expect(html).not.toContain('data-colour="green"');
    expect(html).toContain("font-family:&#x27;Barlow Condensed&#x27;");
  });

  it("flips 59's toggles to the same operations: start, goal, and back to release (STV-36)", async () => {
    const { calls, asked } = pretend();
    const first = await clickToggle(NOTHING, "In", [], calls, say, NOON);
    expect(guidance(first.valet, say, true)).toBe("Tågväg från In: fäll målets ställare. Fäll In igen för växlingsväg. Esc avbryter.");
    await clickToggle(first.valet, "Ut", [], calls, say, NOON);
    const back = await clickToggle({ ...NOTHING, route: 7 }, "In", running.routes ?? [], calls, say, NOON);
    expect(asked).toEqual(['targets("In")', 'setRoute("In", "Ut", "train")', "release(7)"]);
    expect(back.valet.route).toBeNull();
    const point = await clickPoint(NOTHING, "In", calls, say, NOON);
    expect(point.valet.choice).toEqual(first.valet.choice);
    expect(guidance(NOTHING, say, true)).toContain("Fäll startsignalens ställare och sedan målets.");
  });

  it("sends nothing when the skin changes, and the drawing stays the same in logical terms (STV-18)", () => {
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    const kept = new Map<string, string>();
    const storage = { setItem: (k: string, v: string) => void kept.set(k, v) };
    let screen: Screen = { view: "all", skin: "85", proportion: 62 };
    const before = drawing(panel, filled(running), new Set(), ends);
    for (const skin of ["95", "59", "85"] as const) {
      screen = changeScreen(1, screen, { skin }, storage);
      expect(screen.skin).toBe(skin);
      expect(drawing(panel, filled(running), new Set(), ends)).toEqual(before);
    }
    expect(changeScreen(1, screen, { skin: "68" as SkinId }, storage).skin).toBe("85");
    expect(fetch).not.toHaveBeenCalled();
    expect(JSON.parse(kept.get("tkl.skarm.1") ?? "{}").skin).toBe("85");
  });
});

describe("Ställverket at level 1–2: the panel functions (STV-04, STV-53, TKL44, FR41)", () => {
  it("calls the interlocking's API for a function, and shows its yes or no", async () => {
    const { calls, asked } = pretend({ panelFunction: () => Promise.resolve(answer({ ...quiet, functions: stationFunctions }, "Signalstopp väster kopplades in.")) });
    const done = await functionCall(NOTHING, { function: "Signalstopp väster", action: "on", value: null, confirm: false }, calls, NOON);
    expect(asked).toEqual(['panelFunction({"function":"Signalstopp väster","action":"on","value":null,"confirm":false})']);
    expect(done.valet.said?.text).toBe("Signalstopp väster kopplades in.");
    const refused = await functionCall(NOTHING, { function: "Okänd", action: "on", value: null, confirm: false }, pretend({ panelFunction: () => Promise.resolve(answer(quiet, "Panelfunktionen Okänd finns inte.", false)) }).calls, NOON);
    expect(refused.refused?.text).toBe("Panelfunktionen Okänd finns inte.");
  });

  it("lists the station's functions in the row Panelens knappar, with the code in each skin", () => {
    const state: Interlocking = { ...quiet, functions: stationFunctions.map((f) => (f.type === "local_release" ? { ...f, on: true } : f)) };
    for (const [skin, code] of [["85", "L01"], ["95", "L01"], ["59", "L1"]] as const) {
      const html = renderToStaticMarkup(<Stallverk12 {...page} state={state} initial={{ plan, state, screen: { view: "all", skin, proportion: 50 } }} />);
      expect(html).toContain(`class="stv-funktioner skal-${skin}" role="group" aria-label="Panelens knappar"`);
      expect(html).toMatch(new RegExp(`aria-pressed="true"[^>]*data-function="Lokalfrigivningsautomat"[^>]*>.*${code} <span class="varde">på</span>`));
      expect(html).toContain("Knapp på modulen · 1");
      expect(html).toContain('Signalstopp väster <span class="varde">av</span>');
      expect(html).toContain('Körström spår 2 <span class="varde tm-mono">2R</span>');
      expect(html).toContain('<option value="t1">Stall 1</option>');
      if (skin === "59") expect(html).toContain('class="vippa59"');
    }
  });

  it("draws the locally released area blue, the freed switch's blue mark and the blocked entry signal (TKL44, FR41)", () => {
    const state = filled({
      ...quiet,
      switches: { "1": { position: "-", control: "tkl", routes: [], protection: false, local: true, function: "Lokal frigivning", state: null, reported: null } },
      signals: { In: { aspect: "stop", end: false, blocked: true, state: null, reported: null }, Ut: { aspect: "stop", end: false, blocked: false, state: null, reported: null } },
      pieces: { c: { state: "local", route: null } },
      functions: stationFunctions,
    });
    const drawn = drawing(panel, state, new Set(), ends);
    expect(drawn.lines.find((l) => l.piece === "c")?.state).toBe("local");
    expect(drawn.signals.find((s) => s.name === "In")?.blocked).toBe(true);
    const in85 = renderToStaticMarkup(<Panelen panel={panel} drawn={drawn} skin={skinOf("85")} say={say} />);
    expect(in85).toMatch(/data-piece="c" data-state="local"[^>]*stroke="#3664ff"/);
    expect(in85).toMatch(/data-local="1" stroke="#3664ff"/);
    expect(in85).toMatch(/data-signal="In" data-aspect="stop" data-blocked="ja"[^>]*><polygon[^>]*><\/polygon><polygon[^>]*fill:#fe0000;stroke:#fe0000/);
    const in95 = renderToStaticMarkup(<Panelen panel={panel} drawn={drawn} skin={skinOf("95")} say={say} />);
    expect(in95).toMatch(/data-piece="c" data-state="local"[^>]*stroke="#4da3ff" stroke-width="7"/);
    const local = skinOf("85").signal({ type: "dvsi", aspect: "local", end: false, blocked: false });
    expect(local.shapes[0]?.fill).toBe("#3664ff");
  });

  it("puts the programming track's button on its stub, lit while the track is switched over (STV-53)", () => {
    const withButton: Panel = { ...panel, functions: [{ name: "Spår 2 prog", type: "programming_track", node: "S", cell: [20, 6], side: "under" }] };
    const off = drawing(withButton, filled({ ...quiet, functions: stationFunctions }), new Set(), ends);
    expect(off.buttons).toEqual([{ name: "Spår 2 prog", type: "programming_track", cell: [20, 6], side: "under", on: false, mode: null }]);
    const on = filled({ ...quiet, functions: stationFunctions.map((f) => (f.type === "programming_track" ? { ...f, on: true } : f)), pieces: { c: { state: "programming", route: null } } });
    const html = renderToStaticMarkup(<Panelen panel={withButton} drawn={drawing(withButton, on, new Set(), ends)} skin={skinOf("85")} say={say} />);
    expect(html).toMatch(/role="button" tabindex="0" aria-label="Programmeringsspår Spår 2 prog" aria-pressed="true" data-function="Spår 2 prog" data-on="ja"/);
    expect(html).toMatch(/<rect[^>]*fill="#3664ff" stroke="#ffffff"[^>]*><\/rect><text[^>]*>PROG<\/text>/);
    expect(html).toMatch(/data-piece="c" data-state="programming"[^>]*stroke="#3664ff"/);
  });
});

// A made-up double slip 5a/5b where two tracks cross at [10, 4]: w and e straight through, nw and
// se on the slant, and the two bows w–se and e–nw. Nothing here names a real station (RS13).
const slipPanel: Panel = {
  ...panel,
  lines: [
    { piece: "w", track: null, cells: [[6, 4], [10, 4]], real: [], free: false },
    { piece: "e", track: null, cells: [[10, 4], [14, 4]], real: [], free: false },
    { piece: "nw", track: null, cells: [[10, 4], [8, 2]], real: [], free: false },
    { piece: "se", track: null, cells: [[10, 4], [12, 6]], real: [], free: false },
  ],
  nodes: [{ id: "5a/5b", type: "switch", cell: [10, 4], real: null }],
  switches: [
    {
      number: "5a/5b",
      type: "double_slip",
      node: "5a/5b",
      cell: [10, 4],
      real: null,
      trunk: null,
      straight: null,
      diverging: null,
      pieces: ["w", "e", "nw", "se"],
      paths: [
        { between: ["w", "e"], positions: { "5a": "+", "5b": "+" } },
        { between: ["nw", "se"], positions: { "5a": "-", "5b": "-" } },
        { between: ["w", "se"], positions: { "5a": "+", "5b": "-" } },
        { between: ["e", "nw"], positions: { "5a": "-", "5b": "+" } },
      ],
      label: [10, 2.9],
      laid: true,
    },
  ],
  signals: [],
  labels: [],
  track_names: [],
};
const slipSwitch = (position: "+" | "-") => ({ position, control: "tkl" as const, routes: [], protection: false, local: false, function: null, state: null, reported: null });
const slipState = (a: "+" | "-", b: "+" | "-", pieces: Interlocking["pieces"] = {}) =>
  filled({ ...quiet, switches: { "5a": slipSwitch(a), "5b": slipSwitch(b) }, levers: {}, signals: {}, exits: [], sections: {}, pieces });

describe("Ställverket at level 1–2: slips as in TDOK 2014:0693 7.16–7.17 (STV-22, trainmeet #38)", () => {
  it("cuts a gap at the knot in the two legs outside the way the slip lies in", () => {
    const cuts = (a: "+" | "-", b: "+" | "-") =>
      Object.fromEntries(drawing(slipPanel, slipState(a, b), new Set(), new Set()).lines.map((l) => [l.piece, l.cut.start || l.cut.end]));
    expect(cuts("+", "+")).toEqual({ w: false, e: false, nw: true, se: true });
    expect(cuts("-", "-")).toEqual({ w: true, e: true, nw: false, se: false });
    expect(cuts("+", "-")).toEqual({ w: false, e: true, nw: true, se: false });
    const near = drawing(slipPanel, slipState("+", "+"), new Set(), new Set()).lines.find((l) => l.piece === "nw");
    expect(near?.cut).toEqual({ start: true, end: false });
  });

  it("has a bow for each way that turns, in the state of the way the slip lies in", () => {
    const quietBows = drawing(slipPanel, slipState("+", "+"), new Set(), new Set()).switches[0]?.bows ?? [];
    expect(quietBows.map((b) => b.state)).toEqual(["free", "free"]);
    const routed = slipState("+", "-", { w: { state: "train", route: 3 }, se: { state: "train", route: 3 } });
    const bows = drawing(slipPanel, routed, new Set(), new Set()).switches[0]?.bows ?? [];
    expect(bows.map((b) => [b.legs[0][1], b.legs[1][1], b.state])).toEqual([
      [[9.5, 4], expect.anything(), "train"],
      [[10.5, 4], expect.anything(), "free"],
    ]);
    const occupied = slipState("+", "-", { w: { state: "train", route: 3 }, se: { state: "occupied", route: 3 } });
    expect(drawing(slipPanel, occupied, new Set(), new Set()).switches[0]?.bows[0]?.state).toBe("occupied");
  });

  it("gives a single slip one bow, and a plain crossing none and no gap", () => {
    const single: Panel = {
      ...slipPanel,
      switches: slipPanel.switches?.map((s) => ({ ...s, type: "single_slip" as const, paths: (s.paths ?? []).slice(0, 3) })),
    };
    expect(drawing(single, slipState("+", "+"), new Set(), new Set()).switches[0]?.bows).toHaveLength(1);
    const crossing: Panel = {
      ...slipPanel,
      switches: slipPanel.switches?.map((s) => ({ ...s, type: "crossing" as const, paths: (s.paths ?? []).slice(0, 2).map((p) => ({ ...p, positions: {} })) })),
    };
    const drawn = drawing(crossing, slipState("+", "+"), new Set(), new Set());
    expect(drawn.switches[0]?.bows).toEqual([]);
    expect(drawn.lines.every((l) => !l.cut.start && !l.cut.end)).toBe(true);
  });

  it("draws the bows beside the straight leg, on the side the slant leaves to, in 85 and 95 but not in 59", () => {
    const drawn = drawing(slipPanel, slipState("+", "-", { w: { state: "train", route: 3 }, se: { state: "train", route: 3 } }), new Set(), new Set());
    const strokes = (skin: SkinId) => {
      const html = renderToStaticMarkup(<Panelen panel={slipPanel} drawn={drawn} skin={skinOf(skin)} say={say} />);
      return [...html.matchAll(/data-bow="5a\/5b" data-state="(\w+)" points="([\d.,\s-]+)" stroke="([^"]+)"/g)].map((m) => ({
        state: m[1],
        points: (m[2] ?? "").split(" ").map((p) => p.split(",").map(Number)),
        stroke: m[3],
      }));
    };
    const at85 = strokes("85");
    expect(at85.map((s) => [s.state, s.stroke])).toEqual([
      ["train", skinOf("85").tracks.train],
      ["free", skinOf("85").tracks.free],
    ]);
    const [westward, eastward] = at85;
    // w–se: west of the knot, under track w; e–nw: east of it, over track e. Both lie flat.
    for (const [x = 0, y = 0] of westward?.points ?? []) expect([x < 240, y > 96]).toEqual([true, true]);
    for (const [x = 0, y = 0] of eastward?.points ?? []) expect([x > 240, y < 96]).toEqual([true, true]);
    expect(westward?.points[0]?.[1]).toBe(westward?.points[1]?.[1]);
    expect(strokes("95")).toHaveLength(2);
    expect(strokes("59")).toHaveLength(0);
  });
});
