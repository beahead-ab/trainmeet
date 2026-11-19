// Fjärrbilden (#36 del c): two made-up stations from an overview, drawn in the skin 95; the names
// grey and blue, the arrows at the main signals, the automat codes, locked, occupied and free, a
// route chosen from its start to its target that blinks until Lägg tågvägen, a no that leaves
// the picture as it was, Ta bort, the offers with the time left, a station that cannot be
// remote-controlled always manned, and the tab Fjärr in a station's own TKL. Nothing here names
// a real station (RS13).
import { isValidElement, type ReactElement, type ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import type { Snapshot } from "./api";
import { remoteTab } from "./App";
import { placesIn, readFjarrScreen } from "./Fjarr";
import { arrowOf, choose, COLOURS, drawPicture, fjarrHappenings, lineOrder, modeOf, reasonText, routeLabel, routesFrom, sentState, SKIN, timeLeft, type Choice } from "./fjarr";
import type { Fjarr, OverviewPlace, RemoteRouteHere } from "./fjarrapi";
import { FjarrbildView, Lagda, Vantar } from "./Fjarrbild";
import { STANDARD } from "./skal";

const ME = "remote-1";
const CONTEXT = { meet_id: "provmote", version: 1, game_day: 1, epoch: 0 };
const CLOCK = { time: "06:10:00", seconds: 22200, running: true, speed: 4, game_day: 1 };

/** A station with two tracks between an entry signal on each side, and a catalogue of four. */
function station(place: string, name: string, more: Partial<OverviewPlace> = {}): OverviewPlace {
  return {
    place: { place, code: name.slice(0, 3), name, phone: null },
    mode: "manned",
    controllable: true,
    controller: null,
    level: 2,
    heard: 3,
    outside: {
      format: "trainmeet.station-outside/1",
      station_id: place,
      name,
      tracks: [
        { id: "1", label: "Spår 1" },
        { id: "2", label: "Spår 2" },
      ],
      exits: [
        { id: "V", side: "left", name: "Väster", tracks: [], signals: [] },
        { id: "O", side: "right", name: "Öster", tracks: [], signals: [] },
      ],
      sides: [],
      parts: [],
      remote_routes: [
        { id: "11-1", start: "11", end: "1", exit: "V", track: "1", direction: "in" },
        { id: "11-2", start: "11", end: "2", exit: "V", track: "2", direction: "in" },
        { id: "12-1", start: "12", end: "1", exit: "O", track: "1", direction: "in" },
        { id: "12-2", start: "12", end: "2", exit: "O", track: "2", direction: "in" },
      ],
      automats: [
        { code: "A3", kind: "a3", default: true },
        { code: "L01", kind: "local_release", default: false },
      ],
      overview: {
        columns: 14,
        rows: 2,
        tracks: [
          { id: "v", row: 0, start: 0, end: 3, track: null, platform: false },
          { id: "t1", row: 0, start: 4, end: 10, track: "1", platform: true },
          { id: "o", row: 0, start: 11, end: 14, track: null, platform: false },
          { id: "t2", row: 1, start: 4, end: 10, track: "2", platform: false },
        ],
        links: [
          { id: "lv", from_row: 0, from_column: 3, to_row: 1, to_column: 4 },
          { id: "lo", from_row: 1, from_column: 10, to_row: 0, to_column: 11 },
        ],
        signals: [
          { name: "11", row: 0, column: 2, towards: "right" },
          { name: "12", row: 0, column: 12, towards: "left" },
        ],
        exits: [
          { exit: "V", row: 0, column: 0 },
          { exit: "O", row: 0, column: 14 },
        ],
        routes: { "11-1": ["v", "t1"], "11-2": ["v", "lv", "t2"], "12-1": ["o", "t1"], "12-2": ["o", "lo", "t2"] },
      },
      remote_receivers: [],
    },
    route_state: null,
    routes: [],
    trains: [],
    sections: [],
    ...more,
  };
}

const section = (id: string, other: string, more: Record<string, unknown> = {}) => ({ section: id, other_place: other, exit: null, occupied: false, detected: false, towards: null, train_number: null, ...more });
const asked = (request_id: string, route: string, state: RemoteRouteHere["state"], reason: string | null = null): RemoteRouteHere =>
  ({ request_id, route, call: null, train_number: null, state, reason, by: ME, asked_at: "06:10:00", answer_in: null }) as RemoteRouteHere;

/** Västby, remote-controlled from here, and Östby, manned, side by side along the line. */
function picture(west: Partial<OverviewPlace> = {}, east: Partial<OverviewPlace> = {}, more: Partial<Fjarr> = {}): Fjarr {
  return {
    overview: {
      protocol: "trainmeet.station/1",
      context: CONTEXT,
      clock: CLOCK,
      places: [
        station("oby", "Östby", { sections: [section("s1", "vby", { exit: "V" })], ...east }),
        station("vby", "Västby", { mode: "remote", controller: { client_id: ME, kind: "remote", name: "Fjärr", place: null }, sections: [section("s1", "oby", { exit: "O" })], ...west }),
      ],
    },
    client_id: ME,
    controls: ["vby"],
    offers: [],
    stale: false,
    heard: null,
    message: null,
    ...more,
  } as Fjarr;
}

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
const placeIn = (fjarr: Fjarr, id: string) => (fjarr.overview?.places ?? []).find((p) => p.place.place === id) as OverviewPlace;
const drawnAt = (fjarr: Fjarr, id: string, choice: Choice | null = null) => drawPicture(fjarr, choice).stations.find((s) => s.place === id);
const states = (fjarr: Fjarr, choice: Choice | null = null) =>
  Object.fromEntries(drawPicture(fjarr, choice).stations.flatMap((s) => [...s.tracks, ...s.links].map((p) => [`${s.place}:${p.id}`, p.state])));
const markup = (fjarr: Fjarr, choice: Choice | null = null) => renderToStaticMarkup(<FjarrbildView drawn={drawPicture(fjarr, choice)} onHit={() => undefined} />);
const panel = (fjarr: Fjarr, more: Partial<Parameters<typeof Vantar>[0]> = {}) => ({
  fjarr,
  choice: null,
  sent: [],
  notices: [],
  heardAt: 0,
  now: 0,
  busy: false,
  onLay: vi.fn(),
  onDrop: vi.fn(),
  onChoose: vi.fn(),
  onAgain: vi.fn(),
  onRemove: vi.fn(),
  onOffer: vi.fn(),
  ...more,
});

describe("the fjärrbild in the skin 95", () => {
  it("draws two stations from an overview, side by side along the line, on black", () => {
    const fjarr = picture();
    // Hubben lists Östby first, but the exits say Västby is to the west: read from left to right.
    expect(lineOrder(fjarr.overview?.places ?? []).map((p) => p.place.place)).toEqual(["vby", "oby"]);
    const drawn = drawPicture(fjarr);
    expect(drawn.stations.map((s) => s.place)).toEqual(["vby", "oby"]);
    const [west, east] = drawn.stations;
    expect(east?.x).toBeGreaterThan((west?.x ?? 0) + (west?.width ?? 0));
    // The line between them leaves by the coupled exits, Öster here and Väster there.
    const line = drawn.lines.find((l) => l.id === "s1");
    expect(line?.points[0]).toEqual([(west?.x ?? 0) + 14, west?.y]);
    expect(line?.points.at(-1)).toEqual([east?.x, east?.y]);
    // Exits no section leaves by get a short line with their name.
    expect(drawn.lines.filter((l) => l.label?.text === "Väster" || l.label?.text === "Öster")).toHaveLength(2);
    const svg = markup(fjarr);
    expect(svg).toContain(`fill="${STANDARD["95"].ground}"`);
    expect(svg).toContain(`stroke="${SKIN.tracks.free}" stroke-width="${SKIN.width}"`);
    expect(svg).toContain("ÖSTBY");
    expect(svg).toContain("VÄSTBY");
    // Main signals with their numbers, never switch numbers or dwarf signals (FR36).
    expect(svg.match(/data-signal="/g)).toHaveLength(4);
    expect(svg).not.toMatch(/dvsi|växel/i);
    expect(SKIN).toBe(STANDARD["95"]);
  });

  it("writes the name grey when remote-controlled and blue when manned (FR32)", () => {
    const drawn = drawPicture(picture());
    expect(drawn.stations.map((s) => [s.place, s.nameColour])).toEqual([
      ["vby", COLOURS.remote],
      ["oby", COLOURS.manned],
    ]);
    expect(COLOURS.manned).toBe("#4da3ff");
    expect(COLOURS.remote).toBe("#c4c8cc");
    const svg = markup(picture());
    expect(svg).toContain(`data-colour="${COLOURS.manned}"`);
    expect(svg).toContain(`data-colour="${COLOURS.remote}"`);
    const offered = drawnAt(picture({}, { mode: "offered" }), "oby");
    expect(offered?.nameColour).toBe(COLOURS.offered);
    expect(offered?.modeText).toBe("erbjuden");
  });

  it("puts a red arrow at the main signals while the controller lays the routes, green while an automat does, none when manned (FR33)", () => {
    const remote = picture();
    expect(arrowOf(placeIn(remote, "vby"))).toBe("remote");
    const svg = markup(remote);
    expect(svg.match(/data-arrow="remote"/g)).toHaveLength(2);
    expect(svg).toContain(`fill="${COLOURS.arrowRemote}"`);
    const automat = picture({ route_state: { locked: [], automats: [{ code: "A3", by: "remote" }], local_areas: [], occupied: [], part_requests: [], ready_to_send: [] } });
    expect(markup(automat).match(/data-arrow="automat"/g)).toHaveLength(2);
    expect(markup(automat)).toContain(`fill="${COLOURS.arrowAutomat}"`);
    // A local release alone lays no routes: the controller still does.
    const local = picture({ route_state: { locked: [], automats: [{ code: "L01", by: "remote" }], local_areas: [], occupied: [], part_requests: [], ready_to_send: [] } });
    expect(arrowOf(placeIn(local, "vby"))).toBe("remote");
    expect(drawnAt(remote, "oby")?.signals.every((s) => s.arrow === null)).toBe(true);
  });

  it("writes the automat codes at the name, yellow when on (FR34)", () => {
    const on = picture({ route_state: { locked: [], automats: [{ code: "A3", by: "station" }, { code: "L01", by: "remote" }], local_areas: [{ code: "L01", tracks: ["2"] }], occupied: [], part_requests: [], ready_to_send: [] } });
    const west = drawnAt(on, "vby");
    expect(west?.codes).toEqual([
      { code: "A3", on: true, local: false },
      { code: "L01", on: true, local: true },
    ]);
    const svg = markup(on);
    expect(svg).toMatch(new RegExp(`fill="${COLOURS.codeOn}" data-code="A3" data-on="ja"`));
    expect(svg).toMatch(new RegExp(`fill="${COLOURS.localOn}" data-code="L01" data-on="ja"`));
    expect(markup(picture())).toMatch(new RegExp(`fill="${COLOURS.codeOff}" data-code="A3" data-on="nej"`));
    // The local area's tracks are released: blue.
    expect(states(on)["vby:t2"]).toBe("local");
  });

  it("draws a locked route green, occupied red and free grey, and the train number red where the train is and green ahead (FR35)", () => {
    const fjarr = picture({
      route_state: { locked: [{ route: "11-1", by: "remote", request_id: "fj-1", automat: null }], automats: [], local_areas: [], occupied: [], part_requests: [], ready_to_send: [] },
      trains: [
        { track: "2", train_number: "4711", call: "c1", expected: false },
        { track: "1", train_number: "9103", call: "c2", expected: true },
      ],
    });
    expect(states(fjarr)).toMatchObject({ "vby:v": "train", "vby:t1": "train", "vby:t2": "occupied", "vby:lv": "free", "vby:o": "free" });
    const svg = markup(fjarr);
    expect(svg).toContain(`data-piece="t1" data-track="1" data-state="train" x1=`);
    expect(svg).toContain(`stroke="${SKIN.tracks.train}" stroke-width="${SKIN.stateWidth}"`);
    expect(svg).toContain(`stroke="${SKIN.tracks.occupied}" stroke-width="${SKIN.stateWidth}"`);
    expect(svg).toMatch(new RegExp(`data-number="4711" data-expected="nej"[^>]*fill="${SKIN.numbers.red}"`));
    expect(svg).toMatch(new RegExp(`data-number="9103" data-expected="ja"[^>]*fill="${SKIN.numbers.green}"`));
    // The start signal of the locked route shows proceed, its end nothing else.
    const signal = drawnAt(fjarr, "vby")?.signals.find((s) => s.name === "11");
    expect(signal?.aspect).toBe("proceed");
    // An occupied line is red with the train's number on it.
    const busy = picture({}, { sections: [section("s1", "vby", { exit: "V", occupied: true, train_number: "55", towards: "oby" })] });
    const line = drawPicture(busy).lines.find((l) => l.id === "s1");
    expect([line?.occupied, line?.number?.text, line?.arrow?.towards]).toEqual([true, "55", 1]);
  });
});

describe("a route from the catalogue (FR11, FR13)", () => {
  it("is chosen with its start and its target, blinks, and Lägg tågvägen sends it", () => {
    const fjarr = picture();
    // Only at a station TKL controls.
    expect(choose(fjarr, null, { kind: "signal", place: "oby", name: "11" })).toBeNull();
    const start = choose(fjarr, null, { kind: "signal", place: "vby", name: "11" });
    expect(start).toEqual({ place: "vby", start: "11", route: null });
    const west = drawnAt(fjarr, "vby", start);
    expect(west?.signals.find((s) => s.name === "11")?.chosen).toBe(true);
    expect(west?.tracks.filter((t) => t.target).map((t) => t.id)).toEqual(["t1", "t2"]);
    // A target that is no route from the start leaves the choice; one that is chooses the route.
    expect(choose(fjarr, start, { kind: "signal", place: "vby", name: "13" })).toEqual(start);
    const chosen = choose(fjarr, start, { kind: "track", place: "vby", piece: "t2", track: "2" });
    expect(chosen).toEqual({ place: "vby", start: "11", route: "11-2" });
    expect(states(fjarr, chosen)).toMatchObject({ "vby:v": "chosen", "vby:lv": "chosen", "vby:t2": "chosen", "vby:t1": "free" });
    expect(markup(fjarr, chosen)).toContain('class="fj-blink" data-piece="t2"');
    // The same start again drops the choice.
    expect(choose(fjarr, start, { kind: "signal", place: "vby", name: "11" })).toBeNull();
    const props = panel(fjarr, { choice: chosen });
    const found = elements(Vantar(props));
    expect(renderToStaticMarkup(<Vantar {...props} />)).toContain("11 → spår 2");
    button(found, "Lägg tågvägen").props.onClick();
    button(found, "Avbryt").props.onClick();
    expect(props.onLay).toHaveBeenCalledTimes(1);
    expect(props.onDrop).toHaveBeenCalledTimes(1);
    // With only the start chosen, the targets are buttons too.
    const targets = panel(fjarr, { choice: start });
    button(elements(Vantar(targets)), "11 → spår 1").props.onClick();
    expect(targets.onChoose).toHaveBeenCalledWith({ place: "vby", start: "11", route: "11-1" });
    // A route asked for or locked cannot be chosen again until it is gone.
    const busy = picture({ routes: [asked("fj-1", "11-1", "requested")] });
    expect(routesFrom(placeIn(busy, "vby"), "11").map((r) => r.id)).toEqual(["11-2"]);
    expect(routeLabel(null, "x-1")).toBe("x-1");
  });

  it("is shown as asked for until the station answers, and a no leaves the picture as it was (FR13, FR14)", () => {
    const before = picture({ route_state: { locked: [{ route: "11-1", by: "remote", request_id: "fj-1", automat: null }], automats: [], local_areas: [], occupied: [], part_requests: [], ready_to_send: [] }, routes: [asked("fj-1", "11-1", "locked")] });
    const sent = { request_id: "fj-2", place: "vby", route: "12-1", at: 0 };
    const waiting = picture({ ...placeIn(before, "vby"), routes: [asked("fj-2", "12-1", "requested"), asked("fj-1", "11-1", "locked")] } as Partial<OverviewPlace>);
    expect(sentState(waiting, sent)?.state).toBe("requested");
    expect(states(waiting)).toEqual(states(before));
    const props = panel(waiting, { sent: [sent] });
    expect(renderToStaticMarkup(<Vantar {...props} />)).toContain("Begärd · väntar på Västbys ställverk");
    const refused = picture({ ...placeIn(before, "vby"), routes: [asked("fj-2", "12-1", "refused", "conflicting_route"), asked("fj-1", "11-1", "locked")] } as Partial<OverviewPlace>);
    expect(sentState(refused, sent)).toMatchObject({ state: "refused", reason: "conflicting_route" });
    expect(reasonText("conflicting_route")).toBe("En fientlig väg är lagd.");
    expect(reasonText("station_not_answering")).toBe("Stationens ställverk svarar inte.");
    expect(states(refused)).toEqual(states(before));
    expect(fjarrHappenings(waiting, refused).map((h) => h.text)).toEqual(["Tågväg 12 → spår 1 nekad: En fientlig väg är lagd."]);
    // A no from Hubben out of contact may be tried again (FR28).
    const again = panel(refused, { notices: [{ id: "n", at: 0, text: "Nej: 12 → spår 1. Kontakten saknades.", again: { place: "vby", route: "12-1" } }] });
    const shown = renderToStaticMarkup(<Vantar {...again} />);
    expect(shown).toContain('role="alert"');
    button(elements(Vantar(again)), "Försök igen").props.onClick();
    expect(again.onAgain).toHaveBeenCalledWith("vby", "12-1");
  });

  it("is taken away with Ta bort, by its request", () => {
    const fjarr = picture({ route_state: { locked: [{ route: "11-1", by: "remote", request_id: "fj-1", automat: null }, { route: "12-2", by: "station", request_id: null, automat: null }], automats: [], local_areas: [], occupied: [], part_requests: [], ready_to_send: [] }, routes: [asked("fj-1", "11-1", "locked"), asked("fj-0", "12-1", "refused", "conflicting_route")] });
    const onRemove = vi.fn();
    const shown = renderToStaticMarkup(<Lagda fjarr={fjarr} busy={false} marked={null} onRemove={onRemove} />);
    expect(shown).toContain("11 → spår 1");
    expect(shown).not.toContain("12 → spår 1");
    const removes = elements(Lagda({ fjarr, busy: false, marked: null, onRemove })).filter((e) => e.type === "button");
    expect(removes).toHaveLength(1);
    button(removes, "Ta bort").props.onClick();
    expect(onRemove).toHaveBeenCalledWith("vby", "fj-1");
    // A piece of it can be clicked in the picture; the station's own route cannot be taken away.
    const west = drawnAt(fjarr, "vby");
    expect(west?.tracks.find((t) => t.id === "t1")?.mine).toBe("fj-1");
    expect(west?.tracks.find((t) => t.id === "t2")?.mine).toBeNull();
    expect(shown).toContain("styrs härifrån");
    // Taken back: the route stays until the train has gone (FR15), and only the station's own
    // interlocking releases it.
    const back = { ...fjarr, controls: [] } as Fjarr;
    expect(elements(Lagda({ fjarr: back, busy: false, marked: null, onRemove })).filter((e) => e.type === "button")).toHaveLength(0);
    expect(renderToStaticMarkup(<Lagda fjarr={back} busy={false} marked={null} onRemove={onRemove} />)).toContain("ligger kvar tills tåget har gått");
    const gone = picture({ routes: [asked("fj-1", "11-1", "cancelled")] });
    const released = picture({ routes: [asked("fj-1", "11-1", "released")] });
    expect(fjarrHappenings(fjarr, gone).map((h) => h.text)).toEqual(["Tågväg 11 → spår 1 borttagen"]);
    expect(fjarrHappenings(gone, released)).toEqual([]);
  });
});

describe("handing over (FR8) and the operating forms", () => {
  it("lists the offers with the time left, Ta emot and Avböj", () => {
    const fjarr = picture({}, {}, { offers: [{ place: "oby", to: { client_id: ME, kind: "remote", name: "Fjärr", place: null }, expires_in: 45 }] });
    const offer = fjarr.offers?.[0];
    expect(offer && timeLeft(offer, 1_000, 4_000)).toBe(42);
    expect(offer && timeLeft(offer, 0, 90_000)).toBe(0);
    const props = panel(fjarr, { heardAt: 1_000, now: 4_000 });
    expect(renderToStaticMarkup(<Vantar {...props} />)).toContain("<b>Östby</b> erbjuder sig<span class=\"liten\"> · 0:42 kvar</span>");
    const found = elements(Vantar(props));
    button(found, "Ta emot").props.onClick();
    button(found, "Avböj").props.onClick();
    expect((props.onOffer as ReturnType<typeof vi.fn>).mock.calls).toEqual([
      ["oby", true],
      ["oby", false],
    ]);
    const before = picture();
    expect(fjarrHappenings(before, fjarr).map((h) => h.text)).toEqual(["Östby erbjuder sig"]);
    const taken = picture({}, {}, { controls: ["vby", "oby"] });
    expect(fjarrHappenings(fjarr, taken).map((h) => h.text)).toEqual(["Östby fjärrstyrs härifrån"]);
  });

  it("shows a station that cannot be remote-controlled as manned, always (FR38)", () => {
    const fjarr = picture({ controllable: false, mode: "remote" });
    const west = placeIn(fjarr, "vby");
    expect(modeOf(west)).toBe("manned");
    expect(arrowOf(west)).toBeNull();
    const drawn = drawnAt(fjarr, "vby");
    expect([drawn?.mode, drawn?.nameColour, drawn?.signals.some((s) => s.arrow)]).toEqual(["manned", COLOURS.manned, false]);
    expect(renderToStaticMarkup(<Lagda fjarr={fjarr} busy={false} marked={null} onRemove={() => undefined} />)).toContain("Bemannad");
  });

  it("stands the stations in a grid read from left to right, with a reference at both ends of a line that wraps (FR48)", () => {
    const names = ["Ett", "Två", "Tre", "Fyra", "Fem", "Sex"];
    const ids = names.map((n) => n.toLowerCase().replace("å", "a"));
    const places = names.map((name, i) =>
      station(ids[i] ?? "", name, {
        sections: [
          ...(i > 0 ? [section(`s${i}`, ids[i - 1] ?? "", { exit: "V" })] : []),
          ...(i < names.length - 1 ? [section(`s${i + 1}`, ids[i + 1] ?? "", { exit: "O" })] : []),
        ],
      }),
    );
    const fjarr = { overview: { protocol: "trainmeet.station/1", context: CONTEXT, clock: CLOCK, places }, client_id: ME, controls: [], offers: [] } as unknown as Fjarr;
    const drawn = drawPicture(fjarr);
    const rows = [...new Set(drawn.stations.map((s) => s.y))];
    expect(rows).toHaveLength(2);
    // Fourteen columns and a gap of six: four stations fill a row of ninety cells.
    expect(drawn.stations.filter((s) => s.y === rows[0]).map((s) => s.name)).toEqual(["Ett", "Två", "Tre", "Fyra"]);
    const wrapped = drawn.lines.filter((l) => l.id.startsWith("s4:"));
    expect(wrapped.map((l) => l.label?.text)).toEqual(["Fem · rad 2 ▶", "▶ Fyra · rad 1"]);
    expect(drawn.lines.find((l) => l.id === "s3")?.label).toBeNull();
  });
});

describe("the remote role and the station's own TKL", () => {
  it("shows the tab Fjärr while the station controls a neighbour or one is offered to it (FR3)", () => {
    const snapshot = (more: Partial<Snapshot>) => ({ controls: [], offers: [], ...more }) as unknown as Snapshot;
    expect(remoteTab(null)).toBe(false);
    expect(remoteTab(snapshot({}))).toBe(false);
    expect(remoteTab(snapshot({ controls: ["vby"] }))).toBe(true);
    expect(remoteTab(snapshot({ offers: [{ place: "vby", to: { client_id: "tkl-1", kind: "tkl", name: "Östby", place: "oby" }, expires_in: 50 }] }))).toBe(true);
  });

  it("reads the remote area written by hand, and keeps each screen's view", () => {
    expect(placesIn(" vby, oby;mby  vby ")).toEqual(["vby", "oby", "mby"]);
    expect(readFjarrScreen(1, { getItem: () => "bild" })).toBe("bild");
    expect(readFjarrScreen(2, { getItem: () => null })).toBe("allt");
    expect(readFjarrScreen(3, null)).toBe("allt");
  });
});
