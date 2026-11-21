// Import från AnyRail (#91, TKL16, ANYRAIL-01–22): AnyRail's own file or its XML export is read in
// CAD, and the file stays in CAD. The page shows the proposed modules on the drawing (approve each
// or all, and name them, AR1), the switches with the assumed ones yellow to confirm (AR3), the
// checks, the measures the file is read with (AR5, AR6: three shown, the rest under Fler mått), and
// the exports. Skapa modulerna makes the approved ones drafts in the library and an assembly that
// places them as in the drawing; Studio gets its track graph through Från CAD.
import { linkClick, type Navigate } from "@trainmeet/design";
import { useCallback, useEffect, useState } from "react";
import {
  api,
  type AnyRailCreated,
  type AnyRailImport,
  type AnyRailMeasures,
  type AnyRailModule,
  type AnyRailSwitch,
  type CheckItem,
  type Scale,
  SCALES,
  type TrackGraph,
} from "./api";
import { pathOf, segsOf } from "./Drawing";
import { anyrailPath, ANYRAIL_PATH, assemblyPath, modulePath, PATHS } from "./routes";

type Point = [number, number];
const same = (p: Point): Point => p;

function message(failure: unknown): string {
  return failure instanceof Error ? failure.message : "Något gick fel. Försök igen.";
}

const number = (n: number, decimals = 1) => n.toLocaleString("sv-SE", { maximumFractionDigits: decimals, useGrouping: false });

/** A measure as the page shows it: in cm or mm, as the specification gives it (AR5, AR6). */
type MeasureKey = "track_width" | "join_distance" | "lateral" | "crossing_node" | "crossing_angle" | "backward_length" | "tight_radius";
type Measure = { key: MeasureKey; label: string; unit: "cm" | "mm" | "°"; more: boolean };

const valueOf = (measures: AnyRailMeasures, key: MeasureKey): number => Number(measures[key] ?? 0);

export const MEASURES: Measure[] = [
  { key: "track_width", label: "Spårbredd", unit: "cm", more: false },
  { key: "join_distance", label: "Skarvavstånd", unit: "cm", more: false },
  { key: "lateral", label: "Sidledsfel", unit: "mm", more: false },
  { key: "crossing_node", label: "Korsning minst från en nod", unit: "cm", more: true },
  { key: "crossing_angle", label: "Korsning flaggas under", unit: "°", more: true },
  { key: "backward_length", label: "Bakåtbit kortare än", unit: "cm", more: true },
  { key: "tight_radius", label: "Flexbåge ritas om under radien", unit: "mm", more: true },
];

/** The measure in the unit shown, from CAD's mm. */
export function shown(measure: Measure, mm: number | undefined): string {
  const value = mm ?? 0;
  return number(measure.unit === "cm" ? value / 10 : value, 2);
}

/** CAD's mm from the unit shown; null when it is no number. */
export function stored(measure: Measure, text: string): number | null {
  const value = Number(text.replace(",", ".").trim());
  if (!Number.isFinite(value) || text.trim() === "") return null;
  return measure.unit === "cm" ? value * 10 : value;
}

const KIND_TITLES: Record<string, string> = {
  switch_assumed: "Antagna växlar",
  switch_joint: "Växlar över en modulskarv",
  oblique_joint: "Sneda skarvar",
  drawing_fix: "Överlapp, glapp och bakåtbitar",
  kink: "Knyckar",
  tight_radius: "Snäva radier",
  crossing_doubt: "Korsningar att kontrollera",
  loose_part: "Lösa delar",
  removed: "Borttagna öglor, broar och väggar",
};

export function grouped(checks: CheckItem[]): [string, CheckItem[]][] {
  const found = new Map<string, CheckItem[]>();
  for (const c of checks) {
    const key = c.kind ?? "other";
    found.set(key, [...(found.get(key) ?? []), c]);
  }
  return Object.keys(KIND_TITLES)
    .filter((k) => found.has(k))
    .map((k): [string, CheckItem[]] => [KIND_TITLES[k] ?? k, found.get(k) ?? []]);
}

function sideText(sw: AnyRailSwitch): string {
  return sw.side === "y" ? "Y" : sw.side === "left" ? "vänster" : "höger";
}

// --- The drawing ---------------------------------------------------------------------------

function area(found: AnyRailImport): { x: number; y: number; w: number; h: number } {
  const points: Point[] = [
    ...(found.modules ?? []).flatMap((m) => m.outline as Point[]),
    ...(found.graph?.nodes ?? []).map((n) => n.at as Point),
  ];
  if (!points.length) return { x: 0, y: 0, w: found.area[0] || 1000, h: found.area[1] || 1000 };
  const xs = points.map((p) => p[0]);
  const ys = points.map((p) => p[1]);
  const pad = 80;
  const x = Math.min(...xs) - pad;
  const y = Math.min(...ys) - pad;
  return { x, y, w: Math.max(...xs) - x + pad, h: Math.max(...ys) - y + pad };
}

export function AnyRailDrawing({ found, chosen, confirmed }: { found: AnyRailImport; chosen: Set<string>; confirmed: Set<string> }) {
  const box = area(found);
  const unit = Math.max(box.w, box.h) / 400;
  const nodes = new Map((found.graph?.nodes ?? []).map((n) => [n.id, n.at as Point]));
  return (
    <svg className="cad-ritning cad-anyrail-bild" viewBox={`${box.x} ${box.y} ${box.w} ${box.h}`} role="img" aria-label="Ritningen ur AnyRail med modulerna" preserveAspectRatio="xMidYMid meet">
      {(found.drawing ?? []).map((line, i) => (
        <path key={`r${i}`} className="cad-anyrail-linje" d={line.map((p, k) => `${k ? "L" : "M"}${p[0]} ${p[1]}`).join("")} strokeWidth={unit * 0.4} />
      ))}
      {(found.modules ?? []).map((m) => (
        <path
          key={m.key}
          className={`cad-skiva${chosen.has(m.key) ? "" : " osedd"}`}
          d={(m.outline as Point[]).map((p, k) => `${k ? "L" : "M"}${p[0]} ${p[1]}`).join("") + "Z"}
          strokeWidth={unit * 0.6}
          data-modul={m.key}
        />
      ))}
      {(found.left_out ?? []).map((line, i) => (
        <path key={`u${i}`} className="cad-anyrail-utanfor" d={line.map((p, k) => `${k ? "L" : "M"}${p[0]} ${p[1]}`).join("")} strokeWidth={unit * 0.8} />
      ))}
      {segsOf(found.graph as unknown as TrackGraph).map((seg, i) => (
        <path key={`s${i}`} className="cad-spar" d={pathOf(seg, same)} strokeWidth={unit * 1.1} />
      ))}
      {(found.modules ?? []).map((m) => {
        const outline = m.outline as Point[];
        const c: Point = [outline.reduce((s, p) => s + p[0], 0) / outline.length, outline.reduce((s, p) => s + p[1], 0) / outline.length];
        return (
          <text key={`t${m.key}`} x={c[0]} y={c[1]} fontSize={unit * 7} textAnchor="middle" className="cad-anl-nummer">
            {m.number}
          </text>
        );
      })}
      {(found.switches ?? []).map((sw) => {
        const yellow = sw.assumed && !(sw.confirm && confirmed.has(sw.confirm));
        return (
          <circle
            key={`v${sw.number}`}
            className={`cad-anyrail-vaxel${yellow ? " antagen" : ""}`}
            cx={sw.at[0]}
            cy={sw.at[1]}
            r={unit * (sw.assumed ? 3.2 : 2)}
            data-vaxel={sw.number}
          />
        );
      })}
      {(found.graph?.nodes ?? [])
        .filter((n) => n.type === "crossing")
        .map((n) => {
          const at = nodes.get(n.id) ?? [0, 0];
          return <rect key={n.id} className="cad-anyrail-korsning" x={at[0] - unit * 2} y={at[1] - unit * 2} width={unit * 4} height={unit * 4} />;
        })}
    </svg>
  );
}

// --- The view ------------------------------------------------------------------------------

export type AnyRailViewProps = {
  found: AnyRailImport;
  chosen: Set<string>;
  names: Record<string, string>;
  confirmed: Set<string>;
  busy?: boolean;
  error?: string | null;
  created?: AnyRailCreated | null;
  navigate?: Navigate;
  onChoose?: (key: string, on: boolean) => void;
  onChooseAll?: () => void;
  onName?: (key: string, name: string) => void;
  onConfirm?: (key: string, on: boolean) => void;
  onMeasures?: (scale: Scale, measures: AnyRailMeasures) => void;
  onCreate?: () => void;
};

function readMeasures(form: HTMLFormElement, before: AnyRailMeasures): AnyRailMeasures | null {
  const next: Record<string, unknown> = { ...before };
  for (const m of MEASURES) {
    const field = form.elements.namedItem(m.key) as HTMLInputElement | null;
    const value = stored(m, field?.value ?? "");
    if (value === null) return null;
    next[m.key] = value;
  }
  return next as unknown as AnyRailMeasures;
}

export function AnyRailView(props: AnyRailViewProps) {
  const { found, chosen, names, confirmed, navigate } = props;
  const stats = found.stats;
  const modules = found.modules ?? [];
  const switches = found.switches ?? [];
  const assumed = switches.filter((s) => s.assumed);
  const open = assumed.filter((s) => !(s.confirm && confirmed.has(s.confirm)));
  const measures = found.measures;
  const defaults = found.defaults ?? measures;
  const changed = MEASURES.filter((m) => valueOf(measures, m.key) !== valueOf(defaults, m.key));
  const field = (m: Measure) => (
    <label key={m.key} className="cad-matt-falt">
      <span>
        {m.label} <span className="cad-dampad">({m.unit})</span>
      </span>
      <input name={m.key} inputMode="decimal" defaultValue={shown(m, valueOf(measures, m.key))} />
      <span className="cad-dampad">förval {shown(m, valueOf(defaults, m.key))}</span>
    </label>
  );
  const submit = (event: { preventDefault: () => void; currentTarget: HTMLFormElement }) => {
    event.preventDefault();
    const form = event.currentTarget;
    const next = readMeasures(form, measures);
    const scale = (form.elements.namedItem("skala") as HTMLSelectElement | null)?.value as Scale | undefined;
    if (next && props.onMeasures) props.onMeasures(scale ?? found.scale, next);
  };
  return (
    <section className="cad-sida cad-anyrail" aria-labelledby="rubrik">
      <nav className="cad-brodsmulor" aria-label="Var du är">
        <a href={PATHS.library} onClick={linkClick(navigate, PATHS.library)}>
          Moduler
        </a>{" "}
        ›{" "}
        <a href={PATHS.new} onClick={linkClick(navigate, PATHS.new)}>
          Ny modul
        </a>{" "}
        › <span aria-current="page">AnyRail</span>
      </nav>
      <div className="cad-rubrikrad">
        <div>
          <h1 id="rubrik">Import från AnyRail</h1>
          <p className="cad-ingress">
            {found.name} · {found.format === "any" ? "AnyRails egen fil" : "XML-export"} · skala {found.scale}
            {found.library ? ` · spårbibliotek ${found.library}` : ""}. Filen stannar i TrainMeet CAD. Allt nedan är förslag tills du
            godkänner.
          </p>
        </div>
      </div>
      {props.error ? (
        <p className="cad-fel" role="alert">
          {props.error}
        </p>
      ) : null}
      <p className="cad-anyrail-sammanfattning">
        {stats.parts} delar · {modules.length} moduler · {stats.switches} växlar, varav {stats.assumed} antagna · {stats.crossings} korsningar ·{" "}
        {stats.station_tracks} stationsspår
      </p>

      <div className="cad-kort">
        <AnyRailDrawing found={found} chosen={chosen} confirmed={confirmed} />
      </div>

      <form className="cad-kort cad-anyrail-matt" aria-labelledby="matt-rubrik" onSubmit={submit}>
        <h2 id="matt-rubrik">Måtten för filen</h2>
        <p className="cad-dampad">
          Förvalen fungerar för de flesta filer. Tolkas filen fel kan du ställa om måtten för den här filen. Samma mått ger alltid samma
          resultat; samplingen var 10:e mm är fast.
        </p>
        <div className="cad-anyrail-falt">
          <label className="cad-matt-falt">
            <span>Skala</span>
            <select name="skala" defaultValue={found.scale}>
              {SCALES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>
          {MEASURES.filter((m) => !m.more).map(field)}
        </div>
        <details className="cad-anyrail-fler">
          <summary>Fler mått</summary>
          <div className="cad-anyrail-falt">{MEASURES.filter((m) => m.more).map(field)}</div>
        </details>
        <p className="cad-dampad">
          {changed.length
            ? `Ändrat mot förvalen: ${changed.map((m) => m.label.toLowerCase()).join(", ")}.`
            : "Filen är läst med förvalen."}
        </p>
        <div className="cad-knapprad">
          <button type="submit" className="tm-knapp" disabled={props.busy}>
            Läs om med måtten
          </button>
        </div>
      </form>

      <div className="cad-kort" aria-labelledby="moduler-rubrik">
        <div className="cad-rubrikrad">
          <h2 id="moduler-rubrik">Modulerna</h2>
          <span className="cad-fyll" />
          <button type="button" className="tm-knapp" onClick={props.onChooseAll}>
            Godkänn alla
          </button>
        </div>
        <p className="cad-dampad">Modulerna är byggda ur ritningens tunna linjer och kontrollerade mot standardmåtten. Godkänn dem som stämmer och döp om dem om du vill.</p>
        <ul className="cad-anyrail-moduler">
          {modules.map((m: AnyRailModule) => (
            <li key={m.key} data-modul={m.key}>
              <label className="cad-anyrail-val">
                <input type="checkbox" checked={chosen.has(m.key)} onChange={(e) => props.onChoose?.(m.key, e.currentTarget.checked)} />
                <span>Godkänn</span>
              </label>
              <input
                className="cad-anyrail-namn"
                aria-label={`Namn på modul ${m.number}`}
                value={names[m.key] ?? m.name}
                onChange={(e) => props.onName?.(m.key, e.currentTarget.value)}
              />
              <span className="tm-mono">
                {number(m.shape.length, 0)} × {number(m.shape.width, 0)}
              </span>
              {m.standard ? <span className="cad-tagg gron">Standard {m.standard}</span> : <span className="cad-tagg gul">Inte standardmått</span>}
              <span className="cad-dampad">
                {m.switches} växlar{m.assumed ? `, ${m.assumed} antagna` : ""}
              </span>
            </li>
          ))}
        </ul>
      </div>

      <div className="cad-kort" aria-labelledby="vaxlar-rubrik">
        <h2 id="vaxlar-rubrik">Växlarna</h2>
        {assumed.length ? (
          <p>
            {open.length ? `${open.length} antagna växlar står gula.` : "Alla antagna växlar är bekräftade."} En antagen växel är där ett flexspår delar sig
            utan växel i AnyRail; den måste bekräftas innan modulen kan godkännas.
          </p>
        ) : (
          <p className="cad-dampad">Inga antagna växlar.</p>
        )}
        <ul className="cad-kollista">
          {assumed.map((sw) => {
            const done = Boolean(sw.confirm && confirmed.has(sw.confirm));
            const module = modules.find((m) => m.key === sw.module);
            return (
              <li key={sw.number} className={done ? "" : "antagen"} data-vaxel={sw.number}>
                <h3>
                  Växel {sw.number}
                  {module ? ` · modul ${module.number}` : ""} {done ? "· bekräftad" : "är antagen"}
                </h3>
                <p>
                  {sideText(sw)}
                  {sw.radius ? `, R ${number(sw.radius, 0)} mm` : ""}, vid x {number(sw.at[0], 0)} mm
                </p>
                <label className="cad-anyrail-val">
                  <input type="checkbox" checked={done} disabled={!sw.confirm} onChange={(e) => sw.confirm && props.onConfirm?.(sw.confirm, e.currentTarget.checked)} />
                  <span>Bekräfta växel {sw.number}</span>
                </label>
              </li>
            );
          })}
        </ul>
        <details>
          <summary>Växellistan, {switches.length} växlar från väster</summary>
          <table className="cad-tabell">
            <thead>
              <tr>
                <th>Nr</th>
                <th>AnyRail</th>
                <th>Typ</th>
                <th>Radie</th>
                <th>Modul</th>
                <th>Antagen</th>
              </tr>
            </thead>
            <tbody>
              {switches.map((sw) => (
                <tr key={sw.number}>
                  <td>{sw.number}</td>
                  <td>{sw.anyrail ?? "–"}</td>
                  <td>{sideText(sw)}</td>
                  <td>{sw.radius ? `${number(sw.radius, 0)} mm` : "–"}</td>
                  <td>{modules.find((m) => m.key === sw.module)?.number ?? "–"}</td>
                  <td>{sw.assumed ? "ja" : "nej"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      </div>

      <div className="cad-kort" aria-labelledby="kontroller-rubrik">
        <h2 id="kontroller-rubrik">Kontrollerna</h2>
        <p className="cad-dampad">
          Knyckar högst {stats.max_kink != null ? number(stats.max_kink, 1) : "–"}° · minsta radie {stats.min_radius != null ? number(stats.min_radius, 0) : "–"} mm ·{" "}
          {stats.backward_removed} bakåtbitar borttagna · {stats.gaps} glapp och {stats.overlaps} överlapp sammanfogade ·{" "}
          {stats.doubled_removed ? `${stats.doubled_removed} dubbelritade spår borttagna · ` : ""}
          {stats.loose} lösa delar
        </p>
        {grouped(found.checks ?? []).map(([title, items]) => (
          <details key={title} className="cad-anyrail-kontroll" open={title === "Antagna växlar"}>
            <summary>
              {title} ({items.length})
            </summary>
            <ul>
              {items.map((c) => (
                <li key={c.key}>
                  <b>{c.title}</b> {c.text}
                  {c.assumed ? <span className="cad-tagg gul">Ska bekräftas</span> : null}
                </li>
              ))}
            </ul>
          </details>
        ))}
      </div>

      <div className="cad-kort" aria-labelledby="export-rubrik">
        <h2 id="export-rubrik">Exportera</h2>
        <ul className="cad-anyrail-filer">
          {(found.files ?? []).map((f) => (
            <li key={f.url}>
              <a href={f.url} download={f.file}>
                {f.name}
              </a>
            </li>
          ))}
        </ul>
      </div>

      <div className="cad-kort cad-anyrail-skapa">
        {props.created ? (
          <>
            <h2>Modulerna är skapade</h2>
            <p>
              {props.created.modules.length} moduler ligger som utkast i ditt modulbibliotek, och anläggningen{" "}
              <a href={assemblyPath(props.created.assembly)} onClick={linkClick(navigate, assemblyPath(props.created.assembly))}>
                {props.created.assembly_name}
              </a>{" "}
              lägger dem som i ritningen. Godkänn modulerna, så kan anläggningen gå till TKL Studio under Från CAD.
            </p>
            <ul>
              {props.created.modules.map((m) => (
                <li key={m.id}>
                  <a href={modulePath(m.id)} onClick={linkClick(navigate, modulePath(m.id))}>
                    {m.number} {m.name}
                  </a>
                </li>
              ))}
            </ul>
          </>
        ) : (
          <>
            <p>
              {chosen.size} av {modules.length} moduler godkända.{" "}
              {open.length ? `${open.length} antagna växlar är inte bekräftade: de modulerna kan inte godkännas i biblioteket förrän du bekräftat dem.` : ""}
            </p>
            <div className="cad-knapprad">
              <button type="button" className="tm-knapp primar" disabled={props.busy || chosen.size === 0} onClick={props.onCreate}>
                Skapa modulerna
              </button>
            </div>
          </>
        )}
      </div>
    </section>
  );
}

// --- The upload and the page ---------------------------------------------------------------

export function AnyRailUpload({ navigate, busy, error, onFile }: { navigate?: Navigate; busy?: boolean; error?: string | null; onFile?: (file: File) => void }) {
  return (
    <section className="cad-sida cad-anyrail" aria-labelledby="rubrik">
      <nav className="cad-brodsmulor" aria-label="Var du är">
        <a href={PATHS.new} onClick={linkClick(navigate, PATHS.new)}>
          Ny modul
        </a>{" "}
        › <span aria-current="page">AnyRail</span>
      </nav>
      <h1 id="rubrik">Import från AnyRail</h1>
      <p className="cad-ingress">
        Ladda upp AnyRails egen fil (.any) eller exporten som XML (Arkiv, Exportera). TrainMeet CAD bygger modulerna ur ritningens tunna linjer,
        läser spåren och växlarna, och visar vad som behöver kontrolleras. Filen stannar i CAD; TKL Studio får spårgrafen.
      </p>
      {error ? (
        <p className="cad-fel" role="alert">
          {error}
        </p>
      ) : null}
      <label className="cad-kort cad-anyrail-fil">
        <span>AnyRail-fil</span>
        <input
          type="file"
          name="fil"
          accept=".any,.xml,.zip,application/xml,text/xml,application/zip"
          disabled={busy}
          onChange={(e) => {
            const file = e.currentTarget.files?.[0];
            if (file && onFile) onFile(file);
          }}
        />
        <span className="cad-dampad">{busy ? "Läser filen …" : "Högst 20 MB. Gratis."}</span>
      </label>
    </section>
  );
}

export function AnyRailPage({ id, navigate }: { id?: string; navigate?: Navigate }) {
  const [found, setFound] = useState<AnyRailImport | null>(null);
  const [chosen, setChosen] = useState<Set<string>>(new Set());
  const [names, setNames] = useState<Record<string, string>>({});
  const [confirmed, setConfirmed] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<AnyRailCreated | null>(null);

  const take = useCallback((next: AnyRailImport) => {
    setFound(next);
    setChosen(new Set((next.modules ?? []).map((m) => m.key)));
    setCreated(next.created ?? null);
    setConfirmed((before) => new Set([...before].filter((k) => (next.switches ?? []).some((s) => s.confirm === k))));
  }, []);

  useEffect(() => {
    if (!id) return;
    api.anyrailRead(id).then(take, (failure: unknown) => setError(message(failure)));
  }, [id, take]);

  if (!id) {
    const upload = (file: File) => {
      setBusy(true);
      setError(null);
      api.anyrailUpload(file, { name: file.name, scale: null, measures: null }).then(
        (made) => {
          setBusy(false);
          if (navigate) navigate(anyrailPath(made.id));
          else window.location.assign(anyrailPath(made.id));
        },
        (failure: unknown) => {
          setBusy(false);
          setError(message(failure));
        },
      );
    };
    return <AnyRailUpload navigate={navigate} busy={busy} error={error} onFile={upload} />;
  }
  if (!found) {
    return error ? (
      <section className="cad-sida">
        <p className="cad-fel" role="alert">
          {error}
        </p>
        <a href={ANYRAIL_PATH} onClick={linkClick(navigate, ANYRAIL_PATH)}>
          Ladda upp en annan fil
        </a>
      </section>
    ) : (
      <p className="cad-sida">Läser filen …</p>
    );
  }
  const run = (work: Promise<void>) => {
    setBusy(true);
    setError(null);
    work.then(
      () => setBusy(false),
      (failure: unknown) => {
        setBusy(false);
        setError(message(failure));
      },
    );
  };
  return (
    <AnyRailView
      found={found}
      chosen={chosen}
      names={names}
      confirmed={confirmed}
      busy={busy}
      error={error}
      created={created}
      navigate={navigate}
      onChoose={(key, on) => setChosen((before) => (on ? new Set([...before, key]) : new Set([...before].filter((k) => k !== key))))}
      onChooseAll={() => setChosen(new Set((found.modules ?? []).map((m) => m.key)))}
      onName={(key, name) => setNames((before) => ({ ...before, [key]: name }))}
      onConfirm={(key, on) => setConfirmed((before) => (on ? new Set([...before, key]) : new Set([...before].filter((k) => k !== key))))}
      onMeasures={(scale, measures) => run(api.anyrailSettings(found.id, { base: found.revision, scale, measures }).then(take))}
      onCreate={() =>
        run(
          api
            .anyrailCreate(found.id, {
              base: found.revision,
              modules: (found.modules ?? [])
                .filter((m) => chosen.has(m.key))
                .map((m) => ({ key: m.key, name: (names[m.key] ?? m.name).trim() || m.name })),
              confirmed: [...confirmed],
              assembly: null,
            })
            .then(setCreated),
        )
      }
    />
  );
}
