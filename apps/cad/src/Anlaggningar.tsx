// Anläggningar (#89 del d2, CAD-06, CAD9, CAD-21) and Till TKL Studio (CAD-10, CAD-15), as the
// views Anlaggning and Till-Studio: modules put together gable to gable, the joints checked, an
// angle per module, the versions pinned with a newer approved one offered; then the track graph
// that goes to Studio, and how to connect it to a station there. CAD never makes a station.
import { linkClick, type Navigate } from "@trainmeet/design";
import { useCallback, useEffect, useState } from "react";
import { API, api, ApiError, type ModuleBrief, type Scale, SCALES } from "./api";
import {
  addModule,
  assemblyApi,
  box,
  candidates,
  endKey,
  endOf,
  follows,
  freeGables,
  join,
  jointAngle,
  jointText,
  moduleAngle,
  removeModule,
  rename,
  studioHref,
  takeNewer,
  title,
  unjoin,
  type Assembly,
  type AssemblyBrief,
  type AssemblyChange,
  type End,
  type NewAssembly,
  type StationUse,
  type StudioGraph,
} from "./anlaggning";
import { count } from "./common";
import { pathOf, segsOf } from "./Drawing";
import { assemblyPath, PATHS, studioPath, type Route } from "./routes";

type Point = [number, number];
const same = (p: Point): Point => p;

/** A form's field by its name: the forms are uncontrolled, so that the page holds no state. */
export type FormLike = { elements: { namedItem: (name: string) => unknown } };

function field(form: FormLike, name: string): string {
  const found = form.elements.namedItem(name) as { value?: unknown } | null;
  return typeof found?.value === "string" ? found.value : "";
}

type Submit = { preventDefault: () => void; currentTarget: FormLike };

function message(failure: unknown): string {
  return failure instanceof Error ? failure.message : "Något gick fel. Försök igen.";
}

function stationsText(stations: StationUse[] | undefined): string {
  return (stations ?? []).map((s) => s.name).join(", ") || "ingen station än";
}

// --- The list ------------------------------------------------------------------------------

type ListProps = {
  list: AssemblyBrief[];
  scale: Scale;
  busy?: boolean;
  error?: string | null;
  navigate?: Navigate;
  onCreate?: (body: NewAssembly) => void;
};

export function AssemblyList({ list, scale, busy, error, navigate, onCreate }: ListProps) {
  return (
    <section className="cad-sida" aria-labelledby="rubrik">
      <div className="cad-rubrikrad">
        <h1 id="rubrik">Anläggningar</h1>
      </div>
      <p className="cad-ingress">
        Sätt ihop godkända moduler gavel mot gavel. Skarvarna kontrolleras, vinkeln följer kurvorna och modulversionerna låses. Anläggningen går sedan
        till TKL Studio som spårgraf.
      </p>
      {error ? (
        <p className="cad-fel" role="alert">
          {error}
        </p>
      ) : null}
      <div className="cad-anl-lista">
        {list.length ? (
          <table className="cad-tabell">
            <thead>
              <tr>
                <th>Anläggning</th>
                <th>Skala</th>
                <th>Moduler</th>
                <th>Läge</th>
                <th>Används i</th>
              </tr>
            </thead>
            <tbody>
              {list.map((a) => (
                <tr key={a.id}>
                  <td>
                    <a href={assemblyPath(a.id)} onClick={linkClick(navigate, assemblyPath(a.id))}>
                      {a.name}
                    </a>
                    {a.owner.kind === "club" ? <span className="cad-dampad"> · {a.owner.name}</span> : null}
                  </td>
                  <td>{a.scale}</td>
                  <td>{a.modules}</td>
                  <td>
                    {a.problems ? (
                      <span className="cad-status fel">{count(a.problems, "sak att rätta", "saker att rätta")}</span>
                    ) : (
                      <span className="cad-status godkand">Klar för Studio</span>
                    )}
                  </td>
                  <td>{stationsText(a.stations)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="cad-dampad">Inga anläggningar än.</p>
        )}
        <form
          className="cad-kort cad-anl-ny"
          onSubmit={(event: Submit) => {
            event.preventDefault();
            const name = field(event.currentTarget, "anlaggning").trim();
            if (name) onCreate?.({ name, scale: (field(event.currentTarget, "skala") || scale) as Scale, owner: null });
          }}
        >
          <h2>Ny anläggning</h2>
          <label className="cad-falt">
            <span>Namn</span>
            <input name="anlaggning" maxLength={80} required />
          </label>
          <label className="cad-falt">
            <span>Skala</span>
            <select name="skala" defaultValue={scale}>
              {SCALES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>
          <button type="submit" className="tm-knapp primar" disabled={busy}>
            Skapa anläggningen
          </button>
        </form>
      </div>
    </section>
  );
}

// --- The drawing ---------------------------------------------------------------------------

/** The assembly from above: the boards, the tracks CAD joined, the free gables and the joints
 * that do not fit. */
export function AssemblyPicture({ assembly, look = "plan" }: { assembly: Assembly; look?: "plan" | "realistisk" | "mork" }) {
  const parts = assembly.parts ?? [];
  const area = box(parts.flatMap((p) => p.outline ?? []));
  const unit = Math.max(area.w, area.h) / 220;
  const segs = assembly.graph ? segsOf(assembly.graph) : [];
  const free = freeGables(assembly);
  const wrong = (assembly.checks ?? []).filter((c) => !c.fits);
  const jointsAt = (assembly.joints ?? []).map((j) => {
    const part = parts.find((p) => p.module === j.a.module);
    const gable = part?.gables?.find((g) => g.end === j.a.gable);
    const points = gable?.tracks?.length ? gable.tracks : gable ? [gable.corner, gable.far] : [];
    const n = points.length || 1;
    return [points.reduce((s, p) => s + p[0], 0) / n, points.reduce((s, p) => s + p[1], 0) / n] as Point;
  });
  const real = look === "realistisk";
  return (
    <svg
      className={`cad-ritning cad-anl-bild ${look}`}
      viewBox={`${area.x} ${area.y} ${area.w} ${area.h}`}
      role="img"
      aria-label={`${assembly.name} ovanifrån`}
      preserveAspectRatio="xMidYMid meet"
    >
      {parts.map((p) => (
        <path
          key={p.module}
          className={`cad-skiva${p.seen ? "" : " osedd"}`}
          d={(p.outline ?? []).map((q, i) => `${i ? "L" : "M"}${q[0]} ${q[1]}`).join("") + "Z"}
          strokeWidth={unit * 0.5}
        />
      ))}
      {real
        ? segs.map((seg, i) => <path key={`b${i}`} className="cad-ballast" d={pathOf(seg, same)} strokeWidth={50} />)
        : null}
      {real
        ? segs.map((seg, i) => (
            <path key={`l${i}`} className="cad-sliprar" d={pathOf(seg, same)} strokeWidth={34} strokeDasharray="6 10" />
          ))
        : null}
      {segs.map((seg, i) => (
        <path key={`s${i}`} className="cad-spar" d={pathOf(seg, same)} strokeWidth={real ? 20 : unit * 1.1} />
      ))}
      {real ? segs.map((seg, i) => <path key={`r${i}`} className="cad-ralsmellan" d={pathOf(seg, same)} strokeWidth={13} />) : null}
      {look === "plan"
        ? parts.map((p) => {
            const outline = p.outline ?? [];
            const n = outline.length || 1;
            const c: Point = [outline.reduce((s, q) => s + q[0], 0) / n, outline.reduce((s, q) => s + q[1], 0) / n];
            return (
              <text key={`t${p.module}`} x={c[0]} y={c[1]} fontSize={unit * 5} textAnchor="middle" className="cad-anl-nummer">
                {p.seen ? p.number : "?"}
              </text>
            );
          })
        : null}
      {look === "plan"
        ? free.map((g) => <circle key={endKey(g.end)} className="cad-fri-gavel" cx={g.at[0]} cy={g.at[1]} r={unit * 2.2} data-gavel={endKey(g.end)} />)
        : null}
      {wrong.map((c) => {
        const at = jointsAt[c.joint];
        return at ? <circle key={`f${c.joint}`} className="cad-skarv-fel" cx={at[0]} cy={at[1]} r={unit * 4} data-skarv={c.joint} /> : null;
      })}
    </svg>
  );
}

// --- One assembly ----------------------------------------------------------------------------

type PageProps = {
  assembly: Assembly;
  modules: ModuleBrief[];
  busy?: boolean;
  error?: string | null;
  navigate?: Navigate;
  onChange?: (change: AssemblyChange) => void;
  onRemove?: () => void;
};

export function AssemblyPage({ assembly, modules, busy, error, navigate, onChange, onRemove }: PageProps) {
  const free = freeGables(assembly);
  const choices = candidates(assembly, modules);
  const edit = assembly.may_edit && !busy;
  const problems = assembly.problems ?? [];
  const parts = assembly.parts ?? [];
  return (
    <section className="cad-sida" aria-labelledby="rubrik">
      <p className="cad-brodsmulor">
        <a href={PATHS.assemblies} onClick={linkClick(navigate, PATHS.assemblies)}>
          Anläggningar
        </a>{" "}
        › {assembly.name}
      </p>
      <div className="cad-rubrikrad">
        <h1 id="rubrik">{assembly.name}</h1>
        <span className="cad-pill">{assembly.scale}</span>
        {assembly.owner.kind === "club" ? <span className="cad-pill">{assembly.owner.name}</span> : null}
        {problems.length ? (
          <span className="cad-status fel">{count(problems.length, "sak att rätta", "saker att rätta")}</span>
        ) : (
          <span className="cad-status godkand">Klar för Studio</span>
        )}
        <span className="cad-dampad">Version {assembly.revision}</span>
        <span className="tm-fyll" />
        <a className="tm-knapp" href={`${API}/assemblies/${assembly.id}/dxf`} download>
          Ladda ner DXF
        </a>
        <a className="tm-knapp primar" href={studioPath(assembly.id)} onClick={linkClick(navigate, studioPath(assembly.id))}>
          Till TKL Studio
        </a>
      </div>
      {error ? (
        <p className="cad-fel" role="alert">
          {error}
        </p>
      ) : null}
      {problems.length ? (
        <div className="cad-fel cad-anl-problem" role="status">
          <strong>Det här hindrar anläggningen från Studio</strong>
          <ul>
            {problems.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        </div>
      ) : null}
      <div className="cad-anl-yta">
        <div className="cad-kort cad-anl-ritkort">
          {parts.length ? <AssemblyPicture assembly={assembly} /> : <p className="cad-dampad">Lägg till den första modulen till höger.</p>}
          <p className="cad-dampad cad-anl-teckenforklaring">
            <span className="cad-prov fri" /> fri gavel · <span className="cad-prov fel" /> skarv som inte passar
          </p>
        </div>
        <div className="cad-anl-sida">
          {assembly.may_edit ? (
            <form
              className="cad-kort cad-anl-lagg"
              aria-label="Lägg till modul"
              onSubmit={(event: Submit) => {
                event.preventDefault();
                const form = event.currentTarget;
                const chosen = field(form, "modul") || choices[0]?.id || "";
                const where = parts.length ? field(form, "vid") || (free[0] ? endKey(free[0].end) : "fritt") : "fritt";
                const at = where !== "fritt" ? endOf(where) : null;
                // Samma håll: B mot A or A mot B, Kant 1 to Kant 1; vänd: the same gable, turned round.
                const turned = field(form, "hall") === "vand";
                const own: End = at ? (turned ? at.gable : at.gable === "A" ? "B" : "A") : "A";
                if (chosen) onChange?.(addModule(assembly, chosen, at, own));
              }}
            >
              <h2>Lägg till modul</h2>
              {choices.length ? (
                <>
                  <label className="cad-falt">
                    <span>Modul, godkänd version</span>
                    <select name="modul" defaultValue={choices[0]?.id}>
                      {choices.map((m) => (
                        <option key={m.id} value={m.id}>
                          {m.number} {m.name} · version {m.version}
                        </option>
                      ))}
                    </select>
                  </label>
                  {parts.length ? (
                    <label className="cad-falt">
                      <span>Vid</span>
                      <select name="vid" defaultValue={free[0] ? endKey(free[0].end) : "fritt"}>
                        {free.map((g) => (
                          <option key={endKey(g.end)} value={endKey(g.end)}>
                            {g.text}
                          </option>
                        ))}
                        <option value="fritt">Fritt, bredvid de andra</option>
                      </select>
                    </label>
                  ) : null}
                  {parts.length ? (
                    <label className="cad-falt">
                      <span>Modulen ligger</span>
                      <select name="hall" defaultValue="samma">
                        <option value="samma">Åt samma håll · Kant 1 mot Kant 1</option>
                        <option value="vand">Vänd · gavel mot samma gavel</option>
                      </select>
                    </label>
                  ) : null}
                  <button type="submit" className="tm-knapp primar" disabled={!edit}>
                    Lägg till
                  </button>
                </>
              ) : (
                <p className="cad-dampad">
                  Inga fler godkända moduler i skala {assembly.scale} som du ser. Godkänn en modul i biblioteket först.
                </p>
              )}
            </form>
          ) : null}
          <div className="cad-kort cad-anl-moduler">
            <h2 className="cad-overrubrik">Moduler · versionerna låsta</h2>
            <ul>
              {parts.map((p) => {
                const placed = (assembly.modules ?? []).find((m) => m.module === p.module);
                return (
                  <li key={p.module} data-modul={p.module}>
                    <strong>{title(p)}</strong> <span className="cad-dampad">version {p.version}</span>
                    {p.placed === "joint" ? null : (
                      <label className="cad-anl-vinkel">
                        Vinkel°
                        <input
                          type="number"
                          step="0.1"
                          defaultValue={Math.round((placed?.angle ?? 0) * 100) / 100}
                          disabled={!edit}
                          onBlur={(e) => {
                            const value = Number(e.currentTarget.value);
                            if (Number.isFinite(value) && value !== placed?.angle) onChange?.(moduleAngle(assembly, p.module, value));
                          }}
                        />
                      </label>
                    )}
                    {p.newer ? (
                      <button type="button" className="tm-knapp gul" disabled={!edit} onClick={() => onChange?.(takeNewer(assembly, p.module))}>
                        Version {p.newer} är godkänd · använd den
                      </button>
                    ) : null}
                    {assembly.may_edit ? (
                      <button type="button" className="cad-lank fara" disabled={!edit} onClick={() => onChange?.(removeModule(assembly, p.module))}>
                        Ta bort
                      </button>
                    ) : null}
                  </li>
                );
              })}
            </ul>
          </div>
          <div className="cad-kort cad-anl-skarvar">
            <h2 className="cad-overrubrik">Skarvar</h2>
            {(assembly.joints ?? []).length ? (
              <ul>
                {(assembly.joints ?? []).map((j, i) => {
                  const check = (assembly.checks ?? [])[i];
                  return (
                    <li key={`${endKey(j.a)}-${endKey(j.b)}`} className={check?.fits ? "passar" : "fel"} data-skarv={i}>
                      <span>{jointText(assembly, j)}</span>{" "}
                      {check?.fits ? <span className="cad-tagg gron">✓ Passar</span> : <span className="cad-tagg rod">Passar inte</span>}
                      {check?.closing ? <span className="cad-dampad"> · sluter en slinga</span> : null}
                      {check?.problems?.length ? (
                        <ul className="cad-anl-varfor">
                          {check.problems.map((p) => (
                            <li key={p}>{p}</li>
                          ))}
                        </ul>
                      ) : null}
                      <label className="cad-anl-vinkel">
                        Skarvens vinkel°
                        <input
                          type="number"
                          step="0.1"
                          min={-15}
                          max={15}
                          defaultValue={j.angle ?? 0}
                          disabled={!edit}
                          onBlur={(e) => {
                            const value = Number(e.currentTarget.value);
                            if (Number.isFinite(value) && value !== (j.angle ?? 0)) onChange?.(jointAngle(assembly, i, value));
                          }}
                        />
                      </label>
                      {assembly.may_edit ? (
                        <button type="button" className="cad-lank fara" disabled={!edit} onClick={() => onChange?.(unjoin(assembly, i))}>
                          Ta bort skarven
                        </button>
                      ) : null}
                    </li>
                  );
                })}
              </ul>
            ) : (
              <p className="cad-dampad">Inga skarvar än.</p>
            )}
            {assembly.may_edit && free.length >= 2 ? (
              <form
                className="cad-anl-skarva"
                aria-label="Skarva två gavlar"
                onSubmit={(event: Submit) => {
                  event.preventDefault();
                  const a = endOf(field(event.currentTarget, "forsta") || endKey(free[0]!.end));
                  const b = endOf(field(event.currentTarget, "andra") || endKey(free[1]!.end));
                  if (a && b && endKey(a) !== endKey(b)) onChange?.(join(assembly, a, b));
                }}
              >
                <h3>Skarva två fria gavlar</h3>
                <select aria-label="Första gaveln" name="forsta" defaultValue={endKey(free[0]!.end)}>
                  {free.map((g) => (
                    <option key={endKey(g.end)} value={endKey(g.end)}>
                      {g.text}
                    </option>
                  ))}
                </select>
                <select aria-label="Andra gaveln" name="andra" defaultValue={endKey(free[1]!.end)}>
                  {free.map((g) => (
                    <option key={endKey(g.end)} value={endKey(g.end)}>
                      {g.text}
                    </option>
                  ))}
                </select>
                <button type="submit" className="tm-knapp" disabled={!edit}>
                  Skarva
                </button>
              </form>
            ) : null}
          </div>
          <div className="cad-kort">
            <h2 className="cad-overrubrik">Används i</h2>
            <p>{stationsText(assembly.stations)}</p>
            {assembly.may_edit ? (
              <form
                onSubmit={(event: Submit) => {
                  event.preventDefault();
                  const value = field(event.currentTarget, "namn").trim();
                  if (value && value !== assembly.name) onChange?.(rename(assembly, value));
                }}
                className="cad-knapprad"
              >
                <label className="cad-falt">
                  <span>Anläggningens namn</span>
                  <input name="namn" defaultValue={assembly.name} maxLength={80} />
                </label>
                <button type="submit" className="tm-knapp" disabled={!edit}>
                  Byt namn
                </button>
                <button type="button" className="cad-lank fara" disabled={!edit} onClick={onRemove}>
                  Ta bort anläggningen
                </button>
              </form>
            ) : null}
          </div>
        </div>
      </div>
    </section>
  );
}

// --- Till TKL Studio -----------------------------------------------------------------------

type StudioProps = {
  studio: StudioGraph;
  assembly: Assembly | null;
  host: string;
  look?: "realistisk" | "mork";
  navigate?: Navigate;
  onLook?: (look: "realistisk" | "mork") => void;
};

export function TillStudio({ studio, assembly, host, look = "realistisk", navigate, onLook }: StudioProps) {
  const source = studio.source;
  const found = follows(studio.graph);
  const problems = source.problems ?? [];
  const shown: Assembly | null = assembly ? { ...assembly, graph: studio.graph } : null;
  return (
    <section className="cad-sida" aria-labelledby="rubrik">
      <p className="cad-brodsmulor">
        <a href={PATHS.assemblies} onClick={linkClick(navigate, PATHS.assemblies)}>
          Anläggningar
        </a>{" "}
        ›{" "}
        <a href={assemblyPath(source.id)} onClick={linkClick(navigate, assemblyPath(source.id))}>
          {source.name}
        </a>{" "}
        › Till TKL Studio
      </p>
      <div className="cad-rubrikrad">
        <h1 id="rubrik">Till TKL Studio</h1>
        <span className="cad-pill">{source.name}</span>
        <span className="cad-dampad">Version {source.revision}</span>
      </div>
      {problems.length ? (
        <div className="cad-fel" role="status">
          <strong>Rätta det här först, så kan anläggningen gå till Studio</strong>
          <ul>
            {problems.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        </div>
      ) : null}
      <div className="cad-anl-yta">
        <div className="cad-kort cad-anl-ritkort">
          <div className="cad-knapprad cad-anl-utseende" role="group" aria-label="Förhandsvisning">
            <button type="button" className="tm-knapp" aria-pressed={look === "realistisk"} onClick={() => onLook?.("realistisk")}>
              Verklighetstrogen
            </button>
            <button type="button" className="tm-knapp" aria-pressed={look === "mork"} onClick={() => onLook?.("mork")}>
              Mörk
            </button>
          </div>
          {shown ? <AssemblyPicture assembly={shown} look={look} /> : <p className="cad-dampad">Hämtar anläggningen …</p>}
        </div>
        <div className="cad-anl-sida">
          <div className="cad-kort cad-anl-foljer">
            <h2 className="cad-overrubrik">Det här följer med</h2>
            <p>Bara spårgrafen, i millimeter, med id som CAD aldrig byter när en modul ritas om.</p>
            <ul>
              <li>{count(found.pieces, "spårbit", "spårbitar")} · {found.metres.toString().replace(".", ",")} m spår</li>
              <li>{count(found.switches, "växel", "växlar")}</li>
              <li>{count(found.crossings, "korsning", "korsningar")}</li>
              <li>{count(found.exits, "spår vid en fri gavel", "spår vid fria gavlar")} · blir linjeutfarter i Studio</li>
              <li>{count(found.ends, "spår som slutar i en modul", "spår som slutar i moduler")} · blir stoppbockar i Studio</li>
            </ul>
            <h2 className="cad-overrubrik">Det räknar Studio fram</h2>
            <p>Signaler, stoppbockar och vägar. Spårens nummer och växlarnas nummer från CAD följer med som förslag.</p>
          </div>
          <div className="cad-kort cad-anl-koppla">
            <h2 className="cad-overrubrik">Koppla till en station i TKL</h2>
            <ol>
              <li>Öppna TKL Studio › Rita och välj Från CAD.</li>
              <li>Välj {source.name} och gör förslaget. Allt är gult tills du bekräftar det.</li>
              <li>Bekräfta förslaget och använd ritningen.</li>
            </ol>
            <p className="cad-dampad">
              CAD skapar aldrig en station. Stationen finns i TKL, och du bekräftar där. Läser du in igen visar Studio skillnaden och behåller det du har lagt till.
            </p>
            <a className={`tm-knapp primar${problems.length ? " avstangd" : ""}`} href={studioHref(host)} aria-disabled={problems.length ? "true" : undefined}>
              Öppna TKL Studio
            </a>
          </div>
          <div className="cad-kort">
            <h2 className="cad-overrubrik">Används i</h2>
            <p>{stationsText(source.stations)}</p>
          </div>
        </div>
      </div>
    </section>
  );
}

// --- The pages, with their data from CAD's API ---------------------------------------------

type ContainerProps = { route: Route; host: string; scale: Scale; navigate?: Navigate };

/** Anläggningar's pages: the list, one assembly and Till TKL Studio, each from CAD's API. */
export function Assemblies({ route, host, scale, navigate }: ContainerProps) {
  const [list, setList] = useState<AssemblyBrief[] | null>(null);
  const [assembly, setAssembly] = useState<Assembly | null>(null);
  const [studio, setStudio] = useState<StudioGraph | null>(null);
  const [modules, setModules] = useState<ModuleBrief[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [look, setLook] = useState<"realistisk" | "mork">("realistisk");
  const id = route.page === "assembly" || route.page === "studio" ? route.id : null;

  useEffect(() => {
    setError(null);
    if (route.page === "assemblies") assemblyApi.list().then(setList, (f: unknown) => setError(message(f)));
  }, [route]);

  const load = useCallback(
    (ident: string) =>
      assemblyApi.read(ident).then(
        (found) => {
          setAssembly(found);
          api.modules("all", found.scale).then((l) => setModules(l.modules), () => setModules([]));
        },
        (f: unknown) => setError(message(f)),
      ),
    [],
  );

  useEffect(() => {
    if (!id) return;
    void load(id);
    if (route.page === "studio") assemblyApi.studio(id).then(setStudio, (f: unknown) => setError(message(f)));
  }, [id, route.page, load]);

  if (route.page === "assemblies") {
    if (!list) return <p className="cad-sida">{error ?? "Hämtar anläggningarna …"}</p>;
    return (
      <AssemblyList
        list={list}
        scale={scale}
        busy={busy}
        error={error}
        navigate={navigate}
        onCreate={(body) => {
          setBusy(true);
          assemblyApi.create(body).then(
            (made) => {
              setBusy(false);
              setAssembly(made);
              navigate?.(assemblyPath(made.id));
            },
            (f: unknown) => {
              setBusy(false);
              setError(message(f));
            },
          );
        }}
      />
    );
  }
  if (route.page === "studio") {
    if (!studio || studio.source.id !== id) return <p className="cad-sida">{error ?? "Hämtar spårgrafen …"}</p>;
    return <TillStudio studio={studio} assembly={assembly?.id === id ? assembly : null} host={host} look={look} navigate={navigate} onLook={setLook} />;
  }
  if (!assembly || assembly.id !== id) return <p className="cad-sida">{error ?? "Hämtar anläggningen …"}</p>;
  return (
    <AssemblyPage
      key={`${assembly.id}-${assembly.revision}`}
      assembly={assembly}
      modules={modules}
      busy={busy}
      error={error}
      navigate={navigate}
      onChange={(change) => {
        setBusy(true);
        setError(null);
        assemblyApi.save(assembly.id, change).then(
          (saved) => {
            setBusy(false);
            setAssembly(saved);
          },
          (f: unknown) => {
            setBusy(false);
            setError(message(f));
            if (f instanceof ApiError && f.status === 409) void load(assembly.id);
          },
        );
      }}
      onRemove={() => {
        if (!window.confirm(`Ta bort ${assembly.name}? Modulerna finns kvar i biblioteket.`)) return;
        assemblyApi.remove(assembly.id).then(() => navigate?.(PATHS.assemblies), (f: unknown) => setError(message(f)));
      }}
    />
  );
}
