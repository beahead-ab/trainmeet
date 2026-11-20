// Studio › Rita › Ladda upp ritning (#89 del c4): grey without internet or a login with TrainMeet
// ID, the price before start, the questions with the legend first, the proposal yellow until the
// owner confirms it. Nothing here names a real station (RS13).
import { isValidElement, type ReactElement, type ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import type { DrawingJob, DrawingQuestion, DrawingRead, Upload } from "./api";
import { UploadView, type UploadProps } from "./LaddaUpp";
import { inOrder, OFFLINE, open, priceText, summaryText, wayIn } from "./laddaupp";
import { Canvas, WaysIn } from "./Rita";
import { confirmAll, proposed, READ, type FullDrawing } from "./rita";
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

const legend: DrawingQuestion = {
  key: "symbol.triangle-grona",
  kind: "legend",
  title: "Vad betyder ▲ i den här ritningen?",
  text: "Ritningen har 3 sådana figurer (▲ gröna).",
  choices: [
    { id: "hsi", text: "Huvudsignal" },
    { id: "knapp", text: "Knapp eller lampa på panelen: tas inte med" },
  ],
  code: null,
  answer: null,
  sample: "▲ gröna",
  count: 3,
  at: [330, 352],
};
const end: DrawingQuestion = { ...legend, key: "ande.40-330", kind: "end", title: "Hur slutar spåret här?", choices: [{ id: "linjeutfart", text: "Linjeutfart" }, { id: "stoppbock", text: "Stoppbock" }], code: "linjeutfart", sample: null, count: 1 };
const lines: DrawingQuestion = { ...legend, key: "linje.orange-tunna", title: "Vad är de orange linjerna?", choices: [{ id: "spar", text: "Spår" }, { id: "annat", text: "Något annat: tas inte med" }], code: "annat", sample: "orange linjerna", count: 2 };

function read(questions: DrawingQuestion[]): DrawingRead {
  return {
    job: "5e1c0a4d-7b2f-4c89-9d3e-0c4a1b2c3d4e",
    page: 1,
    kind: "vector",
    graph: { geometry: "schema", nodes: [], pieces: [], switches: [], labels: [], symbols: [], complete: true, issued: 0 },
    boundaries: [],
    questions,
    underlay: { url: "/api/cad/1/drawings/x/underlay", width: 2400, height: 1696, transform: [2.85, 0, 0, 2.85, 0, 0] },
    summary: { pieces: 10, switches: 5, crossings: 0, line_exits: 4, buffer_stops: 1, signals: 7, boundaries: 9, labels: 20, unknown_symbols: 3 },
    price: { tokens: 0, why: "vector", text: "Gratis." },
    cost: 0,
    notes: [],
  };
}

function job(change: Partial<DrawingJob> = {}): DrawingJob {
  return {
    id: "5e1c0a4d-7b2f-4c89-9d3e-0c4a1b2c3d4e",
    name: "plan.pdf",
    state: "waiting",
    progress: 0,
    step: "Väntar på Läs",
    created_at: "2026-11-20T10:00:00Z",
    format: "pdf",
    pages: [{ number: 1, kind: "vector", width: 842, height: 595, text: true, tokens: 0 }],
    page: 1,
    price: { tokens: 0, why: "vector", text: "Gratis: sidan har ritade linjer och text, som koden läser utan AI." },
    ai: { available: true, given: false, version: "1", sent_to: "TrainMeets AI", text: "Ritningens sida skickas till TrainMeets AI.", balance: 86, message: null },
    read: null,
    cost: 0,
    chain: "1.0.0",
    key: "0".repeat(64),
    message: null,
    ...change,
  };
}

const upload = (found: DrawingJob | null): Upload => ({ available: true, reason: null, job: found, underlay: found?.read ? `/api/tkl/1/studio/ritning/${found.id}/underlag` : null });

function props(change: Partial<UploadProps>): UploadProps {
  const nothing = () => undefined;
  return { upload: null, page: 1, ai: true, consent: false, busy: false, message: "", onFile: nothing, onPage: nothing, onAi: nothing, onConsent: nothing, onRead: nothing, onAnswer: nothing, onProposal: nothing, onClose: nothing, ...change };
}

describe("Ladda upp ritning", () => {
  it("is grey without internet or a login with TrainMeet ID, with the reason, and Rita still works", () => {
    expect(wayIn(null, false)).toEqual({ open: false, reason: OFFLINE });
    const said = "Ladda upp ritning kräver inloggning med TrainMeet ID: logga in under Inställningar. Rita går alltid.";
    const grey = wayIn({ available: false, reason: said, job: null, underlay: null }, true);
    expect(grey).toEqual({ open: false, reason: said });
    const html = renderToStaticMarkup(<WaysIn way="rita" entry={grey} onWay={() => undefined} />);
    expect(html).toMatch(/<button type="button" aria-pressed="true">Rita<\/button>/);
    expect(html).toContain(`disabled="" title="${said}">Ladda upp ritning</button>`);
    expect(html).toContain(said);
    const live = renderToStaticMarkup(<WaysIn way="rita" entry={wayIn(upload(null), true)} onWay={() => undefined} />);
    expect(live).toContain('<button type="button" aria-pressed="false">Ladda upp ritning</button>');
  });

  it("shows the price before start: free for a vector page, 12 tokens a page when AI transcribes", () => {
    expect(priceText(job(), 1, true)).toBe("Gratis: sidan har ritade linjer och text, som koden läser utan AI.");
    const raster = job({ format: "image", pages: [{ number: 1, kind: "raster", width: 1870, height: 1376, text: false, tokens: 12 }], price: { tokens: 12, why: "first", text: "12 tokens." } });
    expect(priceText(raster, 1, true)).toBe("12 tokens för sidan när AI:n skriver av texten. Samma sida igen: gratis.");
    expect(priceText(raster, 1, false)).toContain("Utan AI: gratis");
    const html = renderToStaticMarkup(<UploadView {...props({ upload: upload(raster) })} />);
    expect(html).toContain('data-pris="12"');
    expect(html).toContain("Ritningens sida skickas till TrainMeets AI.");
    // The yes first: Läs waits for it.
    expect(html).toMatch(/<button type="button" class="primar" disabled="">Läs ritningen<\/button>/);
    const yes = renderToStaticMarkup(<UploadView {...props({ upload: upload(raster), consent: true })} />);
    expect(yes).toMatch(/<button type="button" class="primar">Läs ritningen<\/button>/);
  });

  it("asks the legend first, keeps the code's choice until the owner answers, and waits for the answers", () => {
    expect(inOrder([end, legend, lines]).map((q) => q.key)).toEqual(["symbol.triangle-grona", "linje.orange-tunna", "ande.40-330"]);
    const found = read([end, lines, legend]);
    expect(open(found).map((q) => q.key)).toEqual(["symbol.triangle-grona"]);
    expect(summaryText(found)).toBe("5 växlar, 7 signaler, 9 spårledningsgränser, 4 linjeutfarter, 1 stoppbock");
    const done = job({ state: "done", progress: 100, step: "Klart", read: found });
    const html = renderToStaticMarkup(<UploadView {...props({ upload: upload(done) })} />);
    expect(html).toContain("Frågor om ritningen · teckenförklaringen först");
    expect(html.indexOf("Vad betyder ▲")).toBeLessThan(html.indexOf("Hur slutar spåret"));
    expect(html).toContain("kodens val");
    expect(html).toMatch(/disabled="">Gör förslaget i Rita<\/button>/);
    expect(html).toContain(`src="/api/tkl/1/studio/ritning/${done.id}/underlag"`);
    const answer = vi.fn();
    const buttons = elements(UploadView(props({ upload: upload(done), onAnswer: answer }))).filter((e) => e.type === "button");
    const knapp = buttons.find((b) => text(b).startsWith("Knapp eller lampa"));
    (knapp!.props.onClick as () => void)();
    expect(answer).toHaveBeenCalledWith("symbol.triangle-grona", "knapp");
    const answered = job({ ...done, read: read([end, lines, { ...legend, answer: "knapp" }]) });
    expect(renderToStaticMarkup(<UploadView {...props({ upload: upload(answered) })} />)).toMatch(/<button type="button" class="primar">Gör förslaget i Rita<\/button>/);
  });

  it("marks the proposal yellow until the owner confirms it, one by one or all at once", () => {
    const d = provby();
    const origin = { source: "assumed" as const, confirmed: false, ref: null, note: READ };
    const proposal: FullDrawing = {
      ...d,
      proposal: true,
      model: {
        ...d.model,
        pieces: d.model.pieces.map((p) => ({ ...p, origin })),
        switches: d.model.switches.map((s) => ({ ...s, origin })),
        signals: d.model.signals.map((s) => ({ ...s, origin })),
      },
    };
    const count = d.model.pieces.length + d.model.switches.length + d.model.signals.length;
    expect(proposed(proposal.model)).toBe(count);
    const yellow = renderToStaticMarkup(<Canvas drawing={proposal} circuits={[]} selected={[]} route={null} tool="select" />);
    expect(yellow.match(/antagen/g)?.length).toBeGreaterThanOrEqual(count);
    const confirmed = confirmAll(proposal);
    expect(proposed(confirmed.model)).toBe(0);
    expect(renderToStaticMarkup(<Canvas drawing={confirmed} circuits={[]} selected={[]} route={null} tool="select" />)).not.toContain("antagen");
    // Drawn things are not the drawing's proposal, and stay as they are.
    expect(proposed(d.model)).toBe(0);
    expect(confirmAll(d)).toEqual(d);
  });
});
