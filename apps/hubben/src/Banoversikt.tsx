import type { Now } from "./api";
import type { Package } from "./andringar";
import { bestBands, BOX_W, drawing, HEAD_H, KIND_TEXT, minutesOf, ROW_H, sectionLabel, sectionNote, trafficOf, between, type Box, type OnSection, type OnTrack, type Traffic } from "./bana";

// Banöversikten (SKARM-21, H47) as SVG, drawn for a 1920 × 1080 screen and scaled to fit: a box
// per place that clears with a field per track, the sections between them with a field per part,
// and the halts as marks along them. Green is cleared, red occupied, yellow dashed requested,
// blue dashed on the way here, dotted ends here.

type Point = [number, number];
const MARGIN = 28;
const CALLOUT = 46;
const FIELD_W = 82;
const FIELD_H = 22;

/** The way a link is drawn: straight on a row, down in a column, an elbow between rows, or
 * back through the gap to the next band, like the end of a line of text. */
function route(a: Box, b: Box, gaps: number[]): Point[] {
  const ya = a.y + (a.tracks.length ? HEAD_H + ROW_H / 2 : a.h / 2);
  const yb = b.y + (b.tracks.length ? HEAD_H + ROW_H / 2 : b.h / 2);
  if (a.band !== b.band) {
    const [first, second, y1, y2] = a.band < b.band ? [a, b, ya, yb] : [b, a, yb, ya];
    const gap = gaps[first.band] ?? first.y + first.h + 20;
    const out: Point[] = [
      [first.x + first.w, y1],
      [first.x + first.w + 24, y1],
      [first.x + first.w + 24, gap],
      [second.x - 24, gap],
      [second.x - 24, y2],
      [second.x, y2],
    ];
    return a.band < b.band ? out : out.reverse();
  }
  if (Math.abs(a.y - b.y) < 1) {
    const [left, right] = a.x < b.x ? [a, b] : [b, a];
    const y = Math.min(ya, yb);
    return a.x < b.x ? [[left.x + left.w, y], [right.x, y]] : [[right.x, y], [left.x + left.w, y]];
  }
  if (Math.abs(a.x - b.x) < BOX_W) {
    const x = (Math.max(a.x, b.x) + Math.min(a.x + a.w, b.x + b.w)) / 2;
    return a.y < b.y ? [[x, a.y + a.h], [x, b.y]] : [[x, a.y], [x, b.y + b.h]];
  }
  const right = b.x > a.x;
  const start: Point = [right ? a.x + a.w : a.x, ya];
  const end: Point = [right ? b.x : b.x + b.w, yb];
  const middle = (start[0] + end[0]) / 2;
  return [start, [middle, ya], [middle, yb], end];
}

/** The point a fraction of the way along a route. */
export function along(points: Point[], fraction: number): Point {
  const lengths = points.slice(1).map((point, i) => Math.hypot(point[0] - (points[i] as Point)[0], point[1] - (points[i] as Point)[1]));
  let left = fraction * lengths.reduce((sum, length) => sum + length, 0);
  for (let i = 0; i < lengths.length; i++) {
    const length = lengths[i] as number;
    const [x1, y1] = points[i] as Point;
    const [x2, y2] = points[i + 1] as Point;
    if (left <= length || i === lengths.length - 1) {
      const t = length ? Math.min(1, left / length) : 0;
      return [x1 + (x2 - x1) * t, y1 + (y2 - y1) * t];
    }
    left -= length;
  }
  return points[0] as Point;
}

/** Whether the route runs up or down where the fraction lands, so that words go beside it. */
export function upright(points: Point[], fraction: number): boolean {
  const [x1, y1] = along(points, Math.max(0, fraction - 0.01));
  const [x2, y2] = along(points, Math.min(1, fraction + 0.01));
  return Math.abs(y2 - y1) > Math.abs(x2 - x1);
}

const STATE_ORDER: OnSection["state"][] = ["occupied", "cleared", "requested"];
const SECTION_CLASS: Record<OnSection["state"], string> = { occupied: "belagd", cleared: "klar", requested: "begard" };
const TRACK_CLASS: Record<OnTrack["state"], string> = { here: "inne", requested: "begard", cleared: "klar", coming: "kommer", ends: "slutar" };

export type BanoversiktProps = { pkg: Package; now: Now; traffic?: Traffic; label?: string; /** The room's width over its height. */ aspect?: number };

export function Banoversikt({ pkg, now, traffic = trafficOf(pkg, now), label = "Banöversikt", aspect = 3 }: BanoversiktProps) {
  const drawn = drawing(pkg, bestBands(pkg, aspect, 2 * MARGIN + CALLOUT));
  const places = new Map(pkg.places.map((place) => [place.id, place]));
  const clock = minutesOf(now.clock.time) ?? 0;
  const clearances = new Map(now.clearances.map((clearance) => [clearance.clearance_id, clearance]));
  const width = drawn.width + 2 * MARGIN;
  const height = drawn.height + 2 * MARGIN + CALLOUT;
  const shift = (point: Point): Point => [point[0] + MARGIN, point[1] + MARGIN + CALLOUT];
  const name = (id: string) => places.get(id)?.name ?? id;
  const arrow = (entry: OnTrack, box: Box) => {
    const toward = entry.toward ? drawn.boxes.get(entry.toward) : undefined;
    if (!toward || toward === box) return { before: "", after: "" };
    return toward.x + toward.w / 2 >= box.x + box.w / 2 ? { before: "", after: " ▶" } : { before: "◀ ", after: "" };
  };
  return (
    <svg className="banoversikt" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${label}: ${drawn.boxes.size} driftplatser och ${drawn.links.filter((link) => link.section).length} sträckor`}>
      {drawn.links.map((link) => {
        const a = drawn.boxes.get(link.a) as Box;
        const b = drawn.boxes.get(link.b) as Box;
        const points = route(a, b, drawn.gaps).map(shift);
        const path = points.map(([x, y]) => `${x},${y}`).join(" ");
        const section = link.section;
        if (!section) return <polyline key={`${link.a}-${link.b}`} points={path} className="spar utan" />;
        const on = traffic.sections.get(section.id) ?? [];
        const state = STATE_ORDER.find((s) => on.some((entry) => entry.state === s));
        const forward = link.a === section.place_a;
        const parts = section.parts?.length ? section.parts : [{ from_place: section.place_a, to_place: section.place_b }];
        const count = parts.length;
        const [mx, my] = along(points, 0.5);
        const requested = on.find((entry) => entry.state === "requested");
        const asked = requested?.leg.clearance_id ? clearances.get(requested.leg.clearance_id) : undefined;
        const waited = asked ? between(minutesOf(asked.requested_at) ?? clock, clock) : null;
        return (
          <g key={section.id} className={`strecka ${state ? SECTION_CLASS[state] : ""}`}>
            <polyline points={path} className={`spar ${section.tracks === "double" ? "dubbel" : "enkel"}`} />
            {section.tracks === "double" && <polyline points={path} className="spar mellan" />}
            {upright(points, 0.5) ? (
              <>
                <text x={mx + FIELD_W / 2 + 10} y={my - 4} className="strecka-namn">
                  {sectionLabel(section)}
                </text>
                <text x={mx + FIELD_W / 2 + 10} y={my + 12} className="strecka-not">
                  {sectionNote(section, pkg)}
                </text>
              </>
            ) : (
              <>
                <text x={mx} y={my - FIELD_H - 18} className="strecka-namn" textAnchor="middle">
                  {sectionLabel(section)}
                </text>
                <text x={mx} y={my - FIELD_H - 4} className="strecka-not" textAnchor="middle">
                  {sectionNote(section, pkg)}
                </text>
              </>
            )}
            {parts.map((_, k) => {
              const [x, y] = along(points, (k + 0.5) / count);
              const here = on.filter((entry) => {
                const fraction = entry.from === link.a ? entry.progress : 1 - entry.progress;
                return entry.state === "occupied" && Math.min(count - 1, Math.floor(fraction * count)) === k;
              });
              const shown = here[0];
              const fromBox = shown ? drawn.boxes.get(shown.from) : undefined;
              const toBox = shown ? drawn.boxes.get(shown.to) : undefined;
              const right = !fromBox || !toBox || toBox.x + toBox.w / 2 >= fromBox.x + fromBox.w / 2;
              const down = !!fromBox && !!toBox && toBox.y > fromBox.y;
              const standing = upright(points, (k + 0.5) / count);
              return (
                <g key={k}>
                  <rect x={x - FIELD_W / 2} y={y - FIELD_H / 2} width={FIELD_W} height={FIELD_H} rx={3} className={`falt ${shown ? "belagt" : ""}`} />
                  {shown && (
                    <text x={x} y={y + 6} className="tagnummer" textAnchor="middle">
                      {standing ? `${shown.number} ${down ? "▼" : "▲"}` : right ? `${shown.number} ▶` : `◀ ${shown.number}`}
                    </text>
                  )}
                </g>
              );
            })}
            {parts.slice(0, -1).map((part, k) => {
              const [x, y] = along(points, (k + 1) / count);
              const stop = forward ? part.to_place : (parts[count - 2 - k] ?? part).to_place;
              const side = upright(points, (k + 1) / count);
              return (
                <g key={`h${k}`} className="hallplats">
                  {side ? <line x1={x - 14} y1={y} x2={x + 14} y2={y} /> : <line x1={x} y1={y - 14} x2={x} y2={y + 14} />}
                  <text x={side ? x - 20 : x} y={side ? y + 4 : y + 32} textAnchor={side ? "end" : "middle"}>
                    {name(stop)}
                  </text>
                </g>
              );
            })}
            {requested && (
              <g className="pratbubbla">
                <rect x={mx - 110} y={my - FIELD_H - 64} width={220} height={30} rx={6} />
                <text x={mx} y={my - FIELD_H - 44} textAnchor="middle">
                  {`${requested.number} begärt mot ${name(requested.to)}${waited !== null && waited >= 0 ? ` · ${waited} min` : ""}`}
                </text>
              </g>
            )}
            <polyline points={path} className="spar-traff">
              <title>{`Sträcka ${sectionLabel(section) ? `${sectionLabel(section)}, ` : ""}${name(section.place_a)}–${name(section.place_b)}`}</title>
            </polyline>
          </g>
        );
      })}
      {[...drawn.boxes.values()].map((box) => {
        const [x, y] = shift([box.x, box.y]);
        const place = box.place;
        const yard = place.kind === "shadow_yard";
        const tracks = traffic.tracks.get(place.id);
        const sub = place.kind === "remote" && place.remote_from ? `styrs från ${name(place.remote_from)}` : (KIND_TEXT[place.kind] ?? "");
        return (
          <g key={place.id} className={`driftplats ${yard ? "skugga" : ""}`}>
            <rect x={x} y={y} width={box.w} height={box.h} rx={6} className="ruta" />
            <text x={x + 12} y={y + 22} className="plats-namn">
              {place.name}
            </text>
            {place.phone && (
              <text x={x + box.w - 10} y={y + 22} className="plats-tel" textAnchor="end">
                {`tel ${place.phone}`}
              </text>
            )}
            <text x={x + 12} y={y + 38} className="plats-sort">
              {sub}
            </text>
            {yard && (
              <text x={x + 12} y={y + HEAD_H + 16} className="plats-antal">
                {`${traffic.yards.get(place.id) ?? 0} tåg`}
              </text>
            )}
            {box.tracks.map((track, i) => {
              const ty = y + HEAD_H + i * ROW_H;
              const list = tracks?.get(track) ?? [];
              const entry = list.find((item) => item.state !== "coming") ?? list[0];
              const way = entry ? arrow(entry, box) : { before: "", after: "" };
              return (
                <g key={track}>
                  <text x={x + 12} y={ty + 17} className="spar-namn">
                    {track}
                  </text>
                  <rect x={x + 40} y={ty + 2} width={box.w - 52} height={FIELD_H} rx={3} className={`falt ${entry ? TRACK_CLASS[entry.state] : ""}`} />
                  {entry && (
                    <text x={x + 40 + (box.w - 52) / 2} y={ty + 19} className="tagnummer" textAnchor="middle">
                      {`${way.before}${entry.number}${way.after}${list.length > 1 ? ` +${list.length - 1}` : ""}`}
                    </text>
                  )}
                </g>
              );
            })}
          </g>
        );
      })}
    </svg>
  );
}
