import { useState } from "react";
import type { Automation, AutomationSettings, DaySettings, Now, Version } from "./api";
import { DISTURBANCES, LOST, WHERE, dayName } from "./drift";
import { Built } from "./StartPage";
import { Chip, Chips } from "./ui";

// Inställningar (TRAFIK-30, TRAFIK-31, H48, H50): reached with the gear in the header. Inside
// a meet it shows the three heaps: I paketet (follows the version), Under träffen (the meet's
// own settings) and Den här hubben (only the machine). Outside a meet only Den här hubben. Only
// what the hub can do today is here; the rest comes with its step.

export type SettingsProps = {
  admin: boolean;
  now: Now | null;
  hubName: string;
  version: Version | null;
  automation: Automation | null;
  /** Changes when Automatiken's settings were saved, so that the form starts over from them. */
  automationSaved: number;
  onAutomation?: (settings: AutomationSettings) => void;
  onDay?: (settings: DaySettings) => void;
};

type Heap = { label: string; note: string; items: [string, string][] };

export function heaps(now: Now | null): Heap[] {
  const machine: Heap = { label: "Den här hubben", note: "bara maskinen", items: [["hubben", "Namn och version"]] };
  if (!now) return [machine];
  return [
    { label: "I paketet", note: "följer versionen", items: [["traffen", "Träffen och trafikdagarna"]] },
    {
      label: "Under träffen",
      note: "gäller medan den körs",
      items: [
        ["automatik", "Automatik"],
        ["dygnsskifte", "Dygnsskifte"],
      ],
    },
    machine,
  ];
}

export function SettingsPage(props: SettingsProps) {
  const { now, hubName, version } = props;
  return (
    <>
      <div className="sidrubrik">
        <h1>Inställningar</h1>
        <p className="liten">{now ? `${now.name} · tre högar · nås med kugghjulet i sidhuvudet` : "Den här hubben · ingen träff körs"}</p>
      </div>
      <div className="installningar">
        <nav className="kort hogar" aria-label="Inställningar">
          {heaps(now).map((heap) => (
            <div key={heap.label} className="hog">
              <p className="hogrubrik">
                {heap.label}
                <span>{heap.note}</span>
              </p>
              <ul>
                {heap.items.map(([id, label]) => (
                  <li key={id}>
                    <a href={`#${id}`}>{label}</a>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </nav>
        <div className="kortlista">
          {now && <Meet now={now} />}
          {now && <Automatik {...props} now={now} />}
          {now && <Dygnsskifte {...props} now={now} />}
          <section id="hubben" className="kort" aria-labelledby="hubben-rubrik">
            <h2 id="hubben-rubrik">Namn och version</h2>
            <p className="liten">Gäller den här hubben och alla träffar på den.</p>
            <dl className="bygge">
              <dt>Namn</dt>
              <dd>{hubName}</dd>
            </dl>
            {version && <Built version={version} />}
            <p className="liten">Pi:ns nät, PIN och skärmlås, språk och AI kommer hit med Synk i steg 5.</p>
          </section>
        </div>
      </div>
    </>
  );
}

/** I paketet: what the version says, read here and changed in Planering. */
function Meet({ now }: { now: Now }) {
  const planned = now.meet_id !== "provbanan";
  return (
    <section id="traffen" className="kort" aria-labelledby="traffen-rubrik">
      <h2 id="traffen-rubrik">Träffen och trafikdagarna</h2>
      <p className="liten">Står i paketet och följer versionen.</p>
      <dl className="bygge">
        <dt>Träff</dt>
        <dd>{now.name}</dd>
        <dt>Version</dt>
        <dd>{planned ? now.version : "Provbanan, för prov"}</dd>
        <dt>Trafikdag</dt>
        <dd>{dayName(now.traffic_day)}</dd>
        <dt>Speldygn</dt>
        <dd>{`dag ${now.game_day}`}</dd>
      </dl>
      <p className="liten">
        {planned ? (
          <>
            Ändras i Planering: publicera en ny version under <a href={`/planering/${encodeURIComponent(now.meet_id)}/versioner`}>Versioner</a> och byt träff.
          </>
        ) : (
          "Provbanan är densamma på alla hubbar."
        )}
      </p>
    </section>
  );
}

const sameSettings = (a: AutomationSettings, b: AutomationSettings) => (Object.keys(a) as (keyof AutomationSettings)[]).every((key) => a[key] === b[key]);

/** A new scenario key: the same key gives the same disturbances (F15). */
export function newSeed(random: () => number = Math.random): string {
  const letters = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
  const part = () => Array.from({ length: 4 }, () => letters[Math.floor(random() * letters.length)]).join("");
  return `${part()}-${part()}`;
}

/** Under träffen: Automatiken (F14, F15, H42), changed as a whole and saved with Spara. */
function Automatik({ admin, now, automation, automationSaved, onAutomation }: SettingsProps & { now: Now }) {
  const saved = automation?.settings ?? null;
  const [draft, setDraft] = useState<AutomationSettings | null>(saved);
  const [filledAt, setFilledAt] = useState(automationSaved);
  // The form starts from what the hub has: when it first comes, and after each save.
  if (saved && (!draft || filledAt !== automationSaved)) {
    setDraft(saved);
    setFilledAt(automationSaved);
  }
  if (!admin) {
    return (
      <section id="automatik" className="kort" aria-labelledby="automatik-rubrik">
        <h2 id="automatik-rubrik">Automatik</h2>
        <p className="liten">Logga in med hubbens PIN-kod för att se och ändra automatiken.</p>
      </section>
    );
  }
  if (!saved || !draft) {
    return (
      <section id="automatik" className="kort" aria-labelledby="automatik-rubrik">
        <h2 id="automatik-rubrik">Automatik</h2>
        <p className="liten">Läser automatiken …</p>
      </section>
    );
  }
  const change = (part: Partial<AutomationSettings>) => setDraft({ ...draft, ...part });
  const changed = !sameSettings(draft, saved);
  return (
    <section id="automatik" className="kort" aria-labelledby="automatik-rubrik">
      <h2 id="automatik-rubrik">Automatik</h2>
      <p className="liten">{`Gäller ${now.name} medan den körs. En driftplats som ingen box eller TKL arbetar med sköts av automatiken.`}</p>
      <div className="installning">
        <span className="etikett">Automatiken</span>
        <Chips label="Automatiken">
          <Chip label="På" pressed={draft.enabled} onClick={() => change({ enabled: true })} />
          <Chip label="Av" pressed={!draft.enabled} onClick={() => change({ enabled: false })} />
        </Chips>
      </div>
      <div className="installning">
        <label htmlFor="set-lost" className="etikett">
          Tar över en driftplats
        </label>
        <select id="set-lost" value={draft.lost_contact_minutes} onChange={(event) => change({ lost_contact_minutes: Number(event.target.value) as AutomationSettings["lost_contact_minutes"] })}>
          {LOST.map(([minutes, label]) => (
            <option key={minutes} value={minutes}>
              {minutes ? `efter ${label}` : label}
            </option>
          ))}
        </select>
        <span className="liten">efter Kontakt saknas</span>
      </div>
      <div className="installning">
        <label htmlFor="set-answer" className="etikett">
          Klartecken efter
        </label>
        <span>
          <input id="set-answer" type="number" min={0} max={30} className="tal" value={draft.answer_seconds} onChange={(event) => change({ answer_seconds: Number(event.target.value) })} /> s
        </span>
      </div>
      <div className="installning">
        <label htmlFor="set-late" className="etikett">
          Försenat tåg står
        </label>
        <span>
          <input id="set-late" type="number" min={1} max={10} className="tal" value={draft.late_stop_minutes} onChange={(event) => change({ late_stop_minutes: Number(event.target.value) })} /> min
        </span>
      </div>
      <div className="installning">
        <span className="etikett">Undanställning</span>
        <span className="rad">
          <label>
            <input id="set-stabling" type="checkbox" checked={draft.stabling} onChange={(event) => change({ stabling: event.target.checked })} /> efter
          </label>
          <input id="set-stabling-minutes" type="number" min={1} max={60} className="tal" aria-label="Undanställning efter minuter" value={draft.stabling_minutes} onChange={(event) => change({ stabling_minutes: Number(event.target.value) })} /> min
        </span>
        <span className="liten">tåg som slutar ställs undan och släpper spåret</span>
      </div>
      <div className="installning">
        <span className="etikett">Störningar</span>
        <Chips label="Störningar">
          {Object.entries(DISTURBANCES).map(([key, label]) => (
            <Chip key={key} label={label} pressed={draft.disturbance === key} onClick={() => change({ disturbance: key as AutomationSettings["disturbance"] })} />
          ))}
        </Chips>
      </div>
      <div className="installning">
        <span className="etikett">Störningsplats</span>
        <Chips label="Störningsplats">
          {Object.entries(WHERE).map(([key, label]) => (
            <Chip key={key} label={label} pressed={draft.where === key} onClick={() => change({ where: key as AutomationSettings["where"] })} />
          ))}
        </Chips>
      </div>
      <div className="installning">
        <label htmlFor="set-seed" className="etikett">
          Scenarionyckel
        </label>
        <span className="rad">
          <input id="set-seed" maxLength={40} className="tm-mono" value={draft.seed} onChange={(event) => change({ seed: event.target.value })} />
          <button type="button" onClick={() => change({ seed: newSeed() })}>
            Ny nyckel
          </button>
        </span>
        <span className="liten">samma nyckel ger samma störningar</span>
      </div>
      <div className="installningsfot">
        <span id="settings-state" className="liten" role="status">
          {changed ? "Ändrat, inte sparat" : "Inget ändrat"}
        </span>
        <span className="rad">
          <button type="button" disabled={!changed} onClick={() => setDraft(saved)}>
            Avbryt
          </button>
          <button id="settings-save" type="button" className="primar" disabled={!changed} onClick={() => onAutomation?.({ ...draft, seed: draft.seed.trim() })}>
            Spara
          </button>
        </span>
      </div>
      <p className="liten">Ändrar aldrig versionen. Undanställningen räknas i spelminuter.</p>
    </section>
  );
}

/** Under träffen: Dygnsskiftet (F7), by hand by default or automatic, and its time: empty is an
 * hour before the new day's first train, never before midnight. Saved with Spara. */
function Dygnsskifte({ admin, now, onDay }: SettingsProps & { now: Now }) {
  const day = now.day;
  const saved = { mode: day?.mode ?? "manual", time: day?.fixed ? day.time : "" };
  const key = `${saved.mode}|${saved.time}`;
  const [draft, setDraft] = useState(saved);
  const [filledFrom, setFilledFrom] = useState(key);
  // The form starts from what the hub has, and again when that changes.
  if (filledFrom !== key) {
    setDraft(saved);
    setFilledFrom(key);
  }
  if (!admin || !day) {
    return (
      <section id="dygnsskifte" className="kort" aria-labelledby="dygnsskifte-rubrik">
        <h2 id="dygnsskifte-rubrik">Dygnsskifte</h2>
        <p className="liten">Logga in med hubbens PIN-kod för att se och ändra dygnsskiftet.</p>
      </section>
    );
  }
  const changed = draft.mode !== saved.mode || draft.time !== saved.time;
  return (
    <section id="dygnsskifte" className="kort" aria-labelledby="dygnsskifte-rubrik">
      <h2 id="dygnsskifte-rubrik">Dygnsskifte</h2>
      <p className="liten">När nästa speldygn börjar. Natten hör till dygnet före fram till skiftet.</p>
      <div className="installning">
        <span className="etikett">Ny dag</span>
        <Chips label="Ny dag">
          <Chip label="Manuellt" pressed={draft.mode === "manual"} onClick={() => setDraft({ ...draft, mode: "manual" })} />
          <Chip label="Automatiskt" pressed={draft.mode === "automatic"} onClick={() => setDraft({ ...draft, mode: "automatic" })} />
        </Chips>
        <span className="liten">{draft.mode === "manual" ? "Trafikledningen trycker Starta ny dag i Nu" : "startar av sig själv, och väntar högst 30 minuter på tåg som är ute"}</span>
      </div>
      <div className="installning">
        <label htmlFor="set-day-time" className="etikett">
          Tid
        </label>
        <input id="set-day-time" type="time" step={60} value={draft.time} onChange={(event) => setDraft({ ...draft, time: event.target.value })} />
        <span className="liten">tomt: en timme före första tåget, aldrig före midnatt</span>
      </div>
      <div className="installningsfot">
        <span id="day-settings-state" className="liten" role="status">
          {changed ? "Ändrat, inte sparat" : "Inget ändrat"}
        </span>
        <span className="rad">
          <button type="button" disabled={!changed} onClick={() => setDraft(saved)}>
            Avbryt
          </button>
          <button id="day-save" type="button" className="primar" disabled={!changed} onClick={() => onDay?.({ mode: draft.mode, time: draft.time || null })}>
            Spara
          </button>
        </span>
      </div>
    </section>
  );
}
