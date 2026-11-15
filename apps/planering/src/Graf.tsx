import { useEffect, useLayoutEffect, useRef, useState, type Ref } from "react";
import type { Draft, Finding } from "./api";
import { plural, trainName, type Package } from "./data";
import { clock, DAY, KIND, lines, marksOf, minutes, onLine, runTimes, runs, trafficDays, type Line, type Mark } from "./graf";

// Graf (S6): the day's trains along one line as a graphical timetable, after the planning
// program's sheets, with the traffic check's findings numbered. The places stand fixed to the
// left and the day scrolls sideways; drag it with the mouse. Print as PDF on A3, the whole day.

const DAY_FULL: Record<string, string> = { mon: "Måndag", tue: "Tisdag", wed: "Onsdag", thu: "Torsdag", fri: "Fredag", sat: "Lördag", sun: "Söndag" };
const ZOOM = [1, 2, 3, 4, 6, 8];

type SheetProps = { pkg: Package; line: Line; day: string; kinds: Map<string, string | null>; marks: Mark[]; perMinute: number; compact?: boolean; height?: number };

/** What one line on one day looks like: the rows, the hours, the trains and the marks. */
export function sheet({ pkg, line, day, kinds, perMinute, compact = false, height: wanted }: SheetProps) {
  const names = new Map(pkg.places.map((place) => [place.id, place]));
  const run = runTimes(pkg);
  const distance = [0];
  for (let i = 1; i < line.places.length; i++) {
    distance.push(line.distances ? (line.distances[i] ?? 0) : (distance[i - 1] ?? 0) + run(line.places[i - 1] as string, line.places[i] as string));
  }
  const total = Math.max(distance[distance.length - 1] ?? 0, 1);
  const gaps = distance
    .slice(1)
    .map((value, i) => value - (distance[i] ?? 0))
    .filter((gap) => gap > 0);
  const smallest = Math.min(...gaps, total);
  const top = compact ? 34 : 36;
  const bottom = compact ? 26 : 30;
  const inner = Math.min(Math.max(wanted ?? 520, (22 * total) / smallest), compact ? 1600 : 1100);
  const height = top + inner + bottom;
  const rows = new Map(line.places.map((place, i) => [place, i]));
  const rowY = line.places.map((_, i) => top + ((distance[i] ?? 0) / total) * inner);
  const left = compact ? 150 : 0;
  const width = DAY * perMinute;
  const x = (minute: number) => left + minute * perMinute;
  const trains = (pkg.trains ?? [])
    .map((train) => ({ train, found: runs(train, rows, day) }))
    .filter(({ found }) => found.length > 0)
    .map(({ train, found }) => ({ train, found, kind: KIND[kinds.get(train.train_type ?? "") ?? ""] ?? "okand", label: trainName(train) }));
  return { names, top, inner, height, rows, rowY, left, width, x, trains };
}

export function GrafBlad(props: SheetProps & { scroller?: Ref<HTMLDivElement> }) {
  const { line, marks, perMinute, compact = false } = props;
  const { names, top, inner, height, rows, rowY, left, width, x, trains } = sheet(props);
  const step = perMinute >= 3 ? 10 : 30;
  const ticks: number[] = [];
  for (let minute = 0; minute <= DAY; minute += step) ticks.push(minute);
  const placeLabels = line.places.map((place, i) => (
    <text key={place} x={compact ? left - 12 : 156} y={(rowY[i] ?? 0) + 4} className={names.get(place)?.kind === "halt" ? "plats halt" : "plats"}>
      {names.get(place)?.name ?? place}
    </text>
  ));
  const blad = (
    <svg className="graf-blad" width={left + width + 16} height={height} viewBox={`0 0 ${left + width + 16} ${height}`} role="img" aria-label={`Tågdiagram ${line.name}`}>
      <g className="rutnat">
        {ticks.map((minute) => {
          const hour = minute % 60 === 0;
          return (
            <g key={minute}>
              <line x1={x(minute)} x2={x(minute)} y1={top} y2={top + inner} className={hour ? "timme" : "tiominut"} />
              {hour && (
                <>
                  <text x={x(minute)} y={top - 12} className="tid">
                    {clock(minute)}
                  </text>
                  <text x={x(minute)} y={top + inner + 20} className="tid">
                    {clock(minute)}
                  </text>
                </>
              )}
            </g>
          );
        })}
        {line.places.map((place, i) => (
          <line key={place} x1={x(0)} x2={x(DAY)} y1={rowY[i]} y2={rowY[i]} className={names.get(place)?.kind === "halt" ? "rad halt" : "rad"} />
        ))}
      </g>
      {compact && placeLabels}
      <g className="fyndlager">
        {marks.map((mark) => {
          if (mark.from !== undefined) {
            const a = rows.get(mark.from);
            const b = rows.get(mark.to ?? "");
            if (a === undefined || b === undefined) return null;
            const [y1, y2] = [rowY[a] ?? 0, rowY[b] ?? 0].sort((p, q) => p - q) as [number, number];
            return (
              <g key={mark.number}>
                <rect x={x(0)} y={y1} width={width} height={Math.max(y2 - y1, 2)} className={`band ${mark.severity}`} />
                <text x={x(0) + 6} y={(y1 + y2) / 2 + 4} className={`nummer ${mark.severity}`}>
                  {String(mark.number)}
                </text>
              </g>
            );
          }
          const row = rows.get(mark.place ?? "");
          if (row === undefined || mark.minute === null || mark.minute === undefined) return null;
          return (
            <g key={mark.number}>
              <circle cx={x(mark.minute)} cy={rowY[row]} r={11} className={`ring ${mark.severity}`} />
              <text x={x(mark.minute)} y={(rowY[row] ?? 0) - 16} className={`nummer ${mark.severity}`}>
                {String(mark.number)}
              </text>
            </g>
          );
        })}
      </g>
      <g className="tag">
        {trains.flatMap(({ train, found, kind, label }) =>
          found.map((points, index) => {
            const first = points[0];
            const last = points[points.length - 1];
            const second = points[1];
            if (!first || !last || !second) return null;
            const path = points.map(([minute, row], i) => `${i ? "L" : "M"}${x(minute).toFixed(1)},${(rowY[row] ?? 0).toFixed(1)}`).join(" ");
            const from = names.get(first[2].place)?.name ?? "";
            const to = names.get(last[2].place)?.name ?? "";
            const down = (rowY[second[1]] ?? 0) >= (rowY[first[1]] ?? 0);
            return (
              <g key={`${train.id}-${index}`} className={`tagg ${kind}`}>
                <title>{`${label} · ${from} ${clock(first[0])} – ${to} ${clock(last[0])}`}</title>
                <path d={path} />
                <text x={x(first[0]) + 3} y={(rowY[first[1]] ?? 0) + (down ? 14 : -6)} className="nr">
                  {train.number}
                </text>
              </g>
            );
          }),
        )}
      </g>
    </svg>
  );
  if (compact) return blad;
  return (
    <div className="graf">
      <div className="graf-vanster">
        <svg className="graf-namn" width={168} height={height} viewBox={`0 0 168 ${height}`} aria-hidden="true">
          {placeLabels}
        </svg>
      </div>
      <div className="graf-rulla" ref={props.scroller} tabIndex={0} role="region" aria-label={`Dygnet på ${line.name}; rulla i sidled med piltangenterna`}>
        {blad}
      </div>
    </div>
  );
}

export type GrafProps = { draft: Draft | null; findings: Finding[] };

export function GrafPage({ draft, findings }: GrafProps) {
  const pkg = draft?.package ?? null;
  const all = pkg ? lines(pkg) : [];
  const days = pkg ? trafficDays(pkg) : [];
  const [lineId, setLineId] = useState<string | null>(null);
  const [day, setDay] = useState<string | null>(null);
  const [zoom, setZoom] = useState(3);
  const [printing, setPrinting] = useState<Line[] | null>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const drawnZoom = useRef<number | null>(null);
  const keep = useRef<number | null>(null);

  const line = all.find((item) => item.id === lineId) ?? all[0];
  const shownDay = day ?? days[0] ?? "mon";
  const kinds = new Map((draft?.rulebook?.train_types ?? []).map((rule) => [rule.code, rule.content ?? null]));
  const marks = pkg ? marksOf(pkg, findings) : [];
  const dayMarks = marks.filter((mark) => !mark.days || mark.days.includes(shownDay));

  // The middle of what is seen stays in the middle when the scale changes; the first time,
  // the clock's start, where the game begins (the night before stands to the left).
  useLayoutEffect(() => {
    const area = scroller.current;
    if (!area || !pkg) return;
    const perMinute = ZOOM[zoom] ?? 3;
    const start = minutes((pkg.clock as { start_time?: string } | undefined)?.start_time) ?? 360;
    const middle = keep.current ?? (drawnZoom.current === null ? Math.max(0, start - 30) + area.clientWidth / 2 / perMinute : null);
    if (middle !== null) area.scrollLeft = Math.max(0, middle * perMinute - area.clientWidth / 2);
    keep.current = null;
    drawnZoom.current = perMinute;
  }, [zoom, line?.id, shownDay, pkg]);

  // Drag the sheet sideways with the mouse, as in the old graph.
  useEffect(() => {
    let dragging: { x: number; left: number } | null = null;
    const down = (event: PointerEvent) => {
      if (!scroller.current || event.button !== 0 || !scroller.current.contains(event.target as Node)) return;
      dragging = { x: event.clientX, left: scroller.current.scrollLeft };
    };
    const move = (event: PointerEvent) => {
      if (dragging && scroller.current) scroller.current.scrollLeft = dragging.left - (event.clientX - dragging.x);
    };
    const up = () => (dragging = null);
    window.addEventListener("pointerdown", down);
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    return () => {
      window.removeEventListener("pointerdown", down);
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
  }, []);

  useEffect(() => {
    if (!printing) return;
    window.print();
    setPrinting(null);
  }, [printing]);

  const rezoom = (next: number) => {
    const area = scroller.current;
    if (area && drawnZoom.current) keep.current = (area.scrollLeft + area.clientWidth / 2) / drawnZoom.current;
    setZoom(Math.max(0, Math.min(next, ZOOM.length - 1)));
  };

  if (!draft) return <p className="liten">Hämtar träffen …</p>;
  const heading = (
    <div className="sidrubrik">
      <div>
        <p className="overrubrik">{draft.meet.name}</p>
        <h1>Graf</h1>
      </div>
      <span className="under">dygnets tåg, med kontrollens fynd</span>
    </div>
  );
  if (!pkg || !line) {
    return (
      <>
        {heading}
        <section className="kort" id="empty">
          <p className="liten">Lägg till underlag under Data först.</p>
        </section>
      </>
    );
  }
  const drawn = sheet({ pkg, line, day: shownDay, kinds, marks: dayMarks, perMinute: ZOOM[zoom] ?? 3 });
  return (
    <>
      {heading}
      <div className="graf-yta" id="graph-page">
        <section className="kort graf-kort" aria-label="Tågdiagrammet">
          <div className="graf-rad">
            <div id="days" className="segment" role="group" aria-label="Trafikdag">
              {days.map((item) => (
                <button key={item} type="button" aria-pressed={item === shownDay} onClick={() => setDay(item)}>
                  {DAY_FULL[item]}
                </button>
              ))}
            </div>
            <label className="valj">
              Linje{" "}
              <select id="line" value={line.id} onChange={(event) => setLineId(event.target.value)}>
                {all.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}
                  </option>
                ))}
              </select>
            </label>
            <span className="fyll" />
            <div className="segment" role="group" aria-label="Skala">
              <button type="button" id="zoom-out" aria-label="Visa mer av dygnet" onClick={() => rezoom(zoom - 1)}>
                −
              </button>
              <button type="button" id="zoom-in" aria-label="Visa mindre av dygnet" onClick={() => rezoom(zoom + 1)}>
                +
              </button>
            </div>
          </div>
          <div id="graph">
            <GrafBlad pkg={pkg} line={line} day={shownDay} kinds={kinds} marks={dayMarks} perMinute={ZOOM[zoom] ?? 3} scroller={scroller} />
          </div>
          <footer className="graf-fot">
            <span id="graph-count" className="liten">{`${plural(drawn.trains.length, "tåg", "tåg")} på ${(DAY_FULL[shownDay] ?? shownDay).toLowerCase()} på ${line.name} · dra i sidled för resten av dygnet`}</span>
            <span className="fyll" />
            <span className="teckning resande">resande</span>
            <span className="teckning gods">gods</span>
            <span className="teckning tjanst">tjänst</span>
            <span className="teckning okand">okänt slag</span>
          </footer>
        </section>
        <aside className="kort graf-sida" aria-labelledby="i-grafen">
          <h2 id="i-grafen">
            I grafen <span className="liten">trafikkontrollen</span>
          </h2>
          <ol id="graph-findings" className="numrerade">
            {marks.length ? (
              marks.map((mark) => (
                <li key={mark.number} className={onLine(mark, line) ? undefined : "annan"}>
                  <span className={`pill ${mark.severity}`}>{mark.severity === "conflict" ? "Konflikt" : "Iakttagelse"}</span>
                  <p>{mark.message}</p>
                  {!onLine(mark, line) && <p className="liten">Inte på den här linjen.</p>}
                </li>
              ))
            ) : (
              <li className="tom">Inga fynd.</li>
            )}
          </ol>
          <p className="overrubrik">Skriv ut</p>
          <p className="liten">PDF på A3 liggande, hela dygnet. Välj Spara som PDF i utskriften.</p>
          <div className="rad">
            <button type="button" id="print-line" onClick={() => setPrinting([line])}>
              Den här linjen
            </button>
            <button type="button" id="print-all" className="lank" onClick={() => setPrinting(all)}>
              Alla linjer
            </button>
          </div>
        </aside>
      </div>
      <div id="print" className="utskrift" aria-hidden="true">
        {printing?.map((item) => (
          <section key={item.id} className="utskriftssida">
            <h2>{`${draft.meet.name} · ${item.name} · ${DAY_FULL[shownDay] ?? shownDay}`}</h2>
            <GrafBlad pkg={pkg} line={item} day={shownDay} kinds={kinds} marks={dayMarks} perMinute={1} compact height={780} />
          </section>
        ))}
      </div>
    </>
  );
}
