import { lines, runTimes, runs, type Line, type Package as HubPackage } from "@trainmeet/hubben";
import type { Package, ScreenPicture } from "./api";
import { clockSeconds } from "./Klocka";

// Skärm · Tågdiagram (SKARM-18): three hours of the main line (the plan's graph line with the
// most traffic), from half an hour before now.
// What has run is blue, what is planned grey, and now a yellow line. The window follows the
// clock. Without detection, "run" is the timetable up to now for the trains that have started.

type Now = NonNullable<ScreenPicture["now"]>;
export const WINDOW = 180;
export const BEFORE = 30;
const W = 1920;
const H = 860;
const LEFT = 170;
const RIGHT = 50;
const TOP = 50;
const BOTTOM = 60;

const hhmm = (minute: number) => {
  const m = ((Math.round(minute) % 1440) + 1440) % 1440;
  return `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
};

/** Where each place stands on the line, from 0 at the top to 1 at the bottom. */
export function rowsOf(pkg: HubPackage, line: Line): Map<string, number> {
  const run = runTimes(pkg);
  const at: number[] = [0];
  for (let i = 1; i < line.places.length; i++) at.push((at[i - 1] as number) + (line.distances ? (line.distances[i] ?? 0) - (line.distances[i - 1] ?? 0) : run(line.places[i - 1] as string, line.places[i] as string)));
  const end = Math.max(1, at[at.length - 1] as number);
  return new Map(line.places.map((place, i) => [place, (at[i] as number) / end]));
}

/** The main line: the plan's graph line where most trains run between its places. */
export function mainLine(pkg: HubPackage): Line | undefined {
  const all = lines(pkg);
  const score = (line: Line) => {
    const on = new Set(line.places);
    let runs = 0;
    for (const train of pkg.trains ?? []) {
      const calls = train.calls.filter((call) => on.has(call.place));
      runs += Math.max(0, calls.length - 1);
    }
    return runs;
  };
  return [...all].sort((a, b) => score(b) - score(a) || b.places.length - a.places.length)[0];
}

export function DiagramView({ picture, pkg, fetchedAt, now }: { picture: ScreenPicture; pkg: Package | null; fetchedAt: number; now: number }) {
  const seen = picture.now as Now | null | undefined;
  if (!seen || !pkg) return <p className="laddar">Hämtar tidtabellen …</p>;
  const hub = pkg as unknown as HubPackage;
  const line = mainLine(hub);
  if (!line) return <p className="laddar">Träffen har ingen linje att rita.</p>;
  const clock = clockSeconds(picture, fetchedAt, now) / 60;
  const start = clock - BEFORE;
  const rows = rowsOf(hub, line);
  const names = new Map(pkg.places.map((place) => [place.id, place.name]));
  const x = (minute: number) => LEFT + ((minute - start) / WINDOW) * (W - LEFT - RIGHT);
  const y = (row: number) => TOP + row * (H - TOP - BOTTOM);
  const started = new Set(seen.legs.filter((leg) => leg.state !== "planned").map((leg) => leg.train));
  const online = new Set(seen.legs.filter((leg) => leg.state === "on_the_way").map((leg) => leg.train));
  let planned = 0;
  const drawn = (hub.trains ?? []).flatMap((train) =>
    runs(train, rows, seen.traffic_day).flatMap((points, k) =>
      [-1440, 0, 1440].flatMap((shift) => {
        const moved = points.map(([minute, row]) => [minute + shift, row] as const);
        if (!moved.some(([minute]) => minute >= start && minute <= start + WINDOW)) return [];
        if (!started.has(train.id) && moved.some(([minute]) => minute > clock)) planned++;
        const path = moved.map(([minute, row]) => `${x(minute).toFixed(1)},${y(row).toFixed(1)}`).join(" ");
        const first = moved.find(([minute]) => minute >= start) ?? moved[0];
        return [{ key: `${train.id}-${k}-${shift}`, number: train.number, path, run: started.has(train.id), first }];
      }),
    ),
  );
  const ticks = Array.from({ length: WINDOW / 30 + 1 }, (_, i) => Math.ceil(start / 30) * 30 + i * 30).filter((minute) => minute <= start + WINDOW);
  return (
    <section id="graph-view" className="diagram-vy">
      <header className="bana-rubrik">
        <div>
          <h1 id="meet">{picture.meet}</h1>
          <p id="summary">{`Tågdiagram · ${line.name}`}</p>
        </div>
      </header>
      <svg className="diagram" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Tågdiagram för ${line.name}, tre timmar från ${hhmm(start)}`}>
        <defs>
          <clipPath id="ruta">
            <rect x={LEFT} y={0} width={W - LEFT - RIGHT} height={H} />
          </clipPath>
          <clipPath id="kort">
            <rect x={LEFT} y={0} width={Math.max(0, x(clock) - LEFT)} height={H} />
          </clipPath>
        </defs>
        {ticks.map((minute) => (
          <g key={minute} className="tidslinje">
            <line x1={x(minute)} y1={TOP} x2={x(minute)} y2={H - BOTTOM} />
            <text x={x(minute)} y={H - BOTTOM + 28} textAnchor="middle">
              {hhmm(minute)}
            </text>
          </g>
        ))}
        {line.places.map((place) => (
          <g key={place} className="platslinje">
            <line x1={LEFT} y1={y(rows.get(place) ?? 0)} x2={W - RIGHT} y2={y(rows.get(place) ?? 0)} />
            <text x={LEFT - 14} y={y(rows.get(place) ?? 0) + 6} textAnchor="end">
              {names.get(place) ?? place}
            </text>
          </g>
        ))}
        <g clipPath="url(#ruta)">
          {drawn.map((run) => (
            <g key={run.key}>
              <polyline points={run.path} className="tag planerat" />
              {run.run && <polyline points={run.path} className="tag kort" clipPath="url(#kort)" />}
              {run.first && (
                <text x={x(run.first[0]) + 6} y={y(run.first[1]) - 6} className={run.run ? "tagnr kort" : "tagnr"}>
                  {run.number}
                </text>
              )}
            </g>
          ))}
        </g>
        <line x1={x(clock)} y1={TOP - 10} x2={x(clock)} y2={H - BOTTOM} className="nu" />
        <rect x={x(clock) - 34} y={TOP - 38} width={68} height={26} rx={5} className="nu-bricka" />
        <text x={x(clock)} y={TOP - 19} textAnchor="middle" className="nu-text">
          {hhmm(clock)}
        </text>
      </svg>
      <footer className="bana-fot">
        <span id="graph-count">{`${online.size} tåg på linjen · ${planned} planerade inom tre timmar`}</span>
        <span className="teckning kort-teckning">kört</span>
        <span className="teckning">planerat</span>
        <span className="teckning nu-teckning">nu</span>
      </footer>
    </section>
  );
}
