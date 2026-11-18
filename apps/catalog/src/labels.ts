// Skriv ut QR-etiketter (#56, CAT-184), without its screens: one or several QR labels on an A4
// sheet, each with the litt and the number in plain text under the code. A vehicle without a
// label gets one when it is printed (Skapa QR-etikett, CAT-121); one that has a label keeps it,
// unless the owner says yes to replacing it. LabelsPage.tsx shows it.
import { api, type Vehicle, type VehicleTag } from "./api";

export type LabelSize = "small" | "large";
export const LABEL_SIZES: LabelSize[] = ["small", "large"];

/** The QR code's side on paper, in millimetres: about 30 or 50. */
export const LABEL_MM: Record<LabelSize, number> = { small: 30, large: 50 };

/** The sheet, in millimetres: A4 within 10 mm margins, the gap between the labels, and the
 * height of the text under each code. As in catalog.css. */
export const SHEET_MM = { width: 190, height: 277, gap: 4, text: 8 } as const;

/** How many labels of the size an A4 sheet holds. */
export function perSheet(size: LabelSize): number {
  const side = LABEL_MM[size];
  const across = Math.floor((SHEET_MM.width + SHEET_MM.gap) / (side + SHEET_MM.gap));
  const down = Math.floor((SHEET_MM.height + SHEET_MM.gap) / (side + SHEET_MM.text + SHEET_MM.gap));
  return across * down;
}

/** The vehicle's QR label, if it has one (CAT-121). */
export const qrLabel = (vehicle: Vehicle): VehicleTag | null => (vehicle.tags ?? []).find((tag) => tag.kind === "qr") ?? null;

/** What stands under the code: the litt and the number, as on the vehicle. */
export const labelText = (vehicle: Pick<Vehicle, "litt" | "number">): string => `${vehicle.litt ?? ""} ${vehicle.number ?? ""}`.trim();

/** The vehicles chosen in the address: ?fordon=<id>,<id> from Fordon or the vehicle's card. */
export function chosenFromAddress(search: string): Set<string> {
  const listed = new URLSearchParams(search).get("fordon") ?? "";
  return new Set(listed.split(",").map((id) => id.trim().toLowerCase()).filter(Boolean));
}

export type LabelPlan = {
  /** The chosen vehicles that get a label on the sheet, in the list's order. */
  print: Vehicle[];
  /** Of those, the ones without a label: they get one when the sheet is printed. */
  make: Vehicle[];
  /** Of those, the ones whose label is replaced: only when the owner has said so. */
  replace: Vehicle[];
  /** Chosen drafts: a draft gets no label until it is saved as ready (CAT-84). */
  drafts: Vehicle[];
};

export function labelPlan(vehicles: Vehicle[], chosen: Set<string>, renew: boolean): LabelPlan {
  const picked = vehicles.filter((vehicle) => chosen.has(vehicle.id));
  const print = picked.filter((vehicle) => vehicle.status === "ready");
  return {
    print,
    make: print.filter((vehicle) => !qrLabel(vehicle)),
    replace: renew ? print.filter((vehicle) => qrLabel(vehicle)) : [],
    drafts: picked.filter((vehicle) => vehicle.status !== "ready"),
  };
}

/** The labels the plan needs, made one vehicle at a time, each replacement with the label seen
 * (CAT-89). The vehicles as Catalog has them now; the first refusal stops the rest, and what was
 * made stays made. */
export async function makeLabels(plan: LabelPlan): Promise<{ made: Vehicle[]; error: unknown }> {
  const made: Vehicle[] = [];
  for (const vehicle of [...plan.make, ...plan.replace]) {
    try {
      made.push(await api.newLabel(vehicle.id, qrLabel(vehicle)?.assignment ?? null));
    } catch (error) {
      return { made, error };
    }
  }
  return { made, error: null };
}

/** The list with the vehicles that changed. */
export const withChanged = (vehicles: Vehicle[], changed: Vehicle[]): Vehicle[] =>
  vehicles.map((vehicle) => changed.find((found) => found.id === vehicle.id) ?? vehicle);

/** The browser's print dialog, once every QR code on the sheet has come. */
export async function printWhenReady(sheet: ParentNode | null, print: () => void = () => window.print()): Promise<void> {
  const images = [...(sheet?.querySelectorAll("img") ?? [])];
  await Promise.all(
    images.map((image) =>
      image.complete
        ? Promise.resolve()
        : new Promise<void>((done) => {
            image.addEventListener("load", () => done(), { once: true });
            image.addEventListener("error", () => done(), { once: true });
          }),
    ),
  );
  print();
}
