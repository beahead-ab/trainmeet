import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Connection, Panel, TrackPlan } from "./api";
import { asRoute, failuresFirst, handlers, progressText, provaCalls, ProvaView, provkorText, routeTitle, simulatorText, type Calls, type ProvaData, type ProvaRoute, type ProvaWay, type Provkor } from "./Prova";

// Studio › Prova (#85 del c) on the made-up Provby, as TKL's server sends it: a line, a switch and
// a siding, with three of its routes. Nothing here names a real station (RS13).

const panel: Panel = {
  source: "engine",
  width: 30,
  height: 9,
  cell: [24, 24],
  angle: "45",
  rows: 2,
  shortened: false,
  fields: [],
  lines: [
    { piece: "a", track: null, cells: [[3, 2], [10, 2]], real: [], free: false },
    { piece: "b", track: "1", cells: [[10, 2], [27, 2]], real: [], free: false },
    { piece: "c", track: "2", cells: [[10, 2], [13, 5], [20, 5]], real: [], free: false },
  ],
  nodes: [],
  switches: [],
  signals: [],
  labels: [],
  track_names: [],
  tables: [],
  platforms: [],
  building: null,
  real_box: null,
};

const plan = { panel } as TrackPlan;

const route = (o: Partial<ProvaRoute> & Pick<ProvaRoute, "start" | "end" | "result">): ProvaRoute => ({ kind: "train", pieces: ["a", "b"], reason: null, ...o });

const passedIn = route({ start: "In", end: "12", result: "passed" });
const failed = route({ start: "In", end: "22", result: "failed", pieces: ["a", "c"], reason: "Ingen återrapport från växel 1 inom 6 sekunder." });
const shunting = route({ kind: "shunting", start: "D", end: "22", result: "passed", pieces: ["c"] });

const idleProvkor: Provkor = { available: false, reason: "Provkör kräver LocoNet anslutet till banan.", running: false, done: 0, total: 0, route: null, waiting: null, question: null, routes: [], finished: null };

const base: ProvaData = {
  level: 3,
  simulator: "pretend",
  running: false,
  done: 0,
  total: 11,
  routes: [],
  passed: 0,
  failed: 0,
  tried: false,
  started: null,
  finished: null,
  invalidated: false,
  message: "Stationen är inte provad i Studio › Prova.",
  provkor: idleProvkor,
};

const running: ProvaData = { ...base, running: true, done: 3, routes: [passedIn, shunting, failed], passed: 2, failed: 1, message: null, started: "2026-11-18T12:00:00Z" };
const klart: ProvaData = { ...base, done: 11, routes: [passedIn, shunting], passed: 11, tried: true, message: "Klart: varje väg gick igenom. Stationen kan öppnas i Ställverket.", finished: "2026-11-18T12:00:05Z" };

const nothing = { onStart: () => undefined, onStop: () => undefined, onProvkor: () => undefined, onAnswer: () => undefined, onProvkorStop: () => undefined, onChoose: () => undefined, onConnect: () => undefined };

const render = (view: ProvaData, chosen: ProvaWay | null = null, connection: Connection | null = null) =>
  renderToStaticMarkup(<ProvaView view={view} plan={plan} chosen={chosen} connection={connection} {...nothing} />);

/** Calls that answer with the next view and remember what was asked. */
function pretend(next: ProvaData) {
  const asked: string[] = [];
  const answer =
    (name: string) =>
    (...args: unknown[]) => {
      asked.push(`${name}(${args.map((a) => JSON.stringify(a)).join(", ")})`);
      return Promise.resolve(next);
    };
  const calls: Calls = {
    view: answer("view"),
    start: answer("start"),
    stop: answer("stop"),
    provkorStart: answer("provkorStart"),
    provkorAnswer: answer("provkorAnswer"),
    provkorStop: answer("provkorStop"),
    plan: () => Promise.resolve(plan),
    connection: () => Promise.resolve({ connected: false } as Connection),
    connect: () => Promise.resolve({ connected: true, preview: true } as Connection),
  };
  const views: ProvaData[] = [];
  const chosen: (ProvaWay | null)[] = [];
  const done = handlers(calls, (work) => void work().then((v) => views.push(v)), (r) => chosen.push(r));
  return { asked, views, chosen, done };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Prova", () => {
  it("runs in the background and shows the progress (STUDIO-05, STUDIO-27)", async () => {
    const html = render(running);
    expect(html).toContain("<h1>Prova</h1>");
    expect(html).toContain('<progress max="11" value="3" aria-label="Prova"></progress>');
    expect(html).toContain("Provat 3 av 11 vägar · 1 gick inte …");
    expect(html).toContain(">Avbryt</button>");
    expect(html).not.toContain("Starta Prova");
    expect(progressText(running)).toBe("Provat 3 av 11 vägar · 1 gick inte");
    expect(simulatorText(running)).toBe("Nivå 3 · låtsas-LocoNet: växlarna återrapporterar och spårledningarna styr tåget");
    expect(simulatorText({ ...base, level: 2, simulator: "kor" })).toBe("Nivå 2 · ställverket med Kör, sektion för sektion");
    const { asked, views, done } = pretend(running);
    done.onStart();
    done.onStop();
    await Promise.resolve();
    expect(asked).toEqual(["start()", "stop()"]);
    expect(views[0]?.running).toBe(true);
    const before = render(base);
    expect(before).toContain(">Starta Prova</button>");
    expect(before).toContain("Stationen är inte provad i Studio › Prova.");
  });

  it("lists the routes with the failures first, each with its reason", () => {
    expect(failuresFirst([passedIn, shunting, failed]).map(routeTitle)).toEqual(["Tågväg In → 22", "Tågväg In → 12", "Växlingsväg D → 22"]);
    const html = render(running);
    const order = [...html.matchAll(/<span class="prova-namn">([^<]+)<\/span>/g)].map((m) => m[1]);
    expect(order).toEqual(["Tågväg In → 22", "Tågväg In → 12", "Växlingsväg D → 22"]);
    expect(html).toContain('<button type="button" class="prova-vag failed" aria-pressed="false"><span class="prova-markering" aria-label="Gick inte">✗</span><span class="prova-namn">Tågväg In → 22</span><span class="prova-skal">Ingen återrapport från växel 1 inom 6 sekunder.</span></button>');
    expect(html).toContain('aria-label="Gick igenom">✓</span>');
  });

  it("shows a route on the panel when it is clicked, as Spårplan does", async () => {
    const { chosen, done } = pretend(running);
    done.onChoose(failed);
    expect(chosen).toEqual([failed]);
    const html = render(running, failed);
    expect(html).toContain("Tågväg In → 22 <button");
    expect(html).toContain(">Släck</button>");
    expect(html).toContain('<button type="button" class="prova-vag failed" aria-pressed="true">');
    const lit = html.slice(html.indexOf('class="vag-linje tagvag"'));
    expect(lit).toContain('data-piece="a"');
    expect(lit).toContain('data-piece="c"');
    expect(lit.slice(0, lit.indexOf("</g>"))).not.toContain('data-piece="b"');
    expect(asRoute(shunting)).toEqual({ kind: "shunting", start: "D", end: "22", pieces: ["c"], positions: {}, turntable: null });
    expect(render(running, shunting)).toContain('class="vag-linje vaxling"');
    expect(render(running)).toContain("Klicka på en väg nedanför för att se den på panelen.");
  });

  it("says Klart when every route has passed, and that a changed model must be tried again", () => {
    const html = render(klart);
    expect(html).toContain('<p class="prova-klart" role="status"><strong>Klart</strong> · Varje väg gick igenom. Stationen kan öppnas i Ställverket.</p>');
    expect(html).toContain(">Prova igen</button>");
    expect(html).toContain("11 gick igenom · 0 gick inte · 11 vägar");
    const changed = render({ ...base, invalidated: true, message: "Stationsmodellen har ändrats sedan Prova kördes: prova stationen igen." });
    expect(changed).toContain('<p class="notis varning" role="status">Stationsmodellen har ändrats sedan Prova kördes: prova stationen igen.</p>');
    expect(changed).not.toContain("Klart");
    const none = render({ ...base, level: 0, simulator: null, total: 0, message: "Stationen har ingen stationsmodell." });
    expect(none).toMatch(/<button type="button" class="primar" disabled="">Starta Prova<\/button>/);
  });

  it("asks the owner in Provkör, with LocoNet to the layout (STUDIO-05)", async () => {
    expect(render(base)).toContain("Provkör kräver LocoNet anslutet till banan.");
    expect(render(base)).toMatch(/<button type="button" disabled="">Starta Provkör<\/button>/);
    const waiting: Provkor = { ...idleProvkor, available: true, reason: null, running: true, done: 2, total: 11, route: { kind: "train", start: "21", end: "Ut", pieces: ["a"] }, waiting: "Väntar på återrapport från växel 1 …" };
    const html = render({ ...base, provkor: waiting });
    expect(html).toContain('role="alertdialog"');
    expect(html).toContain("Provkör: väg 3 av 11");
    expect(html).toContain("Väntar på återrapport från växel 1 …");
    expect(html).toMatch(/<button type="button" class="primar" disabled="">Ja, det stämmer<\/button>/);
    const asking: Provkor = { ...waiting, waiting: null, question: "Visar signalen 21 kör, och ligger växlarna rätt för tågvägen 21 → Ut? Följ vägen på banan." };
    const shown = render({ ...base, provkor: asking });
    expect(shown).toContain("Visar signalen 21 kör, och ligger växlarna rätt för tågvägen 21 → Ut?");
    expect(shown).toContain('<button type="button" class="primar">Ja, det stämmer</button>');
    expect(provkorText(asking)).toBe("Provkör: väg 3 av 11");
    const { asked, done } = pretend(base);
    done.onProvkor();
    done.onAnswer("right");
    done.onAnswer("wrong");
    done.onAnswer("skip");
    done.onProvkorStop();
    expect(asked).toEqual(["provkorStart()", 'provkorAnswer("right")', 'provkorAnswer("wrong")', 'provkorAnswer("skip")', "provkorStop()"]);
    const after = render({ ...base, provkor: { ...idleProvkor, available: true, reason: null, done: 2, routes: [failed, passedIn] } });
    expect(after).toContain("Provkört 2 vägar");
  });

  it("connects Prova only to a preview run, with its code (STUDIO-12)", async () => {
    const form = render(base);
    expect(form).toContain("Provkörningens kod");
    expect(form).toContain(">Koppla Prova till provkörningen</button>");
    const preview = render(base, null, { connected: true, preview: true, hub_name: "Hubben", status: "approved" } as Connection);
    expect(preview).toContain("Ansluten till en provkörning på Hubben · godkänd.");
    const real = render(base, null, { connected: true, preview: false } as Connection);
    expect(real).toContain("TKL är ansluten till en riktig träff.");
    const sent: unknown[] = [];
    vi.stubGlobal("fetch", (url: string, init: RequestInit) => {
      sent.push([url, init.method, JSON.parse(String(init.body))]);
      return Promise.resolve(new Response(JSON.stringify({ connected: true, preview: true }), { status: 200 }));
    });
    const made = await provaCalls.connect("http://hubben.local", "123456");
    expect(made.preview).toBe(true);
    expect(sent).toEqual([["/api/tkl/1/connection", "POST", { address: "http://hubben.local", code: "123456", prova: true }]]);
  });
});
