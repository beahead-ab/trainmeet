import { useState } from "react";
import { LEVELS, refKey, trainsOf, type Level, type ServiceOffer } from "./api";
import { timeSeconds } from "./clock";
import { onAxis, wholeMinutes } from "./korplan";
import type { Lok, LokState } from "./store";
import { TEXT, type Text } from "./text";
import { Icon, PageHead, Problem } from "./ui";

// Tåg (LOK-17, LOK-18, LOK-19, LOK-25, LOK-31, LOK-32, LOK-40; valj-tjanst.jpg, sok-nummer.jpg,
// valj-tag.jpg, ta-over.jpg): the services in start order with the driver's level first, a
// search on the paper's number, a service released on the line to take over, and one handed out
// by the dispatcher. On a meet without duties the services are the trains.

const rank = (level: Level | null | undefined) => (level ? LEVELS.indexOf(level) : -1);

export function overLevel(offer: ServiceOffer, mine: Level | undefined): boolean {
  return Boolean(mine && offer.level && rank(offer.level) > rank(mine));
}

/** Minutes until the service starts on Drift's clock, or null. */
export function minutesTo(time: string | null | undefined, now: number | null): number | null {
  const start = timeSeconds(time);
  if (start === null || now === null) return null;
  return wholeMinutes(start - onAxis(now, start));
}

export type Groups = { fits: ServiceOffer[]; released: ServiceOffer[]; rest: { start: string; offers: ServiceOffer[] }[] };

/** The list as the tab shows it: released on the line and free first (LOK-40), then the free
 * ones on the driver's level (LOK-32), then all the others in start order under their start
 * time, as the paper's front would be found (LOK-19). */
export function groupServices(offers: ServiceOffer[]): Groups {
  const released = offers.filter((o) => o.released_on_line && !o.taken);
  const fits = offers.filter((o) => o.matches_level && !o.taken && !o.done && !released.includes(o));
  const others = offers.filter((o) => !released.includes(o) && !fits.includes(o));
  const startOf = (o: ServiceOffer) => timeSeconds(o.start.time) ?? Number.MAX_SAFE_INTEGER;
  others.sort((a, b) => startOf(a) - startOf(b) || a.number.localeCompare(b.number, "sv", { numeric: true }));
  const rest: Groups["rest"] = [];
  for (const offer of others) {
    const start = offer.start.time ?? "";
    const last = rest[rest.length - 1];
    if (last && last.start === start) last.offers.push(offer);
    else rest.push({ start, offers: [offer] });
  }
  return { fits, released, rest };
}

function Status({ offer, mine, text, trains }: { offer: ServiceOffer; mine: string | undefined; text: Text; trains: boolean }) {
  if (offer.driver && offer.driver === mine) return <span className="lok-status din">{text.yours}</span>;
  if (offer.done) return <span className="lok-status klar">{text.done}</span>;
  if (offer.taken) return <span className="lok-status tagen">{offer.driver_name ? text.drives(offer.driver_name) : text.someoneDrives}</span>;
  return (
    <span className="lok-status ledig">
      <span aria-hidden="true">●</span> {trains ? text.freeTrain : text.free}
    </span>
  );
}

function Row({ lok, state, offer, now, text }: { lok: Lok; state: LokState; offer: ServiceOffer; now: number | null; text: Text }) {
  const trains = state.services?.kind === "train";
  const me = state.me?.driver;
  const over = overLevel(offer, me?.level);
  const minutes = minutesTo(offer.start.time, now);
  const detail = trains
    ? `${offer.start.time ?? ""}${minutes !== null && minutes > 0 ? ` · ${text.inMinutes(minutes)}` : ""}`
    : `${text.until(offer.end.time ?? "")}${over ? ` · ${text.overLevel}` : offer.operator ? ` · ${offer.operator}` : ""}`;
  return (
    <li>
      <button type="button" className={`lok-tjanst${offer.taken || offer.done ? " upptagen" : ""}`} onClick={() => lok.select(offer)}>
        <span className="lok-nummer tm-mono">{offer.number}</span>
        <span className="lok-vag">
          <b>
            {offer.start.place_name} → {offer.end.place_name}
          </b>
          <span className={over ? "over" : undefined}>{detail}</span>
        </span>
        <span className="lok-hoger">
          <Status offer={offer} mine={me?.id} text={text} trains={trains} />
          {offer.level && <span className={`lok-niva niva-${offer.level}`}>{text.levels[offer.level]}</span>}
          {trains && offer.operator && <span className="lok-niva">{offer.operator}</span>}
        </span>
      </button>
    </li>
  );
}

/** The paper's front in the app, to compare with the paper (LOK-19, sok-nummer.jpg). */
export function Front({ offer, text, paper, now }: { offer: ServiceOffer; text: Text; paper: string | null; now: number | null }) {
  const trains = offer.service.kind === "train";
  const minutes = minutesTo(offer.start.time, now);
  return (
    <div className="lok-framsida">
      <span className="lok-framsida-ord">{trains ? text.train : text.service}</span>
      <span className="lok-framsida-nummer tm-mono">{offer.number}</span>
      {paper && paper !== offer.number && <span className="lok-pa-papper">{text.onPaper(paper)}</span>}
      <p>
        {text.startsLine} <b className="tm-mono">{offer.start.time ?? "–"}</b> {text.at} <b>{offer.start.place_name}</b>
      </p>
      <p>
        {text.endsLine} <b className="tm-mono">{offer.end.time ?? "–"}</b> {text.at} <b>{offer.end.place_name}</b>
      </p>
      <p className="lok-framsida-bolag">
        {[offer.operator, trainsOf(offer).length && !trains ? text.trains(trainsOf(offer).join(", ")) : null, minutes !== null && minutes > 0 ? text.beginsIn(minutes) : null].filter(Boolean).join(" · ")}
      </p>
      {offer.level && <p className={`lok-svarighet niva-${offer.level}`}>{text.difficulty(text.levels[offer.level])}</p>}
    </div>
  );
}

/** Från trafikledningen (LOK-30, valj-tag.jpg): the service handed out, to take or not now. */
export function GivenCard({ lok, state, now }: { lok: Lok; state: LokState; now: number | null }) {
  const by = lok.givenBy();
  const offer = state.me?.service;
  if (!by || !offer) return null;
  const text = TEXT[state.language];
  const minutes = minutesTo(offer.start.time, now);
  const trains = offer.service.kind === "train";
  return (
    <section className="lok-utdelad" aria-label={text.givenBy[by]}>
      <p className="lok-overrubrik">{text.givenBy[by]}</p>
      <div className="lok-utdelad-rad">
        <b>{[trains ? text.trainNumber(offer.number) : text.serviceNumber(offer.number), offer.operator].filter(Boolean).join(" · ")}</b>
        <b className="tm-mono">{offer.start.time}</b>
      </div>
      <p>
        {offer.start.place_name} → {offer.end.place_name}
        {minutes !== null ? ` · ${text.beginsIn(minutes)}` : ""}
      </p>
      <div className="lok-knappar">
        <button type="button" className="lok-knapp primar" onClick={() => lok.acknowledge()}>
          {trains ? text.takeTrain : text.takeIt}
        </button>
        <button type="button" className="lok-knapp" disabled={state.busy} onClick={() => void lok.release()}>
          {text.notNow}
        </button>
      </div>
    </section>
  );
}

export function TagTab({ lok, state, now }: { lok: Lok; state: LokState; now: number | null }) {
  const text = TEXT[state.language];
  const [query, setQuery] = useState(state.query);
  const offers = state.services?.services ?? [];
  const trains = state.services?.kind === "train";
  const mine = state.me?.service;
  const searching = query.trim() !== "";
  const exact = searching ? offers.find((o) => o.exact) : undefined;
  const groups = groupServices(searching && exact ? offers.filter((o) => o !== exact) : offers);
  const level = state.me?.driver.level;
  const search = (value: string) => {
    setQuery(value);
    void lok.loadServices(value);
  };
  const lookByStart = () => {
    lok.paperHint(query.trim());
    search("");
  };
  return (
    <main className="lok-sida" id="innehall">
      <PageHead title={trains ? text.chooseTrain : text.chooseService} sub={trains ? text.noDuties : (state.meetName ?? "")} />
      {!(searching && exact) && <Problem text={state.problem} />}
      <GivenCard lok={lok} state={state} now={now} />
      {mine && !lok.givenBy() && (
        <section className="lok-min-tjanst">
          <p className="lok-overrubrik">{text.yourService}</p>
          <div className="lok-utdelad-rad">
            <b>{trains ? text.trainNumber(mine.number) : text.serviceNumber(mine.number)}</b>
            <span className="tm-mono">{mine.start.time}</span>
          </div>
          <p>
            {mine.start.place_name} → {mine.end.place_name}
          </p>
          <button type="button" className="lok-knapp primar" onClick={() => lok.navigate("korplan")}>
            {text.toKorplan}
          </button>
        </section>
      )}
      {groups.released.map((offer) => (
        <section key={refKey(offer.service)} className="lok-utan-forare">
          <p className="lok-overrubrik">{text.standsWithout}</p>
          <div className="lok-utdelad-rad">
            <b>
              {trains ? text.trainNumber(offer.number) : text.serviceNumber(offer.number)}
              {!trains && trainsOf(offer).length ? ` · ${text.trains(trainsOf(offer).join(", "))}` : ""}
            </b>
            {offer.level && <span className={`lok-niva niva-${offer.level}`}>{text.levels[offer.level]}</span>}
          </div>
          <p>
            {offer.start.place_name} → {offer.end.place_name} · {text.until(offer.end.time ?? "")}
          </p>
          <button type="button" className="lok-knapp primar" disabled={state.busy || Boolean(mine)} onClick={() => void lok.claim(offer, state.paper)}>
            {text.takeOver}
          </button>
        </section>
      ))}
      <div className="lok-sok">
        <label className="lok-sokfalt">
          {Icon.search}
          <span className="lok-dold">{trains ? text.searchTrain : text.searchService}</span>
          <input type="search" inputMode="numeric" value={query} placeholder={trains ? text.searchTrain : text.searchService} onChange={(event) => search(event.target.value)} />
        </label>
      </div>
      <p className="lok-not">{text.photoSoon}</p>
      {state.paper && !searching && (
        <p className="lok-upplysning">
          {text.paperChip(state.paper)} · {text.wrongNumber}{" "}
          <button type="button" className="lok-lank" onClick={() => lok.paperHint(null)}>
            {text.close}
          </button>
        </p>
      )}
      {searching && exact && (
        <section aria-label={text.hitOnNumber(query.trim())}>
          <h2 className="lok-avsnitt">{text.hitOnNumber(query.trim())}</h2>
          <Front offer={exact} text={text} paper={null} now={now} />
          <p className="lok-varning">
            {Icon.warning}
            <span>
              <b>{text.compare}</b> {text.compareNote}
            </span>
          </p>
          <Problem text={state.problem} />
          <div className="lok-knappar staplade">
            <button type="button" className="lok-knapp primar stor" disabled={state.busy || exact.taken || Boolean(mine)} onClick={() => void lok.claim(exact)}>
              {exact.taken ? (exact.driver_name ? text.drives(exact.driver_name) : text.someoneDrives) : text.thatsMine}
            </button>
            <button type="button" className="lok-knapp stor" onClick={lookByStart}>
              {text.notIt}
            </button>
          </div>
        </section>
      )}
      {searching && !exact && state.services && (
        <p className="lok-upplysning">
          {text.noHit(query.trim())}{" "}
          <button type="button" className="lok-lank" onClick={lookByStart}>
            {text.notIt}
          </button>
        </p>
      )}
      {groups.fits.length > 0 && level && (
        <section>
          <h2 className="lok-avsnitt">{text.fitsLevel(text.levels[level])}</h2>
          <ul className="lok-lista">
            {groups.fits.map((offer) => (
              <Row key={refKey(offer.service)} lok={lok} state={state} offer={offer} now={now} text={text} />
            ))}
          </ul>
        </section>
      )}
      {groups.rest.length > 0 && (
        <section>
          <h2 className="lok-avsnitt">{trains ? text.allTrains(offers.length) : text.allServices(offers.length)}</h2>
          <div className="lok-lista-ram">
            {groups.rest.map((group) => (
              <div key={group.start}>
                {!trains && <h3 className="lok-start">{text.startsAt(group.start || "–")}</h3>}
                <ul className="lok-lista">
                  {group.offers.map((offer) => (
                    <Row key={refKey(offer.service)} lok={lok} state={state} offer={offer} now={now} text={text} />
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </section>
      )}
      <p className="lok-not">{trains ? text.trainsOnly : text.wrongNumber}</p>
    </main>
  );
}

/** Tjänstens kort (taget.jpg): the front, the trains, the instructions, and Ta tjänsten. */
export function TjanstKort({ lok, state, now }: { lok: Lok; state: LokState; now: number | null }) {
  const text = TEXT[state.language];
  const offer = state.selected ?? state.me?.service ?? null;
  if (!offer) {
    return (
      <main className="lok-sida" id="innehall">
        <PageHead title={text.chooseService} back onBack={() => lok.navigate("tag")} backLabel={text.back} />
      </main>
    );
  }
  const trains = offer.service.kind === "train";
  const me = state.me;
  const isMine = Boolean(me?.service && refKey(me.service.service) === refKey(offer.service));
  const paper = isMine ? lok.paperOf(offer) : state.paper;
  const takenByOther = offer.taken && !isMine;
  return (
    <main className="lok-sida" id="innehall">
      <PageHead
        title={trains ? text.trainNumber(offer.number) : text.serviceNumber(offer.number)}
        sub={[trainsOf(offer).length ? text.trains(trainsOf(offer).join(", ")) : null, offer.operator].filter(Boolean).join(" · ")}
        back
        onBack={() => lok.navigate(isMine ? "korplan" : "tag")}
        backLabel={text.back}
      />
      <Problem text={state.problem} />
      <Front offer={offer} text={text} paper={paper} now={now} />
      <ul className="lok-lankar">
        <li>
          <button type="button" onClick={() => lok.navigate("instruktioner")}>
            <span className="lok-rod">{Icon.warning}</span>
            <span>{text.readInstructions}</span>
            {Icon.chevron}
          </button>
        </li>
      </ul>
      <div className="lok-knappar">
        {isMine ? (
          <button type="button" className="lok-knapp primar stor" onClick={() => lok.navigate("korplan")}>
            {text.toKorplan}
          </button>
        ) : takenByOther ? (
          <p className="lok-upplysning">{offer.driver_name ? text.drives(offer.driver_name) : text.taken}</p>
        ) : (
          <button type="button" className="lok-knapp primar stor" disabled={state.busy || offer.done || Boolean(me?.service)} onClick={() => void lok.claim(offer, state.paper)}>
            {offer.released_on_line ? text.takeOver : trains ? text.takeTrain : text.takeIt}
          </button>
        )}
        <button type="button" className="lok-knapp stor" onClick={() => lok.navigate(isMine ? "korplan" : "tag")}>
          {text.back}
        </button>
      </div>
    </main>
  );
}
