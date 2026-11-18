// Studio › Prova (#85 del c, STUDIO-05, STUDIO-12, STUDIO-21, STUDIO-27): TKL's simulator runs a
// train through every train route and every shunting route, one at a time from a clean state, in
// the background. At level 3 against the pretend LocoNet, at level 1–2 with Kör. The page shows the
// progress, the routes with the failures first, and a click on a route lights it on the panel as
// Spårplan does. When every route has passed the station is Klart and Ställverket opens without
// its note. With LocoNet connected to the layout, Provkör sets each route on the real layout and
// asks the owner. Prova connects only to a preview run in the hub, never to a real meet.
import { useCallback, useEffect, useRef, useState } from "react";
import type { components } from "../../../contracts/tkl";
import { api, call, Problem, TKL, type Connection, type Route, type TrackPlan } from "./api";
import "./prova.css";
import { PanelView } from "./Sparplan";

type Schemas = components["schemas"];
export type ProvaData = Schemas["trainmeet.tkl-1.prova"];
export type ProvaRoute = Schemas["trainmeet.tkl-1.prova.TklProvaRoute"];
export type ProvaWay = Schemas["trainmeet.tkl-1.prova.TklProvaWay"];
export type Provkor = Schemas["trainmeet.tkl-1.prova.TklProvkor"];
export type ProvkorAnswer = Schemas["trainmeet.tkl-1.provkor-answer"]["answer"];
export type Result = ProvaRoute["result"];

const P = `${TKL}/studio/prova`;
const POLL_MS = 500;

/** Every call Prova makes; the tests give their own. */
export type Calls = {
  view: () => Promise<ProvaData>;
  start: () => Promise<ProvaData>;
  stop: () => Promise<ProvaData>;
  provkorStart: () => Promise<ProvaData>;
  provkorAnswer: (answer: ProvkorAnswer) => Promise<ProvaData>;
  provkorStop: () => Promise<ProvaData>;
  plan: () => Promise<TrackPlan | null>;
  connection: () => Promise<Connection>;
  connect: (address: string, code: string) => Promise<Connection>;
};

export const provaCalls: Calls = {
  view: () => call<ProvaData>(P),
  start: () => call<ProvaData>(`${P}/start`, "POST"),
  stop: () => call<ProvaData>(`${P}/stop`, "POST"),
  provkorStart: () => call<ProvaData>(`${P}/provkor/start`, "POST"),
  provkorAnswer: (answer) => call<ProvaData>(`${P}/provkor/answer`, "POST", { answer }),
  provkorStop: () => call<ProvaData>(`${P}/provkor/stop`, "POST"),
  plan: () => api.stationModel(),
  connection: () => api.connection(),
  // Prova's own Anslut: only a preview run in Provbanan, with its code (STUDIO-12).
  connect: (address, code) => call<Connection>(`${TKL}/connection`, "POST", { address, code, prova: true }),
};

export const RESULT_LABEL: Record<Result, string> = { passed: "Gick igenom", failed: "Gick inte", skipped: "Hoppades över" };
const RESULT_MARK: Record<Result, string> = { passed: "✓", failed: "✗", skipped: "–" };
const ORDER: Record<Result, number> = { failed: 0, skipped: 1, passed: 2 };

/** The routes that did not pass first, then the rest, each in the engine's order. */
export function failuresFirst<T extends { result: Result }>(routes: T[]): T[] {
  return routes
    .map((route, index) => ({ route, index }))
    .sort((a, b) => ORDER[a.route.result] - ORDER[b.route.result] || a.index - b.index)
    .map(({ route }) => route);
}

export function routeTitle(route: ProvaWay): string {
  return `${route.kind === "train" ? "Tågväg" : "Växlingsväg"} ${route.start} → ${route.end}`;
}

/** A route as the panel draws it, as Spårplan does. */
export function asRoute(route: ProvaWay): Route {
  return { kind: route.kind, start: route.start, end: route.end, pieces: route.pieces ?? [], positions: {}, turntable: null };
}

export const sameRoute = (a: ProvaWay | null, b: ProvaWay | null) => !!a && !!b && a.kind === b.kind && a.start === b.start && a.end === b.end;

/** How Prova runs the train, as the page says it. */
export function simulatorText(view: ProvaData): string {
  if (view.simulator === "pretend") return "Nivå 3 · låtsas-LocoNet: växlarna återrapporterar och spårledningarna styr tåget";
  if (view.simulator === "kor") return `Nivå ${view.level} · ställverket med Kör, sektion för sektion`;
  return "Ingen stationsmodell";
}

export function progressText(view: ProvaData): string {
  const failed = view.failed ? ` · ${view.failed} gick inte` : "";
  return `Provat ${view.done} av ${view.total} vägar${failed}`;
}

export function provkorText(provkor: Provkor): string {
  if (provkor.running) return `Provkör: väg ${Math.min(provkor.done + 1, provkor.total)} av ${provkor.total}`;
  return provkor.done ? `Provkört ${provkor.done} vägar` : "";
}

/** What the page's buttons do: each a call to TKL's server, whose answer is the next view. */
export function handlers(calls: Calls, run: (work: () => Promise<ProvaData>) => void, choose: (route: ProvaWay | null) => void): Handlers {
  return {
    onStart: () => run(calls.start),
    onStop: () => run(calls.stop),
    onProvkor: () => run(calls.provkorStart),
    onAnswer: (answer) => run(() => calls.provkorAnswer(answer)),
    onProvkorStop: () => run(calls.provkorStop),
    onChoose: choose,
  };
}

export type Handlers = {
  onStart: () => void;
  onStop: () => void;
  onProvkor: () => void;
  onAnswer: (answer: ProvkorAnswer) => void;
  onProvkorStop: () => void;
  onChoose: (route: ProvaWay | null) => void;
};

export function Prova({ calls = provaCalls, onChanged }: { calls?: Calls; onChanged?: () => void }) {
  const [view, setView] = useState<ProvaData | null>(null);
  const [plan, setPlan] = useState<TrackPlan | null>(null);
  const [chosen, setChosen] = useState<ProvaWay | null>(null);
  const [connection, setConnection] = useState<Connection | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const tried = useRef<boolean | null>(null);

  const show = useCallback(
    (next: ProvaData) => {
      setView(next);
      if (tried.current !== null && tried.current !== next.tried) onChanged?.();
      tried.current = next.tried;
    },
    [onChanged],
  );

  const run = useCallback(
    async (work: () => Promise<ProvaData>) => {
      setBusy(true);
      setError("");
      try {
        show(await work());
      } catch (failed) {
        setError(failed instanceof Error ? failed.message : "Det gick inte.");
      } finally {
        setBusy(false);
      }
    },
    [show],
  );

  useEffect(() => {
    void run(calls.view);
    calls.plan().then(setPlan).catch(() => setPlan(null));
    calls.connection().then(setConnection).catch(() => setConnection(null));
  }, [calls, run]);

  // While the test runs in the background, or Provkör waits for the layout, ask how it stands.
  const moving = !!view && (view.running || view.provkor.running);
  useEffect(() => {
    if (!moving) return;
    const every = setInterval(() => {
      calls.view().then(show).catch(() => undefined);
    }, POLL_MS);
    return () => clearInterval(every);
  }, [calls, moving, show]);

  if (!view) return <p className="tom">{error || "Läser Prova …"}</p>;
  return (
    <ProvaView
      view={view}
      plan={plan}
      chosen={chosen}
      connection={connection}
      error={error}
      busy={busy}
      onConnect={async (address, code) => {
        setError("");
        try {
          setConnection(await calls.connect(address, code));
        } catch (failed) {
          setError(failed instanceof Problem || failed instanceof Error ? failed.message : "Det gick inte.");
        }
      }}
      {...handlers(calls, (work) => void run(work), setChosen)}
    />
  );
}

export function ProvaView({
  view,
  plan,
  chosen,
  connection,
  error = "",
  busy = false,
  onConnect,
  ...on
}: {
  view: ProvaData;
  plan: TrackPlan | null;
  chosen: ProvaWay | null;
  connection: Connection | null;
  error?: string;
  busy?: boolean;
  onConnect: (address: string, code: string) => void;
} & Handlers) {
  const routes = failuresFirst(view.routes ?? []);
  const panel = plan?.panel ?? null;
  const noModel = view.simulator === null;
  return (
    <div className="prova">
      <div className="sidrubrik">
        <h1>Prova</h1>
        <p className="liten">
          Ett simulerat tåg körs genom varje tågväg och växlingsväg, en i taget från ett rent läge. På nivå 3 går det mot låtsas-LocoNet med samma kod som på banan; på nivå 1–2 stegar det med Kör. När varje väg har gått igenom är stationen klar för Ställverket.
        </p>
      </div>
      {error ? (
        <p className="fel" role="alert">
          {error}
        </p>
      ) : null}
      <section className="ruta prova-status" aria-label="Provet">
        <p className="overrad">{simulatorText(view)}</p>
        {view.tried ? (
          <p className="prova-klart" role="status">
            <strong>Klart</strong> · Varje väg gick igenom. Stationen kan öppnas i Ställverket.
          </p>
        ) : view.message && !view.running ? (
          <p className={view.invalidated || view.failed ? "notis varning" : "notis"} role="status">
            {view.message}
          </p>
        ) : null}
        {view.running ? (
          <div className="prova-framsteg">
            <progress max={view.total || 1} value={view.done} aria-label="Prova" />
            <span>{progressText(view)} …</span>
          </div>
        ) : view.routes?.length ? (
          <p className="liten">{`${view.passed} gick igenom · ${view.failed} gick inte · ${view.total} vägar`}</p>
        ) : null}
        <div className="rad">
          {view.running ? (
            <button type="button" disabled={busy} onClick={on.onStop}>
              Avbryt
            </button>
          ) : (
            <button type="button" className="primar" disabled={busy || noModel} onClick={on.onStart}>
              {view.routes?.length ? "Prova igen" : "Starta Prova"}
            </button>
          )}
        </div>
      </section>
      {panel ? (
        <section className="ruta panel-ruta" aria-label="Panelen">
          <div className="rad">
            {chosen ? (
              <span className="liten">
                {routeTitle(chosen)}{" "}
                <button type="button" className="lank" onClick={() => on.onChoose(null)}>
                  Släck
                </button>
              </span>
            ) : (
              <span className="liten">Klicka på en väg nedanför för att se den på panelen.</span>
            )}
          </div>
          <PanelView panel={panel} form="schematic" route={chosen ? asRoute(chosen) : null} />
        </section>
      ) : null}
      {routes.length ? (
        <section className="ruta" aria-label="Vägarna">
          <h2>Vägarna</h2>
          <ul className="prova-vagar">
            {routes.map((route) => (
              <RouteRow key={`${route.kind}|${route.start}|${route.end}`} route={route} chosen={sameRoute(route, chosen)} onChoose={on.onChoose} />
            ))}
          </ul>
        </section>
      ) : null}
      <ProvkorPart provkor={view.provkor} busy={busy} on={on} />
      <Provkorning connection={connection} onConnect={onConnect} />
    </div>
  );
}

function RouteRow({ route, chosen, onChoose }: { route: ProvaRoute; chosen: boolean; onChoose: (route: ProvaWay | null) => void }) {
  return (
    <li>
      <button type="button" className={`prova-vag ${route.result}`} aria-pressed={chosen} onClick={() => onChoose(chosen ? null : route)}>
        <span className="prova-markering" aria-label={RESULT_LABEL[route.result]}>
          {RESULT_MARK[route.result]}
        </span>
        <span className="prova-namn">{routeTitle(route)}</span>
        {route.reason ? <span className="prova-skal">{route.reason}</span> : null}
      </button>
    </li>
  );
}

/** Provkör (STUDIO-05, STUDIO-27): each route on the real layout, with the owner. */
function ProvkorPart({ provkor, busy, on }: { provkor: Provkor; busy: boolean; on: Handlers }) {
  const routes = failuresFirst(provkor.routes ?? []);
  return (
    <section className="ruta provkor" aria-label="Provkör">
      <h2>Provkör på banan</h2>
      <p className="liten">
        Med LocoNet anslutet till banan lägger TKL vägarna en i taget: växlarna läggs om och återrapporterar, och du tittar på banan om signalen visar kör och vägen ligger rätt.
      </p>
      {!provkor.available && !provkor.running ? <p className="liten">{provkor.reason}</p> : null}
      {provkor.running && provkor.route ? (
        <div className="prova-fraga" role="alertdialog" aria-label="Provkör">
          <p className="overrad">{provkorText(provkor)}</p>
          <h3>{routeTitle(provkor.route)}</h3>
          {provkor.question ? <p>{provkor.question}</p> : <p className="liten">{provkor.waiting ?? "Lägger vägen …"}</p>}
          <div className="rad">
            <button type="button" className="primar" disabled={busy || !provkor.question} onClick={() => on.onAnswer("right")}>
              Ja, det stämmer
            </button>
            <button type="button" disabled={busy || !provkor.question} onClick={() => on.onAnswer("wrong")}>
              Nej, fel
            </button>
            <button type="button" disabled={busy} onClick={() => on.onAnswer("skip")}>
              Hoppa över
            </button>
            <button type="button" className="lank" disabled={busy} onClick={on.onProvkorStop}>
              Avsluta Provkör
            </button>
          </div>
        </div>
      ) : (
        <div className="rad">
          <button type="button" disabled={busy || !provkor.available} onClick={on.onProvkor}>
            Starta Provkör
          </button>
          {provkor.done ? <span className="liten">{provkorText(provkor)}</span> : null}
        </div>
      )}
      {routes.length ? (
        <ul className="prova-vagar">
          {routes.map((route) => (
            <RouteRow key={`p|${route.kind}|${route.start}|${route.end}`} route={route} chosen={false} onChoose={on.onChoose} />
          ))}
        </ul>
      ) : null}
    </section>
  );
}

/** Prova with a preview run in the hub, Provbanan with its code; never a real meet (STUDIO-12). */
function Provkorning({ connection, onConnect }: { connection: Connection | null; onConnect: (address: string, code: string) => void }) {
  const [address, setAddress] = useState("");
  const [code, setCode] = useState("");
  return (
    <section className="ruta" aria-label="Provkörning i hubben">
      <h2>Med en provkörning i hubben</h2>
      <p className="liten">Prova kan kopplas till en provkörning i Provbanan, med provkörningens kod. Aldrig till en riktig träff: hubben och TKL säger nej.</p>
      {connection?.connected ? (
        <p className={connection.preview ? "notis" : "notis varning"} role="status">
          {connection.preview
            ? `Ansluten till en provkörning på ${connection.hub_name ?? connection.address ?? "hubben"} · ${connection.status === "approved" ? "godkänd" : "väntar på godkännande"}.`
            : "TKL är ansluten till en riktig träff. Koppla från den i Inställningar innan Prova kopplas till en provkörning."}
        </p>
      ) : (
        <form
          className="rad"
          onSubmit={(event) => {
            event.preventDefault();
            onConnect(address.trim(), code.trim());
          }}
        >
          <label>
            Hubbens adress
            <input value={address} onChange={(e) => setAddress(e.target.value)} placeholder="http://trainmeet.local" />
          </label>
          <label>
            Provkörningens kod
            <input value={code} inputMode="numeric" onChange={(e) => setCode(e.target.value)} />
          </label>
          <button type="submit" disabled={!address.trim() || !code.trim()}>
            Koppla Prova till provkörningen
          </button>
        </form>
      )}
    </section>
  );
}
