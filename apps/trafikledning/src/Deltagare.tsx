import { Banoversikt, clockText, ENGLISH, hub, nextHappenings, numbers, SWEDISH, trafficOf, type Now, type Package, type Participant, type Weekday, type Words } from "@trainmeet/hubben";
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { api } from "./api";
import { IdLogIn } from "./StartPage";

// Deltagarna (DELT-01–DELT-20): the page everyone sees without logging in, telephone first and
// two columns on a computer. The clock, the line and the next happenings come from Drift's open
// API, as on the screens (H72). Over the internet, without logging in, only the traffic: no
// Dela träffen, no Anslut din TMBox and no Wi-Fi (S8). Swedish and English first (DELT-14),
// light and dark after the phone (DELT-12).

export type Language = "sv" | "en";

/** The page's language: Swedish for a Swedish browser, English for the rest (DELT-14). */
export function languageOf(languages: readonly string[]): Language {
  return languages.some((language) => language.toLowerCase().startsWith("sv")) ? "sv" : "en";
}

const DAYS: Record<Language, Record<Weekday, string>> = {
  sv: { mon: "Måndag", tue: "Tisdag", wed: "Onsdag", thu: "Torsdag", fri: "Fredag", sat: "Lördag", sun: "Söndag" },
  en: { mon: "Monday", tue: "Tuesday", wed: "Wednesday", thu: "Thursday", fri: "Friday", sat: "Saturday", sun: "Sunday" },
};

export const TEXT = {
  sv: {
    title: "Träffen",
    live: "Live",
    noMeet: "Ingen träff körs just nu.",
    noMeetHint: "Sidan visar träffen så fort den har startat.",
    running: (speed: number) => `Går · ×${speed}`,
    stopped: "Står still",
    day: (day: string, game: number) => `${day} · dag ${game}`,
    share: "Dela träffen",
    onTheLine: "På banan nu",
    swipe: "svep i sidled",
    happenings: "Nästa händelser",
    wholeLine: "hela banan",
    nothing: "Inget händer de närmaste tre timmarna.",
    connect: "Anslut din TMBox",
    onlyTraffic: "Du ser trafiken. Namn, foton och träffens Wi-Fi visas på träffens nät eller när du är inloggad.",
    logIn: "Logga in",
    pin: "Hubbens PIN-kod",
    code: "Engångskod från trafikledningen",
    useCode: "Jag har en engångskod",
    idLogIn: "Logga in med TrainMeet ID",
    idFailed: "Inloggningen med TrainMeet ID gick inte. Försök igen.",
    again: (name: string) => `Logga in igen som ${name}`,
    againNote: "Utan internet: biljetten från TrainMeet ID gäller i 30 dagar på den här Pi:n.",
    usePin: "Jag har hubbens PIN-kod",
    toDrift: "Till driften →",
    close: "Stäng",
    shareHint: "Visa koden för den som står bredvid.",
    wifiQr: "1 · Wi-Fi",
    meetQr: "2 · Träffen",
    noWifi: "Träffens Wi-Fi har inte lagts in ännu.",
    link: "Länk till träffen",
    copy: "Kopiera",
    copied: "Kopierad",
    linkBoth: "Länken fungerar på träffnätet och via internet.",
    linkHere: "Länken fungerar på träffens nät.",
    connectOrder: "tre steg, i den här ordningen",
    step1: "Koppla boxen till träffens Wi-Fi",
    network: (name: string) => `Nätverk ${name}`,
    password: (password: string) => `lösenord ${password}`,
    open: "öppet nät, inget lösenord",
    askWifi: "Fråga trafikledningen om träffens Wi-Fi.",
    step2: "Boxen hittar hubben själv",
    step2Text: "Hubben annonserar sig på träffnätet; ingen adress eller kod behövs. Boxen visar sin egen kod på displayen.",
    step3: "Trafikledaren tilldelar driftplats",
    step3Text: "Boxen hamnar under Väntar i Klienter och börjar arbeta när den fått driftplats och sida.",
    noBox: "Ingen box till hands? Kör den i webbläsaren på mobilen, iPaden eller datorn. Trafikledningen ger dig koden.",
    webBox: "TMBox i webbläsaren",
    words: SWEDISH,
  },
  en: {
    title: "The meet",
    live: "Live",
    noMeet: "No meet is running just now.",
    noMeetHint: "The page shows the meet as soon as it has started.",
    running: (speed: number) => `Running · ×${speed}`,
    stopped: "Stopped",
    day: (day: string, game: number) => `${day} · day ${game}`,
    share: "Share the meet",
    onTheLine: "On the line now",
    swipe: "swipe sideways",
    happenings: "Next events",
    wholeLine: "the whole line",
    nothing: "Nothing happens in the next three hours.",
    connect: "Connect your TMBox",
    onlyTraffic: "You see the traffic. Names, photos and the meet's Wi-Fi are shown on the meet's network or when you are logged in.",
    logIn: "Log in",
    pin: "The hub's PIN",
    code: "One-time code from the dispatchers",
    useCode: "I have a one-time code",
    idLogIn: "Log in with TrainMeet ID",
    idFailed: "Logging in with TrainMeet ID did not work. Try again.",
    again: (name: string) => `Log in again as ${name}`,
    againNote: "Without internet: the ticket from TrainMeet ID holds for 30 days on this Pi.",
    usePin: "I have the hub's PIN",
    toDrift: "To operations →",
    close: "Close",
    shareHint: "Show the code to the one next to you.",
    wifiQr: "1 · Wi-Fi",
    meetQr: "2 · The meet",
    noWifi: "The meet's Wi-Fi has not been entered yet.",
    link: "Link to the meet",
    copy: "Copy",
    copied: "Copied",
    linkBoth: "The link works on the meet's network and over the internet.",
    linkHere: "The link works on the meet's network.",
    connectOrder: "three steps, in this order",
    step1: "Connect the box to the meet's Wi-Fi",
    network: (name: string) => `Network ${name}`,
    password: (password: string) => `password ${password}`,
    open: "open network, no password",
    askWifi: "Ask the dispatcher for the meet's Wi-Fi.",
    step2: "The box finds the hub by itself",
    step2Text: "The hub announces itself on the meet's network; no address or code is needed. The box shows its own code on its display.",
    step3: "The dispatcher gives it a place",
    step3Text: "The box waits under Väntar in Klienter and starts working when it has a place and a side.",
    noBox: "No box at hand? Run it in the browser on your phone, iPad or computer. The dispatcher gives you the code.",
    webBox: "TMBox in the browser",
    words: ENGLISH as Words,
  },
};

type Text = (typeof TEXT)["sv"];

export type DeltagareProps = {
  now: Now | null;
  elapsedMs: number;
  message: string;
  language?: Language;
  /** Given in tests; the page reads it from the hub itself. */
  initial?: { participant: Participant; pkg: Package | null };
  onLogIn: (pin: string) => void;
  /** Engångskoden från trafikledningen (H56). */
  onLogInWithCode?: (code: string) => void;
  /** The hub logs in with TrainMeet ID (#78). */
  idLogin?: boolean;
  /** On the meet's Pi: whose ticket from ID this browser has, and Logga in igen (KONTO-11). */
  ticketName?: string | null;
  onLogInAgain?: () => void;
};

/** The key that says when the package Drift goes by has changed: the version and the
 * driftändringar on top of it. */
const packageKey = (now: Now) => `${now.meet_id}:${now.version}:${(now.changes ?? []).map((change) => `${change.change_id}:${change.status}`).join(",")}`;

export function DeltagarePage({ now, elapsedMs, message, language = languageOf(typeof navigator === "undefined" ? ["sv"] : navigator.languages ?? [navigator.language]), initial, onLogIn, onLogInWithCode, idLogin = false, ticketName = null, onLogInAgain }: DeltagareProps) {
  const t = TEXT[language];
  const [participant, setParticipant] = useState<Participant | null>(initial?.participant ?? null);
  const [pkg, setPkg] = useState<Package | null>(initial?.pkg ?? null);
  const [sheet, setSheet] = useState<"share" | "connect" | null>(null);
  // Back from ID with a login that did not go through: the login is open, with the reason.
  const [loggingIn, setLoggingIn] = useState(() => typeof window !== "undefined" && new URLSearchParams(window.location.search).has("inloggning"));
  const key = now ? packageKey(now) : null;

  useEffect(() => {
    if (initial) return;
    const read = () => void hub.participant().then(setParticipant, () => undefined);
    read();
    const timer = window.setInterval(read, 30000);
    return () => window.clearInterval(timer);
  }, [initial]);

  useEffect(() => {
    if (initial || !key) return;
    void api.package().then((found) => setPkg(found as Package), () => undefined);
  }, [initial, key]);

  useEffect(() => {
    document.documentElement.lang = language;
  }, [language]);

  const full = participant?.full ?? false;
  return (
    <div className="deltagarsida" lang={language}>
      <section className="kort deltagare-klocka" aria-labelledby="deltagare-traff">
        <p className="liten deltagare-live">
          <span className="prick" aria-hidden="true" /> {t.live}
        </p>
        <h1 id="deltagare-traff">{now?.name ?? t.title}</h1>
        {now ? (
          <>
            <p className="stor-klocka tm-mono" aria-live="off">
              {clockText(now, elapsedMs)}
            </p>
            <p className="liten">
              {now.clock.running ? t.running(now.clock.speed) : t.stopped} · {t.day(DAYS[language][now.traffic_day], now.game_day)}
            </p>
          </>
        ) : (
          <>
            <p id="deltagare-ingen">{t.noMeet}</p>
            <p className="liten">{t.noMeetHint}</p>
          </>
        )}
        {full && (
          <p className="knapprad">
            <button id="dela-traffen" type="button" className="tm-knapp" onClick={() => setSheet("share")}>
              {t.share}
            </button>
          </p>
        )}
      </section>

      {now && pkg && <Line now={now} pkg={pkg} t={t} />}
      {now && <Happenings now={now} pkg={pkg} t={t} />}

      <section className="kort deltagare-anslut">
        {full ? (
          <button id="anslut-box" type="button" className="tm-knapp primar bred" onClick={() => setSheet("connect")}>
            {t.connect}
          </button>
        ) : (
          <p id="bara-trafiken">{t.onlyTraffic}</p>
        )}
        {participant?.logged_in ? (
          <p className="lankar">
            <a href="/drift">{t.toDrift}</a>
          </p>
        ) : loggingIn || ticketName ? (
          <>
            <LogIn t={t} message={message} onLogIn={onLogIn} onLogInWithCode={onLogInWithCode} />
            {idLogin && <IdLogIn label={t.idLogIn} failedText={t.idFailed} ticketName={ticketName} againLabel={t.again} againNote={t.againNote} onAgain={onLogInAgain} />}
          </>
        ) : (
          <button id="deltagare-logga-in" type="button" className="tm-knapp" onClick={() => setLoggingIn(true)}>
            {t.logIn}
          </button>
        )}
      </section>

      {sheet && participant && (
        <Sheet title={sheet === "share" ? t.share : t.connect} subtitle={sheet === "share" ? t.shareHint : t.connectOrder} close={t.close} onClose={() => setSheet(null)}>
          {sheet === "share" ? <Share participant={participant} t={t} /> : <Connect participant={participant} t={t} />}
        </Sheet>
      )}
    </div>
  );
}

function Line({ now, pkg, t }: { now: Now; pkg: Package; t: Text }) {
  const traffic = trafficOf(pkg, now);
  return (
    <section className="kort deltagare-bana" aria-labelledby="deltagare-bana">
      <h2 id="deltagare-bana">
        {t.onTheLine} <span className="liten">{t.swipe}</span>
      </h2>
      <ul className="chips" id="deltagare-tal">
        {numbers(traffic, t.words)
          .slice(0, 3)
          .map(([count, label]) => (
            <li key={label} className="chip">
              <b>{count}</b> {label}
            </li>
          ))}
      </ul>
      {/* The line as on Nu and the screens (H47), as a cut-out to swipe on the phone (H49). */}
      <div className="bana-svep" tabIndex={0}>
        <Banoversikt pkg={pkg} now={now} traffic={traffic} label={t.onTheLine} aspect={3} />
      </div>
    </section>
  );
}

function Happenings({ now, pkg, t }: { now: Now; pkg: Package | null; t: Text }) {
  const names = new Map((pkg?.places ?? []).map((place) => [place.id, place.name]));
  const found = nextHappenings(now, names, 8, t.words);
  const time = (minute: number) => `${String(Math.floor(minute / 60) % 24).padStart(2, "0")}:${String(minute % 60).padStart(2, "0")}`;
  return (
    <section className="kort deltagare-handelser" aria-labelledby="deltagare-handelser">
      <h2 id="deltagare-handelser">
        {t.happenings} <span className="liten">· {t.wholeLine}</span>
      </h2>
      {found.length ? (
        <ol className="handelser">
          {found.map((item) => (
            <li key={`${item.leg.leg}:${item.text}`}>
              <span className="tm-mono">{time(item.minute)}</span>
              <b>{item.number}</b>
              <span>{item.text}</span>
              {item.note && <span className="liten">{item.note}</span>}
            </li>
          ))}
        </ol>
      ) : (
        <p className="liten">{t.nothing}</p>
      )}
    </section>
  );
}

function LogIn({ t, message, onLogIn, onLogInWithCode }: { t: Text; message: string; onLogIn: (pin: string) => void; onLogInWithCode?: (code: string) => void }) {
  const [pin, setPin] = useState("");
  const [code, setCode] = useState("");
  // The PIN, or the one-time code the dispatchers gave (H56): one at a time, so a wrong guess
  // never counts twice.
  const [withCode, setWithCode] = useState(false);
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (withCode) onLogInWithCode?.(code);
    else onLogIn(pin);
  };
  return (
    <form id="deltagare-login" className="formular" onSubmit={submit}>
      {withCode ? (
        <label>
          {t.code}
          <input id="deltagare-code" type="text" inputMode="numeric" pattern="[0-9]{6}" minLength={6} maxLength={6} required autoComplete="one-time-code" value={code} onChange={(event) => setCode(event.target.value)} />
        </label>
      ) : (
        <label>
          {t.pin}
          <input id="deltagare-pin" type="password" inputMode="numeric" pattern="[0-9]{6,12}" minLength={6} maxLength={12} required autoComplete="current-password" value={pin} onChange={(event) => setPin(event.target.value)} />
        </label>
      )}
      <button type="submit" className="tm-knapp primar">
        {t.logIn}
      </button>
      {onLogInWithCode && (
        <button id="deltagare-kodval" type="button" className="tm-knapp" onClick={() => setWithCode(!withCode)}>
          {withCode ? t.usePin : t.useCode}
        </button>
      )}
      <p className="meddelande" role="alert">
        {message}
      </p>
    </form>
  );
}

/** A sheet from the bottom, as a modal dialog: Escape and Stäng close it. */
function Sheet({ title, subtitle, close, onClose, children }: { title: string; subtitle: string; close: string; onClose: () => void; children: ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current;
    if (dialog && !dialog.open && typeof dialog.showModal === "function") dialog.showModal();
  }, []);
  return (
    <dialog ref={ref} className="blad" aria-labelledby="blad-rubrik" onCancel={onClose} onClose={onClose}>
      <header>
        <h2 id="blad-rubrik">{title}</h2>
        <p className="liten">{subtitle}</p>
      </header>
      {children}
      <p className="knapprad">
        <button type="button" className="tm-knapp" onClick={onClose}>
          {close}
        </button>
      </p>
    </dialog>
  );
}

/** Dela träffen (DELT-02): QR 1 · Wi-Fi and QR 2 · Träffen, and the link to copy. */
export function Share({ participant, t, origin = typeof window === "undefined" ? "http://trainmeet.local" : window.location.origin }: { participant: Participant; t: Text; origin?: string }) {
  const link = participant.link ?? `${origin}/`;
  const [copied, setCopied] = useState(false);
  const copy = () => void navigator.clipboard?.writeText(link).then(() => setCopied(true), () => undefined);
  return (
    <div className="dela">
      <div className="qr-par">
        {participant.wifi ? (
          <figure>
            <img src="/api/deltagare/wifi.svg" alt={t.network(participant.wifi.name)} width={180} height={180} />
            <figcaption>{t.wifiQr}</figcaption>
          </figure>
        ) : (
          <p className="liten" id="inget-wifi">
            {t.noWifi}
          </p>
        )}
        <figure>
          <img src={`/api/deltagare/traffen.svg?address=${encodeURIComponent(link)}`} alt={t.link} width={180} height={180} />
          <figcaption>{t.meetQr}</figcaption>
        </figure>
      </div>
      <p className="lank-rad">
        <span className="liten">{t.link}</span>
        <code id="traff-lank">{link}</code>
        <button type="button" className="tm-knapp" onClick={copy}>
          {copied ? t.copied : t.copy}
        </button>
      </p>
      <p className="liten">{participant.link ? t.linkBoth : t.linkHere}</p>
    </div>
  );
}

/** Anslut din TMBox (DELT-03): three steps, the Wi-Fi as text, since a box cannot scan. */
export function Connect({ participant, t }: { participant: Participant; t: Text }) {
  const wifi = participant.wifi;
  return (
    <div className="anslut-steg">
      <ol className="steg">
        <li>
          <b>{t.step1}</b>
          <span id="anslut-wifi">{wifi ? `${t.network(wifi.name)} · ${wifi.open ? t.open : wifi.password ? t.password(wifi.password) : t.askWifi}` : t.askWifi}</span>
        </li>
        <li>
          <b>{t.step2}</b>
          <span>{t.step2Text}</span>
        </li>
        <li>
          <b>{t.step3}</b>
          <span>{t.step3Text}</span>
        </li>
      </ol>
      <p className="liten">{t.noBox}</p>
      <p className="knapprad">
        <a className="tm-knapp" href="/box">
          {t.webBox}
        </a>
      </p>
    </div>
  );
}
