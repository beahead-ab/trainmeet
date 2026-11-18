// TrainMeet TKL's web app. Ställverket, Studio and Inställningar under one header; first start
// and the PIN lock before anything else (TKL18). Ställverket is level 0's list without a station
// model, and the panel at level 1–2 with one (#84). The place's snapshot is fetched when the hub
// hints that it changed, and every ten seconds besides; the last good one stays, marked old,
// when the hub cannot be reached.
import { BottomNav, Header, type NavItem } from "@trainmeet/design";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, full, Problem, TKL, type Action, type CallHere, type Clearance, type Connection, type FoundHub, type Snapshot, type State, type Studio as StudioData, type View } from "./api";
import { FirstStart, Locked } from "./Forsta";
import { happenings, type Happening } from "./handelser";
import { Installningar, type Part } from "./Installningar";
import { play, readSounds, saveSounds, type Sounds } from "./ljud";
import { clockAt, revisionOf } from "./niva0";
import { Sparplan } from "./Sparplan";
import { StallverketSida } from "./Stallverk12";
import { Stallverket } from "./Stallverket";
import { Studio } from "./Studio";

type Page = "stallverket" | "studio" | "installningar";
const PAGES: Record<Page, string> = { stallverket: "/", studio: "/studio", installningar: "/installningar" };
const pageOf = (path: string): Page => (path.startsWith("/studio") ? "studio" : path.startsWith("/installningar") ? "installningar" : "stallverket");
const SPARPLAN = "/studio/sparplan";
const REFRESH_MS = 10_000;
const REQUEST_AGAIN_MS = 30_000;

export function App() {
  const [state, setState] = useState<State | null>(null);
  const [page, setPage] = useState<Page>(pageOf(location.pathname));
  const [path, setPath] = useState(location.pathname);
  const [message, setMessage] = useState("");
  useEffect(() => {
    api
      .state()
      .then(setState)
      .catch((error: unknown) => setMessage(error instanceof Error ? error.message : "TKL svarar inte."));
    const back = () => {
      setPage(pageOf(location.pathname));
      setPath(location.pathname);
    };
    addEventListener("popstate", back);
    return () => removeEventListener("popstate", back);
  }, []);
  const navigate = (href: string) => {
    history.pushState(null, "", href);
    setPage(pageOf(href));
    setPath(href);
  };
  if (!state) return <p className="tom">{message || "Startar TKL …"}</p>;
  if (!state.set_up) {
    return (
      <Frame state={state} page={page} navigate={navigate}>
        <FirstStart cloud={state.mode === "cloud"} onSetUp={async (name, station_id, pin) => setState(await api.setUp({ name, station_id, pin }))} />
      </Frame>
    );
  }
  if (!state.unlocked) {
    return (
      <Frame state={state} page={page} navigate={navigate}>
        <Locked state={state} onUnlock={async (pin) => setState(await api.unlock(pin))} />
      </Frame>
    );
  }
  return <Unlocked state={state} page={page} path={path} navigate={navigate} onLocked={setState} />;
}

function Frame({ state, page, navigate, connection, clock, onLock, children }: { state: State; page: Page; navigate: (href: string) => void; connection?: Connection | null; clock?: string; onLock?: () => void; children: React.ReactNode }) {
  const open = state.set_up && state.unlocked;
  const tabs: NavItem[] = open
    ? [
        { href: PAGES.stallverket, label: "Ställverket", current: page === "stallverket" },
        { href: PAGES.studio, label: "Studio", current: page === "studio" },
        { href: PAGES.installningar, label: "Inställningar", current: page === "installningar" },
      ]
    : [];
  const approved = connection?.connected && connection.status === "approved";
  return (
    <>
      <Header product="TKL" productLabel="TKL" place={state.station?.name ?? "Ny station"} home="/" navLabel="TKL" tabs={tabs} navigate={navigate}>
        {connection?.connected ? (
          <span className={`tm-chip ${approved ? "gron" : "gul"}`}>
            {connection.hub_name ?? "Hubben"} · {approved ? "godkänd" : connection.status === "waiting" ? "väntar" : "inte godkänd"}
          </span>
        ) : null}
        {clock ? <span className="klocka tm-mono">{clock}</span> : null}
        {onLock ? (
          <button type="button" className="lank ljus" onClick={onLock}>
            Lås
          </button>
        ) : null}
      </Header>
      <main className="tkl">{children}</main>
      {open ? <BottomNav items={tabs} label="TKL" navigate={navigate} /> : null}
    </>
  );
}

function Unlocked({ state, page, path, navigate, onLocked }: { state: State; page: Page; path: string; navigate: (href: string) => void; onLocked: (state: State) => void }) {
  const [connection, setConnection] = useState<Connection | null>(null);
  const [studio, setStudio] = useState<StudioData | null>(null);
  const [view, setView] = useState<View | null>(null);
  const [heardAt, setHeardAt] = useState(0);
  const [journal, setJournal] = useState<Happening[]>([]);
  const [hubs, setHubs] = useState<FoundHub[] | null>(null);
  const [sounds, setSounds] = useState<Sounds>(readSounds());
  const [part, setPart] = useState<Part>("anslutning");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [, tick] = useState(0);
  const last = useRef<Snapshot | null>(null);
  const soundsRef = useRef(sounds);
  soundsRef.current = sounds;
  const place = connection?.status === "approved" ? (connection.places?.[0] ?? null) : null;

  const fail = (error: unknown) => {
    if (error instanceof Problem && error.status === 401 && /PIN/.test(error.message)) {
      void api.state().then(onLocked);
      return;
    }
    setNotice(error instanceof Error ? error.message : "Något gick fel.");
  };

  const show = useCallback((next: View) => {
    setView(next);
    if (next.snapshot && !next.stale) {
      setHeardAt(Date.now());
      const found = happenings(last.current, next.snapshot);
      last.current = next.snapshot;
      if (found.length) {
        setJournal((before) => [...found, ...before].slice(0, 200));
        for (const sound of new Set(found.map((h) => h.sound).filter((s) => !!s))) if (sound) play(sound, soundsRef.current);
      }
    }
  }, []);

  const readPlace = useCallback(async () => {
    if (!place) return;
    try {
      show(await api.place(place));
    } catch (error) {
      if (error instanceof Problem && (error.status === 401 || error.status === 409)) {
        setConnection(await api.connection());
      }
      if (!(error instanceof Problem && error.status === 0)) setNotice(error instanceof Error ? error.message : "");
    }
  }, [place, show]);

  useEffect(() => {
    api.connection().then(setConnection).catch(fail);
    api.studio().then(setStudio).catch(fail);
    const second = setInterval(() => tick((n) => n + 1), 1000);
    return () => clearInterval(second);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // While TKL waits for approval, ask how it stands every few seconds.
  useEffect(() => {
    if (!connection?.connected || connection.status !== "waiting") return;
    const waiting = setInterval(() => api.connection().then(setConnection).catch(() => undefined), 3000);
    return () => clearInterval(waiting);
  }, [connection?.connected, connection?.status]);

  // The place: at once, on every hint from the hub, and every ten seconds.
  useEffect(() => {
    if (!place) return;
    void readPlace();
    const every = setInterval(() => void readPlace(), REFRESH_MS);
    const hints = typeof EventSource === "undefined" ? null : new EventSource(`${TKL}/places/${encodeURIComponent(place)}/events`);
    hints?.addEventListener("changed", () => void readPlace());
    return () => {
      clearInterval(every);
      hints?.close();
    };
  }, [place, readPlace]);

  // An unanswered request rings again every 30 seconds (old TKL).
  useEffect(() => {
    const waiting = view?.snapshot?.clearances.some((c) => c.to_place === view.snapshot?.place.place && c.status === "waiting");
    if (!waiting) return;
    const again = setInterval(() => play("request", soundsRef.current), REQUEST_AGAIN_MS);
    return () => clearInterval(again);
  }, [view]);

  useEffect(() => {
    if (page === "installningar" && part === "anslutning" && !connection?.connected && hubs === null) {
      api.hubs().then(setHubs).catch(() => setHubs([]));
    }
  }, [page, part, connection?.connected, hubs]);

  const send = async (action: Action, payload: Record<string, unknown>, call?: CallHere, clearance?: Clearance) => {
    const snapshot = view?.snapshot;
    if (!snapshot || !place) return;
    setBusy(true);
    setNotice("");
    try {
      const reply = await api.command({
        message_id: `tkl-${crypto.randomUUID()}`,
        place,
        context: snapshot.context,
        action,
        expected_revision: revisionOf(action, call, clearance),
        payload,
      });
      show({ snapshot: full(reply.snapshot), stale: false, heard: new Date().toISOString(), message: null });
      if (reply.status === "rejected") setNotice(reply.message ?? "Hubben sa nej.");
    } catch (error) {
      fail(error);
    } finally {
      setBusy(false);
    }
  };

  const answerExit = async (section: string, exit: string) => {
    if (!place) return;
    try {
      show(await api.answerExit(place, section, exit));
    } catch (error) {
      fail(error);
    }
  };

  const snapshot = view?.snapshot ?? null;
  const clock = snapshot ? clockAt(snapshot, heardAt, Date.now()) : undefined;
  let body;
  if (page === "studio") {
    const plan = path.startsWith(SPARPLAN);
    body = (
      <>
        <nav className="studio-flikar" aria-label="Studio">
          <button type="button" aria-current={plan ? undefined : "page"} onClick={() => navigate(PAGES.studio)}>
            Utsidan
          </button>
          <button type="button" aria-current={plan ? "page" : undefined} onClick={() => navigate(SPARPLAN)}>
            Spårplan
          </button>
        </nav>
        {plan ? (
          <Sparplan
            onChanged={() => {
              void api.state().then(onLocked);
              void api.studio().then(setStudio);
            }}
          />
        ) : studio ? (
          <Studio
            key={`${studio.versions?.[0]?.number ?? 0}-${studio.station_model ? "modell" : "lista"}`}
            studio={studio}
            onSave={async (outside) => setStudio(await api.saveList(outside))}
            onVersion={async () => setStudio(await api.newVersion())}
          />
        ) : (
          <p className="tom">Läser listan …</p>
        )}
      </>
    );
  } else if (page === "installningar") {
    body = (
      <Installningar
        part={part}
        state={state}
        connection={connection}
        hubs={hubs}
        questions={snapshot?.questions ?? []}
        sounds={sounds}
        version={studio?.versions?.[0]?.number ?? null}
        onPart={setPart}
        onFind={() => {
          setHubs(null);
          api.hubs().then(setHubs).catch(() => setHubs([]));
        }}
        onConnect={async (address, code) => {
          setConnection(await api.connect(address, code));
          setStudio(await api.studio());
          setJournal([]);
          last.current = null;
        }}
        onDisconnect={async () => {
          setConnection(await api.disconnect());
          setView(null);
          setHubs(null);
        }}
        onExit={(section, exit) => void answerExit(section, exit)}
        onSounds={(next) => {
          setSounds(next);
          saveSounds(next);
        }}
        onPin={async (old, pin) => api.changePin(old, pin)}
      />
    );
  } else if ((state.station?.level ?? 0) >= 1) {
    // Level 1–2 (#84): the panel works on the station's own computer with or without the meet;
    // Tåg and Klarering need the hub, and say so when it is not there.
    const hubNote = !connection?.connected
      ? "TKL är inte ansluten till en träff. Anslut i Inställningar › Anslutning."
      : connection.status !== "approved"
        ? connection.status === "waiting"
          ? "Väntar på att trafikledningen godkänner TKL i Klienter."
          : (connection.message ?? "TKL är inte godkänd. Anslut igen.")
        : view
          ? null
          : `Hämtar ${place} från hubben …`;
    body = (
      <StallverketSida
        level={state.station?.level ?? 0}
        view={connection?.status === "approved" ? view : null}
        hubNote={hubNote}
        outside={studio?.draft ?? null}
        journal={journal}
        sounds={sounds}
        busy={busy}
        onSend={(a, p, c, cl) => void send(a, p, c, cl)}
        onExit={(s, e) => void answerExit(s, e)}
      />
    );
  } else if (!connection?.connected) {
    body = <NotConnected onGo={() => navigate(PAGES.installningar)} text="TKL är inte ansluten till en träff." />;
  } else if (connection.status !== "approved") {
    body = (
      <NotConnected
        onGo={() => navigate(PAGES.installningar)}
        text={connection.status === "waiting" ? "Väntar på att trafikledningen godkänner TKL i Klienter." : connection.message ?? "TKL är inte godkänd. Anslut igen."}
      />
    );
  } else if (view) {
    body = <Stallverket view={view} outside={studio?.draft ?? null} journal={journal} sounds={sounds} busy={busy} onSend={(a, p, c, cl) => void send(a, p, c, cl)} onExit={(s, e) => void answerExit(s, e)} />;
  } else {
    body = <p className="tom">Hämtar {place} från hubben …</p>;
  }
  return (
    <Frame state={state} page={page} navigate={navigate} connection={connection} clock={clock} onLock={() => void api.lock().then(onLocked)}>
      {notice ? (
        <p className="notis" role="alert">
          {notice}{" "}
          <button type="button" className="lank" onClick={() => setNotice("")}>
            Stäng
          </button>
        </p>
      ) : null}
      {body}
    </Frame>
  );
}

function NotConnected({ text, onGo }: { text: string; onGo: () => void }) {
  return (
    <div className="tom-sida">
      <p>{text}</p>
      <button type="button" className="primar" onClick={onGo}>
        Inställningar › Anslutning
      </button>
    </div>
  );
}
