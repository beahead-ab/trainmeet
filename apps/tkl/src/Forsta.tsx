// Första start, tre rutor (TKLAPP): the station, the PIN, and TrainMeet ID, which comes later
// (#78). After that the PIN locks TKL when it starts and when it is locked by hand (TKL18).
import { useState, type FormEvent } from "react";
import type { State } from "./api";

const ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$/;

/** The station's short name as its id: lower case, letters and digits (TKL14). */
export function shortId(name: string): string {
  return name
    .toLowerCase()
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 40);
}

export function FirstStart({ cloud, onSetUp }: { cloud: boolean; onSetUp: (name: string, stationId: string, pin: string) => Promise<void> }) {
  const [name, setName] = useState("");
  const [stationId, setStationId] = useState("");
  const [touched, setTouched] = useState(false);
  const [pin, setPin] = useState("");
  const [again, setAgain] = useState("");
  const [message, setMessage] = useState("");
  const id = touched ? stationId : shortId(name);
  const pinOk = /^[0-9]{4,12}$/.test(pin);
  const same = pinOk && pin === again;
  const ready = name.trim().length > 0 && ID_PATTERN.test(id) && same;
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!ready) return;
    setMessage("");
    try {
      await onSetUp(name.trim(), id, pin);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Det gick inte.");
    }
  };
  return (
    <form className="forsta" onSubmit={submit}>
      <p className="overrad">Första start · tre rutor</p>
      <h1>{name.trim() ? `Gör den här datorn till ${name.trim()}s ställverk.` : "Gör den här datorn till stationens ställverk."}</h1>
      {cloud ? <p className="liten">TKL i molnet: stationen hör till den här webbläsaren tills TrainMeet ID finns i TKL.</p> : null}
      <div className="rutor">
        <fieldset className="ruta">
          <legend>1 · Stationen</legend>
          <label>
            Namn
            <input value={name} onChange={(e) => setName(e.target.value)} maxLength={40} autoComplete="off" required />
          </label>
          <label>
            Kort namn
            <input
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
          <p className="liten">Stationens id skapas här, av det korta namnet. Det följer stationen till varje träff.</p>
        </fieldset>
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
          <p className="liten">{same ? "✓ Lika. " : again ? "Inte lika än. " : ""}Minst fyra siffror. PIN:en frågas när TKL startar och när den låsts.</p>
        </fieldset>
        <fieldset className="ruta valfri">
          <legend>3 · TrainMeet ID · valfritt</legend>
          <p>Synka stationens utsida till Hubben och använd TKL i molnet.</p>
          <p className="liten">Kommer när inloggningen med TrainMeet ID kommer till TKL. Till dess stannar allt på datorn.</p>
        </fieldset>
      </div>
      <p className="liten">Efter starten är stationen på nivå 0: skriv spår och utfarter i Studio och anslut till träffen. Inget lämnar datorn förrän du ansluter.</p>
      {message ? (
        <p className="fel" role="alert">
          {message}
        </p>
      ) : null}
      <button type="submit" className="primar" disabled={!ready}>
        Lås med PIN och starta
      </button>
    </form>
  );
}

export function Locked({ state, onUnlock }: { state: State; onUnlock: (pin: string) => Promise<void> }) {
  const [pin, setPin] = useState("");
  const [message, setMessage] = useState("");
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setMessage("");
    try {
      await onUnlock(pin);
    } catch (error) {
      setPin("");
      setMessage(error instanceof Error ? error.message : "Det gick inte.");
    }
  };
  return (
    <form className="last" onSubmit={submit}>
      <h1>{state.station?.name ?? "TKL"}</h1>
      <p>TKL är låst. Skriv PIN-koden.</p>
      <label>
        PIN
        <input value={pin} onChange={(e) => setPin(e.target.value.replace(/\D/g, ""))} inputMode="numeric" type="password" autoComplete="current-password" maxLength={12} autoFocus />
      </label>
      {message ? (
        <p className="fel" role="alert">
          {message}
        </p>
      ) : null}
      <button type="submit" className="primar" disabled={pin.length < 4}>
        Lås upp
      </button>
    </form>
  );
}
