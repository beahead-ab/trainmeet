// Fjärrbilden (#36 del c): the picture in the skin 95 on black, and the row under it where an
// offer is taken or declined, a chosen route is sent with Lägg tågvägen or dropped with Avbryt,
// the routes TKL asked for are taken away with Ta bort, and every station says its operating form
// and who controls it. What is drawn comes from fjarr.ts in logical terms; the colours, widths,
// signals and train numbers are 95's entry in skal.ts (FR47). Clicks go to the page, which asks
// Hubben: the picture decides nothing (FR12, FR13).
import type { KeyboardEvent, ReactNode } from "react";
import { clockText, COLOURS, myRoutes, pieceColour, pieceWidth, reasonText, routeLabel, routeOf, routesFrom, SKIN, timeLeft, type Choice, type Drawn, type DrawnSignal, type DrawnStation, type Hit, type Sent, sentState } from "./fjarr";
import type { Fjarr } from "./fjarrapi";
import type { Shape } from "./skal";

const r2 = (n: number) => Math.round(n * 100) / 100;
/** The train numbers in 95's font and weight, a size up from the station's picture: the overview's
 * cells are smaller than the station picture's. */
const NUMBER = SKIN.numbers.size * 1.25;

function placed(shapes: Shape[], x: number, y: number, towards: 1 | -1, key: string): ReactNode[] {
  return shapes.map((shape, i) => {
    const points = shape.points.map(([a, h]) => `${r2(x + towards * a)},${r2(y - h)}`).join(" ");
    const style = { fill: shape.fill ?? "none", stroke: shape.stroke ?? "none", strokeWidth: shape.width };
    return shape.closed ? <polygon key={`${key}${i}`} points={points} style={style} /> : <polyline key={`${key}${i}`} points={points} style={style} />;
  });
}

const press = (work: () => void) => (event: KeyboardEvent) => {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    work();
  }
};

function Signal({ station, signal, onHit }: { station: DrawnStation; signal: DrawnSignal; onHit: (hit: Hit) => void }) {
  const look = SKIN.signal({ type: "hsi", aspect: signal.aspect, end: signal.end, blocked: false });
  const above = signal.towards === 1 ? -1 : 1;
  const hit = signal.start || signal.target;
  const work = () => onHit({ kind: "signal", place: station.place, name: signal.name });
  return (
    <g data-signal={signal.name} data-aspect={signal.aspect} data-end={signal.end ? "ja" : undefined} data-arrow={signal.arrow ?? undefined}>
      {look.gap ? <line x1={signal.x + signal.towards * look.gap[0]} x2={signal.x + signal.towards * look.gap[1]} y1={signal.y} y2={signal.y} stroke={SKIN.ground} strokeWidth={SKIN.stateWidth + 0.14} /> : null}
      {placed(look.shapes, signal.x, signal.y, signal.towards, `s${signal.name}`)}
      <text x={signal.x} y={signal.y + above * 0.55 + (above > 0 ? 0.36 : 0)} fill={SKIN.signalId} fontSize={0.56} textAnchor="middle" fontFamily={SKIN.font}>
        {signal.name}
      </text>
      {signal.arrow ? (
        <polygon
          className={`fj-pil ${signal.arrow}`}
          points={[
            [signal.x - signal.towards * 0.28, signal.y + above * 1.12 - 0.22],
            [signal.x - signal.towards * 0.28, signal.y + above * 1.12 + 0.22],
            [signal.x + signal.towards * 0.3, signal.y + above * 1.12],
          ]
            .map(([a, b]) => `${r2(a ?? 0)},${r2(b ?? 0)}`)
            .join(" ")}
          fill={signal.arrow === "automat" ? COLOURS.arrowAutomat : COLOURS.arrowRemote}
        />
      ) : null}
      {signal.chosen ? <circle cx={signal.x} cy={signal.y} r={0.62} fill="none" stroke={SKIN.rings.train} strokeWidth={0.12} /> : null}
      {signal.target ? <circle cx={signal.x} cy={signal.y} r={0.62} fill="none" stroke={SKIN.rings.goal} strokeWidth={0.1} strokeDasharray="0.18 0.12" /> : null}
      {hit ? (
        <circle
          className="fj-klick"
          cx={signal.x}
          cy={signal.y}
          r={0.75}
          fill="transparent"
          role="button"
          tabIndex={0}
          aria-label={signal.target ? `Mål ${signal.name} vid ${station.name}` : `Start ${signal.name} vid ${station.name}`}
          onClick={work}
          onKeyDown={press(work)}
        />
      ) : null}
    </g>
  );
}

function Station({ station, onHit }: { station: DrawnStation; onHit: (hit: Hit) => void }) {
  const top = station.y - 1.5;
  return (
    <g className="fj-station" data-place={station.place} data-mode={station.mode} data-mine={station.mine ? "ja" : undefined}>
      <text x={station.x} y={top} fontFamily={SKIN.font} fontSize={0.9}>
        <tspan fill={SKIN.label} fontFamily="var(--tm-mono)" fontSize={0.7}>
          {station.code}
        </tspan>
        <tspan className="fj-namn" dx={0.45} fill={station.nameColour} fontWeight={700} data-colour={station.nameColour}>
          {station.name.toUpperCase()}
        </tspan>
        {station.codes.map((c) => (
          <tspan key={c.code} dx={0.5} fontSize={0.7} fontWeight={700} fill={c.on ? (c.local ? COLOURS.localOn : COLOURS.codeOn) : COLOURS.codeOff} data-code={c.code} data-on={c.on ? "ja" : "nej"}>
            {c.code}
          </tspan>
        ))}
        {station.mode !== "remote" || !station.mine ? (
          <tspan dx={0.6} fontSize={0.62} fill={station.nameColour}>
            {station.modeText}
          </tspan>
        ) : null}
      </text>
      {station.plain ? <line x1={station.x} x2={station.x + station.width} y1={station.y} y2={station.y} stroke={SKIN.tracks.free} strokeWidth={SKIN.width} /> : null}
      {station.tracks
        .filter((t) => t.platform)
        .map((t) => (
          <rect key={`p${t.id}`} x={t.x1 + 0.3} y={t.y + 0.25} width={t.x2 - t.x1 - 0.6} height={0.22} fill={SKIN.platform} />
        ))}
      {station.links.map((l) => (
        <line
          key={l.id}
          className={l.state === "chosen" ? "fj-blink" : undefined}
          data-piece={l.id}
          data-state={l.state}
          x1={l.x1}
          y1={l.y1}
          x2={l.x2}
          y2={l.y2}
          stroke={pieceColour(l.state)}
          strokeWidth={pieceWidth(l.state)}
        />
      ))}
      {station.tracks.map((t) => {
        const work = () => onHit({ kind: "track", place: station.place, piece: t.id, track: t.track });
        return (
          <g key={t.id}>
            <line className={t.state === "chosen" ? "fj-blink" : undefined} data-piece={t.id} data-track={t.track ?? undefined} data-state={t.state} x1={t.x1} x2={t.x2} y1={t.y} y2={t.y} stroke={pieceColour(t.state)} strokeWidth={pieceWidth(t.state)} />
            {t.label ? (
              <text x={(t.x1 + t.x2) / 2} y={t.y - 0.32} fill={SKIN.trackName} fontSize={0.62} textAnchor="middle" fontFamily={SKIN.font}>
                {t.label}
              </text>
            ) : null}
            {t.target ? <line x1={t.x1} x2={t.x2} y1={t.y} y2={t.y} stroke={SKIN.rings.goal} strokeWidth={0.08} strokeDasharray="0.3 0.2" /> : null}
            {t.target || t.mine ? <rect className="fj-klick" x={t.x1} y={t.y - 0.45} width={t.x2 - t.x1} height={0.9} fill="transparent" role="button" tabIndex={0} aria-label={t.target ? `Mål spår ${t.label ?? t.id} vid ${station.name}` : `Lagd väg vid ${station.name}`} onClick={work} onKeyDown={press(work)} /> : null}
          </g>
        );
      })}
      {station.signals.map((s) => (
        <Signal key={s.name} station={station} signal={s} onHit={onHit} />
      ))}
      {station.exits
        .filter((e) => e.start)
        .map((e) => {
          const work = () => onHit({ kind: "exit", place: station.place, exit: e.exit });
          return <circle key={`e${e.exit}`} className="fj-klick" cx={e.x} cy={e.y} r={0.7} fill="transparent" stroke={SKIN.rings.goal} strokeWidth={0.05} role="button" tabIndex={0} aria-label={`Start ${e.exit} vid ${station.name}`} onClick={work} onKeyDown={press(work)} />;
        })}
      {station.numbers.map((n) => (
        <text
          key={`${n.text}${n.x}`}
          data-number={n.text}
          data-expected={n.expected ? "ja" : "nej"}
          x={n.x}
          y={n.y}
          textAnchor="end"
          fill={n.expected ? (SKIN.numbers.green ?? SKIN.numbers.red) : SKIN.numbers.red}
          fontFamily={SKIN.numbers.font}
          fontWeight={SKIN.numbers.weight}
          fontSize={NUMBER}
          stroke={SKIN.numbers.edge ?? undefined}
          strokeWidth={0.02}
        >
          {SKIN.numberText(n.text)}
        </text>
      ))}
    </g>
  );
}

/** The picture itself, in cells: a station's grid cell is one unit. */
export function FjarrbildView({ drawn, onHit, stale = false }: { drawn: Drawn; onHit: (hit: Hit) => void; stale?: boolean }) {
  return (
    <svg className={`fjarrbild${stale ? " gammal-bild" : ""}`} viewBox={`${r2(drawn.x0)} 0 ${r2(drawn.width)} ${r2(drawn.height)}`} role="img" aria-label="Fjärrbilden" preserveAspectRatio="xMidYMin meet">
      <rect x={drawn.x0} y={0} width={drawn.width} height={drawn.height} fill={SKIN.ground} />
      {drawn.lines.map((line) => (
        <g key={line.id} data-line={line.id} data-occupied={line.occupied ? "ja" : "nej"}>
          <polyline points={line.points.map(([x, y]) => `${r2(x)},${r2(y)}`).join(" ")} fill="none" stroke={line.occupied ? SKIN.tracks.occupied : SKIN.tracks.free} strokeWidth={line.occupied ? SKIN.stateWidth : SKIN.width} />
          {line.arrow ? (
            <polygon
              points={[
                [line.arrow.x - line.arrow.towards * 0.2, line.arrow.y - 0.42],
                [line.arrow.x - line.arrow.towards * 0.2, line.arrow.y - 0.12],
                [line.arrow.x + line.arrow.towards * 0.2, line.arrow.y - 0.27],
              ]
                .map(([a, b]) => `${r2(a ?? 0)},${r2(b ?? 0)}`)
                .join(" ")}
              fill={line.occupied ? SKIN.tracks.occupied : SKIN.tracks.free}
            />
          ) : null}
          {line.number ? (
            <text data-number={line.number.text} x={line.number.x} y={line.number.y} textAnchor="middle" fill={SKIN.numbers.red} fontFamily={SKIN.numbers.font} fontWeight={SKIN.numbers.weight} fontSize={NUMBER}>
              {line.number.text}
            </text>
          ) : null}
          {line.label ? (
            <text x={line.label.x} y={line.label.y} textAnchor={line.label.anchor} fill={SKIN.label} fontSize={0.56} fontFamily={SKIN.font} className="fj-hanvisning">
              {line.label.text}
            </text>
          ) : null}
        </g>
      ))}
      {drawn.stations.map((s) => (
        <Station key={s.place} station={s} onHit={onHit} />
      ))}
    </svg>
  );
}

/** The key under the picture, as the concept has it. */
export function Teckenforklaring() {
  const swatch = (colour: string, width = 0.3) => (
    <svg viewBox="0 0 2 1" className="fj-prov" aria-hidden="true">
      <line x1={0} x2={2} y1={0.5} y2={0.5} stroke={colour} strokeWidth={width} />
    </svg>
  );
  return (
    <ul className="fj-tecken" aria-label="Teckenförklaring">
      <li>{swatch(SKIN.tracks.free, 0.18)} Ledigt</li>
      <li>{swatch(SKIN.tracks.train)} Låst tågväg</li>
      <li>{swatch(SKIN.tracks.occupied)} Belagt</li>
      <li>
        <b style={{ color: COLOURS.remote }}>ABC</b> Fjärrstyrd
      </li>
      <li>
        <b style={{ color: COLOURS.manned }}>ABC</b> Bemannad
      </li>
      <li>
        <b style={{ color: COLOURS.offered }}>ABC</b> Erbjuden
      </li>
      <li>
        <b style={{ color: COLOURS.noContact }}>ABC</b> Kontakt saknas
      </li>
      <li>
        <b style={{ color: COLOURS.codeOn }}>A3</b> Automat inkopplad
      </li>
      <li>
        <span style={{ color: COLOURS.arrowRemote }}>▶</span> Fjärren lägger vägarna
      </li>
      <li>
        <span style={{ color: COLOURS.arrowAutomat }}>▶</span> Automaten lägger
      </li>
    </ul>
  );
}

export type Notice = { id: string; text: string; at: number; again?: { place: string; route: string } };

type PanelProps = {
  fjarr: Fjarr | null;
  choice: Choice | null;
  sent: Sent[];
  notices: Notice[];
  heardAt: number;
  now: number;
  busy: boolean;
  onLay: () => void;
  onDrop: () => void;
  onChoose: (choice: Choice) => void;
  onAgain: (place: string, route: string) => void;
  onRemove: (place: string, requestId: string) => void;
  onOffer: (place: string, accept: boolean) => void;
};

/** Väntar på dig: the offers with the time left (FR8), the chosen route with Lägg tågvägen and
 * Avbryt (FR13), the routes waiting for the station's answer, and the noes for a while. */
export function Vantar({ fjarr, choice, sent, notices, heardAt, now, busy, onLay, onDrop, onChoose, onAgain, onOffer }: PanelProps) {
  const names = new Map((fjarr?.overview?.places ?? []).map((p) => [p.place.place, p.place.name]));
  const name = (place: string) => names.get(place) ?? place;
  const chosen = choice?.route ? routeOf(fjarr, choice.place, choice.route) : null;
  const here = choice ? (fjarr?.overview?.places ?? []).find((p) => p.place.place === choice.place) : undefined;
  const targets = here && choice && !choice.route ? routesFrom(here, choice.start) : [];
  const waiting = sent.filter((s) => {
    const state = sentState(fjarr, s)?.state;
    return !state || state === "requested";
  });
  const empty = !(fjarr?.offers ?? []).length && !choice && !waiting.length && !notices.length;
  return (
    <section className="fj-ruta" aria-labelledby="fj-vantar">
      <h2 id="fj-vantar">Väntar på dig</h2>
      {(fjarr?.offers ?? []).map((offer) => (
        <div key={offer.place} className="fj-rad erbjudande" data-offer={offer.place}>
          <b>{name(offer.place)}</b> erbjuder sig
          <span className="liten"> · {clockText(timeLeft(offer, heardAt, now))} kvar</span>
          <span className="tm-fyll" />
          <button type="button" className="primar" disabled={busy} onClick={() => onOffer(offer.place, true)}>
            Ta emot
          </button>
          <button type="button" disabled={busy} onClick={() => onOffer(offer.place, false)}>
            Avböj
          </button>
        </div>
      ))}
      {choice ? (
        <div className="fj-rad vald" data-choice={choice.route ?? choice.start}>
          {chosen ? (
            <>
              <span>
                <b>{routeLabel(chosen, choice.route ?? "")}</b> vid {name(choice.place)} <span className="chip fj-blinkar">blinkar</span>
              </span>
              <span className="tm-fyll" />
              <button type="button" className="primar" disabled={busy} onClick={onLay}>
                Lägg tågvägen
              </button>
            </>
          ) : (
            <>
              <span>
                Start <b>{choice.start}</b> vid {name(choice.place)}. Välj målet i bilden
                {targets.length ? ":" : "."}
              </span>
              {targets.map((r) => (
                <button key={r.id} type="button" className="lank" onClick={() => onChoose({ ...choice, route: r.id })}>
                  {routeLabel(r, r.id)}
                </button>
              ))}
              <span className="tm-fyll" />
            </>
          )}
          <button type="button" disabled={busy} onClick={onDrop}>
            Avbryt
          </button>
        </div>
      ) : null}
      {waiting.map((s) => (
        <div key={s.request_id} className="fj-rad" data-sent={s.request_id}>
          <b>{routeLabel(routeOf(fjarr, s.place, s.route), s.route)}</b> vid {name(s.place)}
          <span className="tm-fyll" />
          <span className="chip">Begärd · väntar på {name(s.place)}s ställverk</span>
        </div>
      ))}
      {notices.map((n) => (
        <div key={n.id} className="fj-rad nej" role="alert" data-notice={n.id}>
          {n.text}
          {n.again ? (
            <>
              <span className="tm-fyll" />
              <button type="button" disabled={busy} onClick={() => n.again && onAgain(n.again.place, n.again.route)}>
                Försök igen
              </button>
            </>
          ) : null}
        </div>
      ))}
      {empty ? <p className="tom">Inget väntar. Tryck på en startsignal i en station du styr, sedan på målet.</p> : null}
    </section>
  );
}

/** The routes TKL asked for that stand, with Ta bort, and every station's operating form and who
 * controls it (FR5). */
export function Lagda({ fjarr, busy, marked, onRemove }: { fjarr: Fjarr | null; busy: boolean; marked: string | null; onRemove: (place: string, requestId: string) => void }) {
  const me = fjarr?.client_id ?? null;
  const places = fjarr?.overview?.places ?? [];
  const routes = places.flatMap((p) => myRoutes(p, me).map((r) => ({ place: p, route: r })));
  return (
    <section className="fj-ruta" aria-labelledby="fj-lagda">
      <h2 id="fj-lagda">Tågvägar och stationer</h2>
      {routes.length ? (
        routes.map(({ place, route }) => (
          <div key={route.request_id} className={`fj-rad${marked === route.request_id ? " markerad" : ""}`} data-route={route.request_id} data-state={route.state}>
            <b>{routeLabel(routeOf(fjarr, place.place.place, route.route), route.route)}</b> vid {place.place.name}
            <span className="tm-fyll" />
            <span className={`chip${route.state === "locked" ? " gron" : ""}`}>{route.state === "locked" ? "Låst" : "Begärd"}</span>
            {(fjarr?.controls ?? []).includes(place.place.place) ? (
              <button type="button" disabled={busy} onClick={() => onRemove(place.place.place, route.request_id)}>
                Ta bort
              </button>
            ) : (
              <span className="liten">ligger kvar tills tåget har gått</span>
            )}
          </div>
        ))
      ) : (
        <p className="tom">Inga tågvägar lagda härifrån.</p>
      )}
      <ul className="fj-stationer">
        {places.map((p) => {
          const mode = p.controllable || (p.mode !== "remote" && p.mode !== "offered") ? p.mode : "manned";
          const heard = p.heard === null || p.heard === undefined ? null : p.heard;
          return (
            <li key={p.place.place} data-status={p.place.place}>
              <span className={`prick ${heard !== null && heard < 45 ? "gron" : "gra"}`} aria-hidden="true" />
              <b>{p.place.name}</b>
              <span className="liten"> {modeName(mode)}</span>
              <span className="tm-fyll" />
              <span className="liten">{p.controller ? (p.controller.client_id === me ? "styrs härifrån" : `styrs av ${p.controller.name}`) : p.controllable ? "kan fjärrstyras" : "kan inte fjärrstyras"}</span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

const modeName = (mode: string) => ({ manned: "Bemannad", offered: "Erbjuden", remote: "Fjärrstyrd", no_contact: "Kontakt saknas", automatic: "Automatik" })[mode] ?? mode;

export { reasonText };
