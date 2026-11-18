// The interlocking's panel at level 1–2 (#84), drawn in SVG over the station's panel geometry
// (#83). What is drawn comes from stallverk.ts in logical terms; the skin (skal.ts) gives every
// colour, width and symbol, so another skin is another Skin over the same geometry. Clicks go
// to the page, which asks the interlocking: the panel decides nothing (STV-43).
import type { KeyboardEvent } from "react";
import type { Panel } from "./api";
import type { Shape, Skin } from "./skal";
import { cut, fromKnot, goals, type Cell, type Choice, type Drawing, type DrawnSignal } from "./stallverk";
import { round, viewBox } from "./sparplan";
import type { Say } from "./texter";

type Props = {
  panel: Panel;
  drawn: Drawing;
  skin: Skin;
  say: Say;
  choice?: Choice | null;
  /** The set route chosen for the buttons: its start gets a white ring. */
  chosen?: { id: number; start: string } | null;
  /** The panel's share of the screen (STV-05): at most this high, as wide as it may be. */
  height?: string;
  onPoint?: (name: string) => void;
  onSwitch?: (part: string) => void;
  onRoute?: (route: number) => void;
};

const unit = (v: Cell): Cell => {
  const n = Math.hypot(v[0], v[1]) || 1;
  return [v[0] / n, v[1] / n];
};

export function Panelen({ panel, drawn, skin, say, choice = null, chosen = null, height, onPoint, onSwitch, onRoute }: Props) {
  const [dx, dy] = panel.cell;
  // The grid's view, with room at the ends for an exit's name and a train number beside it.
  const grid = viewBox(panel, "schematic", null);
  const box = { ...grid, x: grid.x - 3.5 * dx, width: grid.width + 7 * dx };
  const u = Math.min(dx, dy);
  const px = (c: Cell): Cell => [c[0] * dx, c[1] * dy];
  const line = (cells: Cell[]) => cells.map((c) => px(c).map(round).join(",")).join(" ");
  const font = skin.text * u;
  const lit = goals(choice);
  const start = choice ? (drawn.signals.find((s) => s.name === choice.start)?.symbol ?? drawn.points.find((p) => p.name === choice.start)?.cell) : undefined;
  const chosenAt = chosen ? (drawn.signals.find((s) => s.name === chosen.start)?.symbol ?? drawn.points.find((p) => p.name === chosen.start)?.cell) : undefined;
  const press = (work: () => void) => (event: KeyboardEvent) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      work();
    }
  };
  /** A symbol's shapes, from its own frame (x along `toward`, y to the left of it) to the panel. */
  const placed = (shapes: Shape[], at: Cell, toward: Cell, key: string) => {
    const [tx, ty] = unit(toward);
    const [nx, ny] = [ty, -tx];
    const [x, y] = px(at);
    return shapes.map((shape, i) => {
      const points = shape.points.map(([a, h]) => `${round(x + (tx * a + nx * h) * u)},${round(y + (ty * a + ny * h) * u)}`).join(" ");
      const style = { fill: shape.fill ?? "none", stroke: shape.stroke ?? "none", strokeWidth: shape.width * u };
      return shape.closed ? <polygon key={`${key}${i}`} points={points} style={style} strokeLinejoin="miter" /> : <polyline key={`${key}${i}`} points={points} style={style} />;
    });
  };
  const gapOf = (s: DrawnSignal) => {
    const { gap } = skin.signal({ type: s.type, aspect: s.aspect, end: s.end });
    if (!gap) return null;
    const [tx, ty] = unit(s.toward);
    const a: Cell = [s.symbol[0] + tx * gap[0], s.symbol[1] + ty * gap[0]];
    const b: Cell = [s.symbol[0] + tx * gap[1], s.symbol[1] + ty * gap[1]];
    return <polyline key={`g${s.name}`} points={line([a, b])} style={{ stroke: skin.ground, strokeWidth: (skin.width + 0.14) * u, fill: "none" }} />;
  };
  return (
    <div className="stv-ram" style={{ background: skin.ground }}>
      <svg
        className={`stv-panel skal-${skin.id}`}
        viewBox={`${round(box.x)} ${round(box.y)} ${round(box.width)} ${round(box.height)}`}
        role="group"
        aria-label={say("panel")}
        preserveAspectRatio="xMidYMid meet"
        style={{ fontFamily: skin.font, maxHeight: height }}
      >
        <rect x={box.x} y={box.y} width={box.width} height={box.height} fill={skin.ground} />
        {(panel.platforms ?? []).map(([x1, y1, x2, y2], i) => (
          <rect key={`p${i}`} x={x1 * dx} y={y1 * dy} width={(x2 - x1) * dx} height={(y2 - y1) * dy} fill={skin.platform} />
        ))}
        <g className="spar" fill="none" strokeLinejoin="round" strokeWidth={skin.width * u}>
          {drawn.lines.map((l) => (
            <polyline
              key={l.piece}
              data-piece={l.piece}
              data-state={l.state}
              points={line(cut(l.cells, l.cut.start ? skin.gap : 0, l.cut.end ? skin.gap : 0))}
              stroke={skin.tracks[l.state]}
            />
          ))}
        </g>
        <g className="skydd" fill="none" stroke={skin.protection} strokeWidth={skin.width * u}>
          {drawn.switches
            .filter((s) => s.protection && s.lies && s.trunk)
            .flatMap((s) => [
              <polyline key={`${s.number}l`} data-protection={s.number} points={line(fromKnot(s.lies ?? [], s.cell, 0.9))} />,
              <polyline key={`${s.number}t`} points={line(fromKnot(s.trunk ?? [], s.cell, 0.3))} />,
            ])}
        </g>
        <g className="luckor">{drawn.signals.map(gapOf)}</g>
        <g className="signaler">
          {drawn.signals.map((s) => (
            <g key={s.name} data-signal={s.name} data-aspect={s.aspect} data-end={s.end ? "ja" : undefined} opacity={s.planned ? 0.4 : 1}>
              {placed(skin.signal({ type: s.type, aspect: s.aspect, end: s.end }).shapes, s.symbol, s.toward, s.name)}
            </g>
          ))}
        </g>
        <g className="stoppbockar">
          {drawn.buffers.map((b) => (
            <g key={b.id} data-buffer={b.id}>
              {placed(skin.buffer(b.end), b.cell, b.toward, b.id)}
            </g>
          ))}
        </g>
        <g className="texter" fontSize={font} fontWeight={600} textAnchor="middle" style={{ paintOrder: "stroke" }} stroke={skin.ground} strokeWidth={0.12 * u}>
          {drawn.switches.map((s) => (
            <text key={s.number} x={s.label[0] * dx} y={s.label[1] * dy + font * 0.35} fill={skin.switchNumber} opacity={s.laid ? 1 : 0.55} fontSize={font * 0.85}>
              {s.number}
            </text>
          ))}
          {drawn.labels.map((l) => (
            <text key={`${l.kind}${l.text}`} x={l.cell[0] * dx} y={l.cell[1] * dy + font * 0.35} textAnchor={l.anchor} fill={l.end ? skin.endLabel : skin.label}>
              {l.text}
            </text>
          ))}
          {drawn.names
            .filter((n) => !n.hidden)
            .map((n) => (
              <text key={n.name} data-track-name={n.name} x={n.cell[0] * dx} y={n.cell[1] * dy} textAnchor="end" fill={skin.trackName}>
                {n.name}
              </text>
            ))}
          {drawn.signals.map((s) => (
            <text key={s.name} x={s.label[0] * dx} y={s.label[1] * dy + font * 0.35} fill={skin.signalId} opacity={s.planned ? 0.4 : 1} fontWeight={700}>
              {s.name}
            </text>
          ))}
        </g>
        <g className="tagnummer" fontSize={skin.numbers.size * u} fontWeight={700} textAnchor="middle">
          {drawn.numbers.map((n) => {
            const shown = n.number ? skin.numberText(n.number) : "-----";
            const w = (shown.length * 0.62 + 0.5) * skin.numbers.size * u;
            const h = skin.numbers.size * u * 1.3;
            // Beside an exit's name: past the name's characters, then half the number's width.
            const aside = n.after * 0.6 * skin.text * u + 0.4 * u + w / 2;
            const [x0, y] = px(n.at);
            const x = n.anchor === "start" ? x0 + aside : n.anchor === "end" ? x0 - aside : x0;
            return (
              <g key={n.key} data-number={n.number ?? ""} data-colour={n.colour} style={{ transform: `translate(${round(x)}px, ${round(y)}px)` }}>
                {n.estimated ? <rect x={-w / 2} y={-h / 2} width={w} height={h} fill={skin.ground} stroke={skin.numbers.frame} strokeWidth={0.05 * u} /> : null}
                <text y={skin.numbers.size * u * 0.36} fill={n.colour === "red" ? skin.numbers.red : skin.numbers.green}>
                  {shown}
                  <title>{n.estimated ? `${shown} · ${say("estimated")}` : shown}</title>
                </text>
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
          {drawn.switches.map((s) => {
            const [x, y] = px(s.cell);
            const part = s.parts[0];
            const state = [s.position ?? "?", s.routes.length ? say("locked", { routes: s.routes.join(", ") }) : null, s.protection ? say("protection") : null, s.laid ? null : say("notLaid")].filter(Boolean).join(" · ");
            return (
              <g
                key={s.number}
                role="button"
                tabIndex={0}
                aria-label={say("switchLabel", { name: s.number })}
                data-position={s.position ?? ""}
                onClick={() => part && onSwitch?.(part)}
                onKeyDown={press(() => part && onSwitch?.(part))}
                style={{ cursor: "pointer" }}
              >
                <title>{`${say("switchLabel", { name: s.number })} · ${state}`}</title>
                <circle cx={x} cy={y} r={0.75 * u} fill="transparent" />
              </g>
            );
          })}
          {[...drawn.signals.map((s) => ({ name: s.name, at: s.symbol, label: say("signal", { name: s.name }) })), ...drawn.points.map((p) => ({ name: p.name, at: p.cell, label: say("point", { name: p.name }) }))].map((p) => {
            const [x, y] = px(p.at);
            return (
              <g key={`k${p.name}`} role="button" tabIndex={0} aria-label={p.label} onClick={() => onPoint?.(p.name)} onKeyDown={press(() => onPoint?.(p.name))} style={{ cursor: "pointer" }}>
                <circle cx={x} cy={y} r={0.85 * u} fill="transparent" />
              </g>
            );
          })}
        </g>
        <g className="ringar" fill="none" pointerEvents="none">
          {lit.map((t) => {
            const at = drawn.signals.find((s) => s.name === t.end)?.symbol ?? drawn.points.find((p) => p.name === t.end)?.cell;
            if (!at) return null;
            const [x, y] = px(at);
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
