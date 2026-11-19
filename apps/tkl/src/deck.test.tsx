// Stream Deck on the screen (#86 del a): the deck draws every model's grid, with the dials, the
// strip and the info line where the model has them; a click is a press and holding it a hold
// (SD29); the interlocking's reason stands on the key (SD18); Läge, Platser's lit goals and
// Spårplan's cut-out are drawn as TKL's server describes them; and without TKL every key says
// Ingen kontakt (SD21). A made-up station; nothing here names a real one (RS13).
import { isValidElement, type ReactElement, type ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import type { DeckFace, DeckView, Interlocking, Panel } from "./api";
import { DeckGrid, DeckKey } from "./Deck";
import { facesOf, Holds, keyStyle, readDeck, saveDeck, serialFor, soundOf, textSize } from "./deck";
import { drawing, filled } from "./stallverk";

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
    { piece: "a", track: null, cells: [[3, 2], [10, 2]], real: [], free: false },
    { piece: "b", track: "1", cells: [[10, 2], [27, 2]], real: [], free: false },
    { piece: "c", track: "2", cells: [[10, 2], [13, 5], [20, 5]], real: [], free: false },
  ],
  nodes: [{ id: "1", type: "switch", cell: [10, 2], real: null }],
  switches: [],
  signals: [{ name: "In", type: "hsi", node: "In", cell: [6, 2], toward: [1, 0], symbol: [6, 2], label: [6, 0.9], side: "over", planned: false, real: null, real_toward: null }],
  labels: [],
  track_names: [],
  tables: [],
  platforms: [],
  building: null,
  real_box: null,
};

const state: Interlocking = {
  station_id: "provby",
  level: 2,
  model: "abc",
  revision: 1,
  problem: null,
  switches: {},
  levers: {},
  routes: [],
  trains: [],
  signals: { In: { aspect: "stop", end: false, blocked: false, state: null, reported: null } },
  pieces: { b: { state: "train", route: 1 } },
  numbers: [],
  exits: [],
  tracks: {},
  sections: {},
  events: [],
  last_id: 0,
  field: null,
};

const GRIDS = {
  mini: { columns: 3, rows: 2, dials: 0, strip: false, info: false, touch: 0, pedals: 0 },
  "15": { columns: 5, rows: 3, dials: 0, strip: false, info: false, touch: 0, pedals: 0 },
  xl: { columns: 8, rows: 4, dials: 0, strip: false, info: false, touch: 0, pedals: 0 },
  plus: { columns: 4, rows: 2, dials: 4, strip: true, info: false, touch: 0, pedals: 0 },
  neo: { columns: 4, rows: 2, dials: 0, strip: false, info: true, touch: 2, pedals: 0 },
} as const;

const face = (more: Partial<DeckFace>): DeckFace => ({ type: "empty", bg: "#0d0f11", fg: "#0d0f11", ...more }) as DeckFace;

function deckView(model: keyof typeof GRIDS, faces: (size: number) => DeckFace[] = (n) => Array.from({ length: n }, () => face({})), more: Partial<DeckView> = {}): DeckView {
  const grid = GRIDS[model];
  const size = grid.columns * grid.rows;
  return {
    settings: { serial: "skarm-1", model, grid, workplace: "1", opens_in: null, may_change_mode: true, hold: "normal", places_shown: "alla", plan_drawn: "85", signal_numbers: false },
    revision: 1,
    style: model === "mini" ? "next" : model === "15" ? "row" : model === "xl" ? "column" : "last",
    modes: ["platser"],
    mode: "platser",
    page: "Platser",
    keys: faces(size),
    fixed: [],
    info: model === "neo" ? "06:10  Platser" : "",
    strip: model === "plus" ? [{ label: "Start", value: "O", under: "" }, { label: "Mål", value: "–", under: "" }, { label: "Del", value: "Öster", under: "" }, { label: "Lagd väg", value: "Ingen", under: "" }] : [],
    hold_ms: 600,
    refresh_ms: 15000,
    locked: false,
    contact: true,
    message: null,
    accepted: null,
    ...more,
  } as DeckView;
}

const drawn = drawing(panel, filled(state), new Set(), new Set());
const plan = { panel, drawn };
const html = (view: DeckView) => renderToStaticMarkup(<DeckGrid view={view} faces={facesOf(view, true)} now={0} plan={plan} />);
const count = (markup: string, needle: string) => markup.split(needle).length - 1;

/** The elements a component renders, flattened, for calling their handlers without a DOM. */
function elements(node: ReactNode): ReactElement<Record<string, unknown>>[] {
  if (Array.isArray(node)) return node.flatMap(elements);
  if (!isValidElement(node)) return [];
  const props = node.props as { children?: ReactNode };
  if (typeof node.type === "function") return elements((node.type as (p: unknown) => ReactNode)(node.props));
  return [node as ReactElement<Record<string, unknown>>, ...elements(props.children)];
}

describe("the deck on the screen draws every model", () => {
  it("draws Mini, 15, XL and + in their grids, with the dials and the strip on +", () => {
    for (const [model, n] of [["mini", 6], ["15", 15], ["xl", 32], ["plus", 8]] as const) {
      const markup = html(deckView(model));
      expect(count(markup, 'class="sd-key"'), model).toBe(n);
      expect(markup).toContain(`data-model="${model}"`);
      expect(markup).toContain(`repeat(${GRIDS[model].columns}, 64px)`);
    }
    const plus = html(deckView("plus"));
    expect(count(plus, 'class="sd-ratt"')).toBe(4);
    expect(plus).toContain("sd-remsa");
    expect(plus).toContain("Lagd väg");
    expect(html(deckView("xl"))).not.toContain("sd-ratt");
  });

  it("draws Neo's info line and touch points", () => {
    const markup = html(deckView("neo"));
    expect(markup).toContain("06:10  Platser");
    expect(markup).toContain('aria-label="Pekpunkt vänster"');
    expect(markup).toContain('aria-label="Pekpunkt höger"');
  });
});

describe("press and hold (SD29)", () => {
  it("is a press when short and a hold at the hold time, once, while still down", () => {
    const holds = new Holds(600);
    holds.pressed(2, 1000);
    expect(holds.released(2, 1300)).toBe("press");
    holds.pressed(2, 2000);
    expect(holds.tick(2599)).toEqual([]);
    expect(holds.tick(2600)).toEqual([2]);
    expect(holds.tick(2700)).toEqual([]);
    expect(holds.released(2, 2800)).toBeNull();
    holds.pressed(3, 0);
    holds.cancel(3);
    expect(holds.released(3, 900)).toBeNull();
    holds.ms = 1000;
    holds.pressed(4, 0);
    expect(holds.released(4, 700)).toBe("press");
  });

  it("gives the key's index to the deck on pointer down and up, and Enter presses", () => {
    const down = vi.fn();
    const up = vi.fn();
    const key = vi.fn();
    const view = deckView("15");
    const buttons = elements(DeckGrid({ view, faces: facesOf(view, true), now: 0, plan, onDown: down, onUp: up, onKey: key })).filter((e) => e.props.className === "sd-key");
    expect(buttons).toHaveLength(15);
    const seventh = buttons[7] as ReactElement<{ onPointerDown: (e: { preventDefault: () => void }) => void; onPointerUp: () => void; onKeyDown: (e: object) => void }>;
    seventh.props.onPointerDown({ preventDefault: () => undefined });
    seventh.props.onPointerUp();
    expect(down).toHaveBeenCalledWith(7);
    expect(up).toHaveBeenCalledWith(7);
    seventh.props.onKeyDown({ key: "Enter", shiftKey: true, preventDefault: () => undefined });
    expect(key).toHaveBeenCalledWith(7, true);
  });

  it("turns a dial with the wheel and the arrow keys, and presses it with a click", () => {
    const dial = vi.fn();
    const view = deckView("plus");
    const knobs = elements(DeckGrid({ view, faces: facesOf(view, true), now: 0, plan, onDial: dial })).filter((e) => e.props.className === "sd-ratt");
    const second = knobs[1] as ReactElement<{ onWheel: (e: object) => void; onKeyDown: (e: object) => void; onClick: () => void }>;
    second.props.onWheel({ deltaY: 3, preventDefault: () => undefined });
    second.props.onKeyDown({ key: "ArrowLeft", preventDefault: () => undefined });
    second.props.onClick();
    expect(dial.mock.calls).toEqual([
      [1, 1, false],
      [1, -1, false],
      [1, 0, true],
    ]);
  });
});

describe("what a key shows", () => {
  it("shows the interlocking's reason on the key after a no (SD18)", () => {
    const markup = renderToStaticMarkup(<DeckKey face={face({ type: "answer", text: "2", under: "belagt · tåg 38", bg: "#b91c1c", fg: "#ffffff", label: "Nej: Spårledningen 2 är belagd av tåg 38." })} now={0} plan={null} />);
    expect(markup).toContain("belagt · tåg 38");
    expect(markup).toContain("background:#b91c1c");
    expect(markup).toContain('data-type="answer"');
  });

  it("dims a hindered route with a red dot (SD17), and blinks what waits", () => {
    const hindered = renderToStaticMarkup(<DeckKey face={face({ type: "goal", text: "2", under: "belagt", dot: "#ff5a4d", dim: true })} now={0} plan={null} />);
    expect(hindered).toContain("sd-dot");
    expect(hindered).toContain("sd-face dim");
    const asking = face({ type: "line", text: "Vby", bg: "#0f1a2b", blink: "#1e3a5f" });
    expect(keyStyle(asking, 0).background).toBe("#0f1a2b");
    expect(keyStyle(asking, 600).background).toBe("#1e3a5f");
  });

  it("shows Läge and the modes as the server gives them (SD64)", () => {
    const view = deckView("15", (n) => {
      const keys = Array.from({ length: n }, () => face({}));
      keys[0] = face({ type: "mode", text: "Tågen", under: "ett tåg per knapp", label: "Läge Tågen" });
      keys[1] = face({ type: "mode", text: "Platser", under: "från och till i klartext", frame: "#60a5fa", label: "Läge Platser" });
      keys[2] = face({ type: "mode", text: "Spårplan", under: "signaler och växlar", label: "Läge Spårplan" });
      keys[6] = face({ type: "variant", top: "Platser visar", text: "Alla", label: "Platser visar Alla" });
      keys[14] = face({ type: "mode", top: "Läge", text: "Platser", frame: "#60a5fa", label: "Läge Platser" });
      return keys;
    });
    const markup = html(view);
    for (const said of ["Tågen", "Spårplan", "Platser visar", "signaler och växlar"]) expect(markup).toContain(said);
    expect(markup).toContain("inset 0 0 0 3.5555555555555554px #60a5fa");
  });

  it("lights Platser's goals: Lägg hit with the dashed bar, the planned one with a star (SD20, SD67)", () => {
    const view = deckView("xl", (n) => {
      const keys = Array.from({ length: n }, () => face({}));
      keys[0] = face({ type: "place", text: "O", under: "start", bg: "#000000", fg: "#f3f4f6", frame: "#60a5fa", bar: "#8a939c", label: "Start O" });
      keys[1] = face({ type: "goal", text: "2", under: "planerat", bg: "#172a46", fg: "#f3f4f6", frame: "#60a5fa", bar: "#facc15", bar_dashed: true, star: true, label: "Mål 2" });
      keys[2] = face({ type: "goal", text: "1", under: "Lägg hit", bg: "#172a46", fg: "#f3f4f6", frame: "#60a5fa", bar: "#facc15", bar_dashed: true, label: "Mål 1" });
      keys[3] = face({ type: "place", text: "V", chip: "4410", chip_colour: "green", bg: "#000000", fg: "#f3f4f6", bar: "#8a939c", label: "Plats V" });
      return keys;
    });
    const markup = html(view);
    expect(count(markup, "sd-bar streckad")).toBe(2);
    expect(markup).toContain("Lägg hit");
    expect(markup).toContain("sd-star");
    expect(markup).toContain('sd-chip gron">4410');
    expect(markup).toContain('aria-label="Mål 2"');
  });

  it("draws Spårplan's cut-out: the plan in the square, its tracks in their state (SD71, SD72)", () => {
    const cell = face({ type: "cell", bg: "#000000", fg: "#f3f4f6", tile: { x: 9, y: 0, w: 3, h: 3, drawn: "85", start: null, goals: [], names: [], chosen: false, state: "" }, label: "Ruta" });
    const markup = renderToStaticMarkup(<DeckKey face={cell} now={0} plan={plan} />);
    expect(markup).toContain('viewBox="216 0 72 72"');
    expect(count(markup, "<polyline")).toBe(3);
    expect(markup).toContain('stroke="#22c55e"');
    const relay = renderToStaticMarkup(<DeckKey face={{ ...cell, tile: { ...cell.tile!, drawn: "rela" } }} now={0} plan={plan} />);
    expect(count(relay, "<ellipse")).toBe(3);
    const signal = renderToStaticMarkup(<DeckKey face={{ ...cell, tile: { ...cell.tile!, x: 5, y: 1, w: 3, h: 3, start: "In" } }} now={0} plan={plan} />);
    expect(signal).toContain('data-signal="In"');
    expect(signal).toContain('fill="#2563eb"');
  });

  it("says Ingen kontakt on every key when TKL does not answer, never an old state (SD21)", () => {
    const view = deckView("15", (n) => Array.from({ length: n }, () => face({ type: "place", text: "O" })));
    const gone = facesOf(view, false);
    expect(gone).toHaveLength(15);
    expect(new Set(gone.map((f) => f.label))).toEqual(new Set(["Ingen kontakt"]));
    expect(facesOf({ ...view, contact: false }, true)[0]?.label).toBe("Ingen kontakt");
  });

  it("makes long texts smaller until they fit, as the prototype's canvas", () => {
    expect(textSize("41")).toBeCloseTo(0.38);
    expect(textSize("Lös ut")).toBeGreaterThan(0.2);
    expect(textSize("Lös ut")).toBeLessThanOrEqual(0.25);
    expect(textSize("Enkelspår")).toBeLessThan(0.17);
  });
});

describe("the deck per screen", () => {
  it("is known by its serial number, and keeps whether it is open and its model", () => {
    const kept = new Map<string, string>();
    const storage = { getItem: (k: string) => kept.get(k) ?? null, setItem: (k: string, v: string) => void kept.set(k, v) };
    expect(serialFor(2)).toBe("skarm-2");
    expect(readDeck(2, storage)).toEqual({ open: false, model: "15" });
    saveDeck(2, { open: true, model: "xl" }, storage);
    expect(readDeck(2, storage)).toEqual({ open: true, model: "xl" });
    expect(readDeck(3, storage).open).toBe(false);
  });
});

// Bangård (#87 del d): the shunter's deck on the part's screen, as a 15. TKL's server computes
// every face from the part's state (tkl/deck/yard.py); the screen draws it, sends the presses and
// sounds Tuta and Ring. The faces here are the server's for a made-up yard.
describe("Bangård on the screen as a 15 (#87 del d)", () => {
  const END = 10;
  const OUT = 5;
  const GIVE = 11;
  const TRAIN = 4;
  const yard = (more: Partial<Record<number, DeckFace>> = {}) =>
    deckView(
      "15",
      (n) => {
        const keys = Array.from({ length: n }, () => face({}));
        keys[0] = face({ type: "street", text: "51", under: "V 51", bg: "#1e293b", fg: "#f0f9ff", frame: "#38bdf8", label: "Växelgata V 51 mot 51" });
        keys[TRAIN] = face({ type: "train", top: "klart att skicka", text: "9101", under: "spår 51 · 10:42", small: "1/3", bg: "#1d1a0b", fg: "#fde68a", frame: "#f5c518", label: "Tåg 9101: anmäl klart att skicka" });
        keys[OUT] = face({ type: "request", text: "3", under: "begär", bg: "#262b31", fg: "#e5e7eb", frame: "#a78bfa", label: "Begär V 3" });
        keys[END] = face({ type: "end", top: "Ände", text: "Vänster", under: "◀ vald", bg: "#334155", fg: "#ffffff", line: "#f8fafc", label: "Ände: vänster" });
        keys[GIVE] = face({ type: "action", text: "Lämna", under: "tillbaka", bg: "#1f2937", fg: "#fef3c7", dim: true, label: "Lämna" });
        keys[12] = face({ type: "action", text: "Klart", under: "lämna tillbaka", bg: "#14532d", fg: "#dcfce7", label: "Klart" });
        keys[13] = face({ type: "action", text: "Ring", under: "tågklareraren", bg: "#1e1b4b", fg: "#c7d2fe", label: "Ring tågklareraren" });
        keys[14] = face({ type: "mode", top: "Läge", text: "Bangård", label: "Läge Bangård" });
        for (const [at, given] of Object.entries(more)) keys[Number(at)] = given as DeckFace;
        return keys;
      },
      { modes: ["bangard"], mode: "bangard", page: "Bangård", fixed: [10, 11, 12, 13, 14], settings: { ...deckView("15").settings, serial: "del-bangarden-1", role: "bangarden" } },
    );
  const pressed = (view: DeckView, key: number) => {
    const sent: [number, boolean][] = [];
    const holds = new Holds(view.hold_ms ?? 600);
    const buttons = elements(
      DeckGrid({
        view,
        faces: facesOf(view, true),
        now: 0,
        plan,
        onDown: (k) => holds.pressed(k, 0),
        onUp: (k) => {
          const what = holds.released(k, 100);
          if (what) sent.push([k, what === "hold"]);
        },
      }),
    ).filter((e) => e.props.className === "sd-key") as ReactElement<{ onPointerDown: (e: { preventDefault: () => void }) => void; onPointerUp: () => void }>[];
    buttons[key]?.props.onPointerDown({ preventDefault: () => undefined });
    buttons[key]?.props.onPointerUp();
    return sent;
  };

  it("is the part's own deck on its screen, kept apart from the station's", () => {
    const kept = new Map<string, string>();
    const storage = { getItem: (k: string) => kept.get(k) ?? null, setItem: (k: string, v: string) => void kept.set(k, v) };
    expect(serialFor(1, "bangarden")).toBe("del-bangarden-1");
    expect(serialFor(1, "a:b")).toBe("del-a-b-1");
    saveDeck(1, { open: true, model: "15" }, storage, "bangarden");
    expect(readDeck(1, storage, "bangarden").open).toBe(true);
    expect(readDeck(1, storage).open).toBe(false);
  });

  it("Ände shows the chosen end, and a press on it goes to TKL as a press", () => {
    const view = yard();
    const markup = html(view);
    expect(markup).toContain('data-type="end"');
    expect(markup).toContain('aria-label="Ände: vänster"');
    expect(markup).toContain("sd-line");
    expect(pressed(view, END)).toEqual([[END, false]]);
    const right = html(yard({ [END]: face({ type: "end", top: "Ände", text: "Höger", under: "vald ▶", bg: "#334155", fg: "#ffffff", line: "#f8fafc", label: "Ände: höger" }) }));
    expect(right).toContain('aria-label="Ände: höger"');
    expect(right).toContain("vald ▶");
  });

  it("a request: begär, then waiting blinks, then approved is green", () => {
    expect(pressed(yard(), OUT)).toEqual([[OUT, false]]);
    const waiting = face({ type: "request", text: "3", under: "väntar", bg: "#422006", fg: "#ffffff", frame: "#c4b5fd", blink: "#ca8a04", label: "V 3 begärd, väntar på svar" });
    expect(keyStyle(waiting, 0).background).toBe("#422006");
    expect(keyStyle(waiting, 600).background).toBe("#ca8a04");
    expect(html(yard({ [OUT]: waiting }))).toContain('data-blink="ja"');
    const approved = html(yard({ [OUT]: face({ type: "request", text: "3", under: "godkänd", bg: "#15803d", fg: "#ffffff", frame: "#c4b5fd", label: "V 3 godkänd" }) }));
    expect(approved).toContain("background:#15803d");
    expect(approved).toContain("godkänd");
  });

  it("Lämna waits for a track, and the approved route out says lämna?", () => {
    const giving = yard({
      [GIVE]: face({ type: "action", text: "Lämna", under: "välj spår", bg: "#a16207", fg: "#fef3c7", label: "Lämna: välj spåret" }),
      [OUT]: face({ type: "request", text: "3", under: "lämna?", bg: "#15803d", fg: "#ffffff", frame: "#c4b5fd", dashed: true, label: "V 3 godkänd, tryck för att lämna tillbaka" }),
    });
    const markup = html(giving);
    expect(markup).toContain("välj spår");
    expect(markup).toContain("lämna?");
    expect(keyStyle(facesOf(giving, true)[OUT] as DeckFace, 0).outline).toContain("dashed");
    expect(pressed(giving, OUT)).toEqual([[OUT, false]]);
    // With nothing approved, Lämna is dimmed.
    const idle = facesOf(yard(), true)[GIVE] as DeckFace;
    expect(renderToStaticMarkup(<DeckKey face={idle} now={0} plan={null} />)).toContain("sd-face dim");
  });

  it("the train key shows the next train; a hold steps to the next one", () => {
    const view = yard();
    const markup = html(view);
    for (const said of ["klart att skicka", "9101", "spår 51 · 10:42", "1/3"]) expect(markup).toContain(said);
    const holds = new Holds(view.hold_ms ?? 600);
    holds.pressed(TRAIN, 0);
    expect(holds.tick(700)).toEqual([TRAIN]);
    expect(holds.released(TRAIN, 800)).toBeNull();
    expect(pressed(view, TRAIN)).toEqual([[TRAIN, false]]);
  });

  it("Tuta and Ring sound on the screen, and Fika draws the cup", () => {
    expect(soundOf(face({ type: "action", text: "Tuta" }))).toBe("horn");
    expect(soundOf(face({ type: "action", text: "Ring" }))).toBe("ring");
    expect(soundOf(face({ type: "street", text: "51" }))).toBeNull();
    const cup = renderToStaticMarkup(<DeckKey face={face({ type: "fika", text: "Fika", under: "tryck: tillbaka", bg: "#1c1917", fg: "#a8a29e" })} now={0} plan={null} />);
    expect(cup).toContain("sd-kopp");
    expect(cup).not.toContain("☕");
  });
});
