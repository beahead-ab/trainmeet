// Planeringens API (PLAN-37), with the types generated from the contracts
// (contracts/planning.py). Everyone may look; what changes something needs the login.
import { call, Problem, type MeetSummary } from "@trainmeet/hubben";
import type { components } from "../../../contracts/types";

type Schemas = components["schemas"];
export type { MeetSummary };
export type Draft = Schemas["trainmeet.planning-1.draft"];
export type NewMeet = Schemas["trainmeet.planning-1.new-meet"];
export type IdMeetChoice = Schemas["trainmeet.planning-1.id-meet-choice"];
export type Check = Schemas["trainmeet.planning-1.check"];
export type Finding = Schemas["trainmeet.planning-1.check.Finding"];
export type Version = Schemas["trainmeet.planning-1.version"];
export type ImportPreview = Schemas["trainmeet.planning-1.import-preview"];
export type AiPages = Schemas["trainmeet.planning-1.ai-pages"];
export type Changes = Schemas["trainmeet.planning-1.changes"];
export type TrackPicture = Schemas["trainmeet.planning-1.track-picture"];
export type Answer = Schemas["trainmeet.planning-1.answer"];
export type Proposal = Schemas["trainmeet.planning-1.proposal"];
export type DoubleTrackAnswer = Schemas["trainmeet.planning-1.double-track-answer"];
/** Anläggning från CAD (CAD-11): the planner's assemblies in TrainMeet CAD, or why not. */
export type CadAssemblies = Schemas["trainmeet.planning-1.cad-assemblies"];
export type CadChoice = NonNullable<CadAssemblies["assemblies"]>[number];
export type SectionLength = NonNullable<Draft["lengths"]>[number];
export type LinkCode = Schemas["trainmeet.sync-1.link-code"];
export type Follower = Schemas["trainmeet.sync-1.follower"];
export type Home = Schemas["trainmeet.sync-1.home"];
/** Förarna (PLAN-40, LOK-33): who pays when a driver's photos of a missing duty are read. */
export type PaperReadingSettings = Schemas["trainmeet.driver-1.paper-reading"];
export type PaperReadingPayer = PaperReadingSettings["payer"];
export type DoubleTrackQuestion = NonNullable<Check["double_track"]>[number];
export type Deviation = NonNullable<Check["deviations"]>[number];
/** Egna urtavlor (F13): a file checked before it is saved, and the rights stamp. */
export type ClockCheck = Schemas["trainmeet.planning-1.clock-check"];
export type ClockPackSeen = NonNullable<ClockCheck["packs"]>[number];
export type ClockStamps = Schemas["trainmeet.planning-1.clock-stamps"];
export type ClockStamp = NonNullable<ClockStamps["faces"]>[number];

async function fileCall<T>(url: string, file: File, failed: string): Promise<T> {
  const response = await fetch(url, { method: "POST", body: file, credentials: "same-origin" }).catch(() => null);
  if (!response) throw new Problem("Kontakten med Hubben bröts. Försök igen.", 0);
  const answer: unknown = await response.json().catch(() => ({}));
  if (!response.ok) {
    const said = (answer as { detail?: unknown } | null)?.detail;
    throw new Problem(typeof said === "string" ? said : failed, response.status);
  }
  return answer as T;
}

const MEETS = "/api/planering/1/meets";
const meet = (id: string) => `${MEETS}/${encodeURIComponent(id)}`;

export const planning = {
  meets: () => call<MeetSummary[]>(MEETS),
  create: (fresh: NewMeet) => call<Draft>(MEETS, fresh),
  /** Ny träff for someone logged in with TrainMeet ID: the meets in ID they plan (ID10). */
  idMeets: () => call<IdMeetChoice[]>("/api/planering/1/id-meets"),
  draft: (id: string) => call<Draft>(meet(id)),
  check: (id: string) => call<Check>(`${meet(id)}/check`),
  picture: (id: string) => call<TrackPicture>(`${meet(id)}/picture`),
  versions: (id: string) => call<Version[]>(`${meet(id)}/versions`),
  publish: (id: string) => call<Version>(`${meet(id)}/versions`, {}),
  doubleTrack: (id: string, section: string, answer: DoubleTrackAnswer) => call<Draft>(`${meet(id)}/double-track/${encodeURIComponent(section)}`, answer),
  letStand: (id: string, deviation: Deviation) => call<Draft>(`${meet(id)}/deviations/${encodeURIComponent(deviation.id)}/let-stand`, { fingerprint: deviation.fingerprint }),
  takeBack: (id: string, deviation: Deviation) => call<Draft>(`${meet(id)}/deviations/${encodeURIComponent(deviation.id)}/take-back`, {}),
  withdraw: (id: string, number: number) => call<Version>(`${meet(id)}/versions/${number}/withdraw`, {}),
  // Koppla en Pi (SYNK-02): a code for the meet, and the Pis that follow it.
  linkCode: (id: string) => call<LinkCode>(`/api/sync/1/meets/${encodeURIComponent(id)}/code`, {}),
  followers: (id: string) => call<Follower[]>(`/api/sync/1/meets/${encodeURIComponent(id)}/followers`),
  revoke: (id: string, hub: string) => call<unknown>(`/api/sync/1/meets/${encodeURIComponent(id)}/followers/${encodeURIComponent(hub)}/revoke`, {}),
  // Träffens hem (H35): where the meet is planned, and taking it back from a silent Pi.
  home: (id: string) => call<Home>(`/api/sync/1/meets/${encodeURIComponent(id)}/home`),
  reclaim: (id: string) => call<Home>(`/api/sync/1/meets/${encodeURIComponent(id)}/home/reclaim`, {}),
  change: (id: string, changes: Changes) => call<Draft>(`${meet(id)}/changes`, changes),
  /** Förarna (LOK-33): the meet's tokens or the driver's own, for reading a missing duty. */
  paperReading: (id: string) => call<PaperReadingSettings>(`${meet(id)}/paper-reading`),
  choosePaperReading: (id: string, payer: PaperReadingPayer) => call<PaperReadingSettings>(`${meet(id)}/paper-reading`, { payer }),
  /** Egna urtavlor (F13): what the file holds, without saving it. */
  checkClock: async (id: string, file: File): Promise<ClockCheck> => fileCall<ClockCheck>(`${meet(id)}/clock-faces/check?name=${encodeURIComponent(file.name)}`, file, "Klockpaketet gick inte att läsa."),
  /** The approved faces, with the right to use them confirmed. */
  uploadClock: async (id: string, file: File, approved: string[]): Promise<Draft> => {
    const query = approved.map((face) => `approved=${encodeURIComponent(face)}`).join("&");
    return fileCall<Draft>(`${meet(id)}/clock-faces?name=${encodeURIComponent(file.name)}&rights=true&${query}`, file, "Klockpaketet gick inte att lägga in.");
  },
  clockFaces: (id: string) => call<ClockStamps>(`${meet(id)}/clock-faces`),
  removeClock: (id: string, face: string) => call<Draft>(`${meet(id)}/clock-faces/remove`, { face }),
  clockStyle: (id: string, style: string) => call<Draft>(`${meet(id)}/clock-style`, { style }),
  /** Förarna (PLAN-40): the general instructions as PDF, its bytes in the body. */
  instructionsPdf: async (id: string, file: File): Promise<Draft> => {
    const response = await fetch(`${meet(id)}/instructions.pdf?name=${encodeURIComponent(file.name)}`, {
      method: "POST",
      headers: { "Content-Type": "application/pdf" },
      body: file,
      credentials: "same-origin",
    }).catch(() => null);
    if (!response) throw new Problem("Kontakten med Hubben bröts. Försök igen.", 0);
    const answer: unknown = await response.json().catch(() => ({}));
    if (!response.ok) {
      const said = (answer as { detail?: unknown } | null)?.detail;
      throw new Problem(typeof said === "string" ? said : "PDF:en gick inte att lägga in.", response.status);
    }
    return answer as Draft;
  },
  answer: (id: string, given: Answer) => call<Draft>(`${meet(id)}/answers`, given),
  proposals: (id: string) => call<Proposal[]>(`${meet(id)}/proposals`),
  take: (id: string, proposal: string) => call<Draft>(`${meet(id)}/proposals/${encodeURIComponent(proposal)}/take`, {}),
  reject: (id: string, proposal: string) => call<Proposal>(`${meet(id)}/proposals/${encodeURIComponent(proposal)}/reject`, {}),
  apply: (id: string, source: string) => call<Draft>(`${meet(id)}/sources/${encodeURIComponent(source)}/apply`, {}),
  /** Anläggning från CAD (CAD-11): the planner's assemblies, and one read as a source. */
  cadAssemblies: (id: string) => call<CadAssemblies>(`${meet(id)}/cad`),
  readCad: (id: string, assembly: string) => call<ImportPreview>(`${meet(id)}/cad/${encodeURIComponent(assembly)}`, {}),
  /** The source file as it came, for the administrator. */
  sourceFile: (id: string, source: string) => `${meet(id)}/sources/${encodeURIComponent(source)}`,
  /** Lägg till underlag: the file's own bytes, its name in the address; nothing is put in yet. */
  /** The file read and what it would change; or, for a scanned file, the pages its own AI has
   * to write down first (202). Sent again with transcribe, the AI writes them down. */
  read: async (id: string, file: File, transcribe?: "lists" | "picture" | "graph", ai: "own" | "trainmeet" = "own"): Promise<{ preview: ImportPreview } | { pages: AiPages }> => {
    const asked = transcribe ? `&transcribe=${transcribe}&ai=${ai}` : "";
    const response = await fetch(`${meet(id)}/sources?name=${encodeURIComponent(file.name)}${asked}`, {
      method: "POST",
      headers: { "Content-Type": "application/octet-stream" },
      body: file,
      credentials: "same-origin",
    }).catch(() => null);
    if (!response) throw new Problem("Kontakten med Hubben bröts. Försök igen.", 0);
    const answer: unknown = await response.json().catch(() => ({}));
    if (!response.ok) {
      const said = (answer as { detail?: unknown } | null)?.detail;
      throw new Problem(typeof said === "string" ? said : "Filen gick inte att läsa.", response.status);
    }
    if (response.status === 202) return { pages: answer as AiPages };
    return { preview: answer as ImportPreview };
  },
};
