// Planering's words and numbers, as the old pages wrote them (hub/static/planering.js).
import type { MeetSummary } from "./api";

export const COUNTRIES: Record<string, string> = { se: "Sverige", dk: "Danmark", no: "Norge", de: "Tyskland" };
const LEVELS: Record<number, string> = { 1: "Minimum", 2: "Struktur", 3: "Exakt struktur", 4: "Facit" };

export const number = (value: number) => new Intl.NumberFormat("sv-SE").format(value);

/** The meet's days: one day, a span, or none. */
export function dates(meet: MeetSummary["meet"]): string {
  const format = (value: string) => new Date(`${value}T12:00:00`).toLocaleDateString("sv-SE", { day: "numeric", month: "short", year: "numeric" });
  const first = meet.first_date ?? null;
  const last = meet.last_date ?? null;
  if (!first && !last) return "Inget datum";
  if (!last || first === last) return format((first ?? last) as string);
  if (!first) return format(last);
  return `${format(first)} – ${format(last)}`;
}

/** When a version was published: day, month and time. */
export const when = (value: string) => new Date(value).toLocaleString("sv-SE", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

/** The source's level: 1 Minimum to 4 Facit, or none yet. */
export const levelText = (value: number | null | undefined) => (value ? `Nivå ${value} · ${LEVELS[value] ?? ""}` : "Inget underlag");
