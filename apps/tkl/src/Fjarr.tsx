// Fjärrstyrning i TKL (#36 del c). TKL started in the remote role is a remote interlocking with no
// station of its own (FR1, TKL47): first start offers it next to the station, it connects as the
// client kind remote with its remote area and waits for Trafikledningen's approval (FR4), and its
// pages are Fjärrbild, Tåg och klarering and Inställningar. A station's own TKL has the same pages
// under its tab Fjärr when it controls a neighbour or a neighbour is offered to it (FR3).
//
// Fjärrställverket på tre skärmar: the fjärrbild on one screen, Tåg och klarering on another,
// each kept per screen in this browser as TKL's screens are (?skarm=2). On one screen the
// fjärrbild has Väntar på dig, the routes and the stations, and Händelser under it, as the
// concept's overview. The station's own picture in detail stays the station's (its inside never
// leaves it).
//
// A station with parts forwards its parts' requests and its list Klara att skicka while it is
// remote-controlled (#36 del d, FR50, FR51): Väntar på dig answers a request with part.answer,
// and Klara att skicka moves a train with ready.move and marks it with ready.sent. The button
// Stream Deck opens the fjärrtågklarerare's deck on the screen, as in Ställverket (SD37).
//
// The fjärrbild is read from TKL's server every two seconds, every second while a route waits
// for its answer, and every ten while the page is hidden: Hubben's overview has no revision
// counter yet, and reading it keeps the one who remote-controls heard (FR28). Every button sends a station
// command; Hubben's answer and the stations' reports are what the screen shows (FR13).
import { BottomNav, Header, type NavItem } from "@trainmeet/design";
import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { api, full, Problem, type Action, type CallHere, type Clearance, type Connection, type FoundHub, type State, type View } from "./api";
import { choose, drawPicture, fjarrHappenings, myRoutes, partAsks, readyLists, reasonText, routeLabel, routeOf, sentState, type Choice, type FjarrHappening, type Hit, type Sent } from "./fjarr";
import { fjarrApi, type Fjarr, type RemoteAreas } from "./fjarrapi";
import { FjarrbildView, KlaraAttSkicka, Lagda, Teckenforklaring, Vantar, type Notice } from "./Fjarrbild";
import { FirstStart } from "./Forsta";
import { happenings, type Happening } from "./handelser";
import { Pin } from "./Installningar";
import { revisionOf } from "./niva0";
import { screenNumber } from "./skal";
import { Handelser, Klarering, Tag } from "./Stallverket";
import { DeckPanel } from "./Deck";
import { readDeck, REMOTE_ROLE, saveDeck } from "./deck";
import "./fjarr.css";
import { ProvChip } from "./Provmarkering";

const EVERY_MS = 2000;
const WAITING_MS = 1000;
/** While the page is hidden the picture is read seldom, but often enough that Hubben still hears
 * the one who remote-controls (45 seconds, FR28). */
const HIDDEN_MS = 10_000;
const NOTICE_MS = 8000;
const PLACE_MS = 5000;

/** The meet's clock as the picture was read, running on between two reads (as niva0's clockAt). */
export function clockOf(clock: { seconds: number; running: boolean; speed: number }, heardMs: number, nowMs: number): string {
  const seconds = clock.running ? clock.seconds + ((nowMs - heardMs) / 1000) * clock.speed : clock.seconds;
  const minutes = Math.floor(seconds / 60);
  return `${String(Math.floor(minutes / 60) % 24).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}`;
}

const requestId = () => `fj-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
const messageId = () => `fj-${typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : requestId()}`;

// --- Första start ------------------------------------------------------------------------------

/** Första start: the station's interlocking, or a remote interlocking with no station (FR1). */
export function FirstStartChoice({ cloud, onSetUp, onRemote }: { cloud: boolean; onSetUp: (name: string, stationId: string, pin: string) => Promise<void>; onRemote: (name: string, area: string | null, places: string[], pin: string) => Promise<void> }) {
  const [role, setRole] = useState<"station" | "remote">("station");
  return (
    <>
      <div className="fj-roll" role="radiogroup" aria-label="Vad den här datorn blir">
        <button type="button" role="radio" aria-checked={role === "station"} onClick={() => setRole("station")}>
          Stationens ställverk
        </button>
        <button type="button" role="radio" aria-checked={role === "remote"} onClick={() => setRole("remote")}>
          Fjärrställverk (ingen egen station)
        </button>
      </div>
      {role === "station" ? <FirstStart cloud={cloud} onSetUp={onSetUp} /> : <FirstStartRemote cloud={cloud} onSetUp={onRemote} />}
    </>
  );
}

const ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$/;
export const placesIn = (text: string): string[] => [...new Set(text.split(/[\s,;]+/).filter((p) => p.length > 0))];

/** pinless: TKL in the cloud with TrainMeet ID, where the login locks and opens (#88). */
export function FirstStartRemote({ cloud, pinless = false, onSetUp }: { cloud: boolean; pinless?: boolean; onSetUp: (name: string, area: string | null, places: string[], pin: string) => Promise<void> }) {
  const [name, setName] = useState("");
  const [area, setArea] = useState("");
  const [places, setPlaces] = useState("");
  const [pin, setPin] = useState("");
  const [again, setAgain] = useState("");
  const [message, setMessage] = useState("");
  const written = placesIn(places);
  const same = pinless || (/^[0-9]{4,12}$/.test(pin) && pin === again);
  const ready = name.trim().length > 0 && (!area.trim() || ID.test(area.trim())) && written.every((p) => ID.test(p)) && same;
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!ready) return;
    setMessage("");
    try {
      await onSetUp(name.trim(), area.trim() || null, written, pin);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Det gick inte.");
    }
  };
  return (
    <form className="forsta" onSubmit={submit}>
      <p className="overrad">Första start · fjärrställverk</p>
      <h1>Gör den här datorn till ett fjärrställverk.</h1>
      <p>Fjärrställverket har ingen egen station. Det styr ett fjärrområde av stationer i serie längs linjen, när stationerna lämnar över till det.</p>
      {cloud ? <p className="liten">{pinless ? "TKL i molnet: fjärrställverket hör till den här webbläsaren, och inloggningen med TrainMeet ID låser upp det." : "TKL i molnet utan TrainMeet ID: fjärrställverket hör till den här webbläsaren."}</p> : null}
      <div className="rutor">
        <fieldset className="ruta">
          <legend>1 · Fjärrställverket</legend>
          <label>
            Namn
            <input value={name} onChange={(e) => setName(e.target.value)} maxLength={40} autoComplete="off" placeholder="Fjärr Väster" required />
          </label>
          <label>
            Fjärrområde
            <input value={area} onChange={(e) => setArea(e.target.value)} maxLength={80} autoComplete="off" className="tm-mono" />
          </label>
          <label>
            Driftplatser
            <input value={places} onChange={(e) => setPlaces(e.target.value)} autoComplete="off" className="tm-mono" />
          </label>
          <p className="liten">Planens fjärrområde, eller driftplatserna i ordning längs linjen. Båda går att välja när TKL ansluter.</p>
        </fieldset>
        {pinless ? null : (
          <fieldset className="ruta">
            <legend>2 · PIN</legend>
            <label>
              Välj PIN
              <input value={pin} onChange={(e) => setPin(e.target.value.replace(/\D/g, ""))} inputMode="numeric" type="password" autoComplete="new-password" maxLength={12} />
            </label>
            <label>
              Skriv den igen
              <input value={again} onChange={(e) => setAgain(e.target.value.replace(/\D/g, ""))} inputMode="numeric" type="password" autoComplete="new-password" maxLength={12} />
            </label>
            <p className="liten">{same ? "✓ Lika. " : again ? "Inte lika än. " : ""}Minst fyra siffror.</p>
          </fieldset>
        )}
      </div>
      {message ? (
        <p className="fel" role="alert">
          {message}
        </p>
      ) : null}
      <button type="submit" className="primar" disabled={!ready}>
        {pinless ? "Starta fjärrställverket" : "Lås med PIN och starta fjärrställverket"}
      </button>
    </form>
  );
}

// --- The remote interlocking's own app ---------------------------------------------------------

type RemotePage = "bild" | "klarering" | "installningar";
const REMOTE_PAGES: Record<RemotePage, string> = { bild: "/", klarering: "/klarering", installningar: "/installningar" };
const remotePageOf = (path: string): RemotePage => (path.startsWith("/klarering") ? "klarering" : path.startsWith("/installningar") ? "installningar" : "bild");

/** TKL in the remote role: Fjärrbild, Tåg och klarering and Inställningar under one header. */
export function FjarrApp({ state, path, navigate, onLocked }: { state: State; path: string; navigate: (href: string) => void; onLocked: (state: State) => void }) {
  const page = remotePageOf(path);
  const [connection, setConnection] = useState<Connection | null>(null);
  const [notice, setNotice] = useState("");
  useEffect(() => {
    api.connection().then(setConnection).catch(() => undefined);
  }, []);
  useEffect(() => {
    if (!connection?.connected || (connection.status !== "waiting" && connection.status !== "approved")) return;
    const every = connection.status === "waiting" ? 3000 : 15_000;
    const following = setInterval(() => api.connection().then(setConnection).catch(() => undefined), every);
    return () => clearInterval(following);
  }, [connection?.connected, connection?.status]);
  const tabs: NavItem[] = [
    { href: REMOTE_PAGES.bild, label: "Fjärrbild", current: page === "bild" },
    { href: REMOTE_PAGES.klarering, label: "Tåg och klarering", current: page === "klarering" },
    { href: REMOTE_PAGES.installningar, label: "Inställningar", current: page === "installningar" },
  ];
  const approved = connection?.connected && connection.status === "approved";
  const fail = (error: unknown) => {
    if (error instanceof Problem && error.status === 401 && /PIN|TrainMeet ID/.test(error.message)) {
      void api.state().then(onLocked);
      return;
    }
    if (error instanceof Problem && (error.status === 401 || error.status === 409)) void api.connection().then(setConnection);
    setNotice(error instanceof Error ? error.message : "Något gick fel.");
  };
  return (
    <>
      <Header product="TKL" productLabel="TKL" place={`${state.remote?.name ?? state.station?.name ?? ""} · fjärrställverk`} home="/" navLabel="TKL" tabs={tabs} navigate={navigate}>
        {connection?.connected ? (
          <span className={`tm-chip ${approved ? "gron" : "gul"}`}>
            {connection.hub_name ?? "Hubben"} · {approved ? "godkänd" : connection.status === "waiting" ? "väntar" : "inte godkänd"}
          </span>
        ) : null}
        {connection?.connected && connection.preview ? <ProvChip /> : null}
        {state.login ? (
          <button type="button" className="lank ljus" onClick={() => navigate("/stationer")}>
            Dina stationer
          </button>
        ) : null}
        <button type="button" className="lank ljus" onClick={() => void api.lock().then(onLocked)}>
          Lås
        </button>
      </Header>
      <main className="tkl fjarr-sida">
        {notice ? (
          <p className="notis" role="alert">
            {notice}{" "}
            <button type="button" className="lank" onClick={() => setNotice("")}>
              Stäng
            </button>
          </p>
        ) : null}
        {page === "installningar" ? (
          <FjarrInstallningar state={state} connection={connection} onConnection={setConnection} />
        ) : !approved ? (
          <div className="tom-sida">
            <p>{!connection?.connected ? "Fjärrställverket är inte anslutet till en träff." : connection.status === "waiting" ? "Väntar på att trafikledningen godkänner fjärrställverket i Klienter." : (connection.message ?? "Fjärrställverket är inte godkänt. Anslut igen.")}</p>
            <button type="button" className="primar" onClick={() => navigate(REMOTE_PAGES.installningar)}>
              Inställningar › Anslutning
            </button>
          </div>
        ) : (
          <FjarrSida part={page === "klarering" ? "klarering" : "bild"} onProblem={fail} />
        )}
      </main>
      <BottomNav items={tabs} label="TKL" navigate={navigate} />
    </>
  );
}

// --- Inställningar: Anslutning as a remote interlocking, and the PIN ---------------------------

const STATUS: Record<string, string> = { waiting: "Väntar", approved: "Godkänd", refused: "Nekad", revoked: "Återkallad" };

export function FjarrInstallningar({ state, connection, onConnection }: { state: State; connection: Connection | null; onConnection: (c: Connection) => void }) {
  const cloud = state.mode === "cloud";
  const [hubs, setHubs] = useState<FoundHub[] | null>(null);
  const [address, setAddress] = useState("");
  const [code, setCode] = useState("");
  const [areas, setAreas] = useState<RemoteAreas | null>(null);
  const [area, setArea] = useState(state.remote?.area ?? "");
  const [places, setPlaces] = useState((state.remote?.places ?? []).join(", "));
  const [message, setMessage] = useState("");
  const [sending, setSending] = useState(false);
  useEffect(() => {
    if (!connection?.connected) api.hubs().then(setHubs).catch(() => setHubs([]));
  }, [connection?.connected]);
  const look = async (to: string) => {
    setAddress(to);
    setAreas(null);
    try {
      setAreas(await fjarrApi.areas(to));
    } catch {
      setAreas({ areas: [], places: [], message: "Hubben svarade inte." });
    }
  };
  const connect = async (event?: FormEvent) => {
    event?.preventDefault();
    setMessage("");
    setSending(true);
    try {
      onConnection(await fjarrApi.connect({ address: address.trim(), code: code.trim() || null, area: area.trim() || null, places: placesIn(places) }));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Det gick inte att ansluta.");
    } finally {
      setSending(false);
    }
  };
  const name = state.remote?.name ?? state.station?.name ?? "";
  return (
    <div className="installningar fj-installningar">
      <div className="innehall">
        {connection?.connected ? (
          <section className="ruta">
            <h2>{connection.status === "approved" ? "Ansluten" : connection.status === "waiting" ? "Väntar på godkännande" : (STATUS[connection.status ?? ""] ?? "Ansluten")}</h2>
            <ol className="steg">
              <li className="klart">Hittade Hubben · {connection.hub_name ?? connection.address}</li>
              <li className="klart">Bad om att få fjärrstyra som {name}</li>
              <li className={connection.status === "approved" ? "klart" : ""}>{connection.status === "approved" ? `Godkänd för ${(connection.places ?? []).join(", ")}` : "Godkännande av trafikledningen i Klienter, per driftplats"}</li>
            </ol>
            {connection.message ? <p className="fel">{connection.message}</p> : null}
            <p className="liten">Godkännandet ger bara rätt att ta emot. Stationerna lämnar över var för sig, och erbjudandet syns i Fjärrbild.</p>
            <button
              type="button"
              className="fara"
              onClick={() =>
                void api.disconnect().then((c) => {
                  onConnection(c);
                  setAreas(null);
                })
              }
            >
              Koppla från
            </button>
          </section>
        ) : (
          <>
            <section className="ruta">
              <h2>{cloud ? "Hubbar över internet" : "Hubben på träffnätet"}</h2>
              {hubs === null ? (
                <p className="tom">Letar …</p>
              ) : hubs.length ? (
                <ul className="hubbar">
                  {hubs.map((hub) => (
                    <li key={hub.address}>
                      <div>
                        <b>{hub.name}</b>
                        <span className="liten"> · {hub.meet ?? "ingen träff startad"}</span>
                      </div>
                      <button type="button" onClick={() => void look(hub.address)}>
                        Välj
                      </button>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="tom">Ingen hubb hittades. Skriv adressen nedan.</p>
              )}
            </section>
            <form className="ruta" onSubmit={(e) => void connect(e)}>
              <h2>Anslut som fjärrställverk</h2>
              <label>
                Hubbens adress
                <input value={address} onChange={(e) => setAddress(e.target.value)} onBlur={() => address.trim() && void look(address.trim())} placeholder={cloud ? "Välj en hubb ovan" : "http://trainmeet.local"} required />
              </label>
              <label>
                Kod
                <input value={code} onChange={(e) => setCode(e.target.value)} inputMode="numeric" autoComplete="off" maxLength={20} className="tm-mono" />
              </label>
              {areas?.areas?.length ? (
                <fieldset className="fj-omraden">
                  <legend>Planens fjärrområden</legend>
                  {areas.areas.map((a) => (
                    <label key={a.id} className="kryss">
                      <input type="radio" name="omrade" checked={area === a.id} onChange={() => setArea(a.id)} />
                      {a.name} <span className="liten">{a.places.map((p) => areas.places?.find((x) => x.place === p)?.name ?? p).join(" – ")}</span>
                    </label>
                  ))}
                </fieldset>
              ) : areas?.message ? (
                <p className="liten">{areas.message}</p>
              ) : null}
              <label>
                Fjärrområde
                <input value={area} onChange={(e) => setArea(e.target.value)} className="tm-mono" autoComplete="off" />
              </label>
              <label>
                Driftplatser
                <input value={places} onChange={(e) => setPlaces(e.target.value)} className="tm-mono" autoComplete="off" />
              </label>
              {areas?.places?.length ? <p className="liten">Driftplatserna i planen: {areas.places.map((p) => `${p.name} (${p.place})`).join(", ")}.</p> : null}
              <p className="liten">Skrivna driftplatser går före fjärrområdet. Trafikledningen godkänner varje driftplats för sig.</p>
              <button type="submit" className="primar" disabled={sending || !address.trim()}>
                Anslut
              </button>
            </form>
          </>
        )}
        {message ? (
          <p className="fel" role="alert">
            {message}
          </p>
        ) : null}
        <Pin onPin={async (old, pin) => api.changePin(old, pin)} />
      </div>
    </div>
  );
}

// --- Fjärrbild and Tåg och klarering -----------------------------------------------------------

type ScreenView = "allt" | "bild";
const screenKey = (n: number) => `tkl.fjarr.skarm.${n}`;
export function readFjarrScreen(n: number, storage: Pick<Storage, "getItem"> | null): ScreenView {
  try {
    return storage?.getItem(screenKey(n)) === "bild" ? "bild" : "allt";
  } catch {
    return "allt";
  }
}

const storage = (): Storage | null => (typeof localStorage === "undefined" ? null : localStorage);

/** Fjärrbild or Tåg och klarering, with the picture read every few seconds. */
export function FjarrSida({ part, onProblem: given }: { part: "bild" | "klarering"; onProblem: (error: unknown) => void }) {
  const told = useRef(given);
  told.current = given;
  const onProblem = useCallback((error: unknown) => told.current(error), []);
  const [fjarr, setFjarr] = useState<Fjarr | null>(null);
  const [heardAt, setHeardAt] = useState(0);
  const [now, setNow] = useState(Date.now());
  const [choice, setChoice] = useState<Choice | null>(null);
  const [sent, setSent] = useState<Sent[]>([]);
  const [notices, setNotices] = useState<Notice[]>([]);
  const [journal, setJournal] = useState<FjarrHappening[]>([]);
  const [marked, setMarked] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // The parts' requests answered here (#36 del d), by place and request, until the station's
  // route.state no longer lists them waiting.
  const [answered, setAnswered] = useState<Set<string>>(() => new Set());
  const screen = typeof location === "undefined" ? 1 : screenNumber(location.search);
  const [view, setView] = useState<ScreenView>(readFjarrScreen(screen, storage()));
  // The fjärrtågklarerare's Stream Deck (#36 del d, SD37), on the screen as in Ställverket.
  const [deckOpen, setDeckOpen] = useState(() => readDeck(screen, storage(), REMOTE_ROLE).open);
  const last = useRef<Fjarr | null>(null);
  const waiting = useRef(false);
  waiting.current = sent.length > 0;

  const show = useCallback((next: Fjarr) => {
    setFjarr(next);
    if (next.stale) return;
    setHeardAt(Date.now());
    const found = fjarrHappenings(last.current, next);
    last.current = next;
    if (found.length) setJournal((before) => [...found, ...before].slice(0, 200));
  }, []);

  const read = useCallback(async () => {
    try {
      show(await fjarrApi.picture());
    } catch (error) {
      if (!(error instanceof Problem && error.status === 0)) onProblem(error);
    }
  }, [onProblem, show]);

  useEffect(() => {
    let stop = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const again = async () => {
      await read();
      const hidden = typeof document !== "undefined" && document.visibilityState === "hidden";
      if (!stop) timer = setTimeout(() => void again(), hidden ? HIDDEN_MS : waiting.current ? WAITING_MS : EVERY_MS);
    };
    void again();
    const second = setInterval(() => setNow(Date.now()), 1000);
    return () => {
      stop = true;
      clearTimeout(timer);
      clearInterval(second);
    };
  }, [read]);

  // A sent route stays until the station's answer is in the picture; a no is shown for a while,
  // and the picture does not change (FR13, FR14).
  useEffect(() => {
    if (!fjarr || !sent.length) return;
    const names = new Map((fjarr.overview?.places ?? []).map((p) => [p.place.place, p.place.name]));
    const kept: Sent[] = [];
    const refusals: Notice[] = [];
    for (const s of sent) {
      const state = sentState(fjarr, s);
      if (!state || state.state === "requested") {
        if (Date.now() - s.at < 30_000) kept.push(s);
        continue;
      }
      if (state.state === "refused") refusals.push({ id: s.request_id, at: Date.now(), text: `Nej: ${routeLabel(routeOf(fjarr, s.place, s.route), s.route)} vid ${names.get(s.place) ?? s.place}. ${reasonText(state.reason)}` });
    }
    if (kept.length !== sent.length) setSent(kept);
    if (refusals.length) setNotices((before) => [...refusals, ...before]);
  }, [fjarr, sent]);

  useEffect(() => {
    setNotices((before) => {
      const kept = before.filter((n) => now - n.at < (n.again ? 3 * NOTICE_MS : NOTICE_MS));
      return kept.length === before.length ? before : kept;
    });
  }, [now]);

  // An answer to a part stays marked until the request no longer waits, or the station says
  // why its interlocking could not lay it yet (FR50).
  useEffect(() => {
    if (!fjarr || !answered.size) return;
    const asking = new Map(partAsks(fjarr).map((a) => [`${a.place}:${a.request.request_id}`, a.request]));
    const kept = new Set([...answered].filter((key) => asking.has(key) && !asking.get(key)?.note));
    if (kept.size !== answered.size) setAnswered(kept);
  }, [fjarr, answered]);

  const command = async (place: string, action: Action, payload: Record<string, unknown>, context = fjarr?.overview?.context, call?: CallHere, clearance?: Clearance) => {
    if (!context) return null;
    setBusy(true);
    try {
      return await fjarrApi.command({ message_id: messageId(), place, context, action, expected_revision: revisionOf(action, call, clearance), payload });
    } catch (error) {
      onProblem(error);
      return null;
    } finally {
      setBusy(false);
    }
  };

  /** Lägg tågvägen: route.request with TKL's own id (FR11). Hubben's no comes back at once;
   * out of contact it may be tried again (FR28). */
  const lay = async (place: string, route: string) => {
    const id = requestId();
    const reply = await command(place, "route.request", { request_id: id, route });
    if (!reply) return;
    setChoice(null);
    if (reply.status === "rejected") {
      const label = routeLabel(routeOf(fjarr, place, route), route);
      const again = reply.reason === "no_contact" ? { place, route } : undefined;
      setNotices((before) => [{ id, at: Date.now(), text: `Nej: ${label}. ${reply.message ?? reasonText(reply.reason)}`, again }, ...before.filter((n) => !n.again)]);
    } else {
      setSent((before) => [...before, { request_id: id, place, route, at: Date.now() }]);
    }
    await read();
  };

  const remove = async (place: string, requestIdOf: string) => {
    const reply = await command(place, "route.cancel", { request_id: requestIdOf });
    if (reply?.status === "rejected") setNotices((before) => [{ id: `${requestIdOf}-bort`, at: Date.now(), text: reply.message ?? reasonText(reply.reason) }, ...before]);
    setMarked(null);
    await read();
  };

  /** Godkänn or Neka a part's request (FR50): part.answer, which the station does as the
   * clearer's answer in its box. */
  const answerPart = async (place: string, part: string, request: string, approve: boolean) => {
    const reply = await command(place, "part.answer", { part, request_id: request, approve });
    if (reply?.status === "rejected") setNotices((before) => [{ id: `${place}-${request}-del`, at: Date.now(), text: reply.message ?? reasonText(reply.reason) }, ...before]);
    else if (reply) setAnswered((before) => new Set([...before, `${place}:${request}`]));
    await read();
  };

  /** Klara att skicka (FR51): a train moved in the station's list, or Skickat. */
  const ready = async (place: string, action: "ready.move" | "ready.sent", payload: Record<string, unknown>) => {
    const reply = await command(place, action, payload);
    if (reply?.status === "rejected") setNotices((before) => [{ id: `${place}-${String(payload.train_number)}-klar`, at: Date.now(), text: reply.message ?? reasonText(reply.reason) }, ...before]);
    await read();
  };

  const offer = async (place: string, accept: boolean) => {
    const reply = await command(place, "place.offer.answer", { accept });
    if (reply?.status === "rejected") setNotices((before) => [{ id: `${place}-erbjudande`, at: Date.now(), text: reply.message ?? reasonText(reply.reason) }, ...before]);
    await read();
  };

  const hit = (where: Hit) => {
    if (where.kind === "track" && !choice) {
      const place = (fjarr?.overview?.places ?? []).find((p) => p.place.place === where.place);
      const pieces = place?.outside?.overview?.routes ?? {};
      const found = place ? myRoutes(place, fjarr?.client_id ?? null).find((r) => r.state === "locked" && (pieces[r.route] ?? []).includes(where.piece)) : undefined;
      if (found) {
        setMarked(found.request_id);
        return;
      }
    }
    setChoice((before) => choose(fjarr, before, where));
  };

  const drawn = useMemo(() => drawPicture(fjarr, choice), [fjarr, choice]);
  const clock = fjarr?.overview ? clockOf(fjarr.overview.clock, heardAt, now) : null;

  if (!fjarr) return <p className="tom">Läser fjärrbilden från hubben …</p>;
  if (part === "klarering") return <FjarrKlarering fjarr={fjarr} onProblem={onProblem} />;
  const panels = {
    fjarr,
    choice,
    sent,
    notices,
    heardAt,
    now,
    busy,
    onLay: () => choice?.route && void lay(choice.place, choice.route),
    onDrop: () => setChoice(null),
    onChoose: setChoice,
    onAgain: (place: string, route: string) => void lay(place, route),
    onRemove: (place: string, id: string) => void remove(place, id),
    onOffer: (place: string, accept: boolean) => void offer(place, accept),
    answered,
    onPart: (place: string, part: string, request: string, approve: boolean) => void answerPart(place, part, request, approve),
  };
  return (
    <div className={`fj-sida fj-vy-${view}`}>
      <div className="fj-huvud">
        <h1>Fjärrbild</h1>
        {clock ? <span className="fj-klocka tm-mono">{clock}</span> : null}
        <span className="tm-fyll" />
        <span className="liten">Skärm {screen}:</span>
        <div className="fj-skarm" role="radiogroup" aria-label="Den här skärmen">
          {(
            [
              ["allt", "Allt på en skärm"],
              ["bild", "Bara fjärrbilden"],
            ] as [ScreenView, string][]
          ).map(([key, label]) => (
            <button
              key={key}
              type="button"
              role="radio"
              aria-checked={view === key}
              onClick={() => {
                setView(key);
                storage()?.setItem(screenKey(screen), key);
              }}
            >
              {label}
            </button>
          ))}
        </div>
        <button
          type="button"
          aria-pressed={deckOpen}
          onClick={() => {
            const open = !deckOpen;
            setDeckOpen(open);
            saveDeck(screen, { ...readDeck(screen, storage(), REMOTE_ROLE), open }, storage(), REMOTE_ROLE);
          }}
        >
          Stream Deck
        </button>
      </div>
      {fjarr.stale ? (
        <p className="gammal" role="status">
          {fjarr.message ?? "Ingen kontakt med hubben."} Bilden är den senaste TKL fick{fjarr.heard ? ` ${new Date(fjarr.heard).toLocaleTimeString("sv-SE")}` : ""}.
        </p>
      ) : null}
      <div className="fj-bild">
        <FjarrbildView drawn={drawn} onHit={hit} stale={fjarr.stale ?? false} />
      </div>
      {deckOpen ? <DeckPanel screen={screen} plan={null} role={REMOTE_ROLE} /> : null}
      <Teckenforklaring />
      <div className="kolumner fj-kolumner">
        <Vantar {...panels} />
        {view === "allt" || readyLists(fjarr).length ? <KlaraAttSkicka fjarr={fjarr} busy={busy} onMove={(place, number, to) => void ready(place, "ready.move", { train_number: number, to })} onSent={(place, number) => void ready(place, "ready.sent", { train_number: number })} /> : null}
        {view === "allt" ? <Lagda fjarr={fjarr} busy={busy} marked={marked} onRemove={panels.onRemove} /> : null}
        {view === "allt" ? <FjarrHandelser journal={journal} /> : null}
      </div>
      {view === "bild" ? <p className="liten">Tåg och klarering på en annan skärm: öppna TKL där med ?skarm=3 och välj Tåg och klarering.</p> : null}
    </div>
  );
}

function FjarrHandelser({ journal }: { journal: FjarrHappening[] }) {
  return (
    <section className="fj-ruta" aria-labelledby="fj-handelser">
      <h2 id="fj-handelser">Händelser</h2>
      {journal.length ? (
        <ul className="handelser">
          {journal.map((h) => (
            <li key={h.id}>
              <span className="tm-mono">{h.time}</span> {h.text}
            </li>
          ))}
        </ul>
      ) : (
        <p className="tom">Inget har hänt sedan sidan öppnades.</p>
      )}
    </section>
  );
}

/** Tåg och klarering for each station TKL controls, chosen with a tab: level 0's Tåg, Klarering
 * and Händelser as they are, for the whole station (FR17). */
export function FjarrKlarering({ fjarr, onProblem: given }: { fjarr: Fjarr; onProblem: (error: unknown) => void }) {
  const told = useRef(given);
  told.current = given;
  const onProblem = useCallback((error: unknown) => told.current(error), []);
  const controlled = fjarr.controls ?? [];
  const names = new Map((fjarr.overview?.places ?? []).map((p) => [p.place.place, p.place.name]));
  const [chosen, setChosen] = useState<string | null>(null);
  const place = chosen && controlled.includes(chosen) ? chosen : (controlled[0] ?? null);
  const [view, setView] = useState<View | null>(null);
  const [journal, setJournal] = useState<Record<string, Happening[]>>({});
  const [busy, setBusy] = useState(false);
  const last = useRef<Record<string, View["snapshot"]>>({});

  const take = useCallback((at: string, next: View) => {
    setView(next);
    const snapshot = next.snapshot;
    if (!snapshot || next.stale) return;
    const found = happenings(last.current[at] ?? null, snapshot);
    last.current[at] = snapshot;
    if (found.length) setJournal((before) => ({ ...before, [at]: [...found, ...(before[at] ?? [])].slice(0, 200) }));
  }, []);

  useEffect(() => {
    if (!place) return;
    let stop = false;
    const read = () =>
      fjarrApi
        .place(place)
        .then((next) => !stop && take(place, next))
        .catch((error: unknown) => !stop && !(error instanceof Problem && error.status === 0) && onProblem(error));
    setView(null);
    void read();
    const every = setInterval(() => void read(), PLACE_MS);
    return () => {
      stop = true;
      clearInterval(every);
    };
  }, [place, take, onProblem]);

  if (!place) return <p className="tom">Fjärrställverket styr ingen station just nu. En station som lämnar över syns i Fjärrbild, under Väntar på dig.</p>;
  const snapshot = view?.snapshot ?? null;
  // The station's outside as the meet runs it: the exits' names in Klarering, and its tracks.
  const outside = (fjarr.overview?.places ?? []).find((p) => p.place.place === place)?.outside ?? null;
  const send = async (action: Action, payload: Record<string, unknown>, call?: CallHere, clearance?: Clearance) => {
    if (!snapshot) return;
    setBusy(true);
    try {
      const reply = await fjarrApi.command({ message_id: messageId(), place, context: snapshot.context, action, expected_revision: revisionOf(action, call, clearance), payload });
      take(place, { snapshot: full(reply.snapshot), stale: false, heard: new Date().toISOString(), message: null });
      if (reply.status === "rejected") onProblem(new Error(reply.message ?? "Hubben sa nej."));
    } catch (error) {
      onProblem(error);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="fj-klarering">
      <nav className="studio-flikar" aria-label="Stationerna">
        {controlled.map((p) => (
          <button key={p} type="button" aria-current={p === place ? "page" : undefined} onClick={() => setChosen(p)}>
            {names.get(p) ?? p}
          </button>
        ))}
      </nav>
      <p className="liten">Den som fjärrstyr klarerar för hela stationen. Styrs båda ändarna av en sträcka härifrån går sträckan direkt.</p>
      {view?.stale ? (
        <p className="gammal" role="status">
          {view.message ?? "Ingen kontakt med hubben."}
        </p>
      ) : null}
      {snapshot ? (
        <div className="kolumner">
          <Tag snapshot={snapshot} outside={outside} busy={busy} onSend={(a, p, c, cl) => void send(a, p, c, cl)} />
          <Klarering snapshot={snapshot} outside={outside} busy={busy} onSend={(a, p, c, cl) => void send(a, p, c, cl)} />
          <Handelser journal={journal[place] ?? []} />
        </div>
      ) : (
        <p className="tom">Hämtar {names.get(place) ?? place} från hubben …</p>
      )}
    </div>
  );
}
