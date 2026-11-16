import { useEffect, useState } from "react";
import type { Automation, ChangePlace, Client, ClockControl, Leg, Now, Weekday } from "./api";
import type { MeetChoice } from "@trainmeet/hubben";
import { CASES, ORDINARY, SPEEDS, STATES, WEEKDAYS, clockAt, dayName, jumpNote, jumpText, minuteOf, modeText, placeCode, placeName } from "./drift";
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
  openAutomation?: boolean;
  onClock?: (control: ClockControl) => void;
  onStart?: (choice: MeetChoice, day: Weekday) => void;
  onPlace?: (change: ChangePlace) => void;
};

export function NuPage(props: NuProps) {
  const { now } = props;
  return now ? <Meet {...props} now={now} /> : <NoMeet {...props} />;
}

/** An unanswered request is reminded of every third minute (H39, DRIFT-33). */
export const reminded = (count: number | undefined) => (count ? ` · påmind ${count === 1 ? "en gång" : `${count} gånger`}` : "");

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

/** Tidshopp (TRAFIK-01, H37): the slider picks a minute of the game day, and Hoppa closes the
 * open clearances and places the trains by the timetable. Every jump can be undone (F6), so it
 * is made at once and Ångra is offered after it. */
function Tidshopp({ now, onClock }: { now: Now; onClock?: (control: ClockControl) => void }) {
  const [minute, setMinute] = useState(() => Math.floor(now.clock.seconds / 60) % 1440);
  const time = clockAt(minute);
  const last = now.jump;
  return (
    <section id="time-jump" aria-labelledby="time-jump-title">
      <h2 id="time-jump-title">Tidshopp</h2>
      <div className="rad">
        <label className="slider">
          Tid
          <input id="jump-slider" type="range" min={0} max={1439} step={1} value={minute} aria-valuetext={time} onChange={(event) => setMinute(Number(event.target.value))} />
        </label>
        <input
          id="jump-time"
          type="time"
          step={60}
          aria-label="Tid att hoppa till"
          value={time}
          onChange={(event) => {
            const picked = minuteOf(event.target.value);
            if (picked !== null) setMinute(picked);
          }}
        />
        <button id="jump" type="button" onClick={() => onClock?.({ action: "jump", time, speed: null, game_day: null, jump: null })}>
          {`Hoppa till ${time}`}
        </button>
      </div>
      <p className="liten">{jumpNote(now.clearances.length)}</p>
      {last && (
        <div className="rad" id="jump-undo">
          <span>{jumpText(last)}</span>
          <button id="undo-jump" type="button" onClick={() => onClock?.({ action: "undo_jump", jump: last.seq, speed: null, time: null, game_day: null })}>
            Ångra hoppet
          </button>
        </div>
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
          <button id="clock-toggle" type="button" className="primar" onClick={() => onClock?.({ action: now.clock.running ? "stop" : "start", speed: null, time: null, game_day: null, jump: null })}>
            {now.clock.running ? "Stoppa klockan" : "Starta klockan"}
          </button>
          <Chips label="Hastighet">
            {SPEEDS.map((speed) => (
              <Chip key={speed} label={`${speed}×`} pressed={now.clock.speed === speed} onClick={() => onClock?.({ action: "speed", speed, time: null, game_day: null, jump: null })} />
            ))}
          </Chips>
        </div>
      )}
      {admin && <Tidshopp now={now} onClock={onClock} />}
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
            <li key={clearance.clearance_id} className={clearance.reminders ? "vantar" : undefined}>
              <div className="vem">
                <b>{`${clearance.train_number} · ${placeCode(now, clearance.from_place)} → ${placeCode(now, clearance.to_place)}`}</b>
                <span className="liten">{`${clearance.departed ? "På väg" : (CASES[clearance.status] ?? clearance.status)} · begärd ${clearance.requested_at}${reminded(clearance.reminders)}`}</span>
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

/** Automatiken (F14): who works each place, leave and take back; its settings are under the
 * gear (H48, H50). */
function Automatiken({ now, clients, automation, openAutomation, onPlace }: NuProps & { now: Now; automation: Automation }) {
  const settings = automation.settings;
  const counts: Record<string, number> = { manned: 0, no_contact: 0, automatic: 0 };
  const places = automation.places ?? [];
  for (const place of places) counts[place.mode] = (counts[place.mode] ?? 0) + 1;
  const clientName = (id: string) => clients.find((client) => client.client_id === id)?.name ?? id;
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
      <p className="liten">
        Automatikens inställningar finns under kugghjulet, i <a href="/installningar#automatik">Inställningar</a>.
      </p>
    </details>
  );
}

