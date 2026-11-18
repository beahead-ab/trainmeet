// Catalog's API with the types generated from the contracts (CAT-36,
// contracts/catalog.openapi.json -> contracts/catalog.d.ts). Nothing here is typed by hand.
import type { components } from "../../../contracts/catalog";

type Schemas = components["schemas"];
export type CatalogVersion = Schemas["trainmeet.catalog-1.version"];
export type Session = Schemas["trainmeet.catalog-1.session"];
export type AppKey = NonNullable<Session["apps"]>[number];
export type Account = Schemas["trainmeet.catalog-1.account"];
export type TrialLogin = Schemas["trainmeet.catalog-1.trial-login"];
export type Vehicle = Schemas["trainmeet.catalog-1.vehicle"];
export type VehicleFields = Schemas["trainmeet.catalog-1.vehicle-fields"];
export type VehicleChange = Schemas["trainmeet.catalog-1.vehicle-change"];
export type VehicleList = Schemas["trainmeet.catalog-1.vehicle-list"];
export type VehicleEvent = Schemas["trainmeet.catalog-1.vehicle-event"];
export type Place = Schemas["trainmeet.catalog-1.place"];
export type Lend = Schemas["trainmeet.catalog-1.lend"];
export type Problem = Schemas["trainmeet.catalog-1.problem"];
export type VehicleKind = Schemas["trainmeet.catalog-1.vehicle.VehicleKind"];
export type VehicleState = Schemas["trainmeet.catalog-1.vehicle.VehicleState"];
export type ProblemCode = Problem["code"];
export type Tag = Schemas["trainmeet.catalog-1.tag"];
export type VehicleTag = Vehicle["tags"] extends (infer T)[] | undefined ? T : never;
export type Lookup = Schemas["trainmeet.catalog-1.lookup"];
export type TagEvent = Schemas["trainmeet.catalog-1.tag-event"];
export type PendingState = Schemas["trainmeet.catalog-1.pending"];
export type TagLink = Schemas["trainmeet.catalog-1.tag-link"];
export type FleetChoice = Schemas["trainmeet.catalog-1.fleet-choice"];
export type FleetRight = FleetChoice["right"];
export type Picture = Schemas["trainmeet.catalog-1.picture"];
export type PictureBackground = Schemas["trainmeet.catalog-1.picture.PictureBackground"];
export type BackgroundChange = Schemas["trainmeet.catalog-1.background-change"];
export type StorageUse = Schemas["trainmeet.catalog-1.storage-use"];
export type TripSummary = Schemas["trainmeet.catalog-1.trip-summary"];
export type Trip = Schemas["trainmeet.catalog-1.trip"];
export type TripRow = Trip["rows"][number];
export type TripStep = Trip["step"];
export type Tick = TripRow["ticks"][number];
export type NewTrip = Schemas["trainmeet.catalog-1.new-trip"];
export type TripTapped = Schemas["trainmeet.catalog-1.trip-tapped"];
export type Reading = Schemas["trainmeet.catalog-1.reading"];
export type ReadingAsk = Schemas["trainmeet.catalog-1.reading-ask"];
export type ReadingConsent = Schemas["trainmeet.catalog-1.reading-consent"];
export type ReadingQuestion = Schemas["trainmeet.catalog-1.reading.ReadingQuestion"];
export type Suggestion = Schemas["trainmeet.catalog-1.reading.Suggestion"];
export type NewVehicle = Schemas["trainmeet.catalog-1.new-vehicle"];
export type Batch = Schemas["trainmeet.catalog-1.batch"];
export type BatchCard = Schemas["trainmeet.catalog-1.batch-card"];
export type BatchCardStatus = BatchCard["status"];
export type BatchSummary = Schemas["trainmeet.catalog-1.batch-summary"];
export type BatchAsk = Schemas["trainmeet.catalog-1.batch-ask"];
export type BatchCardChange = Schemas["trainmeet.catalog-1.batch-card-change"];
export type BatchApproval = Schemas["trainmeet.catalog-1.batch-approval"];
/** The core fields the AI suggests from a photo (CAT-137, CAT-139): SuggestedField in
 * contracts/catalog.py. The generated type keys Reading.suggestions by any string, so the names
 * are written here, as KINDS and STATES are. */
export type SuggestedField = "kind" | "litt" | "number" | "operator" | "maker" | "article_number";
/** Förebildskatalogen (#53, CAT-155–CAT-165, CAT-173). */
export type FieldRegister = Schemas["trainmeet.catalog-1.field-register"];
export type TypeField = FieldRegister["fields"][number];
export type ProfileFields = FieldRegister["profiles"][number];
export type FieldProfile = ProfileFields["profile"];
export type Prototype = Schemas["trainmeet.catalog-1.prototype"];
export type PrototypeList = Schemas["trainmeet.catalog-1.prototype-list"];
export type PrototypeRevision = Schemas["trainmeet.catalog-1.prototype-revision"];
export type PrototypeProposal = Schemas["trainmeet.catalog-1.prototype-proposal"];
export type PrototypeReview = Schemas["trainmeet.catalog-1.prototype-review"];
export type PrototypeSummary = Schemas["trainmeet.catalog-1.prototype-summary"];
export type PrototypeLink = Schemas["trainmeet.catalog-1.prototype-link"];
export type PrototypeStatus = Prototype["status"];
export type PrototypeSourceKind = PrototypeRevision["source"]["kind"];
export type VehiclePrototype = Schemas["trainmeet.catalog-1.vehicle-prototype"];
/** Typuppgifter: the values by the field register's keys (CAT-156). */
export type TypeData = Record<string, string>;

export const KINDS: VehicleKind[] = ["locomotive", "freight_wagon", "passenger_coach", "multiple_unit", "other"];
export const STATES: VehicleState[] = ["home", "packed", "at_meet", "lent"];
export const ENGINES: VehicleKind[] = ["locomotive", "multiple_unit"];
/** The trip's three steps, in order (CAT-176). */
export const STEPS: TripStep[] = ["pack", "arrive", "home"];
/** The backgrounds a picture can have, original first (CAT-128). */
export const BACKGROUNDS: PictureBackground[] = ["original", "white", "grey", "transparent", "rails"];
/** What an upload may be (CAT-123). HEIC from an iPhone is sent as JPEG by the browser. */
export const PICTURE_KINDS = ["image/jpeg", "image/png", "image/webp"] as const;
/** As in catalog/pictures.py: 10 pictures per vehicle (CAT-17), at most 15 MB each (CAT-123). */
export const PICTURES_PER_VEHICLE = 10;
export const PICTURE_MAX_BYTES = 15 * 1024 * 1024;
/** The fields a reading may suggest, in the form's order (CAT-137). */
export const SUGGESTED_FIELDS: SuggestedField[] = ["kind", "litt", "number", "operator", "maker", "article_number"];
/** As in catalog/reading.py: 1–4 photos in one reading, the whole vehicle and close-ups (CAT-135). */
export const READING_PICTURES = 4;
/** As in contracts/catalog.py: up to 30 photos in a batch, one per vehicle (CAT-147). */
export const BATCH_PHOTOS = 30;
/** Where a batch's photo is (CAT-147–CAT-153), in the order a photo goes. */
export const CARD_STATUSES: BatchCardStatus[] = ["waiting", "reading", "ready", "review", "failed", "manual", "approved"];

/** Catalog said no, with a code the web app has a text for, or something else went wrong.
 * retryAfter is Catalog's Retry-After in seconds, when it said when to try again (CAT-146).
 * cards are the batch's cards that stopped Godkänn alla (Problem.cards, CAT-150). */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: ProblemCode | null,
    readonly retryAfter: number | null = null,
    readonly cards: string[] = [],
  ) {
    super(`Catalog svarade ${status}${code ? ` (${code})` : ""}`);
  }
}

/** A form, such as a reading's photos, goes as the browser builds it; anything else as JSON. */
async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method, credentials: "same-origin", headers: { Accept: "application/json" } };
  if (body instanceof FormData) {
    init.body = body;
  } else if (body !== undefined) {
    init.headers = { ...init.headers, "Content-Type": "application/json" };
    init.body = JSON.stringify(body);
  }
  const response = await fetch(path, init);
  if (!response.ok) {
    const problem = problemOf(await response.text().catch(() => ""));
    throw new ApiError(response.status, problem.code, secondsOf(response.headers.get("Retry-After")), problem.cards);
  }
  return (await response.json()) as T;
}

/** Retry-After in seconds; a date or anything else is no answer. */
function secondsOf(value: string | null): number | null {
  return value && /^\d+$/.test(value.trim()) ? Number(value.trim()) : null;
}

/** A form with photos (catalog/reading_api.py): the part data is the ask as JSON, and the parts
 * images are the photos, in order. */
function photoForm(ask: ReadingAsk | BatchAsk, photos: Blob[]): FormData {
  const form = new FormData();
  form.append("data", JSON.stringify(ask));
  photos.forEach((photo, index) => form.append("images", photo, photo instanceof File && photo.name ? photo.name : `foto-${index + 1}`));
  return form;
}

/** A reading's form: the ReadingAsk and the 1–4 photos. */
export const readingForm = (ask: ReadingAsk, photos: Blob[]): FormData => photoForm(ask, photos);

/** A batch's form (catalog/batches_api.py): the BatchAsk and the photos sent this time. */
export const batchForm = (ask: BatchAsk, photos: Blob[]): FormData => photoForm(ask, photos);

/** The code in Catalog's answer when it said no, if it is one, and the cards it names. */
function problemOf(body: string): { code: ProblemCode | null; cards: string[] } {
  try {
    const problem = JSON.parse(body) as Partial<Problem> | null;
    const cards = Array.isArray(problem?.cards) ? problem.cards.filter((card): card is string => typeof card === "string") : [];
    return { code: typeof problem?.code === "string" ? problem.code : null, cards };
  } catch {
    return { code: null, cards: [] };
  }
}

function codeOf(body: string): ProblemCode | null {
  return problemOf(body).code;
}

/** The picture as the request's body, with its own type (CAT-123). XMLHttpRequest rather than
 * fetch, since only it tells how much of the picture has been sent: `onSent` gets 0–1. */
function send<T>(path: string, file: Blob, onSent?: (part: number) => void): Promise<T> {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open("POST", path);
    request.setRequestHeader("Accept", "application/json");
    request.setRequestHeader("Content-Type", file.type);
    if (onSent) request.upload.onprogress = (event) => event.lengthComputable && onSent(event.loaded / event.total);
    request.onload = () => {
      if (request.status < 200 || request.status >= 300) return reject(new ApiError(request.status, codeOf(request.responseText)));
      try {
        resolve(JSON.parse(request.responseText) as T);
      } catch {
        reject(new ApiError(request.status, null));
      }
    };
    request.onerror = () => reject(new TypeError("Catalog svarade inte"));
    request.send(file);
  });
}

export type Filters = { q?: string; kinds?: VehicleKind[]; state?: VehicleState | null; place?: string };

function query(filters: Filters): string {
  const params = new URLSearchParams();
  if (filters.q?.trim()) params.set("q", filters.q.trim());
  for (const kind of filters.kinds ?? []) params.append("kind", kind);
  if (filters.state) params.set("state", filters.state);
  if (filters.place) params.set("place", filters.place);
  const text = params.toString();
  return text ? `?${text}` : "";
}

const V = "/api/catalog/1/vehicles";
const P = "/api/catalog/1/places";
const M = "/api/catalog/1/meets";
const R = "/api/catalog/1/readings";
const F = "/api/catalog/1/prototypes";
const B = "/api/catalog/1/batches";

/** The fleet the person works in: null for their own, otherwise the owner's id (CAT-50, #49). */
let working: string | null = null;
export function workIn(owner: string | null): void {
  working = owner;
}
/** A fleet address, in the fleet the person works in unless another is named. */
function inFleet(path: string, fleet: string | null = working): string {
  if (fleet === null) return path;
  return `${path}${path.includes("?") ? "&" : "?"}fleet=${encodeURIComponent(fleet)}`;
}
const T = "/api/catalog/1/tags";
const tagPath = (uid: string) => `${T}/${encodeURIComponent(uid)}`;
const picturesPath = (vehicle: string) => `${V}/${vehicle}/pictures`;

/** Where a new picture is sent, with Spara original and the background chosen (CAT-17, CAT-128). */
export function uploadAddress(vehicle: string, keepOriginal: boolean, background: PictureBackground): string {
  return inFleet(`${picturesPath(vehicle)}?${new URLSearchParams({ keep_original: String(keepOriginal), background })}`);
}

/** TrainMeet ID's login: the browser goes there itself, and comes back to `next` (#66). */
export function idLoginHref(next: string, language: string): string {
  return `/api/catalog/1/id/login?${new URLSearchParams({ next, lang: language })}`;
}

export const api = {
  version: () => call<CatalogVersion>("GET", "/api/version"),
  session: () => call<Session>("GET", "/api/catalog/1/session"),
  fleets: () => call<FleetChoice[]>("GET", "/api/catalog/1/fleets"),
  logOut: () => call<Session>("DELETE", "/api/catalog/1/session"),
  trialAccounts: () => call<Account[]>("GET", "/api/catalog/1/trial/accounts"),
  trialLogIn: (login: TrialLogin) => call<Session>("POST", "/api/catalog/1/trial/login", login),
  vehicles: (filters: Filters = {}) => call<VehicleList>("GET", inFleet(V + query(filters))),
  vehicle: (id: string) => call<Vehicle>("GET", inFleet(`${V}/${id}`)),
  /** A new vehicle goes in the fleet the person works in, or in their own (CAT-50). With the
   * reading its form was filled in from, a value kept as the AI suggested it gets the source ai. */
  addVehicle: (fields: VehicleFields, own = false, reading: string | null = null) =>
    call<Vehicle>("POST", own ? V : inFleet(V), { ...fields, reading } satisfies NewVehicle),
  changeVehicle: (id: string, change: VehicleChange) => call<Vehicle>("PUT", inFleet(`${V}/${id}`), change),
  removeVehicle: (id: string, version: number) => call<{ id: string }>("DELETE", inFleet(`${V}/${id}?version=${version}`)),
  move: (vehicles: string[], place: string | null) => call<VehicleList>("POST", inFleet(`${V}/move`), { vehicles, place }),
  lend: (id: string, lend: Lend) => call<Vehicle>("POST", inFleet(`${V}/${id}/lend`), lend),
  giveBack: (id: string, version: number) => call<Vehicle>("POST", inFleet(`${V}/${id}/return`), { version }),
  events: (id: string) => call<VehicleEvent[]>("GET", inFleet(`${V}/${id}/events`)),
  places: () => call<Place[]>("GET", inFleet(P)),
  addPlace: (name: string) => call<Place>("POST", inFleet(P), { name }),
  renamePlace: (id: string, name: string) => call<Place>("PUT", inFleet(`${P}/${id}`), { name }),
  removePlace: (id: string) => call<{ id: string }>("DELETE", inFleet(`${P}/${id}`)),
  lookup: (uid: string) => call<Lookup>("GET", tagPath(uid)),
  link: (uid: string, link: TagLink) => call<Vehicle>("POST", inFleet(`${tagPath(uid)}/link`), link),
  unlink: (vehicle: string, assignment: string) => call<Vehicle>("POST", inFleet(`${V}/${vehicle}/tags/unlink`), { assignment, confirm: true }),
  newLabel: (vehicle: string, replace: string | null) => call<Vehicle>("POST", inFleet(`${V}/${vehicle}/tags/qr`), { replace }),
  newSimulated: () => call<Tag>("POST", inFleet(`${T}/simulated`)),
  tagEvents: (uid: string) => call<TagEvent[]>("GET", inFleet(`${tagPath(uid)}/events`)),
  pending: (fleet: string | null = working) => call<PendingState>("GET", inFleet(`${T}/pending`, fleet)),
  waitForTag: (vehicle: string, replace: string | null) => call<PendingState>("POST", inFleet(`${T}/pending`), { vehicle, replace }),
  stopWaiting: () => call<PendingState>("DELETE", inFleet(`${T}/pending`)),
  tell: (uid: string, text: string) => call<{ told: true }>("POST", `${tagPath(uid)}/notice`, { text }),
  clearNotice: (vehicle: string, notice: string) => call<{ id: string }>("DELETE", inFleet(`${V}/${vehicle}/notices/${notice}`)),
  settings: () => call<{ show_name: boolean }>("GET", "/api/catalog/1/settings"),
  changeSettings: (show_name: boolean) => call<{ show_name: boolean }>("PUT", "/api/catalog/1/settings", { show_name }),
  /** The vehicle's pictures in order (CAT-05). The addresses expire (CAT-130): read them again after a change. */
  pictures: (vehicle: string) => call<Picture[]>("GET", inFleet(picturesPath(vehicle))),
  addPicture: (vehicle: string, file: Blob, keepOriginal: boolean, background: PictureBackground, onSent?: (part: number) => void) =>
    send<Picture>(uploadAddress(vehicle, keepOriginal, background), file, onSent),
  mainPicture: (vehicle: string, picture: string) => call<Picture[]>("POST", inFleet(`${picturesPath(vehicle)}/${picture}/main`)),
  pictureBackground: (vehicle: string, picture: string, background: PictureBackground) =>
    call<Picture>("POST", inFleet(`${picturesPath(vehicle)}/${picture}/background`), { background } satisfies BackgroundChange),
  removePicture: (vehicle: string, picture: string) => call<{ id: string }>("DELETE", inFleet(`${picturesPath(vehicle)}/${picture}`)),
  /** The fleet owner's storage, also in someone else's fleet (CAT-131, CAT-133). */
  storage: () => call<StorageUse>("GET", inFleet("/api/catalog/1/storage")),
  /** The meets, the owner's own: the active ones first (CAT-174, CAT-183). */
  trips: () => call<TripSummary[]>("GET", inFleet(M)),
  trip: (id: string) => call<Trip>("GET", inFleet(`${M}/${id}`)),
  newTrip: (body: NewTrip) => call<Trip>("POST", inFleet(M), body),
  /** The whole pack list (CAT-175). */
  packList: (id: string, vehicles: string[]) => call<Trip>("POST", inFleet(`${M}/${id}/vehicles`), { vehicles }),
  /** A press on the row: tick, or take the tick away (CAT-176). */
  tick: (id: string, vehicle: string, step: TripStep, ticked: boolean) => call<Trip>("POST", inFleet(`${M}/${id}/ticks`), { vehicle, step, ticked }),
  /** A tag tapped in the step; with add, the vehicle goes on the list first (CAT-181). */
  tapInTrip: (id: string, uid: string, step: TripStep, add = false) => call<TripTapped>("POST", inFleet(`${M}/${id}/tap`), { uid, step, add }),
  archiveTrip: (id: string) => call<Trip>("POST", inFleet(`${M}/${id}/archive`)),
  /** What a reading sends and to whom, the price and the balance (CAT-142, CAT-19). */
  readingConsent: () => call<ReadingConsent>("GET", inFleet(`${R}/consent`)),
  /** The AI's suggestions from the photos. The same id and photos again give the same reading,
   * without reading or drawing again (CAT-144). Nothing is saved in a vehicle (CAT-143). */
  read: (ask: ReadingAsk, photos: Blob[]) => call<Reading>("POST", inFleet(R), readingForm(ask, photos)),
  /** The field register and the profiles (CAT-156, CAT-158). */
  fieldRegister: () => call<FieldRegister>("GET", `${F}/fields`),
  /** The catalog: reviewed prototypes, and the person's own proposals for new ones (CAT-173). */
  prototypes: (q = "", kinds: VehicleKind[] = []) => call<PrototypeList>("GET", F + query({ q, kinds })),
  prototype: (id: string) => call<Prototype>("GET", `${F}/${id}`),
  propose: (proposal: PrototypeProposal) => call<PrototypeRevision>("POST", `${F}/proposals`, proposal),
  myProposals: () => call<PrototypeRevision[]>("GET", `${F}/proposals/mine`),
  /** Granskningskön, only for the reviewers TrainMeet ID names (CAT-165). */
  reviewQueue: () => call<PrototypeRevision[]>("GET", `${F}/proposals/queue`),
  review: (revision: string, review: PrototypeReview) => call<PrototypeRevision>("POST", `${F}/proposals/${revision}/review`, review),
  /** Koppla förebild, or Uppdatera to a newer revision (CAT-160, CAT-161). */
  linkPrototype: (vehicle: string, link: PrototypeLink) => call<Vehicle>("POST", inFleet(`${V}/${vehicle}/prototype`), link),
  /** The type data as the owner wants them on the vehicle: equal values inherit (CAT-162). */
  changeTypeData: (vehicle: string, version: number, fields: TypeData) => call<Vehicle>("PUT", inFleet(`${V}/${vehicle}/prototype`), { version, fields }),
  unlinkPrototype: (vehicle: string, version: number) => call<Vehicle>("DELETE", inFleet(`${V}/${vehicle}/prototype?version=${version}`)),
  /** The batches with photos still to approve: someone who edits sees only their own (CAT-153). */
  batches: () => call<BatchSummary[]>("GET", inFleet(B)),
  batch: (id: string) => call<Batch>("GET", inFleet(`${B}/${id}`)),
  /** Photos for the batch with the client's id: a new batch, or more for the same (CAT-147, CAT-149). */
  addBatchPhotos: (ask: BatchAsk, photos: Blob[]) => call<Batch>("POST", inFleet(B), batchForm(ask, photos)),
  removeBatch: (id: string) => call<{ id: string }>("DELETE", inFleet(`${B}/${id}`)),
  changeCard: (batch: string, card: string, change: BatchCardChange) => call<BatchCard>("POST", inFleet(`${B}/${batch}/cards/${card}`), change),
  removeCard: (batch: string, card: string) => call<{ id: string }>("DELETE", inFleet(`${B}/${batch}/cards/${card}`)),
  /** A photo that failed, or was left when the tokens ran out, in the queue again (CAT-151, CAT-152). */
  retryCard: (batch: string, card: string) => call<BatchCard>("POST", inFleet(`${B}/${batch}/cards/${card}/retry`)),
  /** Godkänn alla: every open card as it was seen, or none (CAT-150). */
  approveBatch: (batch: string, approval: BatchApproval) => call<Batch>("POST", inFleet(`${B}/${batch}/approve`), approval),
};

export const qrAddress = (uid: string) => inFleet(`${tagPath(uid)}/qr.svg`);

/** The fields a change carries: everything the owner writes, from a vehicle as it was read. */
export function fieldsOf(vehicle: Vehicle): VehicleFields {
  return {
    status: vehicle.status,
    kind: vehicle.kind ?? null,
    litt: vehicle.litt ?? "",
    number: vehicle.number ?? "",
    operator: vehicle.operator ?? "",
    epoch: vehicle.epoch ?? "",
    scale: vehicle.scale ?? "",
    maker: vehicle.maker ?? "",
    article_number: vehicle.article_number ?? "",
    note: vehicle.note ?? "",
    dcc_address: vehicle.dcc_address ?? "",
    functions: vehicle.functions ?? [],
    place: vehicle.place ?? null,
  };
}

/** Ready needs a kind and a litt or number (CAT-62); otherwise the vehicle is a draft. */
export function statusFor(fields: VehicleFields): "draft" | "ready" {
  return fields.kind && ((fields.litt ?? "").trim() || (fields.number ?? "").trim()) ? "ready" : "draft";
}
