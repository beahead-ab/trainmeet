import { linkClick } from "@trainmeet/design";
import { useState, type FormEvent } from "react";
import type { HubInfo, Version } from "./api";

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
          <a href="/provbanan">Öppna Provbanan →</a>
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

function Built({ version }: { version: Version }) {
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

function HubCard({ info, message, navigate, onSetUp, onLogIn, onLogOut, onMessage }: StartProps & { info: HubInfo }) {
  const [name, setName] = useState(info.name);
  const [pin, setPin] = useState("");
  const [again, setAgain] = useState("");
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
    const submit = (event: FormEvent) => {
      event.preventDefault();
      onLogIn?.(pin);
    };
    return (
      <section className="kort" id="hubben">
        <h1>Logga in</h1>
        <p className="ingress">Utan inloggning kan du titta. Logga in med hubbens PIN-kod för att köra träffen.</p>
        <form id="login-form" className="formular" onSubmit={submit}>
          <label>
            PIN-kod <PinField id="pin" value={pin} onChange={setPin} />
          </label>
          <button type="submit" className="tm-knapp primar">
            Logga in
          </button>
        </form>
        <p id="hub-message" className="meddelande" role="alert">
          {message}
        </p>
      </section>
    );
  }
  return (
    <section className="kort" id="hubben">
      <h1>Inloggad</h1>
      <p className="ingress">Du är inloggad som hubbens lokala administratör.</p>
      <p className="lankar">
        <a href="/planering">Planera en träff →</a>
        <a href="/drift" onClick={linkClick(navigate, "/drift")}>
          Kör träffen →
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
