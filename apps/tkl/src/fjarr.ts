// Fjärrbilden (#36 del c, FR31–FR38, FR47, FR48): the remote area and its neighbours in the
// overview, worked out from Hubben's Overview alone. Every station draws its outside's overview:
// the tracks, switches as lines, and main signals that are controlled centrally, never switch
// numbers, dwarf signals or shunting routes (FR36). It draws only what the station reports in
// route.state, never what was sent (FR13): a locked route green, occupied red, free grey, and the
// train number red where the train is and green ahead (FR35). The station's name is grey when it
// is remote-controlled and blue when it is manned (FR32), a station that cannot be
// remote-controlled is always manned (FR38), the main signals have an arrow, red while the
// controller lays the routes and green while an automat does (FR33), and the automat codes stand
// at the name, yellow when on (FR34). The look is the skin 95 on black, the station's own 95
// entry in skal.ts (FR47). The stations stand in a grid read from left to right, about three rows
// to a screen; a line that does not fit on its row continues on a later one, with a reference at
// both ends (FR48).
//
// A route is chosen with a click on its start and one on its target, only from a station's
// remote catalogue (FR11). It blinks until Lägg tågvägen sends it (FR13). Pure functions, so the
// picture and its tests read the same thing. Nothing here names a station (RS13).
import type { Fjarr, OfferHere, OverviewPlace, PlaceMode, RemoteRoute, RemoteRouteHere, SectionOverview } from "./fjarrapi";
import { STANDARD, type Skin } from "./skal";

/** The skin 95, exactly as the station's own picture has it (FR47). */
export const SKIN: Skin = STANDARD["95"];

/** The name's colour for each operating form (FR32), and the codes' (FR34), in 95's colours. */
export const COLOURS = {
  remote: SKIN.signalId,
  manned: SKIN.tracks.local,
  offered: SKIN.tracks.shunting,
  noContact: SKIN.tracks.occupied,
  codeOn: SKIN.tracks.shunting,
  codeOff: "#6b7075",
  localOn: SKIN.tracks.local,
  arrowRemote: SKIN.tracks.occupied,
  arrowAutomat: SKIN.tracks.train,
} as const;

export const MODE_TEXT: Record<PlaceMode, string> = {
  manned: "bemannad",
  offered: "erbjuden",
  remote: "fjärrstyrd",
  no_contact: "kontakt saknas",
  automatic: "automatik",
};

/** What the station's interlocking, or Hubben, says when it says no, as TEXT_SV has it. */
export const REASONS: Record<string, string> = {
  conflicting_route: "En fientlig väg är lagd.",
  switch_not_in_control: "Växlarna ligger inte i kontroll.",
  area_released: "Området är lokalt frigivet.",
  track_occupied: "Spåret är upptaget av ett annat tåg.",
  station_not_answering: "Stationens ställverk svarar inte.",
  not_controller: "Du styr inte driftplatsen.",
  not_in_catalog: "Tågvägen finns inte i stationens fjärrkatalog.",
  route_already_requested: "Tågvägen är redan begärd.",
  route_not_pending: "Begäran om tågvägen finns inte, eller gäller inte längre.",
  offer_not_pending: "Erbjudandet gäller inte längre.",
  no_contact: "Kontakten med den som fjärrstyr saknades. Inga nya tågvägar gick under tiden. Läs om läget och försök igen.",
};

export const reasonText = (reason: string | null | undefined): string => (reason ? (REASONS[reason] ?? reason) : "Nej.");

// --- The grid (FR48) -------------------------------------------------------------------------

/** Cells around the picture, between two stations on a row, above a station for its name, and
 * between two rows of stations. */
const MARGIN = 2;
const GAP = 6;
const HEADER = 2.6;
/** The height of one of the overview's rows, in cells: the tracks stand further apart than the
 * columns, as in the station's own picture, so that a signal's number and arrow fit between. */
export const ROW_STEP = 1.8;
const ROW_GAP = 2.4;
/** A station without an overview (no catalogue, or an older TKL): its name over a short line. */
const PLAIN = { columns: 8, rows: 1 };
/** A row's width in cells: three or four stations to a row, so that a screen holds about three
 * rows (FR48), as in the concept's overview. */
const ROW_WIDTH = 90;

export type PieceState = "free" | "train" | "occupied" | "local" | "chosen";
export type Point = [number, number];

export type DrawnTrack = { id: string; x1: number; x2: number; y: number; state: PieceState; track: string | null; label: string | null; platform: boolean; target: boolean; mine: string | null };
export type DrawnLink = { id: string; x1: number; y1: number; x2: number; y2: number; state: PieceState; mine: string | null };
export type DrawnSignal = { name: string; x: number; y: number; towards: 1 | -1; aspect: "stop" | "proceed"; end: boolean; arrow: "remote" | "automat" | null; start: boolean; chosen: boolean; target: boolean };
export type DrawnNumber = { text: string; x: number; y: number; expected: boolean };
export type DrawnCode = { code: string; on: boolean; local: boolean };
export type DrawnExit = { exit: string; x: number; y: number; start: boolean };
export type DrawnStation = {
  place: string;
  name: string;
  code: string;
  x: number;
  y: number;
  width: number;
  height: number;
  mode: PlaceMode;
  nameColour: string;
  modeText: string;
  codes: DrawnCode[];
  mine: boolean;
  plain: boolean;
  tracks: DrawnTrack[];
  links: DrawnLink[];
  signals: DrawnSignal[];
  numbers: DrawnNumber[];
  exits: DrawnExit[];
};
export type DrawnLine = { id: string; points: Point[]; occupied: boolean; number: { text: string; x: number; y: number } | null; label: { text: string; x: number; y: number; anchor: "start" | "end" } | null; arrow: { x: number; y: number; towards: 1 | -1 } | null };
/** The picture in cells, from x0: a reference may stand left of the first station on a row. */
export type Drawn = { x0: number; width: number; height: number; stations: DrawnStation[]; lines: DrawnLine[] };

/** The chosen route, before it is sent: its station, its start, and the route once a target is
 * chosen (FR13). */
export type Choice = { place: string; start: string; route: string | null };
/** A route TKL asked for, until the station's answer is in the picture. */
export type Sent = { request_id: string; place: string; route: string; at: number };

const placesOf = (fjarr: Fjarr | null): OverviewPlace[] => fjarr?.overview?.places ?? [];
const catalogue = (place: OverviewPlace): RemoteRoute[] => place.outside?.remote_routes ?? [];

/** The places in the order of the line: from an end, along the sections, so that neighbours
 * stand next to each other; anything left over after them, in Hubben's order. */
export function lineOrder(places: OverviewPlace[]): OverviewPlace[] {
  const byId = new Map(places.map((p) => [p.place.place, p]));
  const next = new Map<string, string[]>();
  for (const p of places) next.set(p.place.place, (p.sections ?? []).map((s) => s.other_place).filter((o) => byId.has(o) && o !== p.place.place));
  const seen = new Set<string>();
  const order: OverviewPlace[] = [];
  const walk = (id: string) => {
    if (seen.has(id)) return;
    seen.add(id);
    const found = byId.get(id);
    if (found) order.push(found);
    for (const o of next.get(id) ?? []) walk(o);
  };
  for (const p of places) if ((next.get(p.place.place) ?? []).length <= 1) walk(p.place.place);
  for (const p of places) walk(p.place.place);
  // Read from left to right: the exits say which way the line runs (FR48).
  const sideOf = (place: OverviewPlace, other: string): number => {
    const exit = (place.sections ?? []).find((s) => s.other_place === other)?.exit;
    const side = (place.outside?.exits ?? []).find((e) => e.id === exit)?.side;
    return side === "right" ? 1 : side === "left" ? -1 : 0;
  };
  let votes = 0;
  for (let i = 0; i + 1 < order.length; i += 1) {
    const [a, b] = [order[i] as OverviewPlace, order[i + 1] as OverviewPlace];
    votes += sideOf(a, b.place.place) - sideOf(b, a.place.place);
  }
  return votes < 0 ? order.reverse() : order;
}

/** A place's operating form as the picture shows it: never remote unless it can be (FR38). */
export function modeOf(place: OverviewPlace): PlaceMode {
  if (!place.controllable && (place.mode === "remote" || place.mode === "offered")) return "manned";
  return place.mode;
}

export function nameColour(mode: PlaceMode): string {
  if (mode === "manned") return COLOURS.manned;
  if (mode === "offered") return COLOURS.offered;
  if (mode === "no_contact") return COLOURS.noContact;
  return COLOURS.remote;
}

/** The arrow at the main signals (FR33): red while the one who remote-controls lays the routes,
 * green while a station automat does, none at a manned station. */
export function arrowOf(place: OverviewPlace): "remote" | "automat" | null {
  const mode = modeOf(place);
  const automat = (place.route_state?.automats ?? []).some((a) => !/^L/i.test(a.code));
  if (mode === "manned" || mode === "offered") return null;
  if (automat) return "automat";
  if (mode === "automatic" || !place.controller) return null;
  return "remote";
}

export function modeText(place: OverviewPlace, me: string | null): string {
  const mode = modeOf(place);
  if (mode === "remote" && place.controller) return place.controller.client_id === me ? "fjärrstyrd härifrån" : `fjärrstyrd från ${place.controller.name}`;
  return MODE_TEXT[mode];
}

/** The routes TKL asked for at a place and that stand, locked or waiting for the answer. */
export function myRoutes(place: OverviewPlace, me: string | null): RemoteRouteHere[] {
  return (place.routes ?? []).filter((r) => r.by === me && (r.state === "locked" || r.state === "requested"));
}

/** The catalogue routes locked in the station's interlocking, as its route.state says (FR13). */
export function lockedRoutes(place: OverviewPlace): string[] {
  return (place.route_state?.locked ?? []).map((r) => r.route);
}

/** A catalogue route asked for or locked may not be chosen again until it is gone. */
function busy(place: OverviewPlace): Set<string> {
  const asked = (place.routes ?? []).filter((r) => r.state === "requested" || r.state === "locked").map((r) => r.route);
  return new Set([...asked, ...lockedRoutes(place)]);
}

/** The routes TKL may choose from a start at a place it controls. */
export function routesFrom(place: OverviewPlace, start: string): RemoteRoute[] {
  const taken = busy(place);
  return catalogue(place).filter((r) => r.start === start && !taken.has(r.id));
}

export type Hit = { kind: "signal"; place: string; name: string } | { kind: "track"; place: string; piece: string; track: string | null } | { kind: "exit"; place: string; exit: string };

/** The starts at a place that are not a drawn signal, such as A1 at a station without signals:
 * chosen at the exit they come in from. */
function startsAtExit(place: OverviewPlace, exit: string): string[] {
  const drawn = new Set((place.outside?.overview?.signals ?? []).map((s) => s.name));
  return [...new Set(catalogue(place).filter((r) => r.exit === exit && r.direction === "in" && !drawn.has(r.start)).map((r) => r.start))];
}

/** A click in the picture (FR11, FR13): a start, then a target that makes a catalogue route from
 * it. Only at a station TKL controls; anything else leaves the choice as it was. */
export function choose(fjarr: Fjarr | null, choice: Choice | null, hit: Hit): Choice | null {
  const place = placesOf(fjarr).find((p) => p.place.place === hit.place);
  if (!place || !(fjarr?.controls ?? []).includes(hit.place)) return choice;
  const pieces = place.outside?.overview?.routes ?? {};
  if (choice && choice.place === hit.place && choice.route === null) {
    const from = routesFrom(place, choice.start);
    const found =
      hit.kind === "signal"
        ? from.find((r) => r.end === hit.name)
        : hit.kind === "track"
          ? (from.find((r) => r.track === hit.track && (pieces[r.id] ?? []).includes(hit.piece)) ?? from.find((r) => r.track === hit.track && r.direction === "in"))
          : from.find((r) => r.exit === hit.exit && r.direction === "out");
    if (found) return { ...choice, route: found.id };
    if (hit.kind === "signal" && hit.name === choice.start) return null;
  }
  const starts = hit.kind === "signal" ? [hit.name] : hit.kind === "exit" ? startsAtExit(place, hit.exit) : [];
  const start = starts.find((s) => routesFrom(place, s).length > 0);
  if (start) return { place: hit.place, start, route: null };
  return choice;
}

export function routeOf(fjarr: Fjarr | null, place: string, route: string): RemoteRoute | null {
  const found = placesOf(fjarr).find((p) => p.place.place === place);
  return found ? (catalogue(found).find((r) => r.id === route) ?? null) : null;
}

export function routeLabel(route: RemoteRoute | null, id: string): string {
  if (!route) return id;
  const target = route.end === route.track ? `spår ${route.track}` : `${route.end}, spår ${route.track}`;
  return route.direction === "in" ? `${route.start} → ${target}` : `${route.start} (spår ${route.track}) → ${route.end}`;
}

/** How a route TKL sent stands now, as the picture has it; null before Hubben lists it. */
export function sentState(fjarr: Fjarr | null, sent: Sent): RemoteRouteHere | null {
  const place = placesOf(fjarr).find((p) => p.place.place === sent.place);
  return (place?.routes ?? []).find((r) => r.request_id === sent.request_id) ?? null;
}

/** Seconds left of an offer's minute (FR8), counted from when the picture was read. */
export function timeLeft(offer: OfferHere, heard: number, now: number): number {
  return Math.max(0, Math.round(offer.expires_in - (now - heard) / 1000));
}

export const clockText = (seconds: number): string => `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;

// --- Drawing ----------------------------------------------------------------------------------

type Block = { place: OverviewPlace; columns: number; rows: number; x: number; y: number; row: number };

function blocksOf(order: OverviewPlace[]): { blocks: Block[]; width: number; height: number } {
  const sizes = order.map((p) => p.outside?.overview ?? PLAIN);
  const limit = Math.max(...sizes.map((s) => s.columns), ROW_WIDTH);
  const blocks: Block[] = [];
  let x = MARGIN;
  let row = 0;
  let width = 0;
  order.forEach((place, i) => {
    const size = sizes[i] ?? PLAIN;
    if (x > MARGIN && x - MARGIN + size.columns > limit) {
      row += 1;
      x = MARGIN;
    }
    blocks.push({ place, columns: size.columns, rows: size.rows, x, y: 0, row });
    width = Math.max(width, x + size.columns);
    x += size.columns + GAP;
  });
  let top = MARGIN;
  for (let r = 0; r <= row; r += 1) {
    const here = blocks.filter((b) => b.row === r);
    const tall = Math.max(1, ...here.map((b) => (b.rows - 1) * ROW_STEP + 1));
    for (const b of here) b.y = top + HEADER;
    top += HEADER + tall + ROW_GAP;
  }
  return { blocks, width: width + MARGIN, height: top };
}

/** The station's own drawing, with the states of the moment. */
function station(block: Block, fjarr: Fjarr | null, choice: Choice | null): DrawnStation {
  const place = block.place;
  const id = place.place.place;
  const me = fjarr?.client_id ?? null;
  const mode = modeOf(place);
  const drawing = place.outside?.overview ?? null;
  const pieces = drawing?.routes ?? {};
  const routes = catalogue(place);
  const state = place.route_state;
  const locked = lockedRoutes(place);
  const lockedPieces = new Set(locked.flatMap((r) => pieces[r] ?? []));
  const mineByPiece = new Map<string, string>();
  for (const r of myRoutes(place, me)) if (r.state === "locked") for (const p of pieces[r.route] ?? []) mineByPiece.set(p, r.request_id);
  const chosenHere = choice && choice.place === id ? choice : null;
  const chosenPieces = new Set(chosenHere?.route ? (pieces[chosenHere.route] ?? []) : []);
  const targets = chosenHere && !chosenHere.route ? routesFrom(place, chosenHere.start) : [];
  const present = (place.trains ?? []).filter((t) => !t.expected).map((t) => t.track);
  const occupied = new Set([...(state?.occupied ?? []), ...present]);
  const local = new Set((state?.local_areas ?? []).flatMap((a) => a.tracks ?? []));
  // What the station reports first: a chosen route never hides an occupied track.
  const stateOf = (piece: string, track: string | null): PieceState => {
    if (track && occupied.has(track)) return "occupied";
    if (chosenPieces.has(piece)) return "chosen";
    if (lockedPieces.has(piece)) return "train";
    if (track && local.has(track)) return "local";
    return "free";
  };
  const at = (column: number, row: number): Point => [block.x + column, block.y + row * ROW_STEP];
  const labels = new Map((place.outside?.tracks ?? []).map((t) => [t.id, t.id]));
  const tracks: DrawnTrack[] = (drawing?.tracks ?? []).map((t) => {
    const [x1, y] = at(t.start, t.row);
    const track = t.track ?? null;
    return {
      id: t.id,
      x1,
      x2: x1 + (t.end - t.start),
      y,
      state: stateOf(t.id, track),
      track,
      label: track ? (labels.get(track) ?? track) : null,
      platform: !!t.platform,
      target: targets.some((r) => r.track === track && (pieces[r.id] ?? []).includes(t.id)),
      mine: mineByPiece.get(t.id) ?? null,
    };
  });
  const links: DrawnLink[] = (drawing?.links ?? []).map((l) => {
    const [x1, y1] = at(l.from_column, l.from_row);
    const [x2, y2] = at(l.to_column, l.to_row);
    return { id: l.id, x1, y1, x2, y2, state: chosenPieces.has(l.id) ? "chosen" : lockedPieces.has(l.id) ? "train" : "free", mine: mineByPiece.get(l.id) ?? null };
  });
  const starts = new Set(locked.map((r) => routes.find((c) => c.id === r)?.start).filter((s): s is string => !!s));
  const ends = new Set(locked.map((r) => routes.find((c) => c.id === r)?.end).filter((s): s is string => !!s));
  const arrow = arrowOf(place);
  const mine = (fjarr?.controls ?? []).includes(id);
  const signals: DrawnSignal[] = (drawing?.signals ?? []).map((s) => {
    const [x, y] = at(s.column, s.row);
    return {
      name: s.name,
      x,
      y,
      towards: s.towards === "left" ? -1 : 1,
      aspect: starts.has(s.name) ? "proceed" : "stop",
      end: ends.has(s.name) && !starts.has(s.name),
      arrow,
      start: mine && routesFrom(place, s.name).length > 0,
      chosen: chosenHere?.start === s.name,
      target: targets.some((r) => r.end === s.name),
    };
  });
  const exits: DrawnExit[] = (drawing?.exits ?? []).map((e) => {
    const [x, y] = at(e.column, e.row);
    return { exit: e.exit, x, y, start: mine && startsAtExit(place, e.exit).some((s) => routesFrom(place, s).length > 0) };
  });
  // The train numbers: red where the train is, green for the one expected (FR35), over the
  // longest piece of its track.
  const numbers: DrawnNumber[] = [];
  for (const train of place.trains ?? []) {
    const longest = tracks.filter((t) => t.track === train.track).sort((a, b) => b.x2 - b.x1 - (a.x2 - a.x1))[0];
    if (!longest) continue;
    const over = numbers.filter((n) => Math.abs(n.y - (longest.y - 0.35)) < 0.1 && n.x > longest.x1 && n.x <= longest.x2).length;
    numbers.push({ text: train.train_number, x: longest.x2 - 0.6 - over * 3.4, y: longest.y - 0.35, expected: train.expected });
  }
  const on = new Set((state?.automats ?? []).map((a) => a.code));
  const codes = (place.outside?.automats ?? []).map((a) => ({ code: a.code, on: on.has(a.code), local: a.kind === "local_release" }));
  return {
    place: id,
    name: place.place.name,
    code: place.place.code,
    x: block.x,
    y: block.y,
    width: block.columns,
    height: block.rows,
    mode,
    nameColour: nameColour(mode),
    modeText: modeText(place, me),
    codes,
    mine,
    plain: !drawing,
    tracks,
    links,
    signals,
    numbers,
    exits,
  };
}

/** Where a station's line to a section leaves its drawing: the exit Hubben coupled to the
 * section, else the first exit on the side the other station stands on. */
function exitPoint(drawn: DrawnStation, place: OverviewPlace, section: SectionOverview, side: "left" | "right" | null): DrawnExit | null {
  const exits = drawn.exits;
  const coupled = section.exit ? exits.find((e) => e.exit === section.exit) : undefined;
  if (coupled) return coupled;
  if (!side) return null;
  const sides = new Map((place.outside?.exits ?? []).map((e) => [e.id, e.side]));
  const facing = exits.filter((e) => sides.get(e.exit) === side).sort((a, b) => a.y - b.y)[0];
  if (facing) return facing;
  if (drawn.plain) return { exit: "", x: side === "left" ? drawn.x : drawn.x + drawn.width, y: drawn.y, start: false };
  return null;
}

/** The whole picture: the stations in the grid, the lines between them and the line ends. */
export function drawPicture(fjarr: Fjarr | null, choice: Choice | null = null): Drawn {
  const order = lineOrder(placesOf(fjarr));
  const { blocks, width, height } = blocksOf(order);
  const stations = blocks.map((b) => station(b, fjarr, choice));
  const byPlace = new Map(stations.map((s, i) => [s.place, { drawn: s, block: blocks[i] as Block, index: i }]));
  // A station without an overview stands on the line of the neighbour next to it on its row.
  for (const [index, block] of blocks.entries()) {
    const plain = stations[index] as DrawnStation;
    if (!plain.plain) continue;
    for (const section of block.place.sections ?? []) {
      const other = byPlace.get(section.other_place);
      if (!other || other.drawn.plain || other.block.row !== block.row || Math.abs(other.index - index) !== 1) continue;
      const back = (other.block.place.sections ?? []).find((s) => s.section === section.section);
      const end = back ? exitPoint(other.drawn, other.block.place, back, other.drawn.x > plain.x ? "left" : "right") : null;
      if (end) {
        plain.y = end.y;
        break;
      }
    }
  }
  const lines: DrawnLine[] = [];
  const used = new Map<string, Set<string>>();
  const use = (place: string, exit: string) => used.set(place, new Set([...(used.get(place) ?? []), exit]));
  const done = new Set<string>();
  const ahead = (towards: string | null, end: string): boolean => towards === end;
  for (const [index, block] of blocks.entries()) {
    const here = stations[index] as DrawnStation;
    for (const section of block.place.sections ?? []) {
      if (done.has(section.section)) continue;
      done.add(section.section);
      const other = byPlace.get(section.other_place);
      if (!other) {
        const number = section.train_number;
        // A line to a place not in the picture: a short line from the exit, with its name.
        const out = exitPoint(here, block.place, section, null);
        if (!out) continue;
        use(here.place, out.exit);
        const dir = out.x <= here.x + 0.01 ? -1 : 1;
        const end: Point = [out.x + dir * 3, out.y];
        const exitName = block.place.outside?.exits.find((e) => e.id === out.exit)?.name;
        lines.push({
          id: section.section,
          points: [[out.x, out.y], end],
          occupied: section.occupied,
          number: number ? { text: number, x: out.x + dir * 1.5, y: out.y - 0.35 } : null,
          label: { text: exitName ?? `mot ${section.other_place}`, x: end[0] + dir * 0.3, y: end[1] + 0.2, anchor: dir < 0 ? "end" : "start" },
          arrow: section.towards ? { x: out.x + dir * (ahead(section.towards, here.place) ? 0.6 : 2.4), y: out.y, towards: ahead(section.towards, here.place) ? (-dir as 1 | -1) : (dir as 1 | -1) } : null,
        });
        continue;
      }
      const there = other.drawn;
      const back = (other.block.place.sections ?? []).find((s) => s.section === section.section) ?? { ...section, exit: null };
      const neighbours = Math.abs(other.index - index) === 1 && other.block.row === block.row;
      // Either end may know the train on the line.
      const occupied = section.occupied || back.occupied;
      const number = section.train_number ?? back.train_number;
      const towards = section.towards ?? back.towards;
      const [left, right, leftPlace, rightPlace, leftSection, rightSection] =
        index <= other.index ? [here, there, block.place, other.block.place, section, back] : [there, here, other.block.place, block.place, back, section];
      const a = exitPoint(left, leftPlace, leftSection, "right");
      const b = exitPoint(right, rightPlace, rightSection, "left");
      if (!a || !b) continue;
      use(left.place, a.exit);
      use(right.place, b.exit);
      if (neighbours) {
        const mid = (a.x + b.x) / 2;
        const points: Point[] = a.y === b.y ? [[a.x, a.y], [b.x, b.y]] : [[a.x, a.y], [mid - 0.5, a.y], [mid + 0.5, b.y], [b.x, b.y]];
        const towardsRight = ahead(towards, right.place);
        lines.push({
          id: section.section,
          points,
          occupied,
          number: number ? { text: number, x: mid, y: Math.min(a.y, b.y) - 0.35 } : null,
          label: null,
          arrow: towards ? { x: towardsRight ? b.x - 0.8 : a.x + 0.8, y: towardsRight ? b.y : a.y, towards: towardsRight ? 1 : -1 } : null,
        });
      } else {
        // Not next to each other on a row (FR48): a line from each end, with a reference to the
        // other station and its row.
        const rowOf = (s: DrawnStation) => (byPlace.get(s.place)?.block.row ?? 0) + 1;
        lines.push({
          id: `${section.section}:a`,
          points: [[a.x, a.y], [a.x + 2.5, a.y]],
          occupied,
          number: number ? { text: number, x: a.x + 1.2, y: a.y - 0.35 } : null,
          label: { text: `${right.name} · rad ${rowOf(right)} ▶`, x: a.x + 2.8, y: a.y + 0.2, anchor: "start" },
          arrow: null,
        });
        lines.push({
          id: `${section.section}:b`,
          points: [[b.x - 2.5, b.y], [b.x, b.y]],
          occupied,
          number: null,
          label: { text: `▶ ${left.name} · rad ${rowOf(left)}`, x: b.x - 2.8, y: b.y + 0.2, anchor: "end" },
          arrow: null,
        });
      }
    }
  }
  // Exits no section leaves by: a short line with the exit's name (Benny: the line's end).
  for (const [index, block] of blocks.entries()) {
    const here = stations[index] as DrawnStation;
    const named = new Map((block.place.outside?.exits ?? []).map((e) => [e.id, e]));
    for (const out of here.exits) {
      if (used.get(here.place)?.has(out.exit)) continue;
      const dir = named.get(out.exit)?.side === "left" ? -1 : 1;
      const end: Point = [out.x + dir * 1.6, out.y];
      // No name where it would run into the station next to it on the row.
      const crowded = stations.some((s) => s !== here && s.y === here.y && (dir > 0 ? s.x > out.x && s.x - out.x < GAP + 2 : out.x > s.x + s.width && out.x - s.x - s.width < GAP + 2));
      lines.push({
        id: `${here.place}:${out.exit}`,
        points: [[out.x, out.y], end],
        occupied: false,
        number: null,
        label: crowded ? null : { text: named.get(out.exit)?.name ?? out.exit, x: end[0] + dir * 0.3, y: end[1] + 0.2, anchor: dir < 0 ? "end" : "start" },
        arrow: null,
      });
    }
  }
  // The picture holds every reference and line end, with their names (about half a cell a letter).
  let x0 = 0;
  let x1 = width;
  for (const line of lines) {
    for (const [x] of line.points) {
      x0 = Math.min(x0, x - 0.5);
      x1 = Math.max(x1, x + 0.5);
    }
    if (!line.label) continue;
    const long = line.label.text.length * 0.32 + 0.5;
    if (line.label.anchor === "end") x0 = Math.min(x0, line.label.x - long);
    else x1 = Math.max(x1, line.label.x + long);
  }
  return { x0, width: x1 - x0, height, stations, lines };
}

/** The colour of a piece in 95: the state's, and the chosen route green, blinking. */
export function pieceColour(state: PieceState): string {
  return state === "chosen" ? SKIN.tracks.train : SKIN.tracks[state];
}

export function pieceWidth(state: PieceState): number {
  return state === "free" ? SKIN.width : SKIN.stateWidth;
}

// --- Händelser (FR37 at the remote interlocking): what changed between two pictures --------------

export type FjarrHappening = { id: string; time: string; text: string; place: string };

/** What happened between two pictures, latest first: offers, what TKL controls, the stations'
 * answers to its routes, and the operating forms. None the first time. */
export function fjarrHappenings(before: Fjarr | null, now: Fjarr): FjarrHappening[] {
  if (!before?.overview || !now.overview) return [];
  const time = now.overview.clock.time.slice(0, 5);
  const found: FjarrHappening[] = [];
  const names = new Map(placesOf(now).map((p) => [p.place.place, p.place.name]));
  const name = (place: string) => names.get(place) ?? place;
  const add = (id: string, place: string, text: string) => found.push({ id: `${id}:${time}:${found.length}`, time, text, place });
  const offered = new Set((before.offers ?? []).map((o) => o.place));
  for (const offer of now.offers ?? []) if (!offered.has(offer.place)) add(`offer:${offer.place}`, offer.place, `${name(offer.place)} erbjuder sig`);
  const had = new Set(before.controls ?? []);
  const has = new Set(now.controls ?? []);
  for (const place of has) if (!had.has(place)) add(`took:${place}`, place, `${name(place)} fjärrstyrs härifrån`);
  for (const place of had) if (!has.has(place)) add(`gone:${place}`, place, `${name(place)} styrs inte längre härifrån`);
  const was = new Map(placesOf(before).map((p) => [p.place.place, p]));
  for (const place of placesOf(now)) {
    const id = place.place.place;
    const old = was.get(id);
    if (old && modeOf(old) !== modeOf(place) && !has.has(id) && !had.has(id)) add(`mode:${id}`, id, `${name(id)}: ${MODE_TEXT[modeOf(place)]}`);
    const asked = new Map((old?.routes ?? []).map((r) => [r.request_id, r.state]));
    for (const r of place.routes ?? []) {
      if (r.by !== now.client_id || asked.get(r.request_id) === r.state) continue;
      const label = routeLabel(catalogue(place).find((c) => c.id === r.route) ?? null, r.route);
      if (r.state === "locked") add(`locked:${r.request_id}`, id, `Tågväg ${label} låst i ${name(id)}s ställverk`);
      else if (r.state === "refused") add(`refused:${r.request_id}`, id, `Tågväg ${label} nekad: ${reasonText(r.reason)}`);
      else if ((r.state === "released" || r.state === "cancelled") && (asked.get(r.request_id) === "locked" || asked.get(r.request_id) === "requested")) add(`gone:${r.request_id}`, id, `Tågväg ${label} borttagen`);
    }
  }
  return found.reverse();
}
