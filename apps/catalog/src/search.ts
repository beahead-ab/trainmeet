// Sök på webben, the flow without its screens (#53 del b, CAT-166–CAT-172, CAT-219): what is
// asked, the search with its client-made id, the proposal the person sends, and Catalog's noes
// in the search's own words. SearchPage.tsx shows it.
import {
  api,
  ApiError,
  type FieldProfile,
  type PrototypeProposal,
  type PrototypeSearch,
  type PrototypeSearchAsk,
  type PrototypeSearchConsent,
  type TypeData,
  type VehicleKind,
} from "./api";
import { problemText, type T } from "./common";

/** The marking to search for (CAT-166): nothing else is sent. */
export type SearchForm = { litt: string; operator: string; kind: VehicleKind | null; profile: FieldProfile };
export const EMPTY_FORM: SearchForm = { litt: "", operator: "", kind: null, profile: "SE" };

/** The proposal as the person sends it: the name, the values, changed or not, and the yes to
 * sharing them (CAT-163). */
export type SearchDraft = { name: string; fields: TypeData; mayShare: boolean; editing: boolean };

/** As the marking is written (contracts/catalog.py, MarkingText): letters, digits and a few signs. */
const MARKING = /^[0-9A-Za-zÀ-ÖØ-öø-ÿ .,'()/+&-]*$/;
const digits = (text: string) => text.replace(/\D/g, "").length;

/** A litt and an operator, never a vehicle's number: what Catalog and the meter would refuse is
 * said before anything is sent. */
export function markingOk(form: SearchForm): boolean {
  const litt = form.litt.trim();
  const operator = form.operator.trim();
  return litt !== "" && litt.length <= 40 && operator.length <= 80 && MARKING.test(litt) && MARKING.test(operator) && digits(litt) <= 5 && digits(operator) <= 4;
}

export const askOf = (id: string, form: SearchForm, consent: boolean): PrototypeSearchAsk => ({
  id,
  litt: form.litt.trim(),
  operator: form.operator.trim(),
  kind: form.kind,
  profile: form.profile,
  consent,
});

export const formOf = (search: PrototypeSearch): SearchForm => ({ litt: search.litt, operator: search.operator ?? "", kind: search.kind ?? null, profile: search.profile });

/** The proposal starts as the search found it, named by the litt. */
export const draftOf = (search: PrototypeSearch): SearchDraft => ({ name: search.litt, fields: { ...search.fields }, mayShare: false, editing: false });

/** What is sent to the review queue: the fields the profile has, and the search they come from.
 * The evidence is Catalog's own, from the stored search; only its id is sent (CAT-171). */
export function proposalOf(search: PrototypeSearch, draft: SearchDraft, keys: string[], sourceText: string): PrototypeProposal {
  const fields = Object.fromEntries(Object.entries(draft.fields).filter(([key, value]) => keys.includes(key) && value.trim()));
  return {
    prototype: null,
    base: null,
    name: draft.name.trim(),
    kind: search.kind ?? null,
    profile: search.profile,
    fields,
    source: { kind: "web_search", text: sourceText },
    may_share: true,
    search: search.id,
  };
}

export const readyToSend = (draft: SearchDraft) => draft.mayShare && draft.name.trim() !== "";

/** The person must say yes before the first search (CAT-142). */
export const needsConsent = (consent: PrototypeSearchConsent, agreed: boolean) => !consent.given && !agreed;

export const canPay = (consent: PrototypeSearchConsent | null) => consent !== null && consent.available && (consent.balance ?? 0) >= consent.price;

const WAIT = 4000;
const TRIES = 75;

/** Search, and keep asking with the same id when the connection drops while the search runs:
 * the same id never searches or draws twice (CAT-144), so the answer is the one search's. A
 * search or reading that was running before this one started is someone's other work: that no
 * is passed on. */
export async function runSearch(
  ask: PrototypeSearchAsk,
  search: (ask: PrototypeSearchAsk) => Promise<PrototypeSearch> = api.searchPrototype,
  wait: (ms: number) => Promise<void> = (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
): Promise<PrototypeSearch> {
  let lost = false;
  for (let attempt = 0; ; attempt += 1) {
    try {
      return await search(ask);
    } catch (failure) {
      const busy = failure instanceof ApiError && failure.code === "reading_busy";
      // No answer from Catalog itself: the connection dropped, or something on the way gave up.
      const dropped = !(failure instanceof ApiError) || (failure.code === null && (failure.status === 502 || failure.status === 504));
      if (attempt >= TRIES || !(dropped || (busy && lost))) throw failure;
      lost = true;
      await wait(WAIT);
    }
  }
}

/** Catalog's no to a search, in the search's own words. */
export function searchProblem(t: T, failure: unknown): string {
  if (!(failure instanceof ApiError)) return t("searchProblemFailed");
  switch (failure.code) {
    case "no_tokens":
      return t("searchProblemShort");
    case "reading_busy":
      return t("searchProblemBusy");
    case "reading_failed":
      return t("searchProblemFailed");
    case "too_many":
      return t("searchProblemTooMany");
    case "bad_type_data":
      return t("searchProblemMarking");
    case "changed":
      return t("searchProblemChanged");
    case "search_off":
      return t("problem_search_off");
    case "unavailable":
      return t("searchProblemNow");
    default:
      return problemText(t, failure);
  }
}
