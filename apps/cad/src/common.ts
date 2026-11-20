// Texts the views share: a module's form and measures, its status, dates and visibility.
import type { ModuleBrief, Shape, Visibility } from "./api";

/** A curve's radius and angle as computed from the string and sagitta, never rounded to round
 * values (CAD16, CAD-35): the radius to the tenth of a mm, the angle to the hundredth of a degree. */
export function bendText(radius: number, angle: number): string {
  const r = radius.toLocaleString("sv-SE", { maximumFractionDigits: 1, useGrouping: false });
  return `R ${r} · ${angle.toLocaleString("sv-SE", { maximumFractionDigits: 2 })}°`;
}

export function shapeText(shape: Shape): string {
  if (shape.kind === "straight") return `Rak · ${Math.round(shape.length)} × ${Math.round(shape.width)}`;
  if (shape.kind === "trapezoid") {
    return `Trapets · ${Math.round(shape.length)} × ${Math.round(shape.width_a)}/${Math.round(shape.width_b)}`;
  }
  return `Kurva · ${bendText(shape.radius, shape.angle)} · bredd ${Math.round(shape.width)}`;
}

export type StatusKind = "godkand" | "matt" | "utkast";

/** Godkänd; Mått klara · inget foto when the gables agree; Utkast while tracks are unknown. */
export function status(module: Pick<ModuleBrief, "status" | "graph">): { text: string; kind: StatusKind } {
  if (module.status === "approved") return { text: "Godkänd", kind: "godkand" };
  if (module.graph.complete) return { text: "Mått klara · inget foto", kind: "matt" };
  return { text: "Utkast", kind: "utkast" };
}

const MONTHS = ["jan", "feb", "mar", "apr", "maj", "jun", "jul", "aug", "sep", "okt", "nov", "dec"];

/** "i dag 13:04", or "30 okt", or "30 okt 2025" another year. */
export function dateText(iso: string, now: Date = new Date()): string {
  const when = new Date(iso);
  const time = `${String(when.getHours()).padStart(2, "0")}:${String(when.getMinutes()).padStart(2, "0")}`;
  if (when.toDateString() === now.toDateString()) return `i dag ${time}`;
  const day = `${when.getDate()} ${MONTHS[when.getMonth()]}`;
  return when.getFullYear() === now.getFullYear() ? day : `${day} ${when.getFullYear()}`;
}

/** "19 nov 18:20" for the history. */
export function stampText(iso: string): string {
  const when = new Date(iso);
  const time = `${String(when.getHours()).padStart(2, "0")}:${String(when.getMinutes()).padStart(2, "0")}`;
  return `${when.getDate()} ${MONTHS[when.getMonth()]} ${time}`;
}

/** "19 nov 2026". */
export function dayText(iso: string): string {
  const when = new Date(iso);
  return `${when.getDate()} ${MONTHS[when.getMonth()]} ${when.getFullYear()}`;
}

/** The norms' names, as contracts/cad.py's NORM_NAMES; FREMO N in scale N (CAD14). */
export const NORM_NAMES: Record<string, string> = {
  fremo: "FREMO",
  fremo_n: "FREMO N",
  mmm: "MMM",
  usms: "USMS",
  club: "Klubbens egen",
  fremo_spur_0: "FREMO Spur 0",
};

export const VISIBILITY: Record<Visibility, string> = {
  me: "Bara jag",
  club: "Min klubb",
  all: "Alla i TrainMeet",
};

export function count(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`;
}
