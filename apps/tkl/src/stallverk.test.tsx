import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { Interlocking, InterlockingAnswer, Panel, Snapshot, Targets, TrackPlan } from "./api";
import { Panelen } from "./Panelen";
import { readScreen, saveScreen, screenNumber, skinOf, SKINS } from "./skal";
import { Stallverk12 } from "./Stallverk12";
import { act, busyLines, clickPoint, clickSwitch, cut, drawing, emergency, escape, filled, fromKnot, goals, guidance, NOTHING, routeEnds, type Calls, type Valet } from "./stallverk";
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
  switches: { "1": { position: "+", control: "tkl", routes: [], protection: false } },
  levers: { "1": "+" },
  routes: [],
  trains: [],
  signals: { In: { aspect: "stop", end: false }, Ut: { aspect: "stop", end: false } },
  pieces: {},
  numbers: [],
  exits: [{ exit: "V", outside: "v", pieces: ["a"], aspect: "stop" }],
  tracks: { "Spår 1": "1", "Spår 2": "2" },
  events: [],
  last_id: 0,
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
  passed: [],
  leaves: "O",
  enters: null,
  set_at: "2026-11-18T12:00:00Z",
  ...extra,
});

// A train route In → Ut with train 41 on the line at V: red on the line, green on track 1.
const running: Interlocking = {
  ...quiet,
  revision: 2,
  switches: { "1": { position: "+", control: "tkl", routes: [7], protection: false } },
  routes: [route(7, "train", { train: 3 })],
  trains: [{ id: 3, number: "41", call: null, section: null, exit: "V" }],
  signals: { In: { aspect: "proceed", end: false }, Ut: { aspect: "stop", end: true } },
  pieces: { a: { state: "occupied", route: null }, a2: { state: "train", route: 7 }, b: { state: "train", route: 7 } },
  numbers: [
    { number: "41", train: 3, colour: "red", section: null, exit: "V", pieces: ["a"], track: null, route: null, estimated: true },
    { number: "41", train: 3, colour: "green", section: "Spår 1", exit: null, pieces: ["b"], track: "1", route: 7, estimated: true },
  ],
  events: [{ at: "2026-11-18T12:00:01Z", text: "Tågväg In → Ut lagd. Tåg 41 tar vägen." }],
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
    const { calls, asked } = pretend({ layLever: () => Promise.resolve(answer({ ...quiet, switches: { "1": { position: "-", control: "tkl", routes: [], protection: false } } }, "Spaken 1 lagd i −.")) });
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
    const look = skinOf("85").signal({ type: "hdvsi", aspect: "shunt", end: false });
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
    const state = filled({ ...quiet, switches: { "1": { position: "-", control: "tkl", routes: [7], protection: true } } });
    const drawn = drawing(panel, state, new Set(), ends);
    expect(drawn.lines.find((l) => l.piece === "b")?.cut).toEqual({ start: true, end: false });
    const html = renderToStaticMarkup(<Panelen panel={panel} drawn={drawn} skin={skinOf("85")} say={say} />);
    expect(html).toContain('data-protection="1"');
    expect(html).toContain('class="skydd" fill="none" stroke="#feff00"');
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

  it("keeps the skin, the proportion and the view per screen in the browser; only 85 can be chosen (STV-05, STV-41)", () => {
    const kept = new Map<string, string>();
    const storage = { getItem: (k: string) => kept.get(k) ?? null, setItem: (k: string, v: string) => void kept.set(k, v) };
    expect(screenNumber("?skarm=2")).toBe(2);
    expect(screenNumber("?skarm=nej")).toBe(1);
    expect(readScreen(1, storage)).toEqual({ view: "all", skin: "85", proportion: 62 });
    saveScreen(2, { view: "row", skin: "85", proportion: 40 }, storage);
    expect(readScreen(2, storage)).toEqual({ view: "row", skin: "85", proportion: 40 });
    expect(readScreen(1, storage).view).toBe("all");
    kept.set("tkl.skarm.3", JSON.stringify({ view: "panel", skin: "95", proportion: 400 }));
    expect(readScreen(3, storage)).toEqual({ view: "panel", skin: "85", proportion: 90 });
    kept.set("tkl.skarm.4", "{inte json");
    expect(readScreen(4, storage).skin).toBe("85");
    expect(Object.keys(SKINS)).toEqual(["85"]);
    const html = renderToStaticMarkup(<Stallverk12 {...page} state={quiet} initial={{ plan, state: quiet, screen: { view: "all", skin: "85", proportion: 50 } }} />);
    expect(html).toContain('aria-pressed="true" title="85">85</button>');
    expect(html).toMatch(/disabled=""[^>]*>95<span class="kommer"> kommer<\/span>/);
    expect(html).toContain("Foto<span class=\"kommer\"> kommer</span>");
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
