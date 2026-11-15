// The pages are addresses of their own, so a link or the home screen opens the right page.
// The server gives index.html for each of them (catalog/app.py).

export type Page = "vehicles" | "meets" | "prototypes" | "tap" | "login" | "help" | "missing";

export const PATHS: Record<Exclude<Page, "missing">, string> = {
  vehicles: "/fordon",
  meets: "/traffar",
  prototypes: "/forebilder",
  tap: "/blippa",
  login: "/logga-in",
  help: "/hjalp",
};

/** The page for an address. The start page is Fordon (CAT-202). */
export function pageFor(pathname: string): Page {
  const path = pathname.replace(/\/+$/, "").toLowerCase() || "/";
  if (path === "/") return "vehicles";
  const found = (Object.entries(PATHS) as [Exclude<Page, "missing">, string][]).find(
    ([, address]) => address === path,
  );
  return found ? found[0] : "missing";
}
