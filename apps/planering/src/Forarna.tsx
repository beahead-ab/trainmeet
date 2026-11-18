import { useEffect, useState, type FormEvent } from "react";
import { planning, type Draft, type PaperReadingPayer, type PaperReadingSettings } from "./api";
import type { Duty, Package } from "./data";

// Förarna (PLAN-40, LOK-34, LF21): the duties per driver level, as the papers' fronts say it,
// and the general instructions the duties refer to, as text or as a PDF. They are kept in the
// meet package, the text in the package's about and the PDF as its attachment, and go with the
// next version to Drift, where Lokföraren shows what there is. And the meet's choice of whose
// tokens read a duty a driver photographs because it is missing from the plan (LOK-33): the
// meet's or the driver's own, kept in the hub, not in the package. Swedish and English (ST10).

export type Language = "sv" | "en";

export const LEVELS: [string, Record<Language, string>][] = [
  ["easy", { sv: "Lätt", en: "Easy" }],
  ["medium", { sv: "Medel", en: "Medium" }],
  ["experienced", { sv: "Erfaren", en: "Experienced" }],
  ["", { sv: "Utan svårighet", en: "No difficulty" }],
];

export const TEXT = {
  sv: {
    title: "Förarna",
    under: "köruppdragen per nivå och de allmänna instruktionerna",
    empty: "Lägg till underlag i Data först.",
    duties: "Köruppdragen per nivå",
    dutiesNote: "Föraren anger sin nivå i Lokföraren, och listan visar de passande först (LOK-32).",
    none: "Träffen har inga köruppdrag. Förarna väljer då ett tåg och kör efter tidtabellen.",
    count: (count: number) => (count === 1 ? "1 köruppdrag" : `${count} köruppdrag`),
    instructions: "De allmänna instruktionerna",
    instructionsNote: "Det köruppdragen hänvisar till. Text eller PDF, eller båda. De följer med nästa version till Lokföraren.",
    language: "Språk",
    languages: { sv: "Svenska", en: "Engelska" } as Record<string, string>,
    text: "Instruktionerna som text",
    save: "Spara texten",
    saved: "Instruktionerna är sparade i utkastet. De följer med nästa version.",
    pdf: "Instruktionerna som PDF",
    noPdf: "Ingen PDF är inlagd.",
    upload: "Lägg in PDF",
    replace: "Byt PDF",
    remove: "Ta bort PDF:en",
    show: "Visa",
    readOnly: "Bara arrangören ändrar instruktionerna.",
    pdfSaved: "PDF:en är inlagd i utkastet.",
    pdfRemoved: "PDF:en är borttagen ur utkastet.",
    size: (kilobytes: number) => `${kilobytes} kB`,
    paper: "När en förare fotar ett köruppdrag",
    paperNote: "Saknas tjänsten i planen läser Lokföraren tidtabellen ur förarens foton. AI-läsningen kostar tokens. Välj vem som står för dem på den här träffen.",
    paperLegend: "AI-läsning av köruppdrag som saknas",
    meetTokens: "Träffens tokens",
    meetTokensNote: "Föraren behöver inget konto. Väljs inloggad med TrainMeet ID: klubben betalar för en träff i ID.",
    driverTokens: "Förarens egna tokens",
    driverTokensNote: "Kräver att föraren har TrainMeet ID. Förval.",
    balance: (title: string, available: number) => `${title} har ${available} tokens kvar.`,
    price: (perPage: number) => `En läsning kostar ${perPage} tokens per sida, så fyra sidor kostar ${perPage * 4}.`,
    ownAi: (model: string) => `Hubben har egen AI (${model}): den läser fotona utan tokens.`,
    noAi: "Hubben har ingen egen AI och når inte TrainMeets AI. Förarna kan inte få pappret läst här.",
    paperSaved: (meet: boolean): string => (meet ? "Träffens tokens läser fotade köruppdrag." : "Förarens egna tokens läser fotade köruppdrag."),
    paperReadOnly: "Bara arrangören ändrar valet.",
  },
  en: {
    title: "Drivers",
    under: "the duties by level and the general instructions",
    empty: "Add a source in Data first.",
    duties: "The duties by level",
    dutiesNote: "The driver gives a level in Lokföraren, and the list shows the fitting duties first (LOK-32).",
    none: "The meet has no duties. The drivers then choose a train and drive by the timetable.",
    count: (count: number) => (count === 1 ? "1 duty" : `${count} duties`),
    instructions: "The general instructions",
    instructionsNote: "What the duties refer to. Text or PDF, or both. They go with the next version to Lokföraren.",
    language: "Language",
    languages: { sv: "Swedish", en: "English" } as Record<string, string>,
    text: "The instructions as text",
    save: "Save the text",
    saved: "The instructions are saved in the draft. They go with the next version.",
    pdf: "The instructions as PDF",
    noPdf: "No PDF is added.",
    upload: "Add PDF",
    replace: "Replace PDF",
    remove: "Remove the PDF",
    show: "Show",
    readOnly: "Only the organiser changes the instructions.",
    pdfSaved: "The PDF is added to the draft.",
    pdfRemoved: "The PDF is removed from the draft.",
    size: (kilobytes: number) => `${kilobytes} kB`,
    paper: "When a driver photographs a duty",
    paperNote: "When the service is missing from the plan, Lokföraren reads the timetable from the driver's photos. The AI reading costs tokens. Choose who pays for them at this meet.",
    paperLegend: "AI reading of missing duties",
    meetTokens: "The meet's tokens",
    meetTokensNote: "The driver needs no account. Chosen logged in with TrainMeet ID: the club pays for a meet in ID.",
    driverTokens: "The driver's own tokens",
    driverTokensNote: "The driver needs TrainMeet ID. The default.",
    balance: (title: string, available: number) => `${title} has ${available} tokens left.`,
    price: (perPage: number) => `A reading costs ${perPage} tokens a page, so four pages cost ${perPage * 4}.`,
    ownAi: (model: string) => `The hub has its own AI (${model}): it reads the photos without tokens.`,
    noAi: "The hub has no AI of its own and does not reach TrainMeets AI. The drivers cannot have a paper read here.",
    paperSaved: (meet: boolean): string => (meet ? "The meet's tokens read photographed duties." : "The driver's own tokens read photographed duties."),
    paperReadOnly: "Only the organiser changes the choice.",
  },
};

type Text = (typeof TEXT)["sv"];

/** A duty as the paper's front says it: start and end with time and place, and the trains. */
export function dutyFront(duty: Duty, pkg: Package): string {
  const trains = new Map((pkg.trains ?? []).map((train) => [train.id, train]));
  const places = new Map((pkg.places ?? []).map((place) => [place.id, place.name]));
  const legs = duty.legs ?? [];
  const first = legs[0];
  const last = legs.at(-1);
  const call = (train: string | undefined, id: string | undefined) => trains.get(train ?? "")?.calls.find((found) => found.id === id);
  const start = first ? call(first.train, first.from_call) : undefined;
  const end = last ? call(last.train, last.to_call) : undefined;
  const numbers = [...new Set(legs.map((leg) => trains.get(leg.train)?.number ?? leg.train))].join(", ");
  const at = (found: typeof start, arrival: boolean) => (found ? `${(arrival ? (found.arrival ?? found.departure) : (found.departure ?? found.arrival)) ?? ""} ${places.get(found.place) ?? found.place}`.trim() : "");
  return `${at(start, false)} – ${at(end, true)} · ${numbers}`;
}

/** The duties by level, in the order Lätt, Medel, Erfaren and those without one. */
export function byLevel(pkg: Package): [string, Duty[]][] {
  const duties = pkg.duties ?? [];
  return LEVELS.map(([level]) => [level, duties.filter((duty) => (duty.level ?? "") === level)] as [string, Duty[]]).filter(([, found]) => found.length > 0);
}

export type ForarnaProps = {
  admin: boolean;
  meet: string;
  draft: Draft | null;
  language?: Language;
  onDraft: (draft: Draft) => void;
  onTell: (text: string, good?: boolean) => void;
  onFail: (error: unknown) => void;
  /** Given in tests; the page reads it from the hub itself. */
  paperReading?: PaperReadingSettings | null;
};

export function ForarnaPage({ admin, meet, draft, language = "sv", onDraft, onTell, onFail, paperReading = null }: ForarnaProps) {
  const text: Text = TEXT[language];
  const [reading, setReading] = useState<PaperReadingSettings | null>(paperReading);
  useEffect(() => {
    if (paperReading) return;
    let current = true;
    planning.paperReading(meet).then(
      (found) => current && setReading(found),
      () => current && setReading(null),
    );
    return () => {
      current = false;
    };
  }, [meet, paperReading]);
  const choose = async (payer: PaperReadingPayer) => {
    try {
      setReading(await planning.choosePaperReading(meet, payer));
      onTell(text.paperSaved(payer === "meet"), true);
    } catch (error) {
      onFail(error);
    }
  };
  const pkg = draft?.package ?? null;
  const [lang, setLang] = useState<Language>("sv");
  const kept = pkg?.about?.[lang]?.instructions ?? "";
  const [written, setWritten] = useState(kept);
  useEffect(() => setWritten(kept), [kept]);
  const pdf = (pkg?.attachments ?? []).find((attachment) => attachment.kind === "instructions") ?? null;

  const save = async (event: FormEvent) => {
    event.preventDefault();
    if (!draft) return;
    try {
      onDraft(await planning.change(meet, { revision: draft.revision ?? 0, changes: [{ instructions: "text", language: lang, text: written.trim() || null, pdf: null }] }));
      onTell(text.saved, true);
    } catch (error) {
      onFail(error);
    }
  };
  const upload = async (file: File | undefined) => {
    if (!file) return;
    try {
      onDraft(await planning.instructionsPdf(meet, file));
      onTell(text.pdfSaved, true);
    } catch (error) {
      onFail(error);
    }
  };
  const remove = async () => {
    if (!draft) return;
    try {
      onDraft(await planning.change(meet, { revision: draft.revision ?? 0, changes: [{ instructions: "pdf", language: "sv", text: null, pdf: null }] }));
      onTell(text.pdfRemoved, true);
    } catch (error) {
      onFail(error);
    }
  };

  return (
    <>
      <div className="sidrubrik">
        <div>
          {draft && <p className="overrubrik">{draft.meet.name}</p>}
          <h1>{text.title}</h1>
        </div>
        <span className="under">{text.under}</span>
      </div>
      {!pkg ? (
        <section className="kort">
          <p>{text.empty}</p>
        </section>
      ) : (
        <>
          <section id="forarna-nivaer" className="kort" aria-labelledby="nivaer-rubrik">
            <h2 id="nivaer-rubrik">{text.duties}</h2>
            <p className="liten">{text.dutiesNote}</p>
            {(pkg.duties ?? []).length === 0 ? (
              <p className="tom">{text.none}</p>
            ) : (
              byLevel(pkg).map(([level, duties]) => (
                <details key={level || "none"} className="niva" open={duties.length <= 12}>
                  <summary>
                    <b>{LEVELS.find(([key]) => key === level)?.[1][language] ?? level}</b> <span className="liten">{text.count(duties.length)}</span>
                  </summary>
                  <ul className="lista">
                    {duties.map((duty) => (
                      <li key={duty.id}>
                        <b>{duty.name}</b> <span className="liten">{dutyFront(duty, pkg)}</span>
                      </li>
                    ))}
                  </ul>
                </details>
              ))
            )}
          </section>
          {reading && <PaperReading reading={reading} text={text} onChoose={(payer) => void choose(payer)} />}
          <section id="forarna-instruktioner" className="kort" aria-labelledby="instruktioner-rubrik">
            <h2 id="instruktioner-rubrik">{text.instructions}</h2>
            <p className="liten">{admin ? text.instructionsNote : text.readOnly}</p>
            <form onSubmit={(event) => void save(event)}>
              <label>
                {text.language}{" "}
                <select value={lang} onChange={(event) => setLang(event.target.value as Language)}>
                  {(["sv", "en"] as Language[]).map((key) => (
                    <option key={key} value={key}>
                      {text.languages[key]}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block">
                {text.text}
                <textarea id="instruktioner-text" rows={10} maxLength={20000} value={written} readOnly={!admin} onChange={(event) => setWritten(event.target.value)} />
              </label>
              {admin && (
                <button type="submit" className="tm-knapp primar" disabled={written === kept}>
                  {text.save}
                </button>
              )}
            </form>
            <h3>{text.pdf}</h3>
            {pdf ? (
              <p id="instruktioner-pdf">
                <a href={`/api/planering/1/meets/${encodeURIComponent(meet)}/attachments/${encodeURIComponent(pdf.id)}`} target="_blank" rel="noreferrer">
                  {`${text.show} ${pdf.filename}`}
                </a>{" "}
                <span className="liten">{text.size(Math.max(1, Math.round(pdf.size / 1024)))}</span>
              </p>
            ) : (
              <p className="tom">{text.noPdf}</p>
            )}
            {admin && (
              <div className="rad">
                <label className="tm-knapp">
                  {pdf ? text.replace : text.upload}
                  <input type="file" accept="application/pdf,.pdf" className="osynlig" onChange={(event) => void upload(event.target.files?.[0])} />
                </label>
                {pdf && (
                  <button type="button" className="fara" onClick={() => void remove()}>
                    {text.remove}
                  </button>
                )}
              </div>
            )}
          </section>
        </>
      )}
    </>
  );
}

/** Vem står för AI-läsningen (LOK-33, PLAN-40): the meet's tokens or the driver's own, the
 * driver's by default. The hub's own AI reads without tokens whichever is chosen (TOKEN-13). */
export function PaperReading({ reading, text, onChoose }: { reading: PaperReadingSettings; text: Text; onChoose: (payer: PaperReadingPayer) => void }) {
  const option = (payer: PaperReadingPayer, label: string, note: string) => (
    <label className="val">
      <input type="radio" name="vem-betalar" value={payer} checked={reading.payer === payer} disabled={!reading.may_change} onChange={() => onChoose(payer)} />{" "}
      <span>
        <b>{label}</b> <span className="liten">{note}</span>
      </span>
    </label>
  );
  return (
    <section id="forarna-papper" className="kort" aria-labelledby="papper-rubrik">
      <h2 id="papper-rubrik">{text.paper}</h2>
      <p className="liten">{text.paperNote}</p>
      <fieldset>
        <legend>{text.paperLegend}</legend>
        {option("meet", text.meetTokens, text.meetTokensNote)}
        {option("driver", text.driverTokens, text.driverTokensNote)}
      </fieldset>
      {reading.payer === "meet" && reading.payer_title && reading.available != null && <p className="liten">{text.balance(reading.payer_title, reading.available)}</p>}
      <p className="liten">{text.price(reading.per_page)}</p>
      {reading.own_ai ? <p className="liten">{text.ownAi(reading.own_ai)}</p> : !reading.trainmeet_ai && <p className="liten">{text.noAi}</p>}
      {!reading.may_change && <p className="liten">{text.paperReadOnly}</p>}
    </section>
  );
}
