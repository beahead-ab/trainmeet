// Ritningsytan (#89 del b): the module in mm with its tracks, switches, gable measures and what
// to check, and the tools' drags. Everything is drawn in the module's own coordinates (x from
// gable A, y away from Kant 1, mm); a curve is turned so that its string lies level, as in the
// module page. The canvas only proposes operations; CAD applies them and draws the result.
import { useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import type { CheckItem, DrawingView, EditOp, SwitchInfo } from "./api";
import { f, kantOne, outline, pathOf, poly, turnDegrees, turner } from "./Drawing";
import { drawnSwitchRadius, markerWord, op, segsOf, snap, type Snap, type Tool } from "./editor";
import { PhotoImage } from "./Foto";
import { arcThrough, furthestFromChord, gableLine, mmText, onGable, projectPath, fromA, type Point, type Seg } from "./geometry";

export type Layers = { tracks: boolean; numbers: boolean; gables: boolean; photo: boolean };
export type Selection = { kind: "switch" | "piece" | "node" | "label"; id: string } | null;

type Props = {
  view: DrawingView;
  tool: Tool;
  layers: Layers;
  selected: Selection;
  /** The open items in Att kolla, numbered as the list. */
  checks: CheckItem[];
  zoom?: number;
  onOps?: (ops: EditOp[]) => void;
  onSelect?: (selection: Selection) => void;
  onText?: (target: string | null, at: Point) => void;
  onLock?: (piece: string | null) => void;
  onZoom?: (zoom: number) => void;
  /** Fotot under: the measuring image under the drawing (part c1). */
  onLayers?: (layers: Layers) => void;
  /** For the tests: the pointer position shown before any move. */
  cursor?: Point | null;
};

type Drag =
  | { kind: "draw"; tool: "line" | "arc"; from: Snap; to: Point; path: Point[]; free: boolean }
  | { kind: "measure"; from: Point; to: Point }
  | { kind: "node"; id: string; from: Point; to: Point }
  | { kind: "piece"; id: string; from: Point; to: Point }
  | { kind: "label"; id: string; from: Point; to: Point }
  | { kind: "switch"; info: SwitchInfo; to: Point; fromA: number };

const PICK = 12;
/** How near, in screen pixels, a pointer must be to pick or snap to something. */

function throughSegs(view: DrawingView, info: SwitchInfo): Seg[] {
  const sw = (view.graph.switches ?? []).find((s) => s.id === info.id);
  if (!sw) return [];
  return [...(sw.trunk ? segsOf(view.graph, sw.trunk) : []), ...(sw.straight ? segsOf(view.graph, sw.straight) : [])];
}

export function Canvas({ view, tool, layers, selected, checks, zoom = 1, onOps, onSelect, onText, onLock, onZoom, onLayers, cursor = null }: Props) {
  const group = useRef<SVGGElement>(null);
  const [drag, setDrag] = useState<Drag | null>(null);
  const [pointer, setPointer] = useState<Point | null>(cursor);
  const [measured, setMeasured] = useState<{ from: Point; to: Point } | null>(null);
  const shape = view.shape;
  const graph = view.graph;
  const track1 = view.gables[0]?.tracks?.[0] ?? 0;
  const turn = turner(shape);
  const board = outline(shape, track1);
  const turned = board.map(turn);
  const xs = turned.map((p) => p[0]);
  const ys = turned.map((p) => p[1]);
  const minX = Math.min(...xs);
  const minY = Math.min(...ys);
  const w = Math.max(...xs) - minX;
  const h = Math.max(...ys) - minY;
  const unit = Math.max(w, h) / 100;
  const pad = Math.max(w, h) * 0.13;
  const fullW = w + 2 * pad;
  const fullH = h + 2.2 * pad;
  const viewW = fullW / zoom;
  const viewH = fullH / zoom;
  const cx = minX + w / 2;
  const cy = minY + h / 2;
  const viewBox = `${f(cx - viewW / 2)} ${f(cy - viewH / 2 - pad * 0.1)} ${f(viewW)} ${f(viewH)}`;
  const infos = view.switches ?? [];

  const toModule = (event: ReactPointerEvent): { at: Point; scale: number } | null => {
    const g = group.current;
    const matrix = g?.getScreenCTM?.();
    if (!g || !matrix) return null;
    const point = new DOMPoint(event.clientX, event.clientY).matrixTransform(matrix.inverse());
    return { at: [point.x, point.y], scale: 1 / Math.hypot(matrix.a, matrix.b) };
  };

  const pickSwitch = (p: Point, tolerance: number): SwitchInfo | null => {
    let best: SwitchInfo | null = null;
    let distance = tolerance * 1.6;
    for (const info of infos) {
      const d = Math.hypot(info.at[0] - p[0], info.at[1] - p[1]);
      if (d <= distance) {
        best = info;
        distance = d;
      }
    }
    return best;
  };
  const pickPiece = (p: Point, tolerance: number): string | null => {
    let best: string | null = null;
    let distance = tolerance;
    for (const piece of graph.pieces ?? []) {
      const d = projectPath(segsOf(graph, piece.id), p).distance;
      if (d <= distance) {
        best = piece.id;
        distance = d;
      }
    }
    return best;
  };
  const pickNode = (p: Point, tolerance: number): string | null => {
    for (const node of graph.nodes ?? []) {
      if (node.type === "switch") continue;
      if (Math.hypot(node.at[0] - p[0], node.at[1] - p[1]) <= tolerance) return node.id;
    }
    return null;
  };
  const pickLabel = (p: Point, tolerance: number): string | null => {
    for (const label of graph.labels ?? []) {
      if (Math.hypot(label.at[0] - p[0], label.at[1] - p[1]) <= tolerance * 2.5) return label.id;
    }
    return null;
  };

  const down = (event: ReactPointerEvent<SVGSVGElement>) => {
    if (event.button !== 0) return;
    const found = toModule(event);
    if (!found) return;
    const { at, scale } = found;
    const tolerance = PICK * scale;
    (event.currentTarget as Element).setPointerCapture?.(event.pointerId);
    if (tool === "line" || tool === "arc") {
      const from = snap(view, at, tolerance);
      setDrag({ kind: "draw", tool, from, to: from.at, path: [from.at], free: tool === "arc" && event.shiftKey });
    } else if (tool === "measure") {
      setDrag({ kind: "measure", from: at, to: at });
      setMeasured(null);
    } else if (tool === "switch") {
      const info = pickSwitch(at, tolerance);
      if (info) {
        onSelect?.({ kind: "switch", id: info.id });
        setDrag({ kind: "switch", info, to: info.at, fromA: info.from_a });
      }
    } else if (tool === "text") {
      const sw = pickSwitch(at, tolerance);
      const label = pickLabel(at, tolerance);
      const piece = pickPiece(at, tolerance);
      onText?.(sw?.id ?? label ?? piece ?? null, at);
    } else if (tool === "lock") {
      onLock?.(pickPiece(at, tolerance));
    } else {
      const sw = pickSwitch(at, tolerance);
      if (sw) {
        onSelect?.({ kind: "switch", id: sw.id });
        return;
      }
      const label = pickLabel(at, tolerance);
      if (label) {
        onSelect?.({ kind: "label", id: label });
        setDrag({ kind: "label", id: label, from: at, to: at });
        return;
      }
      const node = pickNode(at, tolerance);
      if (node) {
        onSelect?.({ kind: "node", id: node });
        setDrag({ kind: "node", id: node, from: at, to: at });
        return;
      }
      const piece = pickPiece(at, tolerance);
      onSelect?.(piece ? { kind: "piece", id: piece } : null);
      if (piece) setDrag({ kind: "piece", id: piece, from: at, to: at });
    }
  };

  const move = (event: ReactPointerEvent<SVGSVGElement>) => {
    const found = toModule(event);
    if (!found) return;
    const { at, scale } = found;
    setPointer(at);
    if (!drag) return;
    if (drag.kind === "draw") {
      const to = drag.free ? at : snap(view, at, PICK * scale, drag.from.node).at;
      setDrag({ ...drag, to, path: [...drag.path, at] });
    } else if (drag.kind === "switch") {
      const onTrack = projectPath(throughSegs(view, drag.info), at).at;
      setDrag({ ...drag, to: onTrack, fromA: fromA(shape, track1, onTrack) });
    } else {
      setDrag({ ...drag, to: at });
    }
  };

  const up = (event: ReactPointerEvent<SVGSVGElement>) => {
    const found = toModule(event);
    const current = drag;
    setDrag(null);
    if (!current || !found) return;
    const tolerance = PICK * found.scale;
    if (current.kind === "draw") {
      const end = snap(view, found.at, tolerance, current.from.node);
      const length = Math.hypot(end.at[0] - current.from.at[0], end.at[1] - current.from.at[1]);
      if (length < tolerance) return;
      if (current.from.kind === "track" && current.from.piece && !current.free) {
        const radius = current.tool === "arc" ? Math.max(view.limits.switch_min_radius, arcRadius(current.from.at, current.path, end.at)) : drawnSwitchRadius(view);
        onOps?.([op.switchTo(current.from.piece, fromA(shape, track1, current.from.at), Math.round(radius), end.at, end.node)]);
      } else if (current.tool === "arc" && current.free) {
        const path = thin([current.from.at, ...current.path.slice(1, -1), end.kind === "free" ? found.at : end.at], tolerance / 3);
        onOps?.([op.polyline(path, current.from.node, end.kind === "track" ? null : end.node)]);
      } else if (current.tool === "arc") {
        const middle = furthestFromChord(current.path);
        if (middle.distance < tolerance / 2) onOps?.([op.line(current.from.at, end.at, current.from.node, end.node)]);
        else onOps?.([op.arc(current.from.at, middle.at, end.at, current.from.node, end.node)]);
      } else {
        onOps?.([op.line(current.from.at, end.at, current.from.node, end.node)]);
      }
    } else if (current.kind === "measure") {
      setMeasured({ from: current.from, to: current.to });
    } else if (current.kind === "switch") {
      if (Math.abs(current.fromA - current.info.from_a) >= 0.5) onOps?.([op.moveSwitch(current.info.id, current.fromA)]);
    } else {
      const by: Point = [current.to[0] - current.from[0], current.to[1] - current.from[1]];
      if (Math.hypot(by[0], by[1]) >= tolerance / 3) onOps?.([op.move(current.id, by)]);
    }
  };

  const selectedPieces = new Set<string>();
  if (selected?.kind === "piece") selectedPieces.add(selected.id);
  if (selected?.kind === "switch") {
    const sw = (graph.switches ?? []).find((s) => s.id === selected.id);
    if (sw?.diverging) selectedPieces.add(sw.diverging);
  }
  const gableA = gableLine(shape, track1, "A");
  const gableB = gableLine(shape, track1, "B");
  const corner = (p: Point) => turn(p);
  const preview = drag?.kind === "draw" ? previewOf(drag) : null;
  const dragShift: Point | null = drag && "from" in drag && (drag.kind === "node" || drag.kind === "piece" || drag.kind === "label") ? [drag.to[0] - drag.from[0], drag.to[1] - drag.from[1]] : null;
  const showMeasure = drag?.kind === "measure" ? { from: drag.from, to: drag.to } : measured;
  const length = shape.kind === "curve" ? (shape.radius * shape.angle * Math.PI) / 180 : shape.length;
  const lengthY = Math.max(...ys) + pad * 0.55;
  const under = Boolean(layers.photo && view.photo);
  return (
    <div className="cad-duk">
      <div className="cad-duk-topp">
        <div className="cad-vaxel" role="tablist" aria-label="Lager under ritningen">
          <button type="button" role="tab" aria-selected={!under} aria-pressed={!under} onClick={() => onLayers?.({ ...layers, photo: false })}>
            Ritning
          </button>
          {view.photo ? (
            <button type="button" role="tab" aria-selected={under} aria-pressed={under} onClick={() => onLayers?.({ ...layers, photo: true })}>
              Fotot under
            </button>
          ) : (
            <button type="button" role="tab" aria-selected="false" disabled title="Fota modulen under Foto på modulens sida">
              Fotot under <span className="cad-kommer-text">inget foto</span>
            </button>
          )}
          <button type="button" role="tab" aria-selected="false" disabled title="Kommer med landskapet (del d)">
            Landskap <span className="cad-kommer-text">kommer</span>
          </button>
        </div>
        <span className="cad-fyll" />
        <span className="tm-mono cad-markor" aria-live="off">
          {pointer ? `x ${mmText(pointer[0])} · y ${mmText(pointer[1])} mm` : "x – · y – mm"}
        </span>
        <span className="cad-zoom">
          <button type="button" className="tm-knapp liten" aria-label="Zooma ut" onClick={() => onZoom?.(Math.max(1, zoom / 1.5))} disabled={zoom <= 1}>
            −
          </button>
          <span className="tm-mono">{Math.round(zoom * 100)} %</span>
          <button type="button" className="tm-knapp liten" aria-label="Zooma in" onClick={() => onZoom?.(Math.min(6, zoom * 1.5))}>
            +
          </button>
        </span>
      </div>
      <svg
        className={`cad-ritning cad-duk-yta verktyg-${tool}`}
        viewBox={viewBox}
        role="application"
        aria-label="Ritningen i millimeter"
        preserveAspectRatio="xMidYMid meet"
        onPointerDown={down}
        onPointerMove={move}
        onPointerUp={up}
        onPointerLeave={() => setPointer(null)}
      >
        <g ref={group} transform={turnDegrees(shape) ? `rotate(${f(turnDegrees(shape))})` : undefined}>
          {under && view.photo ? <PhotoImage layer={view.photo} /> : null}
          <path className={under ? "cad-skiva genomskinlig" : "cad-skiva"} d={poly(board, (p) => p, true)} strokeWidth={unit * 0.25} />
          <path className="cad-kant1" d={poly(kantOne(shape, track1), (p) => p, false)} strokeWidth={unit * 0.9} />
          {layers.tracks
            ? (["cad-ballast", "cad-spar"] as const).map((layer) => (
                // All the ballast first and the tracks over it, so that no piece covers the next.
                <g key={layer}>
                  {(graph.pieces ?? []).map((piece) => {
                    const shift = dragShift && drag?.kind === "piece" && drag.id === piece.id ? dragShift : null;
                    const proposal = piece.origin?.source === "photo" && piece.origin.certainty !== "confirmed";
                    return (
                      <g key={piece.id} data-piece={layer === "cad-spar" ? piece.id : undefined} className={selectedPieces.has(piece.id) ? "cad-vald" : undefined} transform={shift ? `translate(${f(shift[0])} ${f(shift[1])})` : undefined}>
                        {segsOf(graph, piece.id).map((seg, i) => (
                          <path
                            key={i}
                            className={layer === "cad-spar" && proposal ? "cad-spar cad-forslag" : layer}
                            d={pathOf(seg, (p) => p)}
                            strokeWidth={unit * (layer === "cad-ballast" ? 2.2 : 0.5)}
                          />
                        ))}
                      </g>
                    );
                  })}
                </g>
              ))
            : null}
          {layers.tracks
            ? (graph.nodes ?? [])
                .filter((n) => n.type === "buffer_stop")
                .map((n) => <circle key={n.id} className="cad-stoppbock" cx={n.at[0]} cy={n.at[1]} r={unit * 0.9} />)
            : null}
          {layers.gables ? (
            <g className="cad-gavelmatt" fontSize={unit * 2.4}>
              {[
                { line: gableA, tracks: view.gables[0]?.tracks ?? [], out: -1 },
                { line: gableB, tracks: view.gables[1]?.tracks ?? [], out: 1 },
              ].map(({ line, tracks, out }, g) =>
                tracks.map((offset, i) => {
                  const at = onGable(line, offset);
                  const outward: Point = [-line.inward[0], -line.inward[1]];
                  const tick: Point = [at[0] + outward[0] * unit * 5, at[1] + outward[1] * unit * 5];
                  const text: Point = [at[0] + outward[0] * unit * 6.2, at[1] + outward[1] * unit * 6.2];
                  return (
                    <g key={`${g}-${i}`}>
                      <path className="cad-mattlinje" d={`M${f(at[0])} ${f(at[1])}L${f(tick[0])} ${f(tick[1])}`} strokeWidth={unit * 0.25} />
                      <text x={text[0]} y={text[1] + unit * 0.9} textAnchor={out < 0 ? "end" : "start"} className="cad-matt">
                        {mmText(offset)}
                      </text>
                    </g>
                  );
                }),
              )}
              {shape.kind !== "curve" ? (
                <g>
                  <path className="cad-mattlinje" d={`M0 ${f(lengthY)}H${f(shape.length)}M0 ${f(lengthY - unit * 1.4)}V${f(lengthY + unit * 1.4)}M${f(shape.length)} ${f(lengthY - unit * 1.4)}V${f(lengthY + unit * 1.4)}`} strokeWidth={unit * 0.25} />
                  <text x={shape.length / 2} y={lengthY - unit * 0.9} textAnchor="middle" className="cad-matt">
                    {mmText(length)}
                  </text>
                </g>
              ) : null}
            </g>
          ) : null}
          {(graph.labels ?? []).map((label) => {
            const shift = drag?.kind === "label" && drag.id === label.id && dragShift ? dragShift : [0, 0];
            return (
              <text key={label.id} x={label.at[0] + shift[0]!} y={label.at[1] + shift[1]!} fontSize={unit * 2.4} className={selected?.kind === "label" && selected.id === label.id ? "cad-etikett vald" : "cad-etikett"}>
                {label.text}
              </text>
            );
          })}
          {layers.tracks
            ? infos.map((info) => {
                const at = drag?.kind === "switch" && drag.info.id === info.id ? drag.to : info.at;
                const chosen = selected?.kind === "switch" && selected.id === info.id;
                return (
                  <g key={info.id} className={`cad-vaxelmarkor${chosen ? " vald" : ""}${info.origin?.source === "photo" && info.origin.certainty !== "confirmed" ? " forslag" : ""}`} data-switch={info.id}>
                    <circle cx={at[0]} cy={at[1]} r={unit * 1.9} strokeWidth={unit * 0.35} />
                    {layers.numbers ? (
                      <text x={at[0]} y={at[1] + unit * 0.75} textAnchor="middle" fontSize={unit * 2}>
                        {info.number}
                      </text>
                    ) : null}
                  </g>
                );
              })
            : null}
          {checks.map((item, i) => {
            // Markers at the same place get their words one under the other.
            const before = checks.slice(0, i).filter((other) => Math.hypot(other.at[0] - item.at[0], other.at[1] - item.at[1]) < unit * 4).length;
            return (
            <g key={item.key} className={`cad-kollmarkor${item.assumed ? " antagen" : ""}`} data-check={item.key}>
              {item.kind === "short_rail" ? (
                <rect x={item.at[0] - unit * 3} y={item.at[1] - unit * 3} width={unit * 6} height={unit * 6} rx={unit * 0.6} strokeWidth={unit * 0.3} strokeDasharray={`${unit} ${unit * 0.6}`} />
              ) : (
                <circle cx={item.at[0]} cy={item.at[1]} r={unit * 2.6} strokeWidth={unit * 0.3} strokeDasharray={`${unit} ${unit * 0.6}`} />
              )}
              <text x={item.at[0] + unit * 3.6} y={item.at[1] + unit * (4.6 + 2.8 * before)} fontSize={unit * 2.2}>
                {`${i + 1} · ${markerWord(item.kind)}`}
              </text>
            </g>
            );
          })}
          {preview ? <path className="cad-forhand" d={preview} strokeWidth={unit * 0.5} /> : null}
          {drag?.kind === "draw" && drag.from.kind !== "free" ? <circle className="cad-snapp" cx={drag.from.at[0]} cy={drag.from.at[1]} r={unit * 1.2} /> : null}
          {showMeasure ? (
            <g className="cad-mat">
              <path d={`M${f(showMeasure.from[0])} ${f(showMeasure.from[1])}L${f(showMeasure.to[0])} ${f(showMeasure.to[1])}`} strokeWidth={unit * 0.3} />
              <text x={(showMeasure.from[0] + showMeasure.to[0]) / 2} y={(showMeasure.from[1] + showMeasure.to[1]) / 2 - unit} fontSize={unit * 2.4} textAnchor="middle">
                {mmText(Math.hypot(showMeasure.to[0] - showMeasure.from[0], showMeasure.to[1] - showMeasure.from[1]))} mm
              </text>
            </g>
          ) : null}
        </g>
        <g className="cad-texter" fontSize={unit * 2.6}>
          <text x={corner([0, 0])[0]} y={minY - pad * 0.62} textAnchor="start" className="cad-gavel-text">
            GAVEL A
          </text>
          <text x={Math.max(...xs)} y={minY - pad * 0.62} textAnchor="end" className="cad-gavel-text">
            GAVEL B
          </text>
          <text x={corner([0, 0])[0] + unit * 8} y={minY - pad * 0.18} textAnchor="start" className="cad-kant1-text">
            KANT 1
          </text>
        </g>
      </svg>
      <p className="cad-duk-fot">
        <span>Spår totalt {(view.stats.track_length / 1000).toLocaleString("sv-SE", { maximumFractionDigits: 1 })} m</span>
        <span>{view.stats.switches === 1 ? "1 växel" : `${view.stats.switches} växlar`}</span>
        {view.drawing.source === "photo" && view.stats.deviation ? (
          <span>
            Avviker från fotot: median {view.stats.deviation.median.toLocaleString("sv-SE")} mm, högst {view.stats.deviation.max.toLocaleString("sv-SE")} mm
          </span>
        ) : null}
      </p>
    </div>
  );
}

function arcRadius(start: Point, path: Point[], end: Point): number {
  const middle = furthestFromChord([start, ...path, end]);
  const arc = arcThrough(start, middle.at, end);
  return arc ? arc.radius : 2000;
}

/** The hand-drawn path with points no closer than step mm. */
function thin(path: Point[], step: number): Point[] {
  const found: Point[] = [];
  for (const p of path) {
    const last = found[found.length - 1];
    if (!last || Math.hypot(p[0] - last[0], p[1] - last[1]) >= step) found.push(p);
  }
  const end = path[path.length - 1];
  if (end && found[found.length - 1] !== end) found.push(end);
  return found;
}

function previewOf(drag: Extract<Drag, { kind: "draw" }>): string {
  const a = drag.from.at;
  const b = drag.to;
  if (drag.free) return drag.path.map((p, i) => `${i ? "L" : "M"}${f(p[0])} ${f(p[1])}`).join("");
  if (drag.tool === "arc") {
    const middle = furthestFromChord([a, ...drag.path, b]);
    const arc = arcThrough(a, middle.at, b);
    if (arc && middle.distance > 1) return pathOf(arc, (p) => p);
  }
  return `M${f(a[0])} ${f(a[1])}L${f(b[0])} ${f(b[1])}`;
}
