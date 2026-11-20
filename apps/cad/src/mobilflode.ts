// CAD i mobilen (#90): the phone's flow as pure functions, so the tests can run it. The phone keeps
// no data of its own (CADMOB-05): the measures and the gables become the same NewModule and
// ModuleChange as the web's forms, the photo the same PhotoStart as Ladda upp foto, and the
// answers the same calls.
import type {
  CheckItem,
  EditOp,
  GableProfile,
  MobileFlow,
  MobileStep,
  Module,
  ModuleChange,
  NewModule,
  PhotoJob,
  PhotoQuestion,
  PhotoStart,
  Scale,
  Shape,
} from "./api";
import { fromChord, type Bend } from "./geometry";
import { gableFor, tracksOf, type GableState } from "./ModuleForm";
import { mobilePath, type MobileRoute } from "./routes";

/** 1 Mått, 1b Kurva and 2 Gavlar before the module exists: in sessionStorage, so that a reload
 * at the module keeps them, and never sent anywhere until Nästa. */
export type Draft = {
  /** Fota modulen, or Bara mått nu. */
  mode: "foto" | "matt";
  name: string;
  scale: Scale;
  kind: "straight" | "curve";
  length: string;
  width: string;
  chord: string;
  sagitta: string;
  edge: "outer" | "inner";
  a: GableState;
  b: GableState;
  sameB: boolean;
};

export const NEW_GABLE: GableState = { profile: "", norm: "", steps: [""] };

export const EMPTY_DRAFT: Draft = {
  mode: "foto",
  name: "",
  scale: "H0",
  kind: "straight",
  length: "",
  width: "",
  chord: "",
  sagitta: "",
  edge: "outer",
  a: NEW_GABLE,
  b: NEW_GABLE,
  sameB: true,
};

export const num = (text: string) => (text.trim() === "" ? NaN : Number(text.replace(",", ".")));

/** The curve from the string and the sagitta, exact (CAD16). */
export function bendOf(draft: Draft): Bend | null {
  return fromChord(num(draft.chord), num(draft.sagitta));
}

/** May 1 Mått go on? The length may be empty when the photo gives it (CADMOB-02). */
export function measuresReady(draft: Draft): boolean {
  if (!draft.name.trim() || !(num(draft.width) > 0)) return false;
  if (draft.kind === "curve") return bendOf(draft) !== null;
  const length = draft.length.trim();
  if (!length) return draft.mode === "foto";
  return num(length) > 0;
}

export function gableB(draft: Draft): GableState {
  return draft.sameB ? draft.a : draft.b;
}

export function gablesReady(draft: Draft): boolean {
  return tracksOf(draft.a) !== null && tracksOf(gableB(draft)) !== null;
}

/** A profile chosen for a gable, as the web's form does it. */
export function withProfile(gable: GableState, profile: GableProfile | undefined, width: number): GableState {
  return gableFor(profile, gable.steps, width);
}

function gableBody(end: "A" | "B", gable: GableState): NewModule["gables"][number] {
  return {
    end,
    profile: gable.profile || null,
    norm: (gable.norm || null) as NewModule["gables"][number]["norm"],
    tracks: tracksOf(gable) ?? [],
  };
}

export function gablesOf(draft: Draft): NewModule["gables"] {
  return [gableBody("A", draft.a), gableBody("B", gableB(draft))];
}

/** The module's form, or null while the measures do not give one; a straight module without its
 * length has none until the photo. */
export function shapeOf(draft: Draft): Shape | null {
  const width = num(draft.width);
  if (!(width > 0)) return null;
  if (draft.kind === "curve") {
    const bend = bendOf(draft);
    if (!bend) return null;
    return {
      kind: "curve",
      radius: bend.radius,
      angle: bend.angle,
      width,
      edge: draft.edge,
      sides: "bent",
      measured: { chord: num(draft.chord), sagitta: num(draft.sagitta) },
    };
  }
  const length = num(draft.length);
  return length > 0 ? { kind: "straight", length, width } : null;
}

/** The module made before the photo, with its gables, so that the photo is read against them and
 * Kant 1 and gable A can be derived from an asymmetric profile (bildkedjan step 13). */
export function newModuleOf(draft: Draft): NewModule | null {
  const shape = shapeOf(draft);
  if (!shape || !gablesReady(draft)) return null;
  return { name: draft.name.trim(), scale: draft.scale, shape, gables: gablesOf(draft), owner: null, visibility: "me", club: null };
}

/** Without the length the photo makes the module, as Ladda upp foto does, and gives the length. */
export function photoFirst(draft: Draft): boolean {
  return draft.mode === "foto" && draft.kind === "straight" && !draft.length.trim();
}

const NO_START: PhotoStart = {
  module: null,
  scale: "H0",
  kind: "straight",
  profile: "modulfoto",
  name: null,
  width: null,
  width_b: null,
  length: null,
  offset: null,
  chord: null,
  sagitta: null,
  track1: null,
  edge: "outer",
  keep_original: false,
  owner: null,
};

/** The photo for a new module from its measures; the length from the photo. */
export function photoStartOf(draft: Draft): PhotoStart {
  return { ...NO_START, name: draft.name.trim(), scale: draft.scale, kind: "straight", width: num(draft.width) };
}

/** The photo for a module that exists. */
export function photoStartFor(module: Module): PhotoStart {
  return { ...NO_START, module: module.id, scale: module.scale, kind: module.shape.kind };
}

/** A sketch, Fota en skiss: as Från en skiss on the web. */
export function sketchStart(start: PhotoStart): PhotoStart {
  return { ...start, profile: "skiss" };
}

/** The gables from 2 Gavlar on the module the photo made. */
export function withGables(module: Module, draft: Draft): ModuleChange {
  return { base: module.latest, name: module.name, scale: module.scale, shape: module.shape, gables: gablesOf(draft) };
}

/** Använd: the photo's value for the length or a gable's track, or one measured again (Mät om), as
 * a new version of the measures; the same as the web's Använd. */
export function measureChange(
  module: Module,
  job: PhotoJob | null,
  measure: { gable?: "A" | "B"; track?: number; length?: number; value?: number },
): ModuleChange | null {
  if (module.shape.kind === "curve") return null;
  const shape = { ...module.shape };
  if (measure.length != null) shape.length = Math.round(measure.length * 2) / 2;
  const gables = module.gables.map((g) => {
    const photo = (job?.measures ?? []).find((m) => m.gable === g.end && m.track === measure.track)?.photo;
    const value = measure.gable === g.end && measure.track ? (measure.value ?? photo) : undefined;
    const tracks = g.tracks.map((t, i) => (value != null && i === (measure.track ?? 0) - 1 ? Math.round(value * 2) / 2 : t));
    // A gable whose track is moved is no longer the profile's.
    return { end: g.end, norm: g.norm ?? null, profile: value != null ? null : (g.profile ?? null), tracks };
  });
  return { base: module.latest, name: module.name, scale: module.scale, shape, gables };
}

/** The AI's or the code's open questions that change the track plan: 4b AI:n frågar. */
export function openTopology(job: PhotoJob): PhotoQuestion[] {
  return (job.questions ?? []).filter((q) => q.topology && !q.answer);
}

/** Att kolla the phone can answer: a closing choice that needs no tool of Ritningen's. */
export function phoneChoices(item: CheckItem): CheckItem["choices"] {
  return item.choices.filter((c) => c.closes !== false && !c.action);
}

/** The module's open Att kolla, apart from the photo's own questions (answered in 4b). */
export function openChecks(module: Module): CheckItem[] {
  return (module.checks ?? []).filter((item) => !item.answer && !item.choices.some((c) => c.action === "photo"));
}

/** Godkänn spårplanen with the answers given on the phone, in the same call as the web's. */
export function answerOps(answers: Record<string, string>): EditOp[] {
  return Object.entries(answers).map(([key, answer]) => ({ op: "answer", key, answer }));
}

/** The step the computer is told about for a page (CADMOB-01). */
export function stepOf(route: MobileRoute): MobileStep {
  switch (route.page) {
    case "matt":
      return "matt";
    case "gavlar":
      return "gavlar";
    case "skiss":
    case "fota":
    case "horn":
      return "fota";
    case "kontroll":
      return "kontroll";
    case "fraga":
      return "fraga";
    case "klar":
      return "klar";
    default:
      return "start";
  }
}

/** Where a phone that comes back (a reload, or the code given) goes on. */
export function resumePath(flow: MobileFlow): string {
  const module = flow.module ?? flow.bound ?? undefined;
  const job = flow.job ?? undefined;
  if (flow.step === "klar" && module) return mobilePath("klar", module, job);
  if (module && job && (flow.step === "kontroll" || flow.step === "fraga")) return mobilePath("kontroll", module, job);
  if (module && job && flow.step === "fota") return mobilePath("horn", module, job);
  if (module && (flow.bound || flow.step === "fota")) return mobilePath("fota", module);
  if (flow.step === "matt" || flow.step === "gavlar") return mobilePath(flow.step);
  return mobilePath("start");
}

/** "nära gavel A" or "nära gavel B": where an uncertain part lies along the module. */
export function nearGable(module: Module, at: [number, number]): "A" | "B" {
  if (module.shape.kind === "curve") return at[0] <= 0 ? "A" : "B";
  return at[0] <= module.shape.length / 2 ? "A" : "B";
}
