// Studio › Dela stationen (#87 del b, TKL97–TKL103): the owner divides the station into parts.
// A part has a name, and is its own driftplats in Hubben with an id and a signature when it is
// staffed on its own (TKL101). Its area is drawn on the station's panel, section by section,
// with its own switches, its border switches with their owner and position towards the part,
// and the signals in it and at its border (TKL99). The rules at the border are on by default.
// Its switch streets are chosen by an end and a track, computed by TKL from the track graph, and
// its routes out from the station's routes that leave the area. Studio's checks are listed and
// each shows what it is about. Everything is saved as a draft on the computer, as Rita's
// drawing, until Använd makes it the station model's; that waits while routes are set (409).
// The area is picked with omrade.ts, which local release can use as well (TKL103).
import { useCallback, useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { api, Problem, type Dela, type DelaCheck, type DelaFound, type Panel, type PartSide, type RouteOut, type StationPart, type SwitchStreet, type TrackPlan } from "./api";
import {
  addStreet,
  changePart,
  checkList,
  clickPiece,
  DraftSaver,
  clickSignal,
  clickSwitch,
  hasRouteOut,
  markOf,
  newPart,
  removeStreet,
  renamed,
  renameRouteOut,
  renameStreet,
  routesOutAt,
  setBorder,
  SIDES,
  streetsAt,
  toggleRouteOut,
  TOOLS,
  validId,
  type Marked,
  type Tool,
} from "./dela";
import { inArea } from "./omrade";
import { points, round, viewBox } from "./sparplan";
import "./dela.css";

const SAVE_AFTER_MS = 400;
const STATES: Record<string, string> = { draft: "Utkast, sparat på datorn", in_use: "Används i Ställverket" };

export function DelaStationen({ onChanged }: { onChanged?: () => void }) {
  const [plan, setPlan] = useState<TrackPlan | null | undefined>(undefined);
  const [view, setView] = useState<Dela | null>(null);
  const [parts, setParts] = useState<StationPart[]>([]);
  const [chosen, setChosen] = useState<string | null>(null);
  const [tool, setTool] = useState<Tool>("area");
  const [side, setSide] = useState<PartSide>("left");
  const [marked, setMarked] = useState<Marked>(null);
  const [message, setMessage] = useState("");
  const [problems, setProblems] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);
  const [busy, setBusy] = useState(false);
  const saver = useRef<DraftSaver | null>(null);
  saver.current ??= new DraftSaver(api.saveParts, setView, setMessage, setSaving, SAVE_AFTER_MS);

  const load = useCallback((found: Dela) => {
    setView(found);
    setParts(found.parts ?? []);
    setChosen((before) => (found.parts ?? []).find((p) => p.id === before)?.id ?? found.parts?.[0]?.id ?? null);
  }, []);

  useEffect(() => {
    Promise.all([api.stationModel(), api.dela()])
      .then(([found, shown]) => {
        setPlan(found);
        load(shown);
      })
      .catch((error: unknown) => {
        setPlan(null);
        setMessage(error instanceof Error ? error.message : "TKL svarar inte.");
      });
  }, [load]);

  const change = (next: StationPart[]) => {
    setParts(next);
    setMessage("");
    saver.current?.later(next);
  };

  const act = async (work: () => Promise<Dela>, done?: string) => {
    setBusy(true);
    setMessage("");
    setProblems([]);
    try {
      load(await work());
      if (done) setMessage(done);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Det gick inte.");
      setProblems(error instanceof Problem ? error.problems : []);
    } finally {
      setBusy(false);
    }
  };

  const use = () =>
    act(async () => {
      await saver.current?.flush();
      const used = await api.useParts();
      onChanged?.();
      return used;
    }, USED);

  const forget = () =>
    act(() => {
      saver.current?.drop();
      return api.forgetParts();
    });

  if (plan === undefined || (plan && !view)) return <p className="tom">{message || "Hämtar stationen …"}</p>;
  if (!plan?.panel || !view) {
    return (
      <div className="tom-sida">
        <p>{message || "Stationen har ingen spårplan att dela. Importera eller rita stationen först, i Spårplan eller Rita."}</p>
      </div>
    );
  }
  return (
    <DelaVy
      plan={plan}
      view={view}
      parts={parts}
      chosen={chosen}
      tool={tool}
      side={side}
      marked={marked}
      saving={saving}
      busy={busy}
      message={message}
      problems={problems}
      onChoose={setChosen}
      onTool={setTool}
      onSide={setSide}
      onMark={setMarked}
      onChange={change}
      onUse={() => void use()}
      onForget={() => void forget()}
    />
  );
}

export const USED = "Delarna är stationsmodellens. Ställverket kör dem, och utsidan listar delarna som är egna driftplatser.";

type VyProps = {
  plan: TrackPlan;
  view: Dela;
  parts: StationPart[];
  chosen: string | null;
  tool: Tool;
  side: PartSide;
  marked: Marked;
  saving: boolean;
  busy: boolean;
  message: string;
  problems: string[];
  onChoose: (id: string | null) => void;
  onTool: (tool: Tool) => void;
  onSide: (side: PartSide) => void;
  onMark: (marked: Marked) => void;
  onChange: (parts: StationPart[]) => void;
  onUse: () => void;
  onForget: () => void;
};

/** The page with its state from DelaStationen: the parts, the panel, the lists and the checks. */
export function DelaVy({ plan, view, parts, chosen, tool, side, marked, saving, busy, message, problems, onChoose, onTool, onSide, onMark, onChange, onUse, onForget }: VyProps) {
  const panel = plan.panel as Panel;
  const sections = view.sections ?? {};
  const part = parts.find((p) => p.id === chosen) ?? null;
  const found = (view.found ?? []).find((f) => f.part === chosen) ?? null;
  const { list, problems: blocking } = checkList(view.checks);
  const draft = view.state === "draft";
  const edit = (change: (p: StationPart) => StationPart) => {
    if (part) onChange(changePart(parts, part.id, change));
  };
  const add = () => {
    const made = newPart(parts);
    onChange([...parts, made]);
    onChoose(made.id);
    onTool("area");
  };
  const show = (check: DelaCheck) => {
    if (check.part) onChoose(check.part);
    onMark(markOf(check));
  };
  const hint = TOOLS.find((t) => t.tool === tool)?.hint ?? "";
  return (
    <div className="dela">
      <div className="sidrubrik">
        <h1>Dela stationen</h1>
        <p className="liten">
          Dela stationen i delställverk: ett fast område med en egen operatör, mot stationens enda ställverk (TKL97). Rita delens område på panelen, ange gränsväxlarna och vem som äger dem, reglerna vid gränsen, växelgatorna och vägarna ut. En del som bemannas för sig blir egen driftplats i Hubben (TKL101).
        </p>
      </div>
      <div className="rad dela-status">
        <span className={`chip ${draft ? "" : "gron"}`}>{STATES[view.state] ?? view.state}</span>
        <span className="liten">{saving ? "Sparar …" : blocking ? `${blocking} problem att rätta före Använd` : draft ? "Inga problem: delarna kan användas." : ""}</span>
        <span className="tm-fyll" />
        <button type="button" className="lank" disabled={busy || !draft} onClick={onForget}>
          Släng utkastet
        </button>
        <button type="button" className="primar" disabled={busy || saving || !draft || blocking > 0} onClick={onUse}>
          Använd
        </button>
      </div>
      {message ? (
        <div className={problems.length ? "fel" : "notis"} role="alert">
          <p>{message}</p>
          {problems.length ? (
            <ul>
              {problems.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
      <nav className="spar-val dela-delar" aria-label="Delar">
        {parts.map((p) => (
          <button key={p.id} type="button" aria-pressed={p.id === chosen} onClick={() => onChoose(p.id)}>
            {p.name || p.id}
          </button>
        ))}
        <button type="button" onClick={add}>
          + Ny del
        </button>
      </nav>
      {part ? (
        <div className="dela-yta">
          <section className="ruta dela-panel-ruta" aria-label="Panelen">
            <div className="rad">
              <nav className="spar-val" aria-label="Verktyg">
                {TOOLS.map((t) => (
                  <button key={t.tool} type="button" aria-pressed={tool === t.tool} onClick={() => onTool(t.tool)}>
                    {t.label}
                  </button>
                ))}
              </nav>
            </div>
            <p className="liten">{hint}</p>
            <DelaPanel
              panel={panel}
              part={part}
              parts={parts}
              found={found}
              sections={sections}
              tool={tool}
              marked={marked}
              onPiece={(piece) => edit((p) => clickPiece(p, piece, sections))}
              onSwitch={(number) => edit((p) => clickSwitch(p, number, tool, found))}
              onSignal={(name) => edit((p) => clickSignal(p, name, tool))}
            />
            <p className="liten forklaring">
              <span className="farg dela-omrade" /> Området <span className="farg dela-annan" /> En annan del <span className="farg dela-grans" /> Gränsen · ring = gränsväxel, fylld = egen växel
            </p>
          </section>
          <div className="dela-listor">
            <DelForm
              part={part}
              parts={parts}
              onPart={(next) => {
                onChange(changePart(parts, part.id, () => next));
                if (next.id !== part.id) onChoose(next.id);
              }}
              onRemove={() => {
              onChange(parts.filter((p) => p.id !== part.id));
              onChoose(parts.find((p) => p.id !== part.id)?.id ?? null);
            }} />
            <Gransvaxlar part={part} found={found} marked={marked} onEdit={edit} />
            <Regler part={part} onEdit={edit} />
            <div className="spar-val dela-ande" role="group" aria-label="Ände">
              {SIDES.map(([id, name]) => (
                <button key={id} type="button" aria-pressed={side === id} onClick={() => onSide(id)}>
                  {name}
                </button>
              ))}
            </div>
            <Gator part={part} found={found} side={side} marked={marked} onEdit={edit} />
            <VagarUt part={part} found={found} side={side} marked={marked} onEdit={edit} />
          </div>
        </div>
      ) : (
        <p className="tom">Stationen har inga delar. Tryck Ny del för att dela den.</p>
      )}
      <Kontroller list={list} parts={parts} onShow={show} />
    </div>
  );
}

const press = (work: () => void) => (event: KeyboardEvent) => {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    work();
  }
};

type PanelProps = {
  panel: Panel;
  part: StationPart;
  parts: StationPart[];
  found: DelaFound | null;
  sections: Record<string, string[]>;
  tool: Tool;
  marked: Marked;
  onPiece: (piece: string) => void;
  onSwitch: (number: string) => void;
  onSignal: (name: string) => void;
};

/** The station's panel with the part's area tinted, the other parts' fainter, the border where
 * the area meets the rest, and the part's switches and signals. What the tool clicks is a
 * button. */
export function DelaPanel({ panel, part, parts, found, sections, tool, marked, onPiece, onSwitch, onSignal }: PanelProps) {
  const [dx, dy] = panel.cell;
  const u = Math.min(dx, dy);
  const box = viewBox(panel, "schematic", null);
  const mine = inArea(part, sections);
  const others = new Set<string>();
  for (const other of parts) if (other.id !== part.id) for (const piece of inArea(other, sections).pieces) others.add(piece);
  const nodes = new Map((panel.nodes ?? []).map((n) => [n.id, n.cell] as const));
  const border = new Map((part.border ?? []).map((b) => [b.switch, b] as const));
  const borderSignals = new Set(part.border_signals ?? []);
  const scale: [number, number] = [dx, dy];
  const pieceButton = tool === "area";
  const switchButton = tool === "switches" || tool === "border";
  const signalButton = tool === "signals" || tool === "border_signals";
  const isMarked = (kind: string, id: string) => marked?.kind === kind && marked.id === id;
  return (
    <div className="panel-ram">
      <svg className="panel schematisk dela-svg" viewBox={`${round(box.x)} ${round(box.y)} ${round(box.width)} ${round(box.height)}`} role="group" aria-label={`${part.name}s område på panelen`} preserveAspectRatio="xMidYMid meet">
        <rect x={box.x} y={box.y} width={box.width} height={box.height} className="botten" />
        <g className="spar" strokeWidth={0.16 * u}>
          {panel.lines.map((line) => {
            const kind = mine.piece(line.piece) ? "dela-i" : others.has(line.piece) ? "dela-annan" : "";
            const click = () => onPiece(line.piece);
            return (
              <polyline
                key={line.piece}
                data-piece={line.piece}
                data-area={mine.piece(line.piece) ? "ja" : undefined}
                className={`${kind}${isMarked("piece", line.piece) ? " dela-markerad" : ""}`}
                points={points(line.cells, scale)}
                strokeWidth={round((mine.piece(line.piece) ? 0.34 : 0.16) * u)}
                {...(pieceButton ? { role: "button", tabIndex: 0, "aria-label": `Spårbit ${line.piece}`, onClick: click, onKeyDown: press(click), style: { cursor: "pointer" } } : {})}
              />
            );
          })}
        </g>
        <g className="dela-texter">
          {(panel.labels ?? []).map((l) => (
            <text key={`${l.kind}${l.text}`} x={round(l.cell[0] * dx)} y={round(l.cell[1] * dy)} textAnchor={l.anchor ?? "middle"} fontSize={round(0.42 * u)}>
              {l.text}
            </text>
          ))}
          {(panel.track_names ?? []).map((t) => (
            <text key={t.name} className="spar-namn" x={round(t.cell[0] * dx)} y={round(t.cell[1] * dy)} textAnchor="end" fontSize={round(0.42 * u)}>
              {t.name}
            </text>
          ))}
        </g>
        <g className="dela-kanter">
          {(found?.edge ?? []).map((node) => {
            const at = nodes.get(node);
            return at ? <circle key={node} data-edge={node} cx={round(at[0] * dx)} cy={round(at[1] * dy)} r={round(0.3 * u)} /> : null;
          })}
        </g>
        <g className="dela-vaxlar">
          {(panel.switches ?? []).map((s) => {
            const own = mine.switch(s.number);
            const at = border.get(s.number);
            const click = () => onSwitch(s.number);
            const said = at ? `gränsväxel, ${at.owner === "part" ? "delens" : "stationens"}, mot delen ${at.towards_part}` : own ? "delens egen" : "";
            return (
              <g
                key={s.node}
                data-switch={s.number}
                data-own={own ? "ja" : undefined}
                data-border={at ? at.owner ?? "station" : undefined}
                className={isMarked("switch", s.number) ? "dela-markerad" : undefined}
                {...(switchButton ? { role: "button", tabIndex: 0, "aria-label": `Växel ${s.number}`, onClick: click, onKeyDown: press(click), style: { cursor: "pointer" } } : {})}
              >
                <title>{`Växel ${s.number}${said ? ` · ${said}` : ""}`}</title>
                <circle cx={round(s.cell[0] * dx)} cy={round(s.cell[1] * dy)} r={round(0.42 * u)} className={at ? "grans" : own ? "egen" : "vaxel"} strokeWidth={round(0.1 * u)} />
                <text x={round(s.label[0] * dx)} y={round(s.label[1] * dy)} textAnchor="middle" fontSize={round(0.42 * u)}>
                  {s.number}
                </text>
              </g>
            );
          })}
        </g>
        <g className="dela-signaler">
          {(panel.signals ?? []).map((s) => {
            const inside = mine.signal(s.name);
            const atBorder = borderSignals.has(s.name);
            const click = () => onSignal(s.name);
            return (
              <g
                key={s.name}
                data-signal={s.name}
                data-inside={inside ? "ja" : undefined}
                data-border={atBorder ? "ja" : undefined}
                className={isMarked("signal", s.name) ? "dela-markerad" : undefined}
                {...(signalButton ? { role: "button", tabIndex: 0, "aria-label": `Signal ${s.name}`, onClick: click, onKeyDown: press(click), style: { cursor: "pointer" } } : {})}
              >
                <title>{`Signal ${s.name}${atBorder ? " · vid gränsen" : inside ? " · i området" : ""}`}</title>
                <circle cx={round(s.symbol[0] * dx)} cy={round(s.symbol[1] * dy)} r={round(0.3 * u)} className={atBorder ? "grans" : inside ? "egen" : "signal"} strokeWidth={round(0.08 * u)} />
                <text x={round(s.label[0] * dx)} y={round(s.label[1] * dy)} textAnchor="middle" fontSize={round(0.36 * u)}>
                  {s.name}
                </text>
              </g>
            );
          })}
        </g>
      </svg>
    </div>
  );
}

function DelForm({ part, parts, onPart, onRemove }: { part: StationPart; parts: StationPart[]; onPart: (part: StationPart) => void; onRemove: () => void }) {
  const idWrong = !validId(part.id) || parts.filter((p) => p.id === part.id).length > 1;
  return (
    <section className="ruta dela-del" aria-label="Delen">
      <h2>Delen</h2>
      <label>
        Namn
        <input aria-label="Delens namn" value={part.name} onChange={(e) => onPart(renamed(part, e.target.value, parts))} />
      </label>
      <label>
        Id
        <input aria-label="Delens id" className="tm-mono" value={part.id} aria-invalid={idWrong} onChange={(e) => onPart({ ...part, id: e.target.value.trim() })} />
      </label>
      <p className="liten">Delens skärm öppnas på /del/{part.id}, bakom samma PIN som TKL.</p>
      <label className="kryss">
        <input type="checkbox" checked={!!part.own_place} onChange={(e) => onPart({ ...part, own_place: e.target.checked })} />
        Egen driftplats i Hubben, bemannas för sig (TKL101)
      </label>
      {part.own_place ? (
        <label>
          Signatur
          <input aria-label="Driftplatsens signatur" className="tm-mono kort-falt" value={part.code ?? ""} placeholder={part.name} onChange={(e) => onPart({ ...part, code: e.target.value || null })} />
        </label>
      ) : (
        <p className="liten">Delen syns inte i Hubben: samma person kör den och stationen.</p>
      )}
      <button type="button" className="lank" onClick={onRemove}>
        Ta bort delen
      </button>
    </section>
  );
}

type ListProps = { part: StationPart; found: DelaFound | null; marked?: Marked; onEdit: (change: (p: StationPart) => StationPart) => void };

function Gransvaxlar({ part, found, marked, onEdit }: ListProps) {
  const border = part.border ?? [];
  const missing = (found?.border_switches ?? []).filter((b) => !border.some((m) => m.switch === b.switch));
  return (
    <section className="ruta" aria-label="Gränsväxlar">
      <h2>Gränsväxlar</h2>
      {border.length ? (
        <table>
          <thead>
            <tr>
              <th>Växel</th>
              <th>Ägare</th>
              <th>Mot delen</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {border.map((b) => (
              <tr key={b.switch} data-border-row={b.switch} className={marked?.kind === "switch" && marked.id === b.switch ? "dela-markerad" : undefined}>
                <td className="tm-mono">{b.switch}</td>
                <td>
                  <select aria-label={`Ägare för ${b.switch}`} value={b.owner ?? "station"} onChange={(e) => onEdit((p) => setBorder(p, b.switch, { owner: e.target.value as BorderOwner }))}>
                    <option value="station">Stationen</option>
                    <option value="part">Delen</option>
                  </select>
                </td>
                <td>
                  <select aria-label={`Läge mot delen för ${b.switch}`} value={b.towards_part} onChange={(e) => onEdit((p) => setBorder(p, b.switch, { towards_part: e.target.value as "+" | "-" }))}>
                    <option value="+">+ rakt</option>
                    <option value="-">− avvikande</option>
                  </select>
                </td>
                <td>
                  <button type="button" className="lank" onClick={() => onEdit((p) => ({ ...p, border: (p.border ?? []).filter((m) => m.switch !== b.switch) }))}>
                    Ta bort
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="tom">Inga gränsväxlar.</p>
      )}
      {missing.length ? (
        <p className="liten">
          Vid gränsen:{" "}
          {missing.map((b) => (
            <button key={b.switch} type="button" className="lank" onClick={() => onEdit((p) => ({ ...p, border: [...(p.border ?? []), b] }))}>
              + {b.switch} ({b.towards_part} mot delen)
            </button>
          ))}
        </p>
      ) : null}
    </section>
  );
}

type BorderOwner = "station" | "part";

function Regler({ part, onEdit }: Omit<ListProps, "found">) {
  const rules = part.rules ?? { lays_towards_part: true, one_way: true };
  return (
    <section className="ruta" aria-label="Regler">
      <h2>Regler vid gränsen</h2>
      <label className="kryss">
        <input type="checkbox" checked={rules.lays_towards_part ?? true} onChange={(e) => onEdit((p) => ({ ...p, rules: { ...rules, lays_towards_part: e.target.checked } }))} />
        Delen får lägga stationens gränsväxlar mot sitt område, aldrig ut (RANG-12)
      </label>
      <label className="kryss">
        <input type="checkbox" checked={rules.one_way ?? true} onChange={(e) => onEdit((p) => ({ ...p, rules: { ...rules, one_way: e.target.checked } }))} />
        Envägsregeln: en godkänd väg kan bara delen lämna tillbaka (RANG-09)
      </label>
    </section>
  );
}

const positionsText = (positions: Record<string, string>) =>
  Object.entries(positions)
    .map(([k, v]) => `${k}${v === "-" ? "−" : v}`)
    .join(" ");

function Gator({ part, found, side, marked, onEdit }: ListProps & { side: PartSide }) {
  const offered = streetsAt(found, part, side);
  const streets = part.streets ?? [];
  return (
    <section className="ruta" aria-label="Växelgator">
      <h2>Växelgator</h2>
      <p className="liten">Välj ände och spår. TKL räknar fram växlarna ur spårplanen; namnge gatan som knappen ska säga den.</p>
      <div className="dela-erbjudna">
        {offered.length ? (
          offered.map((s: SwitchStreet) => (
            <button key={`${s.side}${s.track}`} type="button" data-offer-street={s.track} title={positionsText(s.positions)} onClick={() => onEdit((p) => addStreet(p, s))}>
              + {s.track}
            </button>
          ))
        ) : (
          <span className="liten">Inga fler spår att nå från den änden.</span>
        )}
      </div>
      {streets.length ? (
        <ul className="dela-lista">
          {streets.map((s) => (
            <li key={s.id} data-street={s.id} className={marked?.kind === "street" && marked.id === s.id ? "dela-markerad" : undefined}>
              <input aria-label={`Namn på gatan ${s.id}`} value={s.name} onChange={(e) => onEdit((p) => renameStreet(p, s.id, e.target.value))} />
              <span className="liten">
                {s.side === "left" ? "vänster" : s.side === "right" ? "höger" : ""} → {s.track} · <span className="tm-mono">{positionsText(s.positions)}</span>
              </span>
              <button type="button" className="lank" onClick={() => onEdit((p) => removeStreet(p, s.id))}>
                Ta bort
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

function VagarUt({ part, found, side, marked, onEdit }: ListProps & { side: PartSide }) {
  const offered = routesOutAt(found, side);
  const chosen = part.routes_out ?? [];
  return (
    <section className="ruta" aria-label="Vägar ut">
      <h2>Vägar ut</h2>
      <p className="liten">Stationens växlingsvägar som börjar i området och lämnar det. Delen begär dem, och stationen lägger dem (RANG-03).</p>
      <ul className="dela-lista dela-erbjudna-vagar">
        {offered.map((r: RouteOut) => (
          <li key={`${r.start}|${r.end}`}>
            <label className="kryss">
              <input type="checkbox" data-offer-route={`${r.start}|${r.end}`} checked={hasRouteOut(part, r)} onChange={() => onEdit((p) => toggleRouteOut(p, r))} />
              <span className="tm-mono">
                {r.start} → {r.end}
              </span>
              <span className="liten">spår {r.track}</span>
            </label>
          </li>
        ))}
        {offered.length ? null : <li className="liten">Inga vägar lämnar området åt det hållet.</li>}
      </ul>
      {chosen.length ? (
        <ul className="dela-lista">
          {chosen.map((r) => (
            <li key={r.id} data-route-out={r.id} className={marked?.kind === "route_out" && marked.id === r.id ? "dela-markerad" : undefined}>
              <input aria-label={`Namn på vägen ut ${r.id}`} value={r.name} onChange={(e) => onEdit((p) => renameRouteOut(p, r.id, e.target.value))} />
              <span className="liten tm-mono">
                {r.start} → {r.end}
              </span>
              <button type="button" className="lank" onClick={() => onEdit((p) => toggleRouteOut(p, r))}>
                Ta bort
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

function Kontroller({ list, parts, onShow }: { list: DelaCheck[]; parts: StationPart[]; onShow: (check: DelaCheck) => void }): ReactNode {
  const name = (id: string | null | undefined) => parts.find((p) => p.id === id)?.name ?? id ?? "";
  return (
    <section className="kolumn dela-kontroller" aria-label="Kontroller">
      <h2>Kontroller</h2>
      {list.length ? (
        <ul className="dela-lista">
          {list.map((c, i) => (
            <li key={`${c.text}${i}`}>
              <button type="button" className={`dela-kontroll ${c.problem ?? true ? "problem" : "not"}`} data-check={c.kind ? `${c.kind}:${c.id ?? ""}` : undefined} onClick={() => onShow(c)}>
                {c.problem ?? true ? "Problem" : "Att veta"}
                {c.part ? ` · ${name(c.part)}` : ""}: {c.text}
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="ok">Inga problem: varje gata leder till sitt spår, vägarna ut börjar i området, gränsväxlarna har en ägare och områdena hänger ihop.</p>
      )}
    </section>
  );
}
