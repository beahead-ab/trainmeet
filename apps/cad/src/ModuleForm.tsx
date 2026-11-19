// Rak modul, Kurvmodul and Trapets: the measures and the gables, as in the views Modul-rak and
// Modul-kurva. The same form changes a module: every save is a new version (CAD-08).
import { linkClick, type Navigate } from "@trainmeet/design";
import { useMemo, useState, type ReactNode } from "react";
import type { GableProfile, Module, ModuleChange, NewModule, ProfileList, Scale, Shape } from "./api";
import { SCALES } from "./api";
import { GableView, ModuleDrawing } from "./Drawing";
import { arcLength, fromChord, lineRadius, mm, toChord, type Bend } from "./geometry";
import { modulePath, PATHS, UPLOAD_PATH, type FormKind } from "./routes";

type GableState = { profile: string; norm: string; steps: string[] };
type FormState = {
  name: string;
  scale: Scale;
  kind: FormKind;
  owner: string;
  length: string;
  width: string;
  widthB: string;
  /** Förskjutning: gable B's corner at Kant 1 across from gable A's, mm (a trapezoid). */
  offset: string;
  mode: "chord" | "radius";
  chord: string;
  sagitta: string;
  radius: string;
  angle: string;
  edge: "outer" | "inner";
  sides: "bent" | "straight";
  a: GableState;
  b: GableState;
  sameB: boolean;
};

export type Owner = { id: string; name: string };

type Props = {
  kind: FormKind;
  scale: Scale;
  profiles: ProfileList | null;
  /** The module to change, at its newest version; without it a new module is made. */
  module?: Module | null;
  /** Who the new module can belong to: the person, and the clubs they are the administrator of. */
  owners?: Owner[];
  owner?: string;
  navigate?: Navigate;
  onCreate?: (body: NewModule) => Promise<void>;
  onSave?: (body: ModuleChange) => Promise<void>;
  onCancel?: () => void;
  /** The form's scale changed: the profiles of that scale are wanted. */
  onScale?: (scale: Scale) => void;
};

const n = (text: string) => (text.trim() === "" ? NaN : Number(text.replace(",", ".")));
const show = (value: number | null | undefined) => (value == null || Number.isNaN(value) ? "" : String(Math.round(value * 10) / 10));

function stepsOf(tracks: number[]): string[] {
  return tracks.map((t, i) => show(i === 0 ? t : t - (tracks[i - 1] ?? 0)));
}

function fixedSteps(profile: GableProfile): (number | null)[] {
  return [profile.first ?? null, ...(profile.spacings ?? [])];
}

function gableFor(profile: GableProfile | undefined, before: string[], width: number): GableState {
  if (!profile) return { profile: "", norm: "", steps: before.length ? before : [show(width / 2)] };
  const fixed = fixedSteps(profile);
  const steps = fixed.map((value, i) => (value != null ? show(value) : before[i] ?? (i === 0 ? show(width / 2 - 25 * (fixed.length - 1)) : "50")));
  return { profile: profile.id, norm: profile.norm ?? "", steps };
}

function initial(kind: FormKind, scale: Scale, profiles: ProfileList | null, module: Module | null | undefined, owner: string): FormState {
  if (module) {
    const shape = module.shape;
    const a = module.gables[0];
    const b = module.gables[1];
    const g = (label: typeof a): GableState => ({ profile: label?.profile ?? "", norm: label?.norm ?? "", steps: stepsOf(label?.tracks ?? []) });
    return {
      name: module.name,
      scale: module.scale,
      kind: shape.kind,
      owner,
      length: shape.kind === "curve" ? "" : show(shape.length),
      width: shape.kind === "trapezoid" ? show(shape.width_a) : show(shape.width),
      widthB: shape.kind === "trapezoid" ? show(shape.width_b) : "",
      offset: shape.kind === "trapezoid" ? show(shape.offset ?? 0) : "0",
      mode: shape.kind === "curve" && shape.measured ? "chord" : "radius",
      chord: shape.kind === "curve" && shape.measured ? show(shape.measured.chord) : "",
      sagitta: shape.kind === "curve" && shape.measured ? show(shape.measured.sagitta) : "",
      radius: shape.kind === "curve" ? show(shape.radius) : "",
      angle: shape.kind === "curve" ? show(shape.angle) : "",
      edge: shape.kind === "curve" ? shape.edge ?? "outer" : "outer",
      sides: shape.kind === "curve" ? shape.sides ?? "bent" : "bent",
      a: g(a),
      b: g(b),
      sameB: JSON.stringify(a?.tracks) === JSON.stringify(b?.tracks) && a?.profile === b?.profile,
    };
  }
  const general = profiles?.profiles.find((p) => p.kind === "general" && p.tracks === 1);
  const width = kind === "trapezoid" ? 480 : 500;
  const gable = gableFor(general, [], width);
  return {
    name: "",
    scale,
    kind,
    owner,
    length: kind === "trapezoid" ? "685" : "1500",
    width: String(width),
    widthB: kind === "trapezoid" ? "280" : "",
    offset: "0",
    mode: "chord",
    chord: "",
    sagitta: "",
    radius: "",
    angle: "",
    edge: "outer",
    sides: "bent",
    a: kind === "trapezoid" ? { ...gable, steps: ["140"] } : gable,
    b: kind === "trapezoid" ? { ...gable, steps: ["140"] } : gable,
    sameB: true,
  };
}

function tracksOf(g: GableState): number[] | null {
  const values = g.steps.map(n);
  if (values.some((v) => !(v > 0))) return null;
  let sum = 0;
  return values.map((v) => (sum += v));
}

/** The bend the form gives, and the one computed from the string and sagitta: the same, never
 * rounded (CAD16, CAD-35). */
function bendOf(state: FormState): { bend: Bend | null; found: Bend | null } {
  if (state.mode === "radius") {
    const radius = n(state.radius);
    const angle = n(state.angle);
    return { bend: radius > 0 && angle > 0 && angle < 180 ? { radius, angle } : null, found: null };
  }
  const found = fromChord(n(state.chord), n(state.sagitta));
  if (!found) return { bend: null, found: null };
  return { bend: found, found };
}

function shapeOf(state: FormState): Shape | null {
  const width = n(state.width);
  if (!(width > 0)) return null;
  if (state.kind === "curve") {
    const { bend } = bendOf(state);
    if (!bend) return null;
    return {
      kind: "curve",
      radius: bend.radius,
      angle: bend.angle,
      width,
      edge: state.edge,
      sides: state.sides,
      measured: state.mode === "chord" ? { chord: n(state.chord), sagitta: n(state.sagitta) } : null,
    };
  }
  const length = n(state.length);
  if (!(length > 0)) return null;
  if (state.kind === "trapezoid") {
    const widthB = n(state.widthB);
    if (!(widthB > 0)) return null;
    const offset = state.offset.trim() === "" ? 0 : n(state.offset);
    if (Number.isNaN(offset)) return null;
    return { kind: "trapezoid", length, width_a: width, width_b: widthB, offset };
  }
  return { kind: "straight", length, width };
}

function Segmented<T extends string>({ label, value, options, onChange }: { label: string; value: T; options: [T, string][]; onChange: (v: T) => void }) {
  return (
    <div className="cad-segment" role="radiogroup" aria-label={label}>
      {options.map(([key, text]) => (
        <button key={key} type="button" role="radio" aria-checked={value === key} onClick={() => onChange(key)}>
          {text}
        </button>
      ))}
    </div>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="cad-falt">
      <span>{label}</span>
      {children}
    </label>
  );
}

function MmInput({ label, value, onChange, readOnly = false, name }: { label: string; value: string; onChange?: (v: string) => void; readOnly?: boolean; name?: string }) {
  return (
    <label className="cad-matt-falt">
      <span>{label}</span>
      <span className="cad-mm">
        <input
          name={name}
          inputMode="decimal"
          value={value}
          readOnly={readOnly}
          aria-readonly={readOnly || undefined}
          onChange={(event) => onChange?.(event.currentTarget.value)}
        />
        <span aria-hidden="true">mm</span>
      </span>
    </label>
  );
}

function GableFields({
  end,
  gable,
  profiles,
  norms,
  width,
  onChange,
}: {
  end: "A" | "B";
  gable: GableState;
  profiles: GableProfile[];
  norms: { norm: string; name: string }[];
  width: number;
  onChange: (g: GableState) => void;
}) {
  const profile = profiles.find((p) => p.id === gable.profile);
  const fixed = profile ? fixedSteps(profile) : [];
  const groups: [string, GableProfile[]][] = [
    ["Normer", profiles.filter((p) => p.kind === "norm")],
    ["Allmänna", profiles.filter((p) => p.kind === "general")],
    ["Egna", profiles.filter((p) => p.kind === "own")],
  ];
  const tracks = tracksOf(gable);
  const last = tracks?.[tracks.length - 1];
  return (
    <fieldset className="cad-gavelfalt">
      <legend>
        <span className="cad-gavelmarke">{end}</span> Gavel {end}
      </legend>
      <Field label="Profil">
        <select
          name={`profil-${end}`}
          value={gable.profile}
          onChange={(event) => {
            const chosen = profiles.find((p) => p.id === event.currentTarget.value);
            onChange(gableFor(chosen, chosen ? gable.steps : gable.steps, width));
          }}
        >
          {groups.map(([title, items]) =>
            items.length ? (
              <optgroup key={title} label={title}>
                {items.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </optgroup>
            ) : null,
          )}
          <option value="">Egen gavel (mät spår för spår)</option>
        </select>
      </Field>
      {profile?.kind !== "norm" && norms.length ? (
        <Field label="Norm">
          <select name={`norm-${end}`} value={gable.norm} onChange={(event) => onChange({ ...gable, norm: event.currentTarget.value })}>
            <option value="">Ingen norm</option>
            {norms.map((item) => (
              <option key={item.norm} value={item.norm}>
                {item.name}
              </option>
            ))}
          </select>
        </Field>
      ) : null}
      {gable.steps.map((step, i) => (
        <MmInput
          key={i}
          name={`gavel-${end}-${i}`}
          label={i === 0 ? "Kant 1 → spår 1" : `Spår ${i} → spår ${i + 1}`}
          value={step}
          readOnly={fixed[i] != null}
          onChange={(value) => onChange({ ...gable, steps: gable.steps.map((s, k) => (k === i ? value : s)) })}
        />
      ))}
      {profile ? (
        <p className="cad-dampad">{profile.read ? profile.note : `${profile.note ?? ""}`}</p>
      ) : (
        <div className="cad-knapprad">
          <button type="button" className="cad-lank" onClick={() => onChange({ ...gable, steps: [...gable.steps, "50"] })}>
            + Lägg till spår
          </button>
          {gable.steps.length ? (
            <button type="button" className="cad-lank" onClick={() => onChange({ ...gable, steps: gable.steps.slice(0, -1) })}>
              Ta bort spår
            </button>
          ) : null}
        </div>
      )}
      {last != null && tracks ? (
        <p className="cad-dampad">
          Spår {tracks.length} ligger {Math.round(last)} mm från Kant 1
        </p>
      ) : null}
    </fieldset>
  );
}

export function ModuleForm({ kind, scale, profiles, module, owners = [], owner = "", navigate, onCreate, onSave, onCancel, onScale }: Props) {
  const start = useMemo(() => initial(kind, scale, profiles, module, owner), [kind, scale, profiles, module, owner]);
  const [state, setState] = useState<FormState>(start);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (change: Partial<FormState>) => setState((s) => ({ ...s, ...change }));
  const scaleProfiles = (profiles?.profiles ?? []).filter((p) => p.scale === state.scale);
  const norms = profiles?.scale === state.scale ? profiles.norms : [];
  const shape = shapeOf(state);
  const a = tracksOf(state.a);
  const b = state.sameB ? a : tracksOf(state.b);
  const dirty = JSON.stringify(state) !== JSON.stringify(start);
  const { found } = bendOf(state);
  const width = n(state.width) || 0;
  const widthB = state.kind === "trapezoid" ? n(state.widthB) || 0 : width;
  const title = module ? module.name : state.kind === "curve" ? "Ny kurvmodul" : state.kind === "trapezoid" ? "Ny trapetsmodul" : "Ny rak modul";
  const ready = Boolean(shape && a && b && state.name.trim());

  const gableBody = (end: "A" | "B", g: GableState, tracks: number[]) => ({
    end,
    profile: g.profile || null,
    norm: (g.norm || null) as NewModule["gables"][number]["norm"],
    tracks,
  });

  async function submit() {
    if (!shape || !a || !b) return;
    setBusy(true);
    setError(null);
    const gables = [gableBody("A", state.a, a), gableBody("B", state.sameB ? state.a : state.b, b)];
    try {
      if (module) {
        await onSave?.({ base: module.latest, name: state.name.trim(), scale: state.scale, shape, gables });
      } else {
        await onCreate?.({
          name: state.name.trim(),
          scale: state.scale,
          shape,
          gables,
          owner: state.owner || null,
          visibility: "me",
          club: null,
        });
      }
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Det gick inte att spara.");
    } finally {
      setBusy(false);
    }
  }

  const kantText = state.edge === "outer" ? "ytterkanten" : "innerkanten";
  const farText = state.edge === "outer" ? "Innerkanten" : "Ytterkanten";
  const rows =
    shape?.kind === "curve" && a
      ? [
          ...a.map((t, i) => ({ line: `Spår ${i + 1}`, radius: lineRadius(shape, a[0] ?? 0, t) })),
          { line: `Kant 1 · ${kantText}`, radius: lineRadius(shape, a[0] ?? 0, 0) },
          { line: farText, radius: lineRadius(shape, a[0] ?? 0, shape.width) },
        ]
      : [];
  const circle = shape?.kind === "curve" ? 360 / shape.angle : 0;

  return (
    <section className="cad-sida" aria-labelledby="rubrik">
      <nav className="cad-brodsmulor" aria-label="Var du är">
        <a href={PATHS.library} onClick={linkClick(navigate, PATHS.library)}>
          ‹ Moduler
        </a>
      </nav>
      <div className="cad-rubrikrad">
        <h1 id="rubrik">{title}</h1>
        {module ? <span className="cad-pill tm-mono">{module.number}</span> : null}
        <span className="cad-pill">{module?.photo ? "Mått · fotad" : "Mått · inget foto"}</span>
        <span className="cad-fyll" />
        {module && state.kind !== "curve" ? (
          <a className="tm-knapp" href={modulePath(module.id, "foto")} onClick={linkClick(navigate, modulePath(module.id, "foto"))}>
            Fota och kontrollera
          </a>
        ) : !module && state.kind !== "curve" ? (
          <a className="tm-knapp" href={UPLOAD_PATH} onClick={linkClick(navigate, UPLOAD_PATH)}>
            Ladda upp ett foto i stället
          </a>
        ) : (
          <button type="button" className="tm-knapp" disabled title="Foto och kontroll tar raka moduler och trapetser än">
            Fota och kontrollera
          </button>
        )}
      </div>
      <div className="cad-tvadelad">
        <form
          className="cad-kort cad-formular"
          onSubmit={(event) => {
            event.preventDefault();
            void submit();
          }}
        >
          <fieldset>
            <legend className="cad-overrubrik">Modul</legend>
            <Field label="Namn">
              <input name="namn" value={state.name} required maxLength={80} onChange={(event) => set({ name: event.currentTarget.value })} />
            </Field>
            {!module && owners.length > 1 ? (
              <Field label="Ägare">
                <select name="agare" value={state.owner} onChange={(event) => set({ owner: event.currentTarget.value })}>
                  {owners.map((o) => (
                    <option key={o.id} value={o.id}>
                      {o.name}
                    </option>
                  ))}
                </select>
              </Field>
            ) : null}
            <div className="cad-rad">
              <Field label="Skala">
                <select
                  name="skala"
                  value={state.scale}
                  onChange={(event) => {
                    const chosen = event.currentTarget.value as Scale;
                    // The profiles and norms belong to a scale: the gables keep their measures only.
                    set({ scale: chosen, a: { ...state.a, profile: "", norm: "" }, b: { ...state.b, profile: "", norm: "" } });
                    onScale?.(chosen);
                  }}
                >
                  {SCALES.map((s) => (
                    <option key={s} value={s}>
                      {s}
                    </option>
                  ))}
                </select>
              </Field>
              <div className="cad-falt">
                <span>Form</span>
                <Segmented
                  label="Form"
                  value={state.kind}
                  options={[
                    ["straight", "Rak"],
                    ["curve", "Kurva"],
                    ["trapezoid", "Trapets"],
                  ]}
                  onChange={(value) => set({ kind: value })}
                />
              </div>
            </div>
            {state.kind !== "curve" ? (
              <div className="cad-rad">
                <MmInput name="langd" label="Längd" value={state.length} onChange={(v) => set({ length: v })} />
                <MmInput name="bredd" label={state.kind === "trapezoid" ? "Bredd vid A" : "Bredd"} value={state.width} onChange={(v) => set({ width: v })} />
                {state.kind === "trapezoid" ? <MmInput name="bredd-b" label="Bredd vid B" value={state.widthB} onChange={(v) => set({ widthB: v })} /> : null}
                {state.kind === "trapezoid" ? (
                  <MmInput name="forskjutning" label="Förskjutning av Kant 1 vid B" value={state.offset} onChange={(v) => set({ offset: v })} />
                ) : null}
              </div>
            ) : null}
          </fieldset>
          {state.kind === "curve" ? (
            <>
              <fieldset>
                <legend className="cad-overrubrik">Mät kurvan</legend>
                <Segmented
                  label="Mät kurvan"
                  value={state.mode}
                  options={[
                    ["chord", "Snöre och pilhöjd"],
                    ["radius", "Radie och vinkel"],
                  ]}
                  onChange={(value) => set({ mode: value })}
                />
                {state.mode === "chord" ? (
                  <>
                    <svg className="cad-snore" viewBox="0 0 400 130" aria-hidden="true">
                      <path d="M30 100Q200 -5 370 100" fill="none" className="cad-spar" strokeWidth="2" />
                      <path d="M30 100H370" className="cad-mattlinje" strokeDasharray="6 5" />
                      <path d="M200 100V48" className="cad-mattlinje" strokeWidth="3" />
                      <text x="190" y="20" fontSize="14">spår 1</text>
                      <text x="210" y="78" fontSize="14" className="cad-matt">pilhöjd</text>
                      <text x="182" y="122" fontSize="14" className="cad-matt">snöre</text>
                      <text x="22" y="122" fontSize="14">A</text>
                      <text x="364" y="122" fontSize="14">B</text>
                    </svg>
                    <MmInput name="snore" label="Snöret, A → B" value={state.chord} onChange={(v) => set({ chord: v })} />
                    <MmInput name="pilhojd" label="Pilhöjd" value={state.sagitta} onChange={(v) => set({ sagitta: v })} />
                    {found ? (
                      <div className="cad-utraknat" role="status">
                        <p>
                          Uträknat: R {found.radius.toLocaleString("sv-SE", { maximumFractionDigits: 1, minimumFractionDigits: 1 })} mm ·{" "}
                          {found.angle.toLocaleString("sv-SE", { maximumFractionDigits: 2, minimumFractionDigits: 2 })}°
                        </p>
                        <p className="cad-dampad">Radien och vinkeln används som de räknas fram ur snöret och pilhöjden, utan avrundning.</p>
                      </div>
                    ) : (
                      <p className="cad-dampad">Spänn ett snöre mellan spår 1:s mitt vid A och B och mät snöret och pilhöjden.</p>
                    )}
                  </>
                ) : (
                  <div className="cad-rad">
                    <MmInput name="radie" label="Radie till spår 1" value={state.radius} onChange={(v) => set({ radius: v })} />
                    <label className="cad-matt-falt">
                      <span>Vinkel</span>
                      <span className="cad-mm">
                        <input name="vinkel" inputMode="decimal" value={state.angle} onChange={(event) => set({ angle: event.currentTarget.value })} />
                        <span aria-hidden="true">°</span>
                      </span>
                    </label>
                  </div>
                )}
              </fieldset>
              <fieldset>
                <legend className="cad-overrubrik">Modulkroppen</legend>
                <MmInput name="bredd" label="Bredd" value={state.width} onChange={(v) => set({ width: v })} />
                <div className="cad-falt">
                  <span>Kant 1 är</span>
                  <Segmented
                    label="Kant 1 är"
                    value={state.edge}
                    options={[
                      ["outer", "Ytterkanten"],
                      ["inner", "Innerkanten"],
                    ]}
                    onChange={(value) => set({ edge: value })}
                  />
                </div>
                <div className="cad-falt">
                  <span>Lådans långsidor</span>
                  <Segmented
                    label="Lådans långsidor"
                    value={state.sides}
                    options={[
                      ["bent", "Böjda"],
                      ["straight", "Raka"],
                    ]}
                    onChange={(value) => set({ sides: value })}
                  />
                </div>
              </fieldset>
            </>
          ) : null}
          <GableFields end="A" gable={state.a} profiles={scaleProfiles} norms={norms} width={width} onChange={(g) => set({ a: g })} />
          <label className="cad-kryss">
            <input type="checkbox" name="lika" checked={state.sameB} onChange={(event) => set({ sameB: event.currentTarget.checked, b: state.a })} />
            Gavel B är likadan som gavel A
          </label>
          {!state.sameB ? (
            <GableFields end="B" gable={state.b} profiles={scaleProfiles} norms={norms} width={widthB} onChange={(g) => set({ b: g })} />
          ) : null}
          <p className="cad-info">Kant 1 är långsidan överst i ritningen. Sätt en tejpbit på den – då mäter du båda gavlarna från samma sida.</p>
          {error ? (
            <p className="cad-fel" role="alert">
              {error}
            </p>
          ) : null}
          <div className="cad-sparrad">
            <span className={dirty ? "cad-andrat" : "cad-dampad"}>{dirty ? "Ändrat · inte sparat" : "Inga ändringar"}</span>
            <span className="cad-fyll" />
            <button type="button" className="tm-knapp" onClick={() => onCancel?.()}>
              Avbryt
            </button>
            <button type="submit" className="tm-knapp primar" disabled={!ready || busy || (module != null && !dirty)}>
              Spara
            </button>
          </div>
        </form>
        <div className="cad-hoger">
          <div className="cad-kort cad-ritkort">
            <div className="cad-kortrubrik">
              <h2>Ovanifrån</h2>
              <span className="cad-dampad">{shape?.kind === "curve" ? `${state.edge === "outer" ? "högerkurva" : "vänsterkurva"} sedd från gavel A` : "mått i mm"}</span>
              <span className="cad-fyll" />
              <span className="cad-legend">
                <i className="heldragen" /> ur måtten <i className="streckad" /> okänt
              </span>
            </div>
            {shape && a && b ? (
              <ModuleDrawing shape={shape} tracks={[a, b]} gables={[labelFor(state.a, scaleProfiles, a), labelFor(state.sameB ? state.a : state.b, scaleProfiles, b)]} />
            ) : (
              <p className="cad-dampad cad-tomritning">Fyll i måtten så ritas modulen här.</p>
            )}
            {shape && a && b && JSON.stringify(a) !== JSON.stringify(b) ? (
              <p className="cad-ruta">
                <b>Spåren mellan gavlarna ritas från fotot.</b> {a.length} spår in vid A, {b.length} spår ut vid B. Hur de går emellan vet vi
                först när modulen är fotad.
              </p>
            ) : null}
          </div>
          {shape?.kind === "curve" ? (
            <div className="cad-kort">
              <div className="cad-kortrubrik">
                <h2>Uträknat</h2>
                {Number.isInteger(Math.round(circle * 100) / 100) ? <span className="cad-dampad">{Math.round(circle)} sådana moduler blir en hel cirkel</span> : null}
              </div>
              <table className="cad-tabell cad-utraknat-tabell">
                <thead>
                  <tr>
                    <th scope="col">Linje</th>
                    <th scope="col">Radie</th>
                    <th scope="col">Längd längs linjen</th>
                    <th scope="col">Rakt avstånd A → B</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => (
                    <tr key={row.line}>
                      <th scope="row">{row.line}</th>
                      <td>{mm(row.radius)}</td>
                      <td>{mm(arcLength(row.radius, shape.angle))}</td>
                      <td>{mm(toChord(row.radius, shape.angle).chord)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : shape && a && b ? (
            <div className="cad-gavelpar">
              <div className="cad-kort">
                <div className="cad-kortrubrik">
                  <h2>Gavel A</h2>
                  <span className="cad-dampad">sedd utifrån · Kant 1 till vänster</span>
                </div>
                <GableView end="A" width={width} tracks={a} />
              </div>
              <div className="cad-kort">
                <div className="cad-kortrubrik">
                  <h2>Gavel B</h2>
                  <span className="cad-dampad">sedd utifrån · Kant 1 till höger</span>
                </div>
                <GableView end="B" width={widthB} tracks={b} />
              </div>
            </div>
          ) : null}
        </div>
      </div>
    </section>
  );
}

function labelFor(g: GableState, profiles: GableProfile[], tracks: number[]): string {
  const profile = profiles.find((p) => p.id === g.profile);
  if (profile) return profile.name;
  return tracks.length ? `Egen gavel · ${tracks.length} spår` : "Utan spår";
}
