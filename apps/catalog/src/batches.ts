// Lägg till flera (#52 del d, CAT-147–CAT-153), the batch without its screens: the photos chosen
// and sent with the batch's client-made id, the queue followed, each draft edited with the same
// marks and uncertain-digit question as Lägg till med foto (reading.ts), and Godkänn alla, all or
// nothing (CAT-150). BatchPage.tsx shows it.
import {
  api,
  ApiError,
  BATCH_PHOTOS,
  KINDS,
  SUGGESTED_FIELDS,
  type Batch,
  type BatchAsk,
  type BatchCard,
  type BatchCardChange,
  type Reading,
  type SuggestedField,
  type Suggestion,
  type VehicleFields,
} from "./api";
import { problemText, type T } from "./common";
import { checkPicture } from "./Pictures";
import { stillUnreadable, type Flow } from "./reading";
import { outgoing } from "./VehicleForm";

/** How often the page reads the batch again while photos wait or are read, in milliseconds. */
export const POLL_MS = 3000;

/** Still in the queue: waiting for its turn, or read now (CAT-147). */
export const inQueue = (card: Pick<BatchCard, "status">) => card.status === "waiting" || card.status === "reading";

/** The cards not yet approved: what Godkänn alla carries. */
export const openCards = (batch: Batch): BatchCard[] => batch.cards.filter((card) => card.status !== "approved");

/** The heading's count: ready, to check (read with something to check, failed, or to fill in by
 * hand), and left in the queue. */
export type Tally = { ready: number; check: number; left: number; total: number };

export function tally(cards: BatchCard[]): Tally {
  const open = cards.filter((card) => card.status !== "approved");
  const count = (...statuses: BatchCard["status"][]) => open.filter((card) => statuses.includes(card.status)).length;
  return { ready: count("ready"), check: count("review", "failed", "manual"), left: count("waiting", "reading"), total: open.length };
}

/** The tokens ran out: in a batch read with AI, the photos left became manual (CAT-152). */
export const tokensRanOut = (batch: Batch | null): boolean => Boolean(batch?.ai && batch.cards.some((card) => card.status === "manual"));

export type ChoiceProblem = "bad_picture" | "picture_too_large" | "batch_full";

/** Photos chosen: what Catalog would refuse is left out (CAT-123), and never more than 30 in the
 * batch with those already in it (CAT-147). */
export function choosePhotos(chosen: File[], files: File[], inBatch: number): { photos: File[]; problem: ChoiceProblem | null } {
  let problem: ChoiceProblem | null = null;
  const fine: File[] = [];
  for (const file of files) {
    const wrong = checkPicture(file);
    if (wrong) problem = wrong;
    else fine.push(file);
  }
  const room = Math.max(BATCH_PHOTOS - inBatch - chosen.length, 0);
  if (fine.length > room) problem = "batch_full";
  return { photos: [...chosen, ...fine.slice(0, room)], problem };
}

/** How the sending went: the batch as Catalog last answered, the cards the photos already were
 * (CAT-149), how many photos were sent, and what stopped the rest. */
export type Sending = { batch: Batch | null; already: string[]; sent: number; error: unknown };

/** The photos, one a request with the batch's id: each request stays far below the 60 MB Catalog
 * reads at a time (catalog/batches_api.py), and the progress is per photo. The first refusal
 * stops the rest, which are left to send again with the same id. */
export async function sendPhotos(ask: BatchAsk, photos: File[], onSent?: (sent: number) => void): Promise<Sending> {
  let batch: Batch | null = null;
  const already = new Set<string>();
  let sent = 0;
  for (const photo of photos) {
    try {
      batch = await api.addBatchPhotos(ask, [photo]);
    } catch (error) {
      return { batch, already: [...already], sent, error };
    }
    for (const card of batch.already ?? []) already.add(card);
    sent += 1;
    onSent?.(sent);
  }
  return { batch, already: [...already], sent, error: null };
}

/** Why a photo was not taken, in the batch's words. */
export function sendProblem(t: T, error: unknown): string {
  if (error instanceof ApiError && error.status === 413) return t("problem_picture_too_large");
  if (error instanceof ApiError && error.code === "too_many_pictures") return t("batchTooMany");
  return problemText(t, error);
}

const valueOf = (fields: VehicleFields, field: SuggestedField) => String(fields[field] ?? "");

/** The card as the form of Lägg till med foto sees it (reading.ts): its values, the AI's
 * suggestions marked where the value is still the one suggested (CAT-136), the fields with a
 * character the AI could not read (CAT-138), and its question (CAT-140). */
export function cardFlow(card: BatchCard): Flow {
  const fields = card.values as VehicleFields;
  const marks: Partial<Record<SuggestedField, Suggestion>> = {};
  const unreadable: SuggestedField[] = [];
  for (const field of SUGGESTED_FIELDS) {
    const suggestion = card.suggestions?.[field];
    if (!suggestion) continue;
    if (field === "kind" && !(KINDS as string[]).includes(suggestion.value)) continue;
    if (valueOf(fields, field) === suggestion.value) marks[field] = suggestion;
    if (suggestion.value.includes("?")) unreadable.push(field);
  }
  const reading: Reading = {
    id: card.id,
    status: "done",
    suggestions: card.suggestions ?? {},
    question: card.question ?? null,
    summary: "",
    warnings: card.warnings ?? [],
    suggested_next_photo: "",
    cost: 0,
    model: "",
    prototype: card.prototype ?? null,
  };
  return { step: "review", photos: [], readingId: null, reading, read: 1, fields, marks, unreadable, agreed: true };
}

/** What a change of the card sends: the values as the form has them, on the version seen. */
export const cardChange = (flow: Flow, card: BatchCard): BatchCardChange => ({ values: outgoing(flow.fields), version: card.version });

/** The cards that still have a character the AI could not read: Godkänn alla waits for them, as
 * Spara does (CAT-138). */
export const unreadableCards = (batch: Batch): string[] => openCards(batch).filter((card) => stillUnreadable(cardFlow(card)).length > 0).map((card) => card.id);

/** Godkänn alla can be asked: something to approve, and nothing left in the queue. */
export const canApprove = (batch: Batch | null): boolean => batch !== null && openCards(batch).length > 0 && !batch.cards.some(inQueue);

export type Approval =
  | { kind: "approved"; batch: Batch }
  /** Nothing was approved: these cards stopped it, Catalog's (Problem.cards) or a ? still there. */
  | { kind: "stopped"; cards: string[]; unreadable: boolean; error: unknown }
  | { kind: "failed"; error: unknown };

/** Godkänn alla: every open card with the version shown, so nothing unseen is approved (CAT-136),
 * and either all become vehicles or none does (CAT-150). */
export async function approveAll(batch: Batch): Promise<Approval> {
  const unreadable = unreadableCards(batch);
  if (unreadable.length) return { kind: "stopped", cards: unreadable, unreadable: true, error: null };
  try {
    const cards = openCards(batch).map((card) => ({ id: card.id, version: card.version }));
    return { kind: "approved", batch: await api.approveBatch(batch.id, { cards }) };
  } catch (error) {
    if (error instanceof ApiError && error.cards.length) return { kind: "stopped", cards: error.cards, unreadable: false, error };
    return { kind: "failed", error };
  }
}
