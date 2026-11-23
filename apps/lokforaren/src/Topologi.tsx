import { gridOf, linksOf, type Package } from "@trainmeet/hubben";
import { useEffect, useRef, useState } from "react";
import { api, trainsOf, type ServiceOffer } from "./api";
import type { Text } from "./text";

// Topologin i tjänsten (LOK-28, LF15, om-taget.jpg): the line as the meet has it, drawn small
// for the phone, with the service's way and its stops marked. The places stand as Bana in
// Planering and the track overview lay them out (gridOf): the longest way level, each branch on
// a row of its own. Halts along a section are not drawn, as in the track overview.

type Stop = { place: string; stops: boolean };

export type TopologyPlace = { id: string; name: string; x: number; y: number; onWay: boolean; stops: boolean; yard: boolean };
export type Topology = { places: TopologyPlace[]; links: { a: string; b: string; onWay: boolean }[]; width: number; height: number };

const STEP_X = 96;
const STEP_Y = 64;
const MARGIN = 40;

/** The service's way: its trains' calls from the duty's legs, the train itself, or the trains it
 * names (an extra train after the paper), with the places it stops at. */
export function wayOf(pkg: Package, offer: ServiceOffer): Stop[] {
  const trains = pkg.trains ?? [];
  const halts = new Set(pkg.places.filter((place) => place.kind === "halt").map((place) => place.id));
  const byId = new Map(trains.map((train) => [train.id, train]));
  const duty = offer.service.kind === "duty" ? (pkg.duties ?? []).find((found) => found.id === offer.service.id) : undefined;
  let legs: { train: string; from?: string; to?: string }[] = (duty?.legs ?? []).map((leg) => ({ train: leg.train, from: leg.from_call, to: leg.to_call }));
  if (!legs.length && byId.has(offer.service.id)) legs = [{ train: offer.service.id }];
  if (!legs.length) legs = trains.filter((train) => trainsOf(offer).includes(train.number)).map((train) => ({ train: train.id }));
  const way: Stop[] = [];
  for (const leg of legs) {
    const calls = byId.get(leg.train)?.calls ?? [];
    const from = leg.from ? Math.max(0, calls.findIndex((call) => call.id === leg.from)) : 0;
    const found = leg.to ? calls.findIndex((call) => call.id === leg.to) : -1;
    const to = found < 0 ? calls.length - 1 : found;
    for (const call of calls.slice(from, to + 1)) {
      if (halts.has(call.place)) continue;
      const last = way[way.length - 1];
      if (last?.place === call.place) last.stops = last.stops || (call.stops ?? true);
      else way.push({ place: call.place, stops: call.stops ?? true });
    }
  }
  return way;
}

const pair = (a: string, b: string) => (a < b ? `${a}|${b}` : `${b}|${a}`);

/** Where each place stands, and which links and places the service's way takes. */
export function topologyOf(pkg: Package, offer: ServiceOffer): Topology | null {
  const links = linksOf(pkg);
  const used = pkg.places.filter((place) => place.kind !== "halt" && links.some((link) => link.a === place.id || link.b === place.id));
  if (used.length < 2) return null;
  const grid = gridOf(
    used.map((place) => place.id),
    links,
  );
  const way = wayOf(pkg, offer);
  const onWay = new Set(way.map((stop) => stop.place));
  const stops = new Set(way.filter((stop) => stop.stops).map((stop) => stop.place));
  const wayLinks = new Set(way.slice(1).map((stop, i) => pair((way[i] as Stop).place, stop.place)));
  const columns = [...grid.values()].map(([column]) => column);
  const rows = [...grid.values()].map(([, row]) => row);
  const left = Math.min(...columns);
  const top = Math.min(...rows);
  const places = used.flatMap((place) => {
    const at = grid.get(place.id);
    if (!at) return [];
    return [{ id: place.id, name: place.name, x: MARGIN + (at[0] - left) * STEP_X, y: MARGIN + (at[1] - top) * STEP_Y, onWay: onWay.has(place.id), stops: stops.has(place.id), yard: place.kind === "shadow_yard" }];
  });
  const ids = new Set(places.map((place) => place.id));
  return {
    places,
    links: links.filter((link) => ids.has(link.a) && ids.has(link.b)).map((link) => ({ a: link.a, b: link.b, onWay: wayLinks.has(pair(link.a, link.b)) })),
    width: MARGIN * 2 + (Math.max(...columns) - left) * STEP_X,
    height: MARGIN * 2 + (Math.max(...rows) - top) * STEP_Y,
  };
}

const FRESH_MS = 60_000;
let kept: { pkg: Package; at: number } | null = null;

/** The package for the line, read once a minute at most: the line changes only with a
 * driftändring, and the phone need not fetch the timetable each time a card opens. */
export function usePackage(): Package | null {
  const [pkg, setPkg] = useState<Package | null>(kept?.pkg ?? null);
  useEffect(() => {
    if (kept && Date.now() - kept.at < FRESH_MS) return;
    let gone = false;
    api.package().then(
      (found) => {
        kept = { pkg: found, at: Date.now() };
        if (!gone) setPkg(found);
      },
      () => undefined,
    );
    return () => {
      gone = true;
    };
  }, []);
  return pkg;
}

/** Topologi: the card in Hela tjänsten. Wide lines scroll sideways in the card (SKARM-22). */
export function Topologi({ pkg, offer, text }: { pkg: Package | null; offer: ServiceOffer; text: Text }) {
  const drawn = pkg ? topologyOf(pkg, offer) : null;
  const frame = useRef<HTMLDivElement>(null);
  const first = drawn?.places.filter((place) => place.onWay).sort((a, b) => a.x - b.x)[0]?.x ?? 0;
  // A long line opens where the service's way begins; the rest is a swipe away.
  useEffect(() => {
    if (frame.current) frame.current.scrollLeft = Math.max(0, first - MARGIN);
  }, [first]);
  if (!drawn) return null;
  const at = new Map(drawn.places.map((place) => [place.id, place]));
  return (
    <section className="lok-kort lok-topologi" aria-labelledby="lok-topologi-rubrik" id="topologi">
      <h2 id="lok-topologi-rubrik" className="lok-overrubrik">
        {text.topology}
      </h2>
      <div className="lok-topologi-ram" ref={frame}>
        <svg viewBox={`0 0 ${drawn.width} ${drawn.height}`} width={drawn.width} height={drawn.height} role="img" aria-label={text.topologyLabel(drawn.places.filter((place) => place.onWay).map((place) => place.name))}>
          {drawn.links.map((link) => {
            const a = at.get(link.a) as TopologyPlace;
            const b = at.get(link.b) as TopologyPlace;
            const d = a.y === b.y ? `M${a.x} ${a.y}H${b.x}` : `M${a.x} ${a.y}H${(a.x + b.x) / 2}V${b.y}H${b.x}`;
            return <path key={pair(link.a, link.b)} d={d} className={link.onWay ? "pa-vagen" : "linje"} />;
          })}
          {drawn.places.map((place) => (
            <g key={place.id} className={place.onWay ? "plats pa-vagen" : "plats"}>
              <circle cx={place.x} cy={place.y} r={place.stops ? 7 : 5} className={place.yard ? "bangard" : place.stops ? "uppehall" : undefined} />
              <text x={place.x} y={place.y + 22} textAnchor="middle">
                {place.name}
              </text>
            </g>
          ))}
        </svg>
      </div>
      <p className="lok-topologi-forklaring">
        <span className="streck" aria-hidden="true" /> {text.yourService} <span className="prick" aria-hidden="true" /> {text.stop}
      </p>
    </section>
  );
}
