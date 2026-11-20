// Studio › Rita › Ladda upp ritning (#89 del c4, STUDIO-01, STUDIO-03, CAD6, TKL27): choose a
// drawing (a signal plan, a panel drawing or a track plan, as a PDF, an SVG or a picture), see the
// price, start, answer the questions with the legend first, and get the proposal: Rita's draft,
// everything yellow until the owner confirms it, with the panel the engine lays out. TrainMeet CAD
// reads the drawing; TKL's server asks it with the person's login with TrainMeet ID.
import { useCallback, useEffect, useRef, useState } from "react";
import { api, type DrawingQuestion, type Rita as RitaView, type Upload } from "./api";
import { chosen, inOrder, open, pageText, priceText, summaryText, working } from "./laddaupp";

const POLL_MS = 1200;
export const ACCEPT = ".pdf,.svg,image/jpeg,image/png,image/webp,application/pdf,image/svg+xml";

export type UploadProps = {
  upload: Upload | null;
  page: number;
  ai: boolean;
  consent: boolean;
  busy: boolean;
  message: string;
  onFile: (file: File) => void;
  onPage: (page: number) => void;
  onAi: (ai: boolean) => void;
  onConsent: (consent: boolean) => void;
  onRead: () => void;
  onAnswer: (key: string, answer: string) => void;
  onProposal: () => void;
  onClose: () => void;
};

/** The panel as it looks: what to do next, from the file to the proposal. */
export function UploadView(props: UploadProps) {
  const { upload, page, ai, consent, busy, message } = props;
  const job = upload?.job ?? null;
  const read = job?.state === "done" ? (job.read ?? null) : null;
  const raster = job?.pages.find((p) => p.number === page)?.kind === "raster";
  const needsYes = !!job && raster && ai && !job.ai.given;
  const waiting = open(read);
  return (
    <section className="ruta ladda-upp" aria-label="Ladda upp ritning">
      <div className="rad">
        <h2>Ladda upp ritning</h2>
        <span className="tm-fyll" />
        <button type="button" className="lank" onClick={props.onClose}>
          Tillbaka till Rita
        </button>
      </div>
      <p className="liten">
        Ladda upp stationens signalplan, panelritning eller spårplan som PDF, SVG eller bild. TrainMeet CAD läser spåren, växlarna, signalerna och spårledningsgränserna, och Studio föreslår stationen. Allt är gult tills du bekräftar det.
      </p>
      <label className="ladda-fil">
        Välj ritning
        <input type="file" accept={ACCEPT} aria-label="Välj ritning" disabled={busy || working(job)} onChange={(e) => e.target.files?.[0] && props.onFile(e.target.files[0])} />
      </label>
      {message ? (
        <p className="fel" role="alert">
          {message}
        </p>
      ) : null}
      {job ? (
        <div className="ladda-jobb">
          <p>
            <strong>{job.name}</strong> · {pageText(job).join(" · ")}
          </p>
          {job.pages.length > 1 ? (
            <label className="rad">
              Sida
              <select aria-label="Sida" value={page} onChange={(e) => props.onPage(Number(e.target.value))}>
                {job.pages.map((p) => (
                  <option key={p.number} value={p.number}>
                    {p.number}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          {raster ? (
            <label className="rad">
              <input type="checkbox" checked={ai} disabled={!job.ai.available} onChange={(e) => props.onAi(e.target.checked)} />
              Låt AI:n skriva av texten {job.ai.available ? "" : `(${job.ai.message ?? "går inte nu"})`}
            </label>
          ) : null}
          {needsYes ? (
            <label className="rad gul-rad">
              <input type="checkbox" checked={consent} onChange={(e) => props.onConsent(e.target.checked)} />
              {job.ai.text}
            </label>
          ) : null}
          <p className="pris" data-pris={job.price.tokens}>
            Pris: {priceText(job, page, raster ? ai : false)}
          </p>
          {working(job) ? (
            <p className="liten" aria-live="polite">
              {job.step} · {job.progress} %
            </p>
          ) : (
            <button type="button" className="primar" disabled={busy || (needsYes && !consent)} onClick={props.onRead}>
              {read ? "Läs igen" : "Läs ritningen"}
            </button>
          )}
          {job.state === "failed" ? <p className="fel">{job.message ?? "Ritningen kunde inte läsas."}</p> : null}
        </div>
      ) : null}
      {read ? (
        <div className="ladda-avlasning">
          <p className="ok">Läst: {summaryText(read)}.</p>
          {read.notes?.map((note) => (
            <p key={note} className="liten">
              {note}
            </p>
          ))}
          {read.questions?.length ? (
            <>
              <h3>Frågor om ritningen · teckenförklaringen först</h3>
              <ol className="ladda-fragor">
                {inOrder(read.questions).map((q) => (
                  <QuestionView key={q.key} question={q} busy={busy} onAnswer={props.onAnswer} />
                ))}
              </ol>
            </>
          ) : null}
          {upload?.underlay ? (
            <figure className="ladda-underlag">
              <img src={upload.underlay} alt="Ritningen uträtad, som CAD läste den" />
              <figcaption className="liten">Ritningen uträtad, som TrainMeet CAD läste den.</figcaption>
            </figure>
          ) : null}
          <div className="rad">
            <button type="button" className="primar" disabled={busy || waiting.length > 0} onClick={props.onProposal}>
              Gör förslaget i Rita
            </button>
            {waiting.length ? <span className="liten">Svara på {waiting.length === 1 ? "frågan" : `de ${waiting.length} frågorna`} först.</span> : null}
          </div>
        </div>
      ) : null}
    </section>
  );
}

function QuestionView({ question, busy, onAnswer }: { question: DrawingQuestion; busy: boolean; onAnswer: (key: string, answer: string) => void }) {
  const now = chosen(question);
  return (
    <li className={question.answer ? "besvarad" : question.code ? "" : "obesvarad"} data-fraga={question.key}>
      <strong>{question.title}</strong> <span className="liten">{question.text}</span>
      <div className="rad">
        {question.choices.map((choice) => (
          <button key={choice.id} type="button" aria-pressed={now === choice.id} disabled={busy} onClick={() => onAnswer(question.key, choice.id)}>
            {choice.text}
            {question.code === choice.id && !question.answer ? <span className="liten"> · kodens val</span> : null}
          </button>
        ))}
      </div>
    </li>
  );
}

/** The panel with TKL behind it: the upload, the read polled until it is done, the answers,
 * and the proposal handed to Rita. */
export function LaddaUpp({ onProposal, onClose }: { onProposal: (view: RitaView, underlay: string | null) => void; onClose: () => void }) {
  const [upload, setUpload] = useState<Upload | null>(null);
  const [page, setPage] = useState(1);
  const [ai, setAi] = useState(true);
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const act = useCallback(async (work: () => Promise<void>) => {
    setBusy(true);
    setMessage("");
    try {
      await work();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Det gick inte.");
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    void act(async () => setUpload(await api.upload()));
  }, [act]);

  const job = upload?.job ?? null;
  useEffect(() => {
    if (!job || !working(job)) return;
    timer.current = setTimeout(() => {
      api.uploadJob(job.id).then(setUpload, (error: unknown) => setMessage(error instanceof Error ? error.message : "TKL svarar inte."));
    }, POLL_MS);
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, [job]);

  return (
    <UploadView
      upload={upload}
      page={page}
      ai={ai}
      consent={consent}
      busy={busy}
      message={message}
      onFile={(file) =>
        void act(async () => {
          const made = await api.uploadDrawing(file);
          setUpload(made);
          setPage(made.job?.page ?? 1);
        })
      }
      onPage={setPage}
      onAi={setAi}
      onConsent={setConsent}
      onRead={() => job && void act(async () => setUpload(await api.readDrawing(job.id, page, ai, consent)))}
      onAnswer={(key, answer) => job && void act(async () => setUpload(await api.answerDrawing(job.id, key, answer)))}
      onProposal={() => job && void act(async () => onProposal(await api.proposal(job.id), upload?.underlay ?? null))}
      onClose={onClose}
    />
  );
}
