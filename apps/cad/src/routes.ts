// CAD's pages as addresses of their own, all served index.html by cad/app.py.

export type Tab = "oversikt" | "ritning" | "foto" | "landskap" | "historik";
export type FormKind = "straight" | "curve" | "trapezoid";
/** Foto och kontroll, Längden ur fotot and Osäkert parti. */
export type PhotoView = "kontroll" | "langd" | "osakert";

export type Route =
  | { page: "library" }
  | { page: "new" }
  | { page: "form"; kind: FormKind; id?: string }
  | { page: "upload" }
  | { page: "sketch" }
  | { page: "module"; id: string; tab: Tab; version?: number }
  | { page: "drawing"; id: string }
  | { page: "lock"; id: string }
  | { page: "photo"; id: string; job: string; view: PhotoView; question?: string }
  | { page: "assemblies" }
  | { page: "profiles" }
  | { page: "login" }
  | { page: "missing" };

export const PATHS = {
  library: "/moduler",
  new: "/moduler/ny",
  assemblies: "/anlaggningar",
  profiles: "/gavelprofiler",
  login: "/logga-in",
} as const;

const FORM_PATHS: Record<FormKind, string> = { straight: "rak", curve: "kurva", trapezoid: "trapets" };
const TABS: Tab[] = ["oversikt", "ritning", "foto", "landskap", "historik"];
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

/** Ny modul ur ett foto. */
export const UPLOAD_PATH = `${PATHS.new}/foto`;
/** Ny modul ur en skiss (part c2). */
export const SKETCH_PATH = `${PATHS.new}/skiss`;

export function formPath(kind: FormKind): string {
  return `${PATHS.new}/${FORM_PATHS[kind]}`;
}

export function modulePath(id: string, tab: Tab = "oversikt", version?: number): string {
  const base = tab === "oversikt" ? `${PATHS.library}/${id}` : `${PATHS.library}/${id}/${tab}`;
  return version ? `${base}?version=${version}` : base;
}

/** Ritningen, for those who may change the module. */
export function drawingPath(id: string): string {
  return `${PATHS.library}/${id}/ritningen`;
}

/** Lås mått, from Ritningen. */
export function lockPath(id: string): string {
  return `${drawingPath(id)}/las-matt`;
}

/** Foto och kontroll for a photo job, or its Längden ur fotot or Osäkert parti. */
export function photoPath(id: string, job: string, view: PhotoView = "kontroll", question?: string): string {
  const base = `${PATHS.library}/${id}/foto/${job}`;
  const path = view === "kontroll" ? base : `${base}/${view}`;
  return question ? `${path}?fraga=${encodeURIComponent(question)}` : path;
}

export function editPath(id: string): string {
  return `${PATHS.library}/${id}/andra`;
}

export function routeFor(pathname: string, search = ""): Route {
  const path = pathname.replace(/\/+$/, "") || "/";
  if (path === "/" || path === PATHS.library) return { page: "library" };
  if (path === PATHS.new) return { page: "new" };
  if (path === PATHS.assemblies) return { page: "assemblies" };
  if (path === PATHS.profiles) return { page: "profiles" };
  if (path === PATHS.login) return { page: "login" };
  const parts = path.split("/").slice(1);
  if (path === UPLOAD_PATH) return { page: "upload" };
  if (path === SKETCH_PATH) return { page: "sketch" };
  if (parts[0] === "moduler" && parts[1] === "ny" && parts.length === 3) {
    const kind = (Object.keys(FORM_PATHS) as FormKind[]).find((k) => FORM_PATHS[k] === parts[2]);
    if (kind) return { page: "form", kind };
  }
  if (parts[0] === "moduler" && parts[1] && UUID.test(parts[1])) {
    const id = parts[1];
    if (parts.length === 2) return withVersion({ page: "module", id, tab: "oversikt" }, search);
    if (parts.length === 3 && parts[2] === "andra") return { page: "form", kind: "straight", id };
    if (parts.length === 3 && parts[2] === "ritningen") return { page: "drawing", id };
    if (parts.length === 4 && parts[2] === "ritningen" && parts[3] === "las-matt") return { page: "lock", id };
    if (parts[2] === "foto" && parts[3] && UUID.test(parts[3]) && parts.length <= 5) {
      const view = (parts[4] ?? "kontroll") as PhotoView;
      if (["kontroll", "langd", "osakert"].includes(view)) {
        const question = new URLSearchParams(search).get("fraga") ?? undefined;
        return question ? { page: "photo", id, job: parts[3], view, question } : { page: "photo", id, job: parts[3], view };
      }
    }
    const tab = TABS.find((t) => t === parts[2]);
    if (parts.length === 3 && tab) return withVersion({ page: "module", id, tab }, search);
  }
  return { page: "missing" };
}

function withVersion(route: Extract<Route, { page: "module" }>, search: string): Route {
  const version = Number(new URLSearchParams(search).get("version"));
  return Number.isInteger(version) && version > 0 ? { ...route, version } : route;
}

/** The header's tab a page belongs to. */
export function tabOf(route: Route): "library" | "assemblies" | "profiles" | null {
  if (route.page === "assemblies") return "assemblies";
  if (route.page === "profiles") return "profiles";
  if (["library", "new", "form", "upload", "sketch", "module", "drawing", "lock", "photo"].includes(route.page)) return "library";
  return null;
}
