// Områdesväljaren (TKL103): an area on the station's panel, as delställverk and lokal frigivning
// both have it in the station model: track circuits or pieces, the switches and the signals in
// it. Clicked section by section: a track circuit, or the pieces between two switches, signals
// or ends when the station has none (the interlocking's sections, tkl/stallverk/plant.py). Pure
// functions without React, so that Dela stationen uses them today and local release's panel
// function can later. Nothing here names a station (RS13).

/** The kind of area the model gives a part (StationPart) and a panel function (PanelFunction). */
export type Area = { track_circuits?: string[] | null; pieces?: string[] | null; switches?: string[] | null; signals?: string[] | null };
/** The station's sections with their pieces, as TKL's server gives them. */
export type Sections = Record<string, string[]>;

/** Every piece in the area: its own and those of its track circuits. */
export function areaPieces(area: Area, sections: Sections): Set<string> {
  const found = new Set(area.pieces ?? []);
  for (const circuit of area.track_circuits ?? []) for (const piece of sections[circuit] ?? []) found.add(piece);
  return found;
}

/** The section a piece belongs to, by its name; the piece itself when no section holds it. */
export function sectionOf(piece: string, sections: Sections): [string, string[]] {
  for (const [name, pieces] of Object.entries(sections)) if (pieces.includes(piece)) return [name, pieces];
  return [piece, [piece]];
}

/** The area with the clicked piece's section in or out: out when all of it is in, else in.
 * A section that is a listed track circuit goes in and out as the circuit; others as pieces,
 * appended in the order they are clicked, so that an area that is not changed stays as it was. */
export function toggleSection<T extends Area>(area: T, piece: string, sections: Sections): T {
  const [name, pieces] = sectionOf(piece, sections);
  const inside = areaPieces(area, sections);
  const all = pieces.every((p) => inside.has(p));
  const circuits = area.track_circuits ?? [];
  if (all) {
    return {
      ...area,
      track_circuits: circuits.filter((c) => c !== name),
      pieces: (area.pieces ?? []).filter((p) => !pieces.includes(p)),
    };
  }
  const own = area.pieces ?? [];
  return { ...area, pieces: [...own, ...pieces.filter((p) => !own.includes(p) && !inside.has(p))] };
}

/** A name in a list or out of it: out when it is there, else at the end. */
export function toggleName(list: string[] | null | undefined, name: string): string[] {
  const now = list ?? [];
  return now.includes(name) ? now.filter((n) => n !== name) : [...now, name];
}

/** Whether a piece, switch or signal of the panel is in the area. A switch counts by its legs. */
export function inArea(area: Area, sections: Sections) {
  const pieces = areaPieces(area, sections);
  return {
    pieces,
    piece: (piece: string) => pieces.has(piece),
    switch: (number: string) => (area.switches ?? []).includes(number),
    signal: (name: string) => (area.signals ?? []).includes(name),
  };
}
