// Inställningar (TKLAPP): Anslutning to the meet (KLAR-02, KLAR-13), Skärmar och ljud on this
// screen (TKL33), and the PIN. The hub is found on the meet's network; over the internet the
// dispatcher gives a code. The key from the approval stays in TKL's server.
import { useState, type FormEvent } from "react";
import type { Connection, FoundHub, Question, State } from "./api";
import { SOUND_NAMES, type Sounds } from "./ljud";
import { SIDE } from "./niva0";

export type Part = "anslutning" | "ljud" | "pin";
const PARTS: [Part, string][] = [
  ["anslutning", "Anslutning"],
  ["ljud", "Skärmar och ljud"],
  ["pin", "PIN"],
];
const STATUS: Record<string, string> = { waiting: "Väntar", approved: "Godkänd", refused: "Nekad", revoked: "Återkallad" };

type Props = {
  part: Part;
  state: State;
  connection: Connection | null;
  hubs: FoundHub[] | null;
  questions: Question[];
  sounds: Sounds;
  version: number | null;
  onPart: (part: Part) => void;
  onFind: () => void;
  onConnect: (address: string, code: string | null) => Promise<void>;
  onDisconnect: () => Promise<void>;
  onExit: (section: string, exit: string) => void;
  onSounds: (sounds: Sounds) => void;
  onPin: (old: string, pin: string) => Promise<void>;
};

export function Installningar(props: Props) {
  const { part, state, connection, onPart } = props;
  const waiting = connection?.connected && connection.status === "waiting";
  return (
    <div className="installningar">
      <nav className="sidomeny" aria-label="Inställningar">
        {PARTS.map(([key, label]) => (
          <button key={key} type="button" aria-current={part === key ? "page" : undefined} onClick={() => onPart(key)}>
            {label}
            {key === "anslutning" && waiting ? <span className="liten"> (väntar)</span> : null}
          </button>
        ))}
        <p className="liten">
          {state.software} · {state.mode === "cloud" ? "i molnet" : "lokal"}
        </p>
      </nav>
      <div className="innehall">
        {part === "anslutning" ? <Anslutning {...props} /> : null}
        {part === "ljud" ? <Ljud sounds={props.sounds} onSounds={props.onSounds} /> : null}
        {part === "pin" ? <Pin onPin={props.onPin} /> : null}
      </div>
    </div>
  );
}

export function Anslutning({ state, connection, hubs, questions, version, onFind, onConnect, onDisconnect, onExit }: Props) {
  const cloud = state.mode === "cloud";
  const [address, setAddress] = useState("");
  const [code, setCode] = useState("");
  const [message, setMessage] = useState("");
  const [sending, setSending] = useState(false);
  const connect = async (to: string, withCode: string | null) => {
    setMessage("");
    setSending(true);
    try {
      await onConnect(to, withCode);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Det gick inte att ansluta.");
    } finally {
      setSending(false);
    }
  };
  const submit = (event: FormEvent) => {
    event.preventDefault();
    void connect(address.trim(), code.trim() || null);
  };
  const name = state.station?.name ?? "";
  if (connection?.connected) {
    const approved = connection.status === "approved";
    return (
      <>
        <section className="ruta">
          <h2>{approved ? "Ansluten" : connection.status === "waiting" ? "Väntar på godkännande" : STATUS[connection.status ?? ""] ?? "Ansluten"}</h2>
          <ol className="steg">
            <li className="klart">Hittade Hubben · {connection.hub_name ?? connection.address}</li>
            <li className="klart">Bad om att få köra {name}, med utsidan version {connection.outside_version}</li>
            <li className={approved ? "klart" : ""}>{approved ? "Godkänd av trafikledningen" : "Godkännande av trafikledningen i Klienter"}</li>
            <li className={approved ? "klart" : ""}>Nyckel för träffen och platsen</li>
          </ol>
          {connection.message ? <p className="fel">{connection.message}</p> : null}
          <p className="liten">Nyckeln klarar omstarter och kan återkallas i Hubben. Den stannar i TKL och visas aldrig.</p>
          <button type="button" className="fara" onClick={() => void onDisconnect()}>
            Koppla från
          </button>
        </section>
        {questions.length ? (
          <section className="ruta">
            <h2>Hubben frågar</h2>
            {questions.map((q) => (
              <div key={q.section} className="fraga">
                <p>{`Vilken av ${name}s utfarter går mot ${q.other_name}?${q.side ? ` Sträckan ligger åt ${SIDE[q.side]?.toLowerCase()}.` : ""}`}</p>
                <div className="knappar">
                  {q.alternatives.map((a) => (
                    <button key={a.exit} type="button" onClick={() => onExit(q.section, a.exit)}>
                      {a.name ? `${a.exit} · ${a.name}` : a.exit}
                    </button>
                  ))}
                </div>
              </div>
            ))}
            <p className="liten">Trafikledningen kan också svara i Klienter. Det första svaret gäller hela träffen.</p>
          </section>
        ) : null}
      </>
    );
  }
  return (
    <>
      <section className="ruta">
        <h2>{cloud ? "Hubbar över internet" : "Hubben på träffnätet"}</h2>
        <p className="liten">
          {cloud
            ? "TKL i molnet når de hubbar den är inställd för. Över internet behövs en kod från trafikledningen."
            : "Bara en hubb med startad träff syns här."}
        </p>
        {hubs === null ? (
          <p className="tom">Letar …</p>
        ) : hubs.length ? (
          <ul className="hubbar">
            {hubs.map((hub) => (
              <li key={hub.address}>
                <div>
                  <b>{hub.name}</b>
                  <span className="liten">
                    {" "}
                    · {hub.meet ?? "ingen träff startad"} · {hub.nearby ? "på träffnätet" : "över internet"}
                  </span>
                </div>
                {hub.nearby ? (
                  <button type="button" className="primar" disabled={sending} onClick={() => void connect(hub.address, null)}>
                    Anslut
                  </button>
                ) : (
                  <button type="button" onClick={() => setAddress(hub.address)}>
                    Välj
                  </button>
                )}
              </li>
            ))}
          </ul>
        ) : (
          <p className="tom">Ingen hubb hittades.</p>
        )}
        <button type="button" className="lank" onClick={onFind}>
          Leta igen
        </button>
      </section>
      <form className="ruta" onSubmit={submit}>
        <h2>Ange adress och kod</h2>
        <p className="liten">Över internet behövs en kod från trafikledningen. Den står under Anslut i trafikledningens sidhuvud, eller i Provbanan.</p>
        <label>
          Hubbens adress
          <input value={address} onChange={(e) => setAddress(e.target.value)} placeholder={cloud ? "Välj en hubb ovan" : "http://trainmeet.local"} required />
        </label>
        <label>
          Kod
          <input value={code} onChange={(e) => setCode(e.target.value)} inputMode="numeric" autoComplete="off" maxLength={20} className="tm-mono" />
        </label>
        <button type="submit" className="primar" disabled={sending || !address.trim()}>
          Anslut
        </button>
      </form>
      <section className="ruta">
        <h2>Det här säger TKL</h2>
        <p>
          Stationen <b>{name}</b> <span className="tm-mono liten">{state.station?.station_id}</span>
          {version ? `, utsidan version ${version} följer med.` : ", och utsidan i Studio blir version 1 när TKL ansluter."}
        </p>
        <p className="liten">Trafikledningen väljer driftplatsen när TKL godkänns. Flera kan be om samma plats; den som svarar först gäller.</p>
      </section>
      {message ? (
        <p className="fel" role="alert">
          {message}
        </p>
      ) : null}
    </>
  );
}

function Ljud({ sounds, onSounds }: { sounds: Sounds; onSounds: (sounds: Sounds) => void }) {
  return (
    <section className="ruta">
      <h2>Ljud på den här skärmen</h2>
      {(Object.keys(SOUND_NAMES) as (keyof Sounds)[]).map((sound) => (
        <label key={sound} className="kryss">
          <input type="checkbox" checked={sounds[sound]} onChange={(e) => onSounds({ ...sounds, [sound]: e.target.checked })} />
          {SOUND_NAMES[sound]}
        </label>
      ))}
      <p className="liten">Skärmarna sparas i webbläsaren. Varje flik eller platta väljer sitt eget ljud. Ett byte skickar aldrig några order.</p>
    </section>
  );
}

function Pin({ onPin }: { onPin: (old: string, pin: string) => Promise<void> }) {
  const [old, setOld] = useState("");
  const [pin, setPin] = useState("");
  const [message, setMessage] = useState("");
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setMessage("");
    try {
      await onPin(old, pin);
      setOld("");
      setPin("");
      setMessage("PIN-koden är bytt.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Det gick inte.");
    }
  };
  return (
    <form className="ruta" onSubmit={submit}>
      <h2>Byt PIN</h2>
      <label>
        Nuvarande PIN
        <input type="password" inputMode="numeric" value={old} onChange={(e) => setOld(e.target.value.replace(/\D/g, ""))} autoComplete="current-password" />
      </label>
      <label>
        Ny PIN
        <input type="password" inputMode="numeric" value={pin} onChange={(e) => setPin(e.target.value.replace(/\D/g, ""))} autoComplete="new-password" />
      </label>
      <p className="liten">Minst fyra siffror. Andra skärmar får låsa upp igen.</p>
      {message ? <p role="status">{message}</p> : null}
      <button type="submit" className="primar" disabled={old.length < 4 || pin.length < 4}>
        Byt PIN
      </button>
    </form>
  );
}
