// Landskapet (#89 del d1, CAD-04, CAD-33): the module's surfaces from the measuring image, with
// Måla, Sudda and Fyll, as the view Landskap. CAD makes the surfaces on its own server (colour
// clustering until TrainMeet's own model is trained, CAD8) and keeps them with the module version;
// the painting is a change set CAD replays and draws, as in Ritningen. Everything the photo gave is
// a proposal (orange) until it is approved (CAD-17). The tracks and the ballast under them are
// drawn from the track plan, never from the photo.
import { useCallback, useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { ApiError, type Module } from "./api";
import { f, kantOne, outline, pathOf, poly, segsOf, turnDegrees } from "./Drawing";
import { PhotoImage } from "./Foto";
import type { Point } from "./geometry";
import { landscapeApi, type Landscape, type LandscapeApi, type LandscapeOp, type Surface, type SurfaceTotal } from "./landskapapi";
import "./landskap.css";

export type Tool = "paint" | "erase" | "fill";

export const TOOLS: [Tool, string, string][] = [
  ["paint", "Måla", "Måla en yta med penseln"],
  ["erase", "Sudda", "Sudda bort en yta, till exempel en skugga som blivit en buske"],
  ["fill", "Fyll", "Fyll en sammanhängande yta"],
];
export const BRUSHES = [10, 20, 40, 80];
const NO_SURFACES: NonNullable<Landscape["surfaces"]> = [];

/** A stroke's points, at most one per step mm, rounded to a tenth of a mm. */
export function thin(points: Point[], step: number): Point[] {
  const found: Point[] = [];
  for (const p of points) {
    const last = found[found.length - 1];
    if (!last || Math.hypot(p[0] - last[0], p[1] - last[1]) >= step) found.push([Math.round(p[0] * 10) / 10, Math.round(p[1] * 10) / 10]);
  }
  const end = points[points.length - 1];
  const last = found[found.length - 1];
  if (end && last && (end[0] !== last[0] || end[1] !== last[1]) && found.length > 1) found.push(end);
  return found.slice(0, 2000);
}

/** The operation a stroke or a click makes. */
export function strokeOp(tool: Tool, surface: Surface, radius: number, points: Point[]): LandscapeOp | null {
  const first = points[0];
  if (!first) return null;
  if (tool === "fill") return { op: "fill", surface, at: first };
  const kept = thin(points, Math.max(2, radius / 3));
  return tool === "paint" ? { op: "paint", surface, radius, points: kept } : { op: "erase", radius, points: kept };
}

export function areaText(mm2: number): string {
  const m2 = mm2 / 1e6;
  return `${m2 >= 0.1 ? m2.toFixed(2).replace(".", ",") : m2.toFixed(3).replace(".", ",")} m²`;
}

export function shareText(share: number): string {
  return `${Math.round(share * 100)} %`;
}

function rings(points: [number, number][][]): string {
  return points.map((ring) => ring.map((p, i) => `${i ? "L" : "M"}${f(p[0])} ${f(p[1])}`).join("") + "Z").join("");
}

function editsText(count: number): string {
  return count === 1 ? "1 ändring som inte är sparad" : `${count} ändringar som inte är sparade`;
}

type CanvasProps = {
  module: Module;
  landscape: Landscape;
  tool: Tool;
  surface: Surface;
  radius: number;
  photoUnder: boolean;
  editable: boolean;
  onOp?: (op: LandscapeOp) => void;
};

/** The module from above with its surfaces, the track bed and the tracks; the brush draws on it. */
export function LandskapCanvas({ module, landscape, tool, surface, radius, photoUnder, editable, onOp }: CanvasProps) {
  const group = useRef<SVGGElement>(null);
  const [stroke, setStroke] = useState<Point[] | null>(null);
  const [pointer, setPointer] = useState<Point | null>(null);
  const shape = module.shape;
  const track1 = module.gables[0]?.tracks?.[0] ?? 0;
  const board = outline(shape, track1);
  const turn = (p: Point): Point => p;
  const xs = board.map((p) => p[0]);
  const ys = board.map((p) => p[1]);
  const minX = Math.min(...xs);
  const minY = Math.min(...ys);
  const w = Math.max(...xs) - minX;
  const h = Math.max(...ys) - minY;
  const pad = Math.max(w, h) * 0.04;
  const degrees = turnDegrees(shape);
  // A curve is turned so that its string lies level; its box is then the turned board's.
  const turned = board.map(([x, y]) => {
    const a = (degrees * Math.PI) / 180;
    return [x * Math.cos(a) - y * Math.sin(a), x * Math.sin(a) + y * Math.cos(a)] as Point;
  });
  const tx = turned.map((p) => p[0]);
  const ty = turned.map((p) => p[1]);
  const view = `${f(Math.min(...tx) - pad)} ${f(Math.min(...ty) - pad)} ${f(Math.max(...tx) - Math.min(...tx) + 2 * pad)} ${f(Math.max(...ty) - Math.min(...ty) + 2 * pad)}`;
  const unit = Math.max(w, h) / 100;
  const colours = new Map((landscape.surfaces ?? NO_SURFACES).map((s) => [s.surface, s.colour]));
  const ballast = colours.get("ballast") ?? "#a8a39a";
  const cell = landscape.grid?.cell ?? 2;
  const proposal = landscape.status === "proposal";

  const toModule = (event: ReactPointerEvent): Point | null => {
    const matrix = group.current?.getScreenCTM?.();
    if (!matrix) return null;
    const p = new DOMPoint(event.clientX, event.clientY).matrixTransform(matrix.inverse());
    return [p.x, p.y];
  };
  const down = (event: ReactPointerEvent<SVGSVGElement>) => {
    if (!editable || event.button !== 0) return;
    const at = toModule(event);
    if (!at) return;
    if (tool === "fill") {
      const op = strokeOp(tool, surface, radius, [at]);
      if (op) onOp?.(op);
      return;
    }
    (event.currentTarget as Element).setPointerCapture?.(event.pointerId);
    setStroke([at]);
  };
  const move = (event: ReactPointerEvent<SVGSVGElement>) => {
    const at = toModule(event);
    if (!at) return;
    setPointer(at);
    if (stroke) setStroke([...stroke, at]);
  };
  const up = () => {
    const done = stroke;
    setStroke(null);
    if (!done) return;
    const op = strokeOp(tool, surface, radius, done);
    if (op) onOp?.(op);
  };
  const brush = tool === "erase" ? "#ffffff" : (colours.get(surface) ?? "#888888");
  return (
    <svg
      className={`cad-landskap-yta${editable ? ` verktyg-${tool}` : ""}`}
      viewBox={view}
      role="img"
      aria-label={`Landskapet på ${module.name}`}
      preserveAspectRatio="xMidYMid meet"
      onPointerDown={down}
      onPointerMove={move}
      onPointerUp={up}
      onPointerLeave={() => setPointer(null)}
    >
      <g ref={group} transform={degrees ? `rotate(${f(degrees)})` : undefined}>
        <path className="cad-skiva" d={poly(board, turn, true)} strokeWidth={unit * 0.25} />
        {photoUnder && landscape.photo ? <PhotoImage layer={landscape.photo} /> : null}
        <g className="cad-ytor" opacity={photoUnder ? 0.55 : 1}>
          {(landscape.areas ?? []).map((area, i) => {
            const colour = colours.get(area.surface) ?? "#999999";
            return (
              <path
                key={i}
                className={proposal && !area.painted ? "cad-yta forslag" : "cad-yta"}
                data-yta={area.surface}
                d={rings([area.outline, ...(area.holes ?? [])])}
                fill={colour}
                stroke={colour}
                strokeWidth={cell}
                fillRule="evenodd"
              />
            );
          })}
          {(landscape.track_bed ?? []).length ? <path className="cad-sparbadd" d={rings(landscape.track_bed ?? [])} fill={ballast} fillRule="evenodd" /> : null}
          {proposal
            ? (landscape.areas ?? [])
                .filter((a) => !a.painted)
                .map((area, i) => <path key={`o${i}`} className="cad-forslagskant" d={rings([area.outline])} strokeWidth={unit * 0.3} strokeDasharray={`${unit} ${unit * 0.7}`} />)
            : null}
        </g>
        <path className="cad-kant1" d={poly(kantOne(shape, track1), turn, false)} strokeWidth={unit * 0.9} />
        {segsOf(module.graph).map((seg, i) => (
          <path key={`s${i}`} className="cad-spar" d={pathOf(seg, turn)} strokeWidth={unit * 0.55} />
        ))}
        {stroke && stroke.length ? (
          <path
            className="cad-penseldrag"
            d={stroke.map((p, i) => `${i ? "L" : "M"}${f(p[0])} ${f(p[1])}`).join("")}
            stroke={brush}
            strokeWidth={radius * 2}
            strokeOpacity={0.7}
          />
        ) : null}
        {editable && pointer && tool !== "fill" ? <circle className="cad-pensel" cx={pointer[0]} cy={pointer[1]} r={radius} strokeWidth={unit * 0.2} /> : null}
      </g>
    </svg>
  );
}

/** A surface's colour as a small square: an SVG fill, which the content security policy allows. */
export function Swatch({ colour }: { colour?: string | undefined }) {
  return (
    <svg className="cad-farg" viewBox="0 0 10 10" aria-hidden="true">
      <rect width="10" height="10" rx="2" fill={colour ?? "#999999"} />
    </svg>
  );
}

function Legend({ totals, landscape }: { totals: SurfaceTotal[]; landscape: Landscape }) {
  const names = new Map((landscape.surfaces ?? NO_SURFACES).map((s) => [s.surface, s]));
  return (
    <div className="cad-kort cad-ytlista">
      <h2 className="cad-overrubrik">Ytor på modulen</h2>
      {totals.length ? (
        <ul>
          {totals.map((t) => (
            <li key={t.surface}>
              <Swatch colour={names.get(t.surface)?.colour} />
              <span>{names.get(t.surface)?.name ?? t.surface}</span>
              <span className="tm-mono">{areaText(t.area)}</span>
              <span className="tm-mono cad-dampad">{shareText(t.share)}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="cad-dampad">Inga ytor än.</p>
      )}
      <p className="cad-dampad">Ballasten räknar spårbädden, som kommer från spårplanen.</p>
    </div>
  );
}

export type ViewProps = {
  module: Module;
  landscape: Landscape | null;
  /** The change set not saved yet, and what Ångra took back. */
  edits: number;
  undone: number;
  tool: Tool;
  surface: Surface;
  radius: number;
  photoUnder: boolean;
  busy?: boolean;
  error?: string | null;
  stale?: boolean;
  onTool?: (tool: Tool) => void;
  onSurface?: (surface: Surface) => void;
  onRadius?: (radius: number) => void;
  onPhotoUnder?: (on: boolean) => void;
  onOp?: (op: LandscapeOp) => void;
  onUndo?: () => void;
  onRedo?: () => void;
  onSave?: () => void;
  onApprove?: () => void;
  onMake?: () => void;
  onReload?: () => void;
};

/** Landskapet as the tab shows it, from the state; LandskapTab holds the state. */
export function LandskapView(props: ViewProps) {
  const { module, landscape, edits, tool, surface, radius, photoUnder, busy, error } = props;
  const old = module.version !== module.latest;
  const editable = module.may_edit && !old;
  if (!landscape) return <p className="cad-kort">Hämtar landskapet …</p>;
  const made = landscape.status !== "none";
  // Orange is what the photo proposed and the owner has not approved; what the owner painted is
  // the owner's own (CAD-17).
  const proposed = landscape.status === "proposal" && (landscape.areas ?? []).some((a) => !a.painted);
  const photo = landscape.photo != null || module.photo != null;
  const surfaces = (landscape.surfaces ?? NO_SURFACES).filter((s) => s.surface !== "unknown" || (landscape.totals ?? []).some((t) => t.surface === "unknown"));
  const header = (
    <div className="cad-kortrubrik">
      <h2>Landskapet</h2>
      {proposed ? <span className="cad-tagg forslag">Förslag</span> : null}
      {landscape.status === "proposal" && !proposed ? <span className="cad-status utkast">Utkast</span> : null}
      {landscape.status === "approved" ? <span className="cad-status godkand">✓ Godkänt</span> : null}
      {made ? (
        <span className="cad-dampad">
          {landscape.method === "colour" ? "Färgklustring av mätbilden" : landscape.method === "model" ? `${landscape.made_by ?? "TrainMeets modell"}` : "Målat för hand"}
          {landscape.saved_in && landscape.saved_in !== landscape.version ? ` · sparat i version ${landscape.saved_in}` : ""}
        </span>
      ) : null}
    </div>
  );
  const messages = (
    <>
      {error ? (
        <p className="cad-fel" role="alert">
          {error}
        </p>
      ) : null}
      {props.stale ? (
        <p className="cad-ruta" role="status">
          Modulen har en nyare version.{" "}
          <button type="button" className="cad-lank" onClick={() => props.onReload?.()}>
            Hämta den
          </button>
        </p>
      ) : null}
    </>
  );
  if (!made) {
    return (
      <section className="cad-kort cad-landskap tom" aria-label="Landskapet">
        {header}
        {messages}
        <p>Modulen har inget landskap än.</p>
        {editable ? (
          photo ? (
            <>
              <p className="cad-dampad">Ytorna görs ur mätbilden på CAD:s egen server: gräs, ballast, mark och väg, plattform, vatten, byggnad, buskar och stig. Gratis.</p>
              <button type="button" className="tm-knapp primar" disabled={busy} onClick={() => props.onMake?.()}>
                Gör landskapet ur mätbilden
              </button>
            </>
          ) : (
            <>
              <p className="cad-dampad">Modulen är inte fotad. Börja med ett tomt landskap och måla ytorna själv. Gratis.</p>
              <button type="button" className="tm-knapp primar" disabled={busy} onClick={() => props.onMake?.()}>
                Börja med ett tomt landskap
              </button>
            </>
          )
        ) : null}
        <LandskapCanvas module={module} landscape={landscape} tool={tool} surface={surface} radius={radius} photoUnder={photoUnder} editable={false} />
      </section>
    );
  }
  return (
    <section className={editable ? "cad-landskap" : "cad-landskap las"} aria-label="Landskapet">
      {editable ? (
        <div className="cad-verktyg" role="toolbar" aria-label="Verktyg för landskapet">
          {TOOLS.map(([key, label, title]) => (
            <button key={key} type="button" aria-pressed={tool === key} title={title} onClick={() => props.onTool?.(key)}>
              {label}
            </button>
          ))}
          <hr />
          <label className="cad-penselval">
            <span>Pensel</span>
            <select name="pensel" value={radius} onChange={(event) => props.onRadius?.(Number(event.currentTarget.value))} disabled={tool === "fill"}>
              {BRUSHES.map((b) => (
                <option key={b} value={b}>
                  {b} mm
                </option>
              ))}
            </select>
          </label>
          <hr />
          <button type="button" disabled={!edits || busy} onClick={() => props.onUndo?.()}>
            Ångra
          </button>
          <button type="button" disabled={!props.undone || busy} onClick={() => props.onRedo?.()}>
            Gör om
          </button>
        </div>
      ) : null}
      <div className="cad-kort cad-landskapkort">
        {header}
        {messages}
        {editable ? (
          <div className="cad-ytval" role="radiogroup" aria-label="Yta att måla">
            {surfaces.map((s) => (
              <button
                key={s.surface}
                type="button"
                role="radio"
                aria-checked={surface === s.surface}
                disabled={tool === "erase"}
                onClick={() => props.onSurface?.(s.surface)}
              >
                <Swatch colour={s.colour} />
                {s.name}
              </button>
            ))}
          </div>
        ) : null}
        <LandskapCanvas
          module={module}
          landscape={landscape}
          tool={tool}
          surface={surface}
          radius={radius}
          photoUnder={photoUnder}
          editable={editable && !busy}
          onOp={props.onOp}
        />
        <div className="cad-landskap-fot">
          {landscape.photo ? (
            <label className="cad-kryss">
              <input type="checkbox" checked={photoUnder} onChange={(event) => props.onPhotoUnder?.(event.currentTarget.checked)} />
              Mätbilden under
            </label>
          ) : null}
          <span className="cad-dampad">Spåren och ballasten under dem ritas från spårplanen, aldrig ur fotot.</span>
        </div>
        {proposed ? (
          <p className="cad-forslag-text">
            Ytorna med orange kant är ett förslag ur fotot tills du godkänner landskapet. Måla och sudda där det blev fel, till exempel skuggor.
          </p>
        ) : null}
        {landscape.method === "colour" ? (
          <p className="cad-dampad cad-modellnot">
            Färgklustringen gör ytorna tills TrainMeets egen modell för landskapet är tränad, på godkända moduler vars ägare sagt ja.
          </p>
        ) : null}
      </div>
      <div className="cad-sidokolumn">
        <Legend totals={landscape.totals ?? []} landscape={landscape} />
        {editable ? (
          <div className="cad-kort cad-landskap-knappar">
            {edits ? <p className="cad-dampad">{editsText(edits)}</p> : null}
            <div className="cad-knapprad">
              <button type="button" className="tm-knapp" disabled={!edits || busy} onClick={() => props.onSave?.()}>
                Spara
              </button>
              {landscape.status !== "approved" || edits ? (
                <button type="button" className="tm-knapp primar" disabled={busy} onClick={() => props.onApprove?.()}>
                  ✓ Godkänn landskapet
                </button>
              ) : null}
            </div>
            <p className="cad-dampad">Spara och Godkänn gör en ny version av modulen. Gratis.</p>
            <button
              type="button"
              className="cad-lank"
              disabled={busy}
              onClick={() => {
                if (typeof window === "undefined" || window.confirm(photo ? "Göra om landskapet ur mätbilden? Det du målat försvinner." : "Börja om med ett tomt landskap?")) props.onMake?.();
              }}
            >
              {photo ? "Gör om ur mätbilden" : "Börja om med ett tomt landskap"}
            </button>
          </div>
        ) : (
          <p className="cad-dampad">{old ? `Du ser version ${module.version}.` : "Bara ägaren och de med rollen redigera ändrar landskapet."}</p>
        )}
      </div>
    </section>
  );
}

function message(failure: unknown): string {
  return failure instanceof Error ? failure.message : "Något gick fel. Försök igen.";
}

/** The Landskap tab: the landscape of the version shown, and the change set on the newest. */
export function LandskapTab({ module, onChanged, client = landscapeApi }: { module: Module; onChanged?: () => void; client?: LandscapeApi }) {
  const [landscape, setLandscape] = useState<Landscape | null>(null);
  const [ops, setOps] = useState<LandscapeOp[]>([]);
  const [undone, setUndone] = useState<LandscapeOp[]>([]);
  const [tool, setTool] = useState<Tool>("paint");
  const [surface, setSurface] = useState<Surface>("grass");
  const [radius, setRadius] = useState(20);
  const [photoUnder, setPhotoUnder] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [stale, setStale] = useState(false);
  const version = module.version;
  // The newest version, as the base of the next change: from the module, and at once from each
  // answer, so that Godkänn right after Spara does not send the version before (409) while the
  // module is read again.
  const [latest, setLatest] = useState(module.latest);
  useEffect(() => setLatest((known) => Math.max(known, module.latest)), [module.latest]);

  const load = useCallback(() => {
    setOps([]);
    setUndone([]);
    setStale(false);
    client.landscape(module.id, version).then(setLandscape, (failure: unknown) => setError(message(failure)));
  }, [client, module.id, version]);
  useEffect(load, [load]);

  const failed = (failure: unknown) => {
    setBusy(false);
    if (failure instanceof ApiError && failure.status === 409) setStale(true);
    else setError(message(failure));
  };
  const show = (next: LandscapeOp[], back: LandscapeOp[]) => {
    setBusy(true);
    client.preview(module.id, { base: latest, operations: next }).then((found) => {
      setLandscape(found);
      setOps(next);
      setUndone(back);
      setError(null);
      setBusy(false);
    }, failed);
  };
  const saved = (found: Landscape) => {
    setLatest((known) => Math.max(known, found.latest));
    setLandscape(found);
    setOps([]);
    setUndone([]);
    setBusy(false);
    setError(null);
    onChanged?.();
  };
  return (
    <LandskapView
      module={module}
      landscape={landscape}
      edits={ops.length}
      undone={undone.length}
      tool={tool}
      surface={surface}
      radius={radius}
      photoUnder={photoUnder}
      busy={busy}
      error={error}
      stale={stale}
      onTool={setTool}
      onSurface={setSurface}
      onRadius={setRadius}
      onPhotoUnder={setPhotoUnder}
      onOp={(op) => show([...ops, op], [])}
      onUndo={() => ops.length && show(ops.slice(0, -1), [ops[ops.length - 1] as LandscapeOp, ...undone])}
      onRedo={() => undone.length && show([...ops, undone[0] as LandscapeOp], undone.slice(1))}
      onSave={() => {
        setBusy(true);
        client.save(module.id, { base: latest, operations: ops }).then(saved, failed);
      }}
      onApprove={() => {
        setBusy(true);
        client.approve(module.id, { base: latest, operations: ops }).then(saved, failed);
      }}
      onMake={() => {
        setBusy(true);
        client.make(module.id, latest).then(saved, failed);
      }}
      onReload={() => {
        setError(null);
        onChanged?.();
      }}
    />
  );
}
