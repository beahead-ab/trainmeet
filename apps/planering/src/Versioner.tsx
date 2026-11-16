import { changeText } from "@trainmeet/hubben";
import { Fragment, useState, type ReactNode } from "react";
import type { Check, Deviation, Draft, DoubleTrackQuestion, Proposal, Version } from "./api";
import { days } from "./data";
import { when } from "./text";

// Versioner (S6): the traffic check, Publicera for the administrator, the proposals from Drift
// with Ta med and Avslå (PLAN-03, 4.4), and the versions, which never change and are never
// removed. Kör i Drift opens Byt träff with the version (TRAFIK-29). Dra tillbaka (PLAN-18,
// F21) keeps the version but it can no longer be started or switched to; a meet that runs it
// goes on, with a warning in Nu (H68).

export type VersionerProps = {
  admin: boolean;
  meet: string;
  draft: Draft | null;
  check: Check | null;
  versions: Version[] | null;
  busy?: boolean;
  onPublish?: () => void;
  /** Förslag från Drift, newest first. */
  proposals?: Proposal[] | null;
  onTake?: (id: string) => void;
  onReject?: (id: string) => void;
  onWithdraw?: (number: number) => void;
  /** Dubbelspårsfrågan (PLAN-35): Ja or Nej for a single-track section. */
  onDoubleTrack?: (question: DoubleTrackQuestion, double: boolean) => void;
  /** Rimlighetskontrollen (PLAN-36): Låt stå and Ta tillbaka. */
  onLetStand?: (deviation: Deviation) => void;
  onTakeBack?: (deviation: Deviation) => void;
};

export function VersionerPage({ admin, meet, draft, check, versions, busy = false, onPublish, proposals = null, onTake, onReject, onWithdraw, onDoubleTrack, onLetStand, onTakeBack }: VersionerProps) {
  const [asking, setAsking] = useState<number | null>(null);
  const next = (versions?.at(-1)?.number ?? 0) + 1;
  const planned = Boolean(draft?.package);
  const findings = check?.findings ?? [];
  const blocking = check?.blocking ?? [];
  const questions = check?.double_track ?? [];
  return (
    <>
      <div className="sidrubrik">
        <div>
          {draft && <p className="overrubrik">{draft.meet.name}</p>}
          <h1>Versioner</h1>
        </div>
        <span className="under">trafikkontrollen och det som publicerats</span>
      </div>
      <section className="kort" aria-labelledby="kontroll-rubrik">
        <h2 id="kontroll-rubrik">Trafikkontroll</h2>
        <p className="liten">Fynden följer med versionen. De stoppar inte publiceringen; det gör bara fel i strukturen.</p>
        {planned && blocking.length > 0 && (
          <ul id="blocking" className="fynd">
            {blocking.map((text) => (
              <li key={text}>
                <span className="pill conflict">Stoppar</span>
                <span>{text}</span>
              </li>
            ))}
          </ul>
        )}
        {planned && questions.length > 0 && (
          <ul id="double-track" className="fynd">
            {questions.map((question) => (
              <li key={question.section}>
                <span className="pill question">Fråga</span>
                <span>{question.message}</span>
                {admin && (
                  <span className="rad svar">
                    <button type="button" disabled={busy} onClick={() => onDoubleTrack?.(question, true)}>
                      Ja, dubbelspår
                    </button>
                    <button type="button" disabled={busy} onClick={() => onDoubleTrack?.(question, false)}>
                      Nej
                    </button>
                  </span>
                )}
              </li>
            ))}
          </ul>
        )}
        <ul id="findings" className="fynd">
          {!draft || !check ? (
            <li className="tom">Kontrollerar …</li>
          ) : !planned ? (
            <li className="tom">Lägg till underlag under Data först.</li>
          ) : findings.length ? (
            findings.map((finding) => (
              <li key={finding.id}>
                <span className={`pill ${finding.severity}`}>{finding.severity === "conflict" ? "Konflikt" : "Iakttagelse"}</span>
                <span>{finding.message}</span>
              </li>
            ))
          ) : (
            <li className="tom">Inga fynd.</li>
          )}
        </ul>
        {admin && (
          <div className="rad">
            <button id="publish" type="button" className="primar" disabled={!planned || busy || versions === null || blocking.length > 0} onClick={onPublish}>
              {`Publicera version ${next}`}
            </button>
            <span className="liten" id="publish-text">
              {!planned ? "" : blocking.length ? "Rätta det som stoppar först." : "Utkastet fryses som en ny version. Den ändras aldrig."}
            </span>
          </div>
        )}
      </section>
      {planned && <Rimlighet admin={admin} meet={meet} deviations={check?.deviations ?? null} busy={busy} onLetStand={onLetStand} onTakeBack={onTakeBack} />}
      <Forslag admin={admin} draft={draft} next={next} proposals={proposals} busy={busy} onTake={onTake} onReject={onReject} />
      <section className="kort lista-kort" aria-labelledby="versioner-rubrik">
        <h2 id="versioner-rubrik">Versioner</h2>
        <p className="liten">En version ändras aldrig och tas aldrig bort. Drift kör en version. En tillbakadragen version finns kvar, men kan inte köras.</p>
        <table className="tabell">
          <thead>
            <tr>
              <th>Version</th>
              <th>Publicerad</th>
              <th className="tal">Konflikter</th>
              <th className="tal">Iakttagelser</th>
              <th>Kontrollsumma</th>
              <th>
                <span className="osynlig">Kör</span>
              </th>
            </tr>
          </thead>
          <tbody id="versions">
            {versions && versions.length ? (
              versions
                .slice()
                .reverse()
                .map((version) => (
                  <Fragment key={version.number}>
                    <tr className={version.withdrawn ? "tillbakadragen" : undefined}>
                      <td>
                        <b>{`Version ${version.number}`}</b>
                      </td>
                      <td>{when(version.published)}</td>
                      <td className="tal">{String(version.conflicts ?? 0)}</td>
                      <td className="tal">{String(version.observations ?? 0)}</td>
                      <td className="kod" title={version.checksum}>
                        {version.checksum.slice(0, 12)}
                      </td>
                      <td>
                        {version.withdrawn ? (
                          <span className="pill tillbaka">{`Tillbakadragen ${when(version.withdrawn)}`}</span>
                        ) : (
                          <span className="rad">
                            <a href={`/drift?traff=${encodeURIComponent(meet)}&version=${version.number}#ny-traff`}>Kör i Drift →</a>
                            {admin && (
                              <button type="button" className="fara" aria-expanded={asking === version.number} aria-controls={`withdraw-${version.number}`} disabled={busy} onClick={() => setAsking(asking === version.number ? null : version.number)}>
                                Dra tillbaka
                              </button>
                            )}
                          </span>
                        )}
                      </td>
                    </tr>
                    {admin && asking === version.number && !version.withdrawn && (
                      <tr id={`withdraw-${version.number}`} className="bekrafta">
                        <td colSpan={6}>
                          <p>{`Version ${version.number} kan sedan inte startas eller tas i drift. Den finns kvar, och en träff som redan kör den fortsätter, med en varning i Nu.`}</p>
                          <span className="rad">
                            <button type="button" className="fara" id="withdraw-confirm" disabled={busy} onClick={() => (setAsking(null), onWithdraw?.(version.number))}>
                              {`Dra tillbaka version ${version.number}`}
                            </button>
                            <button type="button" onClick={() => setAsking(null)}>
                              Avbryt
                            </button>
                          </span>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))
            ) : (
              <tr>
                <td colSpan={6} className="tom">
                  {versions ? "Ingen version är publicerad än." : "Hämtar versionerna …"}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </section>
      {planned && <Exportera admin={admin} meet={meet} versions={versions ?? []} />}
    </>
  );
}

/** Exportera (PLAN-07): the draft or a version, as files. The graph is printed from Graf. */
function Exportera({ admin, meet, versions }: { admin: boolean; meet: string; versions: Version[] }) {
  const [from, setFrom] = useState("");
  const base = `/api/planering/1/meets/${encodeURIComponent(meet)}/export`;
  const query = from ? `?version=${from}` : "";
  const files: [string, string, string][] = [
    ["stationstidtabeller", "Stationstidtabeller", "en sida per driftplats, att skriva ut eller spara som PDF"],
    ["tidtabell", "Hela tidtabellen", "CSV för ett kalkylprogram, en rad per tågbesök"],
    ["koruppdrag", "Köruppdragen", "CSV, varje del av varje köruppdrag"],
    ["paket", "Paketets JSON", "så som Drift läser det"],
  ];
  return (
    <section className="kort" aria-labelledby="export-rubrik">
      <h2 id="export-rubrik">Exportera</h2>
      <p className="liten">Filerna laddas ner. Grafen skriver du ut från Graf.</p>
      <label className="valj">
        Från{" "}
        <select id="export-from" value={from} onChange={(event) => setFrom(event.target.value)}>
          <option value="">Utkastet</option>
          {versions
            .slice()
            .reverse()
            .map((version) => (
              <option key={version.number} value={String(version.number)}>
                {`Version ${version.number}`}
              </option>
            ))}
        </select>
      </label>
      <ul id="exports" className="export">
        {files.map(([what, label, note]) => (
          <li key={what}>
            <a href={`${base}/${what}${query}`} download>
              {label}
            </a>
            <span className="liten">{note}</span>
          </li>
        ))}
        {admin && (
          <li>
            <a href={`${base}/underlag`} download>
              Underlaget som ZIP
            </a>
            <span className="liten">filerna som de kom, bara för den inloggade</span>
          </li>
        )}
      </ul>
    </section>
  );
}

const how = (proposal: Proposal) => `Trafikledningen · ${when(proposal.made)} · körde version ${proposal.version}`;

/** Förslag från Drift (4.4, PLAN-03): each driftändring, to take into the next version or to
 * reject. Drift sees the answer. One let go in Drift before an answer is withdrawn. */
/** Rimlighetskontrollen (PLAN-36): each train against the other trains. Advice, not rules: it
 * never stops publishing. Rätta in the grid, or Låt stå; Ta tillbaka undoes it. */
function Rimlighet({ admin, meet, deviations, busy, onLetStand, onTakeBack }: { admin: boolean; meet: string; deviations: Deviation[] | null; busy: boolean; onLetStand?: (deviation: Deviation) => void; onTakeBack?: (deviation: Deviation) => void }) {
  const open = (deviations ?? []).filter((deviation) => !deviation.let_stand);
  const left = (deviations ?? []).filter((deviation) => deviation.let_stand);
  const grid = (deviation: Deviation) => `/planering/${encodeURIComponent(meet)}/data?block=calls&sok=${encodeURIComponent(deviation.train_number)}`;
  const item = (deviation: Deviation, action: ReactNode) => (
    <li key={deviation.id}>
      <span className="pill observation">{deviation.title}</span>
      <span>
        {deviation.message}
        <span className="liten">{` · ${days(deviation.days)}`}</span>
      </span>
      <span className="rad svar">
        <a href={grid(deviation)}>Visa i rutnätet</a>
        {admin && action}
      </span>
    </li>
  );
  return (
    <section className="kort" aria-labelledby="rimlighet-rubrik">
      <h2 id="rimlighet-rubrik">
        Rimlighet <span className="liten">{deviations ? `· ${open.length} att granska` : ""}</span>
      </h2>
      <p className="liten">Varje tåg jämförs med de andra tågen mellan samma driftplatser och på samma driftplats. Det är råd, inte regler: det stoppar aldrig publiceringen och följer inte med versionen. Rätta i rutnätet eller låt stå.</p>
      <ul id="deviations" className="fynd">
        {deviations === null ? (
          <li className="tom">Kontrollerar …</li>
        ) : open.length ? (
          open.map((deviation) =>
            item(
              deviation,
              <button type="button" disabled={busy} onClick={() => onLetStand?.(deviation)}>
                Låt stå
              </button>,
            ),
          )
        ) : (
          <li className="tom">Inget ovanligt.</li>
        )}
      </ul>
      {left.length > 0 && (
        <details id="let-stand">
          <summary>{`${left.length} lämnade som de är`}</summary>
          <ul className="fynd">
            {left.map((deviation) =>
              item(
                deviation,
                <button type="button" disabled={busy} onClick={() => onTakeBack?.(deviation)}>
                  Ta tillbaka
                </button>,
              ),
            )}
          </ul>
        </details>
      )}
    </section>
  );
}

function Forslag({ admin, draft, next, proposals, busy, onTake, onReject }: { admin: boolean; draft: Draft | null; next: number; proposals: Proposal[] | null; busy: boolean; onTake?: (id: string) => void; onReject?: (id: string) => void }) {
  const waiting = (proposals ?? []).filter((proposal) => proposal.status === "waiting");
  const count = (status: Proposal["status"]) => (proposals ?? []).filter((proposal) => proposal.status === status).length;
  const pkg = draft?.package ?? null;
  return (
    <section id="forslag" className="kort" aria-labelledby="forslag-rubrik">
      <h2 id="forslag-rubrik">
        Förslag från Drift{" "}
        <span id="proposal-count" className="liten">
          {proposals ? `· ${waiting.length} väntar` : ""}
        </span>
      </h2>
      <p className="liten">Driftändringarna görs i Nu och gäller direkt. Här tas de med i nästa version eller avslås.</p>
      <ul id="proposals" className="fynd">
        {proposals === null ? (
          <li className="tom">Hämtar förslagen …</li>
        ) : waiting.length ? (
          waiting.map((proposal) => (
            <li key={proposal.id}>
              <span className="pill observation">Väntar</span>
              <span>
                <b>{changeText(proposal.change, pkg, proposal.train_number)}</b>
                <br />
                <span className="liten">{how(proposal)}</span>
              </span>
              {admin && (
                <span className="rad">
                  <button type="button" className="primar" disabled={busy || !pkg} onClick={() => onTake?.(proposal.id)}>
                    {`Ta med i version ${next}`}
                  </button>
                  <button type="button" disabled={busy} onClick={() => onReject?.(proposal.id)}>
                    Avslå
                  </button>
                </span>
              )}
            </li>
          ))
        ) : (
          <li className="tom">Inga förslag väntar.</li>
        )}
      </ul>
      {proposals !== null && proposals.length > waiting.length && (
        <p id="proposal-history" className="liten">
          {[`Tidigare: ${count("taken")} tagna med`, `${count("rejected")} avslagna`, count("withdrawn") ? `${count("withdrawn")} återtagna i Drift` : ""].filter(Boolean).join(" · ")}
        </p>
      )}
      {!admin && waiting.length > 0 && <p className="liten">Logga in för att ta med eller avslå.</p>}
    </section>
  );
}

