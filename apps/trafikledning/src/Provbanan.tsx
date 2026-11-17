import { useCallback, useEffect, useRef, useState } from "react";
import { Problem, provbanan, type Client, type Command, type Preview, type PreviewCase, type PreviewClients, type PreviewLeg } from "./api";
import { LANGUAGES, SIDES } from "./drift";
import { ExitQuestions } from "./Klienter";
import { Select } from "./ui";

// Provbanan (steg 2): try Drift on four places with Monday's ten trains, acting from the place
// named on each button. Each browser has its own run, kept for a day (H51); boxes, TKL and the
// TMBox app join it with its code. The same as the old page (hub/static/provbanan.js).

const REASONS: Record<string, string> = {
  invalid_departure: "Tåget har redan kört den här sträckan.",
  call_already_requested: "Tåget har redan en pågående klarering.",
  channel_occupied: "Sträckan är upptagen.",
};
const CASES: Record<string, string> = { waiting: "Väntar på svar", approved: "Klart", rejected: "Nekad", cancelled: "Återkallad" };
const KINDS: Record<string, string> = { tkl: "TKL", tmbox_app: "TMBox-appen", dispatch: "Trafikledningen" };
const APPROVAL: Record<string, string> = { waiting: "Väntar på godkännande", approved: "Godkänd för", refused: "Nekad", revoked: "Återkallad" };

const pad = (value: number) => String(value).padStart(2, "0");

/** The run's clock, going on between the hub's answers at the run's speed. */
export function runClock(state: Preview, elapsedMs: number): string {
  const { clock } = state;
  const elapsed = clock.running ? elapsedMs / 1000 : 0;
  const minute = Math.floor((clock.seconds + elapsed * clock.speed) / 60) % 1440;
  return `${pad(Math.floor(minute / 60))}:${pad(minute % 60)}`;
}

export function legLabel(leg: PreviewLeg, places: Preview["places"]): string {
  return [leg.departure.departure ?? "Utan avgångstid", `tåg ${leg.train}`, `${places[leg.departure.place]} → ${places[leg.arrival.place]}`].join(" · ");
}

export function legInfo(leg: PreviewLeg, state: Preview): string {
  const mode = state.sections[leg.section] === "direct" ? "Direktklarering" : "Begärd klarering";
  const track = leg.arrival.track ? ` · planerat ankomstspår ${leg.arrival.track}` : "";
  const status = leg.complete ? " · framme" : leg.blocked ? ` · ${REASONS[leg.blocked] ?? leg.blocked}` : "";
  return mode + track + status;
}

const isActive = (item: PreviewCase) => !item.arrived && (item.status === "waiting" || item.status === "approved");

/** The cases still going on first, then the last five finished, newest first. */
export function shownCases(cases: PreviewCase[]): PreviewCase[] {
  const active = cases.filter(isActive);
  const finished = cases.filter((item) => !isActive(item)).slice(-5).reverse();
  return [...active, ...finished];
}

export const caseStatus = (item: PreviewCase) => (item.arrived ? "Ankommen" : item.departed ? "På väg" : (CASES[item.status] ?? item.status));

/** What can be done with a case now, and from which place. */
export function caseActions(item: PreviewCase, places: Preview["places"]): { label: string; place: string; action: string; payload: Record<string, unknown>; checked: boolean }[] {
  const to = item.to_place;
  const from = item.from_place;
  const actions = [];
  if (item.status === "waiting") {
    actions.push({ label: `${places[to]}: Ge klart`, place: to, action: "clearance.response", payload: { clearance_id: item.id, approved: true }, checked: true });
    actions.push({ label: `${places[to]}: Neka`, place: to, action: "clearance.response", payload: { clearance_id: item.id, approved: false }, checked: true });
  }
  if (!item.departed && (item.status === "waiting" || item.status === "approved")) {
    actions.push({ label: `${places[from]}: Återkalla`, place: from, action: "clearance.cancel", payload: { clearance_id: item.id }, checked: true });
  }
  if (item.status === "approved" && !item.departed) {
    actions.push({ label: `${places[from]}: Avgå`, place: from, action: "train.departed", payload: { call: item.departure }, checked: false });
  }
  if (item.departed && !item.arrived) {
    actions.push({ label: `${places[to]}: Ankom`, place: to, action: "train.arrived", payload: { call: item.arrival }, checked: false });
  }
  return actions;
}

export type ProvbananProps = {
  /** For tests: the run and its clients, without asking the hub. */
  initial?: { state: Preview | null; clients: PreviewClients | null };
};

export function ProvbananPage({ initial }: ProvbananProps) {
  const [state, setState] = useState<Preview | null>(initial?.state ?? null);
  const [loaded, setLoaded] = useState(Boolean(initial));
  const [clients, setClients] = useState<PreviewClients | null>(initial?.clients ?? null);
  const [notice, setNotice] = useState("");
  const [chosen, setChosen] = useState("");
  const [speed, setSpeed] = useState(initial?.state ? String(initial.state.clock.speed) : "");
  const [shownSpeed, setShownSpeed] = useState(initial?.state?.clock.speed ?? null);
  const updated = useRef(0);
  const busy = useRef(false);
  const [, setTick] = useState(0);

  const show = useCallback((next: Preview) => {
    updated.current = performance.now();
    setState(next);
  }, []);

  const readClients = useCallback(async () => {
    try {
      setClients(await provbanan.clients());
    } catch {
      // The next round tries again.
    }
  }, []);

  // One thing at a time, as on the old page; a new run starts from nothing.
  const request = useCallback(
    async (action: () => Promise<Preview>, fresh = false) => {
      if (busy.current) return;
      busy.current = true;
      setNotice("");
      try {
        const next = await action();
        if (fresh) setClients(null);
        show(next);
        if (fresh) await readClients();
      } catch (error) {
        if (error instanceof Problem) setNotice(error.status === 0 ? "Kontakten med Hubben bröts. Ladda om sidan för att läsa läget." : error.message);
      } finally {
        busy.current = false;
      }
    },
    [show, readClients],
  );

  useEffect(() => {
    if (initial) return;
    void (async () => {
      try {
        const found = await provbanan.state();
        if (found) {
          show(found);
          await readClients();
        }
      } catch {
        setNotice("Kontakten med Hubben bröts. Ladda om sidan för att läsa läget.");
      }
      setLoaded(true);
    })();
  }, [initial, show, readClients]);

  // What the boxes do shows here too: the run is read again every other second.
  const running = state !== null;
  useEffect(() => {
    if (initial || !running) return;
    const poll = window.setInterval(() => {
      if (busy.current) return;
      void provbanan.state().then((next) => !busy.current && next && show(next), () => undefined);
      void readClients();
    }, 2000);
    const clock = window.setInterval(() => setTick((tick) => tick + 1), 1000);
    return () => {
      window.clearInterval(poll);
      window.clearInterval(clock);
    };
  }, [initial, running, show, readClients]);

  if (state && state.clock.speed !== shownSpeed) {
    setShownSpeed(state.clock.speed);
    setSpeed(String(state.clock.speed));
  }
  const legs = state?.legs ?? [];
  // The chosen leg stays chosen, also when it can no longer be asked for; at first, and when it
  // is gone, the first one that can be.
  const found = legs.find((leg) => leg.departure.id === chosen);
  const selected = found ?? legs.find((leg) => !leg.blocked) ?? null;
  if (!found && selected) setChosen(selected.departure.id);

  const command = (place: string, action: string, payload: Record<string, unknown>, item?: PreviewCase) => {
    if (!state) return;
    const body = {
      protocol: "trainmeet.station/1",
      message_id: crypto.randomUUID(),
      client_id: `prov-${place}`,
      place,
      context: state.context,
      action,
      payload,
      expected_revision: item ? { scope: "case", key: item.id, value: item.revision } : null,
    } as unknown as Command;
    void request(() => provbanan.command(body));
  };

  const start = () => void request(() => provbanan.start(), true);

  return (
    <div className="prov">
      <section className="kort">
        <h1>Provbanan</h1>
        <p className="ingress">Prova Drift på fyra driftplatser med måndagens tio tåg. Du agerar från den driftplats som anges på knappen.</p>
        {loaded && !state && (
          <button id="start" type="button" className="primar" onClick={start}>
            Starta provkörning
          </button>
        )}
        <p id="notice" className="meddelande" role="status" aria-live="polite">
          {notice}
        </p>
        {state && (
          <div id="run">
            <div className="rad">
              <output id="run-clock" className="provklocka" aria-label="Provkörningens klocka">
                {runClock(state, performance.now() - updated.current)}
              </output>
              <button id="toggle-clock" type="button" onClick={() => void request(() => provbanan.clock({ action: state.clock.running ? "stop" : "start", speed: null, time: null, game_day: null, jump: null }))}>
                {state.clock.running ? "Stanna klockan" : "Starta klockan"}
              </button>
              <label>
                Hastighet <input id="speed" type="number" min={0.1} max={60} step={0.1} value={speed} onChange={(event) => setSpeed(event.target.value)} />
              </label>
              <button
                id="set-speed"
                type="button"
                onClick={(event) => {
                  const field = event.currentTarget.parentElement?.querySelector<HTMLInputElement>("#speed");
                  if (field && !field.reportValidity()) return;
                  if (speed) void request(() => provbanan.clock({ action: "speed", speed: Number(speed), time: null, game_day: null, jump: null }));
                }}
              >
                Spara hastighet
              </button>
            </div>

            <h2>Tidtabell och klarering</h2>
            <p className="ingress">Prova tåg 101 från Norrby för begärd klarering. Prova tåg 102 från Sjövik för direktklarering. Välj ett tågbesök och följ ärendet till ankomst.</p>
            <div className="rad">
              <label>
                Avgång{" "}
                <select id="leg" value={selected?.departure.id ?? ""} onChange={(event) => setChosen(event.target.value)}>
                  {legs.map((leg) => (
                    <option key={leg.departure.id} value={leg.departure.id}>
                      {legLabel(leg, state.places)}
                    </option>
                  ))}
                </select>
              </label>
              <button
                id="request"
                type="button"
                disabled={!selected || Boolean(selected.blocked)}
                onClick={() => selected && command(selected.departure.place, "clearance.request", { call: selected.departure.id, section: selected.section, clearance_id: crypto.randomUUID() })}
              >
                Begär klarering
              </button>
            </div>
            <p id="leg-info" className="liten">
              {selected ? legInfo(selected, state) : ""}
            </p>

            <h2>Boxar</h2>
            <p className="ingress">
              Öppna en box i en ny flik, och anslut den med koden{" "}
              <strong id="join-code" className="tm-mono">
                {clients?.code ?? "–"}
              </strong>
              . Tilldela den sedan en driftplats här. En TKL eller TMBox-appen ansluter med samma kod och godkänns här.
            </p>
            <p>
              <a id="box-link" href={clients ? `/provbanan/box#kod=${clients.code}` : "/provbanan/box"} target="_blank" rel="noopener">
                Öppna en box →
              </a>
            </p>
            <ul id="clients" className="lista">
              {clients?.clients.length ? (
                clients.clients.map((client) => <PreviewClient key={client.client_id} client={client} state={state} onChange={(action) => void act(action, setClients, setNotice)} />)
              ) : (
                <li className="tom">Inga boxar anslutna ännu.</li>
              )}
            </ul>

            <h2>Klareringar</h2>
            <ul id="cases" className="lista">
              {state.cases.length ? (
                shownCases(state.cases).map((item) => (
                  <li key={item.id}>
                    <div className="vem">
                      <b>{`Tåg ${item.train} · ${state.places[item.from_place]} → ${state.places[item.to_place]}`}</b>
                      <span className="liten">{caseStatus(item)}</span>
                    </div>
                    <div className="kontroller">
                      {caseActions(item, state.places).map((action) => (
                        <button key={action.label} type="button" onClick={() => command(action.place, action.action, action.payload, action.checked ? item : undefined)}>
                          {action.label}
                        </button>
                      ))}
                    </div>
                  </li>
                ))
              ) : (
                <li className="tom">Inga klareringar ännu.</li>
              )}
            </ul>
            <button id="restart" type="button" onClick={start}>
              Ny provkörning
            </button>
          </div>
        )}
      </section>
      <p className="liten">Din provkörning sparas i ett dygn i den här webbläsaren.</p>
    </div>
  );
}

type PreviewAction =
  | { action: "assign"; client: Client; place: string; side: Client["side"]; language: string }
  | { action: "approve"; client: Client; place: string }
  | { action: "revoke"; client: Client }
  | { action: "exit"; client: Client; section: string; exit: string };

async function act(change: PreviewAction, setClients: (clients: PreviewClients) => void, setNotice: (text: string) => void) {
  setNotice("");
  try {
    const id = change.client.client_id;
    if (change.action === "assign") setClients(await provbanan.assign({ client_id: id, places: [change.place], side: change.side, language: change.language as never }));
    if (change.action === "approve") setClients(await provbanan.approve({ client_id: id, places: [change.place] }));
    if (change.action === "revoke") setClients(await provbanan.revoke({ client_id: id }));
    if (change.action === "exit") setClients(await provbanan.coupleExit({ client_id: id, section: change.section, exit: change.exit }));
  } catch (error) {
    if (error instanceof Problem) setNotice(error.message);
  }
}

/** A box gets a place, a side and a language; TKL and the TMBox app are approved (H31). */
function PreviewClient({ client, state, onChange }: { client: Client; state: Preview; onChange: (change: PreviewAction) => void }) {
  const places: [string, string][] = state.stations.map((id) => [id, state.places[id] ?? id]);
  const at = client.places ?? [];
  const [place, setPlace] = useState(at[0] ?? places[0]?.[0] ?? "");
  const [side, setSide] = useState<Client["side"]>(client.side);
  const [language, setLanguage] = useState<string>(client.language ?? "sv");
  const named = at.map((id) => state.places[id] ?? id).join(", ");
  if (client.kind === "tmbox_web") {
    const where = at.length ? `Tilldelad ${named}${client.side === "both" ? "" : ` · ${SIDES[client.side].toLowerCase()}`}` : "Väntar på tilldelning";
    const size = client.display ? ` · ${client.display.cols}×${client.display.rows}` : "";
    return (
      <li>
        <div className="vem">
          <b>{client.name}</b>
          <span className="liten">{where + size}</span>
        </div>
        <div className="kontroller">
          <Select label={`Driftplats för ${client.name}`} options={places} value={place} onChange={setPlace} />
          {/* Left and right as the box shows the place; both, the default, is the whole place. */}
          <Select label={`Sida för ${client.name}`} options={Object.entries(SIDES)} value={side} onChange={(value) => setSide(value as Client["side"])} />
          <Select label={`Språk för ${client.name}`} options={Object.entries(LANGUAGES)} value={language} onChange={setLanguage} />
          <button type="button" onClick={() => onChange({ action: "assign", client, place, side, language })}>
            {at.length ? "Ändra" : "Tilldela"}
          </button>
        </div>
      </li>
    );
  }
  return (
    <li className={client.status === "waiting" ? "vantar" : undefined}>
      <div className="vem">
        <b>{`${client.name} (${KINDS[client.kind] ?? client.kind})`}</b>
        <span className="liten">{(APPROVAL[client.status] ?? client.status) + (client.status === "approved" ? ` ${named}` : "")}</span>
      </div>
      <div className="kontroller">
        {client.status === "approved" ? (
          <button type="button" className="fara" onClick={() => onChange({ action: "revoke", client })}>
            Återkalla
          </button>
        ) : (
          <>
            <Select label={`Driftplats för ${client.name}`} options={places} value={place} onChange={setPlace} />
            <button type="button" onClick={() => onChange({ action: "approve", client, place })}>
              Godkänn
            </button>
          </>
        )}
      </div>
      <ExitQuestions client={client} onAnswer={(section, exit) => onChange({ action: "exit", client, section, exit })} />
    </li>
  );
}
