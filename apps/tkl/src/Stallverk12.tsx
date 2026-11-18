// Ställverket at level 1–2 (#84): the station's panel as a working interlocking, drawn in skin 85,
// 95 or 59 (STV-12, STV-41), over the bottom row Tåg · Klarering · Händelser (STV-07). Click the
// start signal and the goal (STV-01, STV-03), the start again for a shunting route (STV-24), Esc
// to cancel; in 59 the signals' toggles are flipped instead (STV-36). A set route is chosen with
// a click, and Kör, Ankommit, Avgått, Lös ut and Nödutlös act on it. A click on a switch lays its
// lever. The panel's buttons are the station's functions from the catalogue (STV-04, STV-53).
// Every operation asks TKL's interlocking, and its answer, yes or no with the reason, is what
// the page shows (STV-43). Every screen waits for the next change, so a second screen follows
// the first (STV-05); the skin, the proportion and the view are chosen per screen and kept in
// this browser. Klarering is level 0's, as it is.
import { useEffect, useMemo, useRef, useState } from "react";
import { api, Problem, type FunctionAsk, type FunctionShown, type InterlockingAnswer, type Interlocking, type Outside, type TrackPlan, type View } from "./api";
import type { Happening } from "./handelser";
import { trains as trainsOf } from "./niva0";
import { Panelen } from "./Panelen";
import { changeScreen, codeIn, PROPORTION, readScreen, screenNumber, SKIN_NAMES, SKIN_ORDER, skinOf, SKINS, type Screen, type ScreenView, type Skin } from "./skal";
import { Klarering, Questions, Stallverket, type Send } from "./Stallverket";
import {
  act,
  busyLines,
  clickPoint,
  clickSwitch,
  clickToggle,
  drawing,
  emergency,
  escape,
  filled,
  functionCall,
  guidance,
  NOTHING,
  routeEnds,
  routeName,
  trainCall,
  type Act,
  type Done,
  type Filled,
  type Said,
  type Valet,
} from "./stallverk";
import { readLanguage, saveLanguage, text, type Language, type Say } from "./texter";
import type { Sounds } from "./ljud";

type Props = {
  level: number;
  view: View | null;
  /** Why the hub's part is missing, when TKL is not connected and approved. */
  hubNote?: string | null;
  outside: Outside | null;
  journal: Happening[];
  sounds: Sounds;
  busy: boolean;
  onSend: Send;
  onExit: (section: string, exit: string) => void;
  /** For tests and a second render: the model and the state, without fetching them. */
  initial?: { plan: TrackPlan | null; state: Interlocking | null; valet?: Valet; refusals?: Said[]; screen?: Screen; language?: Language };
};

const storage = (): Storage | null => (typeof localStorage === "undefined" ? null : localStorage);
const sleep = (ms: number) => new Promise((done) => setTimeout(done, ms));

/** The Ställverket page: level 0 exactly as before for a station without a model, else the
 * panel. The model and the state are fetched here, and followed with the interlocking's wait. */
export function StallverketSida(props: Props) {
  const { level, view, outside, journal, sounds, busy, onSend, onExit, hubNote, initial } = props;
  const [plan, setPlan] = useState<TrackPlan | null | undefined>(initial ? initial.plan : undefined);
  const [state, setState] = useState<Interlocking | null | undefined>(initial ? initial.state : undefined);
  const [failed, setFailed] = useState("");
  const revision = useRef<number | null>(null);
  revision.current = state?.revision ?? null;

  useEffect(() => {
    if (initial || level < 1) return;
    let alive = true;
    void (async () => {
      try {
        const [found, now] = await Promise.all([api.stationModel(), api.interlocking().catch(() => null)]);
        if (!alive) return;
        setPlan(found);
        setState(now);
      } catch (error) {
        if (alive) {
          setPlan(null);
          setFailed(error instanceof Error ? error.message : "");
        }
      }
      // Väntan (STV-05): wait for the next change and read again, on every screen.
      while (alive) {
        const after = revision.current;
        if (after === null) {
          await sleep(2000);
          continue;
        }
        try {
          const waited = await api.interlockingWait(after, 25);
          if (alive && waited.changed && revision.current === after) {
            const fresh = await api.interlocking();
            if (alive) setState(fresh);
          }
        } catch (error) {
          if (error instanceof Problem && error.status === 404 && alive) setPlan(null);
          await sleep(3000);
        }
      }
    })();
    return () => {
      alive = false;
    };
  }, [initial, level]);

  const zero = view ? <Stallverket view={view} outside={outside} journal={journal} sounds={sounds} busy={busy} onSend={onSend} onExit={onExit} /> : <p className="tom">{hubNote ?? "Väntar på hubben …"}</p>;
  if (level < 1) return zero;
  if (plan === undefined || (plan && state === undefined)) return <p className="tom">{text(initial?.language ?? "sv", "loading")}</p>;
  if (!plan?.panel || !state) {
    return (
      <>
        {failed ? <p className="notis">{failed}</p> : null}
        {zero}
      </>
    );
  }
  return <Stallverk12 {...props} plan={plan} panel={plan.panel} state={state} onState={setState} />;
}

type PanelProps = Props & { plan: TrackPlan; panel: NonNullable<TrackPlan["panel"]>; state: Interlocking; onState: (state: Interlocking) => void };

export function Stallverk12({ plan, panel, state: raw, onState, view, hubNote, outside, journal, busy, onSend, onExit, initial }: PanelProps) {
  const [screen] = useState(() => (typeof location === "undefined" ? 1 : screenNumber(location.search)));
  const [settings, setSettings] = useState<Screen>(() => initial?.screen ?? readScreen(screen, storage()));
  const [language, setLanguage] = useState<Language>(() => initial?.language ?? readLanguage(storage()));
  const [valet, setValet] = useState<Valet>(initial?.valet ?? NOTHING);
  const [refusals, setRefusals] = useState<Said[]>(initial?.refusals ?? []);
  const [working, setWorking] = useState(false);
  const say: Say = (key, vars) => text(language, key, vars);
  const state: Filled = filled(raw);
  const snapshot = view?.snapshot ?? null;
  const skin = skinOf(settings.skin);
  const ends = useMemo(() => routeEnds(plan.route_list ?? []), [plan]);
  const drawn = drawing(panel, state, busyLines(state, snapshot), ends);

  useEffect(() => {
    const key = (event: KeyboardEvent) => {
      if (event.key === "Escape") setValet((before) => escape(before));
    };
    addEventListener("keydown", key);
    return () => removeEventListener("keydown", key);
  }, []);

  const run = async (work: () => Promise<Done>) => {
    // One question to the interlocking at a time: the next click builds on its answer.
    if (working) return;
    setWorking(true);
    try {
      const done = await work();
      setValet(done.valet);
      if (done.state) onState(done.state);
      const refused = done.refused;
      if (refused) setRefusals((before) => [refused, ...before].slice(0, 30));
    } finally {
      setWorking(false);
    }
  };
  // A skin, a proportion or a view: this screen's own, kept in the browser; it sends no order
  // (STV-05, STV-18).
  const change = (next: Partial<Screen>) => setSettings(changeScreen(screen, settings, next, storage()));
  const operate = (ask: FunctionAsk) => void run(() => functionCall(valet, ask, api));
  const lamps = skin.style === "lamps";
  const chosen = state.routes.find((r) => r.id === valet.route) ?? null;
  const put = (work: () => Promise<InterlockingAnswer>) => void run(() => trainCall(valet, work));

  const panelHeight = settings.view === "panel" ? "84vh" : `${settings.proportion}vh`;
  return (
    <div className="stv" lang={language}>
      <div className="niva">
        <span className="niva-chip">{say("level", { n: state.level })}</span>
        <span>{say("levelText")}</span>
        <span className="tm-fyll" />
        <ScreenBar screen={screen} settings={settings} say={say} onChange={change} onLanguage={() => {
          const next: Language = language === "sv" ? "en" : "sv";
          setLanguage(next);
          saveLanguage(next, storage());
        }} />
      </div>
      {state.problem ? (
        <p className="notis" role="alert">
          {state.problem} <ResetButton say={say} onReset={() => void run(() => trainCall(valet, () => api.resetInterlocking(true, false)))} />
        </p>
      ) : null}
      {settings.view !== "row" ? (
        <section className="stv-ruta" aria-label={say("panel")}>
          <Panelen
            panel={panel}
            drawn={drawn}
            skin={skin}
            say={say}
            title={plan.summary.name}
            choice={valet.choice}
            chosen={chosen ? { id: chosen.id, start: chosen.start } : null}
            height={panelHeight}
            onPoint={(name) => void run(() => clickPoint(valet, name, api, say))}
            onToggle={(name) => void run(() => clickToggle(valet, name, state.routes, api, say))}
            onSwitch={(part) => void run(() => clickSwitch(valet, part, api))}
            onRoute={(route) => setValet({ ...valet, route, confirm: null })}
            onButton={(name) => {
              const found = state.functions.find((f) => f.name === name);
              if (found) operate({ function: name, action: found.on ? "off" : "on", value: null, confirm: false });
            }}
          />
          <Legend skin={skin} say={say} />
          <div className="stv-valet">
            <p className="stv-hjalp" aria-live="polite">
              {guidance(valet, say, lamps)}
            </p>
            {valet.said ? (
              <p className={`stv-svar ${valet.said.ok ? "ja" : "nej"}`} role={valet.said.ok ? "status" : "alert"}>
                {valet.said.ok ? null : <b>{say("refused")}: </b>}
                {valet.said.text}
              </p>
            ) : null}
          </div>
          <RouteBar
            routes={state.routes}
            trains={state.trains}
            chosen={chosen}
            confirm={valet.confirm}
            working={working}
            say={say}
            onChoose={(route) => setValet({ ...valet, route, confirm: null })}
            onAct={(what: Act) => void run(() => act(valet, what, state.routes, api))}
            onEmergency={(confirmed) => void run(() => emergency(valet, confirmed, api))}
            onCancel={() => setValet({ ...valet, confirm: null })}
          />
          <FunctionRow functions={state.functions} skin={skin} working={working} say={say} onOperate={operate} />
        </section>
      ) : null}
      {settings.view !== "panel" ? (
        <>
          {snapshot ? <Questions questions={snapshot.questions} onExit={onExit} /> : null}
          <div className="kolumner">
            <Trains state={state} view={view} hubNote={hubNote ?? null} working={working} say={say} onPut={put} />
            {snapshot ? (
              <Klarering snapshot={snapshot} outside={outside} busy={busy} onSend={onSend} />
            ) : (
              <section className="kolumn" aria-labelledby="kol-klarering">
                <h2 id="kol-klarering">{say("clearance")}</h2>
                <p className="tom">{hubNote ?? say("notConnected")}</p>
              </section>
            )}
            <Events state={state} refusals={refusals} journal={journal} say={say} />
          </div>
        </>
      ) : null}
    </div>
  );
}

function Legend({ skin, say }: { skin: Skin; say: Say }) {
  const swatch = (colour: string) => <span className="farg" style={{ background: colour }} />;
  if (skin.legend === "legend59") {
    const p = skin.plan59;
    return (
      <p className="liten forklaring stv-forklaring">
        {swatch(p?.lit ?? "#fff")} {say("legendLamps59")} {swatch(p?.train ?? "#0f0")} {say("legendArrows59")} {swatch(p?.position ?? "#00f")} {say("legendPosition59")} · {say("legendSignals59")} · {say("legendToggles59")} · {say("skinName59")}
      </p>
    );
  }
  const signals = skin.legend === "legend95" ? say("legendSignals95") : say("legendSignals");
  return (
    <p className="liten forklaring stv-forklaring">
      {swatch(skin.tracks.free)} {say("legendFree")}
      {swatch(skin.tracks.train)} {say("legendTrain")}
      {swatch(skin.tracks.shunting)} {say("legendShunting")}
      {swatch(skin.tracks.occupied)} {say("legendOccupied")}
      {swatch(skin.tracks.local)} {say("legendLocal")} · {say("legendGap")} · {say("legendProtection")} · {signals}, {say("legendBlocked")} · {say("legendNumbers")} · {say(skin.legend === "legend95" ? "skinName95" : "skinName85")}
    </p>
  );
}

/** Panelens knappar (STV-04, STV-53): the station's panel functions from the catalogue, in the
 * same place in every skin; in 59 as toggle switches with a lamp above (SJH s. 152, 158). */
function FunctionRow({ functions, skin, working, say, onOperate }: { functions: FunctionShown[]; skin: Skin; working: boolean; say: Say; onOperate: (ask: FunctionAsk) => void }) {
  const [confirming, setConfirming] = useState<string | null>(null);
  if (!functions.length) return null;
  const ask = (name: string, action: FunctionAsk["action"], value: string | null = null, confirm = false): FunctionAsk => ({ function: name, action, value, confirm });
  const lampOf = (f: FunctionShown) =>
    f.type === "signal_stop" || f.type === "emergency_release" ? skin.lamps.stop : f.type === "local_release" ? skin.lamps.local : f.type === "programming_track" ? skin.local : skin.lamps.on;
  const lamp = (f: FunctionShown, on: boolean) =>
    skin.style === "lamps" ? (
      <svg className="vippa59" width="18" height="30" viewBox="0 0 22 34" aria-hidden="true">
        <circle cx="11" cy="6" r="4.2" fill={on ? lampOf(f) : skin.lamps.off} stroke="#141616" />
        <circle cx="11" cy="23" r="7.5" fill="#c3c7c9" stroke="#6c7174" />
        <circle cx="11" cy="23" r="3.4" fill="#1a1c1d" />
        <circle cx={on ? 15 : 11} cy="22.3" r="4" fill="#f3f2ec" stroke="#8d908e" strokeWidth=".8" />
      </svg>
    ) : (
      <span className="lampa" style={{ background: on ? lampOf(f) : skin.lamps.off, borderColor: lampOf(f) }} />
    );
  return (
    <div className={`stv-funktioner skal-${skin.id}`} role="group" aria-label={say("functions")}>
      <span className="liten">{say("functions")}:</span>
      {functions.map((f) => {
        const name = codeIn(f.codes, skin.id) ?? f.name;
        const title = f.note ?? f.name;
        if (f.type === "traction_current") {
          const modes = f.modes ?? [];
          const at = modes.findIndex((m) => m.value === f.mode);
          const next = modes[(at + 1) % Math.max(1, modes.length)];
          return (
            <button key={f.name} type="button" className="funktion" title={title} disabled={working || !next} onClick={() => next && onOperate(ask(f.name, "set", next.value))}>
              {skin.style === "lamps" ? lamp(f, false) : null}
              {name} <span className="varde tm-mono">{f.mode ?? "–"}</span>
            </button>
          );
        }
        if (f.type === "turntable") {
          return (
            <label key={f.name} className="funktion" title={title}>
              {say("turnTo", { name })}{" "}
              <select value={f.mode ?? ""} disabled={working} onChange={(e) => onOperate(ask(f.name, "set", e.target.value))}>
                <option value="" disabled>
                  –
                </option>
                {(f.modes ?? []).map((m) => (
                  <option key={m.value} value={m.value}>
                    {m.label}
                  </option>
                ))}
              </select>
            </label>
          );
        }
        if (f.type === "emergency_release") {
          return confirming === f.name ? (
            <span key={f.name} className="funktion">
              <button
                type="button"
                className="fara"
                disabled={working}
                onClick={() => {
                  setConfirming(null);
                  onOperate(ask(f.name, "release", null, true));
                }}
              >
                {say("confirmFunction", { name })}
              </button>
              <button type="button" onClick={() => setConfirming(null)}>
                {say("cancel")}
              </button>
            </span>
          ) : (
            <button key={f.name} type="button" className="funktion fara" title={title} disabled={working} onClick={() => setConfirming(f.name)}>
              {lamp(f, false)}
              {name}
            </button>
          );
        }
        const on = f.on ?? false;
        return (
          <span key={f.name} className="funktion-grupp">
            <button type="button" className="funktion" aria-pressed={on} title={title} data-function={f.name} disabled={working} onClick={() => onOperate(ask(f.name, on ? "off" : "on"))}>
              {lamp(f, on)}
              {name} <span className="varde">{on ? say("functionOn") : say("functionOff")}</span>
            </button>
            {f.type === "local_release" && on
              ? (f.switches ?? []).map((sw) => (
                  <button key={sw} type="button" className="funktion modul" disabled={working} onClick={() => onOperate(ask(f.name, "lay", sw))}>
                    {say("moduleButton", { name: sw })}
                  </button>
                ))
              : null}
          </span>
        );
      })}
    </div>
  );
}

function ScreenBar({ screen, settings, say, onChange, onLanguage }: { screen: number; settings: Screen; say: Say; onChange: (next: Partial<Screen>) => void; onLanguage: () => void }) {
  const views: [ScreenView, string][] = [
    ["all", say("viewAll")],
    ["panel", say("viewPanel")],
    ["row", say("viewRow")],
  ];
  return (
    <div className="stv-skarm" role="group" aria-label={say("screen", { n: screen })} title={say("screenNote")}>
      <b>{say("screen", { n: screen })}</b>
      <label>
        {say("shows")}{" "}
        <select value={settings.view} onChange={(e) => onChange({ view: e.target.value as ScreenView })}>
          {views.map(([id, name]) => (
            <option key={id} value={id}>
              {name}
            </option>
          ))}
        </select>
      </label>
      <span className="spar-val" role="group" aria-label={say("skin")}>
        {SKIN_ORDER.map((id) => {
          const ready = id in SKINS;
          return (
            <button key={id} type="button" aria-pressed={settings.skin === id} disabled={!ready} onClick={() => onChange({ skin: id })} title={ready ? SKIN_NAMES[id] : `${SKIN_NAMES[id]} · ${say("coming")}`}>
              {SKIN_NAMES[id]}
              {ready ? null : <span className="kommer"> {say("coming")}</span>}
            </button>
          );
        })}
      </span>
      {settings.view === "all" ? (
        <label>
          {say("proportion")}{" "}
          <input type="range" min={PROPORTION.min} max={PROPORTION.max} step={2} value={settings.proportion} onChange={(e) => onChange({ proportion: Number(e.target.value) })} />{" "}
          <span className="tm-mono">{settings.proportion} %</span>
        </label>
      ) : null}
      <button type="button" className="lank" onClick={() => window.open(`${location.pathname}?skarm=${screen + 1}`, "_blank")}>
        {say("newScreen")}
      </button>
      <button type="button" className="lank" onClick={onLanguage}>
        {say("otherLanguage")}
      </button>
    </div>
  );
}

function ResetButton({ say, onReset }: { say: Say; onReset: () => void }) {
  const [asking, setAsking] = useState(false);
  if (!asking) {
    return (
      <button type="button" className="fara" onClick={() => setAsking(true)}>
        {say("reset")}
      </button>
    );
  }
  return (
    <>
      <button type="button" className="fara" onClick={onReset}>
        {say("confirmReset")}
      </button>{" "}
      <button type="button" onClick={() => setAsking(false)}>
        {say("cancel")}
      </button>
    </>
  );
}

type RouteBarProps = {
  routes: Filled["routes"];
  trains: Filled["trains"];
  chosen: Filled["routes"][number] | null;
  confirm: number | null;
  working: boolean;
  say: Say;
  onChoose: (route: number) => void;
  onAct: (what: Act) => void;
  onEmergency: (confirmed: boolean) => void;
  onCancel: () => void;
};

function RouteBar({ routes, trains, chosen, confirm, working, say, onChoose, onAct, onEmergency, onCancel }: RouteBarProps) {
  const numberOf = (train: number | null | undefined) => trains.find((t) => t.id === train)?.number ?? null;
  return (
    <div className="stv-vagar">
      <span className="liten">{say("routes")}:</span>
      {routes.length ? (
        routes.map((r) => (
          <button key={r.id} type="button" className={`vag ${r.kind}`} aria-pressed={chosen?.id === r.id} onClick={() => onChoose(r.id)}>
            {r.kind === "train" ? say("trainRoute") : say("shuntingRoute")} {routeName(r)}
            {numberOf(r.train) ? <span className="tm-mono"> · {numberOf(r.train)}</span> : null}
          </button>
        ))
      ) : (
        <span className="tom">{say("noRoutes")}</span>
      )}
      {chosen ? (
        <span className="stv-knappar" role="group" aria-label={`${say("chosenRoute")} ${routeName(chosen)}`}>
          <button type="button" className="primar" disabled={working} onClick={() => onAct("step")}>
            {say("step")}
          </button>
          <button type="button" disabled={working} onClick={() => onAct("arrive")}>
            {say("arrive")}
          </button>
          {chosen.leaves ? (
            <button type="button" disabled={working} onClick={() => onAct("depart")}>
              {say("depart")}
            </button>
          ) : null}
          <button type="button" disabled={working} onClick={() => onAct("release")}>
            {say("release")}
          </button>
          {confirm === chosen.id ? (
            <>
              <button type="button" className="fara" disabled={working} onClick={() => onEmergency(true)}>
                {say("confirmEmergency", { route: routeName(chosen) })}
              </button>
              <button type="button" onClick={onCancel}>
                {say("cancel")}
              </button>
            </>
          ) : (
            <button type="button" className="fara" disabled={working} onClick={() => onEmergency(false)}>
              {say("emergency")}
            </button>
          )}
        </span>
      ) : null}
    </div>
  );
}

function Trains({ state, view, hubNote, working, say, onPut }: { state: Filled; view: View | null; hubNote: string | null; working: boolean; say: Say; onPut: (work: () => Promise<InterlockingAnswer>) => void }) {
  const snapshot = view?.snapshot ?? null;
  const found = snapshot ? trainsOf(snapshot) : null;
  const places: [string, string][] = [
    ...state.exits.map((e): [string, string] => [`exit:${e.exit}`, say("lineAt", { exit: e.exit })]),
    ...Object.entries(state.tracks).map(([section, track]): [string, string] => [`section:${section}`, section === `Spår ${track}` ? say("track", { track }) : `${say("track", { track })} · ${section}`]),
  ];
  const [number, setNumber] = useState("");
  const [where, setWhere] = useState(places[0]?.[0] ?? "");
  // A train on its way here is in the interlocking when it was put by its call, or typed with
  // its number.
  const inside = (call: string, number: string) => state.trains.some((t) => t.call === call || (!!t.number && t.number === number));
  const said = (t: Filled["trains"][number]) => (t.exit ? say("onTheLine", { exit: t.exit }) : say("onSection", { section: t.section ?? "" }));
  return (
    <section className="kolumn" aria-labelledby="kol-tag">
      <h2 id="kol-tag">
        {say("trains")} <span className="liten">{say("trainsSub")}</span>
      </h2>
      <h3>{say("inInterlocking")}</h3>
      {state.trains.length ? (
        state.trains.map((t) => (
          <div key={t.id} className="kort" data-train={t.number ?? ""}>
            <div className="rad">
              <b className="tm-mono">{t.number ?? "–"}</b> <span className="liten">{said(t)}</span>
              <span className="tm-fyll" />
              <button type="button" disabled={working} onClick={() => onPut(() => api.removeTrain(t.id))}>
                {say("remove")}
              </button>
            </div>
          </div>
        ))
      ) : (
        <p className="tom">{say("noTrains")}</p>
      )}
      <h3>{say("comingHere")}</h3>
      {!found ? (
        <p className="tom">{hubNote ?? say("notConnected")}</p>
      ) : found.coming.length ? (
        found.coming.map(({ train, from, exit }) => (
          <div key={train.call} className="kort kommer">
            <div className="rad">
              <b className="tm-mono">{train.train_number}</b> <span>{say("from", { place: from })}</span>
              {exit ? <span className="liten"> · {exit}</span> : null}
              <span className="tm-fyll" />
              {inside(train.call, train.train_number) ? (
                <span className="chip">{say("alreadyIn")}</span>
              ) : (
                <button type="button" className="primar" disabled={working} onClick={() => onPut(() => api.putTrain({ number: null, call: train.call, section: null, exit: null }))}>
                  {say("putAtEntry")}
                </button>
              )}
            </div>
          </div>
        ))
      ) : (
        <p className="tom">{say("noneComing")}</p>
      )}
      <h3>{say("putTrain")}</h3>
      <form
        className="stv-satt-ut"
        onSubmit={(event) => {
          event.preventDefault();
          const [kind, name] = [where.slice(0, where.indexOf(":")), where.slice(where.indexOf(":") + 1)];
          const trimmed = number.trim();
          onPut(() => api.putTrain({ number: trimmed || null, call: null, section: kind === "exit" ? null : name, exit: kind === "exit" ? name : null }));
          setNumber("");
        }}
      >
        <input aria-label={say("trainNumber")} placeholder={say("trainNumber")} value={number} maxLength={8} size={7} onChange={(e) => setNumber(e.target.value)} />
        <select aria-label={say("where")} value={where} onChange={(e) => setWhere(e.target.value)}>
          {places.map(([id, name]) => (
            <option key={id} value={id}>
              {name}
            </option>
          ))}
        </select>
        <button type="submit" disabled={working || !where}>
          {say("put")}
        </button>
      </form>
      {found ? (
        <>
          <h3>{say("atStation")}</h3>
          {found.atStation.length ? (
            <ul className="harnast">
              {found.atStation.map(({ call, to }) => (
                <li key={call.call}>
                  <b className="tm-mono">{call.train_number}</b> {to ? say("towards", { place: to }) : say("endsHere")}
                  {call.track ? <span className="liten"> · {say("track", { track: call.track })}</span> : null}
                </li>
              ))}
            </ul>
          ) : (
            <p className="tom">{say("noneAtStation")}</p>
          )}
        </>
      ) : null}
      <p className="liten fot">{say("trainsNote")}</p>
    </section>
  );
}

function Events({ state, refusals, journal, say }: { state: Filled; refusals: Said[]; journal: Happening[]; say: Say }) {
  const rows = [
    ...state.events.map((e) => ({ at: e.at, text: e.text, no: false })),
    ...refusals.map((r) => ({ at: r.at, text: r.text, no: true })),
  ].sort((a, b) => (a.at < b.at ? 1 : a.at > b.at ? -1 : 0));
  const time = (at: string) => {
    const d = new Date(at);
    return Number.isNaN(d.getTime()) ? at : d.toLocaleTimeString("sv-SE");
  };
  return (
    <section className="kolumn" aria-labelledby="kol-handelser">
      <h2 id="kol-handelser">
        {say("events")} <span className="liten">{say("eventsSub")}</span>
      </h2>
      {rows.length ? (
        <ul className="handelser stv-handelser">
          {rows.map((row, i) => (
            <li key={`${row.at}${i}`} className={row.no ? "nej" : undefined}>
              <span className="tm-mono">{time(row.at)}</span> {row.no ? <b>{say("refused")}: </b> : null}
              {row.text}
            </li>
          ))}
        </ul>
      ) : (
        <p className="tom">{say("noEvents")}</p>
      )}
      {journal.length ? (
        <>
          <h3>{say("fromHub")}</h3>
          <ul className="handelser">
            {journal.map((h) => (
              <li key={h.id}>
                <span className="tm-mono">{h.time}</span> {h.text}
              </li>
            ))}
          </ul>
        </>
      ) : null}
    </section>
  );
}
