import { useState, type ChangeEvent } from "react";
import { candidatesOf, idLoginAddress, PAPER_PAGES, photosOf, refKey, type PaperEnd, type PaperService } from "./api";
import type { Lok, LokState } from "./store";
import { Row } from "./Tag";
import { TEXT, type Text } from "./text";
import { Icon, PageHead, Problem, Sheet } from "./ui";

// Efter pappret (LOK-13, LOK-18, LOK-29, LOK-33; foto-saknas.jpg, papper.jpg): the driver whose
// service is not in the plan photographs the paper's pages, sees the price and who pays before
// anything is read, and the hub reads the timetable. The planned services nearest the paper's
// start come first (LF16): one of them may be it. Else the driver runs after the paper, and the
// körplan is marked so until Trafikledningen has decided.

/** The service run after the paper that the driver has now, waiting or approved. */
export function runningPaper(state: LokState): PaperService | null {
  const paper = state.me?.paper ?? null;
  return paper && state.me?.service?.service.kind === "paper" ? paper : null;
}

/** The time on the paper's front, or – when it could not be read: never guessed (LOK-29). */
function EndLine({ word, end, text }: { word: string; end: PaperEnd; text: Text }) {
  return (
    <p>
      {word} <b className="tm-mono">{end.time ?? "–"}</b>
      {!end.time && end.unreadable && <small className="lok-olaslig"> {text.unreadable}</small>} {end.place_name ? `${text.at} ${end.place_name}` : ""}
      {end.place_name && !end.place && <small className="lok-olaslig"> · {text.notInMeet}</small>}
    </p>
  );
}

/** The photos of the paper, small: tap one to see it large and compare it with what was read.
 * The hub gives each its own address; the service worker never keeps them (public/sw.js). */
export function PaperPhotos({ paper, text, label = true }: { paper: PaperService; text: Text; label?: boolean }) {
  const photos = photosOf(paper);
  const [open, setOpen] = useState<number | null>(null);
  if (!photos.length) return null;
  return (
    <div className="lok-foton">
      {label && <span className="lok-overrubrik">{text.yourPhotos}</span>}
      <ul>
        {photos.map((photo, index) => (
          <li key={photo}>
            <button type="button" className="lok-foto" onClick={() => setOpen(index)} aria-label={text.photoOf(index + 1, photos.length)}>
              <img src={photo} alt="" loading="lazy" referrerPolicy="no-referrer" />
            </button>
          </li>
        ))}
      </ul>
      {open !== null && photos[open] && (
        <Sheet title={text.photoOf(open + 1, photos.length)} onClose={() => setOpen(null)} text={text} closeLabel={text.close}>
          <img className="lok-foto-stor" src={photos[open]} alt={text.photoOf(open + 1, photos.length)} referrerPolicy="no-referrer" />
        </Sheet>
      )}
    </div>
  );
}

/** Where the paper stands with Trafikledningen: waiting, approved as a train, or rejected. */
export function paperStatusText(paper: Pick<PaperService, "status" | "train_number">, text: Text): string {
  return paper.status === "approved" && paper.train_number ? text.approvedAs(paper.train_number) : text.paperStatus[paper.status];
}

/** PÅ PAPPRET (foto-saknas.jpg): the front as the AI read it, beside the driver's photo. */
export function PaperFront({ paper, text }: { paper: PaperService; text: Text }) {
  const first = photosOf(paper)[0];
  return (
    <section className="lok-kort lok-pa-pappret" aria-label={text.onThePaper}>
      <span className="lok-ditt-foto">{first ? <img src={first} alt={text.page(1)} referrerPolicy="no-referrer" /> : Icon.camera}</span>
      <div>
        <p className="lok-overrubrik">{text.onThePaper}</p>
        <b className="lok-pa-pappret-nummer">{paper.number ? text.serviceNumber(paper.number) : text.numberUnread}</b>
        <EndLine word={text.starts} end={paper.start} text={text} />
        <EndLine word={text.ends} end={paper.end} text={text} />
        {(paper.operator || paper.train_number) && <p className="lok-mute">{[paper.operator, paper.train_number ? text.trainOnPaper(paper.train_number) : null].filter(Boolean).join(" · ")}</p>}
        <span className={`lok-papper-status ${paper.status}`}>
          {text.afterPaper} · {paperStatusText(paper, text)}
        </span>
      </div>
    </section>
  );
}

/** The hub's comparison with the plan, its first sentence in bold (foto-saknas.jpg). */
export function Said({ said }: { said: string }) {
  const at = said.search(/\.\s/);
  const first = at === -1 ? said : said.slice(0, at + 1);
  const rest = at === -1 ? "" : said.slice(at + 2);
  return (
    <p className="lok-varning">
      {Icon.warning}
      <span>
        <b>{first}</b>
        {rest ? ` ${rest}` : ""}
      </span>
    </p>
  );
}

/** Avslagen (LOK-13): Trafikledningen's reason, and another service to take. */
export function RejectedCard({ lok, state }: { lok: Lok; state: LokState }) {
  const paper = state.me?.paper;
  if (!paper || paper.status !== "rejected" || state.me?.service) return null;
  const text = TEXT[state.language];
  return (
    <section className="lok-utan-forare lok-avslagen" aria-label={text.paperStatus.rejected}>
      <p className="lok-overrubrik">
        {text.afterPaper} · {text.paperStatus.rejected}
      </p>
      <p>{text.rejectedBanner(paper.reason)}</p>
      {state.route !== "tag" && (
        <button type="button" className="lok-knapp primar" onClick={() => lok.navigate("tag")}>
          {text.chooseAnother}
        </button>
      )}
    </section>
  );
}

/** At the top of the körplan after the paper (papper.jpg): read from the photos and not in the
 * plan, where it stands with Trafikledningen, and the photos to compare with. */
export function PaperBanner({ state }: { state: LokState }) {
  const paper = runningPaper(state);
  if (!paper) return null;
  const text = TEXT[state.language];
  const approved = paper.status === "approved";
  return (
    <div className={`lok-papper-banner${approved ? " godkand" : ""}`} role="status">
      <p>
        {approved ? Icon.check : Icon.warning}
        <span>
          <b>{paperStatusText(paper, text)}.</b> {approved ? text.approvedNote : text.paperBanner}
        </span>
      </p>
      <PaperPhotos paper={paper} text={text} />
    </div>
  );
}

/** Läsningen (LOK-33, TOKEN-14): the price, who pays and the balance, before anything is read;
 * or why it cannot be read, and the login with TrainMeet ID when that would help. */
function PriceCard({ lok, state, text }: { lok: Lok; state: LokState; text: Text }) {
  const price = state.price;
  if (!price) return <p className="lok-not">{text.priceLoading}</p>;
  if (!price.ready) {
    return (
      <>
        <p className="lok-varning" role="alert">
          {Icon.warning}
          <span>{lok.priceProblem(price)}</span>
        </p>
        {lok.offersLogin(price) && (
          <a className="lok-knapp mjuk stor" href={idLoginAddress("/lokforaren/papper", state.language)}>
            {text.idLogin}
          </a>
        )}
      </>
    );
  }
  const pages = state.pages.length;
  const hub = price.paid_by === "hub";
  const free = price.price === 0;
  return (
    <section className="lok-kort lok-pris" aria-label={text.reading}>
      <div className="lok-pris-rad">
        <span className="lok-overrubrik">{text.reading}</span>
        {price.paid_by && <span className="lok-betalare">{text.paidBy[price.paid_by]}</span>}
      </div>
      <p className="lok-pris-summa">{free ? text.noTokens : pages ? text.tokens(price.price) : text.perPage(price.per_page)}</p>
      {hub ? <p>{text.ownAi}</p> : !free && pages > 0 && <p>{text.pagesPrice(pages, price.per_page)}</p>}
      {!hub && price.payer && <p>{[text.payer(price.payer), price.available !== null && price.available !== undefined ? text.left(price.available) : null].filter(Boolean).join(" · ")}</p>}
    </section>
  );
}

/** Fota pappret: 1–4 photos, the price, and Läs pappret. */
function PhotoStep({ lok, state }: { lok: Lok; state: LokState }) {
  const text = TEXT[state.language];
  const pages = state.pages;
  const busy = state.busy || state.reading;
  const choose = (event: ChangeEvent<HTMLInputElement>) => {
    const files = [...(event.target.files ?? [])];
    event.target.value = "";
    if (files.length) void lok.addPages(files);
  };
  if (state.me?.service) {
    return (
      <>
        <p className="lok-upplysning">{text.hasService}</p>
        <button type="button" className="lok-knapp primar stor" onClick={() => lok.navigate("korplan")}>
          {text.toKorplan}
        </button>
      </>
    );
  }
  const price = state.price;
  return (
    <>
      <p className="lok-not">{text.paperIntro}</p>
      <ul className="lok-sidor" aria-label={text.paperTitle}>
        {pages.map((page, index) => (
          <li key={page.preview + index}>
            <img src={page.preview} alt={text.page(index + 1)} />
            <span>{text.page(index + 1)}</span>
            <button type="button" className="lok-ta-bort" aria-label={text.removePage(index + 1)} disabled={busy} onClick={() => lok.removePage(index)}>
              {Icon.close}
            </button>
          </li>
        ))}
        {pages.length < PAPER_PAGES && (
          <li>
            <label className={`lok-ny-sida${busy ? " av" : ""}`}>
              {Icon.camera}
              <span>{pages.length ? text.addPage : text.takeFront}</span>
              <input className="lok-dold" type="file" accept="image/*" capture="environment" multiple disabled={busy} onChange={choose} />
            </label>
          </li>
        )}
      </ul>
      <p className="lok-not">{text.photosCleaned}</p>
      <PriceCard lok={lok} state={state} text={text} />
      <Problem text={state.problem} />
      {state.reading && (
        <p className="lok-upplysning" role="status" aria-live="polite">
          {text.readingNow}
        </p>
      )}
      {price?.ready && pages.length > 0 && (
        <button type="button" className="lok-knapp primar stor" disabled={busy} onClick={() => void lok.readPaper()}>
          {Icon.camera} {text.readPaper(price.price)}
        </button>
      )}
      <p className="lok-not">{text.readNote}</p>
    </>
  );
}

/** The paper beside the plan (LF16, foto-saknas.jpg): what was read, the hub's comparison and
 * the nearest planned services, any of which the driver may take instead; else Kör efter
 * pappret. Later the same page shows the paper, its photos and where it stands. */
function PaperResult({ lok, state, paper, now }: { lok: Lok; state: LokState; paper: PaperService; now: number | null }) {
  const text = TEXT[state.language];
  const waiting = paper.status === "waiting";
  const candidates = candidatesOf(paper);
  const choose = (offer: (typeof candidates)[number]) => {
    lok.paperHint(paper.number ?? null);
    lok.select(offer);
  };
  return (
    <>
      <Problem text={state.problem} />
      <PaperFront paper={paper} text={text} />
      {waiting && (
        <>
          <Said said={paper.said} />
          <h2 className="lok-avsnitt">{text.nearest}</h2>
          {candidates.length > 0 ? (
            <>
              <ul className="lok-lista lok-lista-ram">
                {candidates.map((offer) => (
                  <Row key={refKey(offer.service)} lok={lok} state={state} offer={offer} now={now} text={text} withStart onChoose={choose} />
                ))}
              </ul>
              <p className="lok-not">{text.nearestNote}</p>
            </>
          ) : (
            <p className="lok-not">{text.noNearest}</p>
          )}
        </>
      )}
      <PaperPhotos paper={paper} text={text} />
      <div className="lok-knappar staplade">
        <button type="button" className="lok-knapp primar stor" onClick={() => lok.navigate("korplan")}>
          {waiting ? text.runAfterPaper : text.toKorplan}
        </button>
        {waiting && (
          <button type="button" className="lok-knapp stor" onClick={() => lok.navigate("tag")}>
            {text.showList}
          </button>
        )}
      </div>
      {waiting && <p className="lok-not">{text.dispatchKnows}</p>}
    </>
  );
}

/** The page /lokforaren/papper: the photos and the price before reading, and after it the
 * paper beside the plan. */
export function PapperSida({ lok, state, now }: { lok: Lok; state: LokState; now: number | null }) {
  const text = TEXT[state.language];
  const paper = runningPaper(state);
  return (
    <main className="lok-sida" id="innehall">
      <PageHead title={paper ? text.paperResult : text.paperTitle} sub={state.meetName ?? ""} back onBack={() => lok.navigate(paper ? "korplan" : "tag")} backLabel={text.back} />
      {paper ? (
        <PaperResult lok={lok} state={state} paper={paper} now={now} />
      ) : (
        <>
          <RejectedCard lok={lok} state={state} />
          <PhotoStep lok={lok} state={state} />
        </>
      )}
    </main>
  );
}
