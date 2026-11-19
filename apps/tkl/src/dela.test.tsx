// Studio › Dela stationen (#87 del b): drawing the area section by section, the border switches
// with their owner and position, a street from an end and a track, a route out chosen from the
// station's, the checks that show what they are about, and the draft that is saved a moment
// after each change and before Använd. A made-up station with a yard; nothing here names a
// real one (RS13).
import { isValidElement, type ReactElement, type ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Dela, Panel, StationPart, SwitchStreet, TrackPlan } from "./api";
import {
  addStreet,
  checkList,
  clickPiece,
  clickSignal,
  clickSwitch,
  DraftSaver,
  hasRouteOut,
  idFrom,
  markOf,
  newPart,
  renamed,
  routesOutAt,
  setBorder,
  streetsAt,
  toggleRouteOut,
  type Marked,
  type Tool,
} from "./dela";
import { DelaPanel, DelaVy } from "./DelaStationen";
import { placeLine } from "./delar";
import { areaPieces, toggleSection } from "./omrade";

// V -a- W -b- [1] ... the yard: u v w x p q r s, switch 3 at the border and 4 its own.
const line = (piece: string, x1: number, x2: number, y = 2) => ({ piece, track: null, free: false, cells: [[x1, y], [x2, y]] as [number, number][] });
const panel = {
  source: "plan",
  width: 20,
  height: 4,
  cell: [30, 30],
  lines: [line("a", 0, 2), line("b", 2, 4), line("y", 4, 6), line("w", 6, 8), line("v", 8, 10), line("u", 10, 12), line("x", 8, 12, 3), line("q", 12, 16, 3), line("s", 12, 16, 4)],
  nodes: [
    { id: "B", type: "signal_point", cell: [6, 2] },
    { id: "3", type: "switch", cell: [8, 2] },
    { id: "4", type: "switch", cell: [12, 3] },
  ],
  switches: [
    { number: "3", type: "ordinary", node: "3", cell: [8, 2], label: [8, 1.5], laid: true },
    { number: "4", type: "ordinary", node: "4", cell: [12, 3], label: [12, 2.5], laid: true },
    { number: "1", type: "ordinary", node: "1", cell: [4, 2], label: [4, 1.5], laid: true },
  ],
  signals: [
    { name: "B", type: "dvsi", node: "B", cell: [6, 2], toward: [-1, 0], symbol: [6, 2], label: [6, 1.4], side: "over" },
    { name: "U1", type: "dvsi", node: "U", cell: [12, 2], toward: [-1, 0], symbol: [12, 2], label: [12, 1.4], side: "over" },
  ],
} as unknown as Panel;
const plan = { summary: { station_id: "exb", name: "Exempelby", level: 2, pieces: 9, switches: 3, signals: 2, track_circuits: 0, station_tracks: [], line_exits: [], turntables: 0, plan: true }, checks: { problems: [], notes: [] }, routes: {}, route_list: [], panel } as unknown as TrackPlan;
const sections = { a: ["a"], b: ["b"], y: ["y"], w: ["w"], v: ["v", "u"], x: ["x"], q: ["q"], s: ["s"] };

const yard = (more: Partial<StationPart> = {}): StationPart => ({ ...newPart([]), id: "bangarden", name: "Bangården", ...more });
const view = (parts: StationPart[], more: Partial<Dela> = {}): Dela => ({
  state: "draft",
  parts,
  sections,
  found: [
    {
      part: "bangarden",
      edge: ["B"],
      border_switches: [{ switch: "3", owner: "station", towards_part: "-" }],
      streets: [
        { id: "H51", name: "H 51", side: "right", track: "51", positions: { "3": "-", "4": "+" } },
        { id: "H52", name: "H 52", side: "right", track: "52", positions: { "3": "-", "4": "-" } },
      ],
      routes_out: [
        { id: "VUt", name: "V Ut", side: "left", track: "Ut", start: "U1", end: "Ut" },
        { id: "VB", name: "V B", side: "left", track: "B", start: "U1", end: "B" },
      ],
    },
  ],
  checks: [
    { text: "Bangården är egen driftplats men har ingen signatur. Hubben använder namnet.", problem: false, part: "bangarden", kind: "part", id: "bangarden" },
    { text: "Bangården: växel 3 står vid gränsen. Gör den till gränsväxel och ange vem som äger den (TKL99).", problem: true, part: "bangarden", kind: "switch", id: "3" },
  ],
  ...more,
});

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
const byLabel = (found: ReactElement<Record<string, unknown>>[], label: string) => {
  const hit = found.find((e) => e.props["aria-label"] === label || (e.type === "button" && textOf(e.props.children as ReactNode).trim() === label));
  expect(hit, label).toBeTruthy();
  return hit as ReactElement<{ onClick: () => void; onChange: (e: unknown) => void; disabled?: boolean }>;
};

const makeHandlers = () => ({
  onChange: vi.fn<(parts: StationPart[]) => void>(),
  onChoose: vi.fn<(id: string | null) => void>(),
  onMark: vi.fn<(marked: Marked) => void>(),
  onUse: vi.fn<() => void>(),
  onForget: vi.fn<() => void>(),
});
type Handlers = ReturnType<typeof makeHandlers>;
const page = (parts: StationPart[], shown: Dela, given: { tool?: Tool; marked?: Marked; saving?: boolean } = {}) => {
  const handlers: Handlers = makeHandlers();
  const props = {
    plan,
    view: shown,
    parts,
    chosen: parts[0]?.id ?? null,
    tool: given.tool ?? ("area" as Tool),
    side: "right" as const,
    marked: given.marked ?? null,
    saving: given.saving ?? false,
    busy: false,
    message: "",
    problems: [],
    onTool: vi.fn<(tool: Tool) => void>(),
    onSide: vi.fn<(side: "left" | "right") => void>(),
    ...handlers,
  };
  return { props, handlers, found: elements(DelaVy(props)), markup: renderToStaticMarkup(<DelaVy {...props} />) };
};
const changed = (handlers: Pick<Handlers, "onChange">): StationPart => (handlers.onChange.mock.calls.at(-1)?.[0] as StationPart[])[0] as StationPart;

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe("drawing the area", () => {
  it("clicks a section in and out, and leaves an area that is not changed as it was", () => {
    const empty = yard();
    const one = toggleSection(empty, "u", sections);
    expect(one.pieces).toEqual(["v", "u"]);
    expect([...areaPieces(toggleSection(one, "q", sections), sections)]).toEqual(["v", "u", "q"]);
    expect(toggleSection(one, "v", sections).pieces).toEqual([]);
    const circuits = { ...empty, track_circuits: ["v"], pieces: ["q"] };
    expect(toggleSection(circuits, "u", sections)).toMatchObject({ track_circuits: [], pieces: ["q"] });
    expect(clickPiece(empty, "x", sections).pieces).toEqual(["x"]);
  });

  it("shows the area tinted on the panel, the border where it meets the rest, and each piece a button with the area tool", () => {
    const part = yard({ pieces: ["v", "u", "x", "q"], switches: ["4"], signals: ["U1"], border: [{ switch: "3", owner: "station", towards_part: "-" }], border_signals: ["B"] });
    const markup = renderToStaticMarkup(<DelaPanel panel={panel} part={part} parts={[part, yard({ id: "lok", name: "Lok", pieces: ["s"] })]} found={view([part]).found?.[0] ?? null} sections={sections} tool="area" marked={null} onPiece={() => undefined} onSwitch={() => undefined} onSignal={() => undefined} />);
    expect(markup).toContain('data-piece="q" data-area="ja" class="dela-i"');
    expect(markup).toContain('data-piece="s" class="dela-annan"');
    expect(markup).toContain('data-edge="B"');
    expect(markup).toContain('data-switch="4" data-own="ja"');
    expect(markup).toContain('data-switch="3" data-border="station"');
    expect(markup).toContain('data-signal="B" data-border="ja"');
    const { found, handlers } = page([yard()], view([yard()]));
    byLabel(found, "Spårbit q").props.onClick();
    expect(changed(handlers).pieces).toEqual(["q"]);
  });
});

describe("the border switches", () => {
  it("are marked with the owner and position Studio suggests, the station by default, and changed in the list", () => {
    const found = view([yard()]).found?.[0] ?? null;
    const marked = clickSwitch(yard({ switches: ["3"] }), "3", "border", found);
    expect(marked.border).toEqual([{ switch: "3", owner: "station", towards_part: "-" }]);
    expect(marked.switches, "a switch is one or the other").toEqual([]);
    expect(clickSwitch(marked, "3", "border", found).border).toEqual([]);
    expect(clickSwitch(yard(), "4", "switches").switches).toEqual(["4"]);
    expect(setBorder(marked, "3", { owner: "part" }).border?.[0]?.owner).toBe("part");
    expect(clickSignal(yard(), "B", "border_signals").border_signals).toEqual(["B"]);
    const part = yard({ border: [{ switch: "3", owner: "station", towards_part: "-" }] });
    const { found: shown, handlers, markup } = page([part], view([part]), { tool: "border" });
    expect(markup).toContain('data-border-row="3"');
    byLabel(shown, "Ägare för 3").props.onChange({ target: { value: "part" } });
    expect(changed(handlers).border).toEqual([{ switch: "3", owner: "part", towards_part: "-" }]);
    byLabel(shown, "Läge mot delen för 3").props.onChange({ target: { value: "+" } });
    expect(changed(handlers).border?.[0]?.towards_part).toBe("+");
    byLabel(shown, "Växel 4").props.onClick();
    expect(changed(handlers).border?.map((b) => b.switch)).toEqual(["3", "4"]);
  });

  it("offers the switches at the border that are not marked yet", () => {
    const { found, handlers } = page([yard()], view([yard()]));
    byLabel(found, "+ 3 (- mot delen)").props.onClick();
    expect(changed(handlers).border).toEqual([{ switch: "3", owner: "station", towards_part: "-" }]);
  });
});

describe("a street", () => {
  it("is chosen by an end and a track from what TKL computed, named, and given an id of its own", () => {
    const shown = view([yard()]);
    const found = shown.found?.[0] ?? null;
    expect(streetsAt(found, yard(), "right").map((s) => s.track)).toEqual(["51", "52"]);
    expect(streetsAt(found, yard(), "left")).toEqual([]);
    const one = addStreet(yard(), found?.streets?.[0] as never);
    expect(streetsAt(found, one, "right").map((s) => s.track)).toEqual(["52"]);
    expect(addStreet(one, { ...(found?.streets?.[0] as SwitchStreet), track: "51b" }).streets?.map((s) => s.id)).toEqual(["H51", "H51-2"]);
    const { found: page1, handlers } = page([yard()], shown);
    byLabel(page1, "+ 51").props.onClick();
    expect(changed(handlers).streets).toEqual([{ id: "H51", name: "H 51", side: "right", track: "51", positions: { "3": "-", "4": "+" } }]);
    const { found: page2, handlers: h2, markup } = page([one], view([one]));
    expect(markup).toContain("3− 4+");
    byLabel(page2, "Namn på gatan H51").props.onChange({ target: { value: "Till 51" } });
    expect(changed(h2).streets?.[0]?.name).toBe("Till 51");
  });
});

describe("a route out", () => {
  it("is chosen from the station's routes that leave the area, per end, and taken away again", () => {
    const found = view([yard()]).found?.[0] ?? null;
    const [out] = routesOutAt(found, "left");
    expect(out?.start).toBe("U1");
    const chosen = toggleRouteOut(yard(), out as never);
    expect(hasRouteOut(chosen, out as never)).toBe(true);
    expect(toggleRouteOut(chosen, out as never).routes_out).toEqual([]);
    const { props } = page([yard()], view([yard()]));
    const left = elements(DelaVy({ ...props, side: "left" }));
    const box = left.find((e) => e.props["data-offer-route"] === "U1|Ut") as ReactElement<{ onChange: () => void }>;
    box.props.onChange();
    expect(changed(props).routes_out?.map((r) => `${r.start}→${r.end}`)).toEqual(["U1→Ut"]);
  });
});

describe("the checks", () => {
  it("are listed problems first, and a click shows the part and what the check is about", () => {
    const { list, problems } = checkList(view([yard()]).checks);
    expect(problems).toBe(1);
    expect(list[0]?.id).toBe("3");
    expect(markOf(list[0] as never)).toEqual({ kind: "switch", id: "3" });
    const { found, handlers, markup } = page([yard()], view([yard()]));
    expect(markup).toContain('data-check="switch:3"');
    expect(markup).toContain("1 problem att rätta före Använd");
    const check = found.find((e) => e.props["data-check"] === "switch:3") as ReactElement<{ onClick: () => void }>;
    check.props.onClick();
    expect(handlers.onChoose).toHaveBeenCalledWith("bangarden");
    expect(handlers.onMark).toHaveBeenCalledWith({ kind: "switch", id: "3" });
    const part = yard({ border: [{ switch: "3", owner: "station", towards_part: "-" }] });
    const marked = renderToStaticMarkup(<DelaVy {...page([part], view([part])).props} marked={{ kind: "switch", id: "3" }} />);
    expect(marked).toContain('data-border-row="3" class="dela-markerad"');
    expect(marked).toContain('data-switch="3" data-border="station" class="dela-markerad"');
  });

  it("stop Använd while a problem stands, and say when there is none", () => {
    const { found } = page([yard()], view([yard()]));
    expect(byLabel(found, "Använd").props.disabled).toBe(true);
    const clean = page([yard()], view([yard()], { checks: [] }));
    expect(byLabel(clean.found, "Använd").props.disabled).toBe(false);
    expect(clean.markup).toContain("Inga problem: varje gata leder till sitt spår");
    expect(byLabel(page([yard()], view([yard()], { checks: [], state: "in_use" })).found, "Använd").props.disabled).toBe(true);
  });
});

describe("saving", () => {
  it("saves the draft a moment after the last change, only the newest answer counts, and Använd sends what waits first", async () => {
    vi.useFakeTimers();
    const answers: ((value: Dela) => void)[] = [];
    const send = vi.fn((parts: StationPart[]) => new Promise<Dela>((done) => answers.push(() => done(view(parts)))));
    const shown = vi.fn();
    const saving = vi.fn();
    const saver = new DraftSaver(send, shown, vi.fn(), saving, 400);
    saver.later([yard({ name: "A" })]);
    saver.later([yard({ name: "B" })]);
    expect(send).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(400);
    expect(send).toHaveBeenCalledTimes(1);
    expect(send.mock.calls[0]?.[0][0]?.name).toBe("B");
    saver.later([yard({ name: "C" })]);
    const flushed = saver.flush();
    expect(send).toHaveBeenCalledTimes(2);
    answers[0]?.(view([]));
    answers[1]?.(view([]));
    await flushed;
    expect(shown).toHaveBeenCalledTimes(1);
    expect((shown.mock.calls[0]?.[0] as Dela).parts?.[0]?.name).toBe("C");
    expect(saving.mock.calls.at(-1)).toEqual([false]);
    saver.later([yard({ name: "D" })]);
    saver.drop();
    await vi.advanceTimersByTimeAsync(1000);
    expect(send).toHaveBeenCalledTimes(2);
  });

  it("names a new part, keeps its id with the name, and makes the id from the name", () => {
    expect(idFrom("Rangerbangården", [])).toBe("rangerbangarden");
    expect(idFrom("Lok stall", ["lok-stall"])).toBe("lok-stall-2");
    const first = newPart([]);
    expect([first.name, first.id, first.rules]).toEqual(["Ny del", "ny-del", { lays_towards_part: true, one_way: true }]);
    expect(newPart([first]).name).toBe("Ny del 2");
    expect(renamed(first, "Bangården", [first]).id).toBe("bangarden");
    expect(renamed({ ...first, id: "egen" }, "Bangården", [first]).id).toBe("egen");
    const named = page([first], view([first]));
    byLabel(named.found, "Delens namn").props.onChange({ target: { value: "Lastplatsen" } });
    expect(changed(named.handlers)).toMatchObject({ name: "Lastplatsen", id: "lastplatsen" });
    expect(named.handlers.onChoose).toHaveBeenCalledWith("lastplatsen");
    const { found, handlers } = page([], view([]));
    byLabel(found, "+ Ny del").props.onClick();
    expect(handlers.onChange.mock.calls[0]?.[0]).toEqual([first]);
    expect(handlers.onChoose).toHaveBeenCalledWith("ny-del");
  });
});

describe("the part's place in Hubben", () => {
  it("is a small line with the dispatcher's answer, for a part that is its own driftplats", () => {
    const part = { id: "bangarden", name: "Bangården", own_place: true };
    expect(placeLine(part, [{ part: "bangarden", place: "exb-bgd", status: "waiting" }], true)).toBe("Bangården i Hubben (exb-bgd): väntar på trafikledningen.");
    expect(placeLine(part, [{ part: "bangarden", place: "exb-bgd", status: "refused" }], true)).toBe("Bangården i Hubben (exb-bgd): nekad.");
    expect(placeLine(part, [], true)).toContain("inte begärd");
    expect(placeLine(part, [], false)).toBeNull();
    expect(placeLine({ ...part, own_place: false }, [], true)).toBeNull();
  });
});
