import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { HubInfo } from "./api";
import { Screen } from "./App";
import { momentsOf } from "./korplan";
import type { Page } from "./photo";
import type { LokState } from "./store";
import { CLOCK, hub, korplan, lokWith, me, offer, PAPER_ID, paperKorplan, paperMe, paperService, presence, price, services } from "./testdata";

// Efter pappret in the phone (LOK-13, LOK-18, LOK-29, LOK-33; foto-saknas.jpg, papper.jpg),
// against a fetch that answers like the hub (hub/driver_api.py, hub/paper_reading.py).

const DRIVERS = "/api/drift/1/drivers";
const LOG_IN = "Pappret läses med dina egna tokens. Logga in med TrainMeet ID, eller be trafikledningen om hjälp.";
const NO_AI = "Hubben har ingen AI som kan läsa pappret. Be trafikledningen om hjälp.";
const HUB = { name: "Hubben", set_up: true, logged_in: false, id_login: true, person: null } as unknown as HubInfo;

const at = (time: string) => {
  const [h, m, s] = time.split(":").map(Number);
  return (h ?? 0) * 3600 + (m ?? 0) * 60 + (s ?? 0);
};

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-11-18T09:00:00Z"));
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

function draw(state: Partial<LokState>, time = "06:20:00") {
  const lok = lokWith(state);
  lok.clock.accept({ ...CLOCK, seconds: at(time) });
  return { lok, html: renderToStaticMarkup(<Screen lok={lok} state={lok.state} now={lok.clock.seconds()} />) };
}

const page = (n: number): Page => ({ picture: new Blob([`sida ${n}, ritad på nytt`], { type: "image/jpeg" }), preview: `data:image/jpeg;base64,c2lkYS${n}` });
const photo = (n: number) => new File([`IMG ${n}`], `IMG_00${n}.jpg`, { type: "image/jpeg" });

/** A Lok whose photos are "drawn anew" by a stand-in: the canvas itself is in photo.test.ts. */
function lokReading(state: Partial<LokState> = {}) {
  const lok = lokWith({ me: me({ service: null, start: null }), route: "papper", ...state });
  let n = 0;
  (lok as unknown as { redraw: (file: File) => Promise<Page> }).redraw = async () => page((n += 1));
  return lok;
}

describe("Fota pappret: the price and who pays before anything is read (LOK-33)", () => {
  it("shows the price, who pays and the balance, then Läs pappret", () => {
    const { html } = draw({ me: me({ service: null, start: null }), route: "papper", pages: [page(1), page(2)], price: price() });
    expect(html).toContain("Fota pappret");
    expect(html).toContain('accept="image/*" capture="environment" multiple=""');
    expect(html).toContain('alt="Framsidan"');
    expect(html).toContain('aria-label="Ta bort sida 2"');
    expect(html).toContain("Läsningen");
    expect(html).toContain("24 tokens");
    expect(html).toContain("2 sidor · 12 tokens per sida");
    expect(html).toContain('class="lok-betalare">Träffens tokens<');
    expect(html).toContain("Betalas av Provbanans klubb · 480 tokens kvar");
    const [cost, read] = [html.indexOf("24 tokens"), html.indexOf("Läs pappret · 24 tokens")];
    expect(cost).toBeGreaterThan(-1);
    expect(cost).toBeLessThan(read);
    const own = draw({ me: me({ service: null, start: null }), route: "papper", pages: [page(1)], price: price({ pages: 1, price: 0, per_page: 0, paid_by: "hub", payer: "Hubbens egen AI", available: null }) }).html;
    expect(own).toContain("Hubbens egen AI läser, utan tokens.");
    expect(own).toContain("</svg> Läs pappret</button>");
    const english = draw({ me: me({ service: null, start: null }), route: "papper", pages: [page(1), page(2)], price: price(), language: "en" }).html;
    expect(english).toContain("2 pages · 12 tokens a page");
    expect(english).toContain("Paid by Provbanans klubb · 480 tokens left");
    expect(english).toContain("Read the paper · 24 tokens");
  });

  it("does not offer the reading when it cannot be read, and says why, with the login where it helps", () => {
    const notReady = price({ ready: false, paid_by: null, payer: null, available: null, message: LOG_IN, log_in: true });
    const { html } = draw({ me: me({ service: null, start: null }), route: "papper", pages: [page(1)], price: notReady, hub: HUB });
    expect(html).toContain(LOG_IN);
    expect(html).toContain(">Logga in med TrainMeet ID<");
    expect(html).toContain('href="/api/hub/id/login?next=%2Flokforaren%2Fpapper&amp;lang=sv"');
    expect(html).not.toContain("Läs pappret");
    expect(draw({ me: me({ service: null, start: null }), route: "papper", pages: [page(1)], price: notReady, hub: HUB, language: "en" }).html).toContain("The paper is read with your own tokens. Log in with TrainMeet ID");
    // No AI: logging in would not help.
    const noAi = draw({ me: me({ service: null, start: null }), route: "papper", pages: [page(1)], price: { ...notReady, message: NO_AI, log_in: false }, hub: HUB }).html;
    expect(noAi).toContain(NO_AI);
    expect(noAi).not.toContain("Logga in med TrainMeet ID");
    // Too little left on the meet's balance.
    const short = price({ ready: false, available: 10, message: "Saldot räcker inte: 10 tokens kvar, 24 behövs. Be trafikledningen om hjälp." });
    expect(draw({ me: me({ service: null, start: null }), route: "papper", pages: [page(1), page(2)], price: short }).html).toContain("Saldot räcker inte: 10 tokens kvar, 24 behövs.");
    expect(draw({ me: me({ service: null, start: null }), route: "papper", pages: [page(1), page(2)], price: short, language: "en" }).html).toContain("The balance is not enough: 10 tokens left, 24 needed.");
  });

  it("asks the price before the photos, so that the driver knows first", async () => {
    const lok = lokReading();
    const { calls } = hub({ [`GET ${DRIVERS}/paper/price`]: { body: price({ pages: 1, price: 12 }) } });
    await lok.loadPrice();
    expect(calls.map((c) => c.path)).toEqual([`${DRIVERS}/paper/price?pages=1`]);
    expect(lok.state.price?.price).toBe(12);
    const html = renderToStaticMarkup(<Screen lok={lok} state={lok.state} now={null} />);
    expect(html).toContain("12 tokens per sida");
    expect(html).toContain("Fota framsidan");
    expect(html).not.toContain("Läs pappret");
  });
});

describe("reading the paper (LOK-29)", () => {
  it("sends 1–4 pages drawn anew as a form, with the price the driver saw", async () => {
    const lok = lokReading();
    const { calls } = hub({
      [`GET ${DRIVERS}/paper/price`]: (url) => {
        const pages = Number(url.searchParams.get("pages"));
        return { body: price({ pages, price: 12 * pages }) };
      },
      [`POST ${DRIVERS}/paper`]: { status: 201, body: paperService() },
      [`GET ${DRIVERS}/me`]: { body: paperMe() },
      [`GET ${DRIVERS}/korplan`]: { body: paperKorplan() },
    });
    expect(await lok.readPaper()).toBe(false); // nothing photographed yet
    await lok.addPages([photo(1), photo(2), photo(3)]);
    expect(lok.state.pages).toHaveLength(3);
    expect(calls.at(-1)?.path).toBe(`${DRIVERS}/paper/price?pages=3`);
    await lok.addPages([photo(4), photo(5)]);
    expect(lok.state.pages).toHaveLength(4);
    expect(lok.state.problem).toBe("Högst 4 sidor. De första är med.");
    expect(lok.state.price?.price).toBe(48);
    expect(await lok.readPaper()).toBe(true);
    const sent = calls.find((c) => c.method === "POST")!;
    expect(sent.path).toBe(`${DRIVERS}/paper?price=48`);
    const form = sent.body as FormData;
    const parts = form.getAll("pages") as File[];
    expect([...form.keys()]).toEqual(["pages", "pages", "pages", "pages"]);
    expect(parts.map((part) => [part.name, part.type])).toEqual([1, 2, 3, 4].map((n) => [`sida${n}.jpg`, "image/jpeg"]));
    expect(await parts[0]!.text()).toBe("sida 1, ritad på nytt");
    // Read: the photos are gone from the phone, and the page shows the paper beside the plan.
    expect(lok.state.pages).toEqual([]);
    expect(lok.state.me?.paper?.status).toBe("waiting");
    expect(lok.state.route).toBe("papper");
    const one = lokReading();
    const { calls: again } = hub({ [`GET ${DRIVERS}/paper/price`]: { body: price({ pages: 1, price: 12 }) }, [`POST ${DRIVERS}/paper`]: { status: 201, body: paperService({ pages: 1 }) }, [`GET ${DRIVERS}/me`]: { body: paperMe() }, [`GET ${DRIVERS}/korplan`]: { body: paperKorplan() } });
    await one.addPages([photo(1)]);
    await one.readPaper();
    expect((again.find((c) => c.method === "POST")!.body as FormData).getAll("pages")).toHaveLength(1);
  });

  it("says 402, 403 and 409 as messages: the hub's words in Swedish, and English in English", async () => {
    const answers = {
      402: { status: 402, body: { detail: "Saldot räcker inte: 10 tokens kvar, 24 behövs. Be trafikledningen om hjälp." } },
      403: { status: 403, body: { detail: LOG_IN } },
      409: { status: 409, body: { detail: "Läsningen kostar nu 36 tokens. Se priset och läs igen." } },
    } as const;
    for (const [status, answer] of Object.entries(answers)) {
      for (const language of ["sv", "en"] as const) {
        const lok = lokReading({ pages: [page(1), page(2)], price: price(), language });
        const { calls } = hub({ [`POST ${DRIVERS}/paper`]: answer, [`GET ${DRIVERS}/paper/price`]: { body: price({ price: 36 }) } });
        expect(await lok.readPaper()).toBe(false);
        expect(lok.state.problem).toBe(language === "sv" ? answer.body.detail : lok.text.paperErrors[Number(status)]);
        // The photos stay, and the price is asked again.
        expect(lok.state.pages).toHaveLength(2);
        expect(calls.at(-1)?.path).toBe(`${DRIVERS}/paper/price?pages=2`);
      }
    }
    const lok = lokReading({ pages: [page(1)], price: price(), language: "en" });
    hub({ [`POST ${DRIVERS}/paper`]: { status: 409, reason: "one_service", body: { detail: "Du har redan en tjänst. Släpp den först." } }, [`GET ${DRIVERS}/me`]: { body: me() }, [`GET ${DRIVERS}/korplan`]: { body: korplan() } });
    await lok.readPaper();
    expect(lok.state.problem).toBe("You already have a service. Release it first.");
    const html = draw({ me: me(), route: "papper" }).html;
    expect(html).toContain("Du har redan en tjänst. Släpp den först om du ska köra efter pappret.");
    expect(html).not.toContain('capture="environment"');
  });
});

describe("the paper beside the plan first (LF16, foto-saknas.jpg)", () => {
  it("shows the front as read, the hub's comparison and the nearest services, then Kör efter pappret", () => {
    const { html } = draw({ me: paperMe(), route: "papper" });
    expect(html).toContain("Pappret och planen");
    expect(html).toContain("På pappret");
    expect(html).toContain("Tjänst 24");
    expect(html).toContain(`src="/api/drift/1/drivers/paper/${PAPER_ID}/pages/1"`);
    expect(html).toContain("Green Cargo · tåg G 4521");
    expect(html).toContain("Efter pappret · Väntar på trafikledningen");
    const [said, nearest, three, one, run, list] = [
      html.indexOf("<b>Ingen tjänst startar 06:31 vid Norrby.</b> Närmast: 3 kl. 06:35, 1 kl. 06:00."),
      html.indexOf("Närmast i planen"),
      html.indexOf("06:35 · Norrby → Norrby"),
      html.indexOf("Bo kör"),
      html.indexOf(">Kör efter pappret<"),
      html.indexOf(">Visa hela listan<"),
    ];
    expect(said).toBeGreaterThan(-1);
    expect([said, nearest, three, one, run, list]).toEqual([...[said, nearest, three, one, run, list]].sort((a, b) => a - b));
    expect(html).toContain("Trafikledningen har fått veta att tjänsten saknas i planen.");
  });

  it("takes a planned service instead when the driver picks one: the paper is let go", async () => {
    const lok = lokWith({ me: paperMe(), korplan: paperKorplan(), route: "papper" });
    const three = paperService().candidates![0]!;
    // As the page does when a candidate is tapped: the paper's number goes with it (LOK-19).
    lok.paperHint("24");
    lok.select(three);
    expect(lok.state.route).toBe("tjanst");
    const card = renderToStaticMarkup(<Screen lok={lok} state={lok.state} now={null} />);
    expect(card).toContain("24 på ditt papper");
    expect(card).toMatch(/<button type="button" class="lok-knapp primar stor">Ta tjänsten i stället<\/button>/);
    expect(card).toContain("Pappret släpps, och tjänsten i planen blir din.");
    const { calls } = hub({
      [`POST ${DRIVERS}/claim`]: { body: me({ service: offer("3", { taken: true, driver: "forare-a" }), paper: null }) },
      [`GET ${DRIVERS}/korplan`]: { body: korplan({ number: "3" }) },
    });
    expect(await lok.claim(three, lok.state.paper)).toBe(true);
    expect(calls.map((c) => [c.method, c.path, c.body])).toEqual([
      ["POST", `${DRIVERS}/claim`, { kind: "duty", id: "d3" }],
      ["GET", `${DRIVERS}/korplan`, undefined],
    ]);
    expect(lok.state.route).toBe("korplan");
    expect(lok.paperOf(three)).toBe("24");
  });
});

describe("the körplan after the paper (LOK-13, LOK-29, papper.jpg)", () => {
  it("is marked Efter pappret in the head, with where it stands and the photos to compare", () => {
    const { html } = draw({ me: paperMe(), korplan: paperKorplan(), route: "korplan" }, "06:45:00");
    expect(html).toContain("Tjänst 24");
    expect(html).toContain('<span class="lok-papper">Efter pappret</span>');
    expect(html).toContain("G 4521 · Norrby → Sjövik");
    expect(html).toContain("<b>Väntar på trafikledningen.</b> Avläst från dina foton. Tjänsten finns inte i planen. Tågklarerarna ser tåget när trafikledningen har godkänt det.");
    expect(html).toContain('aria-label="Sida 1 av 2"');
    expect(html).toContain('aria-label="Sida 2 av 2"');
    expect(html).toContain('aria-label="Fotona av pappret"');
    expect(html).not.toContain('aria-label="Tjänstens kort"');
    expect(html.indexOf("Efter pappret")).toBeLessThan(html.indexOf('class="lok-tidsaxel"'));
  });

  it("shows a time that could not be read as unknown, never guessed, and a place not in the meet by its name", () => {
    const { html } = draw({ me: paperMe(), korplan: paperKorplan(), route: "korplan" }, "06:50:00");
    // Åsen: the arrival 06:49 was read; the departure was not, and is not made up from it.
    expect(html.match(/06:49/g)).toHaveLength(1);
    expect(html).toContain('<span class="lok-tid tm-mono">–<small class="lok-olaslig">oläslig</small></span>');
    expect(html).toContain("Avgång · tiden gick inte att läsa");
    // Next is that departure: its time is unknown, and so are the minutes to it.
    expect(html).toMatch(/<span class="lok-overrubrik">Avgång<\/span><span>tiden gick inte att läsa<\/span>/);
    expect(html).toMatch(/<b>Åsen<\/b><b class="tm-mono">–<\/b>/);
    expect(html).toContain("<b>Bruket</b><span class=\"lok-bricka\">inte i träffen</span>");
    // Bruket is not one of the meet's places: check-in there cannot be offered.
    const atBruket = draw({ me: paperMe(), korplan: paperKorplan(), route: "korplan" }, "06:55:30").html;
    expect(atBruket).not.toContain("Checka in · Bruket");
    expect(atBruket).toMatch(/<\/span> Checka in<\/button>/);
    // In English too.
    expect(draw({ me: paperMe(), korplan: paperKorplan(), route: "korplan", language: "en" }, "06:50:00").html).toContain("–<small class=\"lok-olaslig\">unreadable</small>");
  });

  it("keeps the rows whose times could not be read in their place, until the next time read has passed", () => {
    const rows = paperKorplan().rows ?? [];
    const unreadable = (index: number) => paperService().rows?.[index]?.unreadable ?? false;
    const plain = momentsOf(rows);
    expect(plain.some((m) => m.unknown)).toBe(false);
    expect(plain.map((m) => `${m.row.place_name} ${m.kind}`)).not.toContain("Åsen departure");
    const moments = momentsOf(rows, unreadable);
    const unknown = moments.filter((m) => m.unknown);
    expect(unknown.map((m) => `${m.row.place_name} ${m.kind}`)).toEqual(["Åsen departure"]);
    // It stands just before Bruket's arrival, the next time read.
    const index = moments.indexOf(unknown[0]!);
    expect(moments[index - 1]?.row.place_name).toBe("Åsen");
    expect(moments[index + 1]?.row.place_name).toBe("Bruket");
    expect(unknown[0]!.t).toBe(at("06:55"));
  });

  it("says waiting, approved with the train number, and rejected with the reason", () => {
    const approved = draw({ me: paperMe("approved", { train: "x-c-papper", train_number: "G 4521" }), korplan: paperKorplan("approved"), route: "korplan" }, "06:45:00").html;
    expect(approved).toContain("<b>Godkänd · tåg G 4521.</b> Tågklarerarna ser tåget nu, märkt efter pappret.");
    expect(approved).toContain('<span class="lok-papper">Efter pappret</span>');
    expect(approved).not.toContain("Väntar på trafikledningen");
    const english = draw({ me: paperMe(), korplan: paperKorplan(), route: "korplan", language: "en" }, "06:45:00").html;
    expect(english).toContain("<b>Waiting for the dispatcher.</b> Read from your photos.");
    expect(english).toContain('<span class="lok-papper">After the paper</span>');
    const rejected = me({ service: null, start: null, paper: paperService({ status: "rejected", reason: "Tjänst 3 är samma. Ta den." }) });
    const plan = draw({ me: rejected, route: "korplan" }).html;
    expect(plan).toContain("Efter pappret · Avslagen");
    expect(plan).toContain("Trafikledningen avslog tjänsten efter pappret: Tjänst 3 är samma. Ta den.");
    expect(plan).toContain(">Välj en annan tjänst<");
    // After rejection the driver takes another service.
    const list = draw({ me: rejected, services: services(), route: "tag" }).html;
    expect(list).toContain("Trafikledningen avslog tjänsten efter pappret: Tjänst 3 är samma. Ta den.");
    expect(lokWith({ me: rejected }).mayTake()).toBe(true);
  });

  it("tells the driver as soon as Trafikledningen has decided", async () => {
    const lok = lokWith({ me: paperMe(), korplan: paperKorplan() });
    hub({ [`GET ${DRIVERS}/me`]: { body: paperMe("approved", { train: "x-c-papper", train_number: "G 4521" }) }, [`GET ${DRIVERS}/korplan`]: { body: paperKorplan("approved") } });
    await lok.refresh();
    expect(lok.state.notice).toBe("Trafikledningen har godkänt tjänsten efter pappret som tåg G 4521.");
    const other = lokWith({ me: paperMe(), korplan: paperKorplan() });
    hub({ [`GET ${DRIVERS}/me`]: { body: me({ service: null, start: null, paper: paperService({ status: "rejected", reason: "Fel dag." }) }) } });
    await other.refresh();
    expect(other.state.notice).toBe("Trafikledningen avslog tjänsten efter pappret: Fel dag.");
    expect(other.state.korplan).toBeNull();
  });
});

describe("finding the service (LOK-18): the camera, Stämmer inte and Hittar inte min tjänst", () => {
  it("has the camera beside the search, and Hittar inte min tjänst under the list and after a search", () => {
    const { html } = draw({ me: me({ service: null, start: null }), services: services(), route: "tag" });
    expect(html).not.toContain("kommer snart");
    expect(html).toMatch(/<label class="lok-kamera" title="Fota papprets framsida">.*capture="environment"/);
    expect(html).toContain("Hittar inte min tjänst · fota pappret");
    const none = draw({ me: me({ service: null, start: null }), services: services([]), route: "tag", query: "24" }).html;
    expect(none).toContain("Ingen tjänst har numret 24.");
    expect(none).toContain("Stämmer inte · leta på starttiden");
    expect(none).toContain("Hittar inte min tjänst · fota pappret");
    expect(draw({ me: me({ service: null, start: null }), services: services([]), route: "tag", query: "24", language: "en" }).html).toContain("Cannot find my service · photograph the paper");
  });

  it("marks the driver's own service after the paper in Tåg, Förare and Jag", () => {
    const tag = draw({ me: paperMe(), services: services(), route: "tag" }).html;
    expect(tag).toContain("Din tjänst · Efter pappret");
    expect(tag).toContain("Norrby → Sjövik · Väntar på trafikledningen");
    const forare = draw({ me: paperMe(), korplan: paperKorplan(), services: services(), presence: [presence("Kim Ek", { me: true, service_number: "24" })], route: "forare" }).html;
    expect(forare).toContain("tjänst 24 · efter pappret");
    expect(forare).not.toContain("<b>Bruket</b>");
    expect(draw({ me: paperMe(), route: "jag" }).html).toContain("Tjänst 24 · tåg G 4521 · efter pappret");
  });
});
