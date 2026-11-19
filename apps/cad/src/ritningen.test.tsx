import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ModulePage } from "./ModulePage";
import { Ritningen } from "./Ritningen";
import { drawnSwitchRadius, markerWord, op, push, redo, snap, startEditor, TOOLS, undo } from "./editor";
import { fromA, gableLine, mmText, onGable, projectPath } from "./geometry";
import { drawingPath, lockPath, routeFor } from "./routes";
import { HISTORY, STATION } from "./testdata";
import { DRAWING } from "./testdrawing";

const MODULE = { ...STATION, name: "Modul 1213 × 680", version: 3, latest: 3 };

function page(overrides: Partial<Parameters<typeof Ritningen>[0]> = {}): string {
  return renderToStaticMarkup(<Ritningen module={MODULE} view={DRAWING} changes={2} undone={1} {...overrides} />);
}

describe("Ritningen", () => {
  it("has the breadcrumb, the title with its badges, Exportera coming and Godkänn spårplanen", () => {
    const html = page();
    expect(html).toContain(">Moduler</a> › <a href=\"/moduler/0e6c2f0a-1b2c-4d3e-8f40-5a6b7c8d9e0f\">Modul 1213 × 680</a> › <span aria-current=\"page\">Ritningen</span>");
    expect(html).toContain('<h1 id="rubrik">Ritningen</h1>');
    expect(html).toContain(">Ritad</span>");
    expect(html).toContain("⚠ 3 saker att kolla");
    expect(html).toMatch(/<button type="button" class="tm-knapp" disabled="" title="Exporten kommer i del d">Exportera <span class="cad-kommer-text">kommer<\/span><\/button>/);
    expect(html).toMatch(/<button type="button" class="tm-knapp primar" disabled="" title="Svara på det som står under Att kolla först.">✓ Godkänn spårplanen<\/button>/);
    expect(page({ view: { ...DRAWING, checks: [] } })).not.toMatch(/primar" disabled=""/);
  });

  it("has the tools on the left, Ångra and Gör om", () => {
    const html = page();
    for (const tool of TOOLS) expect(html).toContain(`<span>${tool.label}</span>`);
    expect(TOOLS.map((t) => t.label)).toEqual(["Välj", "Flytta växel", "Rakt spår", "Båge", "Lås mått", "Mät", "Text"]);
    expect(html).toContain('aria-pressed="true" title="Klicka på en växel');
    expect(page({ initialTool: "arc" })).toContain("Håll Skift för frihand");
    expect(page({ changes: 0, undone: 0 })).toMatch(/disabled="" title="Ctrl\+Z"><span>Ångra<\/span>/);
  });

  it("draws the canvas: the tabs, the cursor, the gables and their measures, switches and what to check", () => {
    const html = page({});
    expect(html).toContain("Ritning</button>");
    expect(html).toContain('disabled="" title="Kommer med fotot (del c)">Fotot under <span class="cad-kommer-text">kommer</span>');
    expect(html).toContain("Landskap <span class=\"cad-kommer-text\">kommer</span>");
    expect(html).toContain("x – · y – mm");
    expect(html).toContain(">GAVEL A</text>");
    expect(html).toContain(">GAVEL B</text>");
    expect(html).toContain(">KANT 1</text>");
    for (const measure of [">53<", ">580<", ">526<", ">578<", `>${mmText(1213)}<`]) expect(html).toContain(measure);
    expect(html).toContain('data-switch="v12"');
    expect(html).toContain("1 · ände?");
    expect(html).toContain("2 · passbit?");
    expect(html).toContain("3 · radie?");
    expect(html).toContain("Spår totalt 3,4 m");
    expect(html).toContain("1 växel");
    expect(html).not.toContain("Avviker från fotot");
  });

  it("shows the switch inspector for the chosen switch", () => {
    const html = page({ initialSelection: { kind: "switch", id: "v12" } });
    expect(html).toContain('<h2 id="vaxel-rubrik">Växel 1</h2>');
    expect(html).toContain(">Antagen</span>");
    expect(html).toContain("<dt>Lämnar</dt><dd>spår från A2 mot B2</dd>");
    expect(html).toContain('<span class="tm-mono">230 mm</span> från gavel A');
    expect(html).toMatch(/<input[^>]*name="vaxel-radie" value="300"\/>/);
    expect(html).toContain('<option value="okand" selected="">Okänd</option>');
    expect(html).toContain("R 2200 · 9,4°");
    expect(html).toContain("Lås växelns läge när kurvorna räknas om");
    expect(page()).toContain("Välj en växel i ritningen så visas den här.");
  });

  it("lists Att kolla with their answer buttons, numbered as on the canvas", () => {
    const html = page();
    expect(html).toContain('Att kolla <span class="cad-antal">3</span>');
    expect(html).toContain("<h3>2 · Rälsen slutar 51 mm före gavel A</h3>");
    expect(html).toContain(">Det är en passbit</button>");
    expect(html).toContain(">Rälsen går ända fram</button>");
    expect(html).toContain("<h3>3 · Växel 1: radien blev 300 mm</h3>");
    expect(html).toContain(">Välj växeltyp</button>");
    expect(html).toMatch(/<li class="antagen" data-key="switch_radius:v12:300">/);
    const answered = { ...DRAWING, checks: (DRAWING.checks ?? []).map((c, i) => (i === 0 ? { ...c, answer: { key: c.key, answer: "slutar", by: null } } : c)) };
    expect(page({ view: answered })).toContain("<summary>1 besvarad</summary>");
  });

  it("has Utjämning with its four levels and the explanation", () => {
    const html = page();
    expect(html).toContain('role="radiogroup" aria-label="Utjämning"');
    for (const level of ["Av", "Lätt", "Normal", "Kraftig"]) expect(html).toContain(`>${level}</button>`);
    expect(html).toContain('role="radio" aria-checked="true">Normal</button>');
    expect(html).toContain("Knaggliga linjer blir mjuka kurvor. Normal: minsta radie 400 mm och högst 9 mm från linjen.");
  });

  it("has the layers, with Fotot under and Landskap off until parts c and d", () => {
    const html = page();
    for (const layer of ["Spår och växlar", "Växelnummer", "Gavelmått"]) expect(html).toContain(`<span>${layer}</span>`);
    expect(html).toContain('disabled="" name="lager-photo"');
    expect(html).toContain('disabled="" name="lager-landscape"');
    expect(html).toContain('name="lager-numbers" checked=""');
  });

  it("says when someone saved in between", () => {
    expect(page({ stale: true })).toContain("Modulen har en nyare version.");
    expect(page({ error: "Ändring 3 går inte: Spåret går utanför modulen." })).toContain("Spåret går utanför modulen.");
  });
});

describe("the change set", () => {
  it("undoes and redoes, and a new change forgets what was undone", () => {
    const first = op.line([0, 53], [600, 53], "n1", null);
    const second = op.remove("s5");
    let editor = push(push(startEditor(STATION.id, 3), first), second);
    expect(editor.ops).toEqual([first, second]);
    editor = undo(editor);
    expect(editor.ops).toEqual([first]);
    expect(editor.undone).toEqual([second]);
    expect(redo(editor).ops).toEqual([first, second]);
    const third = op.smoothing("strong");
    editor = push(editor, third);
    expect(editor.undone).toEqual([]);
    expect(undo(undo(undo(editor))).ops).toEqual([]);
    expect(editor.base).toBe(3);
    expect(editor.module).toBe(STATION.id);
  });

  it("writes every operation with all of CAD's fields", () => {
    expect(op.switchTo("s5", 230.04, 830, [1213, 526], "n4")).toEqual({
      op: "switch",
      piece: "s5",
      from_a: 230,
      radius: 830,
      angle: null,
      side: null,
      toward: "B",
      design: null,
      tail: 0,
      to: [1213, 526],
      to_node: "n4",
    });
    expect(op.setSwitch("v12", { design: "h0-r830-114" })).toEqual({ op: "set_switch", switch: "v12", radius: null, design: "h0-r830-114", locked: null });
    expect(op.lock(null, 140, null, "different")).toEqual({ op: "lock", piece: null, a: 140, b: null, radii: "different" });
    expect(op.answer("short_rail:n10:A:51", "passbit")).toEqual({ op: "answer", key: "short_rail:n10:A:51", answer: "passbit" });
  });

  it("snaps to a free end, a gable's track, the middle of a track, or the gable", () => {
    const free = (DRAWING.graph.nodes ?? []).find((n) => n.type === "module_joint" && n.gable === "A" && n.track === 1)!;
    expect(snap(DRAWING, [free.at[0] + 3, free.at[1] - 2], 8)).toMatchObject({ kind: "end", node: free.id });
    const track = snap(DRAWING, [600, 581], 8);
    expect(track.kind).toBe("track");
    expect(track.piece).toBeTruthy();
    expect(snap(DRAWING, [1210, 300], 8)).toMatchObject({ kind: "gable", node: null, at: [1213, 300] });
    expect(snap(DRAWING, [600, 300], 8)).toMatchObject({ kind: "free", at: [600, 300] });
  });

  it("measures from gable A and projects on a track as CAD does", () => {
    const curve = { kind: "curve" as const, radius: 2000, angle: 30, width: 500, edge: "outer" as const, sides: "bent" as const, measured: null };
    const b = gableLine(curve, 200, "B");
    expect(fromA(curve, 200, onGable(b, 200))).toBeCloseTo((2000 * Math.PI) / 6, 6);
    expect(projectPath([{ kind: "line", start: [0, 0], end: [100, 0] }], [40, 7])).toEqual({ at: [40, 0], distance: 7 });
    const trapezoid = { kind: "trapezoid" as const, length: 685, width_a: 480, width_b: 280, offset: 131.5 };
    expect(onGable(gableLine(trapezoid, 140, "B"), 140)).toEqual([685, 271.5]);
  });

  it("gives a drawn switch the smallest known type's radius and names the markers", () => {
    expect(drawnSwitchRadius(DRAWING)).toBe(830);
    expect(markerWord("short_rail")).toBe("passbit?");
    expect(markerWord("switch_radius")).toBe("radie?");
  });
});

describe("the module page and the addresses", () => {
  it("opens Ritningen from the Ritning tab for those who may edit, and stays read-only for others", () => {
    const html = renderToStaticMarkup(<ModulePage module={STATION} history={HISTORY} tab="oversikt" clubs={[]} />);
    expect(html).toContain(`href="${drawingPath(STATION.id)}">Ritning</a>`);
    const viewer = renderToStaticMarkup(<ModulePage module={{ ...STATION, may_edit: false }} history={HISTORY} tab="ritning" clubs={[]} />);
    expect(viewer).toContain(`href="/moduler/${STATION.id}/ritning" aria-current="page">Ritning</a>`);
    expect(viewer).toContain("Bara ägaren och de med rollen redigera ändrar ritningen.");
  });

  it("has addresses for Ritningen and Lås mått", () => {
    expect(routeFor(drawingPath(STATION.id))).toEqual({ page: "drawing", id: STATION.id });
    expect(routeFor(lockPath(STATION.id))).toEqual({ page: "lock", id: STATION.id });
  });
});
