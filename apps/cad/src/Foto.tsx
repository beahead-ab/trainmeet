// Foto och kontroll (#89 del c1, CAD-02, CAD-17, CAD-18, CAD-29): a module's photo taken in,
// its corners and Kant 1 confirmed, the price before it is read, the AI's tracks over the photo
// and the owner's measures against it (the view Foto-kontroll); Längden ur fotot when only the
// width is known (Matt-ur-foto); and Osäkert parti, where the owner answers what the code and
// the AI could not agree on (Osakert). Code measures; AI only reads which tracks connect (CAD2).
import { linkClick, type Navigate } from "@trainmeet/design";
import { useRef, useState, type PointerEvent as ReactPointerEvent, type ReactNode } from "react";
import type { Module, PhotoChoice, PhotoConsent, PhotoJob, PhotoLayer, PhotoMeasure, PhotoQuestion, PhotoStart, Scale, StorageUse } from "./api";
import { count, dayText } from "./common";
import { f, kantOne, outline, pathOf, poly, segsOf } from "./Drawing";
import { mmText, type Point } from "./geometry";
import { drawingPath, modulePath, PATHS, photoPath, type PhotoView } from "./routes";

export const MAX_PHOTOS = 4;
const MB = 1024 * 1024;

const nr = (value: number, digits = 1) => value.toLocaleString("sv-SE", { maximumFractionDigits: digits, useGrouping: false });

/** The price before the photo is read: 12 tokens per measuring image, follow-ups included, or
 * nothing with the account's own AI or without AI (CAD3, CAD-29). */
export function PriceText({ consent }: { consent: PhotoConsent | null }) {
  if (!consent) return <p className="cad-dampad">Hämtar priset …</p>;
  if (!consent.available) {
    return (
      <p className="cad-dampad">
        {consent.message ?? "AI-avläsningen går inte att använda just nu."} Utan AI är det gratis: du svarar själv på vilka spår som
        hänger ihop.
      </p>
    );
  }
  if (consent.own_ai) {
    return (
      <p className="cad-pris">
        <b>Gratis</b> med din egen AI ({consent.own_ai}).
      </p>
    );
  }
  return (
    <p className="cad-pris">
      <b>{consent.price} tokens</b> för mätbilden, med följdfrågorna. Samma bild igen kostar inget.
      {consent.balance != null ? (
        <span className="cad-dampad">
          {" "}
          {consent.payer ? `${consent.payer} har` : "Du har"} {consent.balance} tokens.
        </span>
      ) : null}
    </p>
  );
}

// --- Ladda upp ett foto ------------------------------------------------------------------------

type UploadProps = {
  /** A photo for this module; none: a new module from the photo. */
  module?: Module | null;
  scale: Scale;
  consent: PhotoConsent | null;
  storage?: StorageUse | null;
  busy?: boolean;
  error?: string | null;
  navigate?: Navigate;
  onUpload?: (start: PhotoStart, files: File[]) => void;
  /** The form chosen at first: a straight module unless told otherwise. */
  initialKind?: "straight" | "trapezoid" | "curve";
};

/** Ladda upp foto: one to four photos of one module from above, and for a new module its width;
 * the length can come from the photo. A curve module comes with its chord and sagitta on track 1
 * and track 1's distance from Kant 1 (part c2). */
export function PhotoUpload({ module, scale, consent, storage, busy, error, navigate, onUpload, initialKind }: UploadProps) {
  const [name, setName] = useState("");
  const [kind, setKind] = useState<"straight" | "trapezoid" | "curve">(initialKind ?? "straight");
  const [width, setWidth] = useState("");
  const [widthB, setWidthB] = useState("");
  const [length, setLength] = useState("");
  const [chord, setChord] = useState("");
  const [sagitta, setSagitta] = useState("");
  const [track1, setTrack1] = useState("");
  const [edge, setEdge] = useState<"outer" | "inner">("outer");
  const [files, setFiles] = useState<File[]>([]);
  const [keep, setKeep] = useState(false);
  const number = (text: string) => Number(text.replace(",", "."));
  const curveReady = number(chord) > 0 && number(sagitta) > 0 && number(sagitta) < number(chord) / 2 && number(track1) > 0;
  const ready =
    files.length > 0 &&
    files.length <= MAX_PHOTOS &&
    (module ? true : name.trim() !== "" && number(width) > 0 && (kind !== "trapezoid" || number(widthB) > 0) && (kind !== "curve" || curveReady));
  const submit = () => {
    if (!ready) return;
    const empty = {
      module: null,
      profile: "modulfoto" as const,
      name: null,
      width: null,
      width_b: null,
      length: null,
      offset: null,
      owner: null,
      chord: null,
      sagitta: null,
      track1: null,
      edge: "outer" as const,
    };
    const start: PhotoStart = module
      ? { ...empty, module: module.id, scale: module.scale, kind: module.shape.kind, keep_original: keep }
      : {
          ...empty,
          name: name.trim(),
          scale,
          kind,
          width: number(width),
          width_b: kind === "trapezoid" ? number(widthB) : null,
          length: kind !== "curve" && length.trim() ? number(length) : null,
          chord: kind === "curve" ? number(chord) : null,
          sagitta: kind === "curve" ? number(sagitta) : null,
          track1: kind === "curve" ? number(track1) : null,
          edge,
          keep_original: keep,
        };
    onUpload?.(start, files);
  };
  const size = files.reduce((sum, file) => sum + file.size, 0);
  return (
    <form
      className="cad-kort cad-formular cad-uppladdning"
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      <h2>{module ? "Ladda upp ett foto av modulen" : "Ladda upp ett foto"}</h2>
      <p className="cad-dampad">
        Ett foto rakt ovanifrån med hela modulen och lite av golvet runt om. En lång modul får tas i 2–4 foton som överlappar; de sys
        ihop till ett. Bredden ger fotot dess skala, och längden kan räknas fram ur fotot.
      </p>
      {module ? null : (
        <>
          <label className="cad-falt">
            <span>Namn</span>
            <input name="foto-namn" required maxLength={80} value={name} onChange={(event) => setName(event.currentTarget.value)} />
          </label>
          <div className="cad-falt">
            <span>Form</span>
            <div className="cad-segment" role="radiogroup" aria-label="Form">
              {(
                [
                  ["straight", "Rak"],
                  ["trapezoid", "Trapets"],
                  ["curve", "Kurva"],
                ] as const
              ).map(([value, label]) => (
                <button key={value} type="button" role="radio" aria-checked={kind === value} onClick={() => setKind(value)}>
                  {label}
                </button>
              ))}
            </div>
          </div>
          <div className="cad-rad">
            <label className="cad-matt-falt">
              <span>{kind === "trapezoid" ? "Bredd vid gavel A" : "Bredd"}</span>
              <span className="cad-mm">
                <input name="foto-bredd" inputMode="decimal" value={width} onChange={(event) => setWidth(event.currentTarget.value)} />
                <span aria-hidden="true">mm</span>
              </span>
            </label>
            {kind === "trapezoid" ? (
              <label className="cad-matt-falt">
                <span>Bredd vid gavel B</span>
                <span className="cad-mm">
                  <input name="foto-bredd-b" inputMode="decimal" value={widthB} onChange={(event) => setWidthB(event.currentTarget.value)} />
                  <span aria-hidden="true">mm</span>
                </span>
              </label>
            ) : null}
            {kind !== "curve" ? (
              <label className="cad-matt-falt">
                <span>Längd (om du vet den)</span>
                <span className="cad-mm">
                  <input name="foto-langd" inputMode="decimal" placeholder="ur fotot" value={length} onChange={(event) => setLength(event.currentTarget.value)} />
                  <span aria-hidden="true">mm</span>
                </span>
              </label>
            ) : null}
          </div>
          {kind === "curve" ? (
            <div className="cad-ruta">
              <p className="cad-dampad">
                Mät spår 1 med ett snöre från spårmitten vid gavel A till spårmitten vid gavel B (kordan), och pilhöjden från snörets mitt till spåret.
                Radien och vinkeln räknas fram exakt, utan avrundning.
              </p>
              <div className="cad-rad">
                <label className="cad-matt-falt">
                  <span>Korda</span>
                  <span className="cad-mm">
                    <input name="foto-korda" inputMode="decimal" value={chord} onChange={(event) => setChord(event.currentTarget.value)} />
                    <span aria-hidden="true">mm</span>
                  </span>
                </label>
                <label className="cad-matt-falt">
                  <span>Pilhöjd</span>
                  <span className="cad-mm">
                    <input name="foto-pilhojd" inputMode="decimal" value={sagitta} onChange={(event) => setSagitta(event.currentTarget.value)} />
                    <span aria-hidden="true">mm</span>
                  </span>
                </label>
                <label className="cad-matt-falt">
                  <span>Spår 1 från Kant 1</span>
                  <span className="cad-mm">
                    <input name="foto-spar1" inputMode="decimal" value={track1} onChange={(event) => setTrack1(event.currentTarget.value)} />
                    <span aria-hidden="true">mm</span>
                  </span>
                </label>
              </div>
              <div className="cad-segment" role="radiogroup" aria-label="Kant 1 på kurvan">
                {(
                  [
                    ["outer", "Kant 1 ytterst"],
                    ["inner", "Kant 1 innerst"],
                  ] as const
                ).map(([value, label]) => (
                  <button key={value} type="button" role="radio" aria-checked={edge === value} onClick={() => setEdge(value)}>
                    {label}
                  </button>
                ))}
              </div>
            </div>
          ) : null}
        </>
      )}
      <label className="cad-falt cad-filval">
        <span>Foton, 1–{MAX_PHOTOS} av samma modul</span>
        <input
          type="file"
          name="foton"
          accept="image/jpeg,image/png"
          multiple
          onChange={(event) => setFiles(Array.from(event.currentTarget.files ?? []).slice(0, MAX_PHOTOS))}
        />
      </label>
      {files.length ? (
        <p className="cad-dampad">
          {count(files.length, "foto", "foton")} · {nr(size / MB)} MB
        </p>
      ) : null}
      <label className="cad-kryss">
        <input type="checkbox" name="spara-original" checked={keep} onChange={(event) => setKeep(event.currentTarget.checked)} />
        Spara originalet. Annars sparas det tills modulen godkänns, högst 30 dagar, och räknas inte i ditt utrymme.
      </label>
      <div className="cad-ruta cad-prisruta">
        <PriceText consent={consent} />
        <p className="cad-dampad">
          Du ser priset igen innan fotot läses av. Utan AI är det gratis. Fotots plats och kamerans uppgifter tas bort innan något sparas.
          {storage ? ` Ditt utrymme för modulfoton: ${nr(storage.used / MB)} av ${nr(storage.limit / MB, 0)} MB.` : ""}
        </p>
      </div>
      {error ? (
        <p className="cad-fel" role="alert">
          {error}
        </p>
      ) : null}
      <div className="cad-knapprad">
        {module ? null : (
          <a className="tm-knapp" href={PATHS.new} onClick={linkClick(navigate, PATHS.new)}>
            Avbryt
          </a>
        )}
        <button type="submit" className="tm-knapp primar" disabled={!ready || busy}>
          {busy ? "Laddar upp …" : "Ladda upp"}
        </button>
      </div>
    </form>
  );
}

/** Från skiss: a hand-drawn track plan with the modules' frames, read into a module (part c2).
 * The frame chosen is this module; its length and width give the sketch its scale. */
export function SketchUpload({ scale, consent, busy, error, navigate, onUpload }: UploadProps) {
  const [name, setName] = useState("");
  const [kind, setKind] = useState<"straight" | "trapezoid">("straight");
  const [length, setLength] = useState("");
  const [width, setWidth] = useState("");
  const [widthB, setWidthB] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const number = (text: string) => Number(text.replace(",", "."));
  const ready = file !== null && name.trim() !== "" && number(length) > 0 && number(width) > 0 && (kind === "straight" || number(widthB) > 0);
  return (
    <form
      className="cad-kort cad-formular cad-uppladdning"
      onSubmit={(event) => {
        event.preventDefault();
        if (!ready || !file) return;
        onUpload?.(
          {
            module: null,
            profile: "skiss",
            name: name.trim(),
            scale,
            kind,
            width: number(width),
            width_b: kind === "trapezoid" ? number(widthB) : null,
            length: number(length),
            offset: null,
            chord: null,
            sagitta: null,
            track1: null,
            edge: "outer",
            keep_original: false,
            owner: null,
          },
          [file],
        );
      }}
    >
      <h2>Ladda upp en skiss</h2>
      <p className="cad-dampad">
        En handritad spårplan, skannad eller fotad, med modulernas ramar utritade. Du väljer sedan ramen som är den här modulen. Spåren ritas om
        som raka och bågar som följer skissen, ± 20 mm, tills du mäter eller godkänner.
      </p>
      <label className="cad-falt">
        <span>Namn</span>
        <input name="skiss-namn" required maxLength={80} value={name} onChange={(event) => setName(event.currentTarget.value)} />
      </label>
      <div className="cad-falt">
        <span>Form</span>
        <div className="cad-segment" role="radiogroup" aria-label="Form">
          {(
            [
              ["straight", "Rak"],
              ["trapezoid", "Trapets"],
            ] as const
          ).map(([value, label]) => (
            <button key={value} type="button" role="radio" aria-checked={kind === value} onClick={() => setKind(value)}>
              {label}
            </button>
          ))}
        </div>
      </div>
      <div className="cad-rad">
        <label className="cad-matt-falt">
          <span>Längd</span>
          <span className="cad-mm">
            <input name="skiss-langd" inputMode="decimal" value={length} onChange={(event) => setLength(event.currentTarget.value)} />
            <span aria-hidden="true">mm</span>
          </span>
        </label>
        <label className="cad-matt-falt">
          <span>{kind === "trapezoid" ? "Bredd vid gavel A" : "Bredd"}</span>
          <span className="cad-mm">
            <input name="skiss-bredd" inputMode="decimal" value={width} onChange={(event) => setWidth(event.currentTarget.value)} />
            <span aria-hidden="true">mm</span>
          </span>
        </label>
        {kind === "trapezoid" ? (
          <label className="cad-matt-falt">
            <span>Bredd vid gavel B</span>
            <span className="cad-mm">
              <input name="skiss-bredd-b" inputMode="decimal" value={widthB} onChange={(event) => setWidthB(event.currentTarget.value)} />
              <span aria-hidden="true">mm</span>
            </span>
          </label>
        ) : null}
      </div>
      <label className="cad-falt cad-filval">
        <span>Skissen</span>
        <input type="file" name="skiss" accept="image/jpeg,image/png" onChange={(event) => setFile(event.currentTarget.files?.[0] ?? null)} />
      </label>
      <div className="cad-ruta cad-prisruta">
        <PriceText consent={consent} />
        <p className="cad-dampad">
          Koden läser spåren. AI:n frågas bara om ett parti koden inte kan avgöra, till samma pris som ett foto: 12 tokens för skissen, med
          följdfrågorna. Utan AI är det gratis.
        </p>
      </div>
      {error ? (
        <p className="cad-fel" role="alert">
          {error}
        </p>
      ) : null}
      <div className="cad-knapprad">
        <a className="tm-knapp" href={PATHS.new} onClick={linkClick(navigate, PATHS.new)}>
          Avbryt
        </a>
        <button type="submit" className="tm-knapp primar" disabled={!ready || busy}>
          {busy ? "Laddar upp …" : "Ladda upp skissen"}
        </button>
      </div>
    </form>
  );
}

export function SketchPage(props: UploadProps) {
  return (
    <section className="cad-sida" aria-labelledby="rubrik">
      <nav className="cad-brodsmulor" aria-label="Var du är">
        <a href={PATHS.library} onClick={linkClick(props.navigate, PATHS.library)}>
          Moduler
        </a>{" "}
        ›{" "}
        <a href={PATHS.new} onClick={linkClick(props.navigate, PATHS.new)}>
          Ny modul
        </a>{" "}
        › <span aria-current="page">Från en skiss</span>
      </nav>
      <div className="cad-rubrikrad">
        <h1 id="rubrik">Ny modul ur en skiss</h1>
      </div>
      <SketchUpload {...props} />
    </section>
  );
}

/** Ny modul ur ett foto: its own page from Ny modul. */
export function UploadPage(props: UploadProps) {
  return (
    <section className="cad-sida" aria-labelledby="rubrik">
      <nav className="cad-brodsmulor" aria-label="Var du är">
        <a href={PATHS.library} onClick={linkClick(props.navigate, PATHS.library)}>
          Moduler
        </a>{" "}
        ›{" "}
        <a href={PATHS.new} onClick={linkClick(props.navigate, PATHS.new)}>
          Ny modul
        </a>{" "}
        › <span aria-current="page">Ladda upp ett foto</span>
      </nav>
      <div className="cad-rubrikrad">
        <h1 id="rubrik">Ny modul ur ett foto</h1>
      </div>
      <PhotoUpload {...props} />
    </section>
  );
}

// --- The photo with the corners and Kant 1 ------------------------------------------------------

type Corners = Point[];

/** Gable A is the side before Kant 1, gable B the side after it (side i runs from corner i). */
function sideMiddle(corners: Corners, side: number): Point {
  const a = corners[side % 4] ?? [0, 0];
  const b = corners[(side + 1) % 4] ?? [0, 0];
  return [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
}

/** The side opposite a side. */
const opposite = (side: number) => (side + 2) % 4;
/** Is the side beside Kant 1, a gable? */
const besideKant1 = (side: number, kant1: number) => side === (kant1 + 1) % 4 || side === (kant1 + 3) % 4;

/** Tap a side: a gable becomes gable A; a long side becomes Kant 1. Gable A then stays at its
 * end when the owner chose it (chosen), else it is the side before Kant 1, as CAD draws a module
 * (part c2). */
export function tapSide(side: number, kant1: number, gableA: number, chosen = false): { kant1: number; gableA: number } {
  if (besideKant1(side, kant1)) return { kant1, gableA: side };
  if (side === kant1) return { kant1, gableA };
  return { kant1: side, gableA: chosen && besideKant1(gableA, side) ? gableA : (side + 3) % 4 };
}

function CornerEditor({
  job,
  corners,
  kant1,
  gableA,
  onCorners,
  onSide,
}: {
  job: PhotoJob;
  corners: Corners;
  kant1: number;
  gableA: number;
  onCorners: (corners: Corners) => void;
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
    if (!p) return;
    onCorners(corners.map((c, i) => (i === dragging ? [Math.round(p[0] * 10) / 10, Math.round(p[1] * 10) / 10] : c)));
  };
  const gableAt = sideMiddle(corners, gableA);
  const gableBt = sideMiddle(corners, opposite(gableA));
  const kant = sideMiddle(corners, kant1);
  return (
    <svg
      ref={svg}
      className="cad-fotobild"
      viewBox={`0 0 ${preview.width} ${preview.height}`}
      role="img"
      aria-label="Fotot med modulens hörn"
      onPointerMove={move}
      onPointerUp={() => setDragging(null)}
      onPointerLeave={() => setDragging(null)}
    >
      <image href={preview.url} width={preview.width} height={preview.height} />
      <path className="cad-fotoram" d={poly(corners, (p) => p, true)} strokeWidth={unit * 0.35} />
      {corners.map((c, side) => {
        const next = corners[(side + 1) % 4] ?? c;
        return (
          <line
            key={`sida${side}`}
            className={side === kant1 ? "cad-fotokant1" : side === gableA ? "cad-fotogavela" : "cad-fotosida"}
            data-sida={side}
            x1={c[0]}
            y1={c[1]}
            x2={next[0]}
            y2={next[1]}
            strokeWidth={unit * (side === kant1 || side === gableA ? 1.1 : 1.6)}
            onClick={() => onSide(side)}
          >
            <title>
              {side === kant1
                ? "Kant 1"
                : side === gableA
                  ? "Gavel A"
                  : besideKant1(side, kant1)
                    ? "Gör den här gaveln till gavel A"
                    : "Gör den här sidan till Kant 1"}
            </title>
          </line>
        );
      })}
      {corners.map((c, i) => (
        <circle
          key={`horn${i}`}
          className="cad-fotohorn"
          data-horn={i}
          cx={c[0]}
          cy={c[1]}
          r={unit * 1.3}
          strokeWidth={unit * 0.45}
          onPointerDown={(event) => {
            event.currentTarget.ownerSVGElement?.setPointerCapture?.(event.pointerId);
            setDragging(i);
          }}
        />
      ))}
      <g className="cad-fototexter" fontSize={unit * 2.6}>
        <text x={kant[0]} y={kant[1] - unit * 1.8} textAnchor="middle">
          KANT 1
        </text>
        <text x={gableAt[0]} y={gableAt[1]} textAnchor="middle">
          GAVEL A
        </text>
        <text x={gableBt[0]} y={gableBt[1]} textAnchor="middle">
          GAVEL B
        </text>
      </g>
    </svg>
  );
}

/** The photo as taken in, with the AI's tracks over it when the job is read. */
function PhotoWithTracks({ job, tracks }: { job: PhotoJob; tracks: boolean }) {
  const preview = job.preview;
  if (!preview) return <p className="cad-dampad">Originalfotot är borttaget. Mätbilden finns kvar under Ritningen.</p>;
  const unit = Math.max(preview.width, preview.height) / 100;
  const corners = (job.corners?.corners ?? []) as Point[];
  return (
    <svg className="cad-fotobild" viewBox={`0 0 ${preview.width} ${preview.height}`} role="img" aria-label={job.profile === "skiss" ? (tracks ? "Skissen med spåren" : "Skissen") : tracks ? "Fotot med AI:ns spår" : "Fotot"}>
      <image href={preview.url} width={preview.width} height={preview.height} />
      {tracks
        ? (job.tracks_on_photo ?? []).map((line, i) => (
            <path key={i} className="cad-aispar" d={poly(line as Point[], (p) => p, false)} strokeWidth={unit * 0.45} strokeDasharray={`${unit * 1.2} ${unit * 0.8}`} />
          ))
        : null}
      {corners.map((c, i) => (
        <circle key={i} className="cad-fotohorn" cx={c[0]} cy={c[1]} r={unit * 1.1} strokeWidth={unit * 0.4} />
      ))}
    </svg>
  );
}

/** The measuring image under the drawing in the module's millimetres (Fotot under): pixel (0, 0)'s
 * centre at (x0, y0) mm. */
export function PhotoImage({ layer, opacity = 1 }: { layer: PhotoLayer; opacity?: number }) {
  const { grid } = layer;
  const image = (
    <image
      className="cad-fotolager"
      href={layer.url}
      x={grid.x0 - 0.5 / grid.ppm}
      y={grid.y0 - 0.5 / grid.ppm}
      width={grid.width / grid.ppm}
      height={grid.height / grid.ppm}
      opacity={opacity}
      preserveAspectRatio="none"
    />
  );
  // A photo read with another Kant 1 or gable A keeps its image: mirrored into this frame.
  return grid.matrix ? <g transform={`matrix(${grid.matrix.join(" ")})`}>{image}</g> : image;
}

/** Uträtad ritning: the measuring image with the track plan over it, in mm. */
function Straightened({ module, job }: { module: Module; job: PhotoJob }) {
  const shape = module.shape;
  const track1 = module.gables[0]?.tracks?.[0] ?? 0;
  const board = outline(shape, track1);
  const xs = board.map((p) => p[0]);
  const ys = board.map((p) => p[1]);
  const minX = Math.min(...xs);
  const minY = Math.min(...ys);
  const w = Math.max(...xs) - minX;
  const h = Math.max(...ys) - minY;
  const pad = Math.max(w, h) * 0.08;
  const unit = Math.max(w, h) / 100;
  const segs = segsOf(module.graph);
  return (
    <svg className="cad-ritning" viewBox={`${f(minX - pad)} ${f(minY - pad * 1.6)} ${f(w + 2 * pad)} ${f(h + pad * 3)}`} role="img" aria-label="Uträtad ritning">
      {job.measure ? <PhotoImage layer={job.measure} opacity={0.55} /> : null}
      <path className="cad-skiva genomskinlig" d={poly(board, (p) => p, true)} strokeWidth={unit * 0.25} />
      <path className="cad-kant1" d={poly(kantOne(shape, track1), (p) => p, false)} strokeWidth={unit * 0.9} />
      {segs.map((seg, i) => (
        <g key={i}>
          <path className="cad-spar" d={pathOf(seg, (p) => p)} strokeWidth={unit * 0.6} />
          <path className="cad-aispar" d={pathOf(seg, (p) => p)} strokeWidth={unit * 0.3} strokeDasharray={`${unit * 1.2} ${unit * 0.8}`} />
        </g>
      ))}
      <g className="cad-texter" fontSize={unit * 2.4}>
        <text x={minX} y={minY - unit * 2.2} className="cad-kant1-text">
          KANT 1
        </text>
        <text x={minX} y={minY + h + pad * 0.9} className="cad-gavel-text">
          GAVEL A
        </text>
        <text x={minX + w} y={minY + h + pad * 0.9} textAnchor="end" className="cad-gavel-text">
          GAVEL B
        </text>
      </g>
    </svg>
  );
}

// --- Foto och kontroll ---------------------------------------------------------------------------

export type PhotoPageProps = {
  module: Module;
  job: PhotoJob | null;
  view: PhotoView;
  question?: string;
  consent: PhotoConsent | null;
  busy?: boolean;
  error?: string | null;
  navigate?: Navigate;
  onRead?: (corners: Point[], kant1: number, ai: boolean, consent: boolean, gableA?: number, frame?: number) => void;
  /** Another Kant 1 or gable A after reading: at no cost (part c2). */
  onOrientation?: (kant1: number, gableA: number) => void;
  onAnswer?: (key: string, answer: string) => void;
  onCloseup?: (key: string, file: File, consent: boolean) => void;
  /** Använd the photo's value for a gable's track, or the length: a new version of the measures. */
  onUseMeasure?: (measure: { gable?: "A" | "B"; track?: number; length?: number; width?: number }) => void;
  onApprovePlan?: () => void;
};

function Crumbs({ module, here, navigate }: { module: Module; here: string; navigate?: Navigate }) {
  return (
    <nav className="cad-brodsmulor" aria-label="Var du är">
      <a href={PATHS.library} onClick={linkClick(navigate, PATHS.library)}>
        Moduler
      </a>{" "}
      ›{" "}
      <a href={modulePath(module.id)} onClick={linkClick(navigate, modulePath(module.id))}>
        {module.name}
      </a>{" "}
      › <span aria-current="page">{here}</span>
    </nav>
  );
}

const LEVEL_MARK: Record<string, string> = { ok: "✓", low: "!", warn: "⚠", refuse: "✕" };

/** Bekräfta hörnen och Kant 1, see the price, and read it, with AI or without. */
function ConfirmCorners({ module, job, consent, busy, onRead }: Pick<PhotoPageProps, "module" | "job" | "consent" | "busy" | "onRead"> & { job: PhotoJob }) {
  const start = (job.corners?.corners ?? []) as Point[];
  const [corners, setCorners] = useState<Corners>(start.length === 4 ? start : []);
  const [kant1, setKant1] = useState(job.corners?.kant1 ?? 0);
  const [gableA, setGableA] = useState(job.corners?.gable_a ?? ((job.corners?.kant1 ?? 0) + 3) % 4);
  // The frame the corners start on: the one code chose (the largest), or the one read before.
  const startFrame = job.frame ?? job.frames?.findIndex((f) => JSON.stringify(f.corners) === JSON.stringify(start)) ?? -1;
  const [frame, setFrame] = useState<number | undefined>(job.frames?.length ? Math.max(0, startFrame) : undefined);
  const [agreed, setAgreed] = useState(false);
  const aiPossible = Boolean(consent?.available && consent.may_read);
  const needsYes = aiPossible && !consent?.given;
  const sketch = job.profile === "skiss";
  // Gable A chosen by the owner, or derived: it stays at its end when Kant 1 moves.
  const [aChosen, setAChosen] = useState(Boolean(job.corners?.derived));
  const side = (tapped: number) => {
    const next = tapSide(tapped, kant1, gableA, aChosen);
    if (besideKant1(tapped, kant1)) setAChosen(true);
    setKant1(next.kant1);
    setGableA(next.gableA);
  };
  const chooseFrame = (index: number) => {
    const chosen = job.frames?.[index];
    if (!chosen) return;
    setFrame(index);
    setCorners(chosen.corners as Point[]);
    setKant1(chosen.kant1);
    setGableA((chosen.kant1 + 3) % 4);
    setAChosen(false);
  };
  return (
    <div className="cad-fotolayout">
      <div className="cad-kort cad-fotokort">
        <div className="cad-kortrubrik">
          <h2>{sketch ? "Skissen" : "Fotot"}</h2>
          <span className="cad-dampad">
            {sketch
              ? job.frames?.length
                ? `${count(job.frames.length, "ram hittad", "ramar hittade")}, välj modulens`
                : "Dra hörnen till modulens ram"
              : job.corners?.found
                ? job.corners.certain
                  ? "4 hörn hittade"
                  : "4 hörn hittade, dra dem rätt om de ligger fel"
                : "Dra hörnen till modulens hörn"}{" "}
            · tryck på den långsida som är Kant 1 och på gavel A
          </span>
        </div>
        {sketch && job.frames?.length ? (
          <div className="cad-knapprad" role="radiogroup" aria-label="Modulens ram">
            {job.frames.map((_, index) => (
              <button key={index} type="button" role="radio" aria-checked={frame === index} className="tm-knapp liten" onClick={() => chooseFrame(index)}>
                Ram {index + 1}
              </button>
            ))}
          </div>
        ) : null}
        {corners.length === 4 ? <CornerEditor job={job} corners={corners} kant1={kant1} gableA={gableA} onCorners={setCorners} onSide={side} /> : null}
        <div className="cad-knapprad">
          <button
            type="button"
            className="tm-knapp liten"
            onClick={() => {
              setGableA(opposite(gableA));
              setAChosen(true);
            }}
          >
            Spegla: gavel A i andra änden
          </button>
          <button type="button" className="tm-knapp liten" onClick={() => side(opposite(kant1))}>
            Andra långsidan som Kant 1
          </button>
          <button
            type="button"
            className="tm-knapp liten"
            onClick={() => {
              setKant1((kant1 + 1) % 4);
              setGableA((gableA + 1) % 4);
            }}
          >
            Vrid ett kvarts varv
          </button>
        </div>
        <p className={job.corners?.derived ? "cad-ruta" : "cad-dampad"} role={job.corners?.derived ? "status" : undefined}>
          {job.corners?.why ?? "Tryck på den långsida som är Kant 1 och på gavel A."}{" "}
          {gableA === (kant1 + 3) % 4
            ? "Från gavel A längs Kant 1 ligger modulen till höger, sett ovanifrån."
            : "Speglad: från gavel A längs Kant 1 ligger modulen till vänster, sett ovanifrån."}
          {job.message ? ` ${job.message}` : ""}
        </p>
      </div>
      <div className="cad-sidokolumn">
        <div className="cad-kort">
          <h2 className="cad-overrubrik">Läs av fotot</h2>
          <dl className="cad-fakta-lista">
            <dt>Modul</dt>
            <dd>
              {module.name} · {module.scale}
            </dd>
            <dt>Bredd</dt>
            <dd className="tm-mono">
              {module.shape.kind === "trapezoid" ? `${nr(module.shape.width_a)}/${nr(module.shape.width_b)}` : module.shape.kind === "straight" ? nr(module.shape.width) : "–"} mm
            </dd>
            <dt>Längd</dt>
            <dd className="tm-mono">{job.length_given && module.shape.kind !== "curve" ? `${nr(module.shape.length)} mm` : "ur fotot"}</dd>
          </dl>
          <PriceText consent={consent} />
          {needsYes ? (
            <div className="cad-samtycke" role="group" aria-label="Vad som skickas">
              <p>{consent?.text}</p>
              <p className="cad-dampad">
                Bara mätbilden skickas, utan fotots plats och kamerans uppgifter. AI:n får svara med fasta svar om vilka spår som hänger ihop;
                koden mäter. Du godkänner det en gång.
              </p>
              <label className="cad-kryss">
                <input type="checkbox" name="samtycke" checked={agreed} onChange={(event) => setAgreed(event.currentTarget.checked)} />
                Jag godkänner att mätbilden skickas till {consent?.sent_to}.
              </label>
            </div>
          ) : null}
          <div className="cad-knapprad">
            {aiPossible ? (
              <button
                type="button"
                className="tm-knapp primar"
                disabled={busy || corners.length !== 4 || (needsYes && !agreed)}
                onClick={() => onRead?.(corners, kant1, true, needsYes && agreed, gableA, frame)}
              >
                {consent?.price ? `Läs av med AI · ${consent.price} tokens` : "Läs av med AI"}
              </button>
            ) : null}
            <button type="button" className={aiPossible ? "tm-knapp" : "tm-knapp primar"} disabled={busy || corners.length !== 4} onClick={() => onRead?.(corners, kant1, false, false, gableA, frame)}>
              Läs av utan AI · gratis
            </button>
          </div>
          <p className="cad-dampad">Utan AI svarar du själv på vilka spår som hänger ihop. Allt är ett förslag tills du godkänner spårplanen.</p>
        </div>
      </div>
    </div>
  );
}

function Progress({ job }: { job: PhotoJob }) {
  return (
    <div className="cad-kort cad-fotoprogress" role="status" aria-live="polite">
      <h2>{job.state === "queued" ? "Väntar i kön" : "Läser av fotot"}</h2>
      <progress max={100} value={job.progress} aria-label="Hur långt det har kommit" />
      <p>
        {job.step} · {job.progress} %
      </p>
      <p className="cad-dampad">Det tar ungefär en halv minut på ett vanligt foto. Du kan gå härifrån; modulen får en ny version när det är klart.</p>
    </div>
  );
}

function MeasureRow({ measure, onUse }: { measure: PhotoMeasure; onUse?: PhotoPageProps["onUseMeasure"] }) {
  const [kept, setKept] = useState(false);
  const owner = measure.owner != null ? nr(measure.owner, measure.key === "proportion" ? 2 : 1) : "–";
  const photo = nr(measure.photo, measure.key === "proportion" ? 2 : 1);
  if (measure.agrees || kept) {
    return (
      <li className="cad-mattrad">
        <span className={measure.agrees ? "cad-ok" : "cad-dampad"} aria-hidden="true">
          {measure.agrees ? "✓" : "–"}
        </span>
        <span>{measure.label}</span>
        <span className="cad-fyll" />
        <span className="tm-mono">
          {owner} · ≈ {photo}
        </span>
      </li>
    );
  }
  const off = measure.owner != null ? Math.abs(measure.owner - measure.photo) : null;
  const gable = measure.gable ?? undefined;
  const track = measure.track ?? undefined;
  return (
    <li className="cad-mattrad avviker">
      <div className="cad-mattrad-topp">
        <span className="cad-varning" aria-hidden="true">
          !
        </span>
        <b>{measure.label}</b>
        <span className="cad-fyll" />
        <b className="tm-mono">
          {owner} · ≈ {photo}
        </b>
      </div>
      <p>
        {off != null ? `${nr(off)} mm ifrån, mer än fotots ± ${nr(measure.plus_minus)} mm.` : "Du har inget mått här."} Mät gärna om.
      </p>
      <div className="cad-knapprad">
        {gable && track ? (
          <button type="button" className="tm-knapp" onClick={() => onUse?.({ gable, track, length: undefined })}>
            Använd {photo}
          </button>
        ) : measure.key === "langd" ? (
          <button type="button" className="tm-knapp" onClick={() => onUse?.({ length: measure.photo })}>
            Använd {photo}
          </button>
        ) : null}
        {measure.owner != null ? (
          <button type="button" className="tm-knapp" onClick={() => setKept(true)}>
            Behåll {owner}
          </button>
        ) : null}
      </div>
    </li>
  );
}

function openQuestions(job: PhotoJob): PhotoQuestion[] {
  return (job.questions ?? []).filter((q) => !q.answer);
}

/** Kant 1 och gavel A after reading: mirror or swap at no cost (part c2). */
function Orientation({ job, busy, onOrientation }: { job: PhotoJob; busy?: boolean; onOrientation?: PhotoPageProps["onOrientation"] }) {
  const kant1 = job.corners?.kant1 ?? 0;
  const gableA = job.corners?.gable_a ?? (kant1 + 3) % 4;
  const mirrored = gableA !== (kant1 + 3) % 4;
  return (
    <div className="cad-kort cad-orientering">
      <div className="cad-kortrubrik">
        <h2>Kant 1 och gavel A</h2>
        <span className="cad-fyll" />
        <span className="cad-tagg gron">Kostar inget</span>
      </div>
      <p className="cad-dampad">
        {mirrored ? "Speglad: modulen ligger till vänster om Kant 1 från gavel A." : "Modulen ligger till höger om Kant 1 från gavel A, som CAD ritar den."} Ett annat val
        räknas om ur samma mätbild, utan ny avläsning.
      </p>
      <div className="cad-knappstapel">
        <button type="button" className="tm-knapp" disabled={busy} onClick={() => onOrientation?.(kant1, opposite(gableA))}>
          Byt gavel A och B
        </button>
        <button type="button" className="tm-knapp" disabled={busy} onClick={() => onOrientation?.(opposite(kant1), gableA)}>
          Kant 1 på andra långsidan
        </button>
      </div>
    </div>
  );
}

function Result({ module, job, navigate, onAnswer, onUseMeasure, onApprovePlan, onOrientation, busy }: PhotoPageProps & { job: PhotoJob }) {
  const [tracks, setTracks] = useState(true);
  const sketch = job.profile === "skiss";
  const measures = job.measures ?? [];
  const agree = measures.filter((m) => m.agrees).length;
  const open = openQuestions(job);
  const topology = open.filter((q) => q.topology);
  const others = open.filter((q) => !q.topology);
  const quality = job.quality;
  const gauge = job.gauge;
  const summary = job.summary;
  const length = job.length;
  const shape = module.shape;
  const width = shape.kind === "trapezoid" ? shape.width_a : shape.kind === "straight" ? shape.width : 0;
  const worstPm = Math.max(job.length_plus_minus ?? 0, ...measures.map((m) => m.plus_minus));
  return (
    <>
      <ul className="cad-kort cad-kedjerad" aria-label="Vad fotot gav">
        <li>
          <span className="cad-ok">✓</span> 4 hörn {job.corners?.found ? "hittade" : "satta"}
        </li>
        <li>
          <span className="cad-ok">✓</span> Bilden uträtad
          {quality ? ` · ${nr(quality.px_per_mm)} px per mm` : ""}
        </li>
        {gauge?.value != null ? (
          <li>
            <span className={gauge.agrees ? "cad-ok" : "cad-varning"}>{gauge.agrees ? "✓" : "⚠"}</span> Skala från spårvidden · {module.scale}{" "}
            {nr(gauge.nominal)} mm på {gauge.places} ställen
          </li>
        ) : null}
        <li>
          <span className="cad-ok">✓</span> Spåren ritade
        </li>
        {measures.length ? (
          <li className={agree < measures.length ? "avviker" : undefined}>
            <span className={agree < measures.length ? "cad-varning" : "cad-ok"}>{agree < measures.length ? "⚠" : "✓"}</span> {agree} av{" "}
            {measures.length} mått stämmer
          </li>
        ) : null}
        <li className="cad-fyll" aria-hidden="true" />
        <li className="cad-dampad">mätosäkerhet ±{nr(worstPm)} mm</li>
      </ul>
      {quality && quality.gates.some((g) => g.level !== "ok") ? (
        <ul className="cad-ruta cad-grindar" aria-label="Fotots kvalitet">
          {quality.gates
            .filter((g) => g.level !== "ok")
            .map((g) => (
              <li key={g.key} className={g.level}>
                {LEVEL_MARK[g.level]} {g.text}
              </li>
            ))}
        </ul>
      ) : null}
      <div className="cad-fotolayout">
        <div className="cad-hoger">
          <div className="cad-kort cad-fotokort">
            <div className="cad-kortrubrik">
              <h2>{sketch ? "Skissen" : "Fotot"}</h2>
              <span className="cad-dampad">
                {sketch ? "inläst" : "taget"} {dayText(job.created_at)}
                {job.ai ? ` · läst av ${job.ai}` : " · läst utan AI"}
              </span>
              <span className="cad-fyll" />
              <div className="cad-vaxel" role="group" aria-label="Visa">
                <button type="button" aria-pressed={!tracks} onClick={() => setTracks(false)}>
                  {sketch ? "Bara skissen" : "Bara fotot"}
                </button>
                <button type="button" aria-pressed={tracks} onClick={() => setTracks(true)}>
                  {sketch ? "Med spåren" : "Med AI-spåren"}
                </button>
              </div>
            </div>
            <PhotoWithTracks job={job} tracks={tracks} />
          </div>
          <div className="cad-kort">
            <div className="cad-kortrubrik">
              <h2>Uträtad ritning</h2>
              <span className="cad-dampad">fotot omräknat till millimeter</span>
              <span className="cad-fyll" />
              <span className="cad-legend">
                <i className="streckad orange" /> {job.profile === "skiss" ? "Förslag ur skissen" : "AI-förslag"}
              </span>
            </div>
            <Straightened module={module} job={job} />
            <p className="cad-dampad cad-centrerad">
              {length != null ? `${nr(length, 0)} × ${nr(width, 0)} mm enligt fotot` : `Längden räknas inte ur fotot`}
              {job.length_given && shape.kind !== "curve" ? ` · du angav ${nr(shape.length, 0)} × ${nr(width, 0)}` : ""}
            </p>
          </div>
        </div>
        <div className="cad-sidokolumn">
          <div className="cad-kort">
            <div className="cad-kortrubrik">
              <h2>Dina mått mot fotot</h2>
              <span className="cad-fyll" />
              <span className="cad-dampad">du · fotot</span>
            </div>
            <ul className="cad-mattlista">
              {measures.map((m) => (
                <MeasureRow key={m.key} measure={m} onUse={onUseMeasure} />
              ))}
            </ul>
            {!job.length_given && length != null ? (
              <p>
                <a href={photoPath(module.id, job.id, "langd")} onClick={linkClick(navigate, photoPath(module.id, job.id, "langd"))}>
                  Längden ur fotot: {nr(length, 0)} mm ± {nr(job.length_plus_minus ?? 0)}
                </a>
              </p>
            ) : null}
          </div>
          <Orientation job={job} busy={busy} onOrientation={onOrientation} />
          {others.map((q) => (
            <div key={q.key} className="cad-kort cad-fraga">
              <h2>{q.title}</h2>
              <p>{q.text}</p>
              <div className="cad-knapprad">
                {q.choices.map((c) => (
                  <button
                    key={c.id}
                    type="button"
                    className="tm-knapp"
                    disabled={busy}
                    onClick={() => {
                      if (q.kind === "scale" && c.id === "anvand") {
                        const match = /(\d+)$/.exec(q.key);
                        if (match) onUseMeasure?.({ width: Number(match[1]) });
                      }
                      onAnswer?.(q.key, c.id);
                    }}
                  >
                    {c.text}
                  </button>
                ))}
              </div>
            </div>
          ))}
          <div className="cad-kort">
            <div className="cad-kortrubrik">
              <h2>Spårplanen</h2>
              <span className="cad-tagg forslag">{job.profile === "skiss" ? "Förslag ur skissen, ± 20 mm" : "AI-förslag"}</span>
            </div>
            {summary ? (
              <dl className="cad-fakta-lista">
                <dt>Spår vid gavlarna</dt>
                <dd>
                  {summary.tracks_a} vid A · {summary.tracks_b} vid B
                </dd>
                <dt>Växlar</dt>
                <dd>{summary.switches}</dd>
                {summary.crossings ? (
                  <>
                    <dt>Korsningar</dt>
                    <dd>{summary.crossings}</dd>
                  </>
                ) : null}
                {summary.ends ? (
                  <>
                    <dt>Stickspår</dt>
                    <dd>{count(summary.ends, "med stoppbock", "med stoppbock")}</dd>
                  </>
                ) : null}
                <dt>Spår totalt</dt>
                <dd>≈ {nr(summary.track_length / 1000)} m</dd>
                {summary.deviation ? (
                  <>
                    <dt>Avviker från {sketch ? "skissen" : "fotot"}</dt>
                    <dd>
                      median {nr(summary.deviation.median, 2)} mm, högst {nr(summary.deviation.max, 2)} mm
                    </dd>
                  </>
                ) : null}
              </dl>
            ) : null}
            {topology.length ? (
              <p className="cad-ruta">
                {count(topology.length, "parti", "partier")} att kontrollera innan spårplanen kan godkännas.{" "}
                <a href={photoPath(module.id, job.id, "osakert", topology[0]?.key)} onClick={linkClick(navigate, photoPath(module.id, job.id, "osakert", topology[0]?.key))}>
                  Svara
                </a>
              </p>
            ) : null}
            <div className="cad-knappstapel">
              <button type="button" className="tm-knapp primar" disabled={busy || topology.length > 0 || module.version !== module.latest} onClick={() => onApprovePlan?.()}>
                Godkänn spårplanen
              </button>
              <a className="tm-knapp" href={drawingPath(module.id)} onClick={linkClick(navigate, drawingPath(module.id))}>
                Rätta i ritningen
              </a>
            </div>
            <p className="cad-dampad">Spårplanen sparas som förslag tills du godkänt den. Dina mått ändras bara om du själv väljer det.</p>
          </div>
        </div>
      </div>
    </>
  );
}

function Kontroll(props: PhotoPageProps) {
  const { module, job, navigate } = props;
  const open = job ? openQuestions(job) : [];
  const disagree = job ? (job.measures ?? []).filter((m) => !m.agrees).length : 0;
  const toCheck = disagree + open.length;
  return (
    <section className="cad-sida" aria-labelledby="rubrik">
      <Crumbs module={module} here="Foto och kontroll" navigate={navigate} />
      <div className="cad-rubrikrad">
        <h1 id="rubrik">Foto och kontroll</h1>
        <span className="cad-pill tm-mono">{module.number}</span>
        {job?.state === "done" && toCheck ? <span className="cad-tagg orange">{count(toCheck, "sak att kolla", "saker att kolla")}</span> : null}
        <span className="cad-fyll" />
        <a className="tm-knapp" href={modulePath(module.id, "foto")} onClick={linkClick(navigate, modulePath(module.id, "foto"))}>
          Byt foto
        </a>
      </div>
      {props.error ? (
        <p className="cad-fel" role="alert">
          {props.error}
        </p>
      ) : null}
      {!job ? <p>Hämtar fotot …</p> : null}
      {job && (job.state === "corners" || job.state === "failed") ? <ConfirmCorners key={job.id} {...props} job={job} /> : null}
      {job && (job.state === "queued" || job.state === "running") ? <Progress job={job} /> : null}
      {job && job.state === "done" ? <Result {...props} job={job} /> : null}
    </section>
  );
}

// --- Längden ur fotot ---------------------------------------------------------------------------

function Langd(props: PhotoPageProps) {
  const { module, job, navigate, onUseMeasure } = props;
  const [typed, setTyped] = useState("");
  const input = useRef<HTMLInputElement>(null);
  if (!job || job.state !== "done" || job.length == null) {
    return (
      <section className="cad-sida">
        <Crumbs module={module} here="Längden ur fotot" navigate={navigate} />
        <p>{job ? "Fotot är inte läst än." : "Hämtar fotot …"}</p>
      </section>
    );
  }
  const length = job.length;
  const pm = job.length_plus_minus ?? 0;
  const shape = module.shape;
  const width = shape.kind === "trapezoid" ? shape.width_a : shape.kind === "straight" ? shape.width : 0;
  const sleepers = job.sleepers;
  const gauge = job.gauge;
  const quality = job.quality;
  const tilt = quality?.tilt ?? 0;
  const value = Number(typed.replace(",", "."));
  const outside = typed.trim() !== "" && value > 0 && Math.abs(value - length) > pm;
  const kontroll = photoPath(module.id, job.id);
  return (
    <section className="cad-sida" aria-labelledby="rubrik">
      <nav className="cad-brodsmulor" aria-label="Var du är">
        <a href={PATHS.library} onClick={linkClick(navigate, PATHS.library)}>
          Moduler
        </a>{" "}
        ›{" "}
        <a href={modulePath(module.id)} onClick={linkClick(navigate, modulePath(module.id))}>
          {module.name}
        </a>{" "}
        ›{" "}
        <a href={kontroll} onClick={linkClick(navigate, kontroll)}>
          Foto och kontroll
        </a>
      </nav>
      <div className="cad-rubrikrad">
        <h1 id="rubrik">Längden ur fotot</h1>
        <span className="cad-tagg orange">Förslag</span>
        <span className="cad-fyll" />
        <button type="button" className="tm-knapp" onClick={() => input.current?.focus()}>
          Jag skriver in längden
        </button>
        <button
          type="button"
          className="tm-knapp primar"
          onClick={() => {
            if (shape.kind !== "curve" && Math.abs(shape.length - length) > 0.5) onUseMeasure?.({ length });
            navigate?.(kontroll);
          }}
        >
          ✓ Använd {nr(length, 0)} mm
        </button>
      </div>
      <div className="cad-fotolayout">
        <div>
          <div className="cad-kort cad-fotokort">
            {job.measure ? (
              <svg
                className="cad-fotobild"
                viewBox={`${f(job.measure.grid.x0 - 4)} ${f(job.measure.grid.y0 - 4)} ${f(job.measure.grid.width / job.measure.grid.ppm + 8)} ${f(job.measure.grid.height / job.measure.grid.ppm + 8)}`}
                role="img"
                aria-label={`Mätbilden, längden ≈ ${nr(length, 0)} mm`}
              >
                <PhotoImage layer={job.measure} />
                <line className="cad-langdlinje" x1={0} y1={width - 4} x2={length} y2={width - 4} strokeWidth={3} strokeDasharray="14 8" />
                <line className="cad-breddlinje" x1={length - 6} y1={0} x2={length - 6} y2={width} strokeWidth={4} />
                <text className="cad-langdtext" x={length / 2} y={width - 18} textAnchor="middle" fontSize={Math.max(18, width / 22)}>
                  längd ≈ {nr(length, 0)} mm
                </text>
                <text className="cad-breddtext" x={length - 18} y={width / 2} textAnchor="end" fontSize={Math.max(18, width / 22)}>
                  {nr(width, 0)}
                </text>
              </svg>
            ) : null}
          </div>
          <p className="cad-dampad cad-bildtext">
            <span>Fotot uträtat till {quality ? nr(quality.px_per_mm) : "–"} px per mm</span>
            <span>{job.corners?.found ? "Hörnen hittade i alla fyra" : "Hörnen satta för hand"}</span>
            <span>{tilt < 3 ? "Taget nästan rakt ovanifrån" : `Taget ${nr(tilt)}° från rakt ovanifrån, uträtat`}</span>
          </p>
        </div>
        <div className="cad-sidokolumn">
          <div className="cad-kort">
            <h2 className="cad-overrubrik">Dina mått</h2>
            <dl className="cad-fakta-lista">
              <dt>Bredd</dt>
              <dd className="tm-mono">{nr(width)} mm</dd>
              <dt>Längd</dt>
              <dd>{job.length_given && shape.kind !== "curve" ? <span className="tm-mono">{nr(shape.length)} mm</span> : "ej ifylld"}</dd>
            </dl>
          </div>
          <div className="cad-kort">
            <h2 className="cad-overrubrik">Uträknat ur fotot</h2>
            <p className="cad-stortal">
              <b>{nr(length, 0)}</b> mm <span className="cad-dampad">± {nr(pm)} mm</span>
            </p>
            <p>
              Bredden {nr(width, 0)} mm och de fyra hörnen ger skalan längs båda ledderna. Det fungerar också för trapetsmoduler, där
              förskjutningen räknas fram samtidigt.
            </p>
          </div>
          <div className="cad-kort">
            <h2 className="cad-overrubrik">Kontroll med spåret</h2>
            <table className="cad-tabell">
              <thead>
                <tr>
                  <th scope="col">Mätning</th>
                  <th scope="col">Värde</th>
                  <th scope="col">
                    <span className="cad-dold">Stämmer</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <th scope="row">Sliperdelning, raka spår</th>
                  <td className="tm-mono">{sleepers?.straight != null ? `${nr(sleepers.straight, 2)} mm` : "–"}</td>
                  <td>{sleepers?.straight != null ? <span className="cad-tagg gron">✓ mätt</span> : <span className="cad-tagg">inga raka</span>}</td>
                </tr>
                <tr>
                  <th scope="row">Sliperdelning, sneda spåret{sleepers?.slanting_angle != null ? ` (${nr(sleepers.slanting_angle, 0)}°)` : ""}</th>
                  <td className="tm-mono">{sleepers?.slanting != null ? `${nr(sleepers.slanting, 2)} mm` : "–"}</td>
                  <td>
                    {sleepers?.agree == null ? (
                      <span className="cad-tagg">inga sneda</span>
                    ) : sleepers.agree ? (
                      <span className="cad-tagg gron">✓ lika</span>
                    ) : (
                      <span className="cad-tagg orange">olika</span>
                    )}
                  </td>
                </tr>
                <tr>
                  <th scope="row">Spårvidd</th>
                  <td className="tm-mono">{gauge?.value != null ? `${nr(gauge.value, 2)} mm` : "–"}</td>
                  <td>
                    {gauge?.agrees == null ? (
                      <span className="cad-tagg">för brusig</span>
                    ) : gauge.agrees ? (
                      <span className="cad-tagg gron">✓ {nr(gauge.nominal)}</span>
                    ) : (
                      <span className="cad-tagg orange">inte {nr(gauge.nominal)}</span>
                    )}
                  </td>
                </tr>
              </tbody>
            </table>
            <p className="cad-dampad">
              {sleepers?.agree
                ? "Sliperdelningen är densamma på raka och sneda spår, så skalan stämmer på längden också."
                : sleepers?.agree === false
                  ? "Sliperdelningen skiljer mellan raka och sneda spår: kontrollera hörnen innan du litar på längden."
                  : "Modulen har inget snett spår att jämföra med; längden vilar på hörnen och bredden."}
              {gauge?.agrees == null ? " Spårvidden varierar för mycket för att användas här." : ""}
            </p>
          </div>
          <div className="cad-kort">
            <h2 className="cad-overrubrik">Mät gärna själv</h2>
            <label className="cad-falt">
              <span>Uppmätt längd</span>
              <span className="cad-mm">
                <input ref={input} name="uppmatt-langd" inputMode="decimal" placeholder={nr(length, 0)} value={typed} onChange={(event) => setTyped(event.currentTarget.value)} />
                <span aria-hidden="true">mm</span>
              </span>
            </label>
            <p className={outside ? "cad-fel" : "cad-dampad"} role={outside ? "alert" : undefined}>
              Får du under {nr(length - pm, 0)} eller över {nr(length + pm, 0)} mm stämmer något inte. Lita på tumstocken och ta ett nytt foto.
            </p>
            <button
              type="button"
              className="tm-knapp"
              disabled={!(value > 0)}
              onClick={() => {
                onUseMeasure?.({ length: value });
                navigate?.(kontroll);
              }}
            >
              Spara {typed.trim() ? `${typed.trim()} mm` : "längden"}
            </button>
          </div>
        </div>
      </div>
    </section>
  );
}

// --- Osäkert parti ------------------------------------------------------------------------------

const SKETCH_HINT: Record<string, string> = {
  two_switches: "Spåren förbinds. Ett tåg kan byta spår här.",
  crossing: "Spåren korsar utan förbindelse. Inga växlar.",
  single_slip: "En korsning där ett tåg kan byta spår åt ena hållet.",
  double_slip: "En korsning där ett tåg kan byta spår åt båda hållen.",
  joined: "Spåren hänger ihop.",
  apart: "Spåren hänger inte ihop här.",
};

/** A choice's sketch: two tracks in grey with the black centre lines, as the view Osakert. */
export function Sketch({ kind }: { kind: NonNullable<PhotoChoice["sketch"]> | null | undefined }) {
  const bed = (d: string, key: string) => <path key={key} d={d} className="cad-skiss-bank" />;
  const line = (d: string, key: string) => <path key={key} d={d} className="cad-skiss-linje" />;
  const paths: [string, string][] =
    kind === "crossing" || kind === "single_slip" || kind === "double_slip"
      ? [
          ["M10 20C70 20 100 50 120 50S170 80 230 80", "a"],
          ["M10 80C70 80 100 50 120 50S170 20 230 20", "b"],
        ]
      : kind === "apart"
        ? [
            ["M10 25H230", "a"],
            ["M10 75H230", "b"],
          ]
        : [
            ["M10 25H230", "a"],
            ["M10 75H230", "b"],
            ["M70 25C110 25 120 75 170 75", "c"],
          ];
  return (
    <svg className="cad-skiss" viewBox="0 0 240 100" aria-hidden="true">
      {paths.map(([d, key]) => bed(d, `bank-${key}`))}
      {paths.map(([d, key]) => line(d, `linje-${key}`))}
      {kind === "two_switches" || kind === "joined" ? (
        <>
          <circle cx={70} cy={25} r={7} className="cad-skiss-vaxel" />
          <circle cx={170} cy={75} r={7} className="cad-skiss-vaxel" />
        </>
      ) : null}
      {kind === "crossing" ? <path d="M120 40L130 50L120 60L110 50Z" className="cad-skiss-korsning" /> : null}
      {kind === "single_slip" || kind === "double_slip" ? (
        <>
          <path d="M85 35C105 40 135 40 155 35" className="cad-skiss-linje" />
          {kind === "double_slip" ? <path d="M85 65C105 60 135 60 155 65" className="cad-skiss-linje" /> : null}
        </>
      ) : null}
    </svg>
  );
}

function Osakert(props: PhotoPageProps) {
  const { module, job, question, navigate, onAnswer, onCloseup, consent, busy } = props;
  const all = job ? (job.questions ?? []).filter((q) => q.topology) : [];
  const open = all.filter((q) => !q.answer);
  const asked = all.find((q) => q.key === question) ?? open[0] ?? all[0];
  const [chosen, setChosen] = useState<string | null>(asked?.answer ?? asked?.ai ?? asked?.code ?? null);
  const kontroll = job ? photoPath(module.id, job.id) : modulePath(module.id);
  if (!job || !asked) {
    return (
      <section className="cad-sida">
        <Crumbs module={module} here="Att kolla" navigate={navigate} />
        <h1>Inget parti att kontrollera</h1>
        <p>
          <a href={kontroll} onClick={linkClick(navigate, kontroll)}>
            Till Foto och kontroll
          </a>
        </p>
      </section>
    );
  }
  const number = all.indexOf(asked) + 1;
  const switches = job.summary?.switches ?? 0;
  const gableTracks = (job.summary?.tracks_a ?? 0) + (job.summary?.tracks_b ?? 0);
  const layer = job.measure;
  const span = 260;
  const fromB = module.shape.kind !== "curve" ? module.shape.length - asked.at[0] : 0;
  const choice = asked.choices.find((c) => c.id === chosen);
  return (
    <section className="cad-sida" aria-labelledby="rubrik">
      <Crumbs module={module} here="Att kolla" navigate={navigate} />
      <div className="cad-rubrikrad">
        <h1 id="rubrik">Ett parti att kontrollera</h1>
        <span className="cad-tagg gul">
          ⚠ {number} av {all.length}
        </span>
        <span className="cad-dampad">
          Övriga {count(switches, "växel", "växlar")} och {count(gableTracks, "gavelspår", "gavelspår")} är klara
        </span>
      </div>
      {props.error ? (
        <p className="cad-fel" role="alert">
          {props.error}
        </p>
      ) : null}
      <div className="cad-osakert">
        <div>
          <div className="cad-kort cad-fotokort">
            {layer ? (
              <svg
                className="cad-fotobild"
                viewBox={`${f(asked.at[0] - span)} ${f(asked.at[1] - span * 0.5)} ${f(span * 2)} ${f(span)}`}
                role="img"
                aria-label="Partiet förstorat ur fotot"
              >
                <PhotoImage layer={layer} />
                <ellipse className="cad-osakert-ring" cx={asked.at[0]} cy={asked.at[1]} rx={span * 0.32} ry={span * 0.22} strokeWidth={2.5} strokeDasharray="10 7" />
              </svg>
            ) : null}
          </div>
          <p className="cad-dampad">
            Förstorat ur fotot, {mmText(Math.min(asked.at[0], fromB))} mm från gavel {asked.at[0] <= fromB ? "A" : "B"}.
            {job.quality ? ` Fotot gav ${nr(job.quality.px_per_mm)} px per mm${job.quality.px_per_mm < 2 ? ", så här finns bara några få pixlar per räl." : "."}` : ""}
          </p>
        </div>
        <div className="cad-hoger">
          <div className="cad-kort">
            <h2 className="cad-overrubrik">{asked.source === "ai" ? "Vad AI:n ser" : "Vad koden ser"}</h2>
            <p>{asked.text}</p>
            {asked.closeup_ai ? <p className="cad-dampad">Med närbilden: {asked.closeup_ai}</p> : null}
          </div>
          <div className="cad-val" role="radiogroup" aria-label={asked.title}>
            {asked.choices.map((c) => (
              <label key={c.id} className={`cad-kort cad-valkort${chosen === c.id ? " valt" : ""}`}>
                <span className="cad-valrubrik">
                  <input type="radio" name="parti" value={c.id} checked={chosen === c.id} onChange={() => setChosen(c.id)} />
                  <b>{c.text}</b>
                  {c.id === asked.ai ? <span className="cad-tagg forslag">AI:n</span> : null}
                  {c.id === asked.code && asked.code !== asked.ai ? <span className="cad-tagg">koden</span> : null}
                </span>
                {c.sketch ? <Sketch kind={c.sketch} /> : null}
                <span className="cad-dampad">{c.hint ?? (c.sketch ? SKETCH_HINT[c.sketch] : "")}</span>
              </label>
            ))}
          </div>
          <label className="cad-kort cad-narbild">
            <span className="cad-narbild-ikon" aria-hidden="true">
              ◉
            </span>
            <span>
              <b>Ta en närbild av partiet</b>
              <br />
              <span className="cad-dampad">Håll mobilen 30 cm ovanför. AI:n tittar igen med närbilden.</span>
            </span>
            <span className="cad-fyll" />
            <span className="cad-pill">{consent?.own_ai ? "gratis" : `◎ ${consent?.price ?? 12} tokens`}</span>
            <input
              className="cad-dold"
              type="file"
              name="narbild"
              accept="image/jpeg,image/png"
              disabled={busy || !consent?.available}
              onChange={(event) => {
                const file = event.currentTarget.files?.[0];
                if (file) onCloseup?.(asked.key, file, Boolean(consent && !consent.given));
              }}
            />
          </label>
          <div className="cad-sparrad">
            <span className="cad-dampad">Resten av spårplanen påverkas inte av valet.</span>
            <span className="cad-fyll" />
            <a className="tm-knapp" href={kontroll} onClick={linkClick(navigate, kontroll)}>
              Fråga mig senare
            </a>
            <button type="button" className="tm-knapp primar" disabled={busy || !chosen} onClick={() => chosen && onAnswer?.(asked.key, chosen)}>
              ✓ Spara{choice ? `: ${choice.text.toLowerCase()}` : ""}
            </button>
          </div>
        </div>
      </div>
    </section>
  );
}

/** Foto och kontroll, Längden ur fotot or Osäkert parti, by the address. */
export function PhotoPage(props: PhotoPageProps): ReactNode {
  if (props.view === "langd") return <Langd {...props} />;
  if (props.view === "osakert") return <Osakert key={props.question ?? ""} {...props} />;
  return <Kontroll {...props} />;
}

// --- Modulens sida: the Foto tab -----------------------------------------------------------------

export type PhotoTabProps = {
  module: Module;
  consent: PhotoConsent | null;
  storage?: StorageUse | null;
  busy?: boolean;
  error?: string | null;
  navigate?: Navigate;
  now?: Date;
  onUpload?: (start: PhotoStart, files: File[]) => void;
  onPhotoSettings?: (change: { keep_original?: boolean; training?: boolean }) => void;
  onRecompute?: (job: string) => void;
};

const DAY = 24 * 60 * 60 * 1000;

/** The Foto tab (CAD-05): the measuring image the version came from, how long the original is
 * kept, Spara original, the training opt-in, and Räkna om med nya versionen. */
export function PhotoTab({ module, consent, storage, busy, error, navigate, now = new Date(), onUpload, onPhotoSettings, onRecompute }: PhotoTabProps) {
  const photo = module.photo;
  const old = module.version !== module.latest;
  const days = photo?.original_until ? Math.max(0, Math.ceil((new Date(photo.original_until).getTime() - now.getTime()) / DAY)) : null;
  return (
    <div className="cad-fotoflik">
      {photo ? (
        <div className="cad-fotolayout">
          <div className="cad-kort cad-fotokort">
            <div className="cad-kortrubrik">
              <h2>Mätbilden</h2>
              <span className="cad-dampad">
                uträtad till millimeter · {dayText(photo.taken_at)} · bildkedjan {photo.chain}
              </span>
            </div>
            <svg
              className="cad-fotobild"
              viewBox={`${f(photo.grid.x0)} ${f(photo.grid.y0)} ${f(photo.grid.width / photo.grid.ppm)} ${f(photo.grid.height / photo.grid.ppm)}`}
              role="img"
              aria-label={`Mätbilden av ${module.name}`}
            >
              <PhotoImage layer={{ job: photo.job, url: photo.display_url, grid: photo.grid }} />
            </svg>
            <p className="cad-knapprad">
              <a className="tm-knapp" href={photoPath(module.id, photo.job)} onClick={linkClick(navigate, photoPath(module.id, photo.job))}>
                Foto och kontroll
              </a>
              <a className="tm-knapp" href={photo.measure_url} download>
                Hämta mätbilden
              </a>
            </p>
          </div>
          <div className="cad-sidokolumn">
            <div className="cad-kort">
              <h2 className="cad-overrubrik">Originalet</h2>
              <p>
                {photo.original_kept
                  ? "Originalet sparas och räknas i ditt utrymme."
                  : days != null
                    ? `Originalet sparas till modulen godkänns, högst ${count(days, "dag", "dagar")} till (${dayText(photo.original_until ?? "")}).`
                    : "Originalet är borttaget. Mätbilden finns kvar."}
              </p>
              <label className="cad-kryss">
                <input
                  type="checkbox"
                  name="spara-original"
                  checked={module.keep_original ?? false}
                  disabled={!module.may_edit || busy || (!photo.original_kept && days == null)}
                  onChange={(event) => onPhotoSettings?.({ keep_original: event.currentTarget.checked })}
                />
                Spara original
              </label>
              {storage ? (
                <p className="cad-dampad">
                  Ditt utrymme för modulfoton: {nr(storage.used / MB)} av {nr(storage.limit / MB, 0)} MB, skilt från Catalogs.
                  {storage.waiting ? ` ${nr(storage.waiting / MB)} MB original väntar på godkännande och räknas inte.` : ""}
                </p>
              ) : null}
            </div>
            <div className="cad-kort">
              <h2 className="cad-overrubrik">Träna TrainMeets spårmodell</h2>
              <label className="cad-kryss">
                <input
                  type="checkbox"
                  name="traning"
                  checked={Boolean(module.training_at)}
                  disabled={!module.may_edit || busy}
                  onChange={(event) => onPhotoSettings?.({ training: event.currentTarget.checked })}
                />
                Ja, TrainMeet får använda mätbilden och spårplanen för att träna sin spårmodell.
              </label>
              <p className="cad-dampad">
                {module.training_at ? `Du sa ja ${dayText(module.training_at)}. ` : ""}Bara mätbilden och geometrin, aldrig originalet. Inget tränas
                än. Du kan ändra dig när som helst.
              </p>
            </div>
            <div className="cad-kort">
              <h2 className="cad-overrubrik">Bildkedjan</h2>
              <p>
                Läst med version {photo.chain}.{" "}
                {photo.newer_chain ? "En nyare version finns. Samma foto ger samma resultat tills du räknar om." : "Det är den senaste versionen."}
              </p>
              <button type="button" className="tm-knapp" disabled={!photo.newer_chain || !module.may_edit || old || busy} onClick={() => onRecompute?.(photo.job)}>
                Räkna om med nya versionen
              </button>
              <p className="cad-dampad">Spåren behåller sina nummer. Det kostar inget att räkna om.</p>
            </div>
          </div>
        </div>
      ) : (
        <div className="cad-kort">
          <h2>Modulen är inte fotad än</h2>
          <p>Fota modulen ovanifrån så ritar koden spåren och jämför dina mått med fotot.</p>
        </div>
      )}
      {module.may_edit && !old ? (
        <PhotoUpload module={module} scale={module.scale} consent={consent} storage={storage} busy={busy} error={error} navigate={navigate} onUpload={onUpload} />
      ) : null}
    </div>
  );
}
