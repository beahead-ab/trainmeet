// Studio › Rita › Ladda upp ritning (#89 del c4, STUDIO-01, STUDIO-03, CAD6): what the panel says
// about a drawing read by TrainMeet CAD. Pure functions, so that the tests read them without a
// browser. The read itself is CAD's; the proposal is Studio's server's (tkl/studio/ritning.py).
import type { DrawingJob, DrawingQuestion, DrawingRead, Upload } from "./api";

export const OFFLINE = "Ladda upp ritning kräver internet och inloggning med TrainMeet ID. Rita går alltid.";

/** Whether the way in is open: TKL says why not, and a browser without internet is never. */
export function wayIn(upload: Upload | null, online: boolean): { open: boolean; reason: string | null } {
  if (!online) return { open: false, reason: OFFLINE };
  if (!upload) return { open: false, reason: null };
  return { open: upload.available, reason: upload.available ? null : (upload.reason ?? OFFLINE) };
}

export const working = (job: DrawingJob | null | undefined): boolean => job?.state === "queued" || job?.state === "running";

/** The price before start: a vector page is free, a raster page 12 tokens with TrainMeets AI,
 * nothing without AI or with the account's own AI. */
export function priceText(job: DrawingJob, page: number, ai: boolean): string {
  const chosen = job.pages.find((p) => p.number === page) ?? job.pages[0]!;
  if (chosen.kind === "vector") return "Gratis: sidan har ritade linjer och text, som koden läser utan AI.";
  if (!ai) return "Utan AI: gratis. Spåren, växlarna och signalfigurerna läses, men inte texten.";
  if (job.page === page && job.price.why !== "first") return job.price.text;
  return `${chosen.tokens} tokens för sidan när AI:n skriver av texten. Samma sida igen: gratis.`;
}

/** The pages as the chooser shows them. */
export function pageText(job: DrawingJob): string[] {
  return job.pages.map((p) => `Sida ${p.number}: ${p.kind === "vector" ? (p.text ? "linjer och text" : "linjer utan text") : "bild"}`);
}

/** The questions, the legend's first (bildkedjan R3), then the track ends. */
export function inOrder(questions: DrawingQuestion[]): DrawingQuestion[] {
  const rank = (q: DrawingQuestion) => (q.kind === "legend" ? 0 : q.kind === "end" ? 1 : 2);
  return [...questions].sort((a, b) => rank(a) - rank(b));
}

/** The questions that wait for the owner: no answer, and no choice of the code's to stand. */
export function open(read: DrawingRead | null | undefined): DrawingQuestion[] {
  return (read?.questions ?? []).filter((q) => !q.answer && !q.code);
}

const count = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

/** What the read found, in one line. */
export function summaryText(read: DrawingRead): string {
  const s = read.summary;
  return [
    count(s.switches, "växel", "växlar"),
    s.crossings ? count(s.crossings, "korsning", "korsningar") : null,
    count(s.signals, "signal", "signaler"),
    count(s.boundaries, "spårledningsgräns", "spårledningsgränser"),
    count(s.line_exits, "linjeutfart", "linjeutfarter"),
    count(s.buffer_stops, "stoppbock", "stoppbockar"),
  ]
    .filter(Boolean)
    .join(", ");
}

/** The choice the owner sees as chosen: their answer, or the code's until they answer. */
export const chosen = (q: DrawingQuestion): string | null => q.answer ?? q.code ?? null;
