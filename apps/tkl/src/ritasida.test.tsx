import { isValidElement, type ReactElement, type ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import type { Finding, Route } from "./api";
import { Canvas, FindingsView, TOOLS } from "./Rita";
import { addTrack, placeDerailer, placeLineExit } from "./rita";
import { blank, provby } from "./ritaprov";

/** Every element in a tree a component returned, to find a button and press it. */
function elements(node: ReactNode): ReactElement<Record<string, unknown>>[] {
  if (Array.isArray(node)) return node.flatMap(elements);
  if (!isValidElement(node)) return [];
  const element = node as ReactElement<Record<string, unknown>>;
  return [element, ...elements(element.props.children as ReactNode)];
}

describe("Rita, the page", () => {
  it("has the seven tools and Markera (STUDIO-02, TKL129)", () => {
    expect(TOOLS.map((t) => t.label)).toEqual(["Markera", "Spår", "Växel", "Spårspärr", "Signal", "Spårledningsgräns", "Stoppbock", "Linjeutfart"]);
  });

  it("draws a derailer across its track with its number, to select", () => {
    const drawn = placeDerailer(provby(), [16, 7]).drawing;
    const html = renderToStaticMarkup(<Canvas drawing={drawn} circuits={[]} selected={[]} route={null} tool="select" />);
    expect(html).toMatch(/<g class="sparr" data-ref="derailer:3" data-derailer="3"><title>Spårspärr 3<\/title><line/);
  });

  it("shows a red dot where a track ends without reaching anything (RS7)", () => {
    const drawn = addTrack(blank(), [2, 4], [12, 4]);
    const html = renderToStaticMarkup(<Canvas drawing={drawn} circuits={[]} selected={[]} route={null} tool="select" />);
    expect(html.match(/data-loose="ja"/g)).toHaveLength(2);
    expect(html).toContain('aria-label="Ritningen på rutnätet"');
    const exit = placeLineExit(drawn, [2, 4]).drawing;
    const fewer = renderToStaticMarkup(<Canvas drawing={exit} circuits={[]} selected={[]} route={null} tool="select" />);
    expect(fewer.match(/data-loose="ja"/g)).toHaveLength(1);
    expect(fewer).toContain(">A</text>");
    const done = renderToStaticMarkup(<Canvas drawing={provby()} circuits={[]} selected={[]} route={null} tool="select" />);
    expect(done).not.toContain('data-loose="ja"');
  });

  it("draws the template's symbols: switch numbers, signals, buffer stops, station tracks and block labels", () => {
    const d = provby();
    const circuits = [{ name: "S1v", pieces: [d.model.station_tracks[0]!.pieces![0]!], detection: null, origin: null }];
    const html = renderToStaticMarkup(<Canvas drawing={d} circuits={circuits} selected={[{ kind: "signal", id: "A1" }]} route={null} tool="signal" />);
    expect(html).toContain('data-signal="A1"');
    expect(html).toContain('class="signal hsi vald"');
    expect(html).toContain("huvudsignal 1Ö");
    expect(html.match(/class="stoppbock"/g)).toHaveLength(2);
    expect(html).toContain('class="blocketikett" data-ref="circuit:S1v"');
    expect(html).toContain('class="sparbeteckning"');
    expect(html).toContain('class="rita-rutnat verktyg-signal"');
    const yellow = { ...d, model: { ...d.model, switches: d.model.switches.map((s) => ({ ...s, origin: { source: "assumed" as const, confirmed: false, ref: null, note: null } })) } };
    expect(renderToStaticMarkup(<Canvas drawing={yellow} circuits={[]} selected={[]} route={null} tool="select" />)).toContain("antagen");
  });

  it("lights up a route on the drawing, in its colour", () => {
    const d = provby();
    const pieces = d.model.pieces.slice(0, 3).map((p) => p.id);
    const route: Route = { kind: "train", start: "A1", end: "1Ö", pieces, positions: { "1": "+" }, turntable: null };
    const html = renderToStaticMarkup(<Canvas drawing={d} circuits={[]} selected={[]} route={route} tool="select" />);
    expect(html.match(/data-lit=/g)).toHaveLength(3);
    expect(html).toContain('class="vag-linje tagvag"');
    const shunting = renderToStaticMarkup(<Canvas drawing={d} circuits={[]} selected={[]} route={{ ...route, kind: "shunting" }} tool="select" />);
    expect(shunting).toContain('class="vag-linje vaxling"');
    expect(renderToStaticMarkup(<Canvas drawing={d} circuits={[]} selected={[]} route={null} tool="select" />)).not.toContain("data-lit=");
  });

  it("lists the problems and notes, each a button to its object", () => {
    const findings: Finding[] = [
      { text: "Spåret slutar utan att nå något i ruta (20, 7).", problem: true, target: { kind: "node", id: "n5" } },
      { text: "Signalen B1: spårbiten s1 når inte signalen.", problem: true, target: { kind: "signal", id: "B1" } },
      { text: "Linjeutfarten A saknar grannstation.", problem: false, target: { kind: "exit", id: "A" } },
      { text: "Stationen får inte plats på skärmen.", problem: false, target: null },
    ];
    const html = renderToStaticMarkup(<FindingsView findings={findings} onPick={() => undefined} />);
    expect(html).toContain("Problem · ritningen kan inte användas än");
    expect(html).toContain('data-target="node:n5"');
    expect(html).toContain('data-target="exit:A"');
    expect(html).toContain("<li>Stationen får inte plats på skärmen.</li>");
    const pick = vi.fn();
    const buttons = elements(FindingsView({ findings, onPick: pick })).filter((e) => e.type === "button");
    expect(buttons).toHaveLength(3);
    (buttons[1]!.props.onClick as () => void)();
    expect(pick).toHaveBeenCalledWith({ kind: "signal", id: "B1" });
    const fine = renderToStaticMarkup(<FindingsView findings={[]} onPick={pick} />);
    expect(fine).toContain("Inga problem: ritningen kan användas.");
  });
});
