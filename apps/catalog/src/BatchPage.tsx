// Lägg till flera (#52 del d, CAT-147–CAT-153): up to 30 photos in a batch, one per vehicle. The
// owner's are read by the AI in a queue, one at a time, while the page follows it; someone who
// edits the fleet leaves photos for the owner without AI (CAT-153). Each photo is a draft, not a
// vehicle (CAT-148), edited in the same form as Lägg till med foto, with the AI's suggestions
// marked (CAT-136), and Godkänn alla makes vehicles of all of them or of none (CAT-150). The
// logic is in batches.ts.
import { linkClick } from "@trainmeet/design";
import { useCallback, useEffect, useId, useState } from "react";
import { api, ApiError, BATCH_PHOTOS, PICTURE_KINDS, SUGGESTED_FIELDS, type Batch, type BatchCard, type BatchSummary, type Place, type ReadingConsent, type SuggestedField } from "./api";
import {
  approveAll,
  canApprove,
  cardChange,
  cardFlow,
  choosePhotos,
  inQueue,
  openCards,
  POLL_MS,
  sendPhotos,
  sendProblem,
  tally,
  tokensRanOut,
  type Tally,
} from "./batches";
import { Crumbs, Dialog, ErrorLine, isOwner, kindText, mayEdit, problemText, timeText, type Ctx, type T } from "./common";
import type { TextKey } from "./i18n";
import { BuyTokens, ConsentView, Price, QuestionView, usePreviews } from "./PhotoFlow";
import { accept, answer, edit, needsConsent, openQuestion, stillUnreadable, type Flow } from "./reading";
import { batchPath, PATHS } from "./routes";
import { FormView } from "./VehicleForm";

const LABELS: Record<SuggestedField, TextKey> = {
  kind: "fKind",
  litt: "fLitt",
  number: "fNumber",
  operator: "fOperator",
  maker: "fMaker",
  article_number: "fArticle",
};

const tallyText = (t: T, counts: Tally) => t("batchTally", { ready: counts.ready, check: counts.check, left: counts.left });
const cardsText = (t: T, n: number) => (n === 1 ? t("batchPhotosOne") : t("batchPhotos", { n }));

/** A card's own name: what it says it is, or where it is in the queue. */
function headline(t: T, card: BatchCard): string {
  if (card.status === "waiting") return t("cardWaiting");
  if (card.status === "reading") return t("cardReading");
  return `${card.values.litt ?? ""} ${card.values.number ?? ""}`.trim() || t("cardEmpty");
}

const filledIn = (card: BatchCard) => Boolean(card.values.kind || card.values.litt?.trim() || card.values.number?.trim());

export type CardRowProps = {
  ctx: Ctx;
  card: BatchCard;
  /** Its number in the batch, from 1. */
  n: number;
  /** The batch is read with AI, so a card can be read again (CAT-152). */
  ai: boolean;
  /** Godkänn alla stopped at it (Problem.cards, CAT-150). */
  stopped: boolean;
  busy: boolean;
  onEdit?: () => void;
  onRemove?: () => void;
  onRetry?: () => void;
};

/** One photo of the batch: the thumbnail, the status, and the suggestions still standing as the
 * AI made them, marked as in Lägg till med foto (CAT-136). */
export function CardRow({ ctx, card, n, ai, stopped, busy, onEdit, onRemove, onRetry }: CardRowProps) {
  const { t, language } = ctx;
  const flow = cardFlow(card);
  const marked = SUGGESTED_FIELDS.filter((field) => flow.marks[field]);
  const queued = inQueue(card);
  const approved = card.status === "approved";
  const byHand = card.status === "failed" || card.status === "manual";
  const note = byHand && !filledIn(card) ? (language === "sv" && card.message ? card.message : t(card.status === "failed" ? "cardFailed" : "cardManual")) : null;
  const unsure = openQuestion(flow) ? t("cardQuestion") : stillUnreadable(flow).length ? t("batchUnreadable") : null;
  const sub = [kindText(t, card.values.kind), card.values.operator].filter(Boolean).join(" · ");
  return (
    <li id={`kort-${card.id}`} className={`cat-omgangskort${stopped ? " cat-stoppad" : ""}`} tabIndex={-1}>
      {card.picture ? (
        <img className="cat-listbild" src={card.picture.thumb_url} alt={t("cardAlt", { n })} width={72} height={48} decoding="async" />
      ) : (
        <span className="cat-listbild cat-fotoplats" aria-hidden="true" />
      )}
      <div className="cat-kortinfo">
        <b className={queued ? "cat-under" : undefined}>{headline(t, card)}</b>
        {sub ? <span className="cat-under">{sub}</span> : null}
        {([false, true] as const).map((low) => {
          // The sure suggestions together, then the unsure ones, each with the pill of the form.
          const fields = marked.filter((field) => (flow.marks[field]?.confidence === "low") === low);
          if (!fields.length) return null;
          const shown = fields.map((field) => `${t(LABELS[field])} ${field === "kind" ? kindText(t, card.values.kind) : (flow.marks[field]?.value ?? "")}`);
          return (
            <p key={String(low)} className="cat-aitext">
              <span className="cat-pill cat-pill-ai">{t(low ? "aiUnsure" : "aiSuggestion")}</span>
              <span className="cat-under">{shown.join(" · ")}</span>
            </p>
          );
        })}
        {note ? <p className="cat-hjalp">{note}</p> : null}
        {unsure ? <p className="cat-varning">{unsure}</p> : null}
        {stopped ? <p className="cat-fel">{t("batchStoppedCard")}</p> : null}
      </div>
      <span className={`cat-pill cat-pill-kort-${card.status}`}>{t(`cardStatus_${card.status}` as TextKey)}</span>
      {approved ? null : (
        <div className="cat-kortknappar">
          {queued ? null : (
            <button type="button" className="tm-knapp cat-godkann" disabled={busy} aria-label={t("cardEdit", { n })} onClick={onEdit}>
              {t("edit")}
            </button>
          )}
          {ai && byHand && onRetry ? (
            <button type="button" className="tm-knapp cat-godkann" disabled={busy} aria-label={t("cardRetryLabel", { n })} onClick={onRetry}>
              {t("cardRetry")}
            </button>
          ) : null}
          <button type="button" className="tm-knapp cat-godkann" disabled={busy} aria-label={t("cardRemove", { n })} onClick={onRemove}>
            {t("removeYes")}
          </button>
        </div>
      )}
    </li>
  );
}

export type BatchViewProps = {
  ctx: Ctx;
  /** Null for a new batch, before anything is sent. */
  batch: Batch | null;
  /** The photos are read with AI; else they are left to fill in by hand (CAT-153). */
  ai: boolean;
  /** The owner, where the AI cannot be used now: the photos are added without it. */
  noAi?: boolean;
  consent: ReadingConsent | null;
  /** The photos chosen and not yet sent, and their addresses in the browser. */
  chosen: File[];
  previews?: string[];
  /** Waiting for what is needed before the photos can go, such as the price. */
  notReady?: boolean;
  choiceProblem?: string | null;
  sending?: { done: number; of: number } | null;
  sendError?: string | null;
  /** How many photos were drafts already (CAT-149). */
  already?: number;
  stopped?: string[];
  approveError?: string | null;
  approving?: boolean;
  busyCard?: string | null;
  error?: string | null;
  onChoose?: (files: File[]) => void;
  onUnchoose?: (index: number) => void;
  onStart?: () => void;
  onEdit?: (card: BatchCard) => void;
  onRemove?: (card: BatchCard) => void;
  onRetry?: (card: BatchCard) => void;
  onApprove?: () => void;
};

/** The batch as it looks, from its state: the photos to send, the queue with each draft, the cost
 * and Godkänn alla. Rendered in the tests without fetching. */
export function BatchView(props: BatchViewProps) {
  const { ctx, batch, ai, consent, chosen } = props;
  const { t, language } = ctx;
  const id = useId();
  const owner = isOwner(ctx);
  const cards = batch?.cards ?? [];
  const open = batch ? openCards(batch) : [];
  const counts = tally(cards);
  const room = BATCH_PHOTOS - cards.length - chosen.length;
  const sending = props.sending ?? null;
  const stopped = new Set(props.stopped ?? []);
  const queued = cards.some(inQueue);
  const already = props.already ?? 0;
  const intro = ai ? t("batchIntro") : !owner ? t("batchLeaveIntro") : props.noAi ? t("batchNoAi") : t("batchIntroManual");
  const start = ai ? (chosen.length === 1 ? t("batchStartOne") : t("batchStart", { n: chosen.length })) : chosen.length === 1 ? t("batchLeaveOne") : t("batchLeave", { n: chosen.length });
  return (
    <>
      <Crumbs ctx={ctx} items={[{ href: PATHS.vehicles, label: t("vehicles") }, { label: t("batchTitle") }]} />
      <p className="tm-overrubrik">{owner ? t("batchTitle") : t("leaveToOwner")}</p>
      <h1>{owner ? t("batchHeading") : t("batchLeaveHeading")}</h1>
      <p className="cat-ingress">{intro}</p>
      <ErrorLine text={props.error ?? null} />
      <div className="cat-kortet">
        <section className="tm-kort cat-omgang" aria-labelledby={`${id}-foton`}>
          <div className="cat-kortrubrik">
            <h2 id={`${id}-foton`}>{cards.length ? cardsText(t, cards.length) : t("photosTitle")}</h2>
            {cards.length ? <span className="cat-under">{tallyText(t, counts)}</span> : null}
          </div>
          <label className={`tm-knapp cat-bildknapp cat-slapp${room <= 0 || sending ? " cat-av" : ""}`}>
            <input
              className="cat-dold"
              type="file"
              accept={PICTURE_KINDS.join(",")}
              multiple
              disabled={room <= 0 || sending !== null}
              aria-describedby={`${id}-hjalp`}
              onChange={(event) => {
                const files = [...(event.target.files ?? [])];
                event.target.value = "";
                if (files.length) props.onChoose?.(files);
              }}
            />
            {cards.length ? t("batchChooseMore") : t("batchChoose")}
          </label>
          <p id={`${id}-hjalp`} className="cat-hjalp">
            {room <= 0 ? t("batchFull") : t("batchChooseHelp")}
          </p>
          <ErrorLine text={props.choiceProblem ?? null} />
          {chosen.length ? (
            <div className="cat-valda">
              <p className="cat-etikett">{t("batchChosen")}</p>
              <ul className="cat-fotoremsa">
                {chosen.map((photo, index) => (
                  <li key={`${index}-${photo.name}`}>
                    {props.previews?.[index] ? <img src={props.previews[index]} alt={photo.name} /> : <span className="cat-fotoplats" />}
                    <button
                      type="button"
                      className="tm-knapp cat-godkann"
                      disabled={sending !== null}
                      aria-label={t("batchChosenRemove", { name: photo.name })}
                      onClick={() => props.onUnchoose?.(index)}
                    >
                      {t("removeYes")}
                    </button>
                  </li>
                ))}
              </ul>
              <button type="button" className="tm-knapp primar" disabled={sending !== null || props.notReady} onClick={props.onStart}>
                {start}
              </button>
            </div>
          ) : null}
          {sending ? (
            <div className="cat-arbete" role="status">
              <progress max={sending.of} value={sending.done} aria-hidden="true" />
              <span>{t("batchSending", { done: Math.min(sending.done + 1, sending.of), of: sending.of })}</span>
            </div>
          ) : null}
          <ErrorLine text={props.sendError ?? null} />
          {already ? (
            <p className="cat-hjalp" role="status">
              {already === 1 ? t("batchAlreadyOne") : t("batchAlready", { n: already })}
            </p>
          ) : null}
          {open.length ? <progress className="cat-kostapel" max={counts.total} value={counts.total - counts.left} aria-hidden="true" /> : null}
          {batch?.waiting_until ? (
            <p className="cat-varning" role="status">
              {language === "sv" && batch.message ? batch.message : t("batchWaits")} {t("batchGoesOn", { time: timeText(language, batch.waiting_until) })}
            </p>
          ) : null}
          {tokensRanOut(batch) ? (
            <div className="cat-besvar" role="status">
              <p className="cat-varning">{t("batchTokensOut")}</p>
              {owner ? <BuyTokens ctx={ctx} /> : null}
            </div>
          ) : null}
          {cards.length ? (
            <ol className="cat-omgangslista" aria-label={t("batchList")}>
              {cards.map((card, index) => (
                <CardRow
                  key={card.id}
                  ctx={ctx}
                  card={card}
                  n={index + 1}
                  ai={Boolean(batch?.ai) && owner}
                  stopped={stopped.has(card.id)}
                  busy={props.busyCard === card.id || props.approving === true}
                  onEdit={() => props.onEdit?.(card)}
                  onRemove={() => props.onRemove?.(card)}
                  onRetry={props.onRetry ? () => props.onRetry?.(card) : undefined}
                />
              ))}
            </ol>
          ) : null}
        </section>

        <div className="cat-sidokolumn">
          <section className="tm-kort cat-avsnitt cat-lasav" aria-labelledby={`${id}-kostnad`}>
            <h2 id={`${id}-kostnad`}>{t("batchCost")}</h2>
            {ai ? (
              <>
                {/* Before sending, the balance and whether it is enough; after, what the batch costs. */}
                <Price ctx={ctx} consent={chosen.length || !consent ? consent : { ...consent, balance: null }} photos={chosen.length || cards.length} />
                <p className="cat-hjalp">{t("batchCostHelp")}</p>
              </>
            ) : (
              <p>{t("batchFree")}</p>
            )}
          </section>
          <section className="tm-kort cat-avsnitt cat-lasav" aria-labelledby={`${id}-sedan`}>
            <h2 id={`${id}-sedan`}>{t("batchThen")}</h2>
            <p>{owner ? t("batchThenText") : t("batchThenLeave")}</p>
            {owner && batch && open.length ? (
              <>
                <button type="button" className="tm-knapp primar" disabled={!canApprove(batch) || props.approving} onClick={props.onApprove}>
                  {props.approving ? t("batchApproving") : t("batchApprove", { n: open.length })}
                </button>
                {queued ? <p className="cat-hjalp">{t("batchApproveWait")}</p> : null}
              </>
            ) : null}
            <ErrorLine text={props.approveError ?? null} />
          </section>
        </div>
      </div>
    </>
  );
}

export type CardEditProps = {
  ctx: Ctx;
  batch: Batch;
  card: BatchCard;
  n: number;
  flow: Flow;
  places: Place[];
  busy: boolean;
  error: string | null;
  onChange?: (flow: Flow) => void;
  onSave?: () => void;
  onCancel?: () => void;
};

/** A draft in the form of Lägg till med foto: the suggestions marked until accepted or edited
 * (CAT-136), the question about an uncertain digit (CAT-140), and what the AI warns about. Spara
 * keeps it in the draft; it becomes a vehicle when the batch is approved. */
export function CardEditView({ ctx, batch, card, n, flow, places, busy, error, onChange, onSave, onCancel }: CardEditProps) {
  const { t } = ctx;
  const options = openQuestion(flow);
  const unreadable = stillUnreadable(flow);
  const marked = Object.keys(flow.marks).length > 0;
  const warnings = card.warnings ?? [];
  const suggested = Object.keys(card.suggestions ?? {}).length > 0;
  const before = (
    <div className="cat-fore">
      {card.picture ? <img className="cat-kortbild" src={card.picture.display_url} alt={t("cardAlt", { n })} /> : null}
      {options ? (
        <QuestionView ctx={ctx} number={String(flow.fields.number ?? "")} options={options} canAdd={false} onAnswer={(option) => onChange?.(answer(flow, option))} />
      ) : null}
      {warnings.length ? (
        <section className="tm-kort cat-avsnitt" aria-label={t("checkTitle")}>
          <p className="cat-varning">{t("checkTitle")}</p>
          <ul className="cat-varningar">
            {warnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        </section>
      ) : null}
      {marked ? (
        <div className="cat-godkannrad">
          <button type="button" className="tm-knapp" onClick={() => onChange?.(accept(flow))}>
            {t("acceptAll")}
          </button>
          <span className="cat-hjalp">{t("acceptHint")}</span>
        </div>
      ) : null}
    </div>
  );
  return (
    <FormView
      ctx={ctx}
      fields={flow.fields}
      places={places}
      eyebrow={suggested ? t("reviewEyebrow") : t("cardByHand")}
      heading={t("cardHeading", { n })}
      intro={t("cardIntro")}
      crumb={t("batchTitle")}
      before={before}
      marks={flow.marks}
      onAccept={(field) => onChange?.(accept(flow, field))}
      unreadable={unreadable}
      blocked={unreadable.length ? t("unreadableBlocks", { fields: unreadable.map((field) => t(LABELS[field])).join(", ") }) : null}
      busy={busy}
      error={error}
      backHref={batchPath(batch.id)}
      onCancel={onCancel}
      onChange={(fields) => onChange?.(edit(flow, fields))}
      onSave={onSave}
    />
  );
}

/** The batches with photos still to approve, under Fordon: the owner's all, someone who edits
 * only those they left (CAT-153). */
export function BatchesSection({ ctx, batches }: { ctx: Ctx; batches: BatchSummary[] | null | undefined }) {
  const { t, language, navigate } = ctx;
  const id = useId();
  if (!batches?.length) return null;
  return (
    <section className="tm-kort cat-omgangar" aria-labelledby={id}>
      <h2 id={id}>{isOwner(ctx) ? t("batchesTitle") : t("batchesMine")}</h2>
      <ul>
        {batches.map((found) => {
          const count = (status: string) => found.counts[status] ?? 0;
          const counts = { ready: count("ready"), check: count("review") + count("failed") + count("manual"), left: count("waiting") + count("reading"), total: found.open };
          return (
            <li key={found.id}>
              <a href={batchPath(found.id)} onClick={linkClick(navigate, batchPath(found.id))}>
                {t("batchesOpen", { time: timeText(language, found.created_at) })}
              </a>
              <span className="cat-under">
                {t("batchesRow", { open: found.open, cards: found.cards })} · {tallyText(t, counts)}
                {found.mine ? "" : ` · ${t("batchesBy")}`}
              </span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

export function BatchPage({ ctx, id }: { ctx: Ctx; id?: string }) {
  if (!mayEdit(ctx))
    return (
      <>
        <Crumbs ctx={ctx} items={[{ href: PATHS.vehicles, label: ctx.t("vehicles") }, { label: ctx.t("batchTitle") }]} />
        <h1>{ctx.t("batchTitle")}</h1>
        <section className="tm-kort cat-tomt">
          <p className="cat-tomt-rubrik">{ctx.t("batchViewOnly")}</p>
        </section>
      </>
    );
  return <BatchWork ctx={ctx} id={id} />;
}

/** How many photos were drafts already, from the address the new batch moved to (CAT-149). */
const alreadyFromAddress = () => Math.max(0, Number(new URLSearchParams(window.location.search).get("fanns")) || 0);

function BatchWork({ ctx, id }: { ctx: Ctx; id?: string }) {
  const { t } = ctx;
  const owner = isOwner(ctx);
  // The batch's id is made here for a new batch: the photos are sent with it, so a retry never
  // makes two batches, and the same file is never two drafts (CAT-149).
  const [batchId] = useState(() => id ?? crypto.randomUUID());
  const [batch, setBatch] = useState<Batch | null>(null);
  const [gone, setGone] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [consent, setConsent] = useState<ReadingConsent | null>(null);
  const [consentKnown, setConsentKnown] = useState(!owner);
  const [agreed, setAgreed] = useState(false);
  const [asking, setAsking] = useState(false);
  const [chosen, setChosen] = useState<File[]>([]);
  const [choiceProblem, setChoiceProblem] = useState<string | null>(null);
  const [sending, setSending] = useState<{ done: number; of: number } | null>(null);
  const [sendError, setSendError] = useState<string | null>(null);
  const [already, setAlready] = useState(() => (id ? alreadyFromAddress() : 0));
  const [stopped, setStopped] = useState<string[]>([]);
  const [approveError, setApproveError] = useState<string | null>(null);
  const [approving, setApproving] = useState(false);
  const [busyCard, setBusyCard] = useState<string | null>(null);
  const [editing, setEditing] = useState<{ card: BatchCard; flow: Flow } | null>(null);
  const [editError, setEditError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [places, setPlaces] = useState<Place[]>([]);
  const [focus, setFocus] = useState<{ card: string; scroll: boolean } | null>(null);
  const previews = usePreviews(chosen);

  const reload = useCallback(async () => {
    try {
      setBatch(await api.batch(batchId));
      setError(null);
    } catch (failure) {
      if (failure instanceof ApiError && failure.status === 404) setGone(true);
      else setError(problemText(t, failure));
    }
  }, [batchId, t]);

  useEffect(() => {
    if (id) void reload();
  }, [id, reload]);

  useEffect(() => {
    if (!owner) return;
    // The price and the consent for the AI (CAT-19, CAT-142), and the places for the drafts.
    api.readingConsent().then(
      (found) => {
        setConsent(found);
        setConsentKnown(true);
      },
      () => setConsentKnown(true),
    );
    api.places().then(setPlaces, () => setPlaces([]));
  }, [owner]);

  // While photos wait or are read, the queue is followed; it goes on without the page too.
  const queued = batch?.cards.some(inQueue) ?? false;
  useEffect(() => {
    if (!queued || editing) return;
    const timer = window.setTimeout(() => void reload(), POLL_MS);
    return () => window.clearTimeout(timer);
  }, [queued, editing, batch, reload]);

  useEffect(() => {
    if (!focus || editing) return;
    const row = document.getElementById(`kort-${focus.card}`);
    if (focus.scroll) row?.scrollIntoView({ block: "center" });
    row?.focus({ preventScroll: true });
    setFocus(null);
  }, [focus, editing]);

  // A batch keeps the way it was made; a new one is read with AI by the owner when it can be.
  const ai = batch ? batch.ai : owner && consent?.available === true;

  const start = async (agreedNow: boolean) => {
    if (chosen.length === 0 || sending) return;
    const yes = agreed || agreedNow;
    if (ai && needsConsent(consent, yes)) {
      setAsking(true);
      return;
    }
    const photos = chosen;
    setSendError(null);
    setStopped([]);
    setApproveError(null);
    setSending({ done: 0, of: photos.length });
    const result = await sendPhotos({ id: batchId, ai, consent: ai && yes }, photos, (done) => setSending({ done, of: photos.length }));
    setSending(null);
    if (result.batch) setBatch(result.batch);
    setChosen(photos.slice(result.sent));
    const known = already + result.already.length;
    setAlready(known);
    if (result.error) {
      if (result.error instanceof ApiError && result.error.code === "consent_required") {
        setAgreed(false);
        setAsking(true);
        return;
      }
      setSendError(t("batchSendFailed", { n: result.sent + 1, problem: sendProblem(t, result.error) }));
      return;
    }
    if (yes) {
      setAgreed(true);
      setConsent((before) => (before ? { ...before, given: true } : before));
    }
    // The new batch gets its own address, so it can be opened again from the vehicles' list.
    if (!id) ctx.replace?.(batchPath(batchId) + (known ? `?fanns=${known}` : ""));
  };

  const change = (card: BatchCard) => {
    setEditing({ card, flow: cardFlow(card) });
    setEditError(null);
  };

  const saveCard = async () => {
    if (!editing || !batch || stillUnreadable(editing.flow).length) return;
    setSaving(true);
    setEditError(null);
    try {
      const changed = await api.changeCard(batch.id, editing.card.id, cardChange(editing.flow, editing.card));
      setBatch((now) => now && { ...now, cards: now.cards.map((card) => (card.id === changed.id ? changed : card)) });
      setStopped((now) => now.filter((card) => card !== changed.id));
      setEditing(null);
      setFocus({ card: changed.id, scroll: true });
    } catch (failure) {
      const changedMeanwhile = failure instanceof ApiError && failure.code === "changed";
      setEditError(changedMeanwhile ? t("batchChanged") : problemText(t, failure));
      if (changedMeanwhile) void reload();
    } finally {
      setSaving(false);
    }
  };

  const onCard = async (card: BatchCard, work: () => Promise<BatchCard | null>) => {
    setBusyCard(card.id);
    setApproveError(null);
    try {
      const after = await work();
      setBatch((now) => now && { ...now, cards: after ? now.cards.map((found) => (found.id === after.id ? after : found)) : now.cards.filter((found) => found.id !== card.id) });
      setStopped((now) => now.filter((found) => found !== card.id));
      setError(null);
    } catch (failure) {
      setError(problemText(t, failure));
    } finally {
      setBusyCard(null);
    }
  };

  const approve = async () => {
    if (!batch) return;
    setApproving(true);
    setApproveError(null);
    setStopped([]);
    const outcome = await approveAll(batch);
    setApproving(false);
    if (outcome.kind === "approved") {
      ctx.navigate?.(PATHS.vehicles);
      return;
    }
    if (outcome.kind === "stopped") {
      // Nothing was approved (CAT-150): the cards that stopped it, the first in view.
      setStopped(outcome.cards);
      const n = outcome.cards.length;
      setApproveError(outcome.unreadable ? t("batchUnreadable") : n === 1 ? t("batchStoppedOne") : t("batchStopped", { n }));
      if (outcome.cards[0]) setFocus({ card: outcome.cards[0], scroll: true });
      return;
    }
    if (outcome.error instanceof ApiError && outcome.error.code === "changed") {
      setApproveError(t("batchChanged"));
      void reload();
      return;
    }
    setApproveError(problemText(t, outcome.error));
  };

  if (gone)
    return (
      <>
        <Crumbs ctx={ctx} items={[{ href: PATHS.vehicles, label: t("vehicles") }, { label: t("batchTitle") }]} />
        <h1>{t("batchTitle")}</h1>
        <section className="tm-kort cat-tomt">
          <p className="cat-tomt-rubrik">{t("batchGone")}</p>
          <a className="tm-knapp primar" href={PATHS.vehicles} onClick={linkClick(ctx.navigate, PATHS.vehicles)}>
            {t("toVehicles")}
          </a>
        </section>
      </>
    );

  if (editing && batch) {
    const n = batch.cards.findIndex((card) => card.id === editing.card.id) + 1;
    return (
      <CardEditView
        ctx={ctx}
        batch={batch}
        card={editing.card}
        n={n}
        flow={editing.flow}
        places={places}
        busy={saving}
        error={editError}
        onChange={(flow) => setEditing((now) => now && { ...now, flow })}
        onSave={() => void saveCard()}
        onCancel={() => {
          setFocus({ card: editing.card.id, scroll: true });
          setEditing(null);
        }}
      />
    );
  }

  if (id && batch === null && !error) return <p className="cat-laddar">{t("loading")}</p>;

  return (
    <>
      <BatchView
        ctx={ctx}
        batch={batch}
        ai={ai}
        noAi={owner && batch === null && consentKnown && consent?.available !== true}
        consent={consent}
        chosen={chosen}
        previews={previews}
        notReady={!consentKnown}
        choiceProblem={choiceProblem}
        sending={sending}
        sendError={sendError}
        already={already}
        stopped={stopped}
        approveError={approveError}
        approving={approving}
        busyCard={busyCard}
        error={error}
        onChoose={(files) => {
          const picked = choosePhotos(chosen, files, batch?.cards.length ?? 0);
          setChosen(picked.photos);
          setChoiceProblem(picked.problem ? t(picked.problem === "batch_full" ? "batchFull" : `problem_${picked.problem}`) : null);
          setSendError(null);
        }}
        onUnchoose={(index) => {
          setChosen((now) => now.filter((_, at) => at !== index));
          setChoiceProblem(null);
        }}
        onStart={() => void start(false)}
        onEdit={change}
        onRemove={(card) =>
          void onCard(card, async () => {
            await api.removeCard(batchId, card.id);
            return null;
          })
        }
        onRetry={owner ? (card) => void onCard(card, () => api.retryCard(batchId, card.id)) : undefined}
        onApprove={() => void approve()}
      />
      <Dialog open={asking} title={t("consentTitle")} onClose={() => setAsking(false)}>
        <ConsentView
          ctx={ctx}
          consent={consent}
          photos={chosen.length}
          keeps={t("batchConsentKeeps")}
          onNo={() => setAsking(false)}
          onYes={() => {
            setAsking(false);
            void start(true);
          }}
        />
      </Dialog>
    </>
  );
}
