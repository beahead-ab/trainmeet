import { useState } from "react";
import { idLoginAddress, LEVELS, trainsOf, type DriverState, type Instructions, type Level } from "./api";
import { shrinkPhoto } from "./photo";
import type { Lok, LokState, Theme } from "./store";
import { TEXT, type Language, type Text } from "./text";
import { Avatar, Icon, PageHead, Problem } from "./ui";

// Jag (LOK-27, LOK-32, LOK-34, LOK-41; jag.jpg, instruktioner.jpg): the name and the photo icon,
// the service, Paus or Inväntar start, the reminders, the level, the language and the theme, the
// general instructions, and leaving the meet. A driver without an account stays on the phone as
// long as the meet runs (LOK-41).

export function JagTab({ lok, state }: { lok: Lok; state: LokState }) {
  const text = TEXT[state.language];
  const me = state.me;
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(me?.driver.name ?? "");
  const [photoProblem, setPhotoProblem] = useState<string | null>(null);
  const [leaving, setLeaving] = useState(false);
  if (!me) return null;
  const driver = me.driver;
  const service = me.service;
  const trains = service?.service.kind === "train";
  const paper = lok.paperOf(service);
  const choose = async (files: FileList | null) => {
    const file = files?.[0];
    if (!file) return;
    setPhotoProblem(null);
    try {
      await lok.photo(await shrinkPhoto(file));
    } catch {
      setPhotoProblem(text.photoBad);
    }
  };
  const states: [DriverState | null, string][] = [
    [null, text.stateNone],
    ["pause", text.states.pause],
    ["waiting_start", text.states.waiting_start],
  ];
  return (
    <main className="lok-sida" id="innehall">
      <PageHead title={text.meTitle} sub={state.meetName ?? ""} />
      <Problem text={state.problem ?? photoProblem} />
      <section className="lok-kort lok-jag">
        <div className="lok-jag-rad">
          <Avatar driver={driver} size="stor" />
          <span>
            <b>{driver.name ?? text.driver}</b>
            <span>{driver.linked ? text.linked : text.guest}</span>
          </span>
          <label className="lok-lank">
            {driver.photo ? text.changePhoto : text.addPhoto}
            <input className="lok-dold" type="file" accept="image/*" onChange={(event) => void choose(event.target.files)} />
          </label>
        </div>
        {driver.photo && (
          <button type="button" className="lok-lank" onClick={() => void lok.removePhoto()}>
            {text.removePhoto}
          </button>
        )}
        <p className="lok-not">{text.photoNote}</p>
        {!driver.linked && state.hub?.id_login && (
          <a className="lok-knapp mjuk" href={idLoginAddress("/lokforaren/jag", state.language)}>
            {text.linkId}
          </a>
        )}
        {editing ? (
          <form
            className="lok-namnrad"
            onSubmit={(event) => {
              event.preventDefault();
              if (!name.trim()) return;
              void lok.profile({ name: name.trim() }).then((done) => done && setEditing(false));
            }}
          >
            <label className="lok-falt">
              <span>{text.name}</span>
              <input value={name} onChange={(event) => setName(event.target.value)} maxLength={40} required />
            </label>
            <button type="submit" className="lok-knapp primar" disabled={state.busy}>
              {text.save}
            </button>
          </form>
        ) : (
          <button type="button" className="lok-lank" onClick={() => setEditing(true)}>
            {text.changeName}
          </button>
        )}
      </section>

      {service && (
        <>
          <h2 className="lok-avsnitt">{trains ? text.train : text.service}</h2>
          <section className="lok-kort">
            <p>
              {[trains ? text.trainNumber(service.number) : text.serviceNumber(service.number), !trains && trainsOf(service).length ? text.trains(trainsOf(service).join(", ")) : null, paper && paper !== service.number ? text.onPaper(paper) : null, service.paper ? text.afterPaper.toLowerCase() : null].filter(Boolean).join(" · ")}
            </p>
            <div className="lok-knappar">
              <button type="button" className="lok-knapp" onClick={() => lok.navigate("tag")}>
                {text.change}
              </button>
              <button type="button" className="lok-knapp" onClick={() => lok.open("release")}>
                {text.release}
              </button>
            </div>
          </section>
        </>
      )}

      <h2 className="lok-avsnitt">{text.myState}</h2>
      <section className="lok-kort lok-val" role="radiogroup" aria-label={text.myState}>
        {states.map(([value, label]) => (
          <button
            key={value ?? "inget"}
            type="button"
            role="radio"
            className="lok-chip"
            aria-checked={(driver.state ?? null) === value}
            disabled={state.busy}
            onClick={() => void lok.profile(value ? { state: value } : { clear_state: true })}
          >
            {label}
          </button>
        ))}
      </section>

      <h2 className="lok-avsnitt">{text.reminders}</h2>
      <section className="lok-kort">
        <label className="lok-vaxel">
          <span>{text.remindersNote}</span>
          <input type="checkbox" role="switch" checked={state.remindersOn} onChange={(event) => lok.setReminders(event.target.checked)} />
        </label>
        {state.remindersOn && !lok.notificationsAllowed() && !lok.notificationsAskable() && <p className="lok-not">{text.notificationsBlocked}</p>}
      </section>

      <h2 className="lok-avsnitt">{text.display}</h2>
      <section className="lok-kort lok-installningar">
        <label className="lok-installning">
          <span>{text.myLevel}</span>
          <select value={driver.level} disabled={state.busy} onChange={(event) => void lok.profile({ level: event.target.value as Level })}>
            {LEVELS.map((level) => (
              <option key={level} value={level}>
                {text.levels[level]}
              </option>
            ))}
          </select>
        </label>
        <label className="lok-installning">
          <span>{text.language}</span>
          <select value={state.language} onChange={(event) => lok.setLanguage(event.target.value as Language)}>
            {(["sv", "en"] as Language[]).map((language) => (
              <option key={language} value={language}>
                {TEXT[language].languages[language]}
              </option>
            ))}
          </select>
        </label>
        <label className="lok-installning">
          <span>{text.theme}</span>
          <select value={state.theme} onChange={(event) => lok.setTheme(event.target.value as Theme)}>
            {(["morkt", "ljust", "auto"] as Theme[]).map((theme) => (
              <option key={theme} value={theme}>
                {text.themes[theme]}
              </option>
            ))}
          </select>
        </label>
      </section>

      <ul className="lok-lankar">
        <li>
          <button type="button" onClick={() => lok.navigate("instruktioner")}>
            <span>{text.instructionsTitle}</span>
            {Icon.chevron}
          </button>
        </li>
      </ul>

      <section className="lok-kort lok-lamna">
        {leaving ? (
          <>
            <p>{text.leaveNote}</p>
            <div className="lok-knappar">
              <button type="button" className="lok-knapp fara" disabled={state.busy} onClick={() => void lok.leave()}>
                {text.leaveConfirm}
              </button>
              <button type="button" className="lok-knapp" onClick={() => setLeaving(false)}>
                {text.cancel}
              </button>
            </div>
          </>
        ) : (
          <button type="button" className="lok-knapp fara" onClick={() => setLeaving(true)}>
            {text.leave}
          </button>
        )}
      </section>
    </main>
  );
}

/** The text in parts: a short first line of a part is its heading (instruktioner.jpg). */
export function partsOf(text: string): { heading: string | null; body: string }[] {
  return text
    .split(/\n\s*\n/)
    .map((part) => part.trim())
    .filter(Boolean)
    .map((part) => {
      const [first, ...rest] = part.split("\n");
      const heading = rest.length && first && first.length <= 40 && !/[.!?:]$/.test(first.trim()) ? first.trim() : null;
      return { heading, body: heading ? rest.join("\n").trim() : part };
    });
}

/** De allmänna instruktionerna (LOK-34): the text in the driver's language, or the other, and
 * the organiser's PDF. Lokföraren shows what there is. */
export function Instruktioner({ lok, state, instructions }: { lok: Lok; state: LokState; instructions: Instructions | null }) {
  const text: Text = TEXT[state.language];
  const said = instructions ? (instructions.text?.[state.language] ?? Object.values(instructions.text ?? {})[0] ?? null) : null;
  return (
    <main className="lok-sida" id="innehall">
      <PageHead title={text.instructionsTitle} sub={state.meetName ?? ""} back onBack={() => lok.navigate(state.me?.service ? "korplan" : "jag")} backLabel={text.back} />
      <p className="lok-not">{text.instructionsNote}</p>
      {said ? (
        <section className="lok-kort lok-instruktioner">
          {partsOf(said).map((part, index) => (
            <div key={index}>
              {part.heading && <h2>{part.heading}</h2>}
              <p>{part.body}</p>
            </div>
          ))}
        </section>
      ) : (
        instructions && !instructions.pdf && <p className="lok-upplysning">{text.noInstructions}</p>
      )}
      <ul className="lok-lankar">
        {instructions?.pdf && (
          <li>
            <a href={instructions.pdf} target="_blank" rel="noopener">
              {Icon.paper}
              <span>
                {text.pdf}
                {instructions.filename ? ` · ${instructions.filename}` : ""}
              </span>
              {Icon.chevron}
            </a>
          </li>
        )}
        {state.me?.service && (
          <li>
            <button type="button" onClick={() => lok.open("messages")}>
              {Icon.message}
              <span>{text.sayToDispatch}</span>
              {Icon.chevron}
            </button>
          </li>
        )}
      </ul>
      {state.me?.service && (
        <button type="button" className="lok-knapp stor" onClick={() => lok.navigate("korplan")}>
          {text.backToService}
        </button>
      )}
    </main>
  );
}
