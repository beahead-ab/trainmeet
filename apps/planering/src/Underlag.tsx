import { useEffect, useRef, useState } from "react";
import { planning, type Draft, type ImportPreview } from "./api";
import { LEVELS, describePreview, plural } from "./data";

// Lägg till underlag (S6), opened from Data: drop or choose Tellurian's planning file (JSON). It
// is read with code, without AI, and nothing is put in before Lägg in i utkastet: first the
// level and exactly what changes in the draft.

type Read = { name: string; state: "reading" } | { name: string; state: "read"; preview: ImportPreview } | { name: string; state: "failed" };

export function readLine(preview: ImportPreview): string {
  const report = preview.report;
  if (preview.source.kind === "station_lists") {
    const verdicts = report.verdicts ?? [];
    const rows = verdicts.reduce((sum, verdict) => sum + verdict.rows, 0);
    return `Stationslistor · ${plural(verdicts.length, "lista", "listor")} · ${plural(rows, "tågbesök", "tågbesök")}`;
  }
  const places = Object.values(report.places ?? {}).reduce((sum, value) => sum + value, 0);
  return `Tellurians plan · ${plural(report.trains, "tåg", "tåg")} · ${plural(places, "driftplats", "driftplatser")} · ${plural(report.sections, "sträcka", "sträckor")}`;
}

export function Underlag({ meet, onClose, onApplied, onFail, initial }: { meet: string; onClose: () => void; onApplied: (draft: Draft) => void; onFail?: (error: unknown) => void; initial?: Read }) {
  const [read, setRead] = useState<Read | null>(initial ?? null);
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState(false);
  const panel = useRef<HTMLDivElement>(null);

  useEffect(() => {
    panel.current?.focus();
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const take = async (file: File | undefined) => {
    if (!file) return;
    setRead({ name: file.name, state: "reading" });
    try {
      setRead({ name: file.name, state: "read", preview: await planning.read(meet, file) });
    } catch (error) {
      setRead({ name: file.name, state: "failed" });
      onFail?.(error);
    }
  };

  const apply = async () => {
    if (read?.state !== "read") return;
    setBusy(true);
    try {
      onApplied(await planning.apply(meet, read.preview.source.id));
    } catch (error) {
      onFail?.(error);
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
            <input id="file" type="file" accept=".json,.gz,application/json,.odt,.zip,.xlsx,.csv" className="osynlig" onChange={(event) => void take(event.target.files?.[0])} />
            <b>Släpp filen här</b>
            <span>eller välj den. Tellurians planeringsfil (JSON), eller stationslistorna (ODT, ZIP, Excel eller CSV), som prövas mot planeringsfilen. Grafen och en bild av banan kommer i nästa del (4c).</span>
          </label>
          {read && (
            <ul id="files" className="filer">
              <li>
                <span className="kalla">{/\.(odt|zip|xlsx|csv)$/i.test(read.name) ? "ST" : "JSON"}</span>
                <div>
                  <b>{read.name}</b>
                  <div className="liten">{preview ? readLine(preview) : "Tellurians plan"}</div>
                </div>
                {read.state === "reading" && <span className="pill likely">Läser …</span>}
                {read.state === "read" && <span className="pill sure">Läst</span>}
                {read.state === "failed" && <span className="pill conflict">Gick inte</span>}
              </li>
            </ul>
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
              {preview.source.kind === "station_lists" ? (
                <div className="andras" id="verdicts">
                  <b>Stationslistorna prövade mot planeringsfilen</b>
                  <p className="liten">Utkastet ändras inte. Varje lista får en dom, rad för rad (IMPORT-27).</p>
                  <ul className="domar">
                    {(preview.report.verdicts ?? []).map((verdict) => (
                      <li key={verdict.document}>
                        <span className={`pill ${verdict.differences?.length ? "conflict" : "sure"}`}>{verdict.differences?.length ? "Skiljer" : "Stämmer"}</span>
                        <span>
                          <b>{verdict.document}</b>
                          <span className="liten">{` · ${verdict.agreeing} av ${verdict.rows} tågbesök stämmer`}</span>
                          {(verdict.differences ?? []).slice(0, 5).map((text) => (
                            <span key={text} className="liten skillnad">
                              {text}
                            </span>
                          ))}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : (
                <div className="andras">
                  <b>Det här ändras i utkastet</b>
                  <p id="changes">{describePreview(preview)}</p>
                  <p className="liten">Allt får källa och säkerhet och syns som kolumner i Data.</p>
                </div>
              )}
              <div className="kostnad">
                <b>Ingen AI</b>
                <span>Filen läses med kod. Inga tokens.</span>
              </div>
            </div>
          )}
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
