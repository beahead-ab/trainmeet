// Exportera (#89 del d1, CAD-07, CAD-24): a module version as the FREMO sheet, the module database's
// record, the MMM measures, DXF and a print, as the view Export. CAD makes every file; the page
// chooses the version and the DXF's layers, and prints the sheets with the browser, as the hub
// prints. A draft exports with Utkast on every file. Export is free (CAD-18).
import { linkClick, type Navigate } from "@trainmeet/design";
import { Fragment, useEffect, useState } from "react";
import { modulePath, PATHS, exportPath } from "./routes";
import { landscapeApi, type ExportFile, type LandscapeApi, type MmmGable, type ModuleExport } from "./landskapapi";
import "./landskap.css";

function fileOf(found: ModuleExport, name: string): ExportFile | undefined {
  return found.files.find((f) => f.url.endsWith(`/${name}`));
}

/** The DXF's address with its choices: the rails, and the landscape when there is one. */
export function dxfHref(found: ModuleExport, rails: boolean, landscape: boolean): string {
  const url = fileOf(found, "modul.dxf")?.url ?? "";
  const query = new URLSearchParams({ rails: String(rails), landscape: String(landscape && found.landscape) });
  return `${url}?${query}`;
}

export function mmText(value: number | null | undefined): string {
  if (value == null) return "–";
  return (Math.round(value * 10) / 10).toString().replace(".", ",").replace("-", "−");
}

function Download({ file, label }: { file: ExportFile | undefined; label: string }) {
  if (!file) return null;
  return (
    <a className="tm-knapp" href={file.url} download={file.file}>
      {label}
    </a>
  );
}

function MmmTable({ gable }: { gable: MmmGable }) {
  return (
    <table className="cad-tabell cad-mmm">
      <caption>
        Gavel {gable.end} · {gable.label} · bredd {mmText(gable.width)} mm
      </caption>
      <thead>
        <tr>
          <th scope="col">Spår</th>
          <th scope="col">Från Kant 1</th>
          <th scope="col">Avstånd</th>
          <th scope="col">MMM</th>
          <th scope="col">Avvikelse</th>
        </tr>
      </thead>
      <tbody>
        {(gable.tracks ?? []).map((t) => (
          <tr key={t.track} className={t.deviation != null && Math.abs(t.deviation) > 2 ? "avviker" : undefined}>
            <td>{t.track}</td>
            <td className="tm-mono">{mmText(t.from_kant1)}</td>
            <td className="tm-mono">{mmText(t.spacing)}</td>
            <td className="tm-mono">{mmText(t.mmm)}</td>
            <td className="tm-mono">{t.deviation == null ? "–" : mmText(t.deviation)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

type ViewProps = {
  found: ModuleExport;
  rails: boolean;
  landscape: boolean;
  navigate?: Navigate;
  onRails?: (on: boolean) => void;
  onLandscape?: (on: boolean) => void;
  onPrint?: () => void;
};

/** Exportera as the page shows it, from the state; ExportPage holds the state. */
export function ExportView({ found, rails, landscape, navigate, onRails, onLandscape, onPrint }: ViewProps) {
  const draft = found.status !== "approved";
  const back = modulePath(found.module);
  const fremo = fileOf(found, "fremo.svg");
  const print = fileOf(found, "utskrift.svg");
  const record = found.record;
  return (
    <section className="cad-sida cad-export" aria-labelledby="rubrik">
      <nav className="cad-brodsmulor" aria-label="Var du är">
        <a href={PATHS.library} onClick={linkClick(navigate, PATHS.library)}>
          Moduler
        </a>{" "}
        ›{" "}
        <a href={back} onClick={linkClick(navigate, back)}>
          {found.name}
        </a>{" "}
        › <span aria-current="page">Exportera</span>
      </nav>
      <div className="cad-rubrikrad">
        <h1 id="rubrik">Exportera</h1>
        <span className="cad-pill tm-mono">{found.number}</span>
        <span className="cad-pill">Version {found.version}</span>
        {draft ? <span className="cad-tagg forslag">Utkast</span> : <span className="cad-status godkand">✓ Godkänd</span>}
        <span className="cad-fyll" />
        <span className="cad-dampad">Exporten är gratis.</span>
      </div>
      {found.versions.length > 1 ? (
        <fieldset className="cad-kort cad-versionsval">
          <legend className="cad-overrubrik">Version att exportera</legend>
          {found.versions.map((v) => {
            const href = exportPath(found.module, v.version);
            return (
              <a key={v.version} href={href} aria-current={v.version === found.version ? "page" : undefined} onClick={linkClick(navigate, href)}>
                {v.label}
              </a>
            );
          })}
        </fieldset>
      ) : null}
      {draft ? (
        <p className="cad-ruta cad-utkastruta" role="status">
          Version {found.version} är inte godkänd. Allt som exporteras märks Utkast.
        </p>
      ) : null}
      <div className="cad-exportval">
        <article className="cad-kort">
          <h2>FREMO-ritning</h2>
          <p className="cad-dampad">Modulbladet: planen med mått, gavlarna med spårens lägen från Kant 1 och titelrutan. A4 liggande.</p>
          {fremo ? <img className="cad-exportbild" src={fremo.url} alt={`FREMO-ritningen för ${found.name}`} /> : null}
          <div className="cad-knapprad">
            <Download file={fremo} label="Ladda ner SVG" />
            <button type="button" className="tm-knapp" onClick={() => onPrint?.()}>
              Skriv ut
            </button>
          </div>
        </article>
        <article className="cad-kort">
          <h2>Moduldatabasen</h2>
          <p className="cad-dampad">
            Modulen som en rad i en modullista, i formatet <span className="tm-mono">{record.format}</span>: samma fält i JSON och CSV.
          </p>
          <dl className="cad-postlista">
            <dt>Modul</dt>
            <dd>
              {record.number} {record.name}
            </dd>
            <dt>Skala och form</dt>
            <dd>
              {record.scale} · {record.shape === "straight" ? "rak" : record.shape === "curve" ? "kurva" : "trapets"} · {mmText(record.length)} mm
            </dd>
            {record.gables.map((g) => (
              <Fragment key={g.end}>
                <dt>Gavel {g.end}</dt>
                <dd>
                  {g.label} · {(g.tracks ?? []).map(mmText).join(" / ") || "inga spår"}
                </dd>
              </Fragment>
            ))}
            <dt>Spår</dt>
            <dd>
              {mmText(record.track_length / 1000)} m · {record.switches} växlar
            </dd>
          </dl>
          <div className="cad-knapprad">
            <Download file={fileOf(found, "moduldatabas.json")} label="JSON" />
            <Download file={fileOf(found, "moduldatabas.csv")} label="CSV" />
          </div>
        </article>
        <article className="cad-kort">
          <h2>MMM</h2>
          <p className="cad-dampad">Gavelmåtten och spåravstånden som MMM anger dem, mot MMM:s lägen där gaveln följer MMM. MMM:s blanketter kommer senare.</p>
          {found.mmm.map((g) => (
            <MmmTable key={g.end} gable={g} />
          ))}
          <div className="cad-knapprad">
            <Download file={fileOf(found, "mmm.csv")} label="Ladda ner CSV" />
          </div>
        </article>
        <article className="cad-kort">
          <h2>DXF</h2>
          <p className="cad-dampad">DXF R12 i mm: spårmitt som riktiga LINE och ARC, modulens kontur, Kant 1, gavelmärken och mått, på egna lager.</p>
          <label className="cad-kryss">
            <input type="checkbox" name="dxf-rals" checked={rails} onChange={(event) => onRails?.(event.currentTarget.checked)} />
            Rälsen
          </label>
          <label className="cad-kryss">
            <input
              type="checkbox"
              name="dxf-landskap"
              checked={landscape && found.landscape}
              disabled={!found.landscape}
              onChange={(event) => onLandscape?.(event.currentTarget.checked)}
            />
            Landskapet{found.landscape ? "" : " (modulen har inget landskap)"}
          </label>
          <div className="cad-knapprad">
            <a className="tm-knapp primar" href={dxfHref(found, rails, landscape)} download={fileOf(found, "modul.dxf")?.file}>
              Ladda ner DXF
            </a>
          </div>
        </article>
        <article className="cad-kort">
          <h2>Utskrift</h2>
          <p className="cad-dampad">Modulen med landskapet, ytorna och måtten, och FREMO-ritningen. Skriv ut, eller spara som PDF i utskriften.</p>
          {print ? <img className="cad-exportbild" src={print.url} alt={`Utskriften för ${found.name}`} /> : null}
          <div className="cad-knapprad">
            <button type="button" className="tm-knapp primar" onClick={() => onPrint?.()}>
              Skriv ut
            </button>
            <Download file={print} label="Ladda ner SVG" />
          </div>
        </article>
      </div>
      <div className="cad-utskrift" aria-hidden="true">
        {print ? <img className="cad-utskriftssida" src={print.url} alt="" /> : null}
        {fremo ? <img className="cad-utskriftssida" src={fremo.url} alt="" /> : null}
      </div>
    </section>
  );
}

/** Exportera: the version from the address, or the approved one. */
export function ExportPage({ id, version, navigate, client = landscapeApi }: { id: string; version?: number; navigate?: Navigate; client?: LandscapeApi }) {
  const [found, setFound] = useState<ModuleExport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [rails, setRails] = useState(false);
  const [landscape, setLandscape] = useState(true);
  useEffect(() => {
    setFound(null);
    client.exportOf(id, version).then(setFound, (failure: unknown) => setError(failure instanceof Error ? failure.message : "Något gick fel."));
  }, [client, id, version]);
  if (error) {
    return (
      <section className="cad-sida">
        <h1>Exportera</h1>
        <p className="cad-fel" role="alert">
          {error}
        </p>
      </section>
    );
  }
  if (!found) return <p className="cad-sida">Hämtar exporten …</p>;
  return (
    <ExportView
      found={found}
      rails={rails}
      landscape={landscape}
      navigate={navigate}
      onRails={setRails}
      onLandscape={setLandscape}
      onPrint={() => window.print()}
    />
  );
}
