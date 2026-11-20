// Fota med mobilen on the computer (#90, CAD1, CADMOB-12): the QR code that opens CAD in the phone
// without a new login, and the phone's progress as the computer follows it. From Ny modul it makes
// a new module; from a module's page a photo for that module. The code is used once and holds ten
// minutes; it ends when the page is left before a phone has used it, and Avsluta ends the phone's
// session too.
import { linkClick, type Navigate } from "@trainmeet/design";
import { useEffect, useRef, useState } from "react";
import { api, type MobileHandoff, type MobileStep, type Module, type PhotoJob } from "./api";
import { modulePath, photoPath } from "./routes";

const POLL_MS = 2000;

export const STEP_TEXT: Record<MobileStep, string> = {
  start: "0 Välj väg",
  matt: "1 Mått",
  gavlar: "2 Gavlar",
  fota: "3 Fota",
  kontroll: "4 Kontroll",
  fraga: "4b AI:n frågar",
  klar: "5 Klart",
};

function minutesLeft(until: string, now: number): number {
  return Math.max(0, Math.ceil((new Date(until).getTime() - now) / 60_000));
}

export type FollowProps = {
  handoff: MobileHandoff;
  module?: Module | null;
  job?: PhotoJob | null;
  now?: number;
  navigate?: Navigate;
  onNew?: () => void;
  onEnd?: () => void;
};

/** What the computer shows: the QR code while it waits, then where the phone is and what it made. */
export function MobileFollow({ handoff, module, job, now = Date.now(), navigate, onNew, onEnd }: FollowProps) {
  const { state } = handoff;
  if (state === "waiting") {
    return (
      <div className="cad-mobilkod" role="group" aria-label="QR-koden">
        {handoff.qr ? <img className="cad-qr" src={handoff.qr} alt="QR-kod till CAD i mobilen" width={220} height={220} /> : null}
        <div>
          <p>
            <b>Skanna koden med mobilens kamera.</b> CAD öppnas i mobilens webbläsare, inloggad som du, utan ny inloggning.
          </p>
          <p className="cad-dampad">Koden gäller en gång och i {minutesLeft(handoff.expires_at, now)} minuter till. Visa den inte för någon annan.</p>
          {handoff.url ? (
            <details className="cad-mobillank">
              <summary>Går det inte att skanna?</summary>
              <p className="cad-dampad">Öppna adressen i mobilen, till exempel genom att skicka den till dig själv:</p>
              <a className="tm-mono" href={handoff.url} data-mobil-lank="">
                {handoff.url}
              </a>
            </details>
          ) : null}
          <p role="status" aria-live="polite">
            Väntar på mobilen …
          </p>
        </div>
      </div>
    );
  }
  if (state === "expired") {
    return (
      <div className="cad-mobilkod" role="status">
        <p>QR-koden har gått ut utan att någon mobil använt den.</p>
        <button type="button" className="tm-knapp primar" onClick={onNew}>
          Visa en ny QR-kod
        </button>
      </div>
    );
  }
  const step = handoff.step ?? "start";
  const done = step === "klar" && module;
  const reading = job && (job.state === "queued" || job.state === "running");
  return (
    <div className="cad-mobilkod cad-mobilfoljer" role="status" aria-live="polite">
      <p>
        <span className={state === "opened" ? "cad-tagg gron" : "cad-tagg"}>{state === "opened" ? "Öppnad i mobilen" : "Mobilen är klar"}</span>{" "}
        <b>Steg {STEP_TEXT[step]}</b>
      </p>
      {module ? (
        <p>
          {module.name} · {module.number}
          {module.status === "approved" ? " · godkänd" : ""}
        </p>
      ) : null}
      {reading ? (
        <p>
          Fotot läses av: {job.step} · {job.progress} %
        </p>
      ) : null}
      {job?.state === "done" && !done ? <p>Fotot är läst. Mobilen visar kontrollen.</p> : null}
      {done ? (
        <p className="cad-knapprad">
          {job && job.module === module.id ? (
            <a className="tm-knapp primar" href={photoPath(module.id, job.id)} onClick={linkClick(navigate, photoPath(module.id, job.id))}>
              Foto och kontroll
            </a>
          ) : null}
          <a className="tm-knapp" href={modulePath(module.id)} onClick={linkClick(navigate, modulePath(module.id))}>
            Öppna modulen
          </a>
        </p>
      ) : module ? (
        <p>
          <a href={modulePath(module.id)} onClick={linkClick(navigate, modulePath(module.id))}>
            Följ modulen här
          </a>
        </p>
      ) : null}
      {state === "opened" ? (
        <button type="button" className="tm-knapp liten" onClick={onEnd}>
          Avsluta i mobilen
        </button>
      ) : (
        <button type="button" className="tm-knapp liten" onClick={onNew}>
          Visa en ny QR-kod
        </button>
      )}
    </div>
  );
}

/** Fota med mobilen: the button, then the QR code and the phone followed. */
export function MobileHandoffPanel({ module = null, navigate, start }: { module?: Module | null; navigate?: Navigate; start?: MobileHandoff }) {
  const [handoff, setHandoff] = useState<MobileHandoff | null>(start ?? null);
  const [followed, setFollowed] = useState<Module | null>(null);
  const [job, setJob] = useState<PhotoJob | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const waiting = useRef<string | null>(null);
  waiting.current = handoff?.state === "waiting" ? handoff.id : null;

  // A code nobody used dies when the page is left.
  useEffect(
    () => () => {
      if (waiting.current) api.mobileCancel(waiting.current).catch(() => undefined);
    },
    [],
  );

  const id = handoff?.id;
  const live = handoff?.state === "waiting" || handoff?.state === "opened";
  useEffect(() => {
    if (!id || !live) return;
    let stop = false;
    // The module and the job are asked again only when the phone moves on, or while the photo is read.
    let seen = "";
    let reading = false;
    const timer = window.setInterval(() => {
      setNow(Date.now());
      api.mobileStatus(id).then(
        (found) => {
          if (stop) return;
          // The address and the QR code come only once; keep them while the code waits.
          setHandoff((before) => ({ ...found, url: before?.url ?? null, qr: before?.qr ?? null }));
          const now = `${found.step}/${found.module}/${found.job}`;
          const moved = now !== seen;
          seen = now;
          if (found.module && (moved || reading))
            api.module(found.module).then(
              (m) => !stop && setFollowed(m),
              () => undefined,
            );
          if (found.job && (moved || reading))
            api.photoJob(found.job).then(
              (j) => {
                if (stop) return;
                reading = j.state === "queued" || j.state === "running";
                setJob(j);
              },
              () => undefined,
            );
        },
        () => undefined,
      );
    }, POLL_MS);
    return () => {
      stop = true;
      window.clearInterval(timer);
    };
  }, [id, live]);

  const make = () => {
    setBusy(true);
    setError(null);
    setJob(null);
    setFollowed(null);
    api.mobileHandoff(module?.id ?? null).then(
      (made) => {
        setBusy(false);
        setHandoff(made);
        setNow(Date.now());
      },
      (failure: unknown) => {
        setBusy(false);
        setError(failure instanceof Error ? failure.message : "Något gick fel. Försök igen.");
      },
    );
  };
  const end = () => {
    if (!handoff) return;
    api.mobileCancel(handoff.id).then(
      (ended) => setHandoff({ ...ended, url: null, qr: null }),
      () => undefined,
    );
  };

  return (
    <div className="cad-mobilpanel">
      {handoff ? (
        <MobileFollow handoff={handoff} module={followed} job={job} now={now} navigate={navigate} onNew={make} onEnd={end} />
      ) : (
        <button type="button" className="tm-knapp primar" disabled={busy} onClick={make}>
          {busy ? "Gör QR-koden …" : module ? "Fota med mobilen" : "Visa QR-koden"}
        </button>
      )}
      {error ? (
        <p className="cad-fel" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}
