// Studio › Rita › Från CAD (#89 del d2): grey without TrainMeet CAD or a login, the person's
// assemblies, the proposal yellow until the owner confirms it, and the difference on a re-import.
// Nothing here names a real station (RS13).
import { isValidElement, type ReactElement, type ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import type { CadDiff, CadSource, FromCad } from "./api";
import { DiffView, FromCadView, type FromCadProps } from "./FranCad";
import { wayIn } from "./laddaupp";
import { cadWay, WaysIn } from "./Rita";
import { confirmAll, FROM_CAD, proposed, type FullDrawing } from "./rita";
import { provby } from "./ritaprov";

function elements(node: ReactNode): ReactElement<Record<string, unknown>>[] {
  if (Array.isArray(node)) return node.flatMap(elements);
  if (!isValidElement(node)) return [];
  const element = node as ReactElement<Record<string, unknown>>;
  if (typeof element.type === "function") {
    return [element, ...elements((element.type as (p: unknown) => ReactNode)(element.props))];
  }
  return [element, ...elements(element.props.children as ReactNode)];
}

const text = (e: ReactElement<Record<string, unknown>>): string => renderToStaticMarkup(e).replace(/<[^>]+>/g, "");

const SOURCE: CadSource = {
  kind: "assembly",
  id: "3c9d7e10-2a4b-4c5d-8e6f-708192a3b4c5",
  name: "Exempelanläggning",
  scale: "H0",
  owner: "Provkonto A",
  revision: 2,
  modules: [
    { id: "11111111-2222-4333-8444-555555555555", number: "M-001", name: "Infart", version: 1 },
    { id: "66666666-7777-4888-8999-aaaaaaaaaaaa", number: "M-002", name: "Linje", version: 1 },
  ],
  ready: true,
  problems: [],
  stations: [],
  changed_at: "2026-11-20T12:00:00Z",
};

const OPEN: FromCad = { available: true, reason: null, sources: [SOURCE], link: null, pending: null };

function view(overrides: Partial<FromCadProps> = {}): FromCadProps {
  return { fromCad: OPEN, busy: false, message: "", problems: [], onPropose: () => undefined, onClose: () => undefined, ...overrides };
}

describe("Från CAD", () => {
  it("is grey with the reason where Ladda upp ritning is, and Rita still works", () => {
    const said = "Ladda upp ritning kräver inloggning med TrainMeet ID: logga in under Inställningar. Rita går alltid.";
    const grey = wayIn({ available: false, reason: said, job: null, underlay: null }, true);
    const cad = cadWay(grey);
    expect(cad).toEqual({ open: false, reason: "Från CAD kräver inloggning med TrainMeet ID: logga in under Inställningar. Rita går alltid." });
    const html = renderToStaticMarkup(<WaysIn way="rita" entry={grey} onWay={() => undefined} />);
    expect(html).toContain(`disabled="" title="${cad.reason}">Från CAD</button>`);
    expect(html).not.toContain("Från CAD<span");
    const closed = renderToStaticMarkup(<FromCadView {...view({ fromCad: { ...OPEN, available: false, reason: cad.reason, sources: [] } })} />);
    expect(closed).toContain(cad.reason!);
    expect(closed).not.toContain("Gör förslaget i Rita");
  });

  it("lists the person's assemblies and makes the proposal on the owner's word", () => {
    const onPropose = vi.fn();
    const html = renderToStaticMarkup(<FromCadView {...view()} />);
    expect(html).toContain("Exempelanläggning");
    expect(html).toContain("Anläggning · H0 · version 2 · 2 moduler · Provkonto A");
    expect(html).toContain("CAD skapar aldrig en station.");
    const button = elements(FromCadView(view({ onPropose }))).find((e) => e.type === "button" && text(e) === "Gör förslaget i Rita");
    (button!.props.onClick as () => void)();
    expect(onPropose).toHaveBeenCalledWith(SOURCE);
  });

  it("says which assembly the station comes from, offers to read it in again, and greys one that cannot go", () => {
    const link = { kind: "assembly" as const, id: SOURCE.id, name: SOURCE.name, revision: 2, registered: true, modules: {}, gauge: null };
    const html = renderToStaticMarkup(<FromCadView {...view({ fromCad: { ...OPEN, link } })} />);
    expect(html).toContain("Stationen kommer från <strong>Exempelanläggning</strong>, version 2.");
    expect(html).toContain("CAD visar stationen under Används i.");
    expect(html).toContain(">Läs in igen</button>");
    expect(html).not.toContain("Mätbilder för Foto");
    const image = { module: "m1", version: 1, job: "j1", title: "M-001 Infart", width: 10, height: 5, matrix: [1, 0, 0, 1, 0, 0], outline: [[0, 0], [10, 0], [10, 5]] as [number, number][], bytes: 100, url: null };
    const photographed = { ...link, images: [image], missing: ["M-002 Linje: Modulen är inte fotad i TrainMeet CAD."] };
    const shown = renderToStaticMarkup(<FromCadView {...view({ fromCad: { ...OPEN, link: photographed } })} />);
    expect(shown).toContain("Mätbilder för Foto: 1 av 2 moduler, kvar med stationen.");
    const blocked = { ...SOURCE, ready: false, problems: ["Skarven går inte ihop."] };
    const grey = renderToStaticMarkup(<FromCadView {...view({ fromCad: { ...OPEN, sources: [blocked] } })} />);
    expect(grey).toContain("Skarven går inte ihop.");
    expect(grey).toMatch(/disabled="">Gör förslaget i Rita<\/button>/);
  });

  it("makes the proposal yellow until the owner confirms it", () => {
    const base = provby();
    const fromCad = { source: "assumed" as const, confirmed: false, ref: "x:s3", note: FROM_CAD };
    const drawing: FullDrawing = { ...base, model: { ...base.model, pieces: base.model.pieces.map((p) => ({ ...p, origin: fromCad })) } };
    expect(proposed(drawing.model)).toBe(drawing.model.pieces.length);
    expect(proposed(confirmAll(drawing).model)).toBe(0);
  });

  it("shows the difference on a re-import, and what of the owner's stays", () => {
    const diff: CadDiff = {
      first: false,
      added: [{ id: "c:s3", text: "M-003 Linje bortom · spår 1" }],
      removed: [],
      moved: [{ id: "b:s3", text: "M-002 Linje · spår 1" }],
      kept: ["en signal", "3 bekräftade spårbitar"],
      lost: ["Signal S9"],
      replaced: false,
      panel: false,
    };
    const html = renderToStaticMarkup(<DiffView diff={diff} />);
    expect(html).toContain("Skillnaden mot förra gången");
    expect(html).toContain('data-skillnad="nytt">Nytt 1');
    expect(html).toContain('data-skillnad="borta">Borta 0');
    expect(html).toContain('data-skillnad="flyttat">Flyttat 1');
    expect(html).toContain("M-003 Linje bortom · spår 1");
    expect(html).toContain("Kvar av det du har lagt till: en signal, 3 bekräftade spårbitar.");
    expect(html).toContain("Signal S9");
    expect(html).toContain("Motorn lägger ut panelen på nytt");
    const first = renderToStaticMarkup(<DiffView diff={{ ...diff, first: true, added: [diff.added![0]!, diff.moved![0]!], moved: [], lost: [] }} />);
    expect(first).toContain("Förslaget ur TrainMeet CAD");
    expect(first).toContain("2 spårbitar ur CAD.");
  });
});
