// The pages are addresses of their own, so a link in a mail opens the right page. ID's API
// gives index.html for each of them (id/app.py). The tabs are Konto, Klubbar, Träffar and
// Tokens (KONTO-38).

export type Page = "account" | "clubs" | "club" | "meets" | "meet" | "tokens" | "invitations" | "fleet" | "help" | "remove" | "missing";
export type Route = { page: Page; id?: string };

export const PATHS = {
  account: "/",
  clubs: "/klubbar",
  meets: "/traffar",
  tokens: "/tokens",
  invitations: "/inbjudningar",
  help: "/hjalp",
  remove: "/konto/ta-bort",
} as const;

export const clubPath = (id: string) => `/klubbar/${id}`;
export const fleetPath = (owner: string) => `/vagnparker/${owner}`;
export const meetPath = (id: string) => `/traffar/${id}`;

const UUID = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}";
const PATTERNS: [RegExp, Page][] = [
  [new RegExp(`^/klubbar/(${UUID})$`), "club"],
  [new RegExp(`^/vagnparker/(${UUID})$`), "fleet"],
  [new RegExp(`^/traffar/(${UUID})$`), "meet"],
];

export function routeFor(address: string): Route {
  const path = (address.split(/[?#]/)[0] ?? "/").replace(/\/+$/, "").toLowerCase() || "/";
  const fixed = (Object.entries(PATHS) as [Page, string][]).find(([, p]) => p === path);
  if (fixed) return { page: fixed[0] };
  for (const [pattern, page] of PATTERNS) {
    const match = pattern.exec(path);
    if (match) return { page, id: match[1] };
  }
  return { page: "missing" };
}

/** Which tab a page belongs to. */
export function tabOf(page: Page): Page {
  if (page === "club") return "clubs";
  if (page === "meet") return "meets";
  if (page === "invitations" || page === "fleet" || page === "help" || page === "remove") return "account";
  return page;
}
