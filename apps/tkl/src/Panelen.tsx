// The interlocking's panel at level 1–2 (#84), drawn in SVG over the station's panel geometry
// (#83). What is drawn comes from stallverk.ts in logical terms; the skin (skal.ts) gives every
// colour, width and symbol, so another skin is another Skin over the same geometry: 85 and 95
// as a screen with the states in the track's colour, 59 as model 59's illuminated plan with
// lamps, arrows and toggle switches (STV-36). Manöver is the owner's free panel (STV-46): one of
// those skins as it is, with the owner's labels and only what the owner shows. The turntable is
// drawn in every skin, the pit as a circle and the bridge at its angle; a click on one of its
// tracks turns it through its function. Clicks go to the page, which asks the interlocking: the
// panel decides nothing (STV-43). While the station is remote-controlled a small arrow sits by
// each main signal the remote catalogue uses, over or under it by its direction: red when the
// one who controls the station lays the routes, green when a station automat does (FR33, #36).
import type { KeyboardEvent, ReactNode } from "react";
import type { Panel } from "./api";
import { EVERYTHING, type OwnerChoices, type Shape, type Skin } from "./skal";
import { angleOf, cut, fromKnot, goals, slice, type Cell, type Choice, type Drawing, type DrawnSignal } from "./stallverk";
import { round, viewBox } from "./sparplan";
import type { Say } from "./texter";

type Props = {
  panel: Panel;
  drawn: Drawing;
  skin: Skin;
  say: Say;
  /** The station's name: model 59 has it above the plan. */
  title?: string;
  choice?: Choice | null;
  /** The set route chosen for the buttons: its start gets a white ring. */
  chosen?: { id: number; start: string } | null;
  /** The panel's share of the screen (STV-05): at most this high, as wide as it may be. */
  height?: string;
  onPoint?: (name: string) => void;
  /** Model 59: a signal's toggle, flipped (STV-36). */
  onToggle?: (name: string) => void;
  onSwitch?: (part: string) => void;
  onRoute?: (route: number) => void;
  /** A panel function's button in the plan, such as the programming track's (STV-53). */
  onButton?: (name: string) => void;
  /** A track at the turntable, clicked: turn the bridge to it with the turntable's function. */
  onTable?: (fn: string, piece: string) => void;
  /** Manöver (STV-46): the owner's labels and what is shown, over the skin as it is. */
  owner?: OwnerChoices | null;
  /** A part's own screen (TKL102): its area is active, the rest greyed and not clicked. */
  area?: Area | null;
  /** Fjärrstyrning (FR33): the arrow by a main signal, red from afar and green by an automat. */
  arrows?: Record<string, "red" | "green">;
};

/** A part's area on the panel (TKL97): its pieces, signals and switches. */
export type Area = { pieces: Set<string>; signals: Set<string>; switches: Set<string> };
const GREY = 0.28;

const unit = (v: Cell): Cell => {
  const n = Math.hypot(v[0], v[1]) || 1;
  return [v[0] / n, v[1] / n];
};

/** The arrow's colours (FR33): as in the remote picture, the same in every skin. */
export const ARROW = { red: "#e02020", green: "#18c018" } as const;

export function Panelen({ panel, drawn, skin, say, title, choice = null, chosen = null, height, onPoint, onToggle, onSwitch, onRoute, onButton, onTable, owner = null, area = null, arrows = {} }: Props) {
  const outside = (piece: string) => !!area && !area.pieces.has(piece);
  const signalOutside = (name: string) => !!area && !area.signals.has(name);
  const switchOutside = (parts: string[]) => !!area && !parts.some((p) => area.switches.has(p));
  const [dx, dy] = panel.cell;
  // The grid's view, with room at the ends for an exit's name and a train number beside it.
  const grid = viewBox(panel, "schematic", null);
  const top = skin.style === "lamps" && title ? 1.6 * dy : 0;
  const box = { x: grid.x - 3.5 * dx, y: grid.y - top, width: grid.width + 7 * dx, height: grid.height + top };
  const u = Math.min(dx, dy);
  const lamps = skin.style === "lamps";
  const p59 = skin.plan59;
  const px = (c: Cell): Cell => [c[0] * dx, c[1] * dy];
  const line = (cells: Cell[]) => cells.map((c) => px(c).map(round).join(",")).join(" ");
  const font = skin.text * u;
  const said = (text: string) => (skin.upper ? text.toUpperCase() : text);
  const lit = goals(choice);
  // Manöver: the owner's label instead of the name, the id kept for every click (STV-46).
  const show = owner?.shown ?? EVERYTHING;
  const trackLabel = (name: string) => owner?.labels.tracks[name] ?? name;
  const signalLabel = (name: string) => owner?.labels.signals[name] ?? name;
  const switchLabel = (number: string) => owner?.labels.switches[number] ?? number;
  const skinClass = `skal-${skin.id}${owner ? " skal-manover" : ""}`;
  const at = (name: string) => drawn.signals.find((s) => s.name === name)?.symbol ?? drawn.points.find((p) => p.name === name)?.cell;
  const start = choice ? at(choice.start) : undefined;
  const chosenAt = chosen ? at(chosen.start) : undefined;
  const press = (work: () => void) => (event: KeyboardEvent) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      work();
    }
  };
  /** A symbol's shapes, from its own frame (x along `toward`, y to the side `side` says) to the panel. */
  const placed = (shapes: Shape[], where: Cell, toward: Cell, key: string, side = 1) => {
    const [tx, ty] = unit(toward);
    const [nx, ny] = [ty * side, -tx * side];
    const [x, y] = px(where);
    return shapes.map((shape, i) => {
      const points = shape.points.map(([a, h]) => `${round(x + (tx * a + nx * h) * u)},${round(y + (ty * a + ny * h) * u)}`).join(" ");
      const style = { fill: shape.fill ?? "none", stroke: shape.stroke ?? "none", strokeWidth: shape.width * u };
      return shape.closed ? <polygon key={`${key}${i}`} points={points} style={style} strokeLinejoin="miter" /> : <polyline key={`${key}${i}`} points={points} style={style} />;
    });
  };
  /** Which way the frame's y goes for a signal: towards the side its id stands on. */
  const sideOf = (s: DrawnSignal) => {
    const [tx, ty] = unit(s.toward);
    const [nx, ny] = [ty, -tx];
    const away = (s.label[0] - s.symbol[0]) * dx * nx + (s.label[1] - s.symbol[1]) * dy * ny;
    return away < 0 ? -1 : 1;
  };
  const look = (s: DrawnSignal) => skin.signal({ type: s.type, aspect: s.aspect, end: s.end, blocked: s.blocked });
  const gapOf = (s: DrawnSignal) => {
    const { gap } = look(s);
    if (!gap) return null;
    const [tx, ty] = unit(s.toward);
    const a: Cell = [s.symbol[0] + tx * gap[0], s.symbol[1] + ty * gap[0]];
    const b: Cell = [s.symbol[0] + tx * gap[1], s.symbol[1] + ty * gap[1]];
    return <polyline key={`g${s.name}`} points={line([a, b])} style={{ stroke: skin.ground, strokeWidth: (skin.stateWidth + 0.14) * u, fill: "none" }} />;
  };
  /** Where a signal's id stands: as the layout says, or in 59 beyond the symbol at its mast. */
  const labelOf = (s: DrawnSignal): Cell => {
    if (!skin.beside || s.type === "stop_lamp") return s.label;
    const [tx, ty] = unit(s.toward);
    const side = sideOf(s);
    const [nx, ny] = [ty * side, -tx * side];
    const [x, y] = px(s.symbol);
    return [(x + (tx * skin.beside.along + nx * skin.beside.label) * u) / dx, (y + (ty * skin.beside.along + ny * skin.beside.label) * u) / dy];
  };
  /** A slip's bow: a short stroke beside the straight leg, on the side the other leg turns to.
   * 85 is the stroke of TDOK 2014:0693 7.16–7.17. 95 is the thinner, shorter stroke of the
   * principskiss in TDOK 2021:0552 5.2.21.2–3, about a third of the track's width. */
  const bowOf = (knot: Cell, legs: [Cell[], Cell[]]): Cell[] => {
    const [cx, cy] = px(knot);
    const from = (leg: Cell[]) => {
      const [x, y] = px(leg[leg.length - 1] as Cell);
      return unit([x - cx, y - cy]);
    };
    const [a, b] = [from(legs[0]), from(legs[1])];
    const [h, d] = Math.abs(a[1]) <= Math.abs(b[1]) ? [a, b] : [b, a];
    const along = d[0] * h[0] + d[1] * h[1];
    const n = unit([d[0] - along * h[0], d[1] - along * h[1]]);
    const open = skin.id === "95";
    const w = (open ? skin.width : skin.stateWidth) * u;
    const reach = open ? 2.2 : 2.1;
    const aside = open ? 1.9 : 1.5;
    const half = open ? 1.05 : 1.2;
    const m: Cell = [cx + h[0] * reach * w + n[0] * aside * w, cy + h[1] * reach * w + n[1] * aside * w];
    return [
      [(m[0] - h[0] * half * w) / dx, (m[1] - h[1] * half * w) / dy],
      [(m[0] + h[0] * half * w) / dx, (m[1] + h[1] * half * w) / dy],
    ];
  };
  const bowWidth = (skin.id === "95" ? skin.width / 3 : 0.6 * skin.stateWidth) * u;
  const trackWidth = (state: string) => (state === "free" || state === "out_of_service" ? skin.width : skin.stateWidth) * u;
  const toggle = (where: Cell, toward: Cell | null, key: string): ReactNode => {
    // Model 59's toggle switch: a short light lever in a light metal ring (SJH s. 152, 157),
    // folded in the train's direction while its route is asked for or set.
    const [x, y] = px(where);
    const r = 0.26 * u;
    const [tx, ty] = toward ? unit(toward) : [0, 0];
    const tip: Cell = [x + tx * r * 0.95, y + ty * r * 0.95];
    return (
      <g key={key} className="vippa" data-folded={toward ? "ja" : undefined} pointerEvents="none">
        <circle cx={round(x)} cy={round(y)} r={round(r)} fill="#c3c7c9" stroke="#6c7174" strokeWidth={0.03 * u} />
        <circle cx={round(x)} cy={round(y)} r={round(r * 0.45)} fill="#1a1c1d" />
        {toward ? <line x1={round(x)} y1={round(y)} x2={round(tip[0])} y2={round(tip[1])} stroke="#e9e8e2" strokeWidth={0.13 * u} strokeLinecap="round" /> : null}
        <circle cx={round(tip[0])} cy={round(tip[1])} r={round(r * 0.5)} fill="#f3f2ec" stroke="#8d908e" strokeWidth={0.02 * u} />
      </g>
    );
  };
  const lamp = (where: Cell, colour: string, key: string, r = 0.16, glow = false): ReactNode => {
    const [x, y] = px(where);
    return (
      <g key={key}>
        {glow ? <circle cx={round(x)} cy={round(y)} r={round(r * 2.1 * u)} fill={colour} opacity={0.28} /> : null}
        <circle cx={round(x)} cy={round(y)} r={round(r * 1.3 * u)} fill={p59?.rim ?? "#000"} />
        <circle cx={round(x)} cy={round(y)} r={round(r * u)} fill={colour} />
      </g>
    );
  };
  return (
    <div className={`stv-ram ${skinClass}`} style={{ background: skin.ground, ...(p59 ? { borderImage: `${p59.frame} 1` } : {}) }}>
      <svg
        className={`stv-panel ${skinClass}`}
        data-symbols={owner ? skin.id : undefined}
        viewBox={`${round(box.x)} ${round(box.y)} ${round(box.width)} ${round(box.height)}`}
        role="group"
        aria-label={say("panel")}
        preserveAspectRatio="xMidYMid meet"
        style={{ fontFamily: skin.font, maxHeight: height }}
      >
        <rect x={box.x} y={box.y} width={box.width} height={box.height} fill={skin.ground} />
        {lamps && title ? (
          <text className="stationsnamn" x={round(box.x + box.width / 2)} y={round(grid.y - 0.55 * dy)} textAnchor="middle" fontSize={round(0.95 * u)} fontWeight={700} letterSpacing={round(0.2 * u)} fill={skin.label}>
            {said(title)}
          </text>
        ) : null}
        {(panel.platforms ?? []).map(([x1, y1, x2, y2], i) => (
          <rect key={`p${i}`} x={x1 * dx} y={y1 * dy} width={(x2 - x1) * dx} height={(y2 - y1) * dy} fill={skin.platform} />
        ))}
        <g className="spar" fill="none" strokeLinejoin="round">
          {drawn.lines.map((l) => (
            <polyline
              key={l.piece}
              data-piece={l.piece}
              data-state={l.state}
              data-outside={outside(l.piece) ? "ja" : undefined}
              opacity={outside(l.piece) ? GREY : undefined}
              points={line(lamps ? l.cells : cut(l.cells, l.cut.start ? skin.gap : 0, l.cut.end ? skin.gap : 0))}
              stroke={skin.tracks[l.state]}
              strokeWidth={round(trackWidth(lamps ? "free" : l.state))}
              strokeDasharray={!lamps && l.state === "out_of_service" ? `${round(0.3 * u)} ${round(0.22 * u)}` : undefined}
            />
          ))}
        </g>
        {!lamps ? (
          <g className="bagar" fill="none" pointerEvents="none">
            {/* Korsningsväxelns bågar, ett kort streck vid knuten parallellt med det raka benet.
                85: TDOK 2014:0693 7.16–7.17. 95: TDOK 2021:0552 5.2.21.2–3, tunnare (STV-22). */}
            {drawn.switches.flatMap((s) =>
              s.bows.map((b, i) => (
                <polyline
                  key={`b${s.number}${i}`}
                  data-bow={s.number}
                  data-state={b.state}
                  opacity={switchOutside(s.parts) ? GREY : undefined}
                  points={line(bowOf(s.cell, b.legs))}
                  stroke={skin.tracks[b.state]}
                  strokeWidth={round(bowWidth)}
                />
              )),
            )}
          </g>
        ) : null}
        {lamps && p59 ? (
          <g className="lampor">
            {/* Avbrott i spårlinjen där två spårledningar möts, 5 enheter (SJH s. 152). */}
            {drawn.boundaries.map((b, i) => {
              const [tx, ty] = unit(b.toward);
              const half = 2.6 / 24;
              return <polyline key={`b${i}`} points={line([[b.at[0] - tx * half, b.at[1] - ty * half], [b.at[0] + tx * half, b.at[1] + ty * half]])} stroke={skin.ground} strokeWidth={round(0.42 * u)} fill="none" />;
            })}
            {/* Vit lampa i spåret som lyser när spårledningen är fri, en till fyra per spårledning (SJH s. 152). */}
            {drawn.lamps.map((l, i) => (
              <g key={`l${i}`} data-lamp={l.section} data-free={l.free ? "ja" : "nej"}>
                {lamp(l.at, l.free ? p59.lit : p59.lens, `l${i}`, 0.16, l.free)}
              </g>
            ))}
            {/* Blått sken i benet växeln ligger åt (SJH s. 151–152); den andra öppningen mörk. */}
            {drawn.switches.flatMap((s) => {
              const out: ReactNode[] = [];
              const opening = (cells: Cell[] | null, colour: string, key: string, glow: boolean) => {
                if (!cells) return;
                const leg = fromKnot(cells, s.cell, 0.55);
                const end = leg[leg.length - 1];
                if (end) out.push(lamp(end, colour, key, 0.13, glow));
              };
              opening(s.other, p59.lens, `${s.number}o`, false);
              opening(s.lies, p59.position, `${s.number}l`, true);
              return out;
            })}
            {/* Två pilar i spåret vid start och mål för en lagd väg (SJH s. 157); växlingsväg gul och mindre. */}
            {drawn.arrows.map((a, i) => {
              const k = a.kind === "shunting" ? 0.8 : 1;
              const pts: [number, number][] = [[-0.25, 0.18], [0.08, 0.18], [0.08, 0.29], [0.33, 0], [0.08, -0.29], [0.08, -0.18], [-0.25, -0.18]];
              const shapes: Shape[] = [{ points: pts.map(([x, y]) => [x * k, y * k]), closed: true, fill: a.kind === "shunting" ? p59.shunting : p59.train, stroke: "#0c0f0d", width: 0.03 }];
              return (
                <g key={`a${a.route}-${i}`} data-arrow={a.kind}>
                  {placed(shapes, a.at, a.toward, `a${i}`)}
                </g>
              );
            })}
          </g>
        ) : null}
        {!lamps ? (
          <g className="skydd" fill="none" strokeWidth={skin.stateWidth * u}>
            {drawn.switches
              .filter((s) => (s.protection || s.local) && s.lies && s.trunk)
              .flatMap((s) => [
                <polyline key={`${s.number}l`} data-protection={s.protection ? s.number : undefined} data-local={s.local ? s.number : undefined} stroke={s.local ? skin.local : skin.protection} points={line(fromKnot(s.lies ?? [], s.cell, 0.9))} />,
                <polyline key={`${s.number}t`} stroke={s.local ? skin.local : skin.protection} points={line(fromKnot(s.trunk ?? [], s.cell, 0.3))} />,
              ])}
          </g>
        ) : null}
        <g className="sparrar">
          {drawn.derailers.map((d) => {
            // Spårspärren (TKL129): a short bar across the track, on it when på and beside it when
            // av; yellow while a route has it locked as protection (STV-20).
            const [x, y] = px(d.cell);
            const shift = d.position === "+" ? 0.38 : 0;
            const half = 0.3;
            const at = (k: number): Cell => [x + d.across[0] * (shift + k) * dx, y + d.across[1] * (shift + k) * dy];
            const [a, b] = [at(-half), at(half)];
            const colour = d.protection ? skin.protection : skin.switchNumber;
            return (
              <g key={`d${d.number}`} data-derailer={d.number} data-position={d.position ?? ""} data-protection={d.protection ? d.number : undefined} opacity={d.laid ? 1 : 0.55}>
                <line x1={round(a[0])} y1={round(a[1])} x2={round(b[0])} y2={round(b[1])} stroke={colour} strokeWidth={round(0.16 * u)} strokeLinecap="butt" />
              </g>
            );
          })}
        </g>
        <g className="vandskivor">
          {drawn.tables.map((t) => {
            // The turntable: the pit as a circle and the bridge as a line at its angle, in the
            // track's colour, in the route's while a set route holds it (RS4).
            const [x, y] = px(t.cell);
            const r = t.radius * dx;
            const [tx, ty] = unit(t.toward);
            const end = r * 0.9;
            const colour = t.held === "train" ? skin.tracks.train : t.held === "shunting" ? skin.tracks.shunting : skin.tracks.free;
            const w = (t.held && !lamps ? skin.stateWidth : skin.width) * u;
            return (
              <g key={`t${t.id}`} data-turntable={t.id} data-bridge={t.piece ?? ""} data-angle={angleOf(t.toward)}>
                <circle cx={round(x)} cy={round(y)} r={round(r)} fill={skin.ground} stroke={skin.tracks.free} strokeWidth={round(skin.width * u * 0.6)} />
                <line
                  className="brygga"
                  x1={round(x - tx * end)}
                  y1={round(y - ty * end)}
                  x2={round(x + tx * end)}
                  y2={round(y + ty * end)}
                  stroke={colour}
                  strokeWidth={round(w)}
                  strokeLinecap="round"
                  strokeDasharray={t.known ? undefined : `${round(0.18 * u)} ${round(0.14 * u)}`}
                />
              </g>
            );
          })}
        </g>
        <g className="luckor">{drawn.signals.map(gapOf)}</g>
        <g className="signaler">
          {drawn.signals.map((s) => (
            <g key={s.name} data-signal={s.name} data-aspect={s.aspect} data-end={s.end ? "ja" : undefined} data-blocked={s.blocked ? "ja" : undefined} opacity={s.planned ? 0.4 : signalOutside(s.name) ? GREY : 1}>
              {placed(look(s).shapes, s.symbol, s.toward, s.name, sideOf(s))}
            </g>
          ))}
        </g>
        <g className="pilar">
          {drawn.signals
            .filter((s) => arrows[s.name])
            .map((s) => {
              // Beside the signal, on the other side from its id, so that both are read; the arrow
              // points the way the signal shows.
              const h = 1.15;
              const colour = ARROW[arrows[s.name] ?? "red"];
              const shape: Shape = { points: [[-0.35, h - 0.28], [0.45, h], [-0.35, h + 0.28]], closed: true, fill: colour, stroke: colour, width: 0.04 };
              return (
                <g key={`pil${s.name}`} data-arrow={s.name} data-arrow-colour={arrows[s.name]}>
                  {placed([shape], s.symbol, s.toward, `pil${s.name}`, -sideOf(s))}
                </g>
              );
            })}
        </g>
        <g className="stoppbockar">
          {drawn.buffers.map((b) => (
            <g key={b.id} data-buffer={b.id}>
              {placed(skin.buffer(b.end), b.cell, b.toward, b.id)}
            </g>
          ))}
        </g>
        <g className="texter" fontSize={font} fontWeight={600} textAnchor="middle" style={{ paintOrder: "stroke" }} stroke={skin.ground} strokeWidth={0.12 * u}>
          {show.switch_numbers
            ? drawn.switches.map((s) => (
                <text key={s.number} data-switch-number={s.number} x={s.label[0] * dx} y={s.label[1] * dy + font * 0.35} fill={skin.switchNumber} opacity={switchOutside(s.parts) ? GREY : s.laid ? 1 : 0.55} fontSize={font * 0.85}>
                  {said(switchLabel(s.number))}
                </text>
              ))
            : null}
          {show.switch_numbers
            ? drawn.derailers.map((d) => (
                <text key={`d${d.number}`} data-derailer-number={d.number} x={d.label[0] * dx} y={d.label[1] * dy + font * 0.35} fill={skin.switchNumber} opacity={d.laid ? 1 : 0.55} fontSize={font * 0.85}>
                  {said(d.number)}
                </text>
              ))
            : null}
          {drawn.labels.map((l) => (
            <text key={`${l.kind}${l.text}`} x={l.cell[0] * dx} y={l.cell[1] * dy + font * 0.35} textAnchor={l.anchor} fill={l.end ? skin.endLabel : skin.label}>
              {said(l.text)}
            </text>
          ))}
          {drawn.names
            .filter((n) => show.track_names && !n.hidden)
            .map((n) => (
              <text key={n.name} data-track-name={n.name} x={n.cell[0] * dx} y={n.cell[1] * dy} textAnchor="end" fill={skin.trackName} fontWeight={700}>
                {said(trackLabel(n.name))}
              </text>
            ))}
          {show.signal_ids
            ? drawn.signals.map((s) => {
                const [x, y] = labelOf(s);
                return (
                  <text key={s.name} data-signal-id={s.name} x={x * dx} y={y * dy + font * 0.35} fill={skin.signalId} opacity={s.planned ? 0.4 : signalOutside(s.name) ? GREY : 1} fontWeight={700}>
                    {said(signalLabel(s.name))}
                  </text>
                );
              })
            : null}
        </g>
        <g className="tagnummer" display={show.train_numbers ? undefined : "none"} fontSize={skin.numbers.size * u} fontWeight={skin.numbers.weight} textAnchor="middle" style={{ fontFamily: skin.numbers.font }}>
          {drawn.numbers.map((n) => {
            const colour = n.colour === "red" ? skin.numbers.red : skin.numbers.green;
            if (!colour) return null;
            const shown = n.number ? skin.numberText(n.number) : "-----";
            const w = (shown.length * 0.62 + 0.5) * skin.numbers.size * u;
            const h = skin.numbers.size * u * 1.3;
            // Beside an exit's name: past the name's characters, then half the number's width.
            const aside = n.after * 0.6 * skin.text * u + 0.4 * u + w / 2;
            const [x0, y] = px(n.at);
            const x = n.anchor === "start" ? x0 + aside : n.anchor === "end" ? x0 - aside : x0;
            // 59: a black window with a thin grey edge, a TKL addition. 85 and 95: a frame only
            // for an estimated position.
            const window = lamps && p59 ? <rect x={-w / 2} y={-h / 2} width={w} height={h} rx={0.06 * u} fill={p59.window.ground} stroke={p59.window.edge} strokeWidth={0.04 * u} /> : null;
            const frame = !lamps && n.estimated ? <rect x={-w / 2} y={-h / 2} width={w} height={h} fill="none" stroke={skin.numbers.frame} strokeWidth={0.05 * u} /> : null;
            const edge = skin.numbers.edge ? { stroke: skin.numbers.edge, strokeWidth: 0.12 * u, paintOrder: "stroke" as const } : {};
            return (
              <g key={n.key} data-number={n.number ?? ""} data-colour={n.colour} style={{ transform: `translate(${round(x)}px, ${round(y)}px)` }}>
                {window ?? frame}
                <text y={skin.numbers.size * u * 0.36} fill={colour} {...edge}>
                  {shown}
                  <title>{n.estimated ? `${shown} · ${say("estimated")}` : shown}</title>
                </text>
              </g>
            );
          })}
        </g>
        {lamps ? (
          <g className="vippor">
            {drawn.signals
              .filter((s) => s.type !== "stop_lamp")
              .map((s) => toggle(s.symbol, s.folded || choice?.start === s.name ? s.toward : null, `v${s.name}`))}
            {drawn.switches
              .filter((s) => s.laid && s.lies)
              .map((s) => {
                const leg = fromKnot(s.lies ?? [], s.cell, 0.5);
                const end = leg[leg.length - 1] ?? s.cell;
                return toggle(s.cell, [end[0] - s.cell[0], end[1] - s.cell[1]], `w${s.number}`);
              })}
          </g>
        ) : null}
        <g className="knappar" fontFamily={skin.font}>
          {drawn.buttons.map((b) => {
            const [x, y] = px(b.cell);
            const w = 2.4 * u;
            const h = 0.9 * u;
            const on = b.on;
            const colour = b.type === "programming_track" ? skin.local : b.type === "local_release" ? skin.lamps.local : b.type === "signal_stop" ? skin.lamps.stop : skin.lamps.on;
            const name = b.type === "programming_track" ? say("programmingButton", { name: b.name }) : b.name;
            return (
              <g
                key={`f${b.name}`}
                role="button"
                tabIndex={0}
                aria-label={name}
                aria-pressed={on}
                data-function={b.name}
                data-on={on ? "ja" : undefined}
                onClick={() => onButton?.(b.name)}
                onKeyDown={press(() => onButton?.(b.name))}
                style={{ cursor: "pointer" }}
              >
                <title>{`${name} · ${on ? say("functionOn") : say("functionOff")}`}</title>
                {lamps ? (
                  <>
                    {lamp([b.cell[0] - 0.75 * (u / dx), b.cell[1]], on ? colour : skin.lamps.off, `fl${b.name}`, 0.16, on)}
                    {toggle([b.cell[0] + 0.25 * (u / dx), b.cell[1]], on ? [1, 0] : null, `ft${b.name}`)}
                  </>
                ) : (
                  <>
                    <rect x={round(x - w / 2)} y={round(y - h / 2)} width={round(w)} height={round(h)} rx={round(0.15 * u)} fill={on ? colour : skin.ground} stroke={on ? "#ffffff" : colour} strokeWidth={round(0.08 * u)} />
                    <text x={round(x)} y={round(y + 0.22 * u)} textAnchor="middle" fontSize={round(0.6 * u)} fontWeight={800} fill={on ? "#000000" : "#ffffff"}>
                      {b.type === "programming_track" ? "PROG" : said(b.name)}
                    </text>
                  </>
                )}
              </g>
            );
          })}
        </g>
        <g className="klick">
          {onRoute
            ? drawn.lines
                .filter((l) => l.route !== null)
                .map((l) => (
                  <polyline key={l.piece} points={line(l.cells)} fill="none" stroke="transparent" strokeWidth={0.9 * u} onClick={() => l.route !== null && onRoute(l.route)} style={{ cursor: "pointer" }} />
                ))
            : null}
          {drawn.tables.flatMap((t) =>
            t.function && onTable
              ? t.tracks.map((k) => {
                  const fn = t.function as string;
                  const turn = () => onTable(fn, k.piece);
                  const name = say("turnTable", { name: fn, track: k.label });
                  return (
                    <g key={`v${t.id}${k.piece}`} role="button" tabIndex={0} aria-label={name} data-table-track={k.piece} onClick={turn} onKeyDown={press(turn)} style={{ cursor: "pointer" }}>
                      <title>{name}</title>
                      <polyline points={line(slice(k.cells, 0, 1.4))} fill="none" stroke="transparent" strokeWidth={round(0.4 * u)} />
                    </g>
                  );
                })
              : [],
          )}
          {drawn.switches.filter((s) => !switchOutside(s.parts)).map((s) => {
            const [x, y] = px(s.cell);
            const part = s.parts[0];
            const state = [s.position ?? "?", s.routes.length ? say("locked", { routes: s.routes.join(", ") }) : null, s.protection ? say("protection") : null, s.local ? say("localSwitch") : null, s.laid ? null : say("notLaid")]
              .filter(Boolean)
              .join(" · ");
            return (
              <g
                key={s.number}
                role="button"
                tabIndex={0}
                aria-label={say("switchLabel", { name: switchLabel(s.number) })}
                data-position={s.position ?? ""}
                onClick={() => part && onSwitch?.(part)}
                onKeyDown={press(() => part && onSwitch?.(part))}
                style={{ cursor: "pointer" }}
              >
                <title>{`${say("switchLabel", { name: switchLabel(s.number) })} · ${state}`}</title>
                <circle cx={x} cy={y} r={0.75 * u} fill="transparent" />
              </g>
            );
          })}
          {drawn.derailers.map((d) => {
            const [x, y] = px(d.cell);
            const name = say("derailerLabel", { name: d.number });
            const state = [d.position === "-" ? say("derailerOn") : d.position === "+" ? say("derailerOff") : "?", d.routes.length ? say("locked", { routes: d.routes.join(", ") }) : null, d.protection ? say("protection") : null, d.laid ? null : say("notLaid")]
              .filter(Boolean)
              .join(" · ");
            return (
              <g key={`d${d.number}`} role="button" tabIndex={0} aria-label={name} data-position={d.position ?? ""} onClick={() => onSwitch?.(d.number)} onKeyDown={press(() => onSwitch?.(d.number))} style={{ cursor: "pointer" }}>
                <title>{`${name} · ${state}`}</title>
                <circle cx={x} cy={y} r={0.6 * u} fill="transparent" />
              </g>
            );
          })}
          {[
            ...drawn.signals.filter((s) => !signalOutside(s.name)).map((s) => ({ name: s.name, at: s.symbol, label: say("signal", { name: signalLabel(s.name) }), toggle: lamps && s.type !== "stop_lamp" })),
            ...drawn.points.map((p) => ({ name: p.name, at: p.cell, label: say("point", { name: p.name }), toggle: false })),
          ].map((p) => {
            const [x, y] = px(p.at);
            const click = () => (p.toggle && onToggle ? onToggle(p.name) : onPoint?.(p.name));
            return (
              <g key={`k${p.name}`} role="button" tabIndex={0} aria-label={p.label} data-toggle={p.toggle ? "ja" : undefined} onClick={click} onKeyDown={press(click)} style={{ cursor: "pointer" }}>
                <circle cx={x} cy={y} r={0.85 * u} fill="transparent" />
              </g>
            );
          })}
        </g>
        <g className="ringar" fill="none" pointerEvents="none">
          {lit.map((t) => {
            const where = at(t.end);
            if (!where) return null;
            const [x, y] = px(where);
            return (
              <circle
                key={`m${t.end}`}
                data-goal={t.end}
                className={t.possible ? "mal" : "mal sparrat"}
                cx={x}
                cy={y}
                r={0.95 * u}
                stroke={t.possible ? skin.rings.goal : skin.rings.blocked}
                strokeWidth={0.16 * u}
                strokeDasharray={t.possible ? undefined : `${0.25 * u} ${0.2 * u}`}
              >
                <title>{t.possible ? (t.via?.length ? `${t.end} (${t.via.join(", ")})` : t.end) : (t.reason ?? t.end)}</title>
              </circle>
            );
          })}
          {chosen && chosenAt ? <circle data-chosen={chosen.start} cx={px(chosenAt)[0]} cy={px(chosenAt)[1]} r={1.05 * u} stroke={skin.rings.chosen} strokeWidth={0.1 * u} /> : null}
          {choice && start ? (
            <circle data-start={choice.start} data-kind={choice.kind} cx={px(start)[0]} cy={px(start)[1]} r={1.05 * u} stroke={choice.kind === "shunting" ? skin.rings.shunting : skin.rings.train} strokeWidth={0.22 * u} />
          ) : null}
        </g>
      </svg>
    </div>
  );
}
