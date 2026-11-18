import { linkClick } from "@trainmeet/design";
import { useState, type FormEvent } from "react";
import { idLoginAddress, type HubInfo, type Version } from "./api";

// The start page: Den här hubben (first start, logging in, who one is: S1, H52) and what runs
// on the hub, as before (hub/page.py).

export const SPEC_URL = "https://platform.trainmeet.app";
export const REPO_URL = "https://github.com/beahead-ab/trainmeet";

export type StartProps = {
  info: HubInfo | null;
  version: Version | null;
  message: string;
  navigate: (href: string) => void;
  onSetUp?: (name: string, pin: string) => void;
  onLogIn?: (pin: string) => void;
  /** Engångskoden från trafikledningen (H56). */
  onLogInWithCode?: (code: string) => void;
  /** Logga in igen with the ticket from ID, without internet (KONTO-11). */
  onLogInAgain?: () => void;
  onLogOut?: () => void;
  onMessage?: (text: string) => void;
};

export function StartPage(props: StartProps) {
  const { info, version, navigate } = props;
  return (
    <>
      {info && <HubCard {...props} info={info} />}
      <section className="kort">
        <h1>Prova Drift</h1>
        <p className="ingress">Här kan du prova Drift med en påhittad träff på Provbanan.</p>
        <p className="lankar">
          <a href="/provbanan" onClick={linkClick(navigate, "/provbanan")}>
            Öppna Provbanan →
          </a>
          <a href="/planering">Planering →</a>
          <a href="/drift" onClick={linkClick(navigate, "/drift")}>
            Se träffen →
          </a>
        </p>
        {version && <Built version={version} />}
      </section>
      <footer className="fot">
        <a href={REPO_URL}>Koden på GitHub</a>
        <a href={SPEC_URL}>Specen</a>
        <span>AGPL-3.0</span>
      </footer>
    </>
  );
}

export function Built({ version }: { version: Version }) {
  const local = !version.commit && !version.pr;
  const built = version.built ? builtText(version.built) : "–";
  return (
    <dl className="bygge">
      <dt>Status</dt>
      <dd>
        <span className="status">Igång</span>
      </dd>
      <dt>Version</dt>
      <dd>{version.version}</dd>
      <dt>Ändring</dt>
      <dd>
        {local ? (
          <span className="lokal">Lokalt bygge</span>
        ) : version.pr && version.pr_url ? (
          <a href={version.pr_url}>{`#${version.pr}${version.title ? ` ${version.title}` : ""}`}</a>
        ) : (
          (version.title ?? "Direkt på main")
        )}
      </dd>
      <dt>Commit</dt>
      <dd>
        {version.commit && version.commit_url ? (
          <a className="tm-mono" href={version.commit_url}>
            {version.commit.slice(0, 7)}
          </a>
        ) : (
          "–"
        )}
      </dd>
      <dt>Byggd</dt>
      <dd>{built}</dd>
    </dl>
  );
}

/** When the image was built, in UTC as the old page showed it: 2026-11-06 07:12 UTC. */
export function builtText(iso: string): string {
  const when = new Date(iso);
  if (Number.isNaN(when.getTime())) return "–";
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${when.getUTCFullYear()}-${pad(when.getUTCMonth() + 1)}-${pad(when.getUTCDate())} ${pad(when.getUTCHours())}:${pad(when.getUTCMinutes())} UTC`;
}

function HubCard({ info, message, navigate, onSetUp, onLogIn, onLogInWithCode, onLogInAgain, onLogOut, onMessage }: StartProps & { info: HubInfo }) {
  const [name, setName] = useState(info.name);
  const [pin, setPin] = useState("");
  const [again, setAgain] = useState("");
  const [code, setCode] = useState("");
  const [withCode, setWithCode] = useState(false);
  if (!info.set_up) {
    const submit = (event: FormEvent) => {
      event.preventDefault();
      if (pin !== again) return onMessage?.("PIN-koderna är inte lika.");
      onSetUp?.(name, pin);
    };
    return (
      <section className="kort" id="hubben">
        <h1>Välkommen till hubben</h1>
        <p className="ingress">Välj ett namn på hubben och en PIN-kod. Du blir hubbens lokala administratör och loggar in med koden.</p>
        <form id="setup-form" className="formular" onSubmit={submit}>
          <label>
            Hubbens namn <input id="hub-name" maxLength={40} required value={name} autoComplete="off" onChange={(event) => setName(event.target.value)} />
          </label>
          <label>
            PIN-kod, 6–12 siffror <PinField id="pin" value={pin} onChange={setPin} fresh />
          </label>
          <label>
            Samma PIN-kod igen <PinField id="pin-again" value={again} onChange={setAgain} fresh />
          </label>
          <button type="submit" className="tm-knapp primar">
            Spara och logga in
          </button>
        </form>
        <p id="hub-message" className="meddelande" role="alert">
          {message}
        </p>
      </section>
    );
  }
  if (!info.logged_in) {
    // The PIN, or a one-time code from the dispatchers (H56): one at a time, so a wrong guess
    // never counts twice.
    const submit = (event: FormEvent) => {
      event.preventDefault();
      if (withCode) onLogInWithCode?.(code);
      else onLogIn?.(pin);
    };
    return (
      <section className="kort" id="hubben">
        <h1>Logga in</h1>
        <p className="ingress">Utan inloggning kan du titta. Logga in med hubbens PIN-kod, eller med en engångskod från trafikledningen, för att köra träffen.</p>
        <form id="login-form" className="formular" onSubmit={submit}>
          {withCode ? (
            <label>
              Engångskod, 6 siffror{" "}
              <input id="code" type="text" inputMode="numeric" pattern="[0-9]{6}" minLength={6} maxLength={6} required autoComplete="one-time-code" value={code} onChange={(event) => setCode(event.target.value)} />
            </label>
          ) : (
            <label>
              PIN-kod <PinField id="pin" value={pin} onChange={setPin} />
            </label>
          )}
          <button type="submit" className="tm-knapp primar">
            Logga in
          </button>
          {onLogInWithCode && (
            <button id="kodval" type="button" className="tm-knapp" onClick={() => setWithCode(!withCode)}>
              {withCode ? "Jag har hubbens PIN-kod" : "Jag har en engångskod"}
            </button>
          )}
        </form>
        {info.id_login && <IdLogIn ticketName={info.ticket_name} onAgain={onLogInAgain} />}
        <p id="hub-message" className="meddelande" role="alert">
          {message}
        </p>
      </section>
    );
  }
  return (
    <section className="kort" id="hubben">
      <h1>Inloggad</h1>
      {info.admin ? (
        <p className="ingress">Du är inloggad som hubbens lokala administratör.</p>
      ) : info.person ? (
        <p className="ingress">{`Du är inloggad med TrainMeet ID som ${info.person}. Dina roller på träffarna kommer från ID.`}</p>
      ) : (
        <p className="ingress">Du är insläppt som trafikledare med en engångskod. Det gäller den här träffen, tills den slutar eller trafikledningen tar bort dig.</p>
      )}
      <p className="lankar">
        {info.admin && <a href="/planering">Planera en träff →</a>}
        <a href="/drift" onClick={linkClick(navigate, "/drift")}>
          Kör träffen →
        </a>
        <a href="/deltagare" onClick={linkClick(navigate, "/deltagare")}>
          Deltagarsidan →
        </a>
      </p>
      <button id="logout-start" type="button" className="tm-knapp" onClick={onLogOut}>
        Logga ut
      </button>
      <p id="hub-message" className="meddelande" role="alert">
        {message}
      </p>
    </section>
  );
}

/** Logga in med TrainMeet ID (#78, KONTO-27): to ID and back to the page one came from. A
 * login that did not go through comes back with ?inloggning=fel. */
export function IdLogIn({
  label = "Logga in med TrainMeet ID",
  failedText = "Inloggningen med TrainMeet ID gick inte. Försök igen.",
  ticketName = null,
  againLabel = (name: string) => `Logga in igen som ${name}`,
  againNote = "Utan internet: biljetten från TrainMeet ID gäller i 30 dagar på den här Pi:n.",
  onAgain,
}: {
  label?: string;
  failedText?: string;
  /** On the meet's Pi: whose ticket from ID this browser has (KONTO-11, KONTO-37). */
  ticketName?: string | null;
  againLabel?: (name: string) => string;
  againNote?: string;
  onAgain?: () => void;
}) {
  const failed = typeof window !== "undefined" && new URLSearchParams(window.location.search).get("inloggning") === "fel";
  const back = typeof window !== "undefined" ? new URLSearchParams(window.location.search).get("next") ?? window.location.pathname : "/";
  return (
    <div className="idinloggning">
      {ticketName && onAgain && (
        <>
          <button id="id-again" type="button" className="tm-knapp primar" onClick={onAgain}>
            {againLabel(ticketName)}
          </button>
          <p className="liten">{againNote}</p>
        </>
      )}
      <a id="id-login" className={ticketName ? "tm-knapp" : "tm-knapp primar"} href={idLoginAddress(back)}>
        {label}
      </a>
      {failed && (
        <p className="meddelande" role="alert">
          {failedText}
        </p>
      )}
    </div>
  );
}

function PinField({ id, value, onChange, fresh = false }: { id: string; value: string; onChange: (value: string) => void; fresh?: boolean }) {
  return (
    <input
      id={id}
      type="password"
      inputMode="numeric"
      pattern="[0-9]{6,12}"
      minLength={6}
      maxLength={12}
      required
      autoComplete={fresh ? "new-password" : "current-password"}
      value={value}
      onChange={(event) => onChange(event.target.value)}
    />
  );
}
