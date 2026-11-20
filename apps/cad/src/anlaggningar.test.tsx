// Anläggningar and Till TKL Studio (#89 del d2): placing modules, joining gables, the problems,
// the pinned versions with a newer one offered, and what goes to Studio. Nothing here is a real
// station.
import { isValidElement, type ReactElement, type ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import type { ModuleBrief } from "./api";
import { AssemblyList, AssemblyPage, TillStudio } from "./Anlaggningar";
import { ModulePage } from "./ModulePage";
import { addModule, candidates, changeOf, follows, freeGables, join, studioHref, takeNewer, type Assembly, type StudioGraph } from "./anlaggning";
import { CURVE, STATION } from "./testdata";

const ONE = "11111111-2222-4333-8444-555555555555";
const TWO = "66666666-7777-4888-8999-aaaaaaaaaaaa";
const OWNER = { kind: "person" as const, id: "6dc0f358-f4a0-53bc-8a19-9db29682090d", name: "Provkonto A" };
const NOW = "2026-11-20T12:00:00+01:00";

function gable(end: "A" | "B", x: number, joined: boolean) {
  return { end, corner: [x, 0] as [number, number], far: [x, 500] as [number, number], tracks: [[x, 140]] as [number, number][], label: "MMM enkelspår", norm: "mmm" as const, joined };
}

function part(module: string, number: string, name: string, x: number, placed: "first" | "joint", joined: [boolean, boolean], newer: number | null = null) {
  return {
    module,
    version: 1,
    seen: true,
    number,
    name,
    owner: "Provkonto A",
    placed,
    outline: [[x, 0], [x + 1500, 0], [x + 1500, 500], [x, 500]] as [number, number][],
    gables: [gable("A", x, joined[0]), gable("B", x + 1500, joined[1])],
    newer,
  };
}

const ASSEMBLY: Assembly = {
  id: "3c9d7e10-2a4b-4c5d-8e6f-708192a3b4c5",
  name: "Exempelanläggning",
  owner: OWNER,
  scale: "H0",
  modules: [
    { module: ONE, version: 1, at: [0, 0], angle: 0 },
    { module: TWO, version: 1, at: [1500, 0], angle: 0 },
  ],
  joints: [{ a: { module: ONE, gable: "B" }, b: { module: TWO, gable: "A" }, angle: 0 }],
  revision: 3,
  changed_at: NOW,
  may_edit: true,
  parts: [part(ONE, "M-001", "Linje 1", 0, "first", [false, true]), part(TWO, "M-002", "Linje 2", 1500, "joint", [true, false], 2)],
  checks: [{ joint: 0, fits: true, problems: [], gap: 0, turn: 0, closing: false }],
  problems: [],
  graph: {
    geometry: "mm",
    nodes: [
      { id: `${ONE}:n1`, type: "module_joint", at: [0, 140], gable: "A", track: 1 },
      { id: `${ONE}:n2`, type: "module_joint", at: [1500, 140], gable: "B", track: 1 },
      { id: `${TWO}:n2`, type: "module_joint", at: [3000, 140], gable: "B", track: 1 },
    ],
    pieces: [
      { id: `${ONE}:s3`, start: `${ONE}:n1`, end: `${ONE}:n2`, segments: [{ kind: "line", start: [0, 140], end: [1500, 140] }], track: null, origin: null },
      { id: `${TWO}:s3`, start: `${ONE}:n2`, end: `${TWO}:n2`, segments: [{ kind: "line", start: [1500, 140], end: [3000, 140] }], track: "1", origin: null },
    ],
    switches: [],
    labels: [],
    symbols: [],
    complete: true,
    issued: 0,
  },
  stations: [{ station_id: "exb", name: "Exempelby", revision: 3, at: NOW }],
};

const WRONG: Assembly = {
  ...ASSEMBLY,
  checks: [{ joint: 0, fits: false, problems: ["Spår 1 möts inte: 10,0 mm isär, högst 1,0 mm."], gap: 10, turn: 0, closing: false }],
  problems: ["Skarven M-001 Linje 1 gavel B – M-002 Linje 2 gavel A: Spår 1 möts inte: 10,0 mm isär, högst 1,0 mm."],
};

const BRIEF = (id: string, name: string, status: "approved" | "draft", scale: "H0" | "N" = "H0"): ModuleBrief => ({ ...CURVE, id, name, status, scale });

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

/** A submitted form, as the page reads it: its fields by name. */
function submit(values: Record<string, string>) {
  return { preventDefault: () => undefined, currentTarget: { elements: { namedItem: (name: string) => (name in values ? { value: values[name] } : null) } } };
}

describe("Anläggningar", () => {
  it("lists the assemblies with their state and where they are used, and makes a new one", () => {
    const onCreate = vi.fn();
    const html = renderToStaticMarkup(
      <AssemblyList list={[{ ...ASSEMBLY, modules: 2, problems: 0, changed_at: NOW, stations: ASSEMBLY.stations ?? [] }]} scale="H0" onCreate={onCreate} />,
    );
    for (const t of ["Exempelanläggning", "Klar för Studio", "Exempelby", "Ny anläggning", "Skapa anläggningen"]) expect(html).toContain(t);
    expect(html).toContain(`href="/anlaggningar/${ASSEMBLY.id}"`);
    const form = elements(AssemblyList({ list: [], scale: "N", onCreate })).find((e) => e.type === "form");
    (form!.props.onSubmit as (e: unknown) => void)(submit({ anlaggning: " Bangården ", skala: "N" }));
    expect(onCreate).toHaveBeenCalledWith({ name: "Bangården", scale: "N", owner: null });
  });

  it("draws the modules joined, with the free gables, and says the joint fits", () => {
    const html = renderToStaticMarkup(<AssemblyPage assembly={ASSEMBLY} modules={[]} />);
    expect(html).toContain("Klar för Studio");
    expect(html).toContain("M-001 Linje 1 B – M-002 Linje 2 A");
    expect(html).toContain("✓ Passar");
    expect(html.match(/class="cad-fri-gavel"/g)?.length).toBe(2);
    expect(html).not.toContain("cad-skarv-fel");
    expect(html).toContain(`href="/anlaggningar/${ASSEMBLY.id}/studio"`);
    expect(html).toContain(`href="/api/cad/1/assemblies/${ASSEMBLY.id}/dxf"`);
    expect(html).toContain("Ladda ner DXF");
    expect(html).toContain("Exempelby");
  });

  it("shows a joint that does not fit, red with the reason, and what keeps it from Studio", () => {
    const html = renderToStaticMarkup(<AssemblyPage assembly={WRONG} modules={[]} />);
    expect(html).toContain("1 sak att rätta");
    expect(html).toContain("Det här hindrar anläggningen från Studio");
    expect(html).toContain("Passar inte");
    expect(html).toContain("Spår 1 möts inte: 10,0 mm isär, högst 1,0 mm.");
    expect(html).toContain('class="cad-skarv-fel"');
  });

  it("pins the versions and offers a newer approved one, never taken silently", () => {
    const onChange = vi.fn();
    const found = elements(AssemblyPage({ assembly: ASSEMBLY, modules: [], onChange }));
    const offer = found.find((e) => e.type === "button" && text(e) === "Version 2 är godkänd · använd den");
    expect(offer).toBeTruthy();
    expect(onChange).not.toHaveBeenCalled();
    (offer!.props.onClick as () => void)();
    const change = onChange.mock.calls[0]![0];
    expect(change.base).toBe(3);
    expect(change.modules.map((m: { version: number | null }) => m.version)).toEqual([1, null]);
  });

  it("puts a module at a free gable, or joins two free gables", () => {
    const third = "bbbbbbbb-cccc-4ddd-8eee-ffffffffffff";
    expect(freeGables(ASSEMBLY).map((g) => g.text)).toEqual(["M-001 Linje 1 · gavel A · MMM enkelspår", "M-002 Linje 2 · gavel B · MMM enkelspår"]);
    const added = addModule(ASSEMBLY, third, { module: TWO, gable: "B" }, "A");
    expect(added.modules?.at(-1)).toEqual({ module: third, version: null, at: [3300, 0], angle: 0 });
    expect(added.joints?.at(-1)).toEqual({ a: { module: TWO, gable: "B" }, b: { module: third, gable: "A" }, angle: 0 });
    const free = addModule(ASSEMBLY, third, null);
    expect(free.joints).toEqual(changeOf(ASSEMBLY).joints);
    const loop = join(ASSEMBLY, { module: ONE, gable: "A" }, { module: TWO, gable: "B" });
    expect(loop.joints).toHaveLength(2);
    expect(takeNewer(ASSEMBLY, TWO).modules?.[1]?.version).toBeNull();
    // Only approved modules in the scale, not already in it.
    const list = [BRIEF(ONE, "Linje 1", "approved"), BRIEF(third, "Ny", "approved"), BRIEF("x", "Utkast", "draft"), BRIEF("y", "N-modul", "approved", "N")];
    expect(candidates(ASSEMBLY, list).map((m) => m.name)).toEqual(["Ny"]);
    // The form adds the chosen module at the first free gable.
    const onChange = vi.fn();
    const form = elements(AssemblyPage({ assembly: ASSEMBLY, modules: list, onChange })).find((e) => e.type === "form" && e.props["aria-label"] === "Lägg till modul");
    (form!.props.onSubmit as (e: unknown) => void)(submit({ modul: third, vid: `${ONE}:A`, hall: "samma" }));
    expect(onChange.mock.calls[0]![0].joints.at(-1)).toEqual({ a: { module: ONE, gable: "A" }, b: { module: third, gable: "B" }, angle: 0 });
    (form!.props.onSubmit as (e: unknown) => void)(submit({ modul: third, vid: `${TWO}:B`, hall: "vand" }));
    expect(onChange.mock.calls[1]![0].joints.at(-1)).toEqual({ a: { module: TWO, gable: "B" }, b: { module: third, gable: "B" }, angle: 0 });
  });

  it("lets a viewer look, not change", () => {
    const html = renderToStaticMarkup(<AssemblyPage assembly={{ ...ASSEMBLY, may_edit: false }} modules={[]} />);
    expect(html).not.toContain("Lägg till modul");
    expect(html).not.toContain("Ta bort skarven");
    expect(html).toContain("✓ Passar");
  });
});

const STUDIO: StudioGraph = {
  source: {
    kind: "assembly",
    id: ASSEMBLY.id,
    name: ASSEMBLY.name,
    scale: "H0",
    owner: "Provkonto A",
    revision: 3,
    modules: [],
    ready: true,
    problems: [],
    stations: ASSEMBLY.stations ?? [],
    changed_at: NOW,
  },
  graph: ASSEMBLY.graph!,
};

describe("Till TKL Studio", () => {
  it("shows the preview, what follows, and how to connect it to a station in TKL", () => {
    const html = renderToStaticMarkup(<TillStudio studio={STUDIO} assembly={ASSEMBLY} host="test.cad.trainmeet.app" />);
    expect(html).toContain('aria-pressed="true">Verklighetstrogen');
    expect(html).toContain("cad-anl-bild realistisk");
    for (const t of ["Det här följer med", "2 spårbitar · 3 m spår", "0 växlar", "2 spår vid fria gavlar", "Signaler, stoppbockar och vägar", "Välj Exempelanläggning och gör förslaget", "CAD skapar aldrig en station"]) {
      expect(html).toContain(t);
    }
    expect(html).toContain('href="https://test.tkl.trainmeet.app/studio/rita"');
    expect(renderToStaticMarkup(<TillStudio studio={STUDIO} assembly={ASSEMBLY} host="x" look="mork" />)).toContain("cad-anl-bild mork");
    expect(follows(STUDIO.graph)).toEqual({ pieces: 2, switches: 0, crossings: 0, exits: 2, ends: 0, metres: 3 });
    expect(studioHref("cad.trainmeet.app")).toBe("https://tkl.trainmeet.app/studio/rita");
  });

  it("toggles realistic and dark, and says what to fix first", () => {
    const onLook = vi.fn();
    const found = elements(TillStudio({ studio: STUDIO, assembly: ASSEMBLY, host: "x", onLook }));
    (found.find((e) => e.type === "button" && text(e) === "Mörk")!.props.onClick as () => void)();
    expect(onLook).toHaveBeenCalledWith("mork");
    const blocked = { ...STUDIO, source: { ...STUDIO.source, ready: false, problems: WRONG.problems ?? [] } };
    const html = renderToStaticMarkup(<TillStudio studio={blocked} assembly={WRONG} host="x" />);
    expect(html).toContain("Rätta det här först");
    expect(html).toContain('aria-disabled="true"');
  });
});

describe("Används i on the module's page", () => {
  it("names the assemblies and the stations in TKL", () => {
    const used = [
      { kind: "assembly" as const, id: ASSEMBLY.id, name: "Exempelanläggning", version: 1, station: null },
      { kind: "station" as const, id: ASSEMBLY.id, name: "Exempelby", version: 3, station: "exb" },
    ];
    const html = renderToStaticMarkup(<ModulePage module={{ ...CURVE, used_in: used }} history={[]} tab="oversikt" clubs={[]} />);
    expect(html).toContain("<dd>Exempelanläggning</dd>");
    expect(html).toContain("<dd>Exempelby</dd>");
    expect(html).toContain('href="/anlaggningar"');
    expect(STATION.used_in).toEqual([]);
  });
});
