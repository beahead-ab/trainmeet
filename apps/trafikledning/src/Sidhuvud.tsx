import { BottomNav, linkClick, ProductName, Skylt, type NavItem } from "@trainmeet/design";
import { useState } from "react";
import { connectPicture, type Joining, type Now, type Weekday } from "./api";
import { clockNote, clockText, meetTitle, PROVBANAN, WEEKDAYS, type MeetChoice } from "./drift";

// The header (S2, TRAFIK-12): the same for everyone. It always has the meet with Byt träff,
// the meet clock, Anslut and Väntar; logged in, one also gets the buttons (S1). Planering and
// Drift are tabs side by side, as in the spec's picture of the header.

export type Page = "start" | "nu" | "klienter" | "logg" | "provbanan";

export const DRIFT_TABS: [Page, string, string][] = [
  ["nu", "Nu", "/drift"],
  ["klienter", "Klienter", "/drift/klienter"],
  ["logg", "Logg", "/drift/logg"],
];

/** Planering's tabs for the meet that runs; Provbanan has no plan, only the list of meets. */
export function planningTabs(now: Now | null): [string, string][] {
  if (!now || now.meet_id === "provbanan") return [["Träffar", "/planering"]];
  const meet = `/planering/${encodeURIComponent(now.meet_id)}`;
  return [
    ["Data", `${meet}/data`],
    ["Bana", `${meet}/bana`],
    ["Graf", `${meet}/graf`],
    ["Versioner", `${meet}/versioner`],
  ];
}

/** Nu, Klienter and Logg: Drift's own pages, in Kontrollrummet. */
export const isDrift = (page: Page) => page === "nu" || page === "klienter" || page === "logg";

export type Menu = "byt" | "anslut" | null;

export type HeaderProps = {
  page: Page;
  hubName: string;
  admin: boolean;
  now: Now | null;
  /** Milliseconds since Nu came from the hub, for the clock between its answers. */
  elapsedMs: number;
  waiting: number;
  choices: MeetChoice[];
  asked: string | null;
  menu: Menu;
  joining: Joining | null;
  joinedAt: number;
  navigate: (href: string) => void;
  onMenu: (menu: Menu) => void;
  onStart: (choice: MeetChoice, day: Weekday) => void;
  onLogOut: () => void;
};

export function Sidhuvud(props: HeaderProps) {
  const { page, hubName, admin, now, elapsedMs, waiting, menu, navigate, onMenu } = props;
  const toggle = (which: Menu) => onMenu(menu === which ? null : which);
  const drift: NavItem[] = DRIFT_TABS.map(([key, label, href]) => ({ href, label, current: key === page }));
  return (
    <>
      <a className="tm-hoppa" href="#innehall">
        Hoppa till innehållet
      </a>
      <header className="tm-sidhuvud hubbhuvud">
        <a className="tm-marke" href="/" onClick={linkClick(navigate, "/")}>
          <Skylt />
          <ProductName name="HUB" label="TrainMeet Hub" />
        </a>
        <span className="tm-streck" aria-hidden="true" />
        {admin ? (
          <div className="tm-meny-ankare">
            <button id="change-meet" type="button" className="traffval" aria-expanded={menu === "byt"} aria-controls="byt-traff" onClick={() => toggle("byt")}>
              <span className="osynlig">Byt träff: </span>
              {now ? meetTitle(now) : hubName} <span aria-hidden="true">▾</span>
            </button>
            {menu === "byt" && <BytTraff {...props} />}
          </div>
        ) : (
          <span id="meet-name" className="traffval">
            {now ? meetTitle(now) : hubName}
          </span>
        )}
        <nav className="tm-flikar" aria-label="Hubben">
          <span className="grupp">Planering</span>
          {planningTabs(now).map(([label, href]) => (
            <a key={href} href={href}>
              {label}
            </a>
          ))}
          <span className="grupp">Drift</span>
          {drift.map((tab) => (
            <a key={tab.href} href={tab.href} aria-current={tab.current ? "page" : undefined} onClick={linkClick(navigate, tab.href)}>
              {tab.label}
            </a>
          ))}
        </nav>
        <span className="tm-fyll" />
        <div className="tm-hoger">
          <span id="clock" className={"klocka" + (now?.clock.running ? " gar" : "")} title="Träffklockan">
            <span className="lampa" aria-hidden="true" />
            <b>{clockText(now, elapsedMs)}</b>
            {now && <span className="not">{clockNote(now)}</span>}
            <span className="osynlig">{now ? (now.clock.running ? " Klockan går." : " Klockan står still.") : " Ingen träff är startad."}</span>
          </span>
          {admin ? (
            <>
              <button id="connect" type="button" className="hknapp" aria-expanded={menu === "anslut"} aria-controls="connect-panel" onClick={() => toggle("anslut")}>
                Anslut
              </button>
              <a id="waiting" className={"hknapp" + (waiting > 0 ? " har" : "")} href="/drift/klienter" onClick={linkClick(navigate, "/drift/klienter")}>
                Väntar <b id="waiting-count">{waiting}</b>
              </a>
              <button id="logout" type="button" className="hknapp" onClick={props.onLogOut}>
                Logga ut
              </button>
            </>
          ) : (
            <a className="tm-knapp primar loggain" href="/" onClick={linkClick(navigate, "/")}>
              Logga in
            </a>
          )}
        </div>
      </header>
      {admin && menu === "anslut" && <Anslut joining={props.joining} at={props.joinedAt} />}
      {isDrift(page) && <BottomNav items={drift} label="Drift" navigate={navigate} />}
    </>
  );
}

/** Byt träff (TRAFIK-29): one click changes the meet, and Drift runs the one chosen (H40). */
function BytTraff({ now, choices, asked, onStart }: HeaderProps) {
  const running = now ? `${now.meet_id}:${now.version}` : null;
  const [day, setDay] = useState<Weekday>(now?.traffic_day ?? "mon");
  const [armed, setArmed] = useState(false);
  const current = choices.find((choice) => choice.value === running);
  return (
    <div id="byt-traff" className="tm-panel bytpanel" role="dialog" aria-label="Byt träff">
      <div className="tm-panel-rubrik">
        <h2>Byt träff</h2>
      </div>
      <ul className="traffar">
        {choices.map((choice) => {
          const runs = choice.value === running;
          return (
            <li key={choice.value}>
              <button type="button" className={"traff" + (choice.value === asked ? " vald" : "")} aria-current={runs ? "true" : undefined} disabled={runs} onClick={() => onStart(choice, day)}>
                <span className="vad">
                  <b>{choice.name}</b>
                  <span>{choice.note}</span>
                </span>
                {runs && <span className="kor">Drift kör</span>}
                {!runs && choice === PROVBANAN && <span className="prov">Prov</span>}
              </button>
            </li>
          );
        })}
      </ul>
      <label className="dag">
        Trafikdag{" "}
        <select id="new-day" value={day} onChange={(event) => setDay(event.target.value as Weekday)}>
          {WEEKDAYS.map(([key, name]) => (
            <option key={key} value={key}>
              {name}
            </option>
          ))}
        </select>
      </label>
      <p className="liten">Ett klick byter träff, och Drift kör den du väljer. Den gamla arkiveras, och boxar och klienter ansluter med den nya koden. Versionerna publiceras i Planering.</p>
      <div className="panelfot">
        <a href="/planering">Alla träffar</a>
        {current && (
          // Two presses to start the running meet over: the old run is archived and its
          // clients let go.
          <button
            id="restart-meet"
            type="button"
            className={"lankknapp" + (armed ? " fara" : "")}
            onClick={() => {
              if (!armed) return setArmed(true);
              setArmed(false);
              onStart(current, day);
            }}
          >
            {armed ? "Tryck igen för att börja om" : "Börja om med samma träff"}
          </button>
        )}
      </div>
    </div>
  );
}

/** Anslut (S2): the meet's code, the address a box and a screen open, and the QR code. */
function Anslut({ joining, at }: { joining: Joining | null; at: number }) {
  return (
    <section id="connect-panel" className="anslut" aria-label="Anslut">
      <div>
        <p className="etikett">Anslut en box, en TKL eller en skärm med koden</p>
        <p id="connect-code" className="anslutkod">
          {joining?.code ?? "------"}
        </p>
        <p className="liten">
          Eller skanna koden med telefonen. Boxen öppnas på{" "}
          <span id="connect-url" className="tm-mono">
            {joining?.url ?? ""}
          </span>
        </p>
        <p className="liten">
          En skärm öppnar{" "}
          <span id="connect-screen" className="tm-mono">
            {joining?.url.replace("/box#", "/skarm#") ?? ""}
          </span>
        </p>
      </div>
      {joining && <img id="connect-qr" src={connectPicture(at)} alt="QR-kod som öppnar boxen med koden" width={180} height={180} />}
    </section>
  );
}
