// Planeringens API (PLAN-37), with the types generated from the contracts
// (contracts/planning.py). Everyone may look; what changes something needs the login.
import { call, Problem, type MeetSummary } from "@trainmeet/hubben";
import type { components } from "../../../contracts/types";

type Schemas = components["schemas"];
export type { MeetSummary };
export type Draft = Schemas["trainmeet.planning-1.draft"];
export type NewMeet = Schemas["trainmeet.planning-1.new-meet"];
export type Check = Schemas["trainmeet.planning-1.check"];
export type Finding = Schemas["trainmeet.planning-1.check.Finding"];
export type Version = Schemas["trainmeet.planning-1.version"];
export type ImportPreview = Schemas["trainmeet.planning-1.import-preview"];
export type Changes = Schemas["trainmeet.planning-1.changes"];
export type Answer = Schemas["trainmeet.planning-1.answer"];

const MEETS = "/api/planering/1/meets";
const meet = (id: string) => `${MEETS}/${encodeURIComponent(id)}`;

export const planning = {
  meets: () => call<MeetSummary[]>(MEETS),
  create: (fresh: NewMeet) => call<Draft>(MEETS, fresh),
  draft: (id: string) => call<Draft>(meet(id)),
  check: (id: string) => call<Check>(`${meet(id)}/check`),
  versions: (id: string) => call<Version[]>(`${meet(id)}/versions`),
  publish: (id: string) => call<Version>(`${meet(id)}/versions`, {}),
  change: (id: string, changes: Changes) => call<Draft>(`${meet(id)}/changes`, changes),
  answer: (id: string, given: Answer) => call<Draft>(`${meet(id)}/answers`, given),
  apply: (id: string, source: string) => call<Draft>(`${meet(id)}/sources/${encodeURIComponent(source)}/apply`, {}),
  /** The source file as it came, for the administrator. */
  sourceFile: (id: string, source: string) => `${meet(id)}/sources/${encodeURIComponent(source)}`,
  /** Lägg till underlag: the file's own bytes, its name in the address; nothing is put in yet. */
  read: async (id: string, file: File): Promise<ImportPreview> => {
    const response = await fetch(`${meet(id)}/sources?name=${encodeURIComponent(file.name)}`, {
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
    return answer as ImportPreview;
  },
};
