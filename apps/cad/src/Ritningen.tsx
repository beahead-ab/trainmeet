// Ritningen (#89 del b, CAD-03): the track plan to draw and change, as the view Ritningen. Tools on
// the left, the canvas in the middle, and the switch inspector, Att kolla, Utjämning and the layers
// on the right. Every change is an operation in the change set; CAD applies the list and answers
// with the drawing, and Spara makes it a new version. Godkänn spårplanen waits for Att kolla.
import { linkClick, type Navigate } from "@trainmeet/design";
import { useEffect, useState } from "react";
import type { CheckItem, DrawingView, EditOp, Module, Smoothing, SwitchInfo } from "./api";
import { Canvas, type Layers, type Selection } from "./Canvas";
import { op, sourceBadge, TOOLS, type Tool } from "./editor";
import { mmText, type Point } from "./geometry";
import { lockPath, modulePath, PATHS } from "./routes";

type Props = {
  module: Module;
  view: DrawingView | null;
  /** How many operations the change set has, and how many are undone. */
  changes: number;
  undone: number;
  busy?: boolean;
  error?: string | null;
  /** 409: someone saved in between. */
  stale?: boolean;
  navigate?: Navigate;
  onOps?: (ops: EditOp[]) => void;
  onUndo?: () => void;
  onRedo?: () => void;
  onSave?: () => void;
  onApprove?: () => void;
  onReload?: () => void;
  /** For the tests: the tool and selection to start with. */
  initialTool?: Tool;
  initialSelection?: Selection;
};

const ICONS: Record<Tool, string> = {
  select: "M5 3l12 8-6 1.5L8 19z",
  switch: "M12 3v18M3 12h18M7 7l-4 5 4 5M17 7l4 5-4 5",
  line: "M4 18L18 6",
  arc: "M4 18C6 9 12 5 20 5",
  lock: "M6 11h12v9H6zM9 11V8a3 3 0 0 1 6 0v3",
  measure: "M3 15l12-12 6 6-12 12zM7 11l2 2M10 8l2 2M13 5l2 2",
  text: "M5 5h14M12 5v14",
};

function ToolIcon({ tool }: { tool: Tool }) {
  return (
    <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true">
      <path d={ICONS[tool]} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function Inspector({ info, view, onOps }: { info: SwitchInfo; view: DrawingView; onOps?: (ops: EditOp[]) => void }) {
  const [radius, setRadius] = useState(info.radius != null ? String(Math.round(info.radius)) : "");
  useEffect(() => setRadius(info.radius != null ? String(Math.round(info.radius)) : ""), [info.radius]);
  const badge = info.origin?.source === "photo" && info.origin.certainty !== "confirmed" ? "AI-förslag" : info.assumed ? "Antagen" : null;
  const commit = () => {
    const value = Number(radius.replace(",", "."));
    if (value > 0 && Math.abs(value - (info.radius ?? 0)) >= 0.5) onOps?.([op.setSwitch(info.id, { radius: value })]);
  };
  return (
    <section className="cad-kort cad-inspektor" aria-labelledby="vaxel-rubrik">
      <div className="cad-inspektor-rubrik">
        <span className="cad-vaxelnummer">{info.number}</span>
        <h2 id="vaxel-rubrik">Växel {info.number}</h2>
        {badge ? <span className={`cad-tagg ${badge === "AI-förslag" ? "orange" : "gul"}`}>{badge}</span> : null}
      </div>
      <dl className="cad-inspektor-fakta">
        <dt>Lämnar</dt>
        <dd>{info.leaves}</dd>
        <dt>Tungspetsar</dt>
        <dd>
          <span className="tm-mono">{mmText(info.from_a)} mm</span> från gavel A
        </dd>
        <dt>
          <label htmlFor="vaxel-radie">Avvikande radie</label>
        </dt>
        <dd>
          <span className="cad-mm">
            <input
              id="vaxel-radie"
              name="vaxel-radie"
              inputMode="decimal"
              value={radius}
              onChange={(event) => setRadius(event.currentTarget.value)}
              onBlur={commit}
              onKeyDown={(event) => {
                if (event.key === "Enter") commit();
              }}
            />
            <span aria-hidden="true">mm</span>
          </span>
        </dd>
        <dt>
          <label htmlFor="vaxel-typ">Växeltyp</label>
        </dt>
        <dd>
          <select id="vaxel-typ" name="vaxel-typ" value={info.design} onChange={(event) => onOps?.([op.setSwitch(info.id, { design: event.currentTarget.value })])}>
            {(view.designs ?? []).map((design) => (
              <option key={design.id} value={design.id}>
                {design.name}
              </option>
            ))}
          </select>
        </dd>
      </dl>
      {info.design === "okand" && info.matched ? (
        <p className="cad-dampad">Radien stämmer med {(view.designs ?? []).find((d) => d.id === info.matched)?.name}.</p>
      ) : null}
      {info.design !== "okand" ? <p className="cad-dampad">{(view.designs ?? []).find((d) => d.id === info.design)?.source}</p> : null}
      <label className="cad-kryss">
        <input type="checkbox" name="las-vaxel" checked={info.locked} onChange={(event) => onOps?.([op.setSwitch(info.id, { locked: event.currentTarget.checked })])} />
        Lås växelns läge när kurvorna räknas om
      </label>
      <button type="button" className="cad-lank fara" onClick={() => onOps?.([op.remove(info.id)])}>
        Ta bort växeln
      </button>
    </section>
  );
}

function Checks({ items, onAnswer }: { items: CheckItem[]; onAnswer: (item: CheckItem, choice: CheckItem["choices"][number]) => void }) {
  const open = items.filter((item) => !item.answer);
  const answered = items.filter((item) => item.answer);
  return (
    <section className="cad-kort cad-attkolla" aria-labelledby="attkolla-rubrik">
      <h2 id="attkolla-rubrik" className="cad-overrubrik">
        Att kolla <span className="cad-antal">{open.length}</span>
      </h2>
      {open.length === 0 ? <p className="cad-dampad">Inget att kolla. Spårplanen kan godkännas.</p> : null}
      <ol className="cad-kollista">
        {open.map((item, i) => (
          <li key={item.key} className={item.assumed ? "antagen" : "forslag"} data-key={item.key}>
            <h3>{`${i + 1} · ${item.title}`}</h3>
            <p>{item.text}</p>
            <div className="cad-knapprad">
              {item.choices.map((choice) => (
                <button key={choice.id} type="button" className="tm-knapp" onClick={() => onAnswer(item, choice)}>
                  {choice.text}
                </button>
              ))}
            </div>
          </li>
        ))}
      </ol>
      {answered.length ? (
        <details className="cad-besvarade">
          <summary>{answered.length === 1 ? "1 besvarad" : `${answered.length} besvarade`}</summary>
          <ul>
            {answered.map((item) => (
              <li key={item.key}>
                ✓ {item.title}: {item.choices.find((c) => c.id === item.answer?.answer)?.text ?? item.answer?.answer}
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </section>
  );
}

function Utjamning({ view, onOps }: { view: DrawingView; onOps?: (ops: EditOp[]) => void }) {
  const level = view.drawing.smoothing ?? "normal";
  const current = (view.smoothing_levels ?? []).find((x) => x.level === level);
  return (
    <section className="cad-kort" aria-labelledby="utjamning-rubrik">
      <h2 id="utjamning-rubrik" className="cad-overrubrik">
        Utjämning
      </h2>
      <div className="cad-segment" role="radiogroup" aria-label="Utjämning">
        {(view.smoothing_levels ?? []).map((x) => (
          <button key={x.level} type="button" role="radio" aria-checked={x.level === level} onClick={() => x.level !== level && onOps?.([op.smoothing(x.level as Smoothing)])}>
            {x.name}
          </button>
        ))}
      </div>
      <p className="cad-dampad cad-forklaring">{current?.text}</p>
      {view.stats.deviation ? (
        <p className="cad-dampad">
          Avviker från de ritade linjerna: median {view.stats.deviation.median.toLocaleString("sv-SE")} mm, högst{" "}
          {view.stats.deviation.max.toLocaleString("sv-SE")} mm.
        </p>
      ) : null}
    </section>
  );
}

function Lager({ layers, onChange }: { layers: Layers; onChange: (layers: Layers) => void }) {
  const rows: [keyof Layers | "photo" | "landscape", string][] = [
    ["tracks", "Spår och växlar"],
    ["numbers", "Växelnummer"],
    ["gables", "Gavelmått"],
    ["photo", "Fotot under"],
    ["landscape", "Landskap"],
  ];
  return (
    <section className="cad-kort cad-lager" aria-labelledby="lager-rubrik">
      <h2 id="lager-rubrik" className="cad-overrubrik">
        Lager
      </h2>
      {rows.map(([key, label]) => {
        const later = key === "photo" || key === "landscape";
        const on = later ? false : layers[key as keyof Layers];
        return (
          <label key={key} className={`cad-lagerrad${later ? " kommer" : ""}`}>
            <span>
              {label}
              {later ? <span className="cad-kommer-text"> kommer</span> : null}
            </span>
            <input
              type="checkbox"
              role="switch"
              name={`lager-${key}`}
              checked={on}
              disabled={later}
              onChange={(event) => !later && onChange({ ...layers, [key]: event.currentTarget.checked })}
            />
          </label>
        );
      })}
    </section>
  );
}

function TextForm({ target, at, onDone }: { target: string | null; at: Point; onDone: (text: string | null) => void }) {
  const [text, setText] = useState("");
  return (
    <form
      className="cad-kort cad-textform"
      onSubmit={(event) => {
        event.preventDefault();
        onDone(text.trim());
      }}
    >
      <h2 className="cad-overrubrik">Text</h2>
      <label className="cad-falt">
        <span>{target ? "Texten på det du klickade" : `Text vid x ${mmText(at[0])} · y ${mmText(at[1])} mm`}</span>
        <input name="text" value={text} maxLength={40} autoFocus onChange={(event) => setText(event.currentTarget.value)} />
      </label>
      <div className="cad-knapprad">
        <button type="submit" className="tm-knapp primar">
          Skriv
        </button>
        <button type="button" className="tm-knapp" onClick={() => onDone(null)}>
          Avbryt
        </button>
      </div>
    </form>
  );
}

export function Ritningen({
  module,
  view,
  changes,
  undone,
  busy = false,
  error,
  stale = false,
  navigate,
  onOps,
  onUndo,
  onRedo,
  onSave,
  onApprove,
  onReload,
  initialTool = "select",
  initialSelection = null,
}: Props) {
  const [tool, setTool] = useState<Tool>(initialTool);
  const [selected, setSelected] = useState<Selection>(initialSelection);
  const [layers, setLayers] = useState<Layers>({ tracks: true, numbers: true, gables: true });
  const [zoom, setZoom] = useState(1);
  const [writing, setWriting] = useState<{ target: string | null; at: Point } | null>(null);
  const items = view?.checks ?? [];
  const open = items.filter((item) => !item.answer);
  const toLock = (piece: string | null) => navigate?.(lockPath(module.id) + (piece ? `?spar=${encodeURIComponent(piece)}` : ""));

  useEffect(() => {
    const key = (event: KeyboardEvent) => {
      if (event.target instanceof HTMLElement && /INPUT|SELECT|TEXTAREA/.test(event.target.tagName)) return;
      const mod = event.ctrlKey || event.metaKey;
      if (mod && event.key.toLowerCase() === "z") {
        event.preventDefault();
        if (event.shiftKey) onRedo?.();
        else onUndo?.();
      } else if (mod && event.key.toLowerCase() === "y") {
        event.preventDefault();
        onRedo?.();
      } else if ((event.key === "Delete" || event.key === "Backspace") && selected) {
        event.preventDefault();
        onOps?.([op.remove(selected.id)]);
        setSelected(null);
      } else if (event.key === "Escape") setSelected(null);
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  });

  const badge = sourceBadge(view?.drawing.source);
  const info = selected?.kind === "switch" ? (view?.switches ?? []).find((s) => s.id === selected.id) : undefined;
  const answer = (item: CheckItem, choice: CheckItem["choices"][number]) => {
    if (choice.action === "design") {
      const sw = item.refs?.find((ref) => (view?.switches ?? []).some((s) => s.id === ref));
      if (sw) setSelected({ kind: "switch", id: sw });
      window.setTimeout(() => document.getElementById("vaxel-typ")?.focus(), 0);
      return;
    }
    if (choice.action === "lock") {
      toLock(null);
      return;
    }
    onOps?.([op.answer(item.key, choice.id)]);
  };
  const hint = TOOLS.find((t) => t.tool === tool)?.hint;
  return (
    <section className="cad-sida cad-ritningen" aria-labelledby="rubrik">
      <nav className="cad-brodsmulor" aria-label="Var du är">
        <a href={PATHS.library} onClick={linkClick(navigate, PATHS.library)}>
          Moduler
        </a>{" "}
        ›{" "}
        <a href={modulePath(module.id)} onClick={linkClick(navigate, modulePath(module.id))}>
          {module.name}
        </a>{" "}
        › <span aria-current="page">Ritningen</span>
      </nav>
      <div className="cad-rubrikrad">
        <h1 id="rubrik">Ritningen</h1>
        <span className={`cad-tagg ${badge.kind}`}>{badge.text}</span>
        {open.length ? (
          <span className="cad-tagg gul" role="status">
            ⚠ {open.length === 1 ? "1 sak att kolla" : `${open.length} saker att kolla`}
          </span>
        ) : null}
        <span className="cad-pill">Version {module.version}</span>
        {module.status === "approved" && !changes ? <span className="cad-status godkand">✓ Godkänd</span> : null}
        <span className="cad-fyll" />
        <button type="button" className="tm-knapp" disabled title="Exporten kommer i del d">
          Exportera <span className="cad-kommer-text">kommer</span>
        </button>
        <button type="button" className="tm-knapp" disabled={!changes || busy} onClick={() => onSave?.()}>
          Spara
        </button>
        <button
          type="button"
          className="tm-knapp primar"
          disabled={busy || !view || open.length > 0}
          title={open.length ? "Svara på det som står under Att kolla först." : undefined}
          onClick={() => onApprove?.()}
        >
          ✓ Godkänn spårplanen
        </button>
      </div>
      {stale ? (
        <p className="cad-fel" role="alert">
          Modulen har en nyare version. Dina ändringar går inte att spara ovanpå den.{" "}
          <button type="button" className="cad-lank" onClick={() => onReload?.()}>
            Öppna den senaste
          </button>
        </p>
      ) : error ? (
        <p className="cad-fel" role="alert">
          {error}
        </p>
      ) : null}
      <div className="cad-ritlayout">
        <div className="cad-verktyg" role="toolbar" aria-label="Verktyg">
          {TOOLS.map((t) => (
            <button
              key={t.tool}
              type="button"
              aria-pressed={tool === t.tool}
              title={t.hint}
              onClick={() => {
                if (t.tool === "lock") toLock(selected?.kind === "piece" ? selected.id : null);
                else setTool(t.tool);
              }}
            >
              <ToolIcon tool={t.tool} />
              <span>{t.label}</span>
            </button>
          ))}
          <hr />
          <button type="button" onClick={() => onUndo?.()} disabled={!changes || busy} title="Ctrl+Z">
            <span>Ångra</span>
          </button>
          <button type="button" onClick={() => onRedo?.()} disabled={!undone || busy} title="Ctrl+Skift+Z">
            <span>Gör om</span>
          </button>
        </div>
        <div className="cad-kort cad-dukkort">
          {view ? (
            <Canvas
              view={view}
              tool={tool}
              layers={layers}
              selected={selected}
              checks={open}
              zoom={zoom}
              onZoom={setZoom}
              onOps={(ops) => onOps?.(ops)}
              onSelect={setSelected}
              onText={(target, at) => setWriting({ target, at })}
              onLock={toLock}
            />
          ) : (
            <p className="cad-dampad">Hämtar ritningen …</p>
          )}
          <p className="cad-dampad cad-tips">{hint}</p>
        </div>
        <div className="cad-sidokolumn">
          {writing ? (
            <TextForm
              key={`${writing.target}-${writing.at.join()}`}
              target={writing.target}
              at={writing.at}
              onDone={(text) => {
                if (text) onOps?.([writing.target ? op.label(writing.target, null, text) : op.label(null, writing.at, text)]);
                setWriting(null);
              }}
            />
          ) : null}
          {info && view ? (
            <Inspector key={info.id} info={info} view={view} onOps={onOps} />
          ) : (
            <section className="cad-kort cad-inspektor tom">
              <h2 className="cad-overrubrik">Växel</h2>
              <p className="cad-dampad">
                {(view?.switches ?? []).length ? "Välj en växel i ritningen så visas den här." : "Ingen växel än. Dra ett spår från mitten av ett annat så blir det en växel."}
              </p>
            </section>
          )}
          <Checks items={items} onAnswer={answer} />
          {view ? <Utjamning view={view} onOps={onOps} /> : null}
          <Lager layers={layers} onChange={setLayers} />
        </div>
      </div>
    </section>
  );
}
