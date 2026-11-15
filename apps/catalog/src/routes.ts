// The pages are addresses of their own, so a link or the home screen opens the right page.
// The server gives index.html for each of them (catalog/app.py).

export type Page =
  | "vehicles"
  | "newVehicle"
  | "vehicle"
  | "editVehicle"
  | "lend"
  | "places"
  | "meets"
  | "prototypes"
  | "tap"
  | "login"
  | "help"
  | "missing";

export type Route = { page: Page; id?: string };

export const PATHS = {
  vehicles: "/fordon",
  newVehicle: "/fordon/nytt",
  places: "/platser",
  meets: "/traffar",
  prototypes: "/forebilder",
  tap: "/blippa",
  login: "/logga-in",
  help: "/hjalp",
} as const;

export const vehiclePath = (id: string) => `/fordon/${id}`;
export const editPath = (id: string) => `/fordon/${id}/andra`;
export const lendPath = (id: string) => `/fordon/${id}/lana-ut`;

const UUID = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}";
const PATTERNS: [RegExp, Page][] = [
  [new RegExp(`^/fordon/(${UUID})$`), "vehicle"],
  [new RegExp(`^/fordon/(${UUID})/andra$`), "editVehicle"],
  [new RegExp(`^/fordon/(${UUID})/lana-ut$`), "lend"],
];

/** The page for an address. The start page is Fordon (CAT-202). */
export function routeFor(pathname: string): Route {
  const path = pathname.replace(/\/+$/, "").toLowerCase() || "/";
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
  return ["newVehicle", "vehicle", "editVehicle", "lend", "places"].includes(page) ? "vehicles" : page;
}
