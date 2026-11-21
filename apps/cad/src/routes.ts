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
  | { page: "anyrail"; id?: string }
  | { page: "module"; id: string; tab: Tab; version?: number }
  | { page: "drawing"; id: string }
  | { page: "lock"; id: string }
  | { page: "photo"; id: string; job: string; view: PhotoView; question?: string }
  | { page: "export"; id: string; version?: number }
  | { page: "assemblies" }
  | { page: "assembly"; id: string }
  | { page: "studio"; id: string }
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
/** Import från AnyRail (#91): the upload, and an import's page. */
export const ANYRAIL_PATH = `${PATHS.new}/anyrail`;

export function anyrailPath(id?: string): string {
  return id ? `${ANYRAIL_PATH}/${id}` : ANYRAIL_PATH;
}

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

/** Exportera (part d1): the approved version, or the one asked for. */
export function exportPath(id: string, version?: number): string {
  return `${PATHS.library}/${id}/exportera${version ? `?version=${version}` : ""}`;
}

/** An assembly's page (part d2). */
export function assemblyPath(id: string): string {
  return `${PATHS.assemblies}/${id}`;
}

/** Till TKL Studio, for an assembly. */
export function studioPath(id: string): string {
  return `${assemblyPath(id)}/studio`;
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
  if (path === ANYRAIL_PATH) return { page: "anyrail" };
  if (parts[0] === "moduler" && parts[1] === "ny" && parts[2] === "anyrail" && parts.length === 4 && parts[3] && UUID.test(parts[3])) {
    return { page: "anyrail", id: parts[3] };
  }
  if (parts[0] === "moduler" && parts[1] === "ny" && parts.length === 3) {
    const kind = (Object.keys(FORM_PATHS) as FormKind[]).find((k) => FORM_PATHS[k] === parts[2]);
    if (kind) return { page: "form", kind };
  }
  if (parts[0] === "anlaggningar" && parts[1] && UUID.test(parts[1])) {
    if (parts.length === 2) return { page: "assembly", id: parts[1] };
    if (parts.length === 3 && parts[2] === "studio") return { page: "studio", id: parts[1] };
  }
  if (parts[0] === "moduler" && parts[1] && UUID.test(parts[1])) {
    const id = parts[1];
    if (parts.length === 2) return withVersion({ page: "module", id, tab: "oversikt" }, search);
    if (parts.length === 3 && parts[2] === "andra") return { page: "form", kind: "straight", id };
    if (parts.length === 3 && parts[2] === "ritningen") return { page: "drawing", id };
    if (parts.length === 3 && parts[2] === "exportera") {
      const version = Number(new URLSearchParams(search).get("version"));
      return Number.isInteger(version) && version > 0 ? { page: "export", id, version } : { page: "export", id };
    }
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
  if (route.page === "assemblies" || route.page === "assembly" || route.page === "studio") return "assemblies";
  if (route.page === "profiles") return "profiles";
  if (["library", "new", "form", "upload", "sketch", "anyrail", "module", "drawing", "lock", "photo", "export"].includes(route.page)) return "library";
  return null;
}

// --- CAD i mobilen (#90): the phone's own pages under /m, opened from the QR code ----------------

/** The phone's pages: 0 Välj väg, 1 Mått (1b Kurva), 2 Gavlar, 3 Fota and its corners, 4 Kontroll,
 * 4b AI:n frågar and 5 Klart (CADMOB-01); entry reads the one-time code from the fragment. */
export type MobilePage = "entry" | "start" | "matt" | "gavlar" | "skiss" | "fota" | "horn" | "kontroll" | "fraga" | "klar";

export type MobileRoute = { page: MobilePage; id?: string; job?: string; question?: string } | { page: "missing" };

export const MOBILE_ROOT = "/m";
const MOBILE_NEW = `${MOBILE_ROOT}/ny`;

/** Is the address one of the phone's? Those pages are an app of their own (Mobil.tsx). */
export function isMobilePath(pathname: string): boolean {
  return pathname === MOBILE_ROOT || pathname.startsWith(`${MOBILE_ROOT}/`);
}

/** A phone page's address: a new module's steps under /m/ny, a module's under /m/<id>. */
export function mobilePath(page: MobilePage, id?: string, job?: string, question?: string): string {
  if (page === "entry") return MOBILE_ROOT;
  if (page === "start") return MOBILE_NEW;
  if (page === "matt" || page === "gavlar" || page === "skiss") return `${MOBILE_NEW}/${page}`;
  const base = id ? `${MOBILE_ROOT}/${id}` : MOBILE_NEW;
  if (page === "fota") return `${base}/foto`;
  if (page === "horn") return `${base}/foto/${job ?? ""}`;
  if (page === "klar") return `${base}/klar${job ? `?jobb=${job}` : ""}`;
  if (page === "kontroll") return `${base}/kontroll/${job ?? ""}`;
  return `${base}/fraga/${job ?? ""}${question ? `?fraga=${encodeURIComponent(question)}` : ""}`;
}

export function mobileRouteFor(pathname: string, search = ""): MobileRoute {
  const path = pathname.replace(/\/+$/, "") || "/";
  const query = new URLSearchParams(search);
  if (path === MOBILE_ROOT) return { page: "entry" };
  if (path === MOBILE_NEW) return { page: "start" };
  const parts = path.split("/").slice(2);
  if (parts[0] === "ny") {
    if (parts.length === 2 && (parts[1] === "matt" || parts[1] === "gavlar" || parts[1] === "skiss")) return { page: parts[1] };
    if (parts.length === 2 && parts[1] === "foto") return { page: "fota" };
    return { page: "missing" };
  }
  const id = parts[0];
  if (!id || !UUID.test(id)) return { page: "missing" };
  if (parts.length === 2 && parts[1] === "foto") return { page: "fota", id };
  if (parts.length === 2 && parts[1] === "klar") {
    const job = query.get("jobb");
    return job && UUID.test(job) ? { page: "klar", id, job } : { page: "klar", id };
  }
  const job = parts[2];
  if (parts.length !== 3 || !job || !UUID.test(job)) return { page: "missing" };
  if (parts[1] === "foto") return { page: "horn", id, job };
  if (parts[1] === "kontroll") return { page: "kontroll", id, job };
  if (parts[1] === "fraga") {
    const question = query.get("fraga");
    return question ? { page: "fraga", id, job, question } : { page: "fraga", id, job };
  }
  return { page: "missing" };
}
