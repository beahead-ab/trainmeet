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

export const KINDS: VehicleKind[] = ["locomotive", "freight_wagon", "passenger_coach", "multiple_unit", "other"];
export const STATES: VehicleState[] = ["home", "packed", "at_meet", "lent"];
export const ENGINES: VehicleKind[] = ["locomotive", "multiple_unit"];
/** The backgrounds a picture can have, original first (CAT-128). */
export const BACKGROUNDS: PictureBackground[] = ["original", "white", "grey", "transparent", "rails"];
/** What an upload may be (CAT-123). HEIC from an iPhone is sent as JPEG by the browser. */
export const PICTURE_KINDS = ["image/jpeg", "image/png", "image/webp"] as const;
/** As in catalog/pictures.py: 10 pictures per vehicle (CAT-17), at most 15 MB each (CAT-123). */
export const PICTURES_PER_VEHICLE = 10;
export const PICTURE_MAX_BYTES = 15 * 1024 * 1024;

/** Catalog said no, with a code the web app has a text for, or something else went wrong. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: ProblemCode | null,
  ) {
    super(`Catalog svarade ${status}${code ? ` (${code})` : ""}`);
  }
}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method, credentials: "same-origin", headers: { Accept: "application/json" } };
  if (body !== undefined) {
    init.headers = { ...init.headers, "Content-Type": "application/json" };
    init.body = JSON.stringify(body);
  }
  const response = await fetch(path, init);
  if (!response.ok) throw new ApiError(response.status, codeOf(await response.text().catch(() => "")));
  return (await response.json()) as T;
}

/** The code in Catalog's answer when it said no, if it is one. */
function codeOf(body: string): ProblemCode | null {
  try {
    const problem = JSON.parse(body) as Partial<Problem> | null;
    return typeof problem?.code === "string" ? problem.code : null;
  } catch {
    return null;
  }
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
  /** A new vehicle goes in the fleet the person works in, or in their own (CAT-50). */
  addVehicle: (fields: VehicleFields, own = false) => call<Vehicle>("POST", own ? V : inFleet(V), fields),
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
