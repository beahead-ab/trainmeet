import type { Check, Draft, Version } from "./api";
import { when } from "./text";

// Versioner (S6): the traffic check, Publicera for the administrator, and the versions, which
// never change and are never removed. Kör i Drift opens Byt träff with the version (TRAFIK-29).

export type VersionerProps = {
  admin: boolean;
  meet: string;
  draft: Draft | null;
  check: Check | null;
  versions: Version[] | null;
  busy?: boolean;
  onPublish?: () => void;
};

export function VersionerPage({ admin, meet, draft, check, versions, busy = false, onPublish }: VersionerProps) {
  const next = (versions?.at(-1)?.number ?? 0) + 1;
  const planned = Boolean(draft?.package);
  const findings = check?.findings ?? [];
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
        <p className="liten">Fynden följer med versionen. De stoppar inte publiceringen.</p>
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
            <button id="publish" type="button" className="primar" disabled={!planned || busy || versions === null} onClick={onPublish}>
              {`Publicera version ${next}`}
            </button>
            <span className="liten" id="publish-text">
              {planned ? "Utkastet fryses som en ny version. Den ändras aldrig." : ""}
            </span>
          </div>
        )}
      </section>
      <section className="kort lista-kort" aria-labelledby="versioner-rubrik">
        <h2 id="versioner-rubrik">Versioner</h2>
        <p className="liten">En version ändras aldrig och tas aldrig bort. Drift kör en version.</p>
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
                  <tr key={version.number}>
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
                      <a href={`/drift?traff=${encodeURIComponent(meet)}&version=${version.number}#ny-traff`}>Kör i Drift →</a>
                    </td>
                  </tr>
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
    </>
  );
}
