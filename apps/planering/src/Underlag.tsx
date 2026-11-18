import { useEffect, useRef, useState } from "react";
import { planning, type AiPages, type Draft, type ImportPreview } from "./api";
import { LEVELS, describePreview, plural } from "./data";

// Lägg till underlag (S6), opened from Data: drop or choose Tellurian's planning file (JSON) or
// the station lists. They are read with code, without AI, and nothing is put in before Lägg in
// i utkastet: first the level and exactly what changes in the draft. Lists added beside the
// planning file get a verdict each instead (IMPORT-27); without it they build the draft, with
// places, kinds and sections derived and osäkra (IMPORT-17).

type Read =
  | { name: string; state: "reading" }
  | { name: string; state: "read"; preview: ImportPreview; transcribed?: boolean }
  | { name: string; state: "ai"; pages: AiPages; file?: File }
  | { name: string; state: "writing"; pages: AiPages }
  | { name: string; state: "failed" };

const TAG: Record<string, string> = { planning_json: "JSON", station_lists: "ST", track_picture: "BILD", graph_picture: "GRAF", station_outside: "STN" };

export function readLine(preview: ImportPreview): string {
  const report = preview.report;
  const verdicts = report.verdicts ?? [];
  const lists = preview.source.kind === "station_lists";
  if (preview.source.kind === "track_picture" && !report.trains) return "Banbild · sparas som underlag";
  if (preview.source.kind === "graph_picture" && !report.trains) return "Graf · sparas som underlag";
  if (preview.source.kind === "station_outside") return "Stationens utsida · kopplas till en driftplats i Data";
  if (lists && verdicts.length) {
    const rows = verdicts.reduce((sum, verdict) => sum + verdict.rows, 0);
    return `Stationslistor · ${plural(verdicts.length, "lista", "listor")} · ${plural(rows, "tågbesök", "tågbesök")}`;
  }
  const places = Object.values(report.places ?? {}).reduce((sum, value) => sum + value, 0);
  const counts = `${plural(report.trains, "tåg", "tåg")} · ${plural(places, "driftplats", "driftplatser")} · ${plural(report.sections, "sträcka", "sträckor")}`;
  if (preview.source.kind === "track_picture") return `Banbild och stationslistor · ${counts}`;
  if (preview.source.kind === "graph_picture") return `Graf och stationslistor · ${counts}`;
  return lists ? `Stationslistor · ${counts}, härledda` : `Tellurians plan · ${counts}`;
}

export function Underlag({ meet, onClose, onApplied, onFail, initial }: { meet: string; onClose: () => void; onApplied: (draft: Draft) => void; onFail?: (error: unknown) => void; initial?: Read }) {
  const [read, setRead] = useState<Read | null>(initial ?? null);
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  const panel = useRef<HTMLDivElement>(null);
  // A failure is said in the panel too, where the planner is looking.
  const failed = (error: unknown) => {
    setProblem(error instanceof Error ? error.message : "Det gick inte.");
    onFail?.(error);
  };

  useEffect(() => {
    panel.current?.focus();
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const take = async (file: File | undefined) => {
    if (!file) return;
    setRead({ name: file.name, state: "reading" });
    setProblem("");
    try {
      const answer = await planning.read(meet, file);
      setRead("pages" in answer ? { name: file.name, state: "ai", pages: answer.pages, file } : { name: file.name, state: "read", preview: answer.preview });
    } catch (error) {
      setRead({ name: file.name, state: "failed" });
      failed(error);
    }
  };

  // Skriv av (IMPORT-05): only now does anything go to the AI, as lists or as the track picture.
  const transcribe = async (kind: "lists" | "picture" | "graph", by: AiBy) => {
    if (read?.state !== "ai" || !read.file) return;
    const { name, pages, file } = read;
    setRead({ name, state: "writing", pages });
    setProblem("");
    try {
      const answer = await planning.read(meet, file, kind, by);
      setRead("pages" in answer ? { name, state: "ai", pages: answer.pages, file } : { name, state: "read", preview: answer.preview, transcribed: true });
    } catch (error) {
      setRead({ name, state: "ai", pages, file });
      failed(error);
    }
  };

  const apply = async () => {
    if (read?.state !== "read") return;
    setBusy(true);
    setProblem("");
    try {
      onApplied(await planning.apply(meet, read.preview.source.id));
    } catch (error) {
      failed(error);
    }
    setBusy(false);
  };

  const preview = read?.state === "read" ? read.preview : null;
  return (
    <div id="drawer" className="lada">
      <div className="lada-bakgrund" onClick={onClose} />
      <div className="lada-panel" role="dialog" aria-modal="true" aria-labelledby="drawer-title" tabIndex={-1} ref={panel}>
        <header>
          <h2 id="drawer-title">Lägg till underlag</h2>
          <button type="button" className="ikon" aria-label="Stäng" onClick={onClose}>
            ×
          </button>
        </header>
        <div className="lada-innehall">
          <label
            className={"slapp" + (over ? " over" : "")}
            id="drop"
            onDragOver={(event) => {
              event.preventDefault();
              setOver(true);
            }}
            onDragLeave={() => setOver(false)}
            onDrop={(event) => {
              event.preventDefault();
              setOver(false);
              void take(event.dataTransfer.files[0]);
            }}
          >
            <input id="file" type="file" accept=".json,.gz,application/json,.odt,.zip,.xlsx,.csv,.pdf,application/pdf,.jpg,.jpeg,.png,image/jpeg,image/png" className="osynlig" onChange={(event) => (void take(event.target.files?.[0]), (event.target.value = ""))} />
            <b>Släpp filen här</b>
            <span>eller välj den. Tellurians planeringsfil (JSON), stationslistorna (ODT, ZIP, Excel, CSV eller PDF) eller banbilden, sidan Topologi i Tellurians PDF. Utan planeringsfilen bygger listorna utkastet och banbilden bekräftar banan. Skannade listor, foton av banan och grafen som bild (JPEG eller PNG) skrivs av med hubbens egna AI.</span>
          </label>
          {read && (
            <ul id="files" className="filer">
              <li>
                <span className="kalla">{read.state === "read" ? TAG[read.preview.source.kind] : /\.(odt|zip|xlsx|csv|pdf|jpe?g|png)$/i.test(read.name) ? "ST" : "JSON"}</span>
                <div>
                  <b>{read.name}</b>
                  <div className="liten">{preview ? readLine(preview) : read.state === "ai" || read.state === "writing" ? "Skannad · skrivs av med AI" : "Tellurians plan"}</div>
                </div>
                {read.state === "reading" && <span className="pill likely">Läser …</span>}
                {read.state === "ai" && <span className="pill unsure">Behöver AI</span>}
                {read.state === "writing" && <span className="pill likely">Skriver av …</span>}
                {read.state === "read" && <span className="pill sure">Läst</span>}
                {read.state === "failed" && <span className="pill conflict">Gick inte</span>}
              </li>
            </ul>
          )}
          {problem && (
            <p id="drawer-problem" className="problem" role="alert">
              {problem}
            </p>
          )}
          {preview && (
            <div id="preview">
              <p className="overrubrik">Underlagets nivå</p>
              <div id="levels" className="nivaer">
                {LEVELS.map(([step, name]) => (
                  <div key={step} className={step <= preview.report.level ? "fylld" : undefined}>
                    <i />
                    {`${step} ${name}`}
                  </div>
                ))}
              </div>
              {preview.source.kind === "station_lists" && preview.report.verdicts?.length ? (
                <Domar preview={preview} text="Utkastet ändras inte. Varje lista får en dom, rad för rad (IMPORT-27)." />
              ) : (
                <div className="andras">
                  <b>Det här ändras i utkastet</b>
                  <p id="changes">{describePreview(preview)}</p>
                  {preview.source.kind === "station_lists" ? (
                    <p className="liten" id="derived">
                      Härlett ur listorna: platstyperna och sträckorna är osäkra tills du bekräftar dem i Bana. Banbilden, grafen eller planeringsfilen höjer nivån.
                    </p>
                  ) : preview.source.kind === "track_picture" || preview.source.kind === "graph_picture" || preview.source.kind === "station_outside" ? (
                    <p className="liten" id="derived">
                      {preview.report.notes?.[0] ?? "Banbilden sparas som underlag."}
                    </p>
                  ) : (
                    <p className="liten">Allt får källa och säkerhet och syns som kolumner i Data.</p>
                  )}
                </div>
              )}
              {preview.source.kind !== "station_lists" && preview.report.verdicts?.length ? (
                <Domar preview={preview} text="Stationslistorna som redan är underlag får en dom var, rad för rad, mot planeringsfilen (IMPORT-27)." />
              ) : null}
              {read?.state === "read" && read.transcribed ? (
                <div className="kostnad">
                  <b>Egen AI</b>
                  <span>Skrivet av hubbens egna AI och läst med kod. Allt är osäkert tills du bekräftar det.</span>
                </div>
              ) : (
                <div className="kostnad">
                  <b>Ingen AI</b>
                  <span>Filen läses med kod. Inga tokens.</span>
                </div>
              )}
            </div>
          )}
          {(read?.state === "ai" || read?.state === "writing") && <Skriv pages={read.pages} writing={read.state === "writing"} onWrite={(kind, by) => void transcribe(kind, by)} />}
        </div>
        <footer>
          <button id="apply" type="button" className="primar" disabled={!preview || busy} onClick={() => void apply()}>
            Lägg in i utkastet
          </button>
          <button type="button" className="lank" onClick={onClose}>
            Avbryt
          </button>
        </footer>
      </div>
    </div>
  );
}

function Domar({ preview, text }: { preview: ImportPreview; text: string }) {
  return (
    <div className="andras" id="verdicts">
      <b>Stationslistorna prövade mot planeringsfilen</b>
      <p className="liten">{text}</p>
      <ul className="domar">
        {(preview.report.verdicts ?? []).map((verdict) => (
          <li key={verdict.document}>
            <span className={`pill ${verdict.differences?.length ? "conflict" : "sure"}`}>{verdict.differences?.length ? "Skiljer" : "Stämmer"}</span>
            <span>
              <b>{verdict.document}</b>
              <span className="liten">{` · ${verdict.agreeing} av ${verdict.rows} tågbesök stämmer`}</span>
              {(verdict.differences ?? []).slice(0, 5).map((difference) => (
                <span key={difference} className="liten skillnad">
                  {difference}
                </span>
              ))}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}


/** Sidor att skriva av (IMPORT-05): what the scanned file needs, before anything goes to the AI. */
type Avskrift = "lists" | "picture" | "graph";
/** Who writes it down: the hub's own AI, or TrainMeets AI through the meter in ID (#79). */
export type AiBy = "own" | "trainmeet";

/** 12 400 as Swedish writes it, with a space that does not break. */
const thousands = (n: number) => String(n).replace(/\B(?=(\d{3})+(?!\d))/g, "\u00a0");

export function Skriv({ pages, writing, onWrite }: { pages: AiPages; writing: boolean; onWrite: (kind: Avskrift, by: AiBy) => void }) {
  const left = pages.pages - pages.saved;
  const [chosen, setChosen] = useState<Avskrift>("lists");
  // Egen AI is the first choice; TrainMeets AI is chosen by the planner, after being told
  // where the pages go and who pays (TK12, TK16).
  const offer = pages.trainmeet_ai ?? null;
  const enough = offer !== null && offer.available >= offer.price;
  const [by, setBy] = useState<AiBy | null>(pages.model ? "own" : null);
  const ready = !left || (by === "own" && Boolean(pages.model)) || (by === "trainmeet" && enough);
  const write = (kind: Avskrift) => {
    setChosen(kind);
    onWrite(kind, by ?? "own");
  };
  const label = (kind: Avskrift, text: string) => (writing && chosen === kind ? "Skriver av …" : text);
  return (
    <div id="ai-pages">
      <div className="andras">
        <b>Filen är skannad och behöver AI</b>
        <p id="ai-count">
          {`${plural(pages.pages, "sida", "sidor")} att skriva av`}
          {pages.tokens ? ` · cirka ${thousands(pages.tokens)} tokens` : ""}
          {pages.saved ? ` · ${plural(pages.saved, "redan avskriven", "redan avskrivna")}, kostar inget` : ""}
        </p>
        <p className="liten">AI:n skriver bara av vad som står, och koden läser det. Allt blir osäkert tills du bekräftar det. Välj vad filen är: en stationslista (det som står om fordonen i tåget skrivs inte av), en bild av banan, som blir bakgrunden i Bana, eller grafen, där linjernas stationer skrivs av.</p>
      </div>
      <div className="kostnad">
        {offer && left ? (
          <label className="val">
            <input type="radio" name="ai-by" value="own" checked={by === "own"} disabled={!pages.model} onChange={() => setBy("own")} /> <b>Egen AI</b>
          </label>
        ) : (
          <b>Egen AI</b>
        )}
        {pages.model ? (
          <span>{left ? `${plural(left, "sida", "sidor")} betalas av din AI-tjänst (${pages.model}).` : "Allt är redan avskrivet. Inget skickas till AI:n."}</span>
        ) : (
          <span>
            Ingen egen AI är inkopplad än. Koppla in den under{" "}
            <a href="/installningar#ai" className="understruken">
              Inställningar → Den här hubben → AI
            </a>{" "}
            och tryck sedan Skriv av.
          </span>
        )}
      </div>
      {offer && left ? (
        <div className="kostnad" id="trainmeet-ai">
          <label className="val">
            <input type="radio" name="ai-by" value="trainmeet" checked={by === "trainmeet"} disabled={!enough} onChange={() => setBy("trainmeet")} />{" "}
            <b>{offer.own_ai ? "Egen AI på kontot" : "TrainMeets AI"}</b>
          </label>
          <span>
            {offer.own_ai
              ? `Sidorna läses av den egna AI:n som ${offer.payer} har kopplat in i TrainMeet ID (${offer.own_ai}). Inga tokens dras.`
              : `Sidorna läses av ${offer.where}. ${thousands(offer.price)} tokens dras från ${offer.payer}, som har ${thousands(offer.available)} kvar.`}
          </span>
          {enough ? null : <span className="liten">Saldot räcker inte. Köp fler tokens i TrainMeet ID, eller koppla in egen AI.</span>}
        </div>
      ) : null}
      <div className="knapprad">
        <button type="button" id="transcribe" className="primar" disabled={writing || !ready} onClick={() => write("lists")}>
          {label("lists", left ? `Skriv av ${plural(left, "sida", "sidor")} som stationslista` : "Läs avskriften")}
        </button>
        <button type="button" id="transcribe-picture" className="sekundar" disabled={writing || !ready} onClick={() => write("picture")}>
          {label("picture", "Skriv av som banbild")}
        </button>
        <button type="button" id="transcribe-graph" className="sekundar" disabled={writing || !ready} onClick={() => write("graph")}>
          {label("graph", "Skriv av som graf")}
        </button>
      </div>
    </div>
  );
}
