// Spårplan i Studio (#83): the station's panel, schematic or soft (STD-12), the checks before it
// may run (problems and notes, STD-04), and the routes the engine derives by kind. Clicking a
// route draws it on the panel in the route's colour; it is only shown, never set (setting routes
// is the interlocking's, #84). A model file is imported here, and the four reference stations
// can be looked at or used as one's own (TKL40). The panel is drawn in SVG in one neutral style
// close to skin 85: black ground (STV-42), grey track, the signal in the track line with its id
// beside it (TKL45). Under the own station's panel, the owner sets Manöver, the free panel with
// the symbols of one of the standard skins, the owner's labels and what is shown (STV-46).
import { useEffect, useRef, useState, type ChangeEvent, type KeyboardEvent } from "react";
import { api, Problem, type Checks, type Panel, type PanelSignal, type Reference, type Route, type TrackPlan } from "./api";
import { ManoverInstallningar } from "./ManoverInstallningar";
import { LEVELS, points, readModelFile, round, routeLines, routeName, routesByKind, SIGNAL_NAMES, viewBox, type Form } from "./sparplan";

const MINE = "";

export function Sparplan({ onChanged }: { onChanged: () => void }) {
  const [own, setOwn] = useState<TrackPlan | null | undefined>(undefined);
  const [references, setReferences] = useState<Reference[]>([]);
  const [shown, setShown] = useState<string>(MINE);
  const [looked, setLooked] = useState<Record<string, TrackPlan>>({});
  const [message, setMessage] = useState("");
  const [problems, setProblems] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const file = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api.stationModel().then(setOwn).catch((error: unknown) => {
      setOwn(null);
      setMessage(error instanceof Error ? error.message : "TKL svarar inte.");
    });
    api.references().then(setReferences).catch(() => setReferences([]));
  }, []);

  const look = async (id: string) => {
    setShown(id);
    setMessage("");
    setProblems([]);
    if (id === MINE || looked[id]) return;
    try {
      const found = await api.reference(id);
      setLooked((before) => ({ ...before, [id]: found }));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Det gick inte att hämta referensstationen.");
    }
  };

  const take = async (work: () => Promise<TrackPlan>) => {
    setBusy(true);
    setMessage("");
    setProblems([]);
    try {
      setOwn(await work());
      setShown(MINE);
      onChanged();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Det gick inte.");
      setProblems(error instanceof Problem ? error.problems : []);
    } finally {
      setBusy(false);
    }
  };

  const importFile = async (event: ChangeEvent<HTMLInputElement>) => {
    const chosen = event.target.files?.[0];
    event.target.value = "";
    if (!chosen) return;
    const read = readModelFile(await chosen.text());
    if ("error" in read) {
      setMessage(read.error);
      setProblems([]);
      return;
    }
    await take(() => api.importModel(read.text));
  };

  const forget = async () => {
    setBusy(true);
    try {
      await api.forgetModel();
      setOwn(null);
      onChanged();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Det gick inte.");
    } finally {
      setBusy(false);
    }
  };

  const reference = references.find((r) => r.id === shown) ?? null;
  const plan = shown === MINE ? own : looked[shown];
  return (
    <div className="sparplan">
      <div className="sidrubrik">
        <h1>Spårplan</h1>
        <p className="liten">
          Stationens modell som en panel: motorn lägger ut den på rutnätet, eller så byggs den ur stationens egen spårplan. Kontrollerna säger om modellen får köras. Vägarna räknas fram och visas här, de läggs inte.
        </p>
      </div>
      <div className="rad val-rad">
        <nav className="spar-val" aria-label="Station att visa">
          <button type="button" aria-pressed={shown === MINE} onClick={() => void look(MINE)}>
            Min station
          </button>
          {references.map((r) => (
            <button key={r.id} type="button" aria-pressed={shown === r.id} onClick={() => void look(r.id)}>
              {r.name}
            </button>
          ))}
        </nav>
        <span className="tm-fyll" />
        <input ref={file} type="file" accept=".json,application/json" hidden aria-label="Stationsmodell att importera" onChange={(e) => void importFile(e)} />
        <button type="button" disabled={busy} onClick={() => file.current?.click()}>
          Importera stationsmodell …
        </button>
        {shown === MINE && own ? (
          <button type="button" className="lank" disabled={busy} onClick={() => void forget()}>
            Ta bort modellen (nivå 0)
          </button>
        ) : null}
        {reference ? (
          <button type="button" className="primar" disabled={busy} onClick={() => void take(() => api.useReference(reference.id))}>
            Använd som min station
          </button>
        ) : null}
      </div>
      {message ? (
        <div className="fel" role="alert">
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
      {plan === undefined ? (
        <p className="tom">Hämtar …</p>
      ) : plan === null ? (
        <div className="tom-sida">
          <p>Stationen har ingen stationsmodell än. Importera en fil, eller titta på en referensstation och använd den som din.</p>
        </div>
      ) : (
        <TrackPlanView key={shown} plan={plan} reference={reference} />
      )}
    </div>
  );
}

/** One station's Spårplan: the summary, the panel with its view and fields, the checks and the
 * routes. Holds which route is shown and in which view. */
export function TrackPlanView({ plan, reference, form: startForm = "schematic", route: startRoute = null }: { plan: TrackPlan; reference: Reference | null; form?: Form; route?: Route | null }) {
  const [form, setForm] = useState<Form>(startForm);
  const [route, setRoute] = useState<Route | null>(startRoute);
  const [field, setField] = useState<number | null>(null);
  const summary = plan.summary;
  const panel = plan.panel;
  const fields = panel?.fields ?? [];
  return (
    <>
      <section className="ruta">
        <p className="overrad">{reference ? "Referensstation · bara att titta på" : "Min station"}</p>
        <h2>
          {summary.name} <span className="chip">{LEVELS[summary.level] ?? `Nivå ${summary.level}`}</span>
        </h2>
        <p className="liten">
          {summary.switches} växlar{summary.levers ? ` (${summary.levers} spakar med kopplade växlar)` : ""} · {summary.signals} signaler · {summary.track_circuits} spårledningar · {summary.pieces} spårbitar
          {summary.turntables ? ` · ${summary.turntables} vändskiva` : ""} · stationsspår {(summary.station_tracks ?? []).join(", ") || "inga"} · linjeutfarter{" "}
          {(summary.line_exits ?? []).join(", ") || "inga"}
        </p>
        {panel ? (
          <p className="liten">
            {panel.source === "plan"
              ? `Panelen byggs ur stationens egen spårplan, ${panel.width} × ${panel.height} rutor.`
              : `Motorns förslag: ${panel.width} × ${panel.height} rutor, ${panel.rows} rader, ${panel.angle === "45" ? "45°" : "flackt 1:2"}${panel.shortened ? ", stationsspåren kortade" : ""}.`}
          </p>
        ) : null}
      </section>
      {panel ? (
        <section className="ruta panel-ruta">
          <div className="rad">
            <nav className="spar-val" aria-label="Vy">
              <button type="button" aria-pressed={form === "schematic"} onClick={() => setForm("schematic")}>
                Schematisk
              </button>
              <button type="button" aria-pressed={form === "soft"} disabled={!panel.real_box} onClick={() => setForm("soft")}>
                Mjuk
              </button>
            </nav>
            {fields.length && form === "schematic" ? (
              <nav className="spar-val" aria-label="Fält">
                <button type="button" aria-pressed={field === null} onClick={() => setField(null)}>
                  Hela stationen
                </button>
                {fields.map((f, i) => (
                  <button key={f.name} type="button" aria-pressed={field === i} onClick={() => setField(i)}>
                    {f.name}
                  </button>
                ))}
              </nav>
            ) : null}
            <span className="tm-fyll" />
            {route ? (
              <span className="liten">
                {route.kind === "train" ? "Tågväg" : "Växlingsväg"} {routeName(route)}{" "}
                <button type="button" className="lank" onClick={() => setRoute(null)}>
                  Släck
                </button>
              </span>
            ) : (
              <span className="liten">Klicka på en väg nedanför för att se den.</span>
            )}
          </div>
          <PanelView panel={panel} form={form} route={route} field={field} />
          <p className="liten forklaring">
            <span className="farg ledigt" /> Spår <span className="farg tagvag" /> Tågväg <span className="farg vaxling" /> Växlingsväg · Huvudsignal triangel, dvärgsignal fylld pil, rött = slutpunktsstopplykta · blek = planerad
          </p>
        </section>
      ) : (
        <p className="tom">Panelen går inte att göra förrän problemen är rättade.</p>
      )}
      {panel && !reference ? <ManoverInstallningar key={`${summary.station_id}|${summary.pieces}|${summary.signals}|${summary.plan}`} panel={panel} /> : null}
      <div className="kolumner sparplan-kolumner">
        <ChecksView checks={plan.checks} />
        <RoutesView routes={plan.route_list ?? []} counts={plan.routes} chosen={route} onChoose={setRoute} />
      </div>
    </>
  );
}

export function ChecksView({ checks }: { checks: Checks }) {
  const problems = checks.problems ?? [];
  const notes = checks.notes ?? [];
  return (
    <section className="kolumn" aria-label="Kontroller">
      <h2>Kontroller</h2>
      {problems.length ? (
        <>
          <h3>Problem · stoppar körningen</h3>
          <ul className="problem">
            {problems.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        </>
      ) : (
        <p className="ok">Inga problem: modellen får köras.</p>
      )}
      {notes.length ? (
        <>
          <h3>Att veta · stoppar inte</h3>
          <ul className="noter">
            {notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        </>
      ) : null}
    </section>
  );
}

export function RoutesView({ routes, counts, chosen, onChoose }: { routes: Route[]; counts: Record<string, number>; chosen: Route | null; onChoose: (route: Route | null) => void }) {
  const { train, shunting } = routesByKind(routes);
  const list = (title: string, found: Route[], count: number) => (
    <div className="vagar">
      <h3>
        {title} ({count})
      </h3>
      {found.length ? (
        <div className="vag-knappar">
          {found.map((r) => {
            const on = chosen?.kind === r.kind && chosen.start === r.start && chosen.end === r.end;
            return (
              <button key={`${r.kind}|${r.start}|${r.end}`} type="button" className={`vag ${r.kind}`} aria-pressed={on} onClick={() => onChoose(on ? null : r)}>
                {routeName(r)}
              </button>
            );
          })}
        </div>
      ) : (
        <p className="tom">Inga.</p>
      )}
    </div>
  );
  return (
    <section className="kolumn" aria-label="Vägar">
      <h2>Vägar</h2>
      <p className="liten">Räknade av motorn ur modellen. Klicka för att se en väg på panelen; den läggs inte.</p>
      {list("Tågvägar", train, counts.train ?? train.length)}
      {list("Växlingsvägar", shunting, counts.shunting ?? shunting.length)}
    </section>
  );
}

/** The panel in SVG: schematic on the grid, or soft in the drawing's real shape. With `onSignal`
 * its signals are buttons, as the miniature in Studio › Inställningar › Stream Deck has them
 * (SD42); `marked` signals get a ring. */
export function PanelView({ panel, form, route, field = null, onSignal, marked = [] }: { panel: Panel; form: Form; route: Route | null; field?: number | null; onSignal?: (name: string) => void; marked?: string[] }) {
  const box = viewBox(panel, form, field);
  const lit = routeLines(panel, route);
  const colour = route?.kind === "shunting" ? "vaxling" : "tagvag";
  const soft = form === "soft" && !!panel.real_box;
  return (
    <div className="panel-ram">
      <svg
        className={`panel ${soft ? "mjuk" : "schematisk"}`}
        viewBox={`${round(box.x)} ${round(box.y)} ${round(box.width)} ${round(box.height)}`}
        role="img"
        aria-label={soft ? "Stationen i verklig form" : "Stationen på rutnätet"}
        preserveAspectRatio="xMidYMid meet"
      >
        <rect x={box.x} y={box.y} width={box.width} height={box.height} className="botten" />
        {soft ? <Soft panel={panel} lit={lit} colour={colour} /> : <Schematic panel={panel} lit={lit} colour={colour} onSignal={onSignal} marked={marked} />}
      </svg>
    </div>
  );
}

type Drawn = { panel: Panel; lit: Panel["lines"]; colour: string; onSignal?: (name: string) => void; marked?: string[] };

function Schematic({ panel, lit, colour, onSignal, marked = [] }: Drawn) {
  const [dx, dy] = panel.cell;
  const u = Math.min(dx, dy);
  const scale: [number, number] = [dx, dy];
  const text = 0.42 * u;
  return (
    <g style={{ fontSize: text }}>
      {(panel.platforms ?? []).map(([x1, y1, x2, y2], i) => (
        <rect key={`p${i}`} className="perrong" x={x1 * dx} y={y1 * dy} width={(x2 - x1) * dx} height={(y2 - y1) * dy} />
      ))}
      {panel.building ? (
        <g className="hus">
          <rect x={panel.building.cells[0] * dx} y={panel.building.cells[1] * dy} width={(panel.building.cells[2] - panel.building.cells[0]) * dx} height={(panel.building.cells[3] - panel.building.cells[1]) * dy} />
          <text x={((panel.building.cells[0] + panel.building.cells[2]) / 2) * dx} y={((panel.building.cells[1] + panel.building.cells[3]) / 2) * dy + text * 0.35} textAnchor="middle">
            {panel.building.name}
          </text>
        </g>
      ) : null}
      <g className="spar" strokeWidth={0.16 * u}>
        {panel.lines.map((line) => (
          <polyline key={line.piece} data-piece={line.piece} points={points(line.cells, scale)} />
        ))}
      </g>
      <g className={`vag-linje ${colour}`} strokeWidth={0.2 * u}>
        {lit.map((line) => (
          <polyline key={line.piece} data-piece={line.piece} points={points(line.cells, scale)} />
        ))}
      </g>
      {(panel.nodes ?? [])
        .filter((n) => n.type === "block_boundary")
        .map((n) => (
          <line key={n.id} className="blockgrans" x1={n.cell[0] * dx} y1={n.cell[1] * dy - 0.18 * u} x2={n.cell[0] * dx} y2={n.cell[1] * dy + 0.18 * u} strokeWidth={0.06 * u} />
        ))}
      {(panel.tables ?? []).map((t) => (
        <circle key={t.id} className="skiva" cx={t.cell[0] * dx} cy={t.cell[1] * dy} r={t.radius * dx} strokeWidth={0.08 * u} />
      ))}
      <g className="vaxelnummer">
        {(panel.switches ?? []).map((s) => (
          <text key={s.node} x={s.label[0] * dx} y={s.label[1] * dy} textAnchor="middle" opacity={s.laid ? 1 : 0.55}>
            {s.number}
          </text>
        ))}
      </g>
      {(panel.signals ?? []).map((s) => (
        <Signal key={s.name} signal={s} at={[s.symbol[0] * dx, s.symbol[1] * dy]} toward={s.toward} size={0.5 * u} label={[s.label[0] * dx, s.label[1] * dy]} onClick={onSignal} marked={marked.includes(s.name)} />
      ))}
      {(panel.labels ?? []).map((l) => (
        <text key={`${l.kind}${l.text}`} className={l.kind === "exit" ? "utfart" : "punkt"} x={l.cell[0] * dx} y={l.cell[1] * dy} textAnchor={l.anchor ?? "middle"}>
          {l.text}
        </text>
      ))}
      {(panel.track_names ?? []).map((t) => (
        <g key={t.name} className="spar-namn">
          <text x={t.cell[0] * dx} y={t.cell[1] * dy} textAnchor="end">
            {t.name}
          </text>
          <rect className="tagnummer" x={t.train_number[0] * dx} y={t.train_number[1] * dy} width={3 * u} height={0.75 * u} rx={0.1 * u} />
        </g>
      ))}
    </g>
  );
}

function Soft({ panel, lit, colour }: Drawn) {
  const [, , width, height] = panel.real_box ?? [0, 0, 1, 1];
  const u = Math.max(width, height) / 90;
  const line = (cells: [number, number][]) => points(cells);
  return (
    <g style={{ fontSize: 0.7 * u }}>
      <g className="spar" strokeWidth={0.22 * u}>
        {panel.lines.map((l) => ((l.real ?? []).length > 1 ? <polyline key={l.piece} data-piece={l.piece} points={line(l.real ?? [])} /> : null))}
      </g>
      <g className={`vag-linje ${colour}`} strokeWidth={0.3 * u}>
        {lit.map((l) => ((l.real ?? []).length > 1 ? <polyline key={l.piece} data-piece={l.piece} points={line(l.real ?? [])} /> : null))}
      </g>
      {(panel.tables ?? []).map((t) =>
        t.real ? <circle key={t.id} className="skiva" cx={t.real[0]} cy={t.real[1]} r={t.real_radius ?? 2 * u} strokeWidth={0.1 * u} /> : null,
      )}
      <g className="vaxelnummer">
        {(panel.switches ?? []).map((s) =>
          s.real ? (
            <text key={s.node} x={s.real[0]} y={s.real[1] - 0.6 * u} textAnchor="middle" opacity={s.laid ? 1 : 0.55}>
              {s.number}
            </text>
          ) : null,
        )}
      </g>
      {(panel.signals ?? []).map((s) => {
        if (!s.real || !s.real_toward) return null;
        const side = s.side === "over" ? -1 : 1;
        return <Signal key={s.name} signal={s} at={s.real} toward={s.real_toward} size={0.8 * u} label={[s.real[0], s.real[1] + side * 1.1 * u + (side > 0 ? 0.5 * u : 0)]} />;
      })}
      {(panel.labels ?? []).map((l) =>
        l.real ? (
          <text key={`${l.kind}${l.text}`} className={l.kind === "exit" ? "utfart" : "punkt"} x={l.real[0]} y={l.real[1] + 1.2 * u} textAnchor="middle">
            {l.text}
          </text>
        ) : null,
      )}
    </g>
  );
}

/** A signal: its symbol in the track line, pointing the way it applies (TKL45), and its id. */
function Signal({ signal, at, toward, size, label, onClick, marked = false }: { signal: PanelSignal; at: [number, number]; toward: [number, number]; size: number; label: [number, number]; onClick?: (name: string) => void; marked?: boolean }) {
  const [tx, ty] = toward;
  const normal: [number, number] = [-ty, tx];
  const kind = signal.type;
  const small = kind === "dvsi" || kind === "stop_lamp" ? 0.75 : 1;
  const s = size * small;
  const tip: [number, number] = [at[0] + tx * s * 0.55, at[1] + ty * s * 0.55];
  const base: [number, number] = [at[0] - tx * s * 0.45, at[1] - ty * s * 0.45];
  const corners: [number, number][] = [tip, [base[0] + normal[0] * s * 0.45, base[1] + normal[1] * s * 0.45], [base[0] - normal[0] * s * 0.45, base[1] - normal[1] * s * 0.45]];
  const clickable = onClick
    ? {
        role: "button",
        tabIndex: 0,
        "aria-label": `Signal ${signal.name}`,
        "data-signal": signal.name,
        onClick: () => onClick(signal.name),
        onKeyDown: (e: KeyboardEvent) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            onClick(signal.name);
          }
        },
      }
    : {};
  return (
    <g className={`signal ${kind}${signal.planned ? " planerad" : ""}${onClick ? " valbar" : ""}${marked ? " markerad" : ""}`} {...clickable}>
      <title>{`${SIGNAL_NAMES[kind] ?? kind} ${signal.name}${signal.planned ? " (planerad)" : ""}`}</title>
      {marked ? <circle className="ring" cx={at[0]} cy={at[1]} r={s * 0.75} strokeWidth={s * 0.12} fill="none" /> : null}
      {onClick ? <circle className="traff" cx={at[0]} cy={at[1]} r={s * 0.9} /> : null}
      {kind === "fsi" ? <circle cx={at[0]} cy={at[1]} r={s * 0.32} strokeWidth={s * 0.1} /> : <polygon points={points(corners)} strokeWidth={s * 0.1} />}
      {kind === "hdvsi" ? <line x1={base[0] + normal[0] * s * 0.45} y1={base[1] + normal[1] * s * 0.45} x2={base[0] - normal[0] * s * 0.45} y2={base[1] - normal[1] * s * 0.45} strokeWidth={s * 0.18} /> : null}
      <text x={label[0]} y={label[1]} textAnchor="middle">
        {signal.name}
      </text>
    </g>
  );
}
