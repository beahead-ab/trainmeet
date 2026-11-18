import { Fragment, useEffect, useRef, useState, type ReactNode } from "react";
import { MESSAGE_KINDS, rowsOf, trainsOf, UNKNOWN_PLACE, type Korplan, type KorplanRow, type MessageKind, type TrainPosition } from "./api";
import { clockText, timeSeconds } from "./clock";
import { axisNow, countdown, frammeAllowed, frammeRow, momentsOf, nextStop, nuPosition, onLineByPlan, wholeMinutes, type Moment, type NextStop } from "./korplan";
import { PaperBanner, RejectedCard, runningPaper } from "./Papper";
import type { Lok, LokState, Then } from "./store";
import { GivenCard } from "./Tag";
import { speedText, TEXT, type Text } from "./text";
import { Icon, PageHead, Problem, Sheet, TrainMark } from "./ui";

// Körplan (LOK-03, LOK-12, LOK-20–LOK-24, LOK-38, LOK-39, LOK-41): before the start the
// countdown on the meet clock with the real time beside it (fore-start.jpg); then the plan as a
// time axis with the NU-line in yellow on Drift's clock, Drift's reality in blue when the game
// shows it, the clearance's word, Ändrat, and the next stop with check-in at the bottom
// (korplan-*.jpg). The app never gives departure (LOK-11). After the paper (LOK-13, LOK-29,
// papper.jpg) the körplan is the timetable as read from the photos, marked so, with where it
// stands with Trafikledningen; a time that could not be read is shown as unknown, never guessed.

const OPENS_BEFORE = 10 * 60;

const hhmm = (seconds: number) => clockText(seconds, false);

/** The rows of a körplan after the paper whose times could not be read (KorplanRow.unreadable,
 * LOK-29): shown as unknown, never guessed. */
export function unreadableRows(korplan: Korplan | null): (index: number) => boolean {
  if (!korplan?.paper) return () => false;
  const rows = rowsOf(korplan);
  return (index) => Boolean(rows[index]?.unreadable);
}

/** The körplan's moments, with the unknown times of a paper kept in their place. */
export function momentsFor(state: LokState): Moment[] {
  const korplan = state.korplan;
  return korplan ? momentsOf(rowsOf(korplan), unreadableRows(korplan)) : [];
}

/** – oläslig: a time on the paper that could not be read (LOK-29). */
function Unknown({ text }: { text: Text }) {
  return (
    <>
      –<small className="lok-olaslig">{text.unreadable}</small>
    </>
  );
}

/** What the head says under the service's number: the trains and the way, or with Drift's
 * reality the train, where it goes and how late. */
export function headLine(korplan: Korplan | null, text: Text): string {
  if (!korplan || !rowsOf(korplan).length) return "";
  const trains = [...new Set(rowsOf(korplan).map((row) => row.train_number))].join(", ");
  const first = rowsOf(korplan)[0]!;
  const last = rowsOf(korplan)[rowsOf(korplan).length - 1]!;
  const position = korplan.settings.reality ? korplan.position : null;
  if (position && position.delay) return `${position.train_number} → ${last.place_name} · ${text.late(position.delay)}`;
  return `${trains} · ${first.place_name} → ${last.place_name}`;
}

/** Where the blue train mark goes: before the moment at this index (LOK-38). */
export function markIndex(moments: Moment[], position: TrainPosition | null | undefined): number | null {
  if (!position) return null;
  const ofTrain = (moment: Moment) => moment.row.train === position.train;
  if (position.state === "on_the_way") {
    const from = moments.findIndex((m) => ofTrain(m) && m.kind === "departure" && m.row.place === position.from_place);
    return from === -1 ? null : from + 1;
  }
  if (position.state === "done") {
    const at = moments.map((m, i) => (ofTrain(m) && m.row.place === position.place ? i : -1)).filter((i) => i >= 0);
    return at.length ? at[at.length - 1]! + 1 : null;
  }
  const here = moments.map((m, i) => (ofTrain(m) && m.row.place === position.place ? i : -1)).filter((i) => i >= 0);
  if (!here.length) return null;
  if (position.state === "planned") return here[0]! + 1;
  // Standing at a stop: between its arrival and departure, or after the place's one moment.
  const last = here[here.length - 1]!;
  return here.length > 1 && moments[last]!.kind === "departure" ? last : last + 1;
}

function TrainLine({ position, korplan, text }: { position: TrainPosition; korplan: Korplan; text: Text }) {
  const name = (place: string | null | undefined) => rowsOf(korplan).find((row) => row.place === place)?.place_name ?? place ?? "";
  const said =
    position.state === "on_the_way"
      ? text.trainOnWay(position.train_number, name(position.to_place))
      : position.state === "planned"
        ? text.trainPlanned(position.train_number, name(position.place))
        : position.state === "done"
          ? text.trainDone(position.train_number, name(position.place))
          : text.trainAt(position.train_number, name(position.place));
  return (
    <li className="lok-moment lok-verklighet">
      <span className="lok-tid" />
      <span className="lok-axel">
        <TrainMark />
      </span>
      <span className="lok-innehall">
        <b>{said}</b>
        <span>
          {text.byStations}
          {position.delay ? ` · ${text.late(position.delay)}` : ""}
        </span>
      </span>
    </li>
  );
}

function NuLine({ now, fraction }: { now: number; fraction: number }) {
  return (
    <li className="lok-nu" aria-label={`NU ${clockText(now)}`} data-fraction={fraction.toFixed(2)}>
      <span className="lok-nu-tid tm-mono">{clockText(now)}</span>
      <span className="lok-nu-linje" aria-hidden="true" />
    </li>
  );
}

function Moments({ lok, state, korplan, moments, now, text }: { lok: Lok; state: LokState; korplan: Korplan; moments: Moment[]; now: number; text: Text }) {
  const nu = nuPosition(moments, now);
  const reality = korplan.settings.reality;
  const position = reality ? korplan.position : null;
  const mark = markIndex(moments, position);
  const checkin = korplan.checkin;
  const lineRef = useRef<HTMLDivElement>(null);
  // Follow the NU-line when it passes a moment, unless the driver has just scrolled.
  const touched = useRef(0);
  useEffect(() => {
    if (Date.now() - touched.current < 8000) return;
    lineRef.current?.querySelector(".lok-nu")?.scrollIntoView?.({ block: "center", behavior: "smooth" });
  }, [nu.index]);
  const items: ReactNode[] = [];
  const extra = (index: number) => {
    if (nu.index === index) items.push(<NuLine key={`nu-${index}`} now={now} fraction={nu.fraction} />);
    if (mark === index && position) items.push(<TrainLine key={`tag-${index}`} position={position} korplan={korplan} text={text} />);
  };
  moments.forEach((moment, index) => {
    extra(index);
    const row = moment.row;
    const firstOfRow = index === 0 || moments[index - 1]!.row.call !== row.call;
    if (row.first_of_train && firstOfRow) {
      const ofTrain = rowsOf(korplan).filter((r) => r.train === row.train);
      items.push(
        <li key={`train-${row.call}`} className="lok-moment lok-tagbricka">
          <span className="lok-tid" />
          <span className="lok-axel" />
          <span className="lok-innehall">
            <span className="lok-tagnummer tm-mono">{row.train_number}</span> {ofTrain[0]?.place_name} → {ofTrain[ofTrain.length - 1]?.place_name}
          </span>
        </li>,
      );
    }
    items.push(<MomentRow key={`${row.call}-${moment.kind}`} lok={lok} state={state} korplan={korplan} moment={moment} firstOfRow={firstOfRow} passed={moment.t <= now} now={now} delay={position?.train === row.train ? (position?.delay ?? 0) : 0} checkedHere={Boolean(checkin && firstOfRow && checkin.place === row.place && (!checkin.train || checkin.train === row.train))} text={text} />);
  });
  extra(moments.length);
  return (
    <div className="lok-tidsaxel" ref={lineRef} onTouchStart={() => (touched.current = Date.now())} onWheel={() => (touched.current = Date.now())}>
      <ol>{items}</ol>
    </div>
  );
}

function MomentRow({ lok, state, korplan, moment, firstOfRow, passed, now, delay, checkedHere, text }: { lok: Lok; state: LokState; korplan: Korplan; moment: Moment; firstOfRow: boolean; passed: boolean; now: number; delay: number; checkedHere: boolean; text: Text }) {
  const row = moment.row;
  const real = row.real;
  const changed = lok.marks.shows(row, now);
  const planned = moment.unknown ? null : moment.kind === "arrival" ? row.arrival ?? row.departure : row.departure ?? row.arrival;
  let reality: string | null = null;
  if (real && moment.kind === "arrival" && real.arrived) reality = text.arrived(real.arrived);
  else if (real && moment.kind === "departure" && real.departed) reality = text.departed(real.departed);
  else if (real && moment.kind === "departure" && real.here && passed) reality = text.standsStill;
  else if (korplan.settings.reality && !passed && delay > 0 && planned) reality = text.about(hhmm((timeSeconds(planned) ?? 0) + delay * 60));
  const time = moment.unknown ? <Unknown text={text} /> : planned;
  const checkin = checkedHere ? korplan.checkin : null;
  if (moment.kind === "pass") {
    return (
      <li className={`lok-moment lok-passage${passed ? " passerad" : ""}${moment.unknown ? " okand" : ""}`}>
        <span className="lok-tid tm-mono">
          {time}
          {reality && <small className="lok-verklig">{reality}</small>}
        </span>
        <span className="lok-axel">
          <span className="lok-prick liten" />
        </span>
        <span className="lok-innehall">
          <span>
            <b>{row.place_name}</b> · {text.passes}
            {row.place === UNKNOWN_PLACE && ` · ${text.notInMeet}`}
          </span>
          {changed && <Changed text={text} />}
        </span>
      </li>
    );
  }
  const what = moment.kind === "arrival" ? text.arrival : text.departure;
  return (
    <li className={`lok-moment${passed ? " passerad" : ""}${row.real?.here ? " har" : ""}${moment.unknown ? " okand" : ""}`}>
      <span className="lok-tid tm-mono">
        {time}
        {reality && <small className="lok-verklig">{reality}</small>}
      </span>
      <span className="lok-axel">
        <span className={`lok-prick${checkin ? " incheckad" : ""}`}>{checkin ? Icon.tag : null}</span>
      </span>
      <span className="lok-innehall">
        {firstOfRow && (
          <span className="lok-plats">
            <b>{row.place_name}</b>
            {row.place === UNKNOWN_PLACE && <span className="lok-bricka">{text.notInMeet}</span>}
            {korplan.settings.arrival && row.unmanned && moment.kind === "arrival" && <span className="lok-bricka">{text.unmanned}</span>}
            {checkin && <span className="lok-du">{text.you(checkin.model_time)}</span>}
          </span>
        )}
        <span className="lok-vad">
          {what}
          {row.track ? ` · ${text.track(row.track)}` : ""}
          {moment.unknown ? ` · ${text.unreadableTime}` : ""}
        </span>
        {changed && <Changed text={text} />}
        {firstOfRow && row.note && <span className="lok-anmarkning">{row.note}</span>}
        {moment.kind === "departure" &&
          (row.real?.late_oncoming ?? []).map((late) => (
            <span key={late.train} className="lok-sen">
              {text.lateOncoming(late.train_number, late.delay)}
            </span>
          ))}
        {moment.kind === "arrival" && row.last && <span className="lok-anmarkning">{text.serviceEnds}</span>}
        {state.framme.includes(row.call) && moment.kind === "arrival" && <span className="lok-du">{text.framme(row.place_name)}</span>}
      </span>
    </li>
  );
}

function Changed({ text }: { text: Text }) {
  return <span className="lok-andrat">{text.changed}</span>;
}

/** Tågklareringens besked for the next stop (LOK-21): for a departure its own, for an arrival
 * the one for the section into it; with the row it was asked from. */
export function clearanceFor(moments: Moment[], next: NextStop): { said: NonNullable<KorplanRow["clearance"]>; from: KorplanRow } | null {
  if (next.moment.kind === "departure") return next.moment.row.clearance ? { said: next.moment.row.clearance, from: next.moment.row } : null;
  const index = moments.indexOf(next.moment);
  for (let i = index - 1; i >= 0; i -= 1) {
    const moment = moments[i]!;
    if (moment.row.train !== next.moment.row.train) break;
    if (moment.kind === "departure") return moment.row.clearance?.to_place === next.moment.row.place ? { said: moment.row.clearance, from: moment.row } : null;
  }
  return null;
}

/** NÄSTA at the bottom (korplan-plan.jpg): the next stop, its track, what is passed on the way,
 * the clearance's word, check-in, Framme where it may be said, and the four messages. */
export function NextPanel({ lok, state, korplan, moments, now }: { lok: Lok; state: LokState; korplan: Korplan; moments: Moment[]; now: number }) {
  const text = TEXT[state.language];
  const next = nextStop(moments, now);
  const position = korplan.settings.reality ? korplan.position : null;
  const delay = next && position?.train === next.moment.row.train ? (position.delay ?? 0) : 0;
  const framme = frammeRow(moments, now, position);
  const mayFramme = frammeAllowed(framme, korplan.settings.arrival) && framme !== null && !state.framme.includes(framme.call);
  const lastRow = rowsOf(korplan)[rowsOf(korplan).length - 1];
  const finishing = !mayFramme && lastRow && (framme?.call === lastRow.call || !next);
  const place = next?.moment.row ?? lastRow;
  const clearance = next && korplan.settings.clearances ? clearanceFor(moments, next) : null;
  const placeName = (id: string) => rowsOf(korplan).find((row) => row.place === id)?.place_name ?? id;
  const towards = next?.moment.kind === "departure" ? moments.slice(moments.indexOf(next.moment) + 1).find((m) => m.kind !== "pass")?.row.place_name : null;
  const minutes = next ? wholeMinutes(next.moment.t + delay * 60 - now) : 0;
  const unknown = Boolean(next?.moment.unknown);
  const paper = runningPaper(state);
  // A place on the paper the meet does not have cannot be checked in at: choose one instead.
  const checkInHere = place && place.place !== UNKNOWN_PLACE ? place : null;
  return (
    <section className="lok-nasta" aria-label={text.next}>
      {next ? (
        <>
          <div className="lok-nasta-rad">
            <span className="lok-overrubrik">{next.moment.kind === "departure" ? text.departure : text.next}</span>
            <span className={delay > 0 ? "lok-sen" : undefined}>{unknown ? text.unreadableTime : delay > 0 ? text.late(delay) : text.inMinutes(minutes)}</span>
          </div>
          <div className="lok-nasta-rad stor">
            <b>{next.moment.kind === "arrival" ? text.arrivalAt(next.moment.row.place_name) : next.moment.row.place_name}</b>
            <b className="tm-mono">{unknown ? "–" : hhmm(next.moment.t + delay * 60)}</b>
          </div>
          <div className="lok-chips">
            {next.moment.row.track && <span className={`lok-chip-liten${lok.marks.shows(next.moment.row, now) ? " andrat" : ""}`}>{text.track(next.moment.row.track)}</span>}
            {towards && <span className="lok-chip-liten">{text.towards(towards)}</span>}
            {next.passes.map((pass) => (
              <span key={pass.row.call} className="lok-chip-liten gra">
                {text.passesWithout(pass.row.place_name)}
              </span>
            ))}
            {delay > 0 && <span className="lok-chip-liten sen">{text.plusMinutes(delay)}</span>}
            {lok.marks.shows(next.moment.row, now) && <span className="lok-chip-liten andrat">{text.changed}</span>}
          </div>
          {clearance && (
            <p className={`lok-klarering ${clearance.said.status}`}>
              {clearance.said.status === "waiting" ? Icon.clock : Icon.pin}
              <span>
                {clearance.said.status === "approved" ? (
                  <b>{text.clearApproved(placeName(clearance.said.to_place))}</b>
                ) : clearance.said.status === "waiting" ? (
                  text.clearWaiting(clearance.from.place_name, placeName(clearance.said.to_place))
                ) : (
                  text.clearRejected(clearance.from.place_name, placeName(clearance.said.to_place))
                )}
                {clearance.said.status === "approved" && clearance.said.track ? ` ${text.clearTrack(placeName(clearance.said.to_place), next.moment.row.train_number, clearance.said.track)}` : ""}
              </span>
            </p>
          )}
          {next.moment.kind === "departure" && korplan.settings.clearances && <p className="lok-not">{text.departureNote}</p>}
        </>
      ) : (
        <div className="lok-nasta-rad stor">
          <b>{text.serviceEnds}</b>
        </div>
      )}
      {mayFramme && framme && <p className="lok-not">{text.frammeNote(framme.place_name)}</p>}
      {finishing && <p className="lok-not">{text.finishNote}</p>}
      {korplan.checkin && <p className={`lok-incheckad${korplan.checkin.fading ? " tonar" : ""}`}>{text.checkedIn(korplan.checkin.place_name, korplan.checkin.model_time)}</p>}
      <Problem text={state.problem} />
      <div className="lok-nasta-knappar">
        {mayFramme && framme ? (
          <button type="button" className="lok-knapp gron" disabled={state.busy} onClick={() => void lok.framme(framme.call)}>
            {Icon.check} {text.framme(framme.place_name)}
          </button>
        ) : finishing && lastRow ? (
          <button type="button" className="lok-knapp gron" disabled={state.busy} onClick={() => void lok.framme(lastRow.call)}>
            {Icon.check} {text.finish}
          </button>
        ) : checkInHere ? (
          <button type="button" className="lok-knapp incheckning" disabled={state.busy} onClick={() => void lok.checkIn(checkInHere.place, checkInHere.track ?? null)}>
            <TrainMark /> {text.checkIn(checkInHere.place_name)}
          </button>
        ) : (
          place && (
            <button type="button" className="lok-knapp incheckning" disabled={state.busy} onClick={() => lok.open("checkin")}>
              <TrainMark /> {text.checkInTitle}
            </button>
          )
        )}
        <button type="button" className="lok-knapp ikon" aria-label={text.sayToDispatch} onClick={() => lok.open("messages")}>
          {Icon.message}
        </button>
        {paper ? (
          <button type="button" className="lok-knapp ikon" aria-label={text.paperPhotos} onClick={() => lok.navigate("papper")}>
            {Icon.camera}
          </button>
        ) : (
          <button type="button" className="lok-knapp ikon" aria-label={text.wholeService} onClick={() => lok.select(state.me?.service ?? null)}>
            {Icon.paper}
          </button>
        )}
      </div>
    </section>
  );
}

/** Before the start (fore-start.jpg): the countdown on the meet clock and the real time beside
 * it, the reminders, and Inväntar start. */
export function ForeStart({ lok, state, now, moments }: { lok: Lok; state: LokState; now: number; moments: Moment[] }) {
  const text = TEXT[state.language];
  const me = state.me!;
  const start = me.start!;
  const speed = lok.clock.speed();
  const running = lok.clock.mode() === "running";
  const left = countdown(start, now, speed, running);
  const first = moments.find((moment) => moment.kind === "departure" && !moment.unknown) ?? moments.find((moment) => !moment.unknown);
  const toward = first ? moments.slice(moments.indexOf(first) + 1).find((m) => m.kind !== "pass") : undefined;
  const state_ = me.driver.state;
  const events: { time: number; title: string; note: string; kind?: string }[] = [];
  if (left.game > 20 * 60) events.push({ time: start.seconds - 20 * 60, title: text.reminder, note: text.reminderNote(20) });
  if (left.game > OPENS_BEFORE) events.push({ time: start.seconds - OPENS_BEFORE, title: text.opens, note: text.opensNote });
  events.push({ time: start.seconds, title: text.serviceBegins, note: me.service?.start.place_name ?? "" });
  if (first && first.t !== start.seconds) events.push({ time: first.t, title: text.departureAt(first.row.place_name), note: [first.row.track ? text.track(first.row.track) : null, toward ? text.towards(toward.row.place_name) : null].filter(Boolean).join(" · "), kind: "verklig" });
  return (
    <section className="lok-fore">
      <p className="lok-fore-rubrik">{text.beginsAt(start.time, me.service?.start.place_name ?? "")}</p>
      <p className="lok-nedrakning">{text.minutesLeft(wholeMinutes(left.game))}</p>
      <p className="lok-fore-ord">{text.leftOnClock}</p>
      <p className="lok-not">{left.real !== null ? text.realTime(wholeMinutes(left.real), speedText(speed)) : text.stoppedClock}</p>
      <div className="lok-kort">
        <h2 className="lok-avsnitt">{text.whatHappens}</h2>
        <ol className="lok-handelser">
          <li className="nu">
            <span className="tm-mono">{hhmm(now)}</span>
            <span className="lok-ring" aria-hidden="true" />
            <span>
              <b>{text.now}</b>
              <span>{state_ ? text.youAre(text.states[state_]) : text.noState}</span>
            </span>
          </li>
          {events.map((event) => (
            <li key={`${event.time}-${event.title}`} className={event.kind}>
              <span className="tm-mono">{hhmm(event.time)}</span>
              <span className="lok-ring" aria-hidden="true" />
              <span>
                <b>{event.title}</b>
                <span>{event.note}</span>
              </span>
            </li>
          ))}
        </ol>
      </div>
      {!state_ && (
        <button type="button" className="lok-knapp" disabled={state.busy} onClick={() => void lok.profile({ state: "waiting_start" })}>
          {text.standWaiting}
        </button>
      )}
      {state.remindersOn && lok.notificationsAskable() && (
        <button type="button" className="lok-knapp" onClick={() => void lok.askNotifications()}>
          {Icon.bell} {text.allowNotifications}
        </button>
      )}
      <div className="lok-knappar">
        <button type="button" className="lok-knapp mjuk stor" onClick={() => lok.seeKorplan()}>
          {text.showKorplan}
        </button>
        <button type="button" className="lok-knapp stor" onClick={() => lok.open("release")}>
          {text.release}
        </button>
      </div>
    </section>
  );
}

export function KorplanTab({ lok, state, now }: { lok: Lok; state: LokState; now: number | null }) {
  const text = TEXT[state.language];
  const me = state.me;
  const korplan = state.korplan;
  if (!me?.service) {
    return (
      <main className="lok-sida" id="innehall">
        <PageHead title={text.tabs.korplan} sub={text.noService} />
        <GivenCard lok={lok} state={state} now={now} />
        <RejectedCard lok={lok} state={state} />
        <section className="lok-kort">
          <p>{text.noServiceNote}</p>
          <button type="button" className="lok-knapp primar" onClick={() => lok.navigate("tag")}>
            {text.toTrains}
          </button>
        </section>
      </main>
    );
  }
  const moments = momentsFor(state);
  const at = now === null ? null : axisNow(moments, now);
  const trains = me.service.service.kind === "train";
  const paper = lok.paperOf(me.service);
  const afterPaper = Boolean(me.service.paper || korplan?.paper);
  const before = me.start && now !== null ? countdown(me.start, now, lok.clock.speed(), true).game : 0;
  const foreStart = before > OPENS_BEFORE && !state.showKorplan;
  const anyChanged = korplan && at !== null && rowsOf(korplan).some((row) => lok.marks.shows(row, at));
  return (
    <main className="lok-sida lok-korplan" id="innehall">
      <PageHead title={trains ? text.trainNumber(me.service.number) : text.serviceNumber(me.service.number)} chip={afterPaper ? text.afterPaper : paper && paper !== me.service.number ? text.paperChip(paper) : null} sub={headLine(korplan, text)} />
      <PaperBanner state={state} />
      <GivenCard lok={lok} state={state} now={now} />
      {anyChanged && (
        <p className="lok-andrat-banner" role="status">
          {Icon.bell}
          <span>{text.changedBanner}</span>
        </p>
      )}
      {korplan && at !== null && foreStart && <ForeStart lok={lok} state={state} now={at} moments={moments} />}
      {korplan && at !== null && !foreStart && (
        <>
          <Moments lok={lok} state={state} korplan={korplan} moments={moments} now={at} text={text} />
          <p className="lok-slapp-rad">
            <button type="button" className="lok-lank" onClick={() => lok.open("release")}>
              {text.release}
            </button>
          </p>
          <NextPanel lok={lok} state={state} korplan={korplan} moments={moments} now={at} />
        </>
      )}
    </main>
  );
}

// --- The sheets ----------------------------------------------------------------------------

/** Säg till trafikledningen (LOK-23, meddela.jpg): four ready messages, one tap and Skicka. */
export function MessageSheet({ lok, state }: { lok: Lok; state: LokState }) {
  const text = TEXT[state.language];
  const [kind, setKind] = useState<MessageKind>("delayed");
  const service = state.me?.service;
  const sub = service ? [service.service.kind === "train" ? text.trainNumber(service.number) : text.serviceNumber(service.number), trainsOf(service).length && service.service.kind !== "train" ? text.trains(trainsOf(service).join(", ")) : null].filter(Boolean).join(" · ") : null;
  return (
    <Sheet title={text.messageTitle} onClose={() => lok.open(null)} text={text}>
      {sub && <p className="lok-ark-under">{sub}</p>}
      <div className="lok-meddelanden" role="radiogroup" aria-label={text.messageTitle}>
        {MESSAGE_KINDS.map((choice) => (
          <button key={choice} type="button" role="radio" aria-checked={kind === choice} className="lok-meddelande" onClick={() => setKind(choice)}>
            <b>{text.kinds[choice]}</b>
            <span>{text.kindNotes[choice]}</span>
          </button>
        ))}
      </div>
      <p className="lok-not">{text.messageNote}</p>
      <Problem text={state.problem} />
      <button type="button" className="lok-knapp primar stor" disabled={state.busy} onClick={() => void lok.send(kind)}>
        {text.sendKind(text.kinds[kind])}
      </button>
    </Sheet>
  );
}

/** Släpp tjänsten (LOK-25, LOK-35, slapp.jpg): released on the line, the train stands and the
 * dispatcher gets the alarm at once; the driver says what comes next. */
export function ReleaseSheet({ lok, state, now }: { lok: Lok; state: LokState; now: number | null }) {
  const text = TEXT[state.language];
  const [then, setThen] = useState<Then>("pause");
  const korplan = state.korplan;
  const service = state.me?.service;
  const position = korplan?.settings.reality ? korplan.position : null;
  const moments = momentsFor(state);
  const byPlan = now !== null && moments.length > 0 && onLineByPlan(moments, axisNow(moments, now));
  const name = (place: string | null | undefined) => rowsOf(korplan).find((row) => row.place === place)?.place_name ?? place ?? "";
  let warning: ReactNode = null;
  if (position) {
    if (position.state === "on_the_way") warning = text.releaseOnLine;
  } else if (korplan) {
    warning = (
      <>
        {byPlan && <b>{text.releaseOnLineByPlan} </b>}
        {text.releaseMaybe}
      </>
    );
  }
  return (
    <Sheet title={text.releaseTitle(service?.number ?? "")} onClose={() => lok.open(null)} text={text}>
      <p className="lok-ark-under">{text.releaseNote}</p>
      {position && (
        <div className="lok-lage">
          <TrainMark />
          <span>
            <b>{position.state === "on_the_way" ? text.trainOnWay(position.train_number, name(position.to_place)) : text.trainAt(position.train_number, name(position.place))}</b>
            <span>{text.byStations}</span>
          </span>
        </div>
      )}
      {warning && (
        <p className="lok-varning">
          {Icon.warning}
          <span>{warning}</span>
        </p>
      )}
      <h3 className="lok-avsnitt">{text.whatThen}</h3>
      <div className="lok-alternativ" role="radiogroup" aria-label={text.whatThen}>
        {(
          [
            ["pause", text.thenPause, text.thenPauseNote],
            ["other", text.thenOther, text.thenOtherNote],
            ["leave", text.thenLeave, text.thenLeaveNote],
          ] as [Then, string, string][]
        ).map(([value, title, note]) => (
          <button key={value} type="button" role="radio" aria-checked={then === value} className="lok-alternativ-val" onClick={() => setThen(value)}>
            <span className="lok-radio" aria-hidden="true" />
            <span>
              <b>{title}</b>
              <span>{note}</span>
            </span>
          </button>
        ))}
      </div>
      <Problem text={state.problem} />
      <button type="button" className="lok-knapp primar stor" disabled={state.busy} onClick={() => void lok.release(then)}>
        {text.releaseHere}
      </button>
    </Sheet>
  );
}

/** Checka in (LOK-22): a place and a track if the driver likes, or Paus. It controls nothing. */
export function CheckInSheet({ lok, state }: { lok: Lok; state: LokState }) {
  const text = TEXT[state.language];
  const fromPlan = state.korplan ? [...new Map(rowsOf(state.korplan).filter((row) => row.stops && row.place !== UNKNOWN_PLACE).map((row) => [row.place, { place: row.place, name: row.place_name }])).values()] : [];
  const places = fromPlan.length ? fromPlan : state.places.map((p) => ({ place: p.place, name: p.name }));
  const [place, setPlace] = useState(places[0]?.place ?? "");
  const [track, setTrack] = useState("");
  return (
    <Sheet title={text.checkInTitle} onClose={() => lok.open(null)} text={text}>
      <p className="lok-ark-under">{text.checkInNote}</p>
      <label className="lok-falt">
        <span>{text.place}</span>
        <select value={place} onChange={(event) => setPlace(event.target.value)}>
          {places.map((p) => (
            <option key={p.place} value={p.place}>
              {p.name}
            </option>
          ))}
        </select>
      </label>
      <label className="lok-falt">
        <span>{text.trackOptional}</span>
        <input value={track} onChange={(event) => setTrack(event.target.value)} maxLength={12} />
      </label>
      <Problem text={state.problem} />
      <button type="button" className="lok-knapp primar stor" disabled={state.busy || !place} onClick={() => void lok.checkIn(place, track || null)}>
        {text.doCheckIn}
      </button>
      <button
        type="button"
        className="lok-knapp stor"
        disabled={state.busy}
        onClick={() => {
          void lok.profile({ state: "pause" }).then(() => lok.open(null));
        }}
      >
        {text.orPause}
      </button>
    </Sheet>
  );
}

export function Sheets({ lok, state, now }: { lok: Lok; state: LokState; now: number | null }) {
  return (
    <Fragment>
      {state.sheet === "messages" && <MessageSheet lok={lok} state={state} />}
      {state.sheet === "release" && <ReleaseSheet lok={lok} state={state} now={now} />}
      {state.sheet === "checkin" && <CheckInSheet lok={lok} state={state} />}
    </Fragment>
  );
}
