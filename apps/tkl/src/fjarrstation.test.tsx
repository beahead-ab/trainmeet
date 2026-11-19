// Fjärrstyrning, the station's side (#36 del b): the operating-form bar with Lämna till … and Ta
// tillbaka (FR5–FR8), the station row with the automats and the name in their colours (FR32–FR34,
// FR39, FR43), the arrows at the main signals (FR33), and Studio's catalogue by line end with its
// quick choices (TKL46, FR10). A made-up station; nothing here names a real one (RS13).
import { isValidElement, type ReactElement, type ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import type { AutomatSpec, FjarrState, FjarrStudio as Studio, FunctionShown, Outside, RemoteCandidate, Snapshot } from "./api";
import { DriftformView, StationsradView } from "./Fjarrstyrning";
import { FjarrStudio } from "./FjarrStudio";
import { arrowsOf, codeFor, grouped, modeSaid, quick, ROW_COLOURS, specsOf, stationRow, tracksOf } from "./fjarrstation";

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
  return hit as ReactElement<{ onClick: () => void; disabled?: boolean; style?: { color: string } }>;
};

const remoteInterlocking = { client_id: "fjarr-1", kind: "remote" as const, name: "Fjärr Västra", place: null };
const neighbour = { client_id: "tkl-2", kind: "tkl" as const, name: "Mellanå", place: "mla" };

function snapshot(more: Partial<Snapshot> = {}): Snapshot {
  return {
    place: { place: "exb", code: "EXB", name: "Exempelby" },
    context: { meet_id: "m", version: 1, game_day: 1, epoch: 0 },
    clock: { time: "09:00", seconds: 32400, running: true, speed: 4, game_day: 1 },
    place_revision: 1,
    sections: [],
    calls: [],
    on_the_way: [],
    have_left: [],
    clearances: [],
    line_messages: [],
    neighbours: [],
    all_places: [],
    questions: [],
    mode: "manned",
    remote: { controllable: true, controller: null, offer: null, receivers: [remoteInterlocking, neighbour], controller_silent: null, routes: [], route_state: null },
    ...more,
  } as unknown as Snapshot;
}

const SPECS: AutomatSpec[] = [
  { code: "A1", kind: "a1", signals: [], default: false },
  { code: "A3", kind: "a3", signals: [], default: true },
  { code: "AN21", kind: "an", signals: ["21"], default: false },
  { code: "L01", kind: "local_release", signals: [], function: "Lokal frigivning", default: false },
];
const LOCAL = { name: "Lokal frigivning", type: "local_release", on: false } as unknown as FunctionShown;
const fjarrState = (more: Partial<FjarrState> = {}): FjarrState => ({ controller: null, automats: [], magazine: [], ...more }) as FjarrState;

describe("the operating-form bar", () => {
  const bar = (shown: Snapshot, onSend = vi.fn(), asking = false, onAsking = vi.fn()) =>
    elements(DriftformView({ snapshot: shown, busy: false, onSend, to: "", asking, onTo: vi.fn(), onAsking }));

  it("says the operating form in words", () => {
    expect(modeSaid(snapshot()).title).toBe("Bemannad");
    const remote = snapshot({ mode: "remote", remote: { ...snapshot().remote, controller: remoteInterlocking, controller_silent: 3 } as Snapshot["remote"] });
    expect(modeSaid(remote)).toEqual({ mode: "remote", title: "Fjärrstyrs från Fjärr Västra", detail: null });
    const silent = snapshot({ mode: "no_contact", remote: { ...snapshot().remote, controller: remoteInterlocking, controller_silent: 50 } as Snapshot["remote"] });
    expect(modeSaid(silent).detail).toBe("Ingen kontakt med Fjärr Västra på 50 s");
    const offered = snapshot({ mode: "offered", remote: { ...snapshot().remote, offer: { place: "exb", to: remoteInterlocking, expires_in: 42 } } as Snapshot["remote"] });
    expect(modeSaid(offered)).toEqual({ mode: "offered", title: "Erbjuden till Fjärr Västra", detail: "42 s kvar" });
    expect(modeSaid(snapshot({ mode: "automatic" })).title).toBe("Automatik");
  });

  it("Lämna till … offers the station to the one chosen", () => {
    const onSend = vi.fn();
    const found = bar(snapshot(), onSend);
    const select = found.find((e) => e.type === "select");
    expect(textOf((select?.props.children as ReactNode) ?? "")).toContain("Fjärr Västra (fjärrställverk)");
    button(found, "Lämna").props.onClick();
    expect(onSend).toHaveBeenCalledWith("place.offer", { to: "fjarr-1" });
  });

  it("an offer can be withdrawn while it stands", () => {
    const onSend = vi.fn();
    const offered = snapshot({ mode: "offered", remote: { ...snapshot().remote, offer: { place: "exb", to: remoteInterlocking, expires_in: 42 } } as Snapshot["remote"] });
    const found = bar(offered, onSend);
    expect(found.some((e) => e.type === "select")).toBe(false);
    button(found, "Ta tillbaka erbjudandet").props.onClick();
    expect(onSend).toHaveBeenCalledWith("place.take_back", {});
  });

  it("Ta tillbaka asks first, then takes the station back (FR7)", () => {
    const onSend = vi.fn();
    const onAsking = vi.fn();
    const remote = snapshot({ mode: "remote", remote: { ...snapshot().remote, controller: remoteInterlocking, receivers: [] } as Snapshot["remote"] });
    button(bar(remote, onSend, false, onAsking), "Ta tillbaka").props.onClick();
    expect(onAsking).toHaveBeenCalledWith(true);
    expect(onSend).not.toHaveBeenCalled();
    const asked = bar(remote, onSend, true, onAsking);
    expect(textOf(asked.map((e) => e.props.children as ReactNode))).toContain("Ta tillbaka stationen från Fjärr Västra?");
    button(asked, "Ja, ta tillbaka").props.onClick();
    expect(onSend).toHaveBeenCalledWith("place.take_back", {});
  });

  it("a station without a catalogue cannot be offered", () => {
    const found = bar(snapshot({ remote: { ...snapshot().remote, controllable: false, receivers: [] } as Snapshot["remote"] }));
    expect(found.some((e) => e.type === "select")).toBe(false);
    expect(renderToStaticMarkup(<>{DriftformView({ snapshot: snapshot({ remote: { ...snapshot().remote, controllable: false } as Snapshot["remote"] }), busy: false, onSend: vi.fn(), to: "", asking: false, onTo: vi.fn(), onAsking: vi.fn() })}</>)).toContain("ingen fjärrkatalog");
  });
});

describe("the station row and the arrows", () => {
  const row = (shown: Snapshot | null, state: FjarrState, functions: FunctionShown[] = [LOCAL], more: { onAutomat?: () => void; onAsk?: () => void; onLocal?: () => void } = {}) =>
    elements(
      StationsradView({
        name: "Exempelby",
        signature: "EXB",
        specs: SPECS,
        state,
        functions,
        snapshot: shown,
        working: false,
        onAutomat: more.onAutomat ?? vi.fn(),
        onLocal: more.onLocal ?? vi.fn(),
        onAsk: more.onAsk ?? vi.fn(),
        allDay: false,
        onAllDay: vi.fn(),
      }),
    );

  it("orders A3, A2 and A1 first and colours a switched-on automat yellow (FR34, FR43)", () => {
    const { automats, locals } = stationRow(SPECS, fjarrState({ automats: [{ code: "A3", kind: "a3", by: "automat", since: "2026-11-19T09:00:00Z", trains: [], out: [] }] }), [LOCAL], null);
    expect(automats.map((a) => [a.code, a.on, a.colour])).toEqual([
      ["A3", true, ROW_COLOURS.on],
      ["A1", false, ROW_COLOURS.off],
      ["AN21", false, ROW_COLOURS.off],
    ]);
    expect(locals.map((l) => [l.code, l.on, l.fn])).toEqual([["L01", false, "Lokal frigivning"]]);
  });

  it("the name is blue when manned and grey when remote-controlled (FR32)", () => {
    const manned = renderToStaticMarkup(<>{StationsradView({ name: "Exempelby", signature: "EXB", specs: SPECS, state: fjarrState(), functions: [LOCAL], snapshot: snapshot(), working: false, onAutomat: vi.fn(), onLocal: vi.fn(), onAsk: vi.fn(), allDay: false, onAllDay: vi.fn() })}</>);
    expect(manned).toContain(`data-remote="nej" style="color:${ROW_COLOURS.manned}"`);
    expect(manned).toContain("EXB</b> EXEMPELBY");
    expect(manned).toContain(">G<");
    const remote = renderToStaticMarkup(<>{StationsradView({ name: "Exempelby", signature: "EXB", specs: SPECS, state: fjarrState({ controller: "Fjärr Västra" }), functions: [LOCAL], snapshot: null, working: false, onAutomat: vi.fn(), onLocal: vi.fn(), onAsk: vi.fn(), allDay: false, onAllDay: vi.fn() })}</>);
    expect(remote).toContain(`data-remote="ja" style="color:${ROW_COLOURS.remote}"`);
  });

  it("on the spot a code switches its automat; while remote-controlled the area is asked for", () => {
    const onAutomat = vi.fn();
    const onLocal = vi.fn();
    button(row(snapshot(), fjarrState(), [LOCAL], { onAutomat }), "A3").props.onClick();
    expect(onAutomat).toHaveBeenCalledWith("A3", true);
    button(row(snapshot(), fjarrState(), [LOCAL], { onLocal }), "L01").props.onClick();
    expect(onLocal).toHaveBeenCalledWith("Lokal frigivning", true);
    const onAsk = vi.fn();
    const remote = row(null, fjarrState({ controller: "Fjärr Västra" }), [LOCAL], { onAsk });
    expect(button(remote, "A3").props.disabled).toBe(true);
    button(remote, "L01").props.onClick();
    expect(onAsk).toHaveBeenCalledWith("local_release.request", { code: "L01", all_day: false });
    const given = row(null, fjarrState({ controller: "Fjärr Västra" }), [{ ...LOCAL, on: true }], { onLocal });
    expect(button(given, "L01").props.style?.color).toBe(ROW_COLOURS.local);
    button(given, "L01").props.onClick();
    expect(onLocal).toHaveBeenCalledWith("Lokal frigivning", false);
  });

  it("arrows only while remote-controlled: green where an automat lays the routes (FR33)", () => {
    const outside = { remote_routes: [{ id: "21-33", start: "21", end: "33", exit: "v", track: "3", direction: "in" }, { id: "22-32", start: "22", end: "32", exit: "o", track: "1", direction: "in" }] } as unknown as Outside;
    expect(arrowsOf(outside, SPECS, fjarrState(), false)).toEqual({});
    expect(arrowsOf(outside, SPECS, fjarrState(), true)).toEqual({ "21": "red", "22": "red" });
    const an = fjarrState({ automats: [{ code: "AN21", kind: "an", by: "remote", since: "2026-11-19T09:00:00Z", trains: [], out: [] }] });
    expect(arrowsOf(outside, SPECS, an, true)).toEqual({ "21": "green", "22": "red" });
    const a3 = fjarrState({ automats: [{ code: "A3", kind: "a3", by: "remote", since: "2026-11-19T09:00:00Z", trains: [], out: [] }] });
    expect(arrowsOf(outside, SPECS, a3, true)).toEqual({ "21": "green", "22": "green" });
  });
});

const candidate = (id: string, exit: string, direction: "in" | "out", track: string): RemoteCandidate => ({
  id,
  start: id.split("-")[0] ?? id,
  end: id.split("-")[1] ?? id,
  via: [],
  exit,
  exit_name: exit === "v" ? "Väster" : "Öster",
  track,
  track_label: `Spår ${track}`,
  direction,
  chosen: false,
});
const CANDIDATES = [candidate("In-12", "v", "in", "1"), candidate("In-22", "v", "in", "2"), candidate("12-Ut2", "o", "out", "1"), candidate("22-Ut2", "o", "out", "2")];

describe("Studio's catalogue", () => {
  it("is grouped by line end, in and out", () => {
    expect(grouped(CANDIDATES).map((g) => [g.name, g.into.map((c) => c.id), g.out.map((c) => c.id)])).toEqual([
      ["Väster", ["In-12", "In-22"], []],
      ["Öster", [], ["12-Ut2", "22-Ut2"]],
    ]);
  });

  it("has the quick choices alla, inga, alla utom ett spår and bara vissa spår (TKL46)", () => {
    expect(quick(CANDIDATES, { kind: "all" })).toEqual(["In-12", "In-22", "12-Ut2", "22-Ut2"]);
    expect(quick(CANDIDATES, { kind: "none" })).toEqual([]);
    expect(quick(CANDIDATES, { kind: "except", track: "2" })).toEqual(["In-12", "12-Ut2"]);
    expect(quick(CANDIDATES, { kind: "only", tracks: ["2"] })).toEqual(["In-22", "22-Ut2"]);
    expect(tracksOf(CANDIDATES)).toEqual([
      { id: "1", label: "Spår 1" },
      { id: "2", label: "Spår 2" },
    ]);
  });

  it("names a second automat of a kind by its entry signal (FR40)", () => {
    expect(codeFor("an", ["21"], [])).toBe("AN");
    expect(codeFor("an", ["121"], [{ code: "AN", kind: "an", signals: ["21"], default: false }])).toBe("AN121");
  });

  it("lists the routes with checkboxes, the chosen ones ticked", () => {
    const studio = {
      settings: { routes: ["In-12"], automats: SPECS, receivers: [] },
      kept: true,
      level: 2,
      candidates: CANDIDATES.map((c) => ({ ...c, chosen: c.id === "In-12" })),
      entry_signals: ["In", "In2"],
      functions: ["Lokal frigivning"],
      suggested: SPECS,
      problems: [],
      outside: null,
      note: null,
    } as unknown as Studio;
    const html = renderToStaticMarkup(<FjarrStudio initial={studio} />);
    expect(html).toContain("Fjärrkatalogen");
    expect(html).toContain("1 av 4 tågvägar i katalogen.");
    expect(html.match(/type="checkbox"/g)?.length).toBe(4 + 2);
    expect(html.match(/checked=""/g)?.length).toBe(1 + 2 + 1);
    expect(html).toContain("Tågväg in");
    expect(html).toContain("Tågväg ut");
    expect(specsOf(studio).map((a) => a.code)).toEqual(["A1", "A3", "AN21", "L01"]);
  });

  it("at level 0 says there is no catalogue (FR16)", () => {
    const html = renderToStaticMarkup(<FjarrStudio initial={{ settings: {}, kept: false, level: 0, note: "En station på nivå 0 har ingen fjärrkatalog (FR16)." } as unknown as Studio} />);
    expect(html).toContain("nivå 0");
    expect(html).not.toContain("type=\"checkbox\"");
  });
});
