// Foto, the fun skin (STV-06, STV-12): the station seen from above in its real shape, drawn as
// vectors after the skins document's table: grass with a dot pattern, the platforms and the
// building where the plan has them, trees and bushes; ballast, concrete sleepers and two rails;
// a glow under the rails and a band between them in the state's colour (green train route, yellow
// shunting, red occupied); red buffer stops; the signals from above, post, screen and lamp, with
// the name on a white sign; and the trains, which roll along the route's pieces when Kör moves
// them (STV-06). The geometry is worked out in foto.ts; a click goes to the page through the same
// click flow as every skin, and the page asks the interlocking (STV-43).
import { useEffect, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import type { Panel } from "./api";
import { along, ease, FOTO, fotoScene, offset, placeIn, placeTrain, PX_PER_UNIT, ROLL_MS, rollOf, type FotoScene, type FotoTrain, type Pt, type Roll } from "./foto";
import type { Skin } from "./skal";
import { round } from "./sparplan";
import { angleOf, goals, slice, type Choice, type Drawing, type Filled, type TrackState } from "./stallverk";
import type { Say } from "./texter";

export type Zoom = "near" | "whole";

type Props = {
  panel: Panel;
  drawn: Drawing;
  state: Filled;
  skin: Skin;
  say: Say;
  choice?: Choice | null;
  chosen?: { id: number; start: string } | null;
  /** The panel's share of the screen (STV-05). */
  height?: string;
  /** Närbild at the skins document's scale, or the whole station; Närbild unless chosen. */
  zoom?: Zoom;
  onPoint?: (name: string) => void;
  onSwitch?: (part: string) => void;
  onRoute?: (route: number) => void;
  onButton?: (name: string) => void;
  onTable?: (fn: string, piece: string) => void;
};

/** The state's colour in Foto: the glow and the band between the rails (the skins document). */
const GLOW: Partial<Record<TrackState, string>> = { train: "#3ee07a", shunting: "#ffd000", occupied: "#ff4b3e", local: "#4da3ff", programming: "#4da3ff", out_of_service: "#ffffff" };
const RED = "#ff3b30";
const GREEN = "#39e46b";
const pts = (path: Pt[]) => path.map((p) => `${round(p[0])},${round(p[1])}`).join(" ");
const degrees = (v: Pt) => round((Math.atan2(v[1], v[0]) * 180) / Math.PI);
const left = (v: Pt): Pt => [v[1], -v[0]];

/** A train's vehicles, in units: a passenger coach rounded with a red line under the windows, a
 * goods train's locomotive and square wagons (the skins document, TKL29). */
function vehicle(kind: FotoTrain["kind"], index: number, count: number, length: number): ReactNode {
  const L = length;
  if (kind === "passenger") {
    const B = FOTO.coachWidth;
    const end = index === 0 ? 1 : index === count - 1 ? -1 : 0;
    return (
      <>
        <rect x={-L / 2} y={-B / 2} width={L} height={B} rx={end ? B / 2 : 2.4} fill="#ebeae5" stroke="#6a6d70" strokeWidth={0.7} />
        <rect x={-L / 2 + (end < 0 ? 7 : 3)} y={-B / 2 + 2.2} width={L - 10} height={B - 4.4} rx={end ? B / 2 - 2 : 1.5} fill="#d3d5d6" />
        {end ? <path d={`M${end * (L / 2 - 6)},${-B / 2 + 1.6} Q${end * (L / 2 - 1)},0 ${end * (L / 2 - 6)},${B / 2 - 1.6}`} fill="none" stroke="#2b3440" strokeWidth={2.2} /> : null}
        <rect x={-L / 2 + 2} y={-B / 2} width={L - 4} height={1.4} fill="#b3262b" />
        <rect x={-L / 2 + 2} y={B / 2 - 1.4} width={L - 4} height={1.4} fill="#b3262b" />
      </>
    );
  }
  const B = FOTO.goodsWidth;
  if (index === 0) {
    return (
      <>
        <rect x={-L / 2} y={-B / 2} width={L} height={B} fill="#d0471f" stroke="#5c1f0e" strokeWidth={0.8} />
        <rect x={-L / 2 + 3} y={-B / 2 + 2} width={L - 6} height={B - 4} fill="#8c8f93" />
        <rect x={L / 2 - 3} y={-B / 2 + 2} width={2} height={B - 4} fill="#1f2a33" />
      </>
    );
  }
  const colours = ["#7a3b26", "#4d5560", "#9a9c98", "#7a3b26", "#3f5b3a"];
  const colour = colours[(index - 1) % colours.length] as string;
  return (
    <>
      <rect x={-L / 2} y={-B / 2} width={L} height={B} fill={colour} stroke="#2b2b2b" strokeWidth={0.8} />
      <path d={`M${-L / 2},0 L${L / 2},0`} stroke="#2b2b2b" strokeOpacity={0.4} strokeWidth={1} />
    </>
  );
}

/** Kör rolls a train from the section it stood on to the next, in about a second (STV-06). The
 * rolls start before the page is painted, so a train never jumps ahead and back. */
function useRolling(trains: FotoTrain[], u: number, onStart: (to: Pt) => void): { rolls: Map<number, Roll>; t: number } {
  const before = useRef<Map<number, FotoTrain>>(new Map());
  const [rolls, setRolls] = useState<Map<number, Roll>>(new Map());
  const [t, setT] = useState(1);
  const signature = trains.map((x) => `${x.train}@${x.key}`).join("|");
  useLayoutEffect(() => {
    const made = new Map<number, Roll>();
    for (const x of trains) {
      const was = before.current.get(x.train);
      if (was && was.key !== x.key) {
        const roll = rollOf(was, x, u);
        if (roll) made.set(x.train, roll);
      }
    }
    before.current = new Map(trains.map((x) => [x.train, x]));
    if (!made.size) return;
    setRolls(made);
    setT(0);
    const first = [...made.values()][0] as Roll;
    onStart(along(first.path, first.to).at);
    const started = performance.now();
    let frame = 0;
    const tick = (now: number) => {
      const done = Math.min(1, (now - started) / ROLL_MS);
      setT(done);
      if (done < 1) frame = requestAnimationFrame(tick);
      else setRolls(new Map());
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
    // The trains are read through their signature: a roll starts only when one has moved.
  }, [signature, u]);
  return { rolls, t };
}

export function Foto({ panel, drawn, state, skin, say, choice = null, chosen = null, height, zoom: startZoom = "near", onPoint, onSwitch, onRoute, onButton, onTable }: Props) {
  const scene = useMemo(() => fotoScene(panel, drawn, state), [panel, drawn, state]);
  const [zoom, setZoom] = useState<Zoom>(startZoom);
  const frame = useRef<HTMLDivElement>(null);
  const follow = (to: Pt, smooth = true) => {
    const box = scene?.box;
    const div = frame.current;
    if (!box || !div || typeof div.scrollTo !== "function") return;
    const [fx, fy] = placeIn(box, to);
    div.scrollTo({ left: fx * div.scrollWidth - div.clientWidth / 2, top: fy * div.scrollHeight - div.clientHeight / 2, behavior: smooth ? "smooth" : "auto" });
  };
  const { rolls, t } = useRolling(scene?.trains ?? [], scene?.u ?? 1, (to) => follow(to));
  // Närbild opens at the first train, or mid-station without one.
  useEffect(() => {
    if (!scene || zoom !== "near") return;
    const train = scene.trains[0];
    const [x, y, w, h] = scene.box;
    follow(train ? along(train.path, train.at).at : [x + w / 2, y + h / 2], false);
  }, [zoom, scene === null]);
  if (!scene) return null;
  const { u, box } = scene;
  const lit = goals(choice);
  const at = (name: string): Pt | undefined => scene.signals.find((s) => s.name === name)?.track ?? scene.points.find((p) => p.name === name)?.at;
  const start = choice ? at(choice.start) : undefined;
  const chosenAt = chosen ? at(chosen.start) : undefined;
  const press = (work: () => void) => (event: KeyboardEvent) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      work();
    }
  };
  const place = (where: Pt, heading: Pt = [1, 0]) => `translate(${round(where[0])} ${round(where[1])}) rotate(${degrees(heading)}) scale(${round(u * 1000) / 1000})`;
  const width = zoom === "near" ? `${Math.round((box[2] / u) * PX_PER_UNIT)}px` : "100%";
  return (
    <div className="stv-foto">
      <div className="stv-foto-rad" role="group" aria-label={say("fotoZoom")}>
        <button type="button" aria-pressed={zoom === "near"} onClick={() => setZoom("near")}>
          {say("fotoNear")}
        </button>
        <button type="button" aria-pressed={zoom === "whole"} onClick={() => setZoom("whole")}>
          {say("fotoWhole")}
        </button>
      </div>
      <div ref={frame} className="stv-ram skal-foto" style={{ background: skin.ground, maxHeight: height }}>
        <svg
          className="stv-panel skal-foto"
          viewBox={`${round(box[0])} ${round(box[1])} ${round(box[2])} ${round(box[3])}`}
          role="group"
          aria-label={say("panel")}
          preserveAspectRatio="xMidYMid meet"
          data-zoom={zoom}
          style={{ fontFamily: skin.font, width, maxWidth: zoom === "near" ? "none" : undefined }}
        >
          <defs>
            <pattern id="foto-gras" width={14 * u} height={14 * u} patternUnits="userSpaceOnUse">
              <circle cx={3 * u} cy={4 * u} r={1.1 * u} fill="#839659" />
              <circle cx={10 * u} cy={9 * u} r={1.3 * u} fill="#9aab6c" />
              <circle cx={7 * u} cy={12 * u} r={0.8 * u} fill="#7b8e52" />
            </pattern>
            <pattern id="foto-ballast" width={5 * u} height={5 * u} patternUnits="userSpaceOnUse">
              <circle cx={1 * u} cy={1 * u} r={0.75 * u} fill="#8f8b82" />
              <circle cx={3.5 * u} cy={3 * u} r={0.7 * u} fill="#c4c0b5" />
              <circle cx={2 * u} cy={4.2 * u} r={0.55 * u} fill="#7b776f" />
            </pattern>
            <filter id="foto-skimmer" filterUnits="userSpaceOnUse" x={box[0]} y={box[1]} width={box[2]} height={box[3]}>
              <feGaussianBlur stdDeviation={3 * u} />
            </filter>
            <filter id="foto-skugga" filterUnits="userSpaceOnUse" x={box[0]} y={box[1]} width={box[2]} height={box[3]}>
              <feGaussianBlur stdDeviation={1.6 * u} />
            </filter>
          </defs>
          <rect x={box[0]} y={box[1]} width={box[2]} height={box[3]} fill="#91a265" />
          <rect x={box[0]} y={box[1]} width={box[2]} height={box[3]} fill="url(#foto-gras)" />
          <Landscape scene={scene} />
          <g className="ballast" fill="none" strokeLinejoin="round">
            {scene.tracks.map((k) => (
              <polyline key={`b${k.piece}`} points={pts(k.path)} stroke="#8d8a80" strokeWidth={FOTO.bank * u} opacity={0.55} />
            ))}
            {scene.tracks.map((k) => (
              <polyline key={`c${k.piece}`} points={pts(k.path)} stroke="#aaa69c" strokeWidth={FOTO.ballast * u} />
            ))}
            {scene.tracks.map((k) => (
              <polyline key={`d${k.piece}`} points={pts(k.path)} stroke="url(#foto-ballast)" strokeWidth={FOTO.ballast * u} />
            ))}
          </g>
          <g className="skimmer" fill="none" strokeLinejoin="round" filter="url(#foto-skimmer)">
            {scene.tracks
              .filter((k) => GLOW[k.state])
              .map((k) => (
                <polyline key={`g${k.piece}`} points={pts(k.path)} stroke={GLOW[k.state]} strokeWidth={FOTO.glow * u} opacity={k.state === "occupied" ? 0.6 : 0.8} />
              ))}
          </g>
          <g className="syllar" fill="none" strokeLinejoin="round">
            {scene.tracks.map((k) => (
              <polyline key={`s${k.piece}`} points={pts(k.path)} stroke="#bdb8ad" strokeWidth={FOTO.sleeper * u} strokeDasharray={`${round(FOTO.sleeperDash[0] * u)} ${round(FOTO.sleeperDash[1] * u)}`} />
            ))}
          </g>
          <g className="strak" fill="none" strokeLinejoin="round">
            {scene.tracks
              .filter((k) => GLOW[k.state])
              .map((k) => (
                <polyline
                  key={`k${k.piece}`}
                  data-piece={k.piece}
                  data-state={k.state}
                  points={pts(k.path)}
                  stroke={GLOW[k.state]}
                  strokeWidth={FOTO.band * u}
                  opacity={k.state === "occupied" ? 0.5 : 0.6}
                  strokeDasharray={k.state === "out_of_service" ? `${round(6 * u)} ${round(5 * u)}` : undefined}
                />
              ))}
          </g>
          <g className="ralar" fill="none" strokeLinejoin="round">
            {scene.tracks.flatMap((k) =>
              [-FOTO.gauge / 2, FOTO.gauge / 2].map((side) => {
                const rail = pts(offset(k.path, side * u));
                return (
                  <g key={`r${k.piece}${side}`} className="ral">
                    <polyline points={rail} stroke="#5d5f63" strokeWidth={FOTO.rail * u} />
                    <polyline points={rail} stroke="#dcdde0" strokeWidth={FOTO.railTop * u} />
                  </g>
                );
              }),
            )}
          </g>
          <g className="vandskivor">
            {scene.tables.map((k) => {
              const held = k.held === "train" ? GLOW.train : k.held === "shunting" ? GLOW.shunting : null;
              return (
                <g key={`t${k.id}`} data-turntable={k.id} data-bridge={k.piece ?? ""} data-angle={angleOf(k.heading)}>
                  <circle cx={round(k.at[0])} cy={round(k.at[1])} r={round(k.r)} fill="#5a5246" stroke="#8d8a80" strokeWidth={round(3 * u)} />
                  <circle cx={round(k.at[0])} cy={round(k.at[1])} r={round(k.r - 5 * u)} fill="none" stroke="#5d5f63" strokeWidth={round(FOTO.rail * u)} />
                  <g transform={place(k.at, k.heading)} className="brygga" opacity={k.known ? 1 : 0.6}>
                    <rect x={-k.r / u + 2} y={-8} width={(2 * k.r) / u - 4} height={16} fill="#4a4d50" stroke="#2b2d2f" strokeWidth={0.8} />
                    {held ? <rect x={-k.r / u + 3} y={-FOTO.band / 2} width={(2 * k.r) / u - 6} height={FOTO.band} fill={held} opacity={0.7} /> : null}
                    {[-FOTO.gauge / 2, FOTO.gauge / 2].map((side) => (
                      <line key={side} x1={-k.r / u + 2} y1={side} x2={k.r / u - 2} y2={side} stroke="#cfd1d4" strokeWidth={FOTO.rail} />
                    ))}
                  </g>
                </g>
              );
            })}
          </g>
          <g className="stoppbockar">
            {scene.buffers.map((b) => (
              <g key={b.id} data-buffer={b.id} transform={place(b.at, b.heading)}>
                <rect x={-2} y={-9} width={8} height={18} rx={1.5} fill="#b13b2e" stroke="#5a1d16" strokeWidth={1} />
                <rect x={-2} y={-2} width={8} height={4} fill="#f1e9d8" />
              </g>
            ))}
          </g>
          <g className="signaler">
            {scene.signals.map((s) => {
              const post: Pt = [s.track[0] + s.heading[0] * 9 * u + left(s.heading)[0] * 11 * u, s.track[1] + s.heading[1] * 9 * u + left(s.heading)[1] * 11 * u];
              const main = s.aspect === "proceed" ? GREEN : s.type === "fsi" ? "#ffb020" : RED;
              const dwarf = s.aspect === "local" ? "#4da3ff" : (s.type === "dvsi" ? s.aspect !== "stop" : s.aspect === "shunt" || s.aspect === "proceed") ? GREEN : RED;
              return (
                <g key={s.name} data-signal={s.name} data-aspect={s.aspect} data-end={s.end ? "ja" : undefined} data-blocked={s.blocked ? "ja" : undefined} opacity={s.planned ? 0.4 : 1}>
                  <g transform={place(post, s.heading)}>
                    <circle cx={0} cy={1.5} r={2.2} fill="#2a2a2a" />
                    {s.type === "dvsi" ? null : s.type === "stop_lamp" ? (
                      <>
                        <rect x={-3} y={-2.5} width={6} height={5} rx={1} fill="#1b1c1d" />
                        <circle cx={0} cy={0} r={1.6} fill={RED} />
                      </>
                    ) : (
                      <>
                        <rect x={-4.5} y={-3} width={9} height={6} rx={1.5} fill="#1b1c1d" />
                        <circle cx={1.8} cy={0} r={2} fill={main} />
                      </>
                    )}
                    {s.type === "dvsi" || s.type === "hdvsi" ? (
                      <>
                        <rect x={-15} y={-2.5} width={6} height={5} rx={1} fill="#1b1c1d" />
                        <circle cx={-12} cy={0} r={1.6} fill={dwarf} />
                      </>
                    ) : null}
                  </g>
                </g>
              );
            })}
          </g>
          <Texts scene={scene} />
          <g className="tag">
            {scene.trains.map((train) => {
              const roll = rolls.get(train.train);
              const path = roll ? roll.path : train.path;
              const s = roll ? roll.from + (roll.to - roll.from) * ease(t) : train.at;
              const cars = placeTrain(train.kind, path, s, u);
              const centre = along(path, s).at;
              const middle = cars[Math.floor(cars.length / 2)] ?? cars[0];
              const label = train.number ?? "";
              const w = 7 * label.length + 9;
              return (
                <g key={train.train} className="tag" data-train={label} data-train-id={train.train} data-x={Math.round(centre[0])} data-y={Math.round(centre[1])} data-rolling={roll && t < 1 ? "ja" : undefined}>
                  <g filter="url(#foto-skugga)">
                    {cars.map((c) => (
                      <g key={`s${c.index}`} transform={place([c.at[0] + 2.2 * u, c.at[1] + 2.8 * u], c.heading)}>
                        <rect x={-c.length / 2} y={-FOTO.coachWidth / 2} width={c.length} height={FOTO.coachWidth} rx={train.kind === "passenger" ? FOTO.coachWidth / 2 : 1} fill="#1d2416" opacity={0.32} />
                      </g>
                    ))}
                  </g>
                  {cars.map((c) => (
                    <g key={c.index} transform={place(c.at, c.heading)}>
                      {vehicle(train.kind, c.index, cars.length, c.length)}
                    </g>
                  ))}
                  {label && middle ? (
                    <g transform={`translate(${round(middle.at[0])} ${round(middle.at[1])}) scale(${round(u * 1000) / 1000})`}>
                      <rect x={-w / 2} y={-7} width={w} height={14} rx={7} fill={train.kind === "goods" ? "#3a2a1c" : "#1f2421"} stroke="#ffffff" strokeWidth={1} />
                      <text x={0} y={3.6} textAnchor="middle" fontSize={10.5} fontWeight={700} fill="#ffffff">
                        {label}
                      </text>
                    </g>
                  ) : null}
                </g>
              );
            })}
          </g>
          <g className="knappar">
            {scene.buttons.map((b) => {
              const name = b.type === "programming_track" ? say("programmingButton", { name: b.name }) : b.name;
              const text = b.type === "programming_track" ? "PROG" : b.name;
              const w = 6.5 * text.length + 10;
              return (
                <g key={`f${b.name}`} role="button" tabIndex={0} aria-label={name} aria-pressed={b.on} data-function={b.name} data-on={b.on ? "ja" : undefined} onClick={() => onButton?.(b.name)} onKeyDown={press(() => onButton?.(b.name))} style={{ cursor: "pointer" }}>
                  <title>{`${name} · ${b.on ? say("functionOn") : say("functionOff")}`}</title>
                  <g transform={`translate(${round(b.at[0])} ${round(b.at[1])}) scale(${round(u * 1000) / 1000})`}>
                    <rect x={-w / 2} y={-7} width={w} height={14} rx={4} fill={b.on ? "#4da3ff" : "#ffffff"} stroke="#1f2421" strokeWidth={1} />
                    <text x={0} y={3.5} textAnchor="middle" fontSize={9.5} fontWeight={800} fill="#1f2421">
                      {text}
                    </text>
                  </g>
                </g>
              );
            })}
          </g>
          <g className="klick">
            {onRoute
              ? scene.tracks
                  .filter((k) => k.route !== null)
                  .map((k) => <polyline key={k.piece} points={pts(k.path)} fill="none" stroke="transparent" strokeWidth={20 * u} onClick={() => k.route !== null && onRoute(k.route)} style={{ cursor: "pointer" }} />)
              : null}
            {scene.tables.flatMap((k) =>
              k.function && onTable
                ? k.tracks
                    .filter((track) => track.real.length > 1)
                    .map((track) => {
                      const fn = k.function as string;
                      const turn = () => onTable(fn, track.piece);
                      const name = say("turnTable", { name: fn, track: track.label });
                      return (
                        <g key={`v${k.id}${track.piece}`} role="button" tabIndex={0} aria-label={name} data-table-track={track.piece} onClick={turn} onKeyDown={press(turn)} style={{ cursor: "pointer" }}>
                          <title>{name}</title>
                          <polyline points={pts(slice(track.real, 0, k.r * 0.8) as Pt[])} fill="none" stroke="transparent" strokeWidth={14 * u} />
                        </g>
                      );
                    })
                : [],
            )}
            {scene.switches.map((s) => {
              const part = s.parts[0];
              return (
                <g key={s.number} role="button" tabIndex={0} aria-label={say("switchLabel", { name: s.number })} data-position={s.position ?? ""} onClick={() => part && onSwitch?.(part)} onKeyDown={press(() => part && onSwitch?.(part))} style={{ cursor: "pointer" }}>
                  <title>{`${say("switchLabel", { name: s.number })} · ${s.position ?? "?"}`}</title>
                  <circle cx={round(s.at[0])} cy={round(s.at[1])} r={round(12 * u)} fill="transparent" />
                </g>
              );
            })}
            {[...scene.signals.map((s) => ({ name: s.name, at: s.track, label: say("signal", { name: s.name }) })), ...scene.points.map((p) => ({ name: p.name, at: p.at, label: say("point", { name: p.name }) }))].map((p) => {
              const click = () => onPoint?.(p.name);
              return (
                <g key={`k${p.name}`} role="button" tabIndex={0} aria-label={p.label} onClick={click} onKeyDown={press(click)} style={{ cursor: "pointer" }}>
                  <circle cx={round(p.at[0])} cy={round(p.at[1])} r={round(13 * u)} fill="transparent" />
                </g>
              );
            })}
          </g>
          <g className="ringar" fill="none" pointerEvents="none">
            {lit.map((g) => {
              const where = at(g.end);
              if (!where) return null;
              return (
                <circle
                  key={`m${g.end}`}
                  data-goal={g.end}
                  className={g.possible ? "mal" : "mal sparrat"}
                  cx={round(where[0])}
                  cy={round(where[1])}
                  r={round(15 * u)}
                  stroke={g.possible ? skin.rings.goal : skin.rings.blocked}
                  strokeWidth={round(2.6 * u)}
                  strokeDasharray={g.possible ? undefined : `${round(4 * u)} ${round(3 * u)}`}
                >
                  <title>{g.possible ? g.end : (g.reason ?? g.end)}</title>
                </circle>
              );
            })}
            {chosen && chosenAt ? <circle data-chosen={chosen.start} cx={round(chosenAt[0])} cy={round(chosenAt[1])} r={round(17 * u)} stroke={skin.rings.chosen} strokeWidth={round(1.8 * u)} /> : null}
            {choice && start ? <circle data-start={choice.start} data-kind={choice.kind} cx={round(start[0])} cy={round(start[1])} r={round(17 * u)} stroke={choice.kind === "shunting" ? skin.rings.shunting : skin.rings.train} strokeWidth={round(3.4 * u)} /> : null}
          </g>
        </svg>
      </div>
    </div>
  );
}

/** The landscape: the platforms with their white edge, the building in brick red, and the trees
 * and bushes, each a few circles with a soft shadow. */
function Landscape({ scene }: { scene: FotoScene }) {
  const { u } = scene;
  return (
    <g className="landskap">
      {scene.platforms.map((p, i) => (
        <polygon key={`p${i}`} className="plattform" points={pts(p)} fill="#8d929a" stroke="#ecebe5" strokeWidth={2.2 * u} strokeLinejoin="round" />
      ))}
      {scene.building ? <polygon className="hus" points={pts(scene.building)} fill="#8e3f30" stroke="#6c2c22" strokeWidth={2 * u} strokeLinejoin="round" /> : null}
      {scene.trees.map((tree, i) => {
        const [x, y] = tree.at;
        const r = tree.r;
        return tree.bush ? (
          <g key={`t${i}`} className="buske">
            <circle cx={round(x)} cy={round(y)} r={round(r)} fill="#56743a" />
            <circle cx={round(x - r * 0.3)} cy={round(y - r * 0.3)} r={round(r * 0.55)} fill="#6d8f45" />
          </g>
        ) : (
          <g key={`t${i}`} className="trad">
            <circle cx={round(x + 2.5 * u)} cy={round(y + 3 * u)} r={round(r)} fill="#3d4a2a" opacity={0.35} />
            <circle cx={round(x)} cy={round(y)} r={round(r)} fill="#4f6b34" />
            <circle cx={round(x - r * 0.25)} cy={round(y - r * 0.25)} r={round(r * 0.62)} fill="#64843f" />
            <circle cx={round(x - r * 0.38)} cy={round(y - r * 0.4)} r={round(r * 0.26)} fill="#7a9a4f" />
          </g>
        );
      })}
    </g>
  );
}

/** The words: the signals' names on white signs, the switch numbers, the track names on plates
 * and the line exits in dark pills. Kept upright whatever way the track runs. */
function Texts({ scene }: { scene: FotoScene }) {
  const { u } = scene;
  const at = (p: Pt, body: ReactNode, key: string, extra: Record<string, string> = {}) => (
    <g key={key} transform={`translate(${round(p[0])} ${round(p[1])}) scale(${round(u * 1000) / 1000})`} {...extra}>
      {body}
    </g>
  );
  return (
    <g className="texter" fontWeight={700}>
      {scene.signals.map((s) => {
        const side = left(s.heading);
        const sign: Pt = [s.track[0] + s.heading[0] * 9 * u + side[0] * 20 * u, s.track[1] + s.heading[1] * 9 * u + side[1] * 20 * u];
        const w = 6 * s.name.length + 7;
        return at(
          sign,
          <>
            <rect x={-w / 2} y={-5.5} width={w} height={11} rx={2.5} fill="#ffffff" opacity={0.9} />
            <text x={0} y={3} textAnchor="middle" fontSize={8.5} fill="#1f2421">
              {s.name}
            </text>
          </>,
          `s${s.name}`,
          { "data-signal-id": s.name, opacity: s.planned ? "0.4" : "1" },
        );
      })}
      {scene.switches.map((s) =>
        at(
          s.label,
          <text x={0} y={3} textAnchor="middle" fontSize={8.5} fill="#1f2421" stroke="#f3f1ea" strokeWidth={2.6} style={{ paintOrder: "stroke" }} opacity={s.laid ? 1 : 0.55}>
            {s.number}
          </text>,
          `v${s.number}`,
          { "data-switch-number": s.number },
        ),
      )}
      {scene.names
        .filter((n) => !n.hidden)
        .map((n) => {
          const w = 7.5 * n.name.length + 8;
          return at(
            n.at,
            <>
              <rect x={-w / 2} y={-6.5} width={w} height={13} rx={2} fill="#f7f5ef" stroke="#3a3f3b" strokeWidth={1} />
              <text x={0} y={3.4} textAnchor="middle" fontSize={9.5} fontWeight={800} fill="#1f2421">
                {n.name}
              </text>
            </>,
            `n${n.name}`,
            { "data-track-name": n.name },
          );
        })}
      {scene.labels.map((l) => {
        if (l.kind === "point") {
          return at(
            [l.at[0], l.at[1] - 12 * u],
            <text x={0} y={3} textAnchor="middle" fontSize={8} fill="#1f2421" stroke="#f3f1ea" strokeWidth={2.4} style={{ paintOrder: "stroke" }}>
              {l.text}
            </text>,
            `p${l.text}`,
          );
        }
        const w = 6.2 * l.text.length + 12;
        return at(
          [l.at[0], l.at[1] - 18 * u],
          <>
            <rect x={-w / 2} y={-7.5} width={w} height={15} rx={7.5} fill="#1f2421" opacity={0.82} />
            <text x={0} y={3.4} textAnchor="middle" fontSize={9.5} fill="#ffffff">
              {l.text}
            </text>
          </>,
          `e${l.text}`,
        );
      })}
    </g>
  );
}

/** Foto without the station's real shape: greyed, with the reason (STV-18). */
export function FotoGreyed({ say, height }: { say: Say; height?: string }) {
  return (
    <div className="stv-ram skal-foto gratt" role="note" style={{ minHeight: height ? `min(${height}, 240px)` : "200px" }}>
      <p>
        <b>{say("fotoGreyed")}</b>
      </p>
      <p className="liten">{say("fotoGreyedNote")}</p>
    </div>
  );
}

