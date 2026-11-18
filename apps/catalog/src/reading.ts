// Lägg till med foto, the flow without its screens (#52, CAT-134–CAT-146): the photos, the
// reading with its client-made id, the AI's suggestions marked until the owner has seen them,
// the uncertain digit, and what Spara sends. PhotoFlow.tsx shows it.
import {
  api,
  ApiError,
  KINDS,
  READING_PICTURES,
  SUGGESTED_FIELDS,
  type Reading,
  type ReadingConsent,
  type SuggestedField,
  type Suggestion,
  type Vehicle,
  type VehicleFields,
  type VehicleKind,
} from "./api";
import { problemText, type T } from "./common";
import { checkPicture } from "./Pictures";
import { EMPTY, outgoing } from "./VehicleForm";

/** Fota, AI:n läser, granska, plats och tagg, klart (CAT-134). */
export type FlowStep = "photo" | "reading" | "review" | "place" | "done";

export type Flow = {
  step: FlowStep;
  /** The photos in order: they become the vehicle's pictures, the first the main one. */
  photos: File[];
  /** The reading's id while it may be retried: the same id never reads or draws twice
   * (CAT-144). Null when the next reading needs a new one. */
  readingId: string | null;
  /** The last reading, and how many photos it read. */
  reading: Reading | null;
  read: number;
  fields: VehicleFields;
  /** The AI's suggestions the owner has not yet accepted or edited (CAT-136). */
  marks: Partial<Record<SuggestedField, Suggestion>>;
  /** The fields the AI wrote with a ? for a character it could not read (CAT-138). */
  unreadable: SuggestedField[];
  /** The person said yes to sending the photos, in this flow (CAT-142). */
  agreed: boolean;
};

export const newFlow = (): Flow => ({
  step: "photo",
  photos: [],
  readingId: null,
  reading: null,
  read: 0,
  fields: EMPTY,
  marks: {},
  unreadable: [],
  agreed: false,
});

const valueOf = (fields: VehicleFields, field: SuggestedField) => String(fields[field] ?? "");

/** Photos chosen: what Catalog would refuse is left out, and never more than four in all. */
export function addPhotos(flow: Flow, files: File[]): { flow: Flow; problem: "bad_picture" | "picture_too_large" | "photos_full" | null } {
  let problem: "bad_picture" | "picture_too_large" | "photos_full" | null = null;
  const fine: File[] = [];
  for (const file of files) {
    const wrong = checkPicture(file);
    if (wrong) problem = wrong;
    else fine.push(file);
  }
  const room = READING_PICTURES - flow.photos.length;
  if (fine.length > room) problem = "photos_full";
  const taken = fine.slice(0, Math.max(room, 0));
  if (taken.length === 0) return { flow, problem };
  // Other photos are another reading, with an id of its own.
  return { flow: { ...flow, photos: [...flow.photos, ...taken], readingId: null }, problem };
}

export function removePhoto(flow: Flow, index: number): Flow {
  return { ...flow, photos: flow.photos.filter((_, at) => at !== index), readingId: null };
}

/** Hoppa över, fyll i själv: the form without a reading, or with the last one's suggestions. */
export function skipReading(flow: Flow): Flow {
  return { ...flow, step: "review" };
}

/** The AI's suggestions in the form, marked (CAT-136). A field that is the owner's own, typed or
 * accepted, keeps its value; an empty or still marked field gets the new suggestion. */
export function applyReading(flow: Flow, reading: Reading): Flow {
  let fields = flow.fields;
  const marks = { ...flow.marks };
  const unreadable = new Set(flow.unreadable);
  for (const field of SUGGESTED_FIELDS) {
    const suggestion = reading.suggestions?.[field];
    if (!suggestion) continue;
    if (field === "kind" && !(KINDS as string[]).includes(suggestion.value)) continue;
    if (!marks[field] && valueOf(fields, field) !== "") continue;
    fields = { ...fields, [field]: field === "kind" ? (suggestion.value as VehicleKind) : suggestion.value } as VehicleFields;
    marks[field] = suggestion;
    if (suggestion.value.includes("?")) unreadable.add(field);
    else unreadable.delete(field);
  }
  return { ...flow, step: "review", reading, read: flow.photos.length, readingId: null, fields, marks, unreadable: [...unreadable] };
}

/** The owner changed the form: a field they edited is their own, no longer a suggestion. */
export function edit(flow: Flow, fields: VehicleFields): Flow {
  const marks = { ...flow.marks };
  for (const field of SUGGESTED_FIELDS) if (marks[field] && valueOf(fields, field) !== valueOf(flow.fields, field)) delete marks[field];
  return { ...flow, fields, marks };
}

/** Godkänn one suggestion, or all of them. */
export function accept(flow: Flow, field?: SuggestedField): Flow {
  if (!field) return { ...flow, marks: {} };
  const marks = { ...flow.marks };
  delete marks[field];
  return { ...flow, marks };
}

/** The question about the uncertain digit, while the number still has its ? (CAT-140). */
export function openQuestion(flow: Flow): string[] | null {
  const question = flow.reading?.question;
  if (!question || question.field !== "number" || question.options.length === 0) return null;
  return valueOf(flow.fields, "number").includes("?") ? question.options : null;
}

/** The owner chose one of the options: the number is theirs. */
export function answer(flow: Flow, option: string): Flow {
  return accept({ ...flow, fields: { ...flow.fields, number: option } }, "number");
}

/** The digits around the uncertain one, as they stand in an option: "455" in "31 74 455 1 209-6". */
export function uncertainPart(number: string, option: string): string {
  const at = number.indexOf("?");
  if (at < 0 || option.length !== number.length) return option;
  let start = at;
  let end = at + 1;
  while (start > 0 && /\d/.test(option[start - 1] ?? "")) start -= 1;
  while (end < option.length && /\d/.test(option[end] ?? "")) end += 1;
  return option.slice(start, end);
}

/** The fields that still have a character the AI could not read: Spara waits (CAT-138). */
export function stillUnreadable(flow: Flow): SuggestedField[] {
  return flow.unreadable.filter((field) => valueOf(flow.fields, field).includes("?"));
}

// --- The reading -------------------------------------------------------------------------------

/** The first time, the person sees what is sent and to whom before anything is sent (CAT-142). */
export function needsConsent(consent: ReadingConsent | null, agreed: boolean): boolean {
  return !agreed && consent !== null && !consent.given;
}

/** No answer from Catalog itself: the network, or a proxy's 5xx without Catalog's code. */
const noAnswer = (error: unknown) => !(error instanceof ApiError) || (error.code === null && error.status >= 500);

/** Whether a retry may use the same id: when Catalog never answered, or the reading is still
 * running, the same id gives the stored reading without reading or drawing again (CAT-144). After
 * any other answer nothing was read or drawn, and the next reading is a new one. */
export function keepsId(error: unknown): boolean {
  return noAnswer(error) || (error instanceof ApiError && (error.code === "reading_busy" || error.code === "consent_required"));
}

export type Attempt = { kind: "consent" } | { kind: "read"; reading: Reading } | { kind: "failed"; error: unknown; keepId: boolean };

/** One try at the reading, with the id the client made for it. */
export async function attemptReading(id: string, photos: Blob[], consent: ReadingConsent | null, agreed: boolean): Promise<Attempt> {
  if (needsConsent(consent, agreed)) return { kind: "consent" };
  try {
    const reading = await api.read({ id, consent: agreed, vehicle: null, version: null }, photos);
    if (reading.status !== "done") return { kind: "failed", error: new ApiError(502, "reading_failed"), keepId: false };
    return { kind: "read", reading };
  } catch (error) {
    if (error instanceof ApiError && error.code === "consent_required") return { kind: "consent" };
    return { kind: "failed", error, keepId: keepsId(error) };
  }
}

/** Why the reading did not work, what was drawn (nothing, CAT-20), and the way on. */
export type Trouble = { text: string; buyTokens: boolean; byHand: boolean };

export function readingTrouble(t: T, error: unknown): Trouble {
  const nothing = t("nothingDrawn");
  const said = (text: string, more: Partial<Trouble> = {}): Trouble => ({ text: `${text} ${nothing}`, buyTokens: false, byHand: false, ...more });
  if (error instanceof ApiError && error.status === 413) return said(t("problem_picture_too_large"));
  if (noAnswer(error)) return { text: t("readNoAnswer"), buyTokens: false, byHand: false };
  if (!(error instanceof ApiError) || error.code === null) return said(t("problem_other"));
  switch (error.code) {
    case "no_tokens":
      return said(t("readNoTokens"), { buyTokens: true });
    case "too_many":
      return error.retryAfter ? said(t("readTooMany", { minutes: Math.max(1, Math.ceil(error.retryAfter / 60)) })) : said(t("readCap"));
    case "reading_busy":
      return said(t("readBusy"));
    case "unavailable":
      return said(t("readUnavailable"), { byHand: true });
    case "reading_failed":
      return said(t("readFailed"));
    case "changed":
      return said(t("readChanged"));
    case "forbidden":
      return said(t("readOwnerOnly"), { byHand: true });
    default:
      return said(problemText(t, error));
  }
}

// --- Saving ------------------------------------------------------------------------------------

/** Spara: the vehicle through its own address, with the suggestions that are left accepted
 * (CAT-136). Not while a character the AI could not read is still a ? (CAT-138). */
export async function saveVehicle(flow: Flow): Promise<Vehicle> {
  if (stillUnreadable(flow).length) throw new ApiError(422, null);
  return api.addVehicle(outgoing(flow.fields));
}

/** The photos become the vehicle's pictures once it exists, in order, so the first is the main
 * one (CAT-125). The first failure is returned; the vehicle is saved whatever happens. */
export async function uploadPhotos(vehicle: Vehicle, photos: File[], onDone?: (done: number) => void): Promise<unknown> {
  let failed: unknown = null;
  for (const [index, photo] of photos.entries()) {
    try {
      await api.addPicture(vehicle.id, photo, false, "original");
    } catch (error) {
      failed ??= error;
    }
    onDone?.(index + 1);
  }
  return failed;
}
