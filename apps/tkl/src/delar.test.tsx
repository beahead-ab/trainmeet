// Delställverk (#87): the box at the top of Ställverket with Godkänn and Neka, the ring, the list
// Klara att skicka with its order and Skickat, and the part's own screen with its streets, the
// request, Lämna, Klart, Ring and the reason for a refusal. A made-up station with a yard;
// nothing here names a real one (RS13).
import { isValidElement, type ReactElement, type ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, type Interlocking, type InterlockingAnswer, type Panel, type PartShown, type PartTrains } from "./api";
import { DelKnappar, PartBoxView } from "./Delar";
import { areaOf, atEnd, attention, boxOf, givePress, outPress, rings, stepTo } from "./delar";
import { Panelen } from "./Panelen";
import { skinOf } from "./skal";
import { drawing, filled } from "./stallverk";
import { text, type Say } from "./texter";

const say: Say = (key, vars) => text("sv", key, vars);

const part: PartShown = {
  id: "bangarden",
  name: "Bangården",
  own_place: true,
  place: null,
  pieces: ["u", "v", "w", "x"],
  switches: ["4"],
  signals: ["U1", "B"],
  border: [{ switch: "3", owner: "station", towards_part: "-" }],
  rules: { lays_towards_part: true, one_way: true },
  streets: [
    { id: "V51", name: "V 51", side: "left", track: "51", positions: { "3": "-", "4": "+" }, laid: true, possible: true, reason: null },
    { id: "V52", name: "V 52", side: "left", track: "52", positions: { "3": "-", "4": "-" }, laid: false, possible: false, reason: "Växel 4 är låst i vägen U1 → Stopp51." },
    { id: "H51", name: "H 51", side: "right", track: "51", positions: { "5": "+" }, laid: false, possible: true, reason: null },
  ],
  routes_out: [
    { id: "V3", name: "V 3", side: "left", track: "3", start: "U1", end: "Ut", possible: true, reason: null, request: null, state: null },
    { id: "H3", name: "H 3", side: "right", track: "3", start: "U2", end: "Ut2", possible: true, reason: null, request: 12, state: "waiting" },
    { id: "S6", name: "Spår 6 ut", side: null, track: "6 ut", start: "S1", end: "S2", possible: false, reason: "Spårdelen y är belagd.", request: null, state: null },
  ],
  requests: [{ id: 12, part: "bangarden", route_out: "H3", said: "52 → 3", start: "U2", end: "Ut2", state: "waiting", route: null, asked: "2026-11-19T10:00:00Z", answered: null }],
  rings: "2026-11-19T10:01:00Z",
  fika: false,
  refused: [{ at: "2026-11-19T10:02:00Z", text: "Går inte att begära V 4: Spårdelen p16.2 är låst i vägen 3/1 → 6/5." }],
};

const state: Interlocking = {
  station_id: "provby",
  level: 2,
  model: "x",
  revision: 4,
  problem: null,
  last_id: 13,
  field: null,
  parts: [part],
  ready: [
    { number: "3795", part: "bangarden", part_name: "Bangården", track: "52", departure: "10:42", call: null, at: "2026-11-19T10:03:00Z", moved: false },
    { number: "3811", part: "bangarden", part_name: "Bangården", track: null, departure: "11:15", call: null, at: "2026-11-19T10:04:00Z", moved: false },
    { number: "9999", part: "bangarden", part_name: "Bangården", track: null, departure: null, call: null, at: "2026-11-19T10:05:00Z", moved: false },
  ],
};

const answer = { accepted: true, message: "Ja.", route: null, state, reports: [] } as InterlockingAnswer;

/** The elements a component renders, flattened, for calling their handlers without a DOM. */
function elements(node: ReactNode): ReactElement<Record<string, unknown>>[] {
  if (Array.isArray(node)) return node.flatMap(elements);
  if (!isValidElement(node)) return [];
  const props = node.props as { children?: ReactNode };
  if (typeof node.type === "function") return elements((node.type as (p: unknown) => ReactNode)(node.props));
  return [node as ReactElement<Record<string, unknown>>, ...elements(props.children)];
}

const textOf = (node: ReactNode): string => {
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(textOf).join("");
  if (isValidElement(node)) return textOf((node.props as { children?: ReactNode }).children);
  return "";
};

const button = (found: ReactElement<Record<string, unknown>>[], label: string) => {
  const hit = found.find((e) => e.type === "button" && (textOf(e.props.children as ReactNode).trim() === label || e.props["aria-label"] === label));
  expect(hit, label).toBeTruthy();
  return hit as ReactElement<{ onClick: () => void; disabled?: boolean }>;
};

afterEach(() => vi.restoreAllMocks());

describe("the box in Ställverket", () => {
  const box = (onWork = vi.fn(), onDrag = vi.fn()) => elements(PartBoxView({ state, say, working: false, onWork, dragged: null, onDrag }));

  it("shows the request with Godkänn and Neka, and each answers through the interlocking", async () => {
    const markup = renderToStaticMarkup(<PartBoxView state={state} say={say} working={false} onWork={() => undefined} dragged={null} onDrag={() => undefined} />);
    expect(markup).toContain("Bangården begär <b>52 → 3</b>");
    expect(markup).toContain("U2 → Ut2");
    const reply = vi.spyOn(api, "partReply").mockResolvedValue(answer);
    const onWork = vi.fn();
    const found = box(onWork);
    button(found, "Godkänn").props.onClick();
    button(found, "Neka").props.onClick();
    for (const [work] of onWork.mock.calls) await (work as () => Promise<unknown>)();
    expect(reply.mock.calls).toEqual([
      [12, true],
      [12, false],
    ]);
  });

  it("rings with a visible mark, and Svara answers", async () => {
    const markup = renderToStaticMarkup(<PartBoxView state={state} say={say} working={false} onWork={() => undefined} dragged={null} onDrag={() => undefined} />);
    expect(markup).toContain('data-ringing="bangarden"');
    expect(markup).toContain("Bangården ringer");
    const answerRing = vi.spyOn(api, "partRingAnswer").mockResolvedValue(answer);
    const onWork = vi.fn();
    button(box(onWork), "Svara").props.onClick();
    await (onWork.mock.calls[0]?.[0] as () => Promise<unknown>)();
    expect(answerRing).toHaveBeenCalledWith("bangarden");
    expect(rings(null, attention(state))).toBe(false);
    expect(rings(new Set(), attention(state))).toBe(true);
    expect(rings(attention(state), attention(state))).toBe(false);
  });

  it("lists Klara att skicka in the interlocking's order, moves a train and marks it Skickat", async () => {
    const markup = renderToStaticMarkup(<PartBoxView state={state} say={say} working={false} onWork={() => undefined} dragged={null} onDrag={() => undefined} />);
    expect(markup.indexOf("3795")).toBeLessThan(markup.indexOf("3811"));
    expect(markup.indexOf("3811")).toBeLessThan(markup.indexOf("9999"));
    expect(markup).toContain("Bangården, spår 52 · 10:42");
    const move = vi.spyOn(api, "readyMove").mockResolvedValue(answer);
    const sent = vi.spyOn(api, "readySent").mockResolvedValue(answer);
    const onWork = vi.fn();
    const found = box(onWork);
    expect(button(found, "Flytta tåg 3795 uppåt").props.disabled).toBe(true);
    expect(button(found, "Flytta tåg 9999 nedåt").props.disabled).toBe(true);
    button(found, "Flytta tåg 9999 uppåt").props.onClick();
    button(found, "Tåg 3795 är skickat").props.onClick();
    const row = found.find((e) => e.props["data-ready"] === "3795") as ReactElement<{ onDrop: (e: object) => void }>;
    row.props.onDrop({ preventDefault: () => undefined, dataTransfer: { getData: () => "3811" } });
    for (const [work] of onWork.mock.calls) await (work as () => Promise<unknown>)();
    expect(move.mock.calls).toEqual([
      ["9999", 1],
      ["3811", 0],
    ]);
    expect(sent).toHaveBeenCalledWith("3795");
    expect(stepTo(state.ready ?? [], "3795", -1)).toBeNull();
  });

  it("shows nothing when nothing waits", () => {
    const quiet = { ...state, parts: [{ ...part, requests: [], rings: null }], ready: [] };
    expect(renderToStaticMarkup(<PartBoxView state={quiet} say={say} working={false} onWork={() => undefined} dragged={null} onDrag={() => undefined} />)).toBe("");
    expect(boxOf(quiet).asking).toEqual([]);
  });
});

describe("the part's own screen", () => {
  const trains: PartTrains = { part: "bangarden", trains: [{ number: "3795", call: "c1", track: "52", departure: "10:42", label: null }], message: null };
  const handlers = () => ({
    onSide: vi.fn(),
    onStreet: vi.fn(),
    onOut: vi.fn(),
    onGive: vi.fn(),
    onDone: vi.fn(),
    onGates: vi.fn(),
    onRing: vi.fn(),
    onHorn: vi.fn(),
    onFika: vi.fn(),
    onClock: vi.fn(),
    onNumber: vi.fn(),
    onAnnounce: vi.fn(),
  });
  const screen = (more: Partial<Parameters<typeof DelKnappar>[0]> = {}) => {
    const on = handlers();
    const props = { part, side: "left" as const, giving: false, working: false, trains, number: "", ready: new Set<string>(), ...on, ...more };
    return { on, props, found: elements(DelKnappar(props)), markup: renderToStaticMarkup(<DelKnappar {...props} />) };
  };

  it("shows the streets and routes out at the chosen end, and lays a street", () => {
    const { on, found, markup } = screen();
    expect(markup).toContain('data-street="V51"');
    expect(markup).toContain('data-street="V52"');
    expect(markup).not.toContain('data-street="H51"');
    expect(markup).toContain('data-route-out="S6"');
    expect(markup).toContain("Växel 4 är låst i vägen U1 → Stopp51.");
    expect(markup).toMatch(/class="del-knapp gata ligger"[^>]*data-street="V51"/);
    const street = found.find((e) => e.props["data-street"] === "V51") as ReactElement<{ onClick: () => void }>;
    street.props.onClick();
    expect(on.onStreet).toHaveBeenCalledWith("V51");
    const right = screen({ side: "right" }).markup;
    expect(right).toContain('data-street="H51"');
    expect(right).toMatch(/class="del-knapp ut vantar"[^>]*data-route-out="H3"/);
    expect(atEnd(part.routes_out ?? [], "right").map((r) => r.id)).toEqual(["H3", "S6"]);
  });

  it("requests a route out, and a press on a waiting one takes it back", () => {
    const { on, found } = screen();
    const out = found.find((e) => e.props["data-route-out"] === "V3") as ReactElement<{ onClick: () => void }>;
    out.props.onClick();
    expect(on.onOut.mock.calls[0]?.[0].id).toBe("V3");
    const [v3, h3] = part.routes_out ?? [];
    expect(outPress(v3 as never, false)).toEqual({ kind: "request", id: "V3" });
    expect(outPress(h3 as never, false)).toEqual({ kind: "return", request: 12 });
    const approved = { ...(h3 as object), state: "approved" } as never;
    expect(outPress(approved, false)).toEqual({ kind: "say", text: "H 3 ligger. Tryck Lämna för att lämna tillbaka den." });
    expect(outPress(approved, true)).toEqual({ kind: "return", request: 12 });
  });

  it("Lämna gives back the one approved, Klart and Ring call the interlocking", () => {
    const { on, found } = screen();
    button(found, "Lämna").props.onClick();
    button(found, "Klart").props.onClick();
    button(found, "Ringer …").props.onClick();
    button(found, "Grindar").props.onClick();
    button(found, "Tuta").props.onClick();
    button(found, "Fika").props.onClick();
    button(found, "Klocka").props.onClick();
    for (const name of ["onGive", "onDone", "onRing", "onGates", "onHorn", "onFika", "onClock"] as const) expect(on[name], name).toHaveBeenCalledOnce();
    expect(givePress(part)).toEqual({ kind: "none" });
    const one = { ...part, requests: [{ ...(part.requests?.[0] as object), state: "approved" }] } as PartShown;
    expect(givePress(one)).toEqual({ kind: "return", request: 12 });
    const two = { ...one, requests: [...(one.requests ?? []), { ...(one.requests?.[0] as object), id: 13 }] } as PartShown;
    expect(givePress(two)).toEqual({ kind: "choose" });
  });

  it("announces a train from the plan or a typed number, and says what was refused and why", () => {
    const { on, found, markup } = screen({ number: "4711" });
    (found.find((e) => e.props["data-train"] === "3795") as ReactElement<{ onClick: () => void }>).props.onClick();
    const form = found.find((e) => e.type === "form") as ReactElement<{ onSubmit: (e: object) => void }>;
    form.props.onSubmit({ preventDefault: () => undefined });
    expect(on.onAnnounce.mock.calls).toEqual([
      ["3795", "c1"],
      ["4711", null],
    ]);
    expect(markup).toContain("spår 52 · 10:42");
    expect(markup).toContain("Går inte att begära V 4: Spårdelen p16.2 är låst i vägen 3/1 → 6/5.");
    const announced = screen({ ready: new Set(["3795"]) }).markup;
    expect(announced).toContain("· anmält");
  });

  it("greys the panel outside the part's area", () => {
    const panel: Panel = {
      source: "engine",
      width: 20,
      height: 6,
      cell: [24, 24],
      angle: "45",
      rows: 1,
      shortened: false,
      fields: [],
      lines: [
        { piece: "u", track: null, cells: [[2, 2], [8, 2]], real: [], free: false },
        { piece: "b", track: null, cells: [[8, 2], [16, 2]], real: [], free: false },
      ],
      nodes: [],
      switches: [],
      signals: [
        { name: "U1", type: "dvsi", node: "U", cell: [4, 2], toward: [1, 0], symbol: [4, 2], label: [4, 1], side: "over", planned: false, real: null, real_toward: null },
        { name: "In", type: "hsi", node: "W", cell: [12, 2], toward: [1, 0], symbol: [12, 2], label: [12, 1], side: "over", planned: false, real: null, real_toward: null },
      ],
      labels: [],
      track_names: [],
      tables: [],
      platforms: [],
      building: null,
      real_box: null,
    };
    const empty = filled({ station_id: "provby", level: 2, model: "x", revision: 0, problem: null, last_id: 0, field: null });
    const markup = renderToStaticMarkup(<Panelen panel={panel} drawn={drawing(panel, empty, new Set(), new Set())} skin={skinOf("85")} say={say} area={areaOf(part)} onPoint={() => undefined} />);
    expect(markup).toMatch(/data-piece="b"[^>]*data-outside="ja"/);
    expect(markup).not.toMatch(/data-piece="u"[^>]*data-outside/);
    expect(markup).toContain('aria-label="Signal U1"');
    expect(markup).not.toContain('aria-label="Signal In"');
  });
});
