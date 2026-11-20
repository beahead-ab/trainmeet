// Lås mått (#89 del b, CAD-24): "Lås ett mått, räkna om kurvan", as the view Las-matt. The gable
// tracks' positions are locked, and CAD makes the curve between them straight, arc, straight, arc,
// straight, fitted to the old line: the old line dashed in orange, the new geometry in black and
// the tangent points as blue crosses. Behåll linjen goes back; Använd geometrin saves a version.
import { linkClick, type Navigate } from "@trainmeet/design";
import { useEffect, useState } from "react";
import type { LockMeasures, LockProposal, LockRadii, Module, Segment } from "./api";
import { bendText, NORM_NAMES } from "./common";
import { f, kantOne, outline, pathOf, poly, turnDegrees, turner } from "./Drawing";
import { gableLine, mmText, onGable, type Point } from "./geometry";
import { drawingPath, modulePath, PATHS } from "./routes";

type Props = {
  module: Module;
  proposal: LockProposal | null;
  busy?: boolean;
  error?: string | null;
  navigate?: Navigate;
  /** A new lock to preview: other values, or other radii. */
  onChange?: (lock: LockMeasures) => void;
  onUse?: (lock: LockMeasures) => void;
};

function sizeText(module: Module): string {
  const shape = module.shape;
  if (shape.kind === "curve") return bendText(shape.radius, shape.angle);
  if (shape.kind === "trapezoid") return `${Math.round(shape.length)} × ${Math.round(shape.width_a)}/${Math.round(shape.width_b)}`;
  return `${Math.round(shape.length)} × ${Math.round(shape.width)}`;
}



function mm(value: number): string {
  return Math.abs(value - Math.round(value)) < 0.05 ? mmText(value) : value.toLocaleString("sv-SE", { maximumFractionDigits: 1 });
}

function partValue(part: NonNullable<LockProposal["parts"]>[number]): string {
  if (part.kind === "arc") return `R ${mmText(part.radius ?? 0)} mm`;
  if (part.label === "Rakt") return `${mmText(part.length)} mm · ${Math.round(part.angle)}°`;
  return `${mmText(part.length)} mm`;
}

function Picture({ module, proposal }: { module: Module; proposal: LockProposal }) {
  const shape = module.shape;
  const track1 = module.gables[0]?.tracks?.[0] ?? 0;
  const board = outline(shape, track1);
  const turn = turner(shape);
  const turned = board.map(turn);
  const xs = turned.map((p) => p[0]);
  const ys = turned.map((p) => p[1]);
  const minX = Math.min(...xs);
  const minY = Math.min(...ys);
  const w = Math.max(...xs) - minX;
  const h = Math.max(...ys) - minY;
  const unit = Math.max(w, h) / 100;
  const pad = Math.max(w, h) * 0.16;
  const segs = (proposal.new ?? []).map((s: Segment) =>
    s.kind === "arc" ? { kind: "arc" as const, start: s.start, end: s.end, center: s.center, radius: s.radius, clockwise: s.clockwise } : { kind: "line" as const, start: s.start, end: s.end },
  );
  const old = proposal.old ?? [];
  const parts = (proposal.parts ?? []).filter((p) => p.length >= 0.5);
  const lockA = proposal.gables?.[0];
  const lockB = proposal.gables?.[1];
  const lineA = gableLine(shape, track1, "A");
  const lineB = gableLine(shape, track1, "B");
  const lockAt = (g: typeof lockA, line: typeof lineA): Point | null => (g ? onGable(line, g.value) : null);
  const a = lockAt(lockA, lineA);
  const b = lockAt(lockB, lineB);
  return (
    <svg className="cad-ritning cad-lasbild" viewBox={`${f(minX - pad)} ${f(minY - pad)} ${f(w + 2 * pad)} ${f(h + 2 * pad)}`} role="img" aria-label="Den gamla linjen och den nya geometrin">
      <g transform={turnDegrees(shape) ? `rotate(${f(turnDegrees(shape))})` : undefined}>
        <path className="cad-skiva" d={poly(board, (p) => p, true)} strokeWidth={unit * 0.3} />
        <path className="cad-kant1" d={poly(kantOne(shape, track1), (p) => p, false)} strokeWidth={unit * 0.9} />
        {segs.map((seg, i) => (
          <path key={`b${i}`} className="cad-ballast" d={pathOf(seg, (p) => p)} strokeWidth={unit * 2.4} />
        ))}
        {segs.map((seg, i) => (
          <path key={`n${i}`} className="cad-spar" d={pathOf(seg, (p) => p)} strokeWidth={unit * 0.5} />
        ))}
        {old.length > 1 ? <path className="cad-gammal" d={poly(old, (p) => p, false)} strokeWidth={unit * 0.5} strokeDasharray={`${unit * 1.6} ${unit * 1.1}`} /> : null}
        {(proposal.tangents ?? []).map((p, i) => (
          <path key={`t${i}`} className="cad-tangent" d={`M${f(p[0] - unit)} ${f(p[1] - unit)}L${f(p[0] + unit)} ${f(p[1] + unit)}M${f(p[0] - unit)} ${f(p[1] + unit)}L${f(p[0] + unit)} ${f(p[1] - unit)}`} strokeWidth={unit * 0.4} />
        ))}
        {parts.map((part, i) => {
          const seg = segs[(proposal.parts ?? []).indexOf(part)];
          if (!seg) return null;
          const mid: Point = seg.kind === "line" ? [(seg.start[0] + seg.end[0]) / 2, (seg.start[1] + seg.end[1]) / 2] : midOfArc(seg);
          const below = part.kind === "arc";
          return (
            <text key={`p${i}`} x={mid[0]} y={mid[1] + (below ? unit * 5.5 : -unit * 2)} fontSize={unit * 2.6} textAnchor="middle" className="cad-del">
              {part.kind === "arc" ? `R ${mmText(part.radius ?? 0)}` : part.label === "Rakt" ? `rakt ${mmText(part.length)} · ${Math.round(part.angle)}°` : `rakt ${mmText(part.length)}`}
            </text>
          );
        })}
        {a && lockA ? (
          <g className="cad-lasmarke">
            <path d={`M${f(a[0])} ${f(a[1])}H${f(a[0] - unit * 6)}`} strokeWidth={unit * 0.3} />
            <text x={a[0] - unit * 7} y={a[1] + unit * 1.1} fontSize={unit * 3.2} textAnchor="end">
              🔒 {mm(lockA.value)}
            </text>
          </g>
        ) : null}
        {b && lockB ? (
          <g className="cad-lasmarke">
            <path d={`M${f(b[0])} ${f(b[1])}H${f(b[0] + unit * 6)}`} strokeWidth={unit * 0.3} />
            <text x={b[0] + unit * 7} y={b[1] + unit * 1.1} fontSize={unit * 3.2} textAnchor="start">
              {mm(lockB.value)} 🔒
            </text>
          </g>
        ) : null}
      </g>
      <g className="cad-texter" fontSize={unit * 3}>
        <text x={minX} y={minY - pad * 0.5} className="cad-gavel-text">
          GAVEL A · {mm(module.shape.kind === "trapezoid" ? module.shape.width_a : module.shape.width)}
        </text>
        <text x={minX + w} y={minY - pad * 0.5} textAnchor="end" className="cad-gavel-text">
          GAVEL B · {mm(module.shape.kind === "trapezoid" ? module.shape.width_b : module.shape.width)}
        </text>
      </g>
    </svg>
  );
}

function midOfArc(seg: { start: Point; end: Point; center: Point; radius: number; clockwise: boolean }): Point {
  const a0 = Math.atan2(seg.start[1] - seg.center[1], seg.start[0] - seg.center[0]);
  const a1 = Math.atan2(seg.end[1] - seg.center[1], seg.end[0] - seg.center[0]);
  let turn = seg.clockwise ? a1 - a0 : a0 - a1;
  turn = ((turn % (2 * Math.PI)) + 2 * Math.PI) % (2 * Math.PI);
  const phi = a0 + ((seg.clockwise ? 1 : -1) * turn) / 2;
  return [seg.center[0] + seg.radius * Math.cos(phi), seg.center[1] + seg.radius * Math.sin(phi)];
}

export function LasMatt({ module, proposal, busy = false, error, navigate, onChange, onUse }: Props) {
  const lock = proposal?.lock;
  const [a, setA] = useState(proposal?.gables?.[0] ? mm(proposal.gables[0].value) : "");
  const [b, setB] = useState(proposal?.gables?.[1] ? mm(proposal.gables[1].value) : "");
  useEffect(() => {
    setA(proposal?.gables?.[0] ? mm(proposal.gables[0].value) : "");
    setB(proposal?.gables?.[1] ? mm(proposal.gables[1].value) : "");
  }, [proposal]);
  const norm = module.gables.map((g) => g.norm).find(Boolean);
  const change = (next: Partial<LockMeasures>) => {
    if (!lock) return;
    onChange?.({ ...lock, ...next });
  };
  const value = (text: string): number | null => {
    const n = Number(text.replace(",", "."));
    return n > 0 ? n : null;
  };
  const [radii, setRadii] = useState<LockRadii>(proposal?.radii ?? "same");
  useEffect(() => setRadii(proposal?.radii ?? "same"), [proposal?.radii]);
  const back = drawingPath(module.id);
  return (
    <section className="cad-sida cad-lasmatt" aria-labelledby="rubrik">
      <nav className="cad-brodsmulor" aria-label="Var du är">
        <a href={PATHS.library} onClick={linkClick(navigate, PATHS.library)}>
          Moduler
        </a>{" "}
        ›{" "}
        <a href={modulePath(module.id)} onClick={linkClick(navigate, modulePath(module.id))}>
          {module.name}
        </a>{" "}
        ›{" "}
        <a href={back} onClick={linkClick(navigate, back)}>
          Ritningen
        </a>{" "}
        › <span aria-current="page">Lås mått</span>
      </nav>
      <div className="cad-rubrikrad">
        <h1 id="rubrik">Lås ett mått, räkna om kurvan</h1>
        <span className="cad-pill tm-mono">{sizeText(module)}</span>
        {norm ? <span className="cad-bricka">{NORM_NAMES[norm] ?? norm}</span> : null}
        <span className="cad-fyll" />
        <a className="tm-knapp" href={back} onClick={linkClick(navigate, back)}>
          Behåll linjen
        </a>
        {busy ? <span className="cad-dampad">Räknar om …</span> : null}
        <button type="button" className="tm-knapp primar" disabled={!proposal?.solved || busy} onClick={() => lock && onUse?.(lock)}>
          ✓ Använd geometrin
        </button>
      </div>
      {error ? (
        <p className="cad-fel" role="alert">
          {error}
        </p>
      ) : null}
      <div className="cad-laslayout">
        <div className="cad-kort cad-dukkort">
          {proposal ? <Picture module={module} proposal={proposal} /> : <p className="cad-dampad">Räknar om kurvan …</p>}
          <ul className="cad-teckenforklaring">
            <li>
              <span className="cad-streck gammal" /> linjen nu
            </li>
            <li>
              <span className="cad-streck ny" /> ny geometri
            </li>
            <li>
              <span className="cad-kryssmarke">✕</span> tangentpunkt
            </li>
          </ul>
        </div>
        <div className="cad-sidokolumn">
          <section className="cad-kort" aria-labelledby="lasta-rubrik">
            <h2 id="lasta-rubrik" className="cad-overrubrik">
              Låsta mått
            </h2>
            {(proposal?.gables ?? []).map((g, i) => (
              <div key={g.gable} className="cad-lasrad">
                <div>
                  <b>
                    Gavel {g.gable} · spår {g.track}
                  </b>
                  <span className="cad-dampad">linjen sa {mm(g.line)} mm</span>
                </div>
                <label className="cad-mm cad-lasfalt">
                  <span aria-hidden="true">🔒</span>
                  <span className="cad-dold">{`Gavel ${g.gable}, spår ${g.track}, låst mått`}</span>
                  <input
                    name={`las-${g.gable}`}
                    inputMode="decimal"
                    value={i === 0 ? a : b}
                    onChange={(event) => (i === 0 ? setA : setB)(event.currentTarget.value)}
                    onBlur={() => change(i === 0 ? { a: value(a) } : { b: value(b) })}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") change(i === 0 ? { a: value(a) } : { b: value(b) });
                    }}
                  />
                  <span aria-hidden="true">mm</span>
                </label>
              </div>
            ))}
            <p className={proposal && !proposal.solved ? "cad-fel" : "cad-dampad"}>{proposal?.why}</p>
          </section>
          <section className="cad-kort" aria-labelledby="kurvan-rubrik">
            <h2 id="kurvan-rubrik" className="cad-overrubrik">
              Kurvan
            </h2>
            <div className="cad-radioval" role="radiogroup" aria-label="Bågarnas radier">
              {(
                [
                  ["same", "Samma radie i båda bågarna"],
                  ["different", "Olika radier"],
                ] as [LockRadii, string][]
              ).map(([key, label]) => (
                <label key={key} className="cad-radio">
                  <input type="radio" name="radier" value={key} checked={radii === key} onChange={() => {
                      setRadii(key);
                      change({ radii: key });
                    }} />
                  {label}
                </label>
              ))}
            </div>
            {proposal?.solved ? (
              <>
                <table className="cad-tabell cad-delar">
                  <thead>
                    <tr>
                      <th>Del</th>
                      <th className="tm-mono">Mått</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(proposal.parts ?? []).map((part, i) => (
                      <tr key={i}>
                        <td>{part.label}</td>
                        <td className="tm-mono">{partValue(part)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {proposal.deviation ? (
                  <p className="cad-knapprad">
                    <span className="cad-tagg gron">✓ Avviker median {proposal.deviation.median.toLocaleString("sv-SE", { maximumFractionDigits: 1 })} mm</span>
                    <span className="cad-tagg gron">högst {proposal.deviation.max.toLocaleString("sv-SE", { maximumFractionDigits: 1 })} mm</span>
                  </p>
                ) : null}
              </>
            ) : null}
          </section>
          <p className="cad-ruta cad-infobox">
            ⓘ DXF-filen får riktiga linjer och bågar för spårmitten, så radierna går att mäta i ett CAD-program. Exporten kommer i nästa steg.
          </p>
        </div>
      </div>
    </section>
  );
}
