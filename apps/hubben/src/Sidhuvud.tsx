import { BottomNav, linkClick, ProductName, Skylt, type NavItem } from "@trainmeet/design";
import { useState } from "react";
import { connectPicture, type Joining, type Now, type Weekday } from "./api";
import { clockNote, clockText, meetTitle, PROVBANAN, WEEKDAYS, type MeetChoice } from "./traff";

// The header (S2, TRAFIK-12): the same for everyone. It always has the meet with Byt träff,
// the meet clock, Anslut and Väntar; logged in, one also gets the buttons (S1). Planering and
// Drift are tabs side by side, as in the spec's picture of the header.

export const DRIFT_TABS: [string, string][] = [
  ["Nu", "/drift"],
  ["Klienter", "/drift/klienter"],
  ["Logg", "/drift/logg"],
];

/** Planering's tabs for the meet in view (null: the list of meets is in view), or else the
 * meet that runs; without one (or on Provbanan, which has no plan) only the list of meets. */
export function planningTabs(now: Now | null, viewed?: string | null): [string, string][] {
  const id = viewed !== undefined ? viewed : now && now.meet_id !== "provbanan" ? now.meet_id : null;
  if (!id) return [["Träffar", "/planering"]];
  const meet = `/planering/${encodeURIComponent(id)}`;
  return [
    ["Data", `${meet}/data`],
    ["Bana", `${meet}/bana`],
    ["Graf", `${meet}/graf`],
    ["Versioner", `${meet}/versioner`],
  ];
}

export type Menu = "byt" | "anslut" | null;

export type HeaderProps = {
  /** The address of the page shown, which marks its tab and the gear. */
  current: string;
  /** The meet Planering shows, for Planering's tabs (null on the list of meets); left out, the
   * meet that runs. */
  viewed?: string | null;
  /** The tabs at the bottom on the phone, if the page has them. */
  bottom?: { label: string; items: NavItem[] };
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
  const { current, viewed, bottom, hubName, admin, now, elapsedMs, waiting, menu, navigate, onMenu } = props;
  const toggle = (which: Menu) => onMenu(menu === which ? null : which);
  const tab = (href: string) => ({ "aria-current": href === current ? ("page" as const) : undefined, onClick: linkClick(navigate, href) });
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
          {planningTabs(now, viewed).map(([label, href]) => (
            <a key={href} href={href} {...tab(href)}>
              {label}
            </a>
          ))}
          <span className="grupp">Drift</span>
          {DRIFT_TABS.map(([label, href]) => (
            <a key={href} href={href} {...tab(href)}>
              {label}
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
          {/* Inställningar, always to the left of the account (TRAFIK-30, H48). */}
          <a id="gear" className="hknapp kugge" href="/installningar" aria-label="Inställningar" title="Inställningar" {...tab("/installningar")}>
            <Gear />
          </a>
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
      {bottom && <BottomNav items={bottom.items} label={bottom.label} navigate={navigate} />}
    </>
  );
}

function Gear() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <circle cx="12" cy="12" r="3.2" />
      <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" />
    </svg>
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
