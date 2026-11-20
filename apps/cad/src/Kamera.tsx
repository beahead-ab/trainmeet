// 3 Fota (#90, CAD1, bildkedjan "1. Fotohjälp i mobilen"): the phone's camera with the photo help.
// The stream is shown with the module's four corners found live on a downscaled frame, the level
// from the phone's tilt, and lights for the frame, the angle, the focus, the light and the
// stillness (fotohjalp.ts). When all is green for a moment the photo is taken by itself. The final
// photo is in full resolution: ImageCapture.takePhoto() where the browser has it (Android), the
// stream itself when it is large enough, or else the phone's own camera through the file picker
// after a Sikta så här view (iOS). Without a camera, as on a computer, the file picker is all.
import { useCallback, useEffect, useRef, useState, type RefObject } from "react";
import {
  analysisSize,
  clipped,
  finalWay,
  findQuad,
  frameCheck,
  FULL_SIDE,
  grayOf,
  hold,
  motion,
  shadowRatio,
  sharpness,
  tiltOf,
  trackSharpness,
  verdict,
  type Hold,
  type Lights,
  type Quad,
  type SharpTrack,
  type Verdict,
} from "./fotohjalp";

export const MAX_PARTS = 4;
const TICK_MS = 150;

type ImageCaptureLike = { takePhoto(): Promise<Blob> };
type ImageCaptureClass = new (track: MediaStreamTrack) => ImageCaptureLike;
type PermissionAsker = { requestPermission?: () => Promise<"granted" | "denied" | "default"> };

function imageCaptureClass(): ImageCaptureClass | null {
  const found = (globalThis as unknown as { ImageCapture?: ImageCaptureClass }).ImageCapture;
  return typeof found === "function" ? found : null;
}

/** iOS asks before the page may read the phone's orientation, on a tap. */
function orientationAsker(): PermissionAsker | null {
  const event = (globalThis as unknown as { DeviceOrientationEvent?: PermissionAsker }).DeviceOrientationEvent;
  return event && typeof event.requestPermission === "function" ? event : null;
}

/** The phone's tilt from straight down, in a ref (the events come 60 times a second). */
function useLevel(): { tilt: RefObject<number | null>; ask: boolean; denied: boolean; turnOn: () => void } {
  const tilt = useRef<number | null>(null);
  const [ask, setAsk] = useState(() => orientationAsker() !== null);
  const [denied, setDenied] = useState(false);
  useEffect(() => {
    if (ask || typeof window === "undefined") return;
    const seen = (event: DeviceOrientationEvent) => {
      if (event.beta == null || event.gamma == null) return;
      tilt.current = tiltOf(event.beta, event.gamma);
    };
    window.addEventListener("deviceorientation", seen);
    return () => window.removeEventListener("deviceorientation", seen);
  }, [ask]);
  const turnOn = () => {
    orientationAsker()
      ?.requestPermission?.()
      .then(
        (answer) => {
          // A no does not stop the photo: the level is unknown, and the chain measures the tilt.
          setAsk(false);
          if (answer !== "granted") setDenied(true);
        },
        () => {
          setAsk(false);
          setDenied(true);
        },
      );
  };
  return { tilt, ask, denied, turnOn };
}

function grab(video: HTMLVideoElement): Promise<Blob | null> {
  const canvas = document.createElement("canvas");
  canvas.width = video.videoWidth;
  canvas.height = video.videoHeight;
  canvas.getContext("2d")?.drawImage(video, 0, 0);
  return new Promise((done) => canvas.toBlob((blob) => done(blob), "image/jpeg", 0.92));
}

function asFile(blob: Blob, n: number): File {
  const png = blob.type === "image/png";
  return new File([blob], `foto-${n}.${png ? "png" : "jpg"}`, { type: png ? "image/png" : "image/jpeg" });
}

const LIGHTS: [keyof Lights, string][] = [
  ["ram", "Ram"],
  ["vinkel", "Vinkel"],
  ["skarpa", "Skärpa"],
  ["ljus", "Ljus"],
  ["stilla", "Stilla"],
];

const MARK = { ok: "✓", warn: "!", unknown: "–" } as const;

/** What the view shows over the stream: the corners, the lights, the analysis frame, the hold and the tilt. */
export type CameraView = { quad: Quad | null; verdict: Verdict; width: number; height: number; progress: number; tilt: number | null };

/** The lights under the view: each check's state, for the eye and for a screen reader. */
export function LightRow({ lights }: { lights: Lights }) {
  return (
    <ul className="mob-lampor" aria-label="Fotohjälpen">
      {LIGHTS.map(([key, label]) => (
        <li key={key} className={lights[key]} data-lampa={key}>
          <span aria-hidden="true">{MARK[lights[key]]}</span> {label}
          <span className="cad-dold">{lights[key] === "ok" ? ": grönt" : lights[key] === "warn" ? ": inte än" : ": okänt"}</span>
        </li>
      ))}
    </ul>
  );
}

/** The overlay on the stream: the corners as found, green when the frame is right. */
export function Overlay({ seen }: { seen: CameraView }) {
  const { quad, width, height } = seen;
  const ok = seen.verdict.lights.ram === "ok";
  return (
    <svg className="mob-overlay" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="xMidYMid meet" aria-hidden="true">
      {quad ? (
        <>
          <polygon className={ok ? "mob-ram ok" : "mob-ram"} points={quad.map((p) => p.join(",")).join(" ")} strokeWidth={Math.max(width, height) / 160} />
          {quad.map((p, i) => (
            <circle key={i} className="mob-horn" cx={p[0]} cy={p[1]} r={Math.max(width, height) / 70} strokeWidth={Math.max(width, height) / 300} />
          ))}
        </>
      ) : null}
    </svg>
  );
}

/** The level: a bubble that moves with the tilt, green within 20°. */
export function Level({ tilt }: { tilt: number | null }) {
  const off = tilt == null ? 0 : Math.min(1, tilt / 40);
  return (
    <div className={`mob-vattenpass${tilt != null && tilt <= 20 ? " ok" : ""}`} role="status" aria-label="Vattenpasset">
      <svg viewBox="-20 -20 40 40" aria-hidden="true">
        <circle r={17} className="mob-vattenpass-ring" />
        <circle r={6} cy={-off * 11} className="mob-vattenpass-bubbla" />
      </svg>
      <b>{tilt == null ? "–" : `${Math.round(tilt)}°`}</b>
      <span>lutning</span>
    </div>
  );
}

type Props = {
  busy?: boolean;
  /** The photos taken, in full resolution: one, or 2–4 parts of a long module. */
  onPhotos: (files: File[]) => void;
  /** For the tests and the screenshots: what the view shows without a stream. */
  initial?: { camera: "starting" | "on" | "none"; seen?: CameraView | null; parts?: number; aim?: boolean };
};

export function Kamera({ busy = false, onPhotos, initial }: Props) {
  const video = useRef<HTMLVideoElement>(null);
  const canvas = useRef<HTMLCanvasElement | null>(null);
  const picker = useRef<HTMLInputElement>(null);
  const [stream, setStream] = useState<MediaStream | null>(null);
  const [camera, setCamera] = useState<"starting" | "on" | "none">(initial?.camera ?? "starting");
  const [seen, setSeen] = useState<CameraView | null>(initial?.seen ?? null);
  const [aim, setAim] = useState(initial?.aim ?? false);
  const [parts, setParts] = useState<File[] | null>(initial?.parts ? [] : null);
  const [taking, setTaking] = useState(false);
  const level = useLevel();
  const busyRef = useRef(busy);
  busyRef.current = busy || taking;
  const partsRef = useRef(parts);
  partsRef.current = parts;
  const levelOff = useRef(level.ask);
  levelOff.current = level.ask;

  useEffect(() => {
    if (initial) return;
    let stopped = false;
    let got: MediaStream | null = null;
    const media = typeof navigator !== "undefined" ? navigator.mediaDevices : undefined;
    if (!media?.getUserMedia) {
      setCamera("none");
      return;
    }
    media.getUserMedia({ video: { facingMode: { ideal: "environment" }, width: { ideal: 4096 }, height: { ideal: 3072 } }, audio: false }).then(
      (found) => {
        if (stopped) {
          found.getTracks().forEach((t) => t.stop());
          return;
        }
        got = found;
        setStream(found);
        setCamera("on");
      },
      () => setCamera("none"),
    );
    return () => {
      stopped = true;
      got?.getTracks().forEach((t) => t.stop());
    };
  }, [initial]);

  useEffect(() => {
    const v = video.current;
    if (!v || !stream) return;
    v.srcObject = stream;
    v.play().catch(() => undefined);
  }, [stream]);

  /** The final photo in full resolution; null: the phone's own camera must take it. */
  const takeFinal = useCallback(async (): Promise<Blob | null> => {
    const v = video.current;
    const track = stream?.getVideoTracks()[0];
    if (!v || !track) return null;
    const Capture = imageCaptureClass();
    const way = finalWay(v.videoWidth, v.videoHeight, Capture !== null);
    if (way === "takePhoto" && Capture) {
      try {
        const blob = await new Capture(track).takePhoto();
        if (blob.size) return blob;
      } catch {
        // Some cameras refuse takePhoto: the stream, if it is large enough.
      }
    }
    if (Math.max(v.videoWidth, v.videoHeight) >= FULL_SIDE) return grab(v);
    return null;
  }, [stream]);

  const shoot = useCallback(async () => {
    if (busyRef.current) return;
    setTaking(true);
    try {
      const blob = await takeFinal();
      if (!blob) {
        // iOS, or a small stream: Sikta så här, then the phone's own camera.
        setAim(true);
        return;
      }
      const taken = partsRef.current;
      if (taken) setParts([...taken, asFile(blob, taken.length + 1)]);
      else onPhotos([asFile(blob, 1)]);
    } finally {
      setTaking(false);
    }
  }, [takeFinal, onPhotos]);

  // The photo help: every TICK_MS a frame of ANALYSIS_SIZE px, checked; all green for HOLD_MS
  // takes the photo by itself (not while photos are taken in parts).
  useEffect(() => {
    if (!stream) return;
    let timer = 0;
    let before: Float32Array | null = null;
    let focus: SharpTrack = { best: 0, at: 0 };
    let held: Hold = { since: null, fired: false };
    const tick = () => {
      const v = video.current;
      if (v && v.videoWidth && !document.hidden) {
        const size = analysisSize(v.videoWidth, v.videoHeight);
        const c = canvas.current ?? (canvas.current = document.createElement("canvas"));
        c.width = size.width;
        c.height = size.height;
        const context = c.getContext("2d", { willReadFrequently: true });
        if (context) {
          context.drawImage(v, 0, 0, size.width, size.height);
          const frame = context.getImageData(0, 0, size.width, size.height);
          const gray = grayOf(frame);
          const quad = findQuad(frame);
          const now = performance.now();
          const focused = trackSharpness(focus, sharpness(gray, size.width, size.height), now);
          focus = focused.track;
          const tilt = level.tilt.current;
          const said = verdict({
            quad,
            check: quad ? frameCheck(quad, size.width, size.height) : null,
            tilt,
            sharp: focused.sharp,
            clipped: clipped(frame, quad),
            shadow: quad ? shadowRatio(frame, quad) : 1,
            motion: motion(before, gray),
            levelOff: levelOff.current,
          });
          before = gray;
          const step = hold(held, said.green && !busyRef.current && partsRef.current === null, now);
          held = step.state;
          setSeen({ quad, verdict: said, width: size.width, height: size.height, progress: step.progress, tilt });
          if (step.fire) void shoot();
        }
      }
      timer = window.setTimeout(tick, TICK_MS);
    };
    tick();
    return () => window.clearTimeout(timer);
  }, [stream, shoot, level.tilt]);

  const chosen = (list: FileList | null) => {
    const files = Array.from(list ?? []).slice(0, MAX_PARTS);
    if (files.length) onPhotos(files);
  };

  const found = seen?.quad ? 4 : 0;
  const ringLength = 2 * Math.PI * 46;
  return (
    <div className="mob-kamera">
      {camera === "none" ? (
        <div className="mob-ingen-kamera" role="status">
          <h2>Kameran går inte att använda här</h2>
          <p>Ta bilden med telefonens kamera, eller välj en bild du redan har: rakt ovanifrån, med hela modulen och lite golv runt om.</p>
        </div>
      ) : (
        <div className="mob-sokare">
          <video ref={video} playsInline muted autoPlay aria-label="Kameran" />
          {seen ? <Overlay seen={seen} /> : null}
          <span className={`mob-chip mob-chip-topp${found ? " ok" : ""}`} role="status">
            {camera === "starting" ? "Startar kameran …" : found ? "✓ 4 av 4 hörn i bild" : "Söker modulens hörn"}
          </span>
          <Level tilt={seen?.tilt ?? null} />
          {aim ? (
            <div className="mob-sikta" role="dialog" aria-label="Sikta så här">
              <p>
                <b>Sikta så här</b> och ta bilden med telefonens egen kamera: den ger full upplösning. Håll telefonen som nu, rakt ovanför mitten.
              </p>
              <button type="button" className="tm-knapp primar" onClick={() => picker.current?.click()}>
                Ta bilden med kameran
              </button>
              <button type="button" className="tm-knapp" onClick={() => setAim(false)}>
                Tillbaka
              </button>
            </div>
          ) : null}
        </div>
      )}
      {level.ask ? (
        <button type="button" className="tm-knapp mob-bred" onClick={level.turnOn}>
          Slå på vattenpasset
        </button>
      ) : null}
      {level.denied ? <p className="cad-dampad">Vattenpasset är av. Håll telefonen plant ändå; vinkeln mäts också i fotot.</p> : null}
      {camera !== "none" && seen ? <LightRow lights={seen.verdict.lights} /> : null}
      <p className="mob-rad" role="status" aria-live="polite">
        {busy
          ? "Laddar upp fotot …"
          : camera === "none"
            ? "Lägg modulen på golvet och stå över mitten."
            : parts
              ? `Fota i delar: bild ${parts.length + 1} av högst ${MAX_PARTS}. Låt bilderna överlappa på mitten.`
              : (seen?.verdict.advice ?? "Stå på en pall så att hela modulen syns. Håll telefonen rakt ovanför och undvik hårda skuggor över spåren.")}
      </p>
      <div className="mob-utlosare">
        <label className="mob-galleri">
          <span className="cad-dold">Välj en bild</span>
          <span aria-hidden="true">▣</span>
          <input
            type="file"
            name="mobil-galleri"
            accept="image/jpeg,image/png"
            multiple
            disabled={busy}
            onChange={(event) => chosen(event.currentTarget.files)}
          />
        </label>
        {camera === "none" ? (
          <button type="button" className="mob-avtryckare" aria-label="Ta bilden med telefonens kamera" disabled={busy} onClick={() => picker.current?.click()}>
            <span />
          </button>
        ) : (
          <button type="button" className="mob-avtryckare" aria-label="Ta bilden" disabled={busy || taking || camera !== "on"} onClick={() => void shoot()}>
            <svg viewBox="0 0 100 100" aria-hidden="true">
              <circle cx={50} cy={50} r={46} className="mob-ring" />
              <circle
                cx={50}
                cy={50}
                r={46}
                className="mob-ring-fylld"
                strokeDasharray={`${(seen?.progress ?? 0) * ringLength} ${ringLength}`}
                transform="rotate(-90 50 50)"
              />
            </svg>
            <span />
          </button>
        )}
        {parts ? (
          <button type="button" className="tm-knapp liten" disabled={busy || parts.length < 2} onClick={() => onPhotos(parts)}>
            Klar, {parts.length} bilder
          </button>
        ) : (
          <button type="button" className="tm-knapp liten" disabled={busy} onClick={() => setParts([])}>
            Fota i delar
          </button>
        )}
      </div>
      <input
        ref={picker}
        className="cad-dold"
        type="file"
        name="mobil-kamera"
        accept="image/*"
        capture="environment"
        multiple={parts !== null}
        onChange={(event) => {
          setAim(false);
          const files = Array.from(event.currentTarget.files ?? []);
          if (parts) setParts([...parts, ...files].slice(0, MAX_PARTS));
          else chosen(event.currentTarget.files);
        }}
      />
      <p className="mob-fot">Lång modul? Fota i delar: 2–{MAX_PARTS} bilder som överlappar på mitten, de sys ihop till en.</p>
    </div>
  );
}
