import { useEffect, useState } from "react";
import { idLoginAddress, LEVELS, type Level } from "./api";
import { clockText } from "./clock";
import type { Lok, LokState } from "./store";
import { TEXT, type Language } from "./text";
import { ClockPill, Problem } from "./ui";

// Kom in (LOK-01, LOK-16, LOK-32, main.jpg): the QR code led here. A name, a language and a
// level are enough; TrainMeet ID is optional. On the meet's network the code is not needed;
// elsewhere the hub asks for it, and the code field shows.

export function Kom({ lok, state, now }: { lok: Lok; state: LokState; now: number | null }) {
  const [name, setName] = useState(state.hub?.person ?? "");
  // Logged in with TrainMeet ID: the name comes from there, as long as the driver has typed none.
  const person = state.hub?.person ?? null;
  useEffect(() => {
    if (person) setName((typed) => typed || person);
  }, [person]);
  const [language, setLanguage] = useState<Language>(state.language);
  const [level, setLevel] = useState<Level>("easy");
  const [code, setCode] = useState(state.code ?? "");
  const text = TEXT[language];
  const loginWithId = state.hub?.id_login && !state.hub.person;
  const next = `/lokforaren/${state.code ? `#kod=${state.code}` : ""}`;
  return (
    <main className="lok-sida lok-kom" id="innehall">
      <section className="lok-traffkort" aria-label={text.clockLabel}>
        <div>
          <b>{state.meetName ?? text.noMeet}</b>
          <span>{text.connected}</span>
        </div>
        <div className="lok-traffklocka">
          <span className="tm-mono">{clockText(now, false)}</span>
          <ClockPill mode={lok.clock.mode()} speed={lok.clock.speed()} text={text} />
        </div>
      </section>
      {state.sessionLost && <p className="lok-upplysning">{text.sessionLost}</p>}
      <form
        className="lok-formular"
        onSubmit={(event) => {
          event.preventDefault();
          if (name.trim()) void lok.join(name, level, language, code || null);
        }}
      >
        <h1>{text.whatsYourName}</h1>
        <label className="lok-falt">
          <span>{text.name}</span>
          <input value={name} onChange={(event) => setName(event.target.value)} maxLength={40} autoComplete="given-name" required />
        </label>
        <fieldset className="lok-val">
          <legend>{text.language}</legend>
          {(["sv", "en"] as Language[]).map((choice) => (
            <button key={choice} type="button" className="lok-chip" aria-pressed={language === choice} onClick={() => setLanguage(choice)}>
              {TEXT[choice].languages[choice]}
            </button>
          ))}
        </fieldset>
        <fieldset className="lok-val lok-nivaer">
          <legend>{text.howUsed}</legend>
          {LEVELS.map((choice) => (
            <button key={choice} type="button" className="lok-chip" aria-pressed={level === choice} onClick={() => setLevel(choice)}>
              {text.levels[choice]}
            </button>
          ))}
        </fieldset>
        {state.needsCode && (
          <label className="lok-falt">
            <span>{text.code}</span>
            <input value={code} onChange={(event) => setCode(event.target.value)} inputMode="numeric" pattern="[0-9 ]{6,7}" autoComplete="one-time-code" />
            <small>{text.codeNote}</small>
          </label>
        )}
        <Problem text={state.problem} />
        <button type="submit" className="lok-knapp primar stor" disabled={state.busy || !name.trim()}>
          {text.start}
        </button>
        {loginWithId && (
          <a className="lok-knapp stor" href={idLoginAddress(next, language)}>
            {text.idLogin}
          </a>
        )}
        {state.hub?.person && <p className="lok-not">{text.idLoggedIn(state.hub.person)}</p>}
        <p className="lok-not">{text.joinNote}</p>
      </form>
    </main>
  );
}

export function IngenTraff({ lok, state }: { lok: Lok; state: LokState }) {
  const text = TEXT[state.language];
  return (
    <main className="lok-sida lok-kom" id="innehall">
      <section className="lok-kort">
        <h1>{text.noMeet}</h1>
        <p>{text.noMeetNote}</p>
        <button type="button" className="lok-knapp primar" onClick={() => void lok.start()}>
          {text.tryAgain}
        </button>
      </section>
    </main>
  );
}
