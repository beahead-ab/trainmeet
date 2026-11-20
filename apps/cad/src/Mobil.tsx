// CAD i mobilen (#90, CAD1, CADMOB-01–16): the phone's own pages under /m, started with the QR code
// from Fota med mobilen on the computer. The steps are those of the views Mobil-Start to Mobil-Klar:
// 0 Välj väg, 1 Mått (1b Kurva), 2 Gavlar, 3 Fota, 4 Kontroll, 4b AI:n frågar and 5 Klart. The phone
// keeps nothing of its own (CADMOB-05): the measures and the photos go into the same module as the
// web's, through CAD's own addresses, and everything AI does is a proposal until the owner approves
// (CADMOB-09). The pages are pure (props in, events out) so the tests can render them; MobileApp
// holds the state and talks to CAD.
import { useCallback, useEffect, useRef, useState, type PointerEvent as ReactPointerEvent, type ReactNode } from "react";
import {
  api,
  ApiError,
  idLoginHref,
  SCALES,
  type CheckItem,
  type MobileFlow,
  type Module,
  type PhotoConsent,
  type PhotoJob,
  type PhotoMeasure,
  type PhotoQuestion,
  type PhotoStart,
  type ProfileList,
  type Session,
} from "./api";
import { bendText, count } from "./common";
import { f, GableView, ModuleDrawing } from "./Drawing";
import { PhotoImage, PriceText, Sketch, SketchUpload, tapSide } from "./Foto";
import { Kamera } from "./Kamera";
import {
  answerOps,
  bendOf,
  EMPTY_DRAFT,
  gableB,
  gablesReady,
  measureChange,
  measuresReady,
  nearGable,
  newModuleOf,
  num,
  openChecks,
  openTopology,
  phoneChoices,
  photoFirst,
  photoStartFor,
  photoStartOf,
  resumePath,
  stepOf,
  withGables,
  withProfile,
  type Draft,
} from "./mobilflode";
import { fixedSteps, tracksOf, type GableState } from "./ModuleForm";
import type { Point } from "./geometry";
import "./mobil.css";
import { isMobilePath, MOBILE_ROOT, mobilePath, mobileRouteFor, PATHS, type MobileRoute } from "./routes";

const nr = (value: number, digits = 1) => value.toLocaleString("sv-SE", { maximumFractionDigits: digits, useGrouping: false });

export const NO_CODE = "Öppna Fota med mobilen på datorn och skanna QR-koden med mobilens kamera.";

// --- The frame: the header, the steps and the button at the bottom ---------------------------------

type Back = { label: string; onClick: () => void; cancel?: boolean };

const STEPS: [string, string][] = [
  ["matt", "Mått"],
  ["gavlar", "Gavlar"],
  ["fota", "Foto"],
  ["kontroll", "Kontroll"],
];

/** 1 Mått · 2 Gavlar · 3 Foto · 4 Kontroll, with the steps done ticked. */
export function Stepper({ at }: { at: "matt" | "gavlar" | "fota" | "kontroll" }) {
  const here = STEPS.findIndex(([key]) => key === at);
  return (
    <ol className="mob-steg" aria-label="Stegen">
      {STEPS.map(([key, label], i) => (
        <li key={key} className={i < here ? "klar" : i === here ? "har" : undefined} aria-current={i === here ? "step" : undefined}>
          {i < here ? "✓" : i + 1} {label}
        </li>
      ))}
    </ol>
  );
}

export function MobileFrame({
  title,
  back,
  steps,
  dark = false,
  children,
  footer,
}: {
  title: string;
  back?: Back;
  steps?: ReactNode;
  dark?: boolean;
  children: ReactNode;
  footer?: ReactNode;
}) {
  return (
    <div className={`mob-app${dark ? " mork" : ""}`}>
      <header className="mob-huvud">
        {back ? (
          <button type="button" className="mob-tillbaka" onClick={back.onClick}>
            <span aria-hidden="true">{back.cancel ? "✕" : "‹"}</span> {back.label}
          </button>
        ) : (
          <span />
        )}
        <h1 id="rubrik">{title}</h1>
        <span />
      </header>
      {steps}
      <main id="innehall" className="mob-innehall">
        {children}
      </main>
      {footer ? <footer className="mob-botten">{footer}</footer> : null}
    </div>
  );
}

function Problem({ error }: { error?: string | null }) {
  return error ? (
    <p className="cad-fel" role="alert">
      {error}
    </p>
  ) : null;
}

function Info({ children }: { children: ReactNode }) {
  return (
    <p className="mob-info">
      <span aria-hidden="true">ⓘ</span> {children}
    </p>
  );
}

// --- The code from the QR code, or why there is none -----------------------------------------------

export function EntryPage({ failed, login }: { failed?: string | null; login?: string }) {
  return (
    <MobileFrame title="TrainMeet CAD">
      {failed ? (
        <div className="cad-kort mob-kort">
          <h2>Koden gäller inte</h2>
          <p>{failed}</p>
          {login ? (
            <a className="tm-knapp primar mob-bred" href={login}>
              Logga in här i stället
            </a>
          ) : null}
        </div>
      ) : (
        <p role="status">Öppnar CAD i mobilen …</p>
      )}
    </MobileFrame>
  );
}

function Loading() {
  return (
    <MobileFrame title="TrainMeet CAD">
      <p role="status">Hämtar …</p>
    </MobileFrame>
  );
}

export function EndedPage() {
  return (
    <MobileFrame title="TrainMeet CAD">
      <div className="cad-kort mob-kort">
        <h2>Klart i mobilen</h2>
        <p>Mobilen är utloggad. Allt du gjorde finns i modulbiblioteket på datorn. Du kan stänga fliken.</p>
      </div>
    </MobileFrame>
  );
}

// --- 0 Välj väg -------------------------------------------------------------------------------------

export function StartPage({
  name,
  tokens,
  onChoose,
  onCancel,
}: {
  /** Whose the phone's session is: a QR code from someone else's screen shows up here. */
  name?: string;
  tokens?: number | null;
  onChoose: (way: "foto" | "skiss" | "matt") => void;
  onCancel?: () => void;
}) {
  const way = (key: "foto" | "skiss" | "matt", icon: string, title: string, text: string, tags: ReactNode, first = false) => (
    <button type="button" className={`mob-vag${first ? " forst" : ""}`} onClick={() => onChoose(key)}>
      <span className="mob-vag-ikon" aria-hidden="true">
        {icon}
      </span>
      <span>
        <b>{title}</b>
        <span>{text}</span>
        <span className="cad-taggar">{tags}</span>
      </span>
    </button>
  );
  return (
    <MobileFrame title="Ny modul" back={onCancel ? { label: "Avbryt", onClick: onCancel, cancel: true } : undefined}>
      <h2 className="mob-fraga">Hur vill du börja?</h2>
      <div className="mob-vagar">
        {way(
          "foto",
          "◉",
          "Fota modulen",
          "Mät, fota uppifrån och låt AI:n rita spåren.",
          <>
            <span className="cad-tagg">◎ 12 tokens</span> <span className="cad-tagg">ca 10 min</span>
          </>,
          true,
        )}
        {way("skiss", "✎", "Fota en skiss", "Handritad spårplan med modulramar. Mått ± 20 mm.", <span className="cad-tagg">◎ 12 tokens per bild</span>)}
        {way("matt", "📏", "Bara mått nu", "Längd, bredd och gavlar. Fota senare.", <span className="cad-tagg gron">Gratis</span>)}
      </div>
      <p className="mob-saldo">
        {name ? (
          <>
            Inloggad som <b>{name}</b>.{" "}
          </>
        ) : null}
        {tokens != null ? (
          <>
            ◎ Du har <b>{tokens} tokens</b> kvar.
          </>
        ) : null}
      </p>
      <Info>Ta med tumstock och en tejpbit. Tejpen markerar Kant 1, som alla gavelmått räknas från.</Info>
    </MobileFrame>
  );
}

// --- 1 Mått and 1b Kurva ----------------------------------------------------------------------------

function Segment<T extends string>({ label, value, options, onChange }: { label: string; value: T; options: [T, string][]; onChange: (v: T) => void }) {
  return (
    <div className="cad-segment mob-segment" role="radiogroup" aria-label={label}>
      {options.map(([key, text]) => (
        <button key={key} type="button" role="radio" aria-checked={value === key} onClick={() => onChange(key)}>
          {text}
        </button>
      ))}
    </div>
  );
}

function Mm({
  label,
  name,
  value,
  placeholder,
  onChange,
}: {
  label: string;
  name: string;
  value: string;
  placeholder?: string;
  onChange: (v: string) => void;
}) {
  return (
    <label className="mob-mm">
      <span>{label}</span>
      <span className="mob-mm-falt">
        <input name={name} inputMode="decimal" value={value} placeholder={placeholder} onChange={(event) => onChange(event.currentTarget.value)} />
        <span aria-hidden="true">mm</span>
      </span>
    </label>
  );
}

/** The module from above with Kant 1, the length and the width, as the view Mobil-Matt. */
function MeasureSketch({ draft }: { draft: Draft }) {
  const length = num(draft.length) > 0 ? num(draft.length) : null;
  const width = num(draft.width) > 0 ? num(draft.width) : null;
  return (
    <svg className="mob-skiss" viewBox="0 0 340 150" role="img" aria-label="Modulen ovanifrån med Kant 1">
      <text x={60} y={14} className="mob-skiss-kant">
        KANT 1
      </text>
      <rect x={20} y={22} width={240} height={90} className="mob-skiss-skiva" />
      <path d="M20 22H260" className="mob-skiss-kant1" />
      <rect x={34} y={18} width={14} height={8} rx={2} className="mob-skiss-tejp" />
      <path d="M284 22V112M278 22H290M278 112H290" className="mob-skiss-matt" />
      <text x={296} y={72} className="mob-skiss-tal">
        {width != null ? nr(width, 0) : "bredd"}
      </text>
      <path d="M20 136H260M20 130V142M260 130V142" className="mob-skiss-matt" />
      <text x={140} y={130} textAnchor="middle" className="mob-skiss-tal">
        {length != null ? `längd ${nr(length, 0)}` : draft.mode === "foto" ? "längd ur fotot" : "längd"}
      </text>
      <text x={20} y={126} className="mob-skiss-gavel">
        A
      </text>
      <text x={260} y={126} textAnchor="end" className="mob-skiss-gavel">
        B
      </text>
    </svg>
  );
}

/** The string from track 1's middle at A to that at B, and the sagitta: the view Mobil-Kurva. */
function CurveSketch() {
  return (
    <svg className="mob-skiss" viewBox="0 0 340 120" role="img" aria-label="Snöret och pilhöjden på spår 1">
      <text x={170} y={14} textAnchor="middle" className="mob-skiss-gavel">
        spår 1 (närmast Kant 1)
      </text>
      <path d="M30 92Q170 10 310 92" className="mob-skiss-spar" />
      <path d="M30 92H310" className="mob-skiss-snore" />
      <path d="M170 92V51" className="mob-skiss-matt" />
      <text x={178} y={74} className="mob-skiss-tal">
        pilhöjd
      </text>
      <text x={170} y={110} textAnchor="middle" className="mob-skiss-tal">
        snöre
      </text>
      <circle cx={30} cy={92} r={6} className="mob-skiss-punkt" />
      <circle cx={310} cy={92} r={6} className="mob-skiss-punkt" />
      <text x={24} y={114} className="mob-skiss-gavel">
        A
      </text>
      <text x={316} y={114} textAnchor="end" className="mob-skiss-gavel">
        B
      </text>
    </svg>
  );
}

export function MeasuresPage({
  draft,
  onDraft,
  onNext,
  onCancel,
}: {
  draft: Draft;
  onDraft: (draft: Draft) => void;
  onNext: () => void;
  onCancel: () => void;
}) {
  const set = (change: Partial<Draft>) => onDraft({ ...draft, ...change });
  const bend = draft.kind === "curve" ? bendOf(draft) : null;
  return (
    <MobileFrame
      title={draft.kind === "curve" && draft.name.trim() ? draft.name : "Ny modul"}
      back={{ label: "Avbryt", onClick: onCancel, cancel: true }}
      steps={<Stepper at="matt" />}
      footer={
        <button type="button" className="tm-knapp primar mob-bred" disabled={!measuresReady(draft)} onClick={onNext}>
          Nästa: gavlarna →
        </button>
      }
    >
      <label className="mob-falt">
        <span>Namn</span>
        <input name="mobil-namn" maxLength={80} value={draft.name} onChange={(event) => set({ name: event.currentTarget.value })} />
      </label>
      <div className="mob-falt">
        <span>Skala</span>
        <Segment label="Skala" value={draft.scale} options={SCALES.map((s) => [s, s])} onChange={(scale) => set({ scale })} />
      </div>
      <div className="mob-falt">
        <span>Form</span>
        <Segment
          label="Form"
          value={draft.kind}
          options={[
            ["straight", "▭ Rak"],
            ["curve", "◠ Kurva"],
          ]}
          onChange={(kind) => set({ kind })}
        />
      </div>
      {draft.kind === "straight" ? (
        <>
          <div className="cad-kort mob-kort">
            <MeasureSketch draft={draft} />
          </div>
          <div className="mob-par">
            <Mm
              label="Längd"
              name="mobil-langd"
              value={draft.length}
              placeholder={draft.mode === "foto" ? "ur fotot" : undefined}
              onChange={(length) => set({ length })}
            />
            <Mm label="Bredd" name="mobil-bredd" value={draft.width} onChange={(width) => set({ width })} />
          </div>
          <Info>
            Mät längden mellan gavlarnas ytterkanter. Sätt en tejpbit på Kant 1: båda gavlarna mäts från den.
            {draft.mode === "foto" ? " Vet du bara bredden? Lämna längden tom, så räknas den fram ur fotot." : ""}
          </Info>
        </>
      ) : (
        <>
          <div className="cad-kort mob-kort">
            <CurveSketch />
            <ol className="mob-lista">
              <li>Spänn ett snöre mellan spår 1:s mitt vid A och vid B.</li>
              <li>Mät snöret.</li>
              <li>Mät från snörets mitt rakt in till spår 1:s mitt.</li>
            </ol>
          </div>
          <div className="mob-par">
            <Mm label="Snöret A → B" name="mobil-korda" value={draft.chord} onChange={(chord) => set({ chord })} />
            <Mm label="Pilhöjd" name="mobil-pilhojd" value={draft.sagitta} onChange={(sagitta) => set({ sagitta })} />
          </div>
          {bend ? (
            <div className="mob-resultat" role="status">
              <span>Radie spår 1 och vinkel</span>
              <b>{bendText(bend.radius, bend.angle)}</b>
              <span className="cad-dampad">Exakt som snöret och pilhöjden ger, utan avrundning.</span>
            </div>
          ) : null}
          <div className="mob-par">
            <Mm label="Bredd" name="mobil-bredd" value={draft.width} onChange={(width) => set({ width })} />
            <div className="mob-falt">
              <span>Kant 1 är</span>
              <Segment
                label="Kant 1 är"
                value={draft.edge}
                options={[
                  ["outer", "Ytterkanten"],
                  ["inner", "Innerkanten"],
                ]}
                onChange={(edge) => set({ edge })}
              />
            </div>
          </div>
        </>
      )}
    </MobileFrame>
  );
}

// --- 2 Gavlar ---------------------------------------------------------------------------------------

export function GablesPage({
  draft,
  profiles,
  busy,
  error,
  onDraft,
  onNext,
  onBack,
}: {
  draft: Draft;
  profiles: ProfileList | null;
  busy?: boolean;
  error?: string | null;
  onDraft: (draft: Draft) => void;
  onNext: () => void;
  onBack: () => void;
}) {
  const [end, setEnd] = useState<"A" | "B">("A");
  const width = num(draft.width) || 500;
  const gable = end === "A" ? draft.a : gableB(draft);
  const choices = (profiles?.profiles ?? []).filter((p) => p.scale === draft.scale);
  const profile = choices.find((p) => p.id === gable.profile);
  const fixed = profile ? fixedSteps(profile) : [];
  const tracks = tracksOf(gable);
  const change = (next: GableState) => {
    if (end === "A") onDraft({ ...draft, a: next, b: draft.sameB ? next : draft.b });
    else onDraft({ ...draft, b: next, sameB: false });
  };
  const doneA = tracksOf(draft.a) !== null;
  const describe = (g: GableState) =>
    choices.find((p) => p.id === g.profile)?.name ?? (tracksOf(g) ? `Egen gavel · ${count(g.steps.length, "spår", "spår")}` : "mäts nu");
  return (
    <MobileFrame
      title={draft.name || "Ny modul"}
      back={{ label: "Mått", onClick: onBack }}
      steps={<Stepper at="gavlar" />}
      footer={
        <button type="button" className="tm-knapp primar mob-bred" disabled={busy || !gablesReady(draft)} onClick={onNext}>
          {busy ? "Sparar …" : draft.mode === "matt" ? "Spara modulen" : "Nästa: fota modulen →"}
        </button>
      }
    >
      <div className="mob-gavelval" role="tablist" aria-label="Gaveln">
        {(["A", "B"] as const).map((e) => (
          <button key={e} type="button" role="tab" aria-selected={end === e} onClick={() => setEnd(e)}>
            <b>
              Gavel {e} {(e === "A" ? doneA : tracksOf(gableB(draft)) !== null) ? <span className="cad-ok">✓</span> : null}
            </b>
            <span>{e === "B" && draft.sameB ? "som gavel A" : describe(e === "A" ? draft.a : gableB(draft))}</span>
          </button>
        ))}
      </div>
      {end === "B" ? (
        <label className="cad-kryss">
          <input
            type="checkbox"
            name="mobil-lika"
            checked={draft.sameB}
            onChange={(event) => onDraft({ ...draft, sameB: event.currentTarget.checked, b: draft.a })}
          />
          Gavel B är som gavel A
        </label>
      ) : null}
      <div className="mob-falt">
        <span>Profil</span>
        <div className="mob-profiler">
          {profiles === null ? <p className="cad-dampad">Hämtar gavelprofilerna …</p> : null}
          {choices.map((p) => (
            <button key={p.id} type="button" aria-pressed={gable.profile === p.id} onClick={() => change(withProfile(gable, p, width))}>
              {p.name}
            </button>
          ))}
          <button type="button" className="mob-egen" aria-pressed={gable.profile === ""} onClick={() => change({ ...gable, profile: "", norm: "" })}>
            Egen gavel – mät spår för spår
          </button>
        </div>
      </div>
      {tracks ? (
        <div className="cad-kort mob-kort">
          <GableView end={end} width={width} tracks={tracks} />
          <span className="cad-dampad">sedd utifrån gavel {end}</span>
        </div>
      ) : null}
      {gable.steps.map((step, i) => (
        <div key={i} className="mob-gavelrad">
          <span>{i === 0 ? "Kant 1 → spår 1" : `Spår ${i} → spår ${i + 1}`}</span>
          <span className="mob-mm-falt">
            <input
              name={`mobil-gavel-${end}-${i}`}
              inputMode="decimal"
              value={step}
              readOnly={fixed[i] != null}
              aria-label={i === 0 ? `Gavel ${end}: Kant 1 till spår 1` : `Gavel ${end}: spår ${i} till spår ${i + 1}`}
              onChange={(event) => {
                const value = event.currentTarget.value;
                change({ ...gable, steps: gable.steps.map((s, k) => (k === i ? value : s)) });
              }}
            />
            <span aria-hidden="true">mm</span>
          </span>
        </div>
      ))}
      {profile ? (
        <p className="cad-dampad">{profile.note}</p>
      ) : (
        <div className="mob-gavelrad">
          <button type="button" className="cad-lank" onClick={() => change({ ...gable, steps: [...gable.steps, "50"] })}>
            + Lägg till spår
          </button>
          {gable.steps.length > 1 ? (
            <button type="button" className="cad-lank" onClick={() => change({ ...gable, steps: gable.steps.slice(0, -1) })}>
              Ta bort spår
            </button>
          ) : null}
        </div>
      )}
      {tracks ? (
        <p className="cad-dampad">
          Spår {tracks.length} är {nr(tracks[tracks.length - 1] ?? 0, 0)} mm från Kant 1
        </p>
      ) : null}
      <Problem error={error} />
    </MobileFrame>
  );
}

// --- 3 Fota: the camera, then the corners, Kant 1 and gable A, and the price ------------------------

export function PhotoStepPage({
  title,
  busy,
  error,
  onPhotos,
  back,
  camera,
}: {
  title: string;
  busy?: boolean;
  error?: string | null;
  onPhotos: (files: File[]) => void;
  back?: Back;
  camera?: Parameters<typeof Kamera>[0]["initial"];
}) {
  return (
    <MobileFrame title={title} back={back} steps={<Stepper at="fota" />} dark>
      <Kamera busy={busy} onPhotos={onPhotos} initial={camera} />
      <Problem error={error} />
    </MobileFrame>
  );
}

const sideMiddle = (corners: Point[], side: number): Point => {
  const a = corners[side % 4] ?? [0, 0];
  const b = corners[(side + 1) % 4] ?? [0, 0];
  return [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
};
const opposite = (side: number) => (side + 2) % 4;

/** The corners as handles with a magnifier, and the sides to tap for Kant 1 and gable A. */
export function CornerHandles({
  job,
  corners,
  kant1,
  gableA,
  onCorners,
  onSide,
}: {
  job: PhotoJob;
  corners: Point[];
  kant1: number;
  gableA: number;
  onCorners: (corners: Point[]) => void;
  onSide: (side: number) => void;
}) {
  const svg = useRef<SVGSVGElement>(null);
  const [dragging, setDragging] = useState<number | null>(null);
  const preview = job.preview;
  if (!preview) return <p className="cad-dampad">Fotot finns inte längre.</p>;
  const unit = Math.max(preview.width, preview.height) / 100;
  const at = (event: ReactPointerEvent): Point | null => {
    const box = svg.current?.getBoundingClientRect();
    if (!box || !box.width) return null;
    return [((event.clientX - box.left) / box.width) * preview.width, ((event.clientY - box.top) / box.height) * preview.height];
  };
  const move = (event: ReactPointerEvent) => {
    if (dragging === null) return;
    const p = at(event);
    if (p) onCorners(corners.map((c, i) => (i === dragging ? [Math.round(p[0] * 10) / 10, Math.round(p[1] * 10) / 10] : c)));
  };
  const held = dragging !== null ? corners[dragging] : undefined;
  const zoom = unit * 9;
  const kant = sideMiddle(corners, kant1);
  const gable = sideMiddle(corners, gableA);
  return (
    <div className="mob-hornbild">
      <svg
        ref={svg}
        className="cad-fotobild mob-foto"
        viewBox={`0 0 ${preview.width} ${preview.height}`}
        role="img"
        aria-label="Fotot med modulens hörn"
        onPointerMove={move}
        onPointerUp={() => setDragging(null)}
        onPointerCancel={() => setDragging(null)}
      >
        <image href={preview.url} width={preview.width} height={preview.height} />
        {corners.map((c, side) => {
          const next = corners[(side + 1) % 4] ?? c;
          return (
            <g key={`sida${side}`} data-sida={side} onClick={() => onSide(side)}>
              <line className="mob-sida-yta" x1={c[0]} y1={c[1]} x2={next[0]} y2={next[1]} strokeWidth={unit * 6} />
              <line
                className={side === kant1 ? "cad-fotokant1" : side === gableA ? "cad-fotogavela" : "cad-fotosida"}
                x1={c[0]}
                y1={c[1]}
                x2={next[0]}
                y2={next[1]}
                strokeWidth={unit * 1.2}
              />
            </g>
          );
        })}
        {corners.map((c, i) => (
          <circle
            key={`horn${i}`}
            className="cad-fotohorn"
            data-horn={i}
            cx={c[0]}
            cy={c[1]}
            r={unit * 2.2}
            strokeWidth={unit * 0.6}
            onPointerDown={(event) => {
              event.currentTarget.ownerSVGElement?.setPointerCapture?.(event.pointerId);
              setDragging(i);
            }}
          />
        ))}
        <g className="cad-fototexter" fontSize={unit * 3.4}>
          <text x={kant[0]} y={kant[1] - unit * 2.2} textAnchor="middle">
            KANT 1
          </text>
          <text x={gable[0]} y={gable[1]} textAnchor="middle">
            GAVEL A
          </text>
        </g>
      </svg>
      {held ? (
        <svg className={held[0] < preview.width / 2 && held[1] < preview.height / 2 ? "mob-lupp hoger" : "mob-lupp"} viewBox={`${f(held[0] - zoom)} ${f(held[1] - zoom)} ${f(2 * zoom)} ${f(2 * zoom)}`} aria-label="Luppen" role="img">
          <image href={preview.url} width={preview.width} height={preview.height} />
          <path
            d={`M${f(held[0] - zoom)} ${f(held[1])}H${f(held[0] + zoom)}M${f(held[0])} ${f(held[1] - zoom)}V${f(held[1] + zoom)}`}
            className="mob-lupp-kors"
            strokeWidth={unit * 0.25}
          />
        </svg>
      ) : null}
    </div>
  );
}

export function CornersPage({
  module,
  job,
  consent,
  busy,
  error,
  onRead,
  onRetake,
}: {
  module: Module;
  job: PhotoJob;
  consent: PhotoConsent | null;
  busy?: boolean;
  error?: string | null;
  onRead: (corners: Point[], kant1: number, ai: boolean, consent: boolean, gableA: number, frame?: number) => void;
  onRetake: () => void;
}) {
  const start = (job.corners?.corners ?? []) as Point[];
  const [corners, setCorners] = useState<Point[]>(start);
  const [kant1, setKant1] = useState(job.corners?.kant1 ?? 0);
  const [gableA, setGableA] = useState(job.corners?.gable_a ?? ((job.corners?.kant1 ?? 0) + 3) % 4);
  const [chosen, setChosen] = useState(Boolean(job.corners?.derived));
  const [frame, setFrame] = useState<number | undefined>(job.frames?.length ? Math.max(0, job.frame ?? 0) : undefined);
  const [agreed, setAgreed] = useState(false);
  const aiPossible = Boolean(consent?.available && consent.may_read);
  const needsYes = aiPossible && !consent?.given;
  const sketch = job.profile === "skiss";
  const side = (tapped: number) => {
    const next = tapSide(tapped, kant1, gableA, chosen);
    if (tapped !== kant1 && tapped !== opposite(kant1)) setChosen(true);
    setKant1(next.kant1);
    setGableA(next.gableA);
  };
  const derived = job.corners?.derived;
  return (
    <MobileFrame
      title={sketch ? "Skissen" : "Hörnen och Kant 1"}
      back={{ label: "Ta om", onClick: onRetake }}
      steps={<Stepper at="fota" />}
      footer={
        <div className="mob-knappar">
          {aiPossible ? (
            <button
              type="button"
              className="tm-knapp primar mob-bred"
              disabled={busy || corners.length !== 4 || (needsYes && !agreed)}
              onClick={() => onRead(corners, kant1, true, needsYes && agreed, gableA, frame)}
            >
              {consent?.price ? `Läs av med AI · ${consent.price} tokens` : "Läs av med AI"}
            </button>
          ) : null}
          <button
            type="button"
            className={aiPossible ? "tm-knapp mob-bred" : "tm-knapp primar mob-bred"}
            disabled={busy || corners.length !== 4}
            onClick={() => onRead(corners, kant1, false, false, gableA, frame)}
          >
            Läs av utan AI · gratis
          </button>
        </div>
      }
    >
      <p className="mob-chip-rad">
        <span className={`mob-chip${job.corners?.found ? " ok" : ""}`}>{job.corners?.found ? "✓ 4 av 4 hörn hittade" : "Dra hörnen till modulens hörn"}</span>
      </p>
      {sketch && job.frames?.length ? (
        <div className="cad-knapprad" role="radiogroup" aria-label="Modulens ram">
          {job.frames.map((found, index) => (
            <button
              key={index}
              type="button"
              role="radio"
              aria-checked={frame === index}
              className="tm-knapp liten"
              onClick={() => {
                setFrame(index);
                setCorners(found.corners as Point[]);
                setKant1(found.kant1);
                setGableA((found.kant1 + 3) % 4);
              }}
            >
              Ram {index + 1}
            </button>
          ))}
        </div>
      ) : null}
      {corners.length === 4 ? <CornerHandles job={job} corners={corners} kant1={kant1} gableA={gableA} onCorners={setCorners} onSide={side} /> : null}
      <p className={derived ? "mob-info" : "cad-dampad"} role={derived ? "status" : undefined}>
        {derived
          ? "Kant 1 och gavel A är lästa ur gavlarnas spår. Tryck på en annan sida om det är fel."
          : "Dra hörnen rätt där landskapet hänger över kanten. Tryck sedan på den långsida som är Kant 1 och på gavel A."}{" "}
        {gableA === (kant1 + 3) % 4
          ? "Från gavel A längs Kant 1 ligger modulen till höger."
          : "Speglad: från gavel A längs Kant 1 ligger modulen till vänster."}
      </p>
      <div className="cad-knapprad">
        <button type="button" className="tm-knapp liten" onClick={() => side(opposite(kant1))}>
          Andra långsidan som Kant 1
        </button>
        <button
          type="button"
          className="tm-knapp liten"
          onClick={() => {
            setGableA(opposite(gableA));
            setChosen(true);
          }}
        >
          Gavel A i andra änden
        </button>
      </div>
      <div className="cad-kort mob-kort">
        <h2 className="cad-overrubrik">Innan fotot läses av</h2>
        <p className="cad-dampad">
          {module.name} · {module.scale}
        </p>
        <PriceText consent={consent} />
        {needsYes ? (
          <div className="cad-samtycke" role="group" aria-label="Vad som skickas">
            <p>{consent?.text}</p>
            <label className="cad-kryss">
              <input type="checkbox" name="mobil-samtycke" checked={agreed} onChange={(event) => setAgreed(event.currentTarget.checked)} />
              Jag godkänner att mätbilden skickas till {consent?.sent_to}.
            </label>
          </div>
        ) : null}
        <p className="cad-dampad">Utan AI svarar du själv på vilka spår som hänger ihop. Allt är ett förslag tills du godkänner spårplanen.</p>
      </div>
      <Problem error={error ?? job.message} />
    </MobileFrame>
  );
}

// --- 4 Kontroll -------------------------------------------------------------------------------------

function MeasureCard({ measure, busy, onUse }: { measure: PhotoMeasure; busy?: boolean; onUse: (value: number) => void }) {
  const [kept, setKept] = useState(false);
  const [again, setAgain] = useState<string | null>(null);
  if (kept) return null;
  const owner = measure.owner != null ? nr(measure.owner) : "–";
  const photo = nr(measure.photo);
  const off = measure.owner != null ? Math.abs(measure.owner - measure.photo) : null;
  const usable = (measure.gable && measure.track) || measure.key === "langd";
  return (
    <div className="cad-kort mob-avviker">
      <div className="mob-avviker-topp">
        <b>{measure.label}</b>
        <span className="tm-mono">
          du {owner} · foto ≈ {photo}
        </span>
      </div>
      <p>{off != null ? `${nr(off)} mm ifrån, mer än fotots ± ${nr(measure.plus_minus)} mm.` : "Du har inget mått här."}</p>
      {again !== null ? (
        <div className="mob-par">
          <Mm label="Uppmätt" name={`mobil-matt-om-${measure.key}`} value={again} onChange={setAgain} />
          <button type="button" className="tm-knapp" disabled={busy || !(num(again) > 0)} onClick={() => onUse(num(again))}>
            Spara
          </button>
        </div>
      ) : (
        <div className="mob-tre">
          {usable ? (
            <button type="button" className="tm-knapp" onClick={() => setAgain("")}>
              Mät om
            </button>
          ) : null}
          {usable ? (
            <button type="button" className="tm-knapp" disabled={busy} onClick={() => onUse(measure.photo)}>
              Använd {photo}
            </button>
          ) : null}
          {measure.owner != null ? (
            <button type="button" className="tm-knapp" onClick={() => setKept(true)}>
              Behåll {owner}
            </button>
          ) : null}
        </div>
      )}
    </div>
  );
}

export type Measure = { gable?: "A" | "B"; track?: number; length?: number; value?: number };

export function CheckPage({
  module,
  job,
  busy,
  error,
  onUseMeasure,
  onAnswer,
  onQuestion,
  onApprove,
  onLater,
  onBack,
}: {
  module: Module;
  job: PhotoJob;
  busy?: boolean;
  error?: string | null;
  onUseMeasure: (measure: Measure) => void;
  onAnswer: (key: string, answer: string) => void;
  onQuestion: (key: string) => void;
  onApprove: (answers: Record<string, string>) => void;
  onLater: () => void;
  onBack: () => void;
}) {
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const reading = job.state === "queued" || job.state === "running";
  const measures = job.measures ?? [];
  const off = measures.filter((m) => !m.agrees);
  const agree = measures.filter((m) => m.agrees);
  const topology = openTopology(job);
  const others = (job.questions ?? []).filter((q) => !q.topology && !q.answer);
  const checks = openChecks(module);
  const unanswerable = checks.filter((item) => phoneChoices(item).length === 0);
  const waiting = checks.filter((item) => phoneChoices(item).length > 0 && !answers[item.key]);
  const ready = job.state === "done" && topology.length === 0 && unanswerable.length === 0 && waiting.length === 0 && module.version === module.latest;
  const summary = job.summary;
  const lengthCard = !job.length_given && job.length != null && module.shape.kind !== "curve";
  const sketch = job.profile === "skiss";
  return (
    <MobileFrame
      title={module.name}
      back={{ label: "Foto", onClick: onBack }}
      steps={<Stepper at="kontroll" />}
      footer={
        job.state === "done" ? (
          <div className="mob-knappar">
            <button type="button" className="tm-knapp primar mob-bred" disabled={busy || !ready} onClick={() => onApprove(answers)}>
              Godkänn spårplanen
            </button>
            <button type="button" className="cad-lank" onClick={onLater}>
              Spara som förslag och fortsätt senare
            </button>
          </div>
        ) : undefined
      }
    >
      {reading ? (
        <div className="cad-kort mob-kort" role="status" aria-live="polite">
          <h2>{job.state === "queued" ? "Väntar i kön" : "Läser av fotot"}</h2>
          <progress max={100} value={job.progress} aria-label="Hur långt det har kommit" />
          <p>
            {job.step} · {job.progress} %
          </p>
          <p className="cad-dampad">Det tar ungefär en halv minut. Du kan lägga ifrån dig telefonen; datorn följer med.</p>
        </div>
      ) : null}
      {job.state === "failed" ? (
        <div className="cad-kort mob-kort">
          <h2>Fotot gick inte att läsa</h2>
          <p>{job.message ?? "Ta ett nytt foto."}</p>
        </div>
      ) : null}
      {job.state === "done" ? (
        <>
          <div className="cad-kort mob-kort">
            <div className="mob-kortrubrik">
              <h2>{sketch ? "Spåren ur skissen" : job.ai ? "Spåren AI:n ritade" : "Spåren ur fotot"}</h2>
              <span className="cad-tagg forslag">förslag</span>
            </div>
            <ModuleDrawing
              shape={module.shape}
              tracks={[module.gables[0]?.tracks ?? [], module.gables[1]?.tracks ?? []]}
              graph={module.graph}
              small
              title="Spårplanen ovanifrån"
            />
          </div>
          {measures.length ? (
            <h2 className="mob-summa">
              <span className={off.length ? "cad-varning" : "cad-ok"} aria-hidden="true">
                {off.length ? "!" : "✓"}
              </span>{" "}
              {agree.length} av {measures.length} mått stämmer
            </h2>
          ) : null}
          {off.map((m) => (
            <MeasureCard
              key={`${m.key}-${module.latest}`}
              measure={m}
              busy={busy}
              onUse={(value) => onUseMeasure(m.key === "langd" ? { length: value } : { gable: m.gable ?? undefined, track: m.track ?? undefined, value })}
            />
          ))}
          {agree.length ? (
            <details className="cad-kort mob-kort">
              <summary>
                <span className="cad-ok">✓</span> {count(agree.length, "mått stämmer", "mått stämmer")}
              </summary>
              <ul className="mob-lista">
                {agree.map((m) => (
                  <li key={m.key}>
                    {m.label}: {m.owner != null ? nr(m.owner) : "–"} · ≈ {nr(m.photo)}
                  </li>
                ))}
              </ul>
            </details>
          ) : null}
          {lengthCard && job.length != null ? (
            <div className="cad-kort mob-kort">
              <h2>Längden ur fotot</h2>
              <p className="cad-stortal">
                <b>{nr(job.length, 0)}</b> mm <span className="cad-dampad">± {nr(job.length_plus_minus ?? 0)} mm</span>
              </p>
              <p className="cad-dampad">
                {job.sleepers?.agree
                  ? `Kontrollerad med sliperdelningen, ${nr(job.sleepers.straight ?? 0, 2)} mm på raka och sneda spår.`
                  : job.sleepers?.straight != null
                    ? `Sliperdelningen ${nr(job.sleepers.straight, 2)} mm; inget snett spår att jämföra med.`
                    : "Längden vilar på hörnen och bredden."}
              </p>
              {module.shape.kind === "straight" && Math.abs(module.shape.length - job.length) > 0.5 ? (
                <button type="button" className="tm-knapp" disabled={busy} onClick={() => onUseMeasure({ length: job.length ?? undefined })}>
                  Använd {nr(job.length, 0)} mm
                </button>
              ) : (
                <p className="cad-ok">✓ Modulen har längden ur fotot.</p>
              )}
            </div>
          ) : null}
          {topology.length ? (
            <div className="cad-kort mob-kort mob-fragekort">
              <h2>
                <span aria-hidden="true">⚠</span> AI:n frågar om {count(topology.length, "parti", "partier")}
              </h2>
              <p>Svara innan spårplanen kan godkännas.</p>
              <button type="button" className="tm-knapp primar" onClick={() => onQuestion(topology[0]?.key ?? "")}>
                Svara
              </button>
            </div>
          ) : null}
          {others.map((q) => (
            <div key={q.key} className="cad-kort mob-kort">
              <h2>{q.title}</h2>
              <p>{q.text}</p>
              <div className="cad-knapprad">
                {q.choices.map((c) => (
                  <button key={c.id} type="button" className="tm-knapp" disabled={busy} onClick={() => onAnswer(q.key, c.id)}>
                    {c.text}
                  </button>
                ))}
              </div>
            </div>
          ))}
          {checks.map((item: CheckItem) => (
            <div key={item.key} className="cad-kort mob-kort">
              <h2>{item.title}</h2>
              <p>{item.text}</p>
              {phoneChoices(item).length ? (
                <div className="cad-knapprad" role="radiogroup" aria-label={item.title}>
                  {phoneChoices(item).map((c) => (
                    <button
                      key={c.id}
                      type="button"
                      role="radio"
                      aria-checked={answers[item.key] === c.id}
                      className="tm-knapp"
                      onClick={() => setAnswers({ ...answers, [item.key]: c.id })}
                    >
                      {c.text}
                    </button>
                  ))}
                </div>
              ) : (
                <p className="cad-dampad">Det här rättas i Ritningen på datorn.</p>
              )}
            </div>
          ))}
          {summary ? (
            <div className="cad-kort mob-kort mob-sparplan">
              <span aria-hidden="true">⎍</span>
              <span>
                <b>Spårplanen</b>
                <span>
                  {count(summary.switches, "växel", "växlar")}
                  {summary.crossings ? ` · ${count(summary.crossings, "korsning", "korsningar")}` : ""}
                  {summary.ends ? ` · ${count(summary.ends, "stickspår", "stickspår")}` : ""} · ≈ {nr(summary.track_length / 1000)} m spår
                </span>
              </span>
            </div>
          ) : null}
          {module.version !== module.latest ? <p className="cad-dampad">Modulen har en nyare version. Öppna den på datorn.</p> : null}
        </>
      ) : null}
      <Problem error={error} />
    </MobileFrame>
  );
}

// --- 4b AI:n frågar ---------------------------------------------------------------------------------

const HINT: Record<string, string> = {
  two_switches: "Ett tåg kan byta spår här.",
  crossing: "Spåren korsar utan förbindelse.",
  single_slip: "Ett tåg kan byta spår åt ena hållet.",
  double_slip: "Ett tåg kan byta spår åt båda hållen.",
  joined: "Spåren hänger ihop.",
  apart: "Spåren hänger inte ihop här.",
};

export function QuestionPage({
  module,
  job,
  question,
  consent,
  busy,
  error,
  onAnswer,
  onCloseup,
  onBack,
}: {
  module: Module;
  job: PhotoJob;
  question?: string;
  consent: PhotoConsent | null;
  busy?: boolean;
  error?: string | null;
  onAnswer: (key: string, answer: string) => void;
  onCloseup: (key: string, file: File) => void;
  onBack: () => void;
}) {
  const all = (job.questions ?? []).filter((q) => q.topology);
  const asked: PhotoQuestion | undefined = all.find((q) => q.key === question) ?? openTopology(job)[0] ?? all[0];
  const [chosen, setChosen] = useState<string | null>(asked?.answer ?? asked?.ai ?? asked?.code ?? null);
  if (!asked) {
    return (
      <MobileFrame title="AI:n frågar" back={{ label: "Kontroll", onClick: onBack }}>
        <p>Inget parti att svara på.</p>
      </MobileFrame>
    );
  }
  const layer = job.measure;
  const span = 220;
  const closeupFree = Boolean(consent?.own_ai);
  return (
    <MobileFrame
      title="AI:n frågar"
      back={{ label: "Kontroll", onClick: onBack }}
      footer={
        <button type="button" className="tm-knapp primar mob-bred" disabled={busy || !chosen} onClick={() => chosen && onAnswer(asked.key, chosen)}>
          Spara svaret →
        </button>
      }
    >
      <p className="mob-chip-rad">
        <span className="cad-tagg gul">
          ⚠ Fråga {all.indexOf(asked) + 1} av {all.length}
        </span>{" "}
        <span className="cad-dampad">nära gavel {nearGable(module, asked.at as [number, number])}</span>
      </p>
      {layer ? (
        <svg
          className="cad-fotobild mob-narbild"
          viewBox={`${f(asked.at[0] - span)} ${f(asked.at[1] - span * 0.5)} ${f(span * 2)} ${f(span)}`}
          role="img"
          aria-label="Partiet förstorat ur fotot"
        >
          <PhotoImage layer={layer} />
          <ellipse className="cad-osakert-ring" cx={asked.at[0]} cy={asked.at[1]} rx={span * 0.32} ry={span * 0.22} strokeWidth={2.5} strokeDasharray="10 7" />
        </svg>
      ) : null}
      <h2 className="mob-fraga">{asked.title}</h2>
      <p className="cad-dampad">{asked.text}</p>
      {asked.closeup_ai ? <p className="mob-info">Med närbilden: {asked.choices.find((c) => c.id === asked.closeup_ai)?.text ?? asked.closeup_ai}</p> : null}
      <div className="mob-val" role="radiogroup" aria-label={asked.title}>
        {asked.choices.map((c) => (
          <label key={c.id} className={`cad-kort mob-valkort${chosen === c.id ? " valt" : ""}`}>
            <input type="radio" name="mobil-parti" value={c.id} checked={chosen === c.id} onChange={() => setChosen(c.id)} />
            <span>
              <b>{c.text}</b>
              {c.id === asked.ai ? <span className="cad-tagg forslag">AI:n</span> : null}
              <span className="cad-dampad">{c.hint ?? (c.sketch ? HINT[c.sketch] : "")}</span>
            </span>
            {c.sketch ? <Sketch kind={c.sketch} /> : null}
          </label>
        ))}
      </div>
      <label className="mob-narbildlank">
        <span aria-hidden="true">◉</span> Ta en närbild i stället · {closeupFree ? "gratis" : `${consent?.price ?? 12} tokens`}
        <input
          className="cad-dold"
          type="file"
          name="mobil-narbild"
          accept="image/*"
          capture="environment"
          disabled={busy || !consent?.available}
          onChange={(event) => {
            const file = event.currentTarget.files?.[0];
            if (file) onCloseup(asked.key, file);
          }}
        />
      </label>
      {consent && consent.available && !consent.given ? <p className="cad-dampad">Närbilden skickas till {consent.sent_to}.</p> : null}
      <Problem error={error} />
    </MobileFrame>
  );
}

// --- 5 Klart ----------------------------------------------------------------------------------------

export type Outcome = "approved" | "draft" | "measures";

export function outcomeOf(module: Module): Outcome {
  if (module.status === "approved") return "approved";
  return module.photographed ? "draft" : "measures";
}

export function DonePage({
  module,
  job,
  outcome,
  onNext,
  onEnd,
}: {
  module: Module;
  job: PhotoJob | null;
  outcome: Outcome;
  onNext?: () => void;
  onEnd: () => void;
}) {
  const shape = module.shape;
  const agrees = job ? (job.measures ?? []).every((m) => m.agrees) : false;
  const summary = job?.summary;
  const photo = module.photo;
  return (
    <MobileFrame
      title="Klart"
      footer={
        <div className="mob-knappar">
          {onNext ? (
            <button type="button" className="tm-knapp primar mob-bred" onClick={onNext}>
              + Nästa modul
            </button>
          ) : null}
          <button type="button" className={onNext ? "cad-lank" : "tm-knapp primar mob-bred"} onClick={onEnd}>
            Klar i mobilen
          </button>
        </div>
      }
    >
      <div className="mob-klar">
        <span className="mob-bock" aria-hidden="true">
          ✓
        </span>
        <div>
          <h2>{outcome === "approved" ? "Modulen är godkänd" : outcome === "draft" ? "Sparad som förslag" : "Måtten är sparade"}</h2>
          <p className="cad-dampad">
            {module.name} · {module.number}
          </p>
        </div>
      </div>
      <div className="cad-kort mob-kort">
        {photo ? (
          <svg
            className="cad-fotobild"
            viewBox={`${f(photo.grid.x0)} ${f(photo.grid.y0)} ${f(photo.grid.width / photo.grid.ppm)} ${f(photo.grid.height / photo.grid.ppm)}`}
            role="img"
            aria-label={`Mätbilden av ${module.name}`}
          >
            <PhotoImage layer={{ job: photo.job, url: photo.display_url, grid: photo.grid }} />
          </svg>
        ) : (
          <ModuleDrawing
            shape={shape}
            tracks={[module.gables[0]?.tracks ?? [], module.gables[1]?.tracks ?? []]}
            graph={module.graph}
            small
            title="Modulen ovanifrån"
          />
        )}
      </div>
      <div className="mob-rutor">
        <div className="cad-kort">
          <b>
            {shape.kind === "curve"
              ? bendText(shape.radius, shape.angle)
              : `${nr(shape.length, 0)} × ${nr(shape.kind === "straight" ? shape.width : shape.width_a, 0)}`}
          </b>
          <span>{shape.kind === "curve" ? `bredd ${nr(shape.width, 0)} mm` : agrees ? "mm, stämmer med fotot" : "mm"}</span>
        </div>
        <div className="cad-kort">
          <b>{summary ? summary.switches : (module.graph.switches ?? []).length}</b>
          <span>växlar{summary?.ends ? ` · ${count(summary.ends, "stickspår", "stickspår")}` : ""}</span>
        </div>
        <div className="cad-kort">
          <b>
            {summary ? summary.tracks_a : (module.gables[0]?.tracks.length ?? 0)} + {summary ? summary.tracks_b : (module.gables[1]?.tracks.length ?? 0)}
          </b>
          <span>spår vid gavlarna</span>
        </div>
        <div className="cad-kort">
          <b>{job?.cost ?? 0}</b>
          <span>tokens använda</span>
        </div>
      </div>
      <Info>
        {outcome === "measures"
          ? "Modulen finns nu i ditt bibliotek. Fota den när du vill, från modulens sida på datorn."
          : "Ritningen, landskapet och filerna finns nu i ditt bibliotek. Öppna på datorn för att exportera eller skicka spårgrafen till TKL Studio."}
      </Info>
    </MobileFrame>
  );
}

// --- The app: the state from CAD's API --------------------------------------------------------------

const DRAFT_KEY = "cad.mobil.utkast";

function loadDraft(): Draft {
  try {
    const kept = window.sessionStorage.getItem(DRAFT_KEY);
    return kept ? { ...EMPTY_DRAFT, ...(JSON.parse(kept) as Partial<Draft>) } : EMPTY_DRAFT;
  } catch {
    return EMPTY_DRAFT;
  }
}

function keepDraft(draft: Draft | null): void {
  try {
    if (draft) window.sessionStorage.setItem(DRAFT_KEY, JSON.stringify(draft));
    else window.sessionStorage.removeItem(DRAFT_KEY);
  } catch {
    // Without storage the draft lives until the page is reloaded.
  }
}

function message(failure: unknown): string {
  return failure instanceof Error ? failure.message : "Något gick fel. Försök igen.";
}

export function MobileApp() {
  const [route, setRoute] = useState<MobileRoute>(() => mobileRouteFor(window.location.pathname, window.location.search));
  const [session, setSession] = useState<Session | null>(null);
  const [flow, setFlow] = useState<MobileFlow | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const [ended, setEnded] = useState(false);
  const [draft, setDraftState] = useState<Draft>(loadDraft);
  const [profiles, setProfiles] = useState<ProfileList | null>(null);
  const [module, setModule] = useState<Module | null>(null);
  const [job, setJob] = useState<PhotoJob | null>(null);
  const [consent, setConsent] = useState<PhotoConsent | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [follows, setFollows] = useState(0);
  const started = useRef(false);

  const setDraft = useCallback((next: Draft) => {
    setDraftState(next);
    keepDraft(next);
  }, []);

  const navigate = useCallback((href: string, replace = false) => {
    // Links into the web's pages (Från en skiss's Avbryt) stay on the phone.
    const target = isMobilePath(new URL(href, window.location.origin).pathname) ? href : mobilePath("start");
    if (replace) window.history.replaceState(null, "", target);
    else window.history.pushState(null, "", target);
    const url = new URL(target, window.location.origin);
    setRoute(mobileRouteFor(url.pathname, url.search));
    setError(null);
    window.scrollTo(0, 0);
  }, []);

  useEffect(() => {
    const back = () => setRoute(mobileRouteFor(window.location.pathname, window.location.search));
    window.addEventListener("popstate", back);
    return () => window.removeEventListener("popstate", back);
  }, []);

  // The one-time code from the fragment, once; or the session the phone already has.
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    const code = new URLSearchParams(window.location.hash.slice(1)).get("k");
    if (code) {
      // The code leaves the address and the history at once, before it is even given.
      window.history.replaceState(null, "", MOBILE_ROOT);
      api.mobileExchange(code).then(
        (found) => {
          setFlow(found);
          api.session().then(setSession, () => setSession(null));
          navigate(resumePath(found), true);
        },
        (failure: unknown) => {
          setFailed(message(failure));
          api.session().then(setSession, () => setSession(null));
        },
      );
      return;
    }
    api.session().then(
      (found) => {
        setSession(found);
        api.mobileFlow().then(
          (mine) => {
            setFlow(mine);
            if (mine.ended) setEnded(true);
            else if (route.page === "entry") navigate(resumePath(mine), true);
          },
          () => {
            if (!found.account) setFailed(NO_CODE);
            else if (route.page === "entry") navigate(mobilePath("start"), true);
          },
        );
      },
      () => setFailed(NO_CODE),
    );
    // Once, when the page opens.
  }, []);

  // The computer follows: the step, the module and the photo job.
  const page = route.page;
  const routeId = route.page === "missing" ? undefined : route.id;
  const routeJob = route.page === "missing" ? undefined : route.job;
  useEffect(() => {
    if (!flow || flow.ended || ended || page === "entry" || page === "missing") return;
    api.mobileProgress({ step: stepOf(route), module: routeId ?? null, job: routeJob ?? null }).then(setFlow, () => undefined);
    // The flow's own answer is not a reason to tell again.
  }, [page, routeId, routeJob, flow?.handoff, ended]);

  const account = session?.account?.id;
  useEffect(() => {
    if (!account || !routeId) return;
    api.module(routeId).then(setModule, (failure: unknown) => setError(message(failure)));
  }, [account, routeId]);

  useEffect(() => {
    if (!account || page !== "gavlar") return;
    api.profiles(draft.scale).then(setProfiles, (failure: unknown) => setError(message(failure)));
  }, [account, page, draft.scale]);

  useEffect(() => {
    if (!account || !(page === "horn" || page === "fraga" || page === "fota" || page === "skiss")) return;
    api.photoConsent(routeId).then(setConsent, () => setConsent(null));
  }, [account, page, routeId]);

  // The job, followed while it waits or runs; the module again when it is read.
  useEffect(() => {
    if (!account || !routeJob) return;
    let stop = false;
    let timer = 0;
    let before: string | null = null;
    const follow = () => {
      api.photoJob(routeJob).then(
        (found) => {
          if (stop) return;
          setJob(found);
          if (before && before !== found.state && found.state === "done") {
            api.module(found.module).then(setModule, () => undefined);
            api.session().then(setSession, () => undefined);
          }
          before = found.state;
          if (found.state === "queued" || found.state === "running") timer = window.setTimeout(follow, 1500);
        },
        (failure: unknown) => !stop && setError(message(failure)),
      );
    };
    follow();
    return () => {
      stop = true;
      window.clearTimeout(timer);
    };
  }, [account, routeJob, follows]);

  const failedCall = (failure: unknown) => {
    setBusy(false);
    setError(failure instanceof ApiError && failure.status === 409 ? "Modulen har ändrats under tiden. Öppna den igen." : message(failure));
  };

  const end = () => {
    if (!flow) {
      window.location.assign(PATHS.library);
      return;
    }
    api.mobileEnd().then(
      () => setEnded(true),
      () => setEnded(true),
    );
  };

  const upload = (start: PhotoStart, files: File[], after?: (job: PhotoJob) => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    api.uploadPhotos(start, files).then(async (made) => {
      try {
        if (after) await after(made);
        setJob(made);
        setBusy(false);
        navigate(mobilePath("horn", made.module, made.id));
      } catch (failure) {
        failedCall(failure);
      }
    }, failedCall);
  };

  // A bound phone has no Välj väg; a photo already read goes on to Kontroll.
  const bound = flow?.bound ?? null;
  const readAlready = page === "horn" && job != null && job.id === routeJob && job.state !== "corners" && job.state !== "failed";
  useEffect(() => {
    if (page === "start" && bound) navigate(mobilePath("fota", bound), true);
    else if (readAlready && job && routeId) navigate(mobilePath("kontroll", routeId, job.id), true);
  }, [page, bound, readAlready, job, routeId, navigate]);

  if (ended) return <EndedPage />;
  const login = session?.login === "trial" ? `${PATHS.login}?next=${encodeURIComponent(mobilePath("start"))}` : idLoginHref(mobilePath("start"));
  if (failed || page === "entry") return <EntryPage failed={failed} login={failed ? login : undefined} />;
  if (!session) return <Loading />;
  if (!session.account) return <EntryPage failed={NO_CODE} login={login} />;
  if (page === "missing") {
    return (
      <MobileFrame title="TrainMeet CAD" back={{ label: "Ny modul", onClick: () => navigate(mobilePath("start")) }}>
        <p>Sidan finns inte.</p>
      </MobileFrame>
    );
  }
  const toStart = () => navigate(mobilePath("start"));

  if (page === "start") {
    if (bound) return <Loading />;
    return (
      <StartPage
        name={session.account.name}
        tokens={session.tokens}
        onCancel={end}
        onChoose={(way) => {
          if (way === "skiss") navigate(mobilePath("skiss"));
          else {
            setDraft({ ...draft, mode: way });
            navigate(mobilePath("matt"));
          }
        }}
      />
    );
  }
  if (page === "matt") return <MeasuresPage draft={draft} onDraft={setDraft} onCancel={toStart} onNext={() => navigate(mobilePath("gavlar"))} />;
  if (page === "gavlar") {
    return (
      <GablesPage
        draft={draft}
        profiles={profiles}
        busy={busy}
        error={error}
        onDraft={setDraft}
        onBack={() => navigate(mobilePath("matt"))}
        onNext={() => {
          if (photoFirst(draft)) {
            navigate(mobilePath("fota"));
            return;
          }
          const body = newModuleOf(draft);
          if (!body) return;
          setBusy(true);
          api.create(body).then((made) => {
            setBusy(false);
            setModule(made);
            setDraft(EMPTY_DRAFT);
            if (draft.mode === "matt") {
              setOutcome("measures");
              navigate(mobilePath("klar", made.id));
            } else navigate(mobilePath("fota", made.id));
          }, failedCall);
        }}
      />
    );
  }
  if (page === "skiss") {
    return (
      <MobileFrame title="Fota en skiss" back={{ label: "Avbryt", onClick: toStart, cancel: true }}>
        <SketchUpload
          scale={draft.scale}
          consent={consent}
          busy={busy}
          error={error}
          navigate={(href) => navigate(href)}
          onUpload={(start, files) => upload(start, files)}
        />
      </MobileFrame>
    );
  }
  if (page === "fota") {
    if (routeId) {
      if (module?.id !== routeId) return <Loading />;
      return (
        <PhotoStepPage
          title="Fota uppifrån"
          busy={busy}
          error={error}
          back={bound ? undefined : { label: "Ny modul", onClick: toStart }}
          onPhotos={(files) => upload(photoStartFor(module), files)}
        />
      );
    }
    return (
      <PhotoStepPage
        title="Fota uppifrån"
        busy={busy}
        error={error}
        back={{ label: "Gavlar", onClick: () => navigate(mobilePath("gavlar")) }}
        onPhotos={(files) =>
          upload(photoStartOf(draft), files, async (made) => {
            // The photo made the module with the length from the photo; 2 Gavlar go onto it.
            const fresh = await api.module(made.module);
            const saved = await api.save(made.module, withGables(fresh, draft));
            setModule(saved);
            setDraft(EMPTY_DRAFT);
          })
        }
      />
    );
  }
  if (!routeId || module?.id !== routeId) return <Loading />;
  const current = module;
  const retake = () => navigate(mobilePath("fota", current.id));
  if (page === "klar") {
    return (
      <DonePage
        module={current}
        job={job && job.module === current.id ? job : null}
        outcome={outcome ?? outcomeOf(current)}
        onNext={
          bound
            ? undefined
            : () => {
                setOutcome(null);
                setJob(null);
                setDraft(EMPTY_DRAFT);
                navigate(mobilePath("start"));
              }
        }
        onEnd={end}
      />
    );
  }
  if (!routeJob || job?.id !== routeJob) return <Loading />;
  const currentJob = job;
  if (page === "horn") {
    if (readAlready) return <Loading />;
    return (
      <CornersPage
        key={currentJob.id}
        module={current}
        job={currentJob}
        consent={consent}
        busy={busy}
        error={error}
        onRetake={retake}
        onRead={(corners, kant1, ai, agreed, gableA, frame) => {
          setBusy(true);
          setError(null);
          api.readPhoto(currentJob.id, { corners, kant1, ai, consent: agreed, gable_a: gableA, frame: frame ?? null }).then((read) => {
            setBusy(false);
            setJob(read);
            setFollows((n) => n + 1);
            if (read.state === "done") api.module(read.module).then(setModule, () => undefined);
            navigate(mobilePath("kontroll", read.module, read.id));
          }, failedCall);
        }}
      />
    );
  }
  const answer = (key: string, chosen: string) => {
    setBusy(true);
    api.answerPhoto(currentJob.id, key, chosen).then((answered) => {
      setBusy(false);
      setJob(answered);
      api.module(answered.module).then(setModule, () => undefined);
      if (page === "fraga") {
        const next = openTopology(answered)[0];
        navigate(next ? mobilePath("fraga", answered.module, answered.id, next.key) : mobilePath("kontroll", answered.module, answered.id));
      }
    }, failedCall);
  };
  if (page === "fraga") {
    return (
      <QuestionPage
        key={route.question ?? ""}
        module={current}
        job={currentJob}
        question={route.question}
        consent={consent}
        busy={busy}
        error={error}
        onBack={() => navigate(mobilePath("kontroll", current.id, currentJob.id))}
        onAnswer={answer}
        onCloseup={(key, file) => {
          setBusy(true);
          api.closeup(currentJob.id, key, file, Boolean(consent && !consent.given)).then((seen) => {
            setBusy(false);
            setJob(seen);
            setConsent((known) => (known ? { ...known, given: true } : known));
          }, failedCall);
        }}
      />
    );
  }
  return (
    <CheckPage
      module={current}
      job={currentJob}
      busy={busy}
      error={error}
      onBack={retake}
      onAnswer={answer}
      onQuestion={(key) => navigate(mobilePath("fraga", current.id, currentJob.id, key))}
      onUseMeasure={(measure) => {
        const change = measureChange(current, currentJob, measure);
        if (!change) return;
        setBusy(true);
        api.save(current.id, change).then((saved) => {
          setBusy(false);
          setModule(saved);
        }, failedCall);
      }}
      onLater={() => {
        setOutcome("draft");
        navigate(mobilePath("klar", current.id, currentJob.id));
      }}
      onApprove={(answers) => {
        setBusy(true);
        api.approvePlan(current.id, { base: current.latest, operations: answerOps(answers) }).then((approved) => {
          setBusy(false);
          setModule(approved);
          setOutcome("approved");
          navigate(mobilePath("klar", approved.id, currentJob.id));
        }, failedCall);
      }}
    />
  );
}
