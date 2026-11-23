// Studio › Rita (#85 del a): draw the station on the grid, or redraw the panel of the one the
// station has (STUDIO-02, STUDIO-30). Six tools put the objects on the grid as the drawing
// template does: rutnät och 45°, en etikett per block, riktningen sitter i symbolen. Every change
// is saved on the computer as a draft; TKL computes the rest of the model from it, checks it
// (problems and notes, each clickable to its object) and derives the routes, which light up on
// the drawing as in Spårplan (STUDIO-16). Använd ritningen makes the draft the station's model:
// the outside is derived from it, and Ställverket runs it. Undo and redo hold for the session.
import { useCallback, useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { api, Problem, type CadDiff, type Finding, type Position, type Rita as RitaView, type Route, type SignalType, type SwitchControl, type SwitchType, type TrackCircuit, type Upload } from "./api";
import { DiffView, FranCad } from "./FranCad";
import { LaddaUpp } from "./LaddaUpp";
import { wayIn } from "./laddaupp";
import {
  addDrag,
  addTrack,
  assumed,
  bendTrack,
  changed,
  confirm,
  confirmAll,
  drags,
  editor,
  extent,
  flipSignal,
  full,
  geometry,
  isReversed,
  joinTogether,
  litBy,
  looseEnds,
  markStationTrack,
  moveNode,
  ownParts,
  partsOf,
  placeBoundary,
  placeDerailer,
  placeBufferStop,
  placeLineExit,
  placeSignal,
  placeSwitch,
  proposed,
  redo,
  refOf,
  removeAt,
  removeDrag,
  renameCircuit,
  renameDerailer,
  renameExit,
  renameSignal,
  renameStationTrack,
  renameSwitch,
  RitaError,
  setControl,
  setDerailerControl,
  setReversed,
  setSignal,
  setSwitchAddress,
  setSwitchType,
  snapPoint,
  snapStraight,
  straighten,
  swapLegs,
  toDrawing,
  undo,
  unmarkStationTrack,
  type Cell,
  type Editor,
  type Facing,
  type FullDrawing,
  type FullModel,
  type Geometry,
  type Ref,
  type Side,
} from "./rita";
import { RoutesView } from "./Sparplan";
import { SIGNAL_NAMES } from "./sparplan";

export type Tool = "select" | "track" | "switch" | "derailer" | "signal" | "boundary" | "buffer" | "exit";

export const TOOLS: { tool: Tool; label: string; hint: string }[] = [
  { tool: "select", label: "Markera", hint: "Klicka för att välja, dra en växel eller en spårände till en annan ruta, och dra i ett spår för att knäcka det. Skift-klick väljer flera växlar." },
  { tool: "track", label: "Spår", hint: "Dra från ruta till ruta: vågrätt, lodrätt eller i 45°. Ett spår som når ett annat kopplas ihop med en växel eller en korsning." },
  { tool: "switch", label: "Växel", hint: "Klicka på ett spår: växeln får ett avvikande ben åt sidan du valt. Klicka där tre spår möts, eller där två korsar, för att välja typen." },
  { tool: "derailer", label: "Spårspärr", hint: "Klicka på ett spår, mellan två spårbitar. Spårspärren läggs på när den skyddar en väg bredvid och av när en väg går över den." },
  { tool: "signal", label: "Signal", hint: "Klicka på ett spår eller en nod. Signalen gäller åt hållet du valt; spåret tåget kommer på är det på andra sidan." },
  { tool: "boundary", label: "Spårledningsgräns", hint: "Klicka på ett spår: ett blockstreck där en spårledning slutar och nästa börjar." },
  { tool: "buffer", label: "Stoppbock", hint: "Klicka där ett spår slutar." },
  { tool: "exit", label: "Linjeutfart", hint: "Klicka där ett spår lämnar stationen mot linjen." },
];

const SWITCH_TYPES: [SwitchType, string][] = [
  ["ordinary", "Vanlig"],
  ["y", "Y-växel"],
  ["single_slip", "Enkel korsningsväxel"],
  ["double_slip", "Dubbel korsningsväxel"],
];
const SIDE_LABELS: [Side, string][] = [
  ["ne", "↗"],
  ["se", "↘"],
  ["nw", "↖"],
  ["sw", "↙"],
];
const SIGNAL_TYPES: [SignalType, string][] = [
  ["hsi", "Hsi, huvudsignal"],
  ["hdvsi", "Hdvsi, kombinerad"],
  ["dvsi", "Dvsi, dvärgsignal"],
  ["fsi", "Fsi, försignal"],
  ["stop_lamp", "Slutpunktsstopplykta"],
];
const CONTROLS: [SwitchControl, string][] = [
  ["tkl", "TKL lägger den"],
  ["manual", "Manuell, utan adress"],
  ["planned", "Planerad"],
  ["not_laid", "Läggs inte från ställverket"],
];
const STATES: Record<string, string> = { new: "Ny ritning", draft: "Utkast, sparat på datorn", in_use: "Används i Ställverket" };
const LATER = ["AnyRail"];
const SAVE_AFTER_MS = 400;
/** Screen pixels for the smaller side of a cell: the drawing keeps one scale and scrolls. */
const CELL_ON_SCREEN = 30;

type Drag =
  | { kind: "track"; from: Cell; to: Cell }
  | { kind: "node"; node: string; to: Cell; moved: boolean }
  | { kind: "bend"; piece: string; from: Cell; to: Cell; moved: boolean };

export function Rita({ onChanged }: { onChanged: () => void }) {
  const [view, setView] = useState<RitaView | null>(null);
  const [state, setState] = useState<Editor | null>(null);
  const [tool, setTool] = useState<Tool>("select");
  const [switchType, setSwitchType_] = useState<SwitchType>("ordinary");
  const [side, setSide] = useState<Side>("se");
  const [signalType, setSignalType] = useState<SignalType>("hsi");
  const [lamps, setLamps] = useState(2);
  const [facing, setFacing] = useState<Facing>("east");
  const [selected, setSelected] = useState<Ref[]>([]);
  const [route, setRoute] = useState<Route | null>(null);
  const [message, setMessage] = useState("");
  const [problems, setProblems] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);
  const [busy, setBusy] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const sent = useRef(0);
  const pending = useRef<FullDrawing | null>(null);
  const [way, setWay] = useState<Way>("rita");
  const [cadDiff, setCadDiff] = useState<CadDiff | null>(null);
  const [upload, setUpload] = useState<Upload | null>(null);
  const [underlay, setUnderlay] = useState<string | null>(null);
  const online = typeof navigator === "undefined" || navigator.onLine !== false;

  const load = useCallback((found: RitaView) => {
    setView(found);
    setState(editor(full(found.drawing)));
    setSelected([]);
    setRoute(null);
  }, []);

  useEffect(() => {
    api.rita().then(load).catch((error: unknown) => setMessage(error instanceof Error ? error.message : "TKL svarar inte."));
  }, [load]);

  useEffect(() => {
    // Ladda upp ritning: open or grey, with the reason (CAD6).
    api.upload().then(setUpload, () => setUpload(null));
  }, []);

  /** Saves the drawing as it is now; the answer counts only if nothing newer was sent. */
  const save = useCallback(async (drawing: FullDrawing) => {
    const number = ++sent.current;
    pending.current = null;
    setSaving(true);
    try {
      const answer = await api.saveDrawing(toDrawing(drawing));
      if (number === sent.current) setView(answer);
    } catch (error) {
      if (number === sent.current) setMessage(error instanceof Error ? error.message : "Ritningen sparades inte.");
    } finally {
      if (number === sent.current) setSaving(false);
    }
  }, []);

  const later = useCallback(
    (drawing: FullDrawing) => {
      pending.current = drawing;
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => void save(drawing), SAVE_AFTER_MS);
    },
    [save],
  );

  const flush = async () => {
    if (timer.current) clearTimeout(timer.current);
    if (pending.current) await save(pending.current);
  };

  const commit = (next: Editor) => {
    if (!state || next === state) return;
    setState(next);
    later(next.drawing);
  };

  /** One change with a tool: kept, or the reason why not. */
  const act = (change: (d: FullDrawing) => FullDrawing, select?: (d: FullDrawing) => Ref[]) => {
    if (!state) return;
    try {
      const next = change(state.drawing);
      setMessage("");
      commit(changed(state, next));
      if (select) setSelected(select(next));
    } catch (error) {
      if (error instanceof RitaError) setMessage(error.message);
      else throw error;
    }
  };

  const use = async () => {
    setBusy(true);
    setMessage("");
    setProblems([]);
    try {
      await flush();
      const answer = await api.useDrawing();
      setView(answer);
      onChanged();
      setMessage("Ritningen är stationens modell. Ställverket kör den, och utsidan räknas fram ur den.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Det gick inte.");
      setProblems(error instanceof Problem ? error.problems : []);
    } finally {
      setBusy(false);
    }
  };

  const forget = async () => {
    setBusy(true);
    try {
      if (timer.current) clearTimeout(timer.current);
      pending.current = null;
      sent.current++;
      load(await api.forgetDrawing());
      setCadDiff(null);
      setMessage("");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Det gick inte.");
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    const key = (event: KeyboardEvent) => {
      if (!state || (event.target instanceof HTMLElement && /INPUT|SELECT|TEXTAREA/.test(event.target.tagName))) return;
      const mod = event.ctrlKey || event.metaKey;
      if (mod && event.key.toLowerCase() === "z") {
        event.preventDefault();
        commit(event.shiftKey ? redo(state) : undo(state));
      } else if (mod && event.key.toLowerCase() === "y") {
        event.preventDefault();
        commit(redo(state));
      } else if ((event.key === "Delete" || event.key === "Backspace") && selected[0]) {
        event.preventDefault();
        act((d) => removeAt(d, selected[0]!), () => []);
      } else if (event.key === "Escape") setSelected([]);
    };
    addEventListener("keydown", key);
    return () => removeEventListener("keydown", key);
  });

  if (!state || !view) return <p className="tom">{message || "Hämtar ritningen …"}</p>;
  const drawing = state.drawing;
  const findings = view.findings ?? [];
  const blocking = findings.filter((f) => f.problem).length;
  const circuits = view.model.track_circuits ?? [];
  const tip = TOOLS.find((t) => t.tool === tool)?.hint ?? "";
  const entry = wayIn(upload, online);
  const cad = cadWay(entry);
  const unconfirmed = proposed(drawing.model);
  const pick = (ref: Ref | null) => setSelected(ref ? [ref] : []);
  return (
    <div className="rita">
      <div className="sidrubrik">
        <h1>Rita</h1>
        <p className="liten">
          Rita stationen på rutnätet med sju objekt: spår, växel, spårspärr, signal, spårledningsgräns, stoppbock och linjeutfart. Allt annat räknas fram: spårledningarna mellan blockstrecken, vägarna och panelen. Har stationen redan en modell ritar du om dess panel här.
        </p>
      </div>
      <WaysIn way={way} entry={entry} cad={cad} onWay={setWay} />
      {way === "cad" && cad.open ? (
        <FranCad
          onClose={() => setWay("rita")}
          onProposal={(made) => {
            if (timer.current) clearTimeout(timer.current);
            pending.current = null;
            sent.current++;
            load(made.rita);
            setWay("rita");
            setUnderlay(null);
            setCadDiff(made.diff);
            setMessage("Förslaget ur TrainMeet CAD är gult tills du bekräftar det. Motorn har lagt ut panelen; rita om den om du vill.");
          }}
        />
      ) : null}
      {cadDiff && way === "rita" ? <DiffView diff={cadDiff} onClose={() => setCadDiff(null)} /> : null}
      {way === "upload" && entry.open ? (
        <LaddaUpp
          onClose={() => setWay("rita")}
          onProposal={(found, picture) => {
            if (timer.current) clearTimeout(timer.current);
            pending.current = null;
            sent.current++;
            load(found);
            setWay("rita");
            setUnderlay(picture);
            setCadDiff(null);
            setMessage("Förslaget ur ritningen är gult tills du bekräftar det. Motorn har lagt ut panelen; rita om den om du vill.");
          }}
        />
      ) : null}
      <div className="rad rita-status">
        <span className={`chip ${view.state === "in_use" ? "gron" : ""}`}>{STATES[view.state] ?? view.state}</span>
        <span className="liten">{saving ? "Sparar …" : drawing.proposal ? "Motorns förslag: rita om det, så sparas det som stationens spårplan." : ""}</span>
        <span className="tm-fyll" />
        {unconfirmed ? (
          <button type="button" className="gul-knapp" onClick={() => commit(changed(state, confirmAll(drawing)))}>
            Bekräfta förslaget ({unconfirmed})
          </button>
        ) : null}
        <button type="button" disabled={!state.past.length} onClick={() => commit(undo(state))}>
          Ångra
        </button>
        <button type="button" disabled={!state.future.length} onClick={() => commit(redo(state))}>
          Gör om
        </button>
        <button type="button" className="lank" disabled={busy || view.state !== "draft"} onClick={() => void forget()}>
          Släng utkastet
        </button>
        <button type="button" className="primar" disabled={busy || saving || view.state !== "draft" || blocking > 0} onClick={() => void use()}>
          Använd ritningen
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
      <div className="rita-verktyg" role="toolbar" aria-label="Verktyg">
        {TOOLS.map((t) => (
          <button key={t.tool} type="button" aria-pressed={tool === t.tool} onClick={() => setTool(t.tool)}>
            {t.label}
          </button>
        ))}
      </div>
      <div className="rad rita-val">
        {tool === "switch" ? (
          <>
            <label className="rad">
              Typ
              <select aria-label="Växeltyp" value={switchType} onChange={(e) => setSwitchType_(e.target.value as SwitchType)}>
                {SWITCH_TYPES.map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <span className="liten">Avvikande ben</span>
            {SIDE_LABELS.map(([value, label]) => (
              <button key={value} type="button" aria-label={`Avvikande ${label}`} aria-pressed={side === value} onClick={() => setSide(value)}>
                {label}
              </button>
            ))}
          </>
        ) : null}
        {tool === "signal" ? (
          <>
            <label className="rad">
              Typ
              <select aria-label="Signaltyp" value={signalType} onChange={(e) => setSignalType(e.target.value as SignalType)}>
                {SIGNAL_TYPES.map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            {signalType === "hsi" ? (
              <label className="rad">
                Lyktor
                <select aria-label="Lyktor" value={lamps} onChange={(e) => setLamps(Number(e.target.value))}>
                  {[2, 3, 4, 5].map((n) => (
                    <option key={n} value={n}>
                      Hsi {n}
                    </option>
                  ))}
                </select>
              </label>
            ) : null}
            <button type="button" aria-pressed={facing === "east"} onClick={() => setFacing("east")}>
              → österut
            </button>
            <button type="button" aria-pressed={facing === "west"} onClick={() => setFacing("west")}>
              ← västerut
            </button>
          </>
        ) : null}
        <span className="liten">{tip}</span>
      </div>
      <div className="rita-yta">
        <Canvas
          drawing={drawing}
          circuits={circuits}
          selected={selected}
          route={route}
          tool={tool}
          onPick={(refs, add) => setSelected(add ? [...selected.filter((r) => !refs.some((x) => x.kind === r.kind && x.id === r.id)), ...refs] : refs)}
          onTool={(at) => {
            if (tool === "switch") act((d) => placeSwitch(d, at, switchType, side), (d) => switchAt(d.model, at));
            else if (tool === "derailer") {
              let number = "";
              act(
                (d) => {
                  const made = placeDerailer(d, at);
                  number = made.number;
                  return made.drawing;
                },
                () => [{ kind: "derailer", id: number }],
              );
            } else if (tool === "boundary") act((d) => placeBoundary(d, at));
            else if (tool === "buffer") act((d) => placeBufferStop(d, at));
            else if (tool === "exit") {
              let id = "";
              act(
                (d) => {
                  const made = placeLineExit(d, at);
                  id = made.id;
                  return made.drawing;
                },
                () => [{ kind: "exit", id }],
              );
            } else if (tool === "signal") {
              let name = "";
              act(
                (d) => {
                  const made = placeSignal(d, at, signalType, facing, signalType === "hsi" ? lamps : null);
                  name = made.name;
                  return made.drawing;
                },
                () => [{ kind: "signal", id: name }],
              );
            }
          }}
          onDraw={(from, to) => act((d) => addTrack(d, from, to))}
          onMove={(node, to) => act((d) => moveNode(d, node, to))}
          onBend={(piece, from, to) => act((d) => bendTrack(d, piece, from, to))}
        />
        <aside className="rita-sida">
          <Inspector drawing={drawing} circuits={circuits} selected={selected} act={act} pick={pick} />
          <LeversView drawing={drawing} selected={selected} act={act} pick={pick} />
        </aside>
      </div>
      {underlay ? (
        <figure className="ladda-underlag rita-underlag">
          <img src={underlay} alt="Den uppladdade ritningen, uträtad" />
          <figcaption className="liten">
            Underlaget: ritningen som TrainMeet CAD läste den.{" "}
            <button type="button" className="lank" onClick={() => setUnderlay(null)}>
              Dölj
            </button>
          </figcaption>
        </figure>
      ) : null}
      <div className="kolumner sparplan-kolumner">
        <FindingsView findings={findings} onPick={(ref) => pick(ref)} />
        <RoutesView routes={view.route_list ?? []} counts={view.routes} chosen={route} onChoose={setRoute} />
      </div>
    </div>
  );
}

export type Way = "rita" | "upload" | "cad";
type Entry = { open: boolean; reason: string | null };

/** Från CAD is open where Ladda upp ritning is: the same TrainMeet CAD and the same login. */
export function cadWay(entry: Entry): Entry {
  return { open: entry.open, reason: entry.reason ? entry.reason.replace("Ladda upp ritning", "Från CAD") : null };
}

/** The ways in (STUDIO-01): Rita, and Ladda upp ritning and Från CAD when TKL reaches TrainMeet
 * CAD with a login with TrainMeet ID; grey with the reason otherwise, and Rita still works (CAD6). */
export function WaysIn({ way, entry, cad = cadWay(entry), onWay }: { way: Way; entry: Entry; cad?: Entry; onWay: (way: Way) => void }) {
  return (
    <>
      <nav className="rita-vagar" aria-label="Väg in">
        <button type="button" aria-pressed={way === "rita"} onClick={() => onWay("rita")}>
          Rita
        </button>
        <button type="button" aria-pressed={way === "upload"} disabled={!entry.open} title={entry.reason ?? undefined} onClick={() => onWay("upload")}>
          Ladda upp ritning
        </button>
        <button type="button" aria-pressed={way === "cad"} disabled={!cad.open} title={cad.reason ?? undefined} onClick={() => onWay("cad")}>
          Från CAD
        </button>
        {LATER.map((later) => (
          <button key={later} type="button" disabled>
            {later}
            <span className="kommer"> · kommer</span>
          </button>
        ))}
      </nav>
      {!entry.open && entry.reason ? <p className="liten ladda-gra">{entry.reason}</p> : null}
    </>
  );
}

function switchAt(model: FullModel, at: Cell): Ref[] {
  const g = geometry(model);
  for (const s of model.switches) {
    const c = g.cells.get(s.node);
    if (c && Math.abs(c[0] - at[0]) < 1e-3 && Math.abs(c[1] - at[1]) < 1e-3) return [{ kind: "switch", id: s.number }];
  }
  return [];
}

/** The checks: problems first, then what is good to know. A finding about an object selects
 * it in the drawing (RS7). */
export function FindingsView({ findings, onPick }: { findings: Finding[]; onPick: (ref: Ref | null) => void }) {
  const problems = findings.filter((f) => f.problem);
  const notes = findings.filter((f) => !f.problem);
  const item = (f: Finding) => {
    const ref = refOf(f.target);
    return (
      <li key={f.text}>
        {ref ? (
          <button type="button" className="lank" data-target={`${ref.kind}:${ref.id}`} onClick={() => onPick(ref)}>
            {f.text}
          </button>
        ) : (
          f.text
        )}
      </li>
    );
  };
  return (
    <section className="kolumn" aria-label="Kontroller">
      <h2>Kontroller</h2>
      {problems.length ? (
        <>
          <h3>Problem · ritningen kan inte användas än</h3>
          <ul className="problem">{problems.map(item)}</ul>
        </>
      ) : (
        <p className="ok">Inga problem: ritningen kan användas.</p>
      )}
      {notes.length ? (
        <>
          <h3>Att veta · stoppar inte</h3>
          <ul className="noter">{notes.map(item)}</ul>
        </>
      ) : null}
    </section>
  );
}

// --- The drawing on the grid ----------------------------------------------------------------

type CanvasProps = {
  drawing: FullDrawing;
  circuits: TrackCircuit[];
  selected: Ref[];
  route: Route | null;
  tool: Tool;
  onPick?: (refs: Ref[], add: boolean) => void;
  onTool?: (at: Cell) => void;
  onDraw?: (from: Cell, to: Cell) => void;
  onMove?: (node: string, to: Cell) => void;
  onBend?: (piece: string, from: Cell, to: Cell) => void;
};

const refFrom = (text: string | null | undefined): Ref | null => {
  if (!text) return null;
  const at = text.indexOf(":");
  return at > 0 ? (refOf({ kind: text.slice(0, at), id: text.slice(at + 1) }) as Ref | null) : null;
};

/** The drawing in SVG on the grid, in the template's way: black track on paper, the switch's
 * number by its knot, the signal's lamp beside the track pointing the way it applies, a short
 * stroke for a boundary, a thick bar for a buffer stop, the exit's name in a box, one label per
 * track circuit, and a red dot where a track ends in the air (RS7). */
export function Canvas({ drawing, circuits, selected, route, tool, onPick, onTool, onDraw, onMove, onBend }: CanvasProps) {
  const model = drawing.model;
  const { dx, dy } = model.panel.grid;
  const u = Math.min(dx, dy);
  const g = useMemo(() => geometry(model), [model]);
  const box = useMemo(() => extent(model, g), [model, g]);
  const loose = useMemo(() => new Set(looseEnds(model)), [model]);
  const svg = useRef<SVGSVGElement>(null);
  const [drag, setDrag] = useState<Drag | null>(null);
  const lit = new Set(route?.pieces ?? []);
  const chosen = { nodes: new Set<string>(), pieces: new Set<string>() };
  for (const ref of selected) {
    const found = litBy(model, ref, circuits);
    found.nodes.forEach((n) => chosen.nodes.add(n));
    found.pieces.forEach((p) => chosen.pieces.add(p));
  }
  const selectedSignals = new Set(selected.filter((r) => r.kind === "signal").map((r) => r.id));
  const cellOf = (event: ReactPointerEvent): Cell | null => {
    const found = svg.current;
    const matrix = found?.getScreenCTM?.();
    if (!found || !matrix) return null;
    const point = new DOMPoint(event.clientX, event.clientY).matrixTransform(matrix.inverse());
    return [point.x / dx, point.y / dy];
  };
  const snapped = (c: Cell): Cell => [Math.round(c[0]), Math.round(c[1])];
  const down = (event: ReactPointerEvent<SVGSVGElement>) => {
    const at = cellOf(event);
    if (!at || event.button !== 0) return;
    const ref = refFrom((event.target as Element).closest?.("[data-ref]")?.getAttribute("data-ref"));
    if (tool === "track") {
      const from = snapPoint(g, at);
      setDrag({ kind: "track", from, to: from });
    } else if (tool === "select") {
      if (ref?.kind === "node" && model.panel.nodes[ref.id]) setDrag({ kind: "node", node: ref.id, to: g.cells.get(ref.id)!, moved: false });
      else if (ref?.kind === "piece") setDrag({ kind: "bend", piece: ref.id, from: snapPoint(g, at), to: snapped(at), moved: false });
      const sw = ref?.kind === "node" ? model.switches.find((s) => s.node === ref.id) : undefined;
      const line = ref?.kind === "node" ? model.line_exits.find((e) => e.node === ref.id) : undefined;
      const picked: Ref | null = sw ? { kind: "switch", id: sw.number } : line ? { kind: "exit", id: line.id } : ref;
      onPick?.(picked ? [picked] : [], event.shiftKey && picked?.kind === "switch");
    } else {
      onTool?.(snapPoint(g, at));
    }
    (event.currentTarget as Element).setPointerCapture?.(event.pointerId);
  };
  const move = (event: ReactPointerEvent<SVGSVGElement>) => {
    const at = cellOf(event);
    if (!at || !drag) return;
    if (drag.kind === "track") setDrag({ ...drag, to: snapStraight(drag.from, at) });
    else {
      const to = snapped(at);
      const from = drag.kind === "node" ? g.cells.get(drag.node)! : drag.from;
      setDrag({ ...drag, to, moved: drag.moved || to[0] !== Math.round(from[0]) || to[1] !== Math.round(from[1]) });
    }
  };
  const up = () => {
    if (drag?.kind === "track" && (drag.to[0] !== drag.from[0] || drag.to[1] !== drag.from[1])) onDraw?.(drag.from, drag.to);
    if (drag?.kind === "node" && drag.moved) onMove?.(drag.node, drag.to);
    if (drag?.kind === "bend" && drag.moved) onBend?.(drag.piece, drag.from, drag.to);
    setDrag(null);
  };
  const px = (c: Cell): [number, number] => [c[0] * dx, c[1] * dy];
  const line = (cells: Cell[]) => cells.map((c) => px(c).map((v) => Math.round(v * 100) / 100).join(",")).join(" ");
  const routeColour = route?.kind === "shunting" ? "vaxling" : "tagvag";
  const dots = [];
  for (let x = Math.ceil(box.x); x <= box.x + box.width; x++) for (let y = Math.ceil(box.y); y <= box.y + box.height; y++) dots.push(<circle key={`${x},${y}`} cx={x * dx} cy={y * dy} r={u * 0.05} />);
  return (
    <div className="rita-ram">
      <svg
        ref={svg}
        className={`rita-rutnat verktyg-${tool}`}
        viewBox={`${box.x * dx} ${box.y * dy} ${box.width * dx} ${box.height * dy}`}
        data-dx={dx}
        data-dy={dy}
        role="application"
        aria-label="Ritningen på rutnätet"
        onPointerDown={down}
        onPointerMove={move}
        onPointerUp={up}
        width={box.width * dx * (CELL_ON_SCREEN / u)}
        height={box.height * dy * (CELL_ON_SCREEN / u)}
        style={{ fontSize: 0.42 * u }}
      >
        <rect x={box.x * dx} y={box.y * dy} width={box.width * dx} height={box.height * dy} className="papper" />
        <g className="prickar">{dots}</g>
        {model.panel.turntable ? <circle className="skiva" cx={px(g.cells.get(model.panel.turntable.node) ?? [0, 0])[0]} cy={px(g.cells.get(model.panel.turntable.node) ?? [0, 0])[1]} r={model.panel.turntable.radius} strokeWidth={0.08 * u} /> : null}
        <g className="spar">
          {[...g.paths].map(([piece, path]) => (
            <g key={piece} data-ref={`piece:${piece}`} className={`${chosen.pieces.has(piece) ? "vald" : ""}${assumed(model.pieces.find((p) => p.id === piece)?.origin) ? " antagen" : ""}`}>
              <polyline className="traff" points={line(path)} strokeWidth={0.7 * u} />
              <polyline className="linje" data-piece={piece} points={line(path)} strokeWidth={0.12 * u} />
            </g>
          ))}
        </g>
        <g className={`vag-linje ${routeColour}`} strokeWidth={0.22 * u}>
          {[...g.paths].filter(([piece]) => lit.has(piece)).map(([piece, path]) => (
            <polyline key={piece} data-lit={piece} points={line(path)} />
          ))}
        </g>
        {model.nodes.map((node) => {
          const c = g.cells.get(node.id);
          if (!c) return null;
          const [x, y] = px(c);
          const pieces = g.touching.get(node.id) ?? [];
          const dir = direction(model, g, pieces[0], node.id);
          const across: [number, number] = [-dir[1], dir[0]];
          const pinned = !!model.panel.nodes[node.id];
          const isLoose = loose.has(node.id);
          const sw = model.switches.find((s) => s.node === node.id);
          const derailer = model.derailers.find((x) => x.node === node.id);
          const exit = model.line_exits.find((e) => e.node === node.id);
          const yellow = assumed(sw?.origin);
          return (
            <g key={node.id} data-ref={`node:${node.id}`} data-node={node.id} className={`nod ${node.type}${chosen.nodes.has(node.id) ? " vald" : ""}${yellow ? " antagen" : ""}`}>
              {node.type === "block_boundary" ? <line className="streck" x1={x - across[0] * 0.3 * u} y1={y - across[1] * 0.3 * u} x2={x + across[0] * 0.3 * u} y2={y + across[1] * 0.3 * u} strokeWidth={0.08 * u} /> : null}
              {derailer ? (
                <g className="sparr" data-ref={`derailer:${derailer.number}`} data-derailer={derailer.number}>
                  <title>{`Spårspärr ${derailer.number}`}</title>
                  <line x1={x - across[0] * 0.3 * u} y1={y - across[1] * 0.3 * u} x2={x + across[0] * 0.3 * u} y2={y + across[1] * 0.3 * u} strokeWidth={0.16 * u} />
                  <text className="vaxelnummer" x={x + Math.abs(across[0]) * 0.7 * u} y={y + Math.abs(across[1]) * 0.85 * u + 0.15 * u} textAnchor={Math.abs(across[0]) > 0.5 ? "start" : "middle"}>
                    {derailer.number}
                  </text>
                  <circle className="traff" cx={x} cy={y} r={0.4 * u} />
                </g>
              ) : null}
              {node.type === "buffer_stop" ? <line className="stoppbock" x1={x - across[0] * 0.35 * u} y1={y - across[1] * 0.35 * u} x2={x + across[0] * 0.35 * u} y2={y + across[1] * 0.35 * u} strokeWidth={0.2 * u} /> : null}
              {exit ? (
                <g className="utfart" data-ref={`exit:${exit.id}`}>
                  <rect x={x - dir[0] * 1.6 * u - 0.75 * u} y={y - dir[1] * 1.6 * u - 0.35 * u} width={1.5 * u} height={0.7 * u} rx={0.35 * u} />
                  <text x={x - dir[0] * 1.6 * u} y={y - dir[1] * 1.6 * u + 0.15 * u} textAnchor="middle">
                    {exit.id}
                  </text>
                </g>
              ) : null}
              {sw ? (
                <text className="vaxelnummer" data-ref={`node:${node.id}`} x={x} y={y + (sw.diverging && (g.paths.get(sw.diverging)?.some((p) => p[1] < c[1]) ?? false) ? 0.85 * u : -0.45 * u)} textAnchor="middle">
                  {sw.number}
                </text>
              ) : null}
              <circle className="traff" cx={x} cy={y} r={0.4 * u} />
              {isLoose ? (
                <circle className="knut los" cx={x} cy={y} r={0.24 * u} data-loose="ja" />
              ) : sw || (pinned && node.type === "joint") ? (
                <circle className="knut egen" cx={x} cy={y} r={0.15 * u} />
              ) : chosen.nodes.has(node.id) ? (
                <circle className="knut" cx={x} cy={y} r={0.12 * u} />
              ) : null}
              {chosen.nodes.has(node.id) ? <circle className="ring" cx={x} cy={y} r={0.38 * u} strokeWidth={0.06 * u} /> : null}
            </g>
          );
        })}
        {model.signals.map((s) => {
          const c = g.cells.get(s.node);
          if (!c) return null;
          const back = direction(model, g, s.approach, s.node);
          return <SignalMark key={s.name} name={s.name} type={s.type} at={px(c)} toward={[-back[0], -back[1]]} u={u} chosen={selectedSignals.has(s.name)} yellow={assumed(s.origin)} />;
        })}
        {circuits.map((circuit) => {
          const middle = circuit.pieces[Math.floor(circuit.pieces.length / 2)];
          const path = middle ? g.paths.get(middle) : undefined;
          if (!path) return null;
          const [a, b] = [path[0]!, path[path.length - 1]!];
          const [x, y] = px([(a[0] + b[0]) / 2, (a[1] + b[1]) / 2]);
          const text = circuit.name;
          const w = (0.3 * text.length + 0.5) * u;
          return (
            <g key={circuit.name} className="blocketikett" data-ref={`circuit:${circuit.name}`}>
              <rect x={x - w / 2} y={y - 0.32 * u} width={w} height={0.64 * u} rx={0.12 * u} />
              <text x={x} y={y + 0.15 * u} textAnchor="middle">
                {text}
              </text>
            </g>
          );
        })}
        {model.station_tracks.map((track) => {
          const middle = (track.pieces ?? [])[Math.floor((track.pieces ?? []).length / 2)];
          const path = middle ? g.paths.get(middle) : undefined;
          if (!path) return null;
          const [a, b] = [path[0]!, path[path.length - 1]!];
          const [x, y] = px([(a[0] + b[0]) / 2, (a[1] + b[1]) / 2]);
          return (
            <g key={track.id} className="sparbeteckning" data-ref={`piece:${middle}`}>
              <rect x={x - 0.4 * u} y={y - 1.35 * u} width={0.8 * u} height={0.7 * u} rx={0.1 * u} />
              <text x={x} y={y - 0.83 * u} textAnchor="middle">
                {track.id}
              </text>
            </g>
          );
        })}
        {drag?.kind === "track" ? <polyline className="forslag" points={line([drag.from, drag.to])} strokeWidth={0.12 * u} /> : null}
        {drag && drag.kind !== "track" && drag.moved ? <circle className="forslag-punkt" cx={drag.to[0] * dx} cy={drag.to[1] * dy} r={0.25 * u} /> : null}
      </svg>
    </div>
  );
}

function direction(model: FullModel, g: Geometry, piece: string | undefined, node: string): [number, number] {
  const path = piece ? g.paths.get(piece) : undefined;
  const found = model.pieces.find((p) => p.id === piece);
  if (!path || path.length < 2 || !found) return [1, 0];
  const [a, b] = found.start === node ? [path[0]!, path[1]!] : [path[path.length - 1]!, path[path.length - 2]!];
  const vx = (b[0] - a[0]) * model.panel.grid.dx;
  const vy = (b[1] - a[1]) * model.panel.grid.dy;
  const size = Math.hypot(vx, vy) || 1;
  return [vx / size, vy / size];
}

/** A signal as the template draws it: a mast beside the track, on the left of the way it
 * applies, and its lamp pointing that way. Hsi a filled lamp, Fsi a hollow one, Hdvsi both, Dvsi
 * a triangle, the stop lamp a red square, so that it is never taken for a loose end's dot. */
function SignalMark({ name, type, at, toward, u, chosen, yellow }: { name: string; type: SignalType; at: [number, number]; toward: [number, number]; u: number; chosen: boolean; yellow: boolean }) {
  const left: [number, number] = [toward[1], -toward[0]];
  const foot: [number, number] = [at[0] + left[0] * 0.15 * u, at[1] + left[1] * 0.15 * u];
  const top: [number, number] = [at[0] + left[0] * 0.65 * u, at[1] + left[1] * 0.65 * u];
  const lamp: [number, number] = [top[0] + toward[0] * 0.28 * u, top[1] + toward[1] * 0.28 * u];
  const label: [number, number] = [at[0] + left[0] * 1.15 * u, at[1] + left[1] * 1.15 * u + 0.15 * u];
  const r = 0.17 * u;
  const tri = [
    [lamp[0] + toward[0] * r * 1.4, lamp[1] + toward[1] * r * 1.4],
    [lamp[0] - toward[0] * r + left[0] * r, lamp[1] - toward[1] * r + left[1] * r],
    [lamp[0] - toward[0] * r - left[0] * r, lamp[1] - toward[1] * r - left[1] * r],
  ];
  return (
    <g className={`signal ${type}${chosen ? " vald" : ""}${yellow ? " antagen" : ""}`} data-ref={`signal:${name}`} data-signal={name}>
      <title>{`${SIGNAL_NAMES[type] ?? type} ${name}`}</title>
      <polyline className="mast" points={`${foot[0]},${foot[1]} ${top[0]},${top[1]} ${lamp[0]},${lamp[1]}`} strokeWidth={0.06 * u} />
      {type === "dvsi" ? <polygon className="lykta" points={tri.map((p) => p.join(",")).join(" ")} /> : null}
      {type === "hsi" || type === "hdvsi" ? <circle className="lykta" cx={lamp[0]} cy={lamp[1]} r={r} /> : null}
      {type === "stop_lamp" ? <rect className="lykta" x={lamp[0] - r} y={lamp[1] - r} width={2 * r} height={2 * r} /> : null}
      {type === "fsi" || type === "hdvsi" ? <circle className="lykta ihalig" cx={lamp[0] + toward[0] * (type === "hdvsi" ? 2.2 * r : 0)} cy={lamp[1] + toward[1] * (type === "hdvsi" ? 2.2 * r : 0)} r={r} strokeWidth={0.05 * u} /> : null}
      <circle className="traff" cx={lamp[0]} cy={lamp[1]} r={0.45 * u} />
      <text x={label[0]} y={label[1]} textAnchor="middle">
        {name}
      </text>
    </g>
  );
}

// --- The selected object -------------------------------------------------------------------------

type Act = (change: (d: FullDrawing) => FullDrawing, select?: (d: FullDrawing) => Ref[]) => void;

/** A text field that changes the drawing when it is left or Enter is pressed. */
function Field({ label, value, onSave, mono = false }: { label: string; value: string; onSave: (value: string) => void; mono?: boolean }) {
  const [text, setText] = useState(value);
  useEffect(() => setText(value), [value]);
  const done = () => {
    if (text !== value) onSave(text);
  };
  return (
    <label>
      {label}
      <input className={mono ? "tm-mono" : undefined} aria-label={label} value={text} onChange={(e) => setText(e.target.value)} onBlur={done} onKeyDown={(e) => e.key === "Enter" && done()} />
    </label>
  );
}

function Inspector({ drawing, circuits, selected, act, pick }: { drawing: FullDrawing; circuits: TrackCircuit[]; selected: Ref[]; act: Act; pick: (ref: Ref | null) => void }) {
  const model = drawing.model;
  const switches = selected.filter((r) => r.kind === "switch");
  if (switches.length > 1) {
    const parts = switches.flatMap((r) => {
      const sw = model.switches.find((s) => s.number === r.id);
      return sw ? partsOf(sw) : [];
    });
    return (
      <section className="ruta rita-inspektor" aria-label="Valt">
        <h2>{switches.length} växlar valda</h2>
        <p className="liten">Lägg tillsammans kopplar växlarna till en spak: de läggs om tillsammans (STUDIO-02).</p>
        <button
          type="button"
          className="primar"
          onClick={() => {
            let id = "";
            act(
              (d) => {
                const made = joinTogether(d, parts);
                id = made.id;
                return made.drawing;
              },
              () => [{ kind: "lever", id }],
            );
          }}
        >
          Lägg tillsammans ({parts.join(", ")})
        </button>
      </section>
    );
  }
  const ref = selected[0];
  if (!ref) {
    return (
      <section className="ruta rita-inspektor" aria-label="Valt">
        <h2>Inget valt</h2>
        <p className="liten">Välj ett spår, en växel, en signal eller en utfart med Markera, eller klicka på ett problem nedanför.</p>
      </section>
    );
  }
  const remove = (
    <button type="button" className="fara" onClick={() => act((d) => removeAt(d, ref), () => [])}>
      Ta bort
    </button>
  );
  if (ref.kind === "derailer") {
    const derailer = model.derailers.find((x) => x.number === ref.id);
    if (!derailer) return null;
    return (
      <section className="ruta rita-inspektor" aria-label="Valt">
        <h2>Spårspärr {derailer.number}</h2>
        <Field label="Nummer" value={derailer.number} mono onSave={(v) => act((d) => renameDerailer(d, derailer.number, v), () => [{ kind: "derailer", id: v.trim() }])} />
        <p className="liten">På när den skyddar en väg bredvid, av när en väg går över den (TKL129). Numret är LocoNet-adressen som förval, som för en växel.</p>
        <label>
          Läggs av
          <select aria-label="Läggs av" value={derailer.control ?? "tkl"} onChange={(e) => act((d) => setDerailerControl(d, derailer.number, e.target.value as SwitchControl))}>
            {CONTROLS.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <div className="rad">{remove}</div>
      </section>
    );
  }
  if (ref.kind === "switch") {
    const sw = model.switches.find((s) => s.number === ref.id);
    if (!sw) return null;
    const plain = sw.type === "ordinary" || sw.type === "y";
    const lever = model.levers.find((l) => partsOf(sw).some((p) => p in l.plus || p in l.minus));
    return (
      <section className="ruta rita-inspektor" aria-label="Valt">
        <h2>Växel {sw.number}</h2>
        {assumed(sw.origin) ? (
          <p className="gul-rad">
            Antagen ur underlaget.{" "}
            <button type="button" onClick={() => act((d) => confirm(d, ref))}>
              Bekräfta
            </button>
          </p>
        ) : null}
        <Field label="Nummer" value={sw.number} mono onSave={(v) => act((d) => renameSwitch(d, sw.node, v), (d) => [{ kind: "switch", id: d.model.switches.find((s) => s.node === sw.node)?.number ?? v }])} />
        {plain ? (
          <Field
            label="LocoNet-adress"
            value={sw.address ? String(sw.address.number) : ""}
            mono
            onSave={(v) => act((d) => setSwitchAddress(d, sw.node, v.trim() ? Number.parseInt(v, 10) : null), (d) => [{ kind: "switch", id: d.model.switches.find((s) => s.node === sw.node)?.number ?? sw.number }])}
          />
        ) : null}
        <p className="liten">Numret är LocoNet-adressen som förval och går att byta (STUDIO-19).</p>
        <label>
          Typ
          <select aria-label="Typ" value={sw.type} onChange={(e) => act((d) => setSwitchType(d, sw.node, e.target.value as SwitchType), (d) => [{ kind: "switch", id: d.model.switches.find((s) => s.node === sw.node)?.number ?? sw.number }])}>
            {(plain ? SWITCH_TYPES.slice(0, 2) : [...SWITCH_TYPES.slice(2), ["crossing", "Korsning utan växel"] as [SwitchType, string]]).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        {plain ? (
          <>
            <label>
              Läggs av
              <select aria-label="Läggs av" value={sw.control ?? "tkl"} onChange={(e) => act((d) => setControl(d, sw.node, e.target.value as SwitchControl))}>
                {CONTROLS.map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <button type="button" onClick={() => act((d) => swapLegs(d, sw.node))}>
              Byt rakt och avvikande
            </button>
          </>
        ) : null}
        {lever ? (
          <p className="liten">
            På spaken{" "}
            <button type="button" className="lank" onClick={() => pick({ kind: "lever", id: lever.id })}>
              {lever.id}
            </button>
          </p>
        ) : null}
        <div className="rad">{remove}</div>
      </section>
    );
  }
  if (ref.kind === "signal") {
    const signal = model.signals.find((s) => s.name === ref.id);
    if (!signal) return null;
    return (
      <section className="ruta rita-inspektor" aria-label="Valt">
        <h2>Signal {signal.name}</h2>
        <Field label="Namn" value={signal.name} mono onSave={(v) => act((d) => renameSignal(d, signal.name, v), () => [{ kind: "signal", id: v.trim() }])} />
        <label>
          Typ
          <select aria-label="Typ" value={signal.type} onChange={(e) => act((d) => setSignal(d, signal.name, { type: e.target.value as SignalType, lamps: e.target.value === "hsi" ? 2 : null }))}>
            {SIGNAL_TYPES.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        {signal.type === "hsi" ? (
          <label>
            Lyktor
            <select aria-label="Lyktor" value={signal.lamps ?? 2} onChange={(e) => act((d) => setSignal(d, signal.name, { lamps: Number(e.target.value) }))}>
              {[1, 2, 3, 4, 5].map((n) => (
                <option key={n} value={n}>
                  Hsi {n}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        <label className="kryss">
          <input type="checkbox" checked={signal.planned} onChange={(e) => act((d) => setSignal(d, signal.name, { planned: e.target.checked }))} />
          Planerad, finns inte än
        </label>
        <div className="rad">
          <button type="button" onClick={() => act((d) => flipSignal(d, signal.name))}>
            Vänd riktningen
          </button>
          {remove}
        </div>
      </section>
    );
  }
  if (ref.kind === "exit") {
    const line = model.line_exits.find((e) => e.id === ref.id);
    if (!line) return null;
    return (
      <section className="ruta rita-inspektor" aria-label="Valt">
        <h2>Linjeutfart {line.id}</h2>
        <Field label="Id" value={line.id} mono onSave={(v) => act((d) => renameExit(d, line.id, v), () => [{ kind: "exit", id: v.trim() }])} />
        <Field label="Grannstation" value={line.neighbour ?? ""} onSave={(v) => act((d) => renameExit(d, line.id, line.id, v))} />
        <p className="liten">Grannen behövs inte: utfarten kopplas till en sträcka per träff (H26).</p>
        <div className="rad">{remove}</div>
      </section>
    );
  }
  if (ref.kind === "circuit") {
    const circuit = circuits.find((c) => c.name === ref.id);
    if (!circuit) return null;
    return (
      <section className="ruta rita-inspektor" aria-label="Valt">
        <h2>Spårledning {circuit.name}</h2>
        <Field label="Namn" value={circuit.name} mono onSave={(v) => act((d) => renameCircuit(d, circuit.pieces, v), () => [{ kind: "circuit", id: v.trim() }])} />
        <p className="liten">Spårledningarna räknas fram mellan blockstrecken och signalerna; namnet följer spåret och riktningen tills du byter det (STUDIO-19).</p>
      </section>
    );
  }
  if (ref.kind === "lever") return <section className="ruta rita-inspektor" aria-label="Valt"><h2>Spak {ref.id}</h2><p className="liten">Se Spakar nedanför.</p></section>;
  if (ref.kind === "piece") {
    const piece = model.pieces.find((p) => p.id === ref.id);
    if (!piece) return null;
    const track = model.station_tracks.find((t) => (t.pieces ?? []).includes(piece.id));
    const circuit = circuits.find((c) => c.pieces.includes(piece.id));
    return (
      <section className="ruta rita-inspektor" aria-label="Valt">
        <h2>Spår{track ? ` ${track.id}` : ""}</h2>
        {track ? (
          <>
            <Field label="Stationsspår, id" value={track.id} mono onSave={(v) => act((d) => renameStationTrack(d, track.id, v, track.label === `Spår ${track.id}` ? `Spår ${v.trim()}` : track.label))} />
            <Field label="Etikett" value={track.label} onSave={(v) => act((d) => renameStationTrack(d, track.id, track.id, v))} />
            <button type="button" onClick={() => act((d) => unmarkStationTrack(d, track.id))}>
              Inte stationsspår
            </button>
          </>
        ) : (
          <button type="button" onClick={() => act((d) => markStationTrack(d, piece.id))}>
            Gör till stationsspår
          </button>
        )}
        {circuit ? (
          <p className="liten">
            I spårledningen{" "}
            <button type="button" className="lank" onClick={() => pick({ kind: "circuit", id: circuit.name })}>
              {circuit.name}
            </button>
          </p>
        ) : null}
        <div className="rad">
          <button type="button" onClick={() => act((d) => straighten(d, piece.id))}>
            Räta ut
          </button>
          {remove}
        </div>
      </section>
    );
  }
  const node = model.nodes.find((n) => n.id === ref.id);
  if (!node) return null;
  const ends = (geometry(model).touching.get(node.id) ?? []).length === 1;
  const at = geometry(model).cells.get(node.id) ?? [0, 0];
  return (
    <section className="ruta rita-inspektor" aria-label="Valt">
      <h2>{node.type === "buffer_stop" ? "Stoppbock" : node.type === "block_boundary" ? "Blockstreck" : ends ? "Spårände" : "Punkt"}</h2>
      {ends && node.type !== "buffer_stop" ? (
        <div className="rad">
          <button type="button" onClick={() => act((d) => placeBufferStop(d, at))}>
            Sätt stoppbock
          </button>
          <button type="button" onClick={() => act((d) => placeLineExit(d, at).drawing)}>
            Sätt linjeutfart
          </button>
        </div>
      ) : null}
      {node.type === "block_boundary" || node.type === "buffer_stop" ? <div className="rad">{remove}</div> : null}
    </section>
  );
}

/** Spakar: the levers with two or more switches (Lägg tillsammans), the parts that lie
 * reversed, and the switches each drags along in one position (STUDIO-34). */
function LeversView({ drawing, selected, act, pick }: { drawing: FullDrawing; selected: Ref[]; act: Act; pick: (ref: Ref | null) => void }) {
  const model = drawing.model;
  const [part, setPart] = useState("");
  const [when, setWhen] = useState<Position>("-");
  const [position, setPosition] = useState<Position>("-");
  const all = model.switches.filter((s) => s.control === "tkl").flatMap(partsOf);
  const sign = (p: Position) => (p === "+" ? "+ (rakt)" : "− (avvikande)");
  return (
    <section className="ruta rita-spakar" aria-label="Spakar">
      <h2>Spakar</h2>
      {model.levers.length ? null : <p className="liten">Varje växel har sin egen spak. Välj två eller flera växlar med skift-klick och lägg dem tillsammans.</p>}
      {model.levers.map((lever) => {
        const own = ownParts(lever);
        const open = selected.some((r) => r.kind === "lever" && r.id === lever.id);
        return (
          <div key={lever.id} className={`spak${open ? " vald" : ""}`}>
            <div className="rad">
              <button type="button" className="lank tm-mono" onClick={() => pick({ kind: "lever", id: lever.id })}>
                Spak {lever.id}
              </button>
              <span className="tm-fyll" />
              <button type="button" className="lank" onClick={() => act((d) => removeAt(d, { kind: "lever", id: lever.id }), () => [])}>
                Dela upp
              </button>
            </div>
            <ul>
              {own.map((p) => (
                <li key={p}>
                  <label className="kryss">
                    <input type="checkbox" checked={isReversed(lever, p)} onChange={(e) => act((d) => setReversed(d, lever.id, p, e.target.checked))} />
                    Växel {p} ligger omvänt
                  </label>
                </li>
              ))}
              {drags(lever).map((drag) => (
                <li key={`${drag.when}${drag.part}`}>
                  I {drag.when} drar spaken med växel {drag.part} till {sign(drag.position)}{" "}
                  <button type="button" className="lank" onClick={() => act((d) => removeDrag(d, lever.id, drag.when, drag.part))}>
                    Ta bort
                  </button>
                </li>
              ))}
            </ul>
            {open ? (
              <div className="rad drar-med">
                <span className="liten">I</span>
                <select aria-label="Spakens läge" value={when} onChange={(e) => setWhen(e.target.value as Position)}>
                  <option value="+">+</option>
                  <option value="-">−</option>
                </select>
                <span className="liten">drar med växel</span>
                <select aria-label="Växeln som dras med" value={part} onChange={(e) => setPart(e.target.value)}>
                  <option value="">välj</option>
                  {all.filter((p) => !own.includes(p)).map((p) => (
                    <option key={p} value={p}>
                      {p}
                    </option>
                  ))}
                </select>
                <span className="liten">till</span>
                <select aria-label="Läget den dras till" value={position} onChange={(e) => setPosition(e.target.value as Position)}>
                  <option value="+">+</option>
                  <option value="-">−</option>
                </select>
                <button type="button" disabled={!part} onClick={() => act((d) => addDrag(d, lever.id, when, part, position))}>
                  Lägg till
                </button>
              </div>
            ) : null}
          </div>
        );
      })}
    </section>
  );
}
