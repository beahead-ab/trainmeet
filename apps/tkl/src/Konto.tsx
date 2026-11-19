// TKL i molnet (#88, TKL5, TKLMOLN-01–TKLMOLN-11): the station belongs to the account in
// TrainMeet ID. TKL starts with Logga in med TrainMeet ID instead of first start and the PIN, one
// login for everything (TKLMOLN-10). Dina stationer lists the account's station packages in
// Hubbens Synk; Öppna reads the latest version into this browser's working copy, and Ny station
// saves version 1 in Synk at once. The account row says which version the working copy builds on
// and whether it has changes not saved yet; Spara i molnet writes the next version, and a save on
// top of a newer one is refused with the choice Läs in den nya or Spara ändå ovanpå (H71,
// TKLMOLN-09). Nothing the owner needs lives only in the working copy.
import { useEffect, useState, type FormEvent } from "react";
import { api, type CloudStation, type CloudStations, type Saved, type State } from "./api";
import { FirstStartRemote } from "./Fjarr";
import { shortId } from "./Forsta";
import "./konto.css";

const ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$/;
export const LOGIN = "/api/tkl/1/id/login";
/** Dina stationer, also while a station is open: a path of its own in the web app. */
export const STATIONER = "/stationer";

/** When a station was saved, as the owner reads it. */
export function savedAt(iso: string): string {
  return new Date(iso).toLocaleString("sv-SE", { dateStyle: "medium", timeStyle: "short" });
}

/** The account row's words about the working copy (TKLMOLN-07). */
export function copySaid(base: number | null | undefined, changed: boolean): string {
  if (!base) return changed ? "inte sparad i molnet än" : "inte sparad i molnet";
  return `version ${base} i molnet${changed ? " · osparade ändringar" : " · sparad"}`;
}

/** Logga in med TrainMeet ID (TKLMOLN-01): the first thing TKL in the cloud shows, and how a
 * working copy locked with Lås is opened again. A plain link: TKL's server goes to ID. */
export function Inloggning({ state, failed = false }: { state: State; failed?: boolean }) {
  const locked = state.set_up && !state.unlocked;
  return (
    <section className="inloggning">
      <p className="overrad">TKL i molnet</p>
      <h1>{state.locked ? `${state.station?.name ?? "TKL"} är låst.` : locked ? "Logga in med TrainMeet ID igen." : "Logga in med TrainMeet ID."}</h1>
      <p>
        {locked
          ? "Logga in med TrainMeet ID igen för att låsa upp. Inloggningen är samma för allt; TKL i molnet har ingen PIN-kod."
          : "Dina stationer ligger i molnet och följer med dig till varje dator och platta. En inloggning för allt, ingen PIN-kod."}
      </p>
      {state.locked ? <p className="liten">Låst för stationen i den här webbläsaren: också Stream Deck visar bara klockan (SD30).</p> : null}
      {failed ? (
        <p className="fel" role="alert">
          Inloggningen gick inte. Försök igen.
        </p>
      ) : null}
      <a id="id-login" className="knapp primar" href={LOGIN}>
        Logga in med TrainMeet ID
      </a>
      <p className="liten">En TKL på stationens egen dator har kvar sin PIN och sin egen station, och kan köra samtidigt (TKLMOLN-04). LocoNet finns bara där.</p>
    </section>
  );
}

type ListProps = {
  person: string;
  stations: CloudStation[] | null;
  open: string | null;
  openName: string | null;
  changed: boolean;
  busy: boolean;
  message: string;
  onOpen: (stationId: string) => void;
  onNew: (name: string, stationId: string) => void;
  onRemote: () => void;
  onBack: (() => void) | null;
};

/** Dina stationer (TKLMOLN-02): the account's station packages in Synk, the latest version of
 * each, with Öppna, and Ny station. Pure, for the tests. */
export function DinaStationerVy({ person, stations, open, openName, changed, busy, message, onOpen, onNew, onRemote, onBack }: ListProps) {
  return (
    <div className="dina-stationer">
      <div className="sidrubrik">
        <p className="overrad">TKL i molnet · {person}</p>
        <h1>Dina stationer</h1>
        <p className="liten">Stationerna ligger i molnet, i Hubbens Synk. Öppna läser in den senaste versionen här; Spara i molnet gör nästa.</p>
      </div>
      {changed && openName ? (
        <p className="notis varning" role="alert">
          {`${openName} har ändringar som inte är sparade i molnet. De försvinner om du öppnar en station här; spara dem först.`}
        </p>
      ) : null}
      {message ? (
        <p className="fel" role="alert">
          {message}
        </p>
      ) : null}
      <section className="ruta">
        {stations === null ? (
          <p className="tom">Hämtar dina stationer …</p>
        ) : stations.length ? (
          <ul className="stationslista">
            {stations.map((s) => (
              <li key={s.station_id} className={s.station_id === open ? "oppen" : undefined}>
                <div>
                  <b>{s.name}</b> <span className="tm-mono liten">{s.station_id}</span>
                  <span className="liten">{` · version ${s.version} · sparad ${savedAt(s.saved)}`}</span>
                  {s.station_id === open ? <span className="tm-chip gron">Öppen här</span> : null}
                </div>
                <button type="button" className={s.station_id === open ? undefined : "primar"} disabled={busy} onClick={() => onOpen(s.station_id)}>
                  {s.station_id === open ? "Läs in igen" : "Öppna"}
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="tom">Du har inga stationer i molnet än. Skapa en nedan.</p>
        )}
      </section>
      <NyStation busy={busy} onNew={onNew} />
      <p className="liten">
        Eller{" "}
        <button type="button" className="lank" onClick={onRemote}>
          gör den här webbläsaren till ett fjärrställverk (ingen egen station)
        </button>
        .
      </p>
      {onBack ? (
        <button type="button" onClick={onBack}>
          Tillbaka till {openName ?? "stationen"}
        </button>
      ) : null}
    </div>
  );
}

function NyStation({ busy, onNew }: { busy: boolean; onNew: (name: string, stationId: string) => void }) {
  const [name, setName] = useState("");
  const [stationId, setStationId] = useState("");
  const [touched, setTouched] = useState(false);
  const id = touched ? stationId : shortId(name);
  const ready = name.trim().length > 0 && ID_PATTERN.test(id);
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (ready) onNew(name.trim(), id);
  };
  return (
    <form className="ruta ny-station" onSubmit={submit}>
      <h2>Ny station</h2>
      <label>
        Namn
        <input id="ny-station-namn" value={name} onChange={(e) => setName(e.target.value)} maxLength={40} autoComplete="off" />
      </label>
      <label>
        Kort namn
        <input
          id="ny-station-id"
          value={id}
          onChange={(e) => {
            setTouched(true);
            setStationId(e.target.value);
          }}
          maxLength={80}
          autoComplete="off"
          className="tm-mono"
        />
      </label>
      <p className="liten">Stationens id, som följer den till varje träff. Version 1 sparas i molnet direkt.</p>
      <button id="ny-station" type="submit" className="primar" disabled={busy || !ready}>
        Skapa och spara i molnet
      </button>
    </form>
  );
}

/** Dina stationer with its calls; a new state when a station is opened or made. */
export function DinaStationer({ state, onState, onBack }: { state: State; onState: (state: State) => void; onBack: (() => void) | null }) {
  const [listed, setListed] = useState<CloudStations | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [remote, setRemote] = useState(false);
  useEffect(() => {
    api.cloudStations().then(setListed, (error: unknown) => setMessage(error instanceof Error ? error.message : "Dina stationer gick inte att hämta."));
  }, []);
  const doing = async (work: () => Promise<State>) => {
    setBusy(true);
    setMessage("");
    try {
      onState(await work());
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Det gick inte.");
    } finally {
      setBusy(false);
    }
  };
  if (remote) {
    return (
      <>
        <FirstStartRemote cloud pinless onSetUp={async (name, area, places) => onState(await api.remoteSetUpInCloud(name, area, places))} />
        <button type="button" className="lank" onClick={() => setRemote(false)}>
          Tillbaka till Dina stationer
        </button>
      </>
    );
  }
  return (
    <DinaStationerVy
      person={state.account?.person ?? ""}
      stations={listed ? (listed.stations ?? []) : message ? [] : null}
      open={listed?.open ?? null}
      openName={state.station?.name ?? null}
      changed={!!state.account?.changed}
      busy={busy}
      message={message}
      onOpen={(stationId) => void doing(() => api.openStation(stationId))}
      onNew={(name, stationId) => void doing(() => api.newStation(name, stationId))}
      onRemote={() => setRemote(true)}
      onBack={onBack}
    />
  );
}

type RowProps = {
  state: State;
  saved: Saved | null;
  busy: boolean;
  message: string;
  onSave: (onTop: number | null) => void;
  onReadNew: () => void;
  onStations: () => void;
};

/** The account row over the pages (TKLMOLN-07): who is logged in, the version in Synk the
 * working copy builds on, Spara i molnet, and the choice when the cloud has a newer version.
 * Pure, for the tests. */
export function KontoradVy({ state, saved, busy, message, onSave, onReadNew, onStations }: RowProps) {
  const account = state.account;
  if (!account) return null;
  const behind = saved?.behind ?? null;
  return (
    <div className="kontorad" aria-label="Stationen i molnet">
      <div className="rad">
        <span>
          <b>{state.station?.name ?? "Stationen"}</b> <span className="liten">{copySaid(account.base, !!account.changed)}</span>
        </span>
        <span className="tm-fyll" />
        <span className="liten">{account.person}</span>
        <button type="button" className="lank" onClick={onStations}>
          Dina stationer
        </button>
        <button id="spara-i-molnet" type="button" className="primar" disabled={busy || (!account.changed && !!account.base)} onClick={() => onSave(null)}>
          Spara i molnet
        </button>
      </div>
      {saved?.version ? (
        <p id="sparad" className="liten" role="status">
          {`Sparad som version ${saved.version} i molnet.`}
        </p>
      ) : null}
      {behind ? (
        <div className="varning valet" role="alert">
          <p>{saved?.message ?? `Molnet har version ${behind}, som är nyare än den du arbetar i.`}</p>
          <div className="knappar">
            <button id="las-in-den-nya" type="button" className="primar" disabled={busy} onClick={onReadNew}>
              {`Läs in den nya (version ${behind})`}
            </button>
            <button id="spara-anda-ovanpa" type="button" disabled={busy} onClick={() => onSave(behind)}>
              {`Spara ändå ovanpå version ${behind}`}
            </button>
          </div>
          <p className="liten">Läs in den nya tar bort ändringarna här. Spara ändå ovanpå gör stationen här till den som gäller, som en ny version efter den andra.</p>
        </div>
      ) : null}
      {message ? (
        <p className="fel" role="alert">
          {message}
        </p>
      ) : null}
    </div>
  );
}

/** How often the account row asks whether the working copy has changed: every page of Studio
 * changes it in its own way, and the row follows without each of them telling it. */
const FOLLOW_MS = 3000;

/** The account row with its calls. */
export function Kontorad({ state, onState, onOpened, onStations }: { state: State; onState: (state: State) => void; onOpened: (state: State) => void; onStations: () => void }) {
  const [saved, setSaved] = useState<Saved | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const changed = !!state.account?.changed;
  const base = state.account?.base ?? null;
  useEffect(() => {
    const look = () =>
      void api.state().then(
        (next) => {
          if (!!next.account?.changed !== changed || (next.account?.base ?? null) !== base || next.unlocked !== state.unlocked) onState(next);
        },
        () => undefined,
      );
    const every = setInterval(look, FOLLOW_MS);
    addEventListener("focus", look);
    return () => {
      clearInterval(every);
      removeEventListener("focus", look);
    };
  }, [changed, base, state.unlocked, onState]);
  const save = async (onTop: number | null) => {
    setBusy(true);
    setMessage("");
    try {
      setSaved(await api.saveInCloud(onTop));
      onState(await api.state());
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Det gick inte att spara i molnet.");
    } finally {
      setBusy(false);
    }
  };
  const readNew = async () => {
    const id = state.station?.station_id;
    if (!id) return;
    setBusy(true);
    setMessage("");
    try {
      onOpened(await api.openStation(id));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Det gick inte att läsa in den nya.");
    } finally {
      setBusy(false);
    }
  };
  return <KontoradVy state={state} saved={saved} busy={busy} message={message} onSave={(onTop) => void save(onTop)} onReadNew={() => void readNew()} onStations={onStations} />;
}
