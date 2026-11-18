// Importera från Tellurian (#56, CAT-186): 1–50 files from Tellurian's card app, each a draft that
// is reviewed and approved with Godkänn alla on the batch's page, as the photos' drafts are. A file
// that cannot be read is told here, in Swedish, and the others go on. The logic is in tellurian.ts.
import { linkClick } from "@trainmeet/design";
import { useId, useState } from "react";
import { ApiError, type TellurianImport } from "./api";
import { Crumbs, ErrorLine, isOwner, mayEdit, problemText, type Ctx, type T } from "./common";
import { batchPath, PATHS } from "./routes";
import { chooseFiles, importCounts, importFiles, reviewBatch, type FileProblem } from "./tellurian";

const PROBLEMS: Record<FileProblem, "importTooMany" | "importTooLarge" | "importTooLargeTogether"> = {
  too_many: "importTooMany",
  too_large: "importTooLarge",
  too_large_together: "importTooLargeTogether",
};

/** Why the import was refused as a whole, in the import's words. */
export function importProblem(t: T, error: unknown): string {
  if (error instanceof ApiError && error.code === "too_many_pictures") return t("importTooManyDrafts");
  if (error instanceof ApiError && error.code === "bad_form") return t("importTooMany");
  return problemText(t, error);
}

/** How each file went: a new draft, one it already was, or why it was not read. */
export function ImportResult({ ctx, result }: { ctx: Ctx; result: TellurianImport }) {
  const { t, language, navigate } = ctx;
  const id = useId();
  const counts = importCounts(result);
  const target = reviewBatch(result);
  return (
    <section className="tm-kort cat-avsnitt cat-importen" aria-labelledby={id} role="status">
      <h2 id={id}>{t("importResult")}</h2>
      <p>{t("importCounts", counts)}</p>
      <ul className="cat-importlista">
        {result.files.map((file, index) => (
          <li key={`${index}-${file.name}`} className={file.ok ? undefined : "cat-importfel"}>
            <b>{file.name}</b> <span className={`cat-pill${file.ok ? "" : " cat-pill-fel"}`}>{t(file.ok ? (file.already ? "importAlready" : "importMade") : "importFailed")}</span>
            {/* The server's own words are Swedish; in English the general text says what to do. */}
            {file.error ? <p className="cat-fel">{language === "sv" ? file.error : t("importFileUnreadable")}</p> : null}
            {file.notes?.length ? (
              <ul className="cat-hjalp">
                {file.notes.map((note) => (
                  <li key={note}>{language === "sv" ? note : t("importNoteLeftOut")}</li>
                ))}
              </ul>
            ) : null}
          </li>
        ))}
      </ul>
      {target ? (
        <a className="tm-knapp primar" href={batchPath(target)} onClick={linkClick(navigate, batchPath(target))}>
          {isOwner(ctx) ? t("importReview") : t("importToBatch")}
        </a>
      ) : null}
    </section>
  );
}

export type ImportViewProps = {
  ctx: Ctx;
  chosen: File[];
  problem?: FileProblem | null;
  sending?: boolean;
  result?: TellurianImport | null;
  error?: string | null;
  onChoose?: (files: File[]) => void;
  onUnchoose?: (index: number) => void;
  onSend?: () => void;
};

/** The page as it looks, from its state. Rendered in the tests without fetching. */
export function ImportView(props: ImportViewProps) {
  const { ctx, chosen } = props;
  const { t } = ctx;
  const id = useId();
  return (
    <>
      <Crumbs ctx={ctx} items={[{ href: PATHS.vehicles, label: t("vehicles") }, { label: t("importTitle") }]} />
      <p className="tm-overrubrik">{t("importTitle")}</p>
      <h1>{t("importHeading")}</h1>
      <p className="cat-ingress">{isOwner(ctx) ? t("importIntro") : t("importIntroLeave")}</p>
      <ErrorLine text={props.error ?? null} />
      <section className="tm-kort cat-avsnitt cat-import" aria-labelledby={`${id}-filer`}>
        <h2 id={`${id}-filer`}>{t("importFiles")}</h2>
        <label className={`tm-knapp cat-bildknapp cat-slapp${props.sending ? " cat-av" : ""}`}>
          <input
            className="cat-dold"
            type="file"
            accept=".json,application/json"
            multiple
            disabled={props.sending}
            aria-describedby={`${id}-hjalp`}
            onChange={(event) => {
              const files = [...(event.target.files ?? [])];
              event.target.value = "";
              if (files.length) props.onChoose?.(files);
            }}
          />
          {chosen.length ? t("importChooseMore") : t("importChoose")}
        </label>
        <p id={`${id}-hjalp`} className="cat-hjalp">
          {t("importChooseHelp")}
        </p>
        <ErrorLine text={props.problem ? t(PROBLEMS[props.problem]) : null} />
        {chosen.length ? (
          <div className="cat-valda">
            <p className="cat-etikett">{t("importChosen")}</p>
            <ul className="cat-fillista">
              {chosen.map((file, index) => (
                <li key={`${index}-${file.name}`}>
                  <span>{file.name}</span>
                  <button
                    type="button"
                    className="tm-knapp cat-godkann"
                    disabled={props.sending}
                    aria-label={t("importRemove", { name: file.name })}
                    onClick={() => props.onUnchoose?.(index)}
                  >
                    {t("removeYes")}
                  </button>
                </li>
              ))}
            </ul>
            <button type="button" className="tm-knapp primar" disabled={props.sending} onClick={props.onSend}>
              {props.sending ? t("importSending") : chosen.length === 1 ? t("importSendOne") : t("importSend", { n: chosen.length })}
            </button>
          </div>
        ) : null}
      </section>
      {props.result ? <ImportResult ctx={ctx} result={props.result} /> : null}
    </>
  );
}

export function ImportPage({ ctx }: { ctx: Ctx }) {
  const { t } = ctx;
  // The import's id is made here: sent again, the same files give the same drafts (CAT-149).
  const [id, setId] = useState(() => crypto.randomUUID());
  const [chosen, setChosen] = useState<File[]>([]);
  const [problem, setProblem] = useState<FileProblem | null>(null);
  const [sending, setSending] = useState(false);
  const [result, setResult] = useState<TellurianImport | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (!mayEdit(ctx))
    return (
      <>
        <Crumbs ctx={ctx} items={[{ href: PATHS.vehicles, label: t("vehicles") }, { label: t("importTitle") }]} />
        <h1>{t("importTitle")}</h1>
        <section className="tm-kort cat-tomt">
          <p className="cat-tomt-rubrik">{t("batchViewOnly")}</p>
        </section>
      </>
    );

  return (
    <ImportView
      ctx={ctx}
      chosen={chosen}
      problem={problem}
      sending={sending}
      result={result}
      error={error}
      onChoose={(files) => {
        const picked = chooseFiles(chosen, files);
        setChosen(picked.files);
        setProblem(picked.problem);
        setError(null);
      }}
      onUnchoose={(index) => {
        setChosen((now) => now.filter((_, at) => at !== index));
        setProblem(null);
      }}
      onSend={async () => {
        if (!chosen.length || sending) return;
        setSending(true);
        setError(null);
        const done = await importFiles(id, chosen);
        setSending(false);
        if (done.error) {
          setError(importProblem(t, done.error));
          return;
        }
        setResult(done.result);
        setChosen([]);
        setProblem(null);
        // The next import is a batch of its own.
        setId(crypto.randomUUID());
      }}
    />
  );
}
