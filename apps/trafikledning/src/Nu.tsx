import { useEffect, useState } from "react";
import type { Automation, AutomationSettings, ChangePlace, Client, ClockControl, Leg, Now, Weekday } from "./api";
import { CASES, DISTURBANCES, LOST, ORDINARY, SPEEDS, STATES, WEEKDAYS, WHERE, dayName, modeText, placeCode, placeName, type MeetChoice } from "./drift";
import { Chip, Chips } from "./ui";

// Nu (S6, TRAFIK-01): the meet, its clock, the open clearances and the trains. Everyone sees
// it (S1); logged in, one also gets the clock's buttons and Automatiken (F14).

export type NuProps = {
  admin: boolean;
  now: Now | null;
  clients: Client[];
  choices: MeetChoice[];
  asked: string | null;
  automation: Automation | null;
  /** Changes when Automatiken's settings were saved, so that its fields are filled again. */
  automationSaved: number;
  openAutomation?: boolean;
  onClock?: (control: ClockControl) => void;
  onStart?: (choice: MeetChoice, day: Weekday) => void;
  onAutomation?: (settings: AutomationSettings) => void;
  onPlace?: (change: ChangePlace) => void;
};

export function NuPage(props: NuProps) {
  const { now } = props;
  return now ? <Meet {...props} now={now} /> : <NoMeet {...props} />;
}

function NoMeet({ admin, choices, asked, onStart }: NuProps) {
  const [choice, setChoice] = useState(asked ?? choices[0]?.value ?? "provbanan:1");
  const [day, setDay] = useState<Weekday>("mon");
  // The choices come after the page: pick the one asked for, or the first, when they do.
  useEffect(() => {
    if (!choices.some((option) => option.value === choice)) setChoice(asked ?? choices[0]?.value ?? "provbanan:1");
  }, [choices, asked, choice]);
  return (
    <section id="no-meet" className="kort">
      <h1>Ingen träff är startad</h1>
      <p className="ingress">
        Hubben kör en träff åt gången: Provbanan, eller en version av en träff som publicerats i <a href="/planering">Planering</a>.
      </p>
      {admin ? (
        <div className="rad">
          <label>
            Träff{" "}
            <select id="first-choice" value={choice} onChange={(event) => setChoice(event.target.value)}>
              {choices.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.meet === "provbanan" ? option.name : `${option.name} · ${option.note}`}
                </option>
              ))}
            </select>
          </label>
          <label>
            Trafikdag{" "}
            <select id="first-day" value={day} onChange={(event) => setDay(event.target.value as Weekday)}>
              {WEEKDAYS.map(([key, name]) => (
                <option key={key} value={key}>
                  {name}
                </option>
              ))}
            </select>
          </label>
          <button
            id="start-meet"
            type="button"
            className="primar"
            onClick={() => {
              const picked = choices.find((option) => option.value === choice);
              if (picked) onStart?.(picked, day);
            }}
          >
            Starta träffen
          </button>
        </div>
      ) : (
        <p className="liten">Logga in för att starta en träff.</p>
      )}
    </section>
  );
}

function Meet(props: NuProps & { now: Now }) {
  const { admin, now, onClock } = props;
  const [filter, setFilter] = useState<Leg["state"] | "all">("all");
  const counts: Record<string, number> = {};
  for (const leg of now.legs) counts[leg.state] = (counts[leg.state] ?? 0) + 1;
  const legs = now.legs.filter((leg) => filter === "all" || leg.state === filter);
  return (
    <section id="meet">
      <div className="sidrubrik">
        <h1 id="title">{now.name}</h1>
        <p id="subtitle" className="liten">
          {`Trafikdag ${dayName(now.traffic_day)} · dag ${now.game_day} · `}
          {now.clock.running ? `klockan går i ${now.clock.speed}×` : "klockan står still"}
        </p>
      </div>
      {admin && (
        <div className="rad" id="clock-controls">
          <button id="clock-toggle" type="button" className="primar" onClick={() => onClock?.({ action: now.clock.running ? "stop" : "start", speed: null, time: null, game_day: null })}>
            {now.clock.running ? "Stoppa klockan" : "Starta klockan"}
          </button>
          <Chips label="Hastighet">
            {SPEEDS.map((speed) => (
              <Chip key={speed} label={`${speed}×`} pressed={now.clock.speed === speed} onClick={() => onClock?.({ action: "speed", speed, time: null, game_day: null })} />
            ))}
          </Chips>
        </div>
      )}
      {admin && props.automation && <Automatiken {...props} automation={props.automation} />}
      <h2>
        Öppna klareringar{" "}
        <span id="case-count" className="antal">
          {now.clearances.length}
        </span>
      </h2>
      <ul id="cases" className="lista">
        {now.clearances.length ? (
          now.clearances.map((clearance) => (
            <li key={clearance.clearance_id}>
              <div className="vem">
                <b>{`${clearance.train_number} · ${placeCode(now, clearance.from_place)} → ${placeCode(now, clearance.to_place)}`}</b>
                <span className="liten">{`${clearance.departed ? "På väg" : (CASES[clearance.status] ?? clearance.status)} · begärd ${clearance.requested_at}`}</span>
              </div>
            </li>
          ))
        ) : (
          <li className="tom">Inga öppna klareringar.</li>
        )}
      </ul>
      <h2>Tågen</h2>
      <Chips label="Visa">
        <Chip label="Alla" pressed={filter === "all"} onClick={() => setFilter("all")} count={now.legs.length} />
        {(Object.entries(STATES) as [Leg["state"], string][]).map(([state, label]) => (
          <Chip key={state} label={label} pressed={filter === state} onClick={() => setFilter(state)} count={counts[state] ?? 0} />
        ))}
      </Chips>
      <div className="ram">
        <table className="tabell">
          <thead>
            <tr>
              <th>Tåg</th>
              <th>Sträcka</th>
              <th>Avgång</th>
              <th>Ankomst</th>
              <th>Läge</th>
              <th>Spår</th>
            </tr>
          </thead>
          <tbody id="legs">
            {legs.map((leg) => (
              <tr key={leg.leg} className={leg.state === "arrived" ? "klar" : undefined}>
                <td className="tag">{leg.train_number}</td>
                <td>{`${placeName(now, leg.from_place)} → ${placeName(now, leg.to_place)}`}</td>
                <td>{leg.departure ?? "–"}</td>
                <td>{leg.arrival ?? "–"}</td>
                <td>
                  <span className={`pill ${leg.state}`}>{STATES[leg.state]}</span>
                </td>
                <td>{leg.track ?? "–"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

type Fields = Pick<AutomationSettings, "answer_seconds" | "late_stop_minutes" | "stabling" | "stabling_minutes" | "seed">;

const fieldsOf = (settings: AutomationSettings): Fields => ({
  answer_seconds: settings.answer_seconds,
  late_stop_minutes: settings.late_stop_minutes,
  stabling: settings.stabling,
  stabling_minutes: settings.stabling_minutes,
  seed: settings.seed,
});

/** Automatiken (F14): who works each place, leave and take back, and its settings (H42). */
function Automatiken({ now, clients, automation, automationSaved, openAutomation, onAutomation, onPlace }: NuProps & { now: Now; automation: Automation }) {
  const settings = automation.settings;
  // The fields are filled when the card is drawn first or saved, not while someone types.
  const [fields, setFields] = useState<Fields>(() => fieldsOf(settings));
  const [filledAt, setFilledAt] = useState(automationSaved);
  if (filledAt !== automationSaved) {
    setFilledAt(automationSaved);
    setFields(fieldsOf(settings));
  }
  const counts: Record<string, number> = { manned: 0, no_contact: 0, automatic: 0 };
  const places = automation.places ?? [];
  for (const place of places) counts[place.mode] = (counts[place.mode] ?? 0) + 1;
  const clientName = (id: string) => clients.find((client) => client.client_id === id)?.name ?? id;
  const save = (change: Partial<AutomationSettings>) => onAutomation?.({ ...settings, ...change });
  const trains = (automation.trains ?? []).filter((train) => !ORDINARY.has(train.reason));
  const summary = settings.enabled
    ? ` · ${counts["automatic"]} automatiska, ${counts["manned"]} bemannade` + (counts["no_contact"] ? `, ${counts["no_contact"]} utan kontakt` : "")
    : " · avstängd";
  return (
    <details id="automatiken" className="kort" open={openAutomation}>
      <summary>
        <h2 className="sammanfattning">
          Automatiken{" "}
          <span id="auto-summary" className="liten">
            {summary}
          </span>
        </h2>
      </summary>
      <p className="liten">
        En driftplats som ingen box eller TKL arbetar med sköts av automatiken: den ger klart när spåret är ledigt, skickar sina tåg och tar emot dem. Den första box eller TKL som arbetar med platsen gör den bemannad.
      </p>
      <div className="ram">
        <table className="tabell">
          <thead>
            <tr>
              <th>Driftplats</th>
              <th>Läge</th>
              <th>
                <span className="osynlig">Åtgärd</span>
              </th>
            </tr>
          </thead>
          <tbody id="auto-places">
            {places.map((place) => (
              <tr key={place.place}>
                <td>{`${place.name} (${place.code})`}</td>
                <td>
                  <span className={`pill ${place.mode}`}>{modeText(place, clientName)}</span>
                </td>
                <td>
                  {place.mode !== "automatic" ? (
                    <button type="button" onClick={() => onPlace?.({ place: place.place, action: "leave", client_id: null })}>
                      Lämna till automatiken
                    </button>
                  ) : place.present?.[0] ? (
                    <button type="button" onClick={() => onPlace?.({ place: place.place, action: "take_back", client_id: place.present?.[0] ?? null })}>
                      {`Ge till ${clientName(place.present[0])}`}
                    </button>
                  ) : (
                    <span className="liten">Ingen box eller TKL ansluten</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <h3>
        Automatiken väntar med{" "}
        <span id="auto-count" className="antal">
          {trains.length}
        </span>
      </h3>
      <ul id="auto-trains" className="lista">
        {trains.length ? (
          trains.slice(0, 12).map((train) => (
            <li key={train.call}>
              <div className="vem">
                <b>{`${train.train} · ${placeCode(now, train.from_place)} → ${placeCode(now, train.to_place)}`}</b>
                <span className="liten">{train.reason}</span>
              </div>
            </li>
          ))
        ) : (
          <li className="tom">{settings.enabled ? "Inga tåg väntar." : "Automatiken är avstängd."}</li>
        )}
      </ul>
      <h3>Inställningar</h3>
      <div className="rad">
        <span className="etikett">Automatiken</span>
        <Chips label="Automatiken">
          <Chip label="På" pressed={settings.enabled} onClick={() => save({ enabled: true })} />
          <Chip label="Av" pressed={!settings.enabled} onClick={() => save({ enabled: false })} />
        </Chips>
      </div>
      <div className="rad">
        <span className="etikett">Tar över efter Kontakt saknas</span>
        <Chips label="Tar över efter Kontakt saknas">
          {LOST.map(([minutes, label]) => (
            <Chip key={minutes} label={label} pressed={settings.lost_contact_minutes === minutes} onClick={() => save({ lost_contact_minutes: minutes })} />
          ))}
        </Chips>
      </div>
      <div className="rad">
        <span className="etikett">Störningar</span>
        <Chips label="Störningar">
          {Object.entries(DISTURBANCES).map(([key, label]) => (
            <Chip key={key} label={label} pressed={settings.disturbance === key} onClick={() => save({ disturbance: key as AutomationSettings["disturbance"] })} />
          ))}
        </Chips>
        <Chips label="Var">
          {Object.entries(WHERE).map(([key, label]) => (
            <Chip key={key} label={label} pressed={settings.where === key} onClick={() => save({ where: key as AutomationSettings["where"] })} />
          ))}
        </Chips>
      </div>
      <div className="rad">
        <label>
          Klartecken efter <input id="auto-answer" type="number" min={0} max={30} className="tal" value={fields.answer_seconds} onChange={(event) => setFields({ ...fields, answer_seconds: Number(event.target.value) })} /> s
        </label>
        <label>
          Försenat tåg står <input id="auto-late" type="number" min={1} max={10} className="tal" value={fields.late_stop_minutes} onChange={(event) => setFields({ ...fields, late_stop_minutes: Number(event.target.value) })} /> min
        </label>
        <label>
          <input id="auto-stabling" type="checkbox" checked={fields.stabling} onChange={(event) => setFields({ ...fields, stabling: event.target.checked })} /> Undanställning efter{" "}
          <input id="auto-stabling-minutes" type="number" min={1} max={60} className="tal" aria-label="Undanställning efter minuter" value={fields.stabling_minutes} onChange={(event) => setFields({ ...fields, stabling_minutes: Number(event.target.value) })} /> min
        </label>
        <label>
          Scenarionyckel <input id="auto-seed" maxLength={40} value={fields.seed} onChange={(event) => setFields({ ...fields, seed: event.target.value })} />
        </label>
        <button id="auto-save" type="button" onClick={() => save({ ...fields, seed: fields.seed.trim() })}>
          Spara
        </button>
      </div>
    </details>
  );
}

