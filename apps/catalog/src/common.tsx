// What the pages share: the texts for a vehicle, the dialog and the error line.
import { linkClick, type Navigate } from "@trainmeet/design";
import { useEffect, useRef, type ReactNode } from "react";
import { ApiError, type FleetChoice, type FleetRight, type Vehicle, type VehicleKind, type VehicleState } from "./api";
import type { Language, TextKey } from "./i18n";

export type T = (key: TextKey, vars?: Record<string, string | number>) => string;
export type Ctx = {
  t: T;
  language: Language;
  navigate?: Navigate;
  replace?: Navigate;
  /** The right in the fleet the person works in (#49): their own unless shared with them. */
  right?: FleetRight;
  /** Whose fleet it is, when it is someone else's (CAT-50). */
  fleetTitle?: string;
  /** Where the owner shares the fleet in TrainMeet ID (CAT-44). */
  shareUrl?: string | null;
  /** Work in another fleet, on the same page: null for the person's own (CAT-50). */
  workIn?: (owner: string | null) => void;
  /** The fleets the person can work in: their own first (CAT-50). */
  fleets?: FleetChoice[] | null;
};

/** The owner may do everything; someone the fleet is shared with less (CAT-46). */
export const isOwner = (ctx: Ctx) => (ctx.right ?? "owner") === "owner";
export const mayEdit = (ctx: Ctx) => (ctx.right ?? "owner") !== "view";

export const kindText = (t: T, kind: VehicleKind | null | undefined) => (kind ? t(`kind_${kind}` as TextKey) : "");
export const stateText = (t: T, state: VehicleState) => t(`state_${state}` as TextKey);

/** Litt and number, as on the vehicle, or "Untitled draft". */
export function title(t: T, vehicle: Pick<Vehicle, "litt" | "number">): string {
  return `${vehicle.litt ?? ""} ${vehicle.number ?? ""}`.trim() || t("draftTitle");
}

/** Kind · operator · scale, what is filled in. */
export function subtitle(t: T, vehicle: Vehicle): string {
  return [kindText(t, vehicle.kind), vehicle.operator, vehicle.scale].filter(Boolean).join(" · ");
}

export function dateText(language: Language, value: string): string {
  const date = value.length === 10 ? new Date(`${value}T12:00:00`) : new Date(value);
  return new Intl.DateTimeFormat(language === "sv" ? "sv-SE" : "en-GB", { day: "numeric", month: "long" }).format(date);
}

export function timeText(language: Language, value: string): string {
  return new Intl.DateTimeFormat(language === "sv" ? "sv-SE" : "en-GB", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

/** The text for why something did not work. */
export function problemText(t: T, error: unknown): string {
  if (error instanceof ApiError && error.code) return t(`problem_${error.code}` as TextKey);
  return t("problem_other");
}

export function ErrorLine({ text }: { text: string | null }) {
  return text ? (
    <p className="cat-fel" role="alert">
      {text}
    </p>
  ) : null;
}

export function Crumbs({ ctx, items }: { ctx: Ctx; items: { href?: string; label: string }[] }) {
  return (
    <nav className="cat-smulor" aria-label={ctx.t("crumbs")}>
      <ol>
        {items.map((item) => (
          <li key={item.label}>
            {item.href ? (
              <a href={item.href} onClick={linkClick(ctx.navigate, item.href)}>
                {item.label}
              </a>
            ) : (
              <span aria-current="page">{item.label}</span>
            )}
          </li>
        ))}
      </ol>
    </nav>
  );
}

/** A modal dialog with the browser's own focus handling. Escape closes it. */
export function Dialog({ open, title: heading, onClose, children }: { open: boolean; title: string; onClose: () => void; children: ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);
  return (
    <dialog ref={ref} className="cat-dialog" aria-label={heading} onClose={onClose}>
      <h2>{heading}</h2>
      {children}
    </dialog>
  );
}

/** The state as a pill: Hemma, Packad, På träffen or Utlånad. */
export function StatePill({ t, state }: { t: T; state: VehicleState }) {
  return <span className={`cat-pill cat-pill-${state}`}>{stateText(t, state)}</span>;
}
