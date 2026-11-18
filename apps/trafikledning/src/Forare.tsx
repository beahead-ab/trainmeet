import { useCallback, useEffect, useState } from "react";
import { api, Problem, type DriverAlarm, type DriverOverview, type DriverRow, type DriverSettings, type Joining, type Now, type OneTimeCodeAnswer, type ServiceOffer, type ServiceRef } from "./api";
import { languageOf, type Language } from "./Deltagare";
import { placeName } from "./drift";

// Förare in Drift (TRAFIK-33, LOK-30): the drivers, their services, check-ins and latest
// messages; hand out and take back a service; the game's two settings and Framme; the alarm
// for a train left without a driver on the line (LOK-35); and the QR code the drivers come in
// with (LOK-01). Trafikledningen does it all; the lokledare sees and hands out, and runs no
// traffic. Swedish and English (ST10).

export const TEXT = {
  sv: {
    title: "Förare",
    intro: "Förarna på träffen och deras tjänster. Dela ut en tjänst, ta tillbaka den, och välj vad förarna ser.",
    logIn: "Logga in som trafikledare eller lokledare för att se förarna.",
    toLogIn: "Till inloggningen →",
    noMeet: "Ingen träff är startad.",
    alarms: "Tåg utan förare",
    alarm: (train: string, from: string, to: string, number: string, since: string) => `Tåg ${train} står utan förare mellan ${from} och ${to} · tjänst ${number} · sedan ${since}`,
    clear: "Kvittera",
    settings: "Vad förarna ser i trafikspelet",
    settingsNote: "Allt är av från början. Bara trafikledningen ändrar valen.",
    reality: "Förarna ser verkligheten: var tåget är enligt stationerna, förseningen och sena mötande tåg",
    clearances: "Förarna ser tågklareringens besked: sträckan klar, spåret och att stationen väntar",
    arrival: "Framme räknas som ankomst, bara på obemannade driftplatser",
    drivers: "Förarna",
    noDrivers: "Inga förare ännu. De kommer in med QR-koden nedan.",
    noService: "Ingen tjänst",
    service: (number: string, trains: string) => `Tjänst ${number} · tåg ${trains}`,
    checkin: (place: string, time: string) => `Incheckad ${place} kl. ${time}`,
    handOut: "Dela ut",
    takeBack: "Ta tillbaka",
    choose: "Välj tjänst",
    services: "Tjänsterna",
    trains: "Tågen",
    free: "Ledig",
    takenBy: (name: string) => `Körs av ${name}`,
    released: "Släppt på linjen",
    done: "Klar",
    messages: "Meddelanden",
    noMessages: "Inga meddelanden från förarna.",
    qr: "QR-koden till träffen",
    qrNote: "Sätt upp den på träffen. Föraren skannar, skriver sitt namn och väljer nivå. Inget konto behövs.",
    code: (code: string) => `Kod ${code.slice(0, 3)} ${code.slice(3)}`,
    letIn: "Släpp in en lokledare",
    letInNote: "Lokledaren ser förarna och delar ut tjänster, men styr ingen trafik. Koden gäller en gång i 15 minuter.",
    give: "Ge en kod",
    who: "Vem, om du vill",
    given: (code: string) => `${code.slice(0, 3)} ${code.slice(3)}`,
    lead: "Du är lokledare: du ser förarna och delar ut tjänster.",
    levels: { easy: "Lätt", medium: "Medel", experienced: "Erfaren" } as Record<string, string>,
    states: { pause: "Paus", waiting_start: "Inväntar start" } as Record<string, string>,
    kinds: { delayed: "Försenad", stopped_on_line: "Står på linjen", needs_help: "Behöver hjälp", engine_trouble: "Loket krånglar" } as Record<string, string>,
    positions: { planned: "Inte iväg än", at: "Står", on_the_way: "På väg", done: "Framme" } as Record<string, string>,
    late: (minutes: number) => `${minutes} min sent`,
    train: (number: string) => `tåg ${number}`,
    serviceNumber: (number: string) => `tjänst ${number}`,
  },
  en: {
    title: "Drivers",
    intro: "The drivers at the meet and their services. Hand out a service, take it back, and choose what the drivers see.",
    logIn: "Log in as dispatcher or loco lead to see the drivers.",
    toLogIn: "To the login →",
    noMeet: "No meet is running.",
    alarms: "Trains without a driver",
    alarm: (train: string, from: string, to: string, number: string, since: string) => `Train ${train} stands without a driver between ${from} and ${to} · service ${number} · since ${since}`,
    clear: "Acknowledge",
    settings: "What the drivers see in this game",
    settingsNote: "All are off to begin with. Only the dispatcher changes them.",
    reality: "The drivers see reality: where the train is according to the stations, the delay and late oncoming trains",
    clearances: "The drivers see the clearances: the section is clear, the track and that the station waits",
    arrival: "Arrived counts as the arrival, only at unmanned places",
    drivers: "The drivers",
    noDrivers: "No drivers yet. They come in with the QR code below.",
    noService: "No service",
    service: (number: string, trains: string) => `Service ${number} · train ${trains}`,
    checkin: (place: string, time: string) => `Checked in at ${place} at ${time}`,
    handOut: "Hand out",
    takeBack: "Take back",
    choose: "Choose a service",
    services: "The services",
    trains: "The trains",
    free: "Free",
    takenBy: (name: string) => `Driven by ${name}`,
    released: "Released on the line",
    done: "Done",
    messages: "Messages",
    noMessages: "No messages from the drivers.",
    qr: "The meet's QR code",
    qrNote: "Put it up at the meet. The driver scans it, writes a name and chooses a level. No account is needed.",
    code: (code: string) => `Code ${code.slice(0, 3)} ${code.slice(3)}`,
    letIn: "Let in a loco lead",
    letInNote: "The loco lead sees the drivers and hands out services, but runs no traffic. The code holds once for 15 minutes.",
    give: "Give a code",
    who: "Who, if you like",
    given: (code: string) => `${code.slice(0, 3)} ${code.slice(3)}`,
    lead: "You are loco lead: you see the drivers and hand out services.",
    levels: { easy: "Easy", medium: "Medium", experienced: "Experienced" } as Record<string, string>,
    states: { pause: "Break", waiting_start: "Waiting to start" } as Record<string, string>,
    kinds: { delayed: "Delayed", stopped_on_line: "Stopped on the line", needs_help: "Needs help", engine_trouble: "Engine trouble" } as Record<string, string>,
    positions: { planned: "Not off yet", at: "At", on_the_way: "On the way", done: "Arrived" } as Record<string, string>,
    late: (minutes: number) => `${minutes} min late`,
    train: (number: string) => `train ${number}`,
    serviceNumber: (number: string) => `service ${number}`,
  },
};

type Text = (typeof TEXT)["sv"];

export type ForareProps = {
  /** Logged in at all: the page asks the hub whether the role may see the drivers. */
  loggedIn: boolean;
  now: Now | null;
  navigate: (href: string) => void;
  onMessage?: (text: string) => void;
  language?: Language;
  /** Given in tests; the page reads them from the hub itself. */
  initial?: { overview: DriverOverview; joining: Joining | null };
};

const refKey = (ref: ServiceRef) => `${ref.kind}:${ref.id}`;

/** What a driver row says about the driver's train: where it is, and how late (LOK-22). */
export function whereText(row: DriverRow, now: Now | null, text: Text): string {
  const position = row.position;
  if (!position) return "";
  const where = position.place ? placeName(now, position.place) : position.from_place && position.to_place ? `${placeName(now, position.from_place)} → ${placeName(now, position.to_place)}` : "";
  const late = position.delay ? ` · ${text.late(position.delay)}` : "";
  return `${text.positions[position.state] ?? position.state}${where ? ` ${where}` : ""}${late}`;
}

/** The alarm in words: which train, where, which service and since when (LOK-35). */
export function alarmText(alarm: DriverAlarm, now: Now | null, text: Text = TEXT.sv): string {
  return text.alarm(alarm.train_number ?? alarm.train ?? "?", placeName(now, alarm.from_place ?? ""), placeName(now, alarm.to_place ?? ""), alarm.number, alarm.since);
}

/** A service as the list shows it: the front of the paper, and who drives it. */
export function serviceText(offer: ServiceOffer, text: Text): string {
  const start = `${offer.start.time ?? ""} ${offer.start.place_name}`.trim();
  const end = `${offer.end.time ?? ""} ${offer.end.place_name}`.trim();
  const level = offer.level ? ` · ${text.levels[offer.level] ?? offer.level}` : "";
  const operator = offer.operator ? ` · ${offer.operator}` : "";
  return `${start} – ${end}${operator}${level}`;
}

export function ForarePage({ loggedIn, now, navigate, onMessage, language = languageOf(typeof navigator === "undefined" ? ["sv"] : (navigator.languages ?? [navigator.language])), initial }: ForareProps) {
  const text = TEXT[language];
  const [overview, setOverview] = useState<DriverOverview | null>(initial?.overview ?? null);
  const [joining, setJoining] = useState<Joining | null>(initial?.joining ?? null);
  const [refused, setRefused] = useState(false);
  const say = useCallback((error: unknown) => onMessage?.(error instanceof Error ? error.message : String(error)), [onMessage]);

  const read = useCallback(async () => {
    try {
      setOverview(await api.drivers());
      setRefused(false);
    } catch (error) {
      if (error instanceof Problem && (error.status === 401 || error.status === 403)) setRefused(true);
      else if (!(error instanceof Problem && error.status === 404)) say(error);
      setOverview(null);
    }
  }, [say]);

  const running = now !== null;
  useEffect(() => {
    if (initial || !loggedIn || !running) return;
    void read();
    void api.driverJoining().then(setJoining, () => setJoining(null));
    const timer = window.setInterval(() => void read(), 3000);
    return () => window.clearInterval(timer);
  }, [initial, loggedIn, running, read]);

  const act = async (doing: () => Promise<DriverOverview>) => {
    try {
      setOverview(await doing());
    } catch (error) {
      say(error);
    }
  };

  if (!loggedIn || refused) {
    return (
      <section className="kort">
        <h1>{text.title}</h1>
        <p className="ingress">{text.logIn}</p>
        <p>
          <a
            href="/"
            onClick={(event) => {
              event.preventDefault();
              navigate("/");
            }}
          >
            {text.toLogIn}
          </a>
        </p>
      </section>
    );
  }
  if (!now) {
    return (
      <section className="kort">
        <h1>{text.title}</h1>
        <p className="ingress">{text.noMeet}</p>
      </section>
    );
  }
  if (!overview) return null;
  const free = overview.services.services?.filter((offer) => !offer.taken && !offer.done) ?? [];
  const names = new Map((overview.drivers ?? []).map((row) => [row.driver.id, row.driver.name ?? row.driver.id]));
  return (
    <section id="forare">
      <div className="sidrubrik">
        <h1>{text.title}</h1>
        <p className="liten">{overview.may_set ? text.intro : text.lead}</p>
      </div>
      {(overview.alarms ?? []).length > 0 && (
        <section id="forare-larm" className="kort varning" role="alert" aria-labelledby="forare-larm-rubrik">
          <h2 id="forare-larm-rubrik">{text.alarms}</h2>
          <ul className="lista">
            {(overview.alarms ?? []).map((alarm) => (
              <li key={refKey(alarm.service)}>
                <div className="vem">
                  <b>{alarmText(alarm, now, text)}</b>
                </div>
                {overview.may_set && (
                  <div className="kontroller">
                    <button type="button" onClick={() => void act(() => api.clearAlarm(alarm.service))}>
                      {text.clear}
                    </button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}
      <Settings settings={overview.settings} disabled={!overview.may_set} text={text} onChange={(settings) => void act(() => api.driverSettings(settings))} />
      <h2>
        {text.drivers} <span className="antal">{(overview.drivers ?? []).length}</span>
      </h2>
      <ul id="forarna" className="lista">
        {(overview.drivers ?? []).length ? (
          (overview.drivers ?? []).map((row) => <DriverLine key={row.driver.id} row={row} now={now} text={text} free={free} onHandOut={(service) => void act(() => api.handOut(row.driver.id, service))} onTakeBack={() => void act(() => api.takeBack(row.driver.id))} />)
        ) : (
          <li className="tom">{text.noDrivers}</li>
        )}
      </ul>
      <h2>{overview.services.kind === "train" ? text.trains : text.services}</h2>
      <ul id="tjanster" className="lista">
        {(overview.services.services ?? []).map((offer) => (
          <li key={refKey(offer.service)} className={offer.released_on_line ? "vantar" : undefined}>
            <div className="vem">
              <b>{`${offer.number} · ${(offer.trains ?? []).join(", ")}`}</b>
              <span className="liten">{serviceText(offer, text)}</span>
            </div>
            <span className="liten">{offer.done ? text.done : offer.taken ? text.takenBy(offer.driver_name ?? names.get(offer.driver ?? "") ?? "") : offer.released_on_line ? text.released : text.free}</span>
          </li>
        ))}
      </ul>
      <h2>{text.messages}</h2>
      <ul id="forar-meddelanden" className="lista">
        {(overview.messages ?? []).length ? (
          (overview.messages ?? []).map((message) => (
            <li key={message.seq}>
              <div className="vem">
                <b>{`${message.model_time} · ${text.kinds[message.kind] ?? message.kind}`}</b>
                <span className="liten">{[message.driver_name, message.train_number ? text.train(message.train_number) : null, message.service_number ? text.serviceNumber(message.service_number) : null].filter(Boolean).join(" · ")}</span>
              </div>
            </li>
          ))
        ) : (
          <li className="tom">{text.noMessages}</li>
        )}
      </ul>
      <section id="forar-qr" className="kort" aria-labelledby="forar-qr-rubrik">
        <h2 id="forar-qr-rubrik">{text.qr}</h2>
        <p className="liten">{text.qrNote}</p>
        {joining && (
          <>
            <img src="/api/drift/1/drivers/connect.svg" alt={joining.url} width={180} height={180} />
            <p className="koden tm-mono">{text.code(joining.code)}</p>
            <p className="liten tm-mono">{joining.url}</p>
          </>
        )}
      </section>
      {overview.may_set && <LetInLead text={text} onMessage={say} />}
    </section>
  );
}

function Settings({ settings, disabled, text, onChange }: { settings: DriverSettings; disabled: boolean; text: Text; onChange: (settings: DriverSettings) => void }) {
  const box = (key: "reality" | "clearances" | "arrival", label: string) => (
    <label className="val">
      <input type="checkbox" name={key} checked={Boolean(settings[key])} disabled={disabled} onChange={(event) => onChange({ ...settings, [key]: event.target.checked })} /> {label}
    </label>
  );
  return (
    <fieldset id="forar-val" className="kort">
      <legend>{text.settings}</legend>
      {box("reality", text.reality)}
      {box("clearances", text.clearances)}
      {box("arrival", text.arrival)}
      <p className="liten">{text.settingsNote}</p>
    </fieldset>
  );
}

function DriverLine({ row, now, text, free, onHandOut, onTakeBack }: { row: DriverRow; now: Now; text: Text; free: ServiceOffer[]; onHandOut: (service: ServiceRef) => void; onTakeBack: () => void }) {
  const [chosen, setChosen] = useState(free[0] ? refKey(free[0].service) : "");
  const driver = row.driver;
  const details = [text.levels[driver.level] ?? driver.level, driver.state ? (text.states[driver.state] ?? driver.state) : null, row.service ? text.service(row.service.number, (row.service.trains ?? []).join(", ")) : text.noService, whereText(row, now, text) || null, row.checkin ? text.checkin(row.checkin.place_name, row.checkin.model_time) : null].filter(Boolean);
  const pick = free.find((offer) => refKey(offer.service) === chosen) ?? free[0];
  return (
    <li className={row.message ? "vantar" : undefined}>
      <div className="vem">
        <b>{driver.name ?? driver.id}</b>
        <span className="liten">{details.join(" · ")}</span>
        {row.message && <span className="liten">{`${row.message.model_time} · ${text.kinds[row.message.kind] ?? row.message.kind}`}</span>}
      </div>
      <div className="kontroller">
        {free.length > 0 && (
          <>
            <select aria-label={`${text.choose}: ${driver.name ?? driver.id}`} value={pick ? refKey(pick.service) : ""} onChange={(event) => setChosen(event.target.value)}>
              {free.map((offer) => (
                <option key={refKey(offer.service)} value={refKey(offer.service)}>
                  {`${offer.number} · ${offer.start.time ?? ""} ${offer.start.place_name}`}
                </option>
              ))}
            </select>
            <button type="button" onClick={() => pick && onHandOut(pick.service)}>
              {text.handOut}
            </button>
          </>
        )}
        {row.service && (
          <button type="button" className="fara" onClick={onTakeBack}>
            {text.takeBack}
          </button>
        )}
      </div>
    </li>
  );
}

function LetInLead({ text, onMessage }: { text: Text; onMessage: (error: unknown) => void }) {
  const [name, setName] = useState("");
  const [given, setGiven] = useState<OneTimeCodeAnswer | null>(null);
  return (
    <section id="slapp-in-lokledare" className="kort" aria-labelledby="lokledare-rubrik">
      <h2 id="lokledare-rubrik">{text.letIn}</h2>
      <p className="liten">{text.letInNote}</p>
      {given ? (
        <p className="koden tm-mono" aria-live="polite">
          {text.given(given.code)}
        </p>
      ) : (
        <form
          className="formular rad"
          onSubmit={(event) => {
            event.preventDefault();
            void api.locoLeadCode(name).then(setGiven, onMessage);
          }}
        >
          <label>
            {text.who} <input maxLength={40} autoComplete="off" value={name} onChange={(event) => setName(event.target.value)} />
          </label>
          <button type="submit" className="tm-knapp primar">
            {text.give}
          </button>
        </form>
      )}
    </section>
  );
}
