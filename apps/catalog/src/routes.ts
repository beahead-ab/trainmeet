// The pages are addresses of their own, so a link or the home screen opens the right page.
// The server gives index.html for each of them (catalog/app.py).

export type Page =
  | "vehicles"
  | "newVehicle"
  | "newPhoto"
  | "newBatch"
  | "batch"
  | "vehicle"
  | "editVehicle"
  | "lend"
  | "places"
  | "meets"
  | "meet"
  | "prototypes"
  | "prototype"
  | "newPrototype"
  | "changePrototype"
  | "reviewQueue"
  | "tap"
  | "login"
  | "help"
  | "tag"
  | "missing";

export type Route = { page: Page; id?: string };

export const PATHS = {
  vehicles: "/fordon",
  newVehicle: "/fordon/nytt",
  /** Lägg till med foto: fota, AI:n föreslår, granska, plats och tagg (CAT-134). */
  newPhoto: "/fordon/nytt/foto",
  /** Lägg till flera: up to 30 photos in a batch, one per vehicle (CAT-147). */
  newBatch: "/fordon/nytt/flera",
  places: "/platser",
  meets: "/traffar",
  prototypes: "/forebilder",
  /** Föreslå förebild (CAT-163). */
  newPrototype: "/forebilder/ny",
  /** Granskningskön, for the reviewers (CAT-164). */
  reviewQueue: "/forebilder/granska",
  tap: "/blippa",
  login: "/logga-in",
  help: "/hjalp",
} as const;

export const vehiclePath = (id: string) => `/fordon/${id}`;
export const editPath = (id: string) => `/fordon/${id}/andra`;
export const lendPath = (id: string) => `/fordon/${id}/lana-ut`;
export const tagPagePath = (uid: string) => `/t/${encodeURIComponent(uid)}`;
export const meetPath = (id: string) => `/traffar/${id}`;
export const prototypePath = (id: string) => `/forebilder/${id}`;
/** Föreslå ändring of a reviewed prototype (CAT-163). */
export const changePrototypePath = (id: string) => `/forebilder/${id}/andra`;
/** A batch of photos and its drafts (CAT-147–CAT-153). */
export const batchPath = (id: string) => `/fordon/omgangar/${id}`;

const UUID = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}";
const PATTERNS: [RegExp, Page][] = [
  [new RegExp(`^/fordon/(${UUID})$`), "vehicle"],
  [new RegExp(`^/fordon/(${UUID})/andra$`), "editVehicle"],
  [new RegExp(`^/fordon/(${UUID})/lana-ut$`), "lend"],
  [new RegExp(`^/traffar/(${UUID})$`), "meet"],
  [new RegExp(`^/forebilder/(${UUID})$`), "prototype"],
  [new RegExp(`^/forebilder/(${UUID})/andra$`), "changePrototype"],
  [new RegExp(`^/fordon/omgangar/(${UUID})$`), "batch"],
  [/^\/t\/([^/]{1,80})$/, "tag"],
];

/** The page for an address. The start page is Fordon (CAT-202). */
export function routeFor(address: string): Route {
  let path = address.split(/[?#]/)[0]!.replace(/\/+$/, "") || "/";
  try {
    path = decodeURIComponent(path);
  } catch {
    // A broken address is simply a page that does not exist.
  }
  path = path.toLowerCase();
  if (path === "/") return { page: "vehicles" };
  const fixed = (Object.entries(PATHS) as [Page, string][]).find(([, address]) => address === path);
  if (fixed) return { page: fixed[0] };
  for (const [pattern, page] of PATTERNS) {
    const match = pattern.exec(path);
    if (match) return { page, id: match[1] };
  }
  return { page: "missing" };
}

/** Which tab a page belongs to. */
export function tabOf(page: Page): Page {
  if (page === "tag") return "tap";
  if (page === "meet") return "meets";
  if (["prototype", "newPrototype", "changePrototype", "reviewQueue"].includes(page)) return "prototypes";
  return ["newVehicle", "newPhoto", "newBatch", "batch", "vehicle", "editVehicle", "lend", "places"].includes(page) ? "vehicles" : page;
}

/** Where to go after logging in: the address one came from, when it is one of Catalog's own
 * pages, so a tag opened while logged out opens again (CAT-103). */
export function nextAfterLogin(search: string): string {
  const next = new URLSearchParams(search).get("next") ?? "";
  return next.startsWith("/") && !next.startsWith("//") && routeFor(next).page !== "missing" ? next : PATHS.vehicles;
}

/** The uid in a tag's address, or what was typed if it is not an address. */
export function uidFrom(text: string): string {
  const trimmed = text.trim();
  const at = trimmed.lastIndexOf("/t/");
  return (at >= 0 ? trimmed.slice(at + 3) : trimmed).replace(/\/+$/, "");
}
