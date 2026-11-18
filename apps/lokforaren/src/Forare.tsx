import { rowsOf, type Presence } from "./api";
import { timeSeconds } from "./clock";
import type { Lok, LokState } from "./store";
import { TEXT, type Text } from "./text";
import { Avatar, Icon, PageHead, Problem, TrainMark } from "./ui";

// Förare (LOK-27, forare.jpg): who drives along my service, by their own check-ins; who is on
// Paus or waits for the start; and which services are free. Names and photos only as the API
// gives them (LOK-37): over the internet without logging in, a driver is no name and no photo.

/** The name the others may see, or the word Förare. */
export const nameOf = (presence: Presence, text: Text) => presence.driver.name ?? text.driver;

function Pill({ presence, text }: { presence: Presence; text: Text }) {
  return (
    <span className={`lok-forare-pill${presence.me ? " jag" : ""}${presence.checkin?.fading ? " tonar" : ""}`}>
      {presence.me ? <TrainMark /> : <Avatar driver={presence.driver} />}
      <b>{presence.me ? text.youShort : nameOf(presence, text)}</b>
      {presence.service_number && <span>{text.serviceShort(presence.service_number)}</span>}
    </span>
  );
}

function DriverRow({ presence, text }: { presence: Presence; text: Text }) {
  const said = [
    presence.driver.state ? text.states[presence.driver.state] : text.levels[presence.driver.level],
    presence.service_number ? text.serviceOf(presence.service_number) : null,
    presence.train_number ? text.trains(presence.train_number) : null,
    presence.checkin ? text.checkedIn(presence.checkin.place_name, presence.checkin.model_time) : null,
  ]
    .filter(Boolean)
    .join(" · ");
  return (
    <li className={`lok-forare-rad${presence.me ? " jag" : ""}`}>
      <Avatar driver={presence.driver} size="stor" />
      <span>
        <b>
          {nameOf(presence, text)}
          {presence.me && <span className="lok-du">{text.youShort}</span>}
        </b>
        <span>{said}</span>
      </span>
    </li>
  );
}

export function ForareTab({ lok, state }: { lok: Lok; state: LokState }) {
  const text = TEXT[state.language];
  const presence = state.presence ?? [];
  const korplan = state.korplan;
  const route = korplan ? [...new Map(rowsOf(korplan).filter((row) => row.stops).map((row) => [row.place, row.place_name])).entries()] : [];
  const onRoute = new Set(route.map(([place]) => place));
  const along = presence.filter((p) => p.checkin && onRoute.has(p.checkin.place));
  const driving = presence.filter((p) => p.service_number && !along.includes(p));
  const resting = presence.filter((p) => !p.service_number && !along.includes(p));
  const free = (state.services?.services ?? []).filter((offer) => !offer.taken && !offer.done);
  const nextFree = free.map((offer) => offer.start.time).filter((time): time is string => Boolean(time)).sort((a, b) => (timeSeconds(a) ?? 0) - (timeSeconds(b) ?? 0))[0];
  const hidden = presence.some((p) => !p.me && p.driver.name === null);
  return (
    <main className="lok-sida" id="innehall">
      <PageHead title={text.driversTitle} sub={text.driversOn(presence.length, state.meetName ?? "")} />
      <Problem text={state.problem} />
      {route.length > 0 && (
        <section className="lok-kort lok-langs">
          <h2 className="lok-avsnitt">{text.alongService}</h2>
          <ol>
            {route.map(([place, name]) => (
              <li key={place}>
                <span className="lok-ring" aria-hidden="true" />
                <b>{name}</b>
                <span className="lok-pills">
                  {along
                    .filter((p) => p.checkin?.place === place)
                    .map((p) => (
                      <Pill key={p.driver.id} presence={p} text={text} />
                    ))}
                </span>
              </li>
            ))}
          </ol>
        </section>
      )}
      {driving.length > 0 && (
        <section className="lok-kort">
          <h2 className="lok-avsnitt">{text.onTrack}</h2>
          <ul className="lok-forare">
            {driving.map((p) => (
              <DriverRow key={p.driver.id} presence={p} text={text} />
            ))}
          </ul>
        </section>
      )}
      {resting.length > 0 && (
        <section className="lok-kort">
          <h2 className="lok-avsnitt">{text.notOnTrack}</h2>
          <ul className="lok-forare">
            {resting.map((p) => (
              <DriverRow key={p.driver.id} presence={p} text={text} />
            ))}
          </ul>
        </section>
      )}
      {presence.length <= 1 && <p className="lok-not">{text.noDrivers}</p>}
      {hidden && <p className="lok-not">{text.namesHidden}</p>}
      <ul className="lok-lankar">
        <li>
          <button type="button" onClick={() => lok.navigate("tag")}>
            <span>{free.length ? text.freeServices(nextFree ?? null) : text.noFree}</span>
            {Icon.chevron}
          </button>
        </li>
      </ul>
      <button type="button" className="lok-knapp incheckning stor" onClick={() => lok.open("checkin")}>
        <TrainMark /> {text.checkInOrPause}
      </button>
    </main>
  );
}
