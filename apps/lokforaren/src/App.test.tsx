import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Korplan } from "./api";
import type { LokState } from "./store";
import { Screen } from "./App";
import { CLOCK, korplan, lokWith, me, offer, presence, row, rows, services } from "./testdata";

// The app as the phone draws it, from the hub's answers (LOK-36, LOK-38).

const at = (time: string) => {
  const [h, m, s] = time.split(":").map(Number);
  return (h ?? 0) * 3600 + (m ?? 0) * 60 + (s ?? 0);
};

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-11-18T09:00:00Z"));
});
afterEach(() => vi.useRealTimers());

function draw(state: Partial<LokState>, time = "06:03:40", clock: Partial<typeof CLOCK> = {}) {
  const lok = lokWith(state);
  lok.clock.accept({ ...CLOCK, ...clock, seconds: at(time) });
  if (lok.state.korplan) lok.marks.note(lok.state.korplan.rows ?? [], at(time));
  return { lok, html: renderToStaticMarkup(<Screen lok={lok} state={lok.state} now={lok.clock.seconds()} />) };
}

const order = (html: string, ...parts: string[]) => parts.map((part) => html.indexOf(part));

describe("an app of its own with the header of every product (LOK-36) and four tabs (LOK-38)", () => {
  it("has the TRAINMEET sign, LOKFÖRAREN in dots, the meet clock and Körplan, Tåg, Förare and Jag", () => {
    const { html } = draw({ me: me(), korplan: korplan(), route: "korplan" });
    expect(html).toContain('alt="TrainMeet"');
    expect(html).toContain('aria-label="Lokföraren"');
    expect(html).toContain("06:03:40");
    expect(html).toContain("GÅR · ×4");
    for (const [route, label] of [["korplan", "Körplan"], ["tag", "Tåg"], ["forare", "Förare"], ["jag", "Jag"]]) {
      expect(html).toContain(`href="/lokforaren/${route}"`);
      expect(html).toContain(`<span>${label}</span>`);
    }
    expect(html).toMatch(/href="\/lokforaren\/korplan" aria-current="page"/);
  });

  it("speaks English too", () => {
    const { html } = draw({ me: me(), korplan: korplan(), route: "korplan", language: "en" });
    expect(html).toContain("<span>Plan</span>");
    expect(html).toContain("<span>Trains</span>");
    expect(html).toContain("Service 1");
    expect(html).toContain("RUNS · ×4");
  });

  it("asks for a name, a language and a level when the phone is not in", () => {
    const { html } = draw({ phase: "join", hub: { id_login: true, name: "Hubben", set_up: true, logged_in: false } as LokState["hub"] });
    expect(html).toContain("Vad heter du?");
    expect(html).toContain("Svenska");
    expect(html).toContain("English");
    expect(html).toContain(">Erfaren<");
    expect(html).toContain("Logga in med TrainMeet ID");
    expect(html).toContain("/api/hub/id/login?next=%2Flokforaren%2F");
    expect(html).not.toContain("tm-bottenmeny");
  });
});

describe("Körplan (LOK-03, LOK-12, LOK-20, LOK-24)", () => {
  it("draws the NU-line in its place on Drift's clock, with the next stop and check-in at the bottom", () => {
    const { html } = draw({ me: me(), korplan: korplan(), route: "korplan" });
    const [norrby, nu, asen] = order(html, "<b>Norrby</b>", 'class="lok-nu"', "<b>Åsen</b>");
    expect(norrby).toBeLessThan(nu!);
    expect(nu).toBeLessThan(asen!);
    expect(html).toContain('aria-label="NU 06:03:40"');
    expect(html).toContain("Ankomst Åsen");
    expect(html).toContain("om 5 min");
    expect(html).toContain("Checka in · Åsen");
    expect(html).not.toContain("Framme");
  });

  it("shows Drift's reality in blue and the clearance's word only when the game has chosen it", () => {
    const real = korplan({
      settings: { reality: true, clearances: true, arrival: false },
      position: { train: "t101", train_number: "101", state: "on_the_way", from_place: "nby", to_place: "asn", section: "s-nby-asn", place: null, delay: 2 },
      rows: [
        row("t101-nby", null, "06:00", { first_of_train: true, real: { passed: true, here: false, arrived: null, departed: "06:02", delay: 2, late_oncoming: [] }, clearance: { status: "approved", to_place: "asn", track: "2" } }),
        ...rows().slice(1),
      ],
    } as Partial<Korplan>);
    const { html } = draw({ me: me(), korplan: real, route: "korplan" });
    expect(html).toContain("avg 06:02");
    expect(html).toContain("Tåg 101 på linjen mot Åsen");
    expect(html).toContain("enligt stationerna");
    expect(html).toContain("101 → Sjövik · 2 min sen");
    expect(html).toContain("Sträckan till Åsen är klar.");
    expect(html).toContain("Tågklareraren i Åsen: 101 tas in på spår 2.");
    const plain = draw({ me: me(), korplan: { ...real, settings: { reality: false, clearances: false, arrival: false } }, route: "korplan" }).html;
    expect(plain).not.toContain("på linjen mot");
    expect(plain).not.toContain("Sträckan till");
  });

  it("marks a change Ändrat for ten game minutes, without acknowledging (LOK-24, LOK-41)", () => {
    const changed = korplan({ rows: [rows()[0]!, row("t101-asn", "06:08", "06:12", { changed: true, track: "2" }), ...rows().slice(2)] });
    const { lok, html } = draw({ me: me(), korplan: changed, route: "korplan" });
    expect(html).toContain('class="lok-andrat">Ändrat<');
    expect(html).toContain("Trafikledningen har ändrat körplanen.");
    vi.advanceTimersByTime(150_000); // ten game minutes at ×4
    lok.clock.accept({ ...CLOCK, seconds: at("06:13:40") });
    const later = renderToStaticMarkup(<Screen lok={lok} state={lok.state} now={lok.clock.seconds()} />);
    expect(later).not.toContain('class="lok-andrat">Ändrat<');
    expect(later).not.toContain("Trafikledningen har ändrat körplanen.");
  });

  it("offers Framme only when the game has chosen it, and only where nobody works (LOK-39)", () => {
    const off = draw({ me: me(), korplan: korplan(), route: "korplan" }).html;
    expect(off).not.toContain("Framme i Åsen");
    const on = korplan({ settings: { reality: false, clearances: false, arrival: true } });
    const allowed = draw({ me: me(), korplan: on, route: "korplan" }).html;
    expect(allowed).toContain("Framme i Åsen");
    expect(allowed).toContain("Åsen är obemannad.");
    expect(allowed).toContain('class="lok-bricka">Obemannad<');
    const manned = korplan({ ...on, rows: [rows()[0]!, row("t101-asn", "06:08", "06:10", { unmanned: false }), ...rows().slice(2)] });
    const there = draw({ me: me(), korplan: manned, route: "korplan" }).html;
    expect(there).not.toContain("Framme i Åsen");
    expect(there).toContain("Checka in · Åsen");
  });

  it("counts down before the start on the meet clock, with the real time beside it (LOK-41)", () => {
    const later = me({ start: { time: "06:30", seconds: at("06:30"), in_game_seconds: 0, in_real_seconds: null } });
    const plan = korplan({ rows: [row("t101-nby", null, "06:30", { first_of_train: true }), row("t101-asn", "06:38", null, { last: true })] });
    const { html } = draw({ me: later, korplan: plan, route: "korplan" }, "06:06:00");
    expect(html).toContain("Tjänsten börjar 06:30 i Norrby");
    expect(html).toContain("24 min");
    expect(html).toContain("≈ 6 min i verklig tid · klockan går ×4");
    expect(html).toContain("Påminnelse");
    expect(html).toContain("Körplanen öppnas");
    expect(html).toContain("Stå som Inväntar start");
    expect(html).not.toContain('class="lok-nu"');
    const waiting = draw({ me: { ...later, driver: { ...later.driver, state: "waiting_start" } }, korplan: plan, route: "korplan" }, "06:06:00").html;
    expect(waiting).toContain("Du står som Inväntar start");
    // Ten minutes before, the körplan opens by itself.
    expect(draw({ me: later, korplan: plan, route: "korplan" }, "06:21:00").html).toContain('class="lok-nu"');
  });
});

describe("the sheets: the four messages and releasing on the line (LOK-23, LOK-25, LOK-35)", () => {
  it("has the four ready messages", () => {
    const { html } = draw({ me: me(), korplan: korplan(), route: "korplan", sheet: "messages" });
    for (const said of ["Försenad", "Står på linjen", "Behöver hjälp", "Loket krånglar"]) expect(html).toContain(`<b>${said}</b>`);
    expect(html).toContain("Skicka: försenad");
    expect(html).toContain("hos tågklarerarna på sträckan");
  });

  it("says that on the line the train stands and the dispatcher gets an alarm at once", () => {
    const onLine = korplan({
      settings: { reality: true, clearances: false, arrival: false },
      position: { train: "t101", train_number: "101", state: "on_the_way", from_place: "nby", to_place: "asn", section: "s-nby-asn", place: null, delay: 0, paper: false },
    });
    const { html } = draw({ me: me(), korplan: onLine, route: "korplan", sheet: "release" });
    expect(html).toContain("Släpp tjänst 1");
    expect(html).toContain("Tåget blir stående på linjen. Trafikledningen får ett larm direkt");
    expect(html).toContain("Paus");
    expect(html).toContain("Tar en annan tjänst");
    expect(html).toContain("Slutar för dagen");
    expect(html).toContain("Släpp tjänsten här");
    // At a station by the stations' word: no alarm to warn of.
    const atStation = { ...onLine, position: { ...onLine.position!, state: "at" as const, place: "asn", from_place: null, to_place: null } };
    expect(draw({ me: me(), korplan: atStation, route: "korplan", sheet: "release" }).html).not.toContain("larm direkt");
    // Without Drift's reality the app says what happens if the train is out, and what the plan says.
    const plain = draw({ me: me(), korplan: korplan(), route: "korplan", sheet: "release" }).html;
    expect(plain).toContain("Enligt körplanen är tåget ute på linjen nu.");
    expect(plain).toContain("Står tåget ute på linjen blir det stående där. Trafikledningen får då ett larm direkt");
  });
});

describe("Tåg (LOK-17, LOK-18, LOK-19, LOK-25, LOK-30)", () => {
  it("lists the services on the driver's level first, the rest in start order, and who drives", () => {
    const list = services([offer("1", { matches_level: true }), offer("2", { level: "easy", start: { time: "06:05", place: "sjv", place_name: "Sjövik" }, taken: true, driver: "forare-b", driver_name: "Bo" }), offer("3", { level: "experienced", start: { time: "06:35", place: "nby", place_name: "Norrby" } })]);
    const { html } = draw({ me: me({ service: null }), services: list, route: "tag" });
    const [fits, one, all, two, three] = order(html, "Passar din nivå · Medel", ">1</span>", "Alla 3 tjänster i startordning", ">2</span>", ">3</span>");
    expect(fits).toBeLessThan(one!);
    expect(one).toBeLessThan(all!);
    expect(all).toBeLessThan(two!);
    expect(two).toBeLessThan(three!);
    expect(html).toContain("Bo kör");
    expect(html).toContain("till 07:34 · över din nivå");
    expect(html).toContain("Startar 06:35");
  });

  it("shows a hit on the paper's number as a front to compare with the paper", () => {
    const lok = lokWith({ me: me({ service: null }), services: services([offer("5", { exact: true })]), route: "tag", query: "5" });
    lok.clock.accept(CLOCK);
    const html = renderToStaticMarkup(<Screen lok={lok} state={lok.state} now={lok.clock.seconds()} />);
    expect(html).toContain("Träff på numret 5");
    expect(html).toContain("Jämför med framsidan på ditt papper.");
    expect(html).toContain("Det är min tjänst");
    expect(html).toContain("Stämmer inte · leta på starttiden");
  });

  it("puts a service released on the line first, to take over (LOK-25)", () => {
    const list = services([offer("4", { released_on_line: true, level: "easy" }), offer("1")]);
    const { html } = draw({ me: me({ service: null }), services: list, route: "tag" });
    expect(html.indexOf("Står utan förare")).toBeLessThan(html.indexOf("Alla"));
    expect(html).toContain("Ta över och kör vidare");
  });

  it("shows a service handed out as given by the dispatcher (LOK-30)", () => {
    const { html } = draw({ me: me({ claimed_by: "dispatcher" }), services: services(), route: "tag" });
    expect(html).toContain("Från trafikledningen");
    expect(html).toContain(">Ta tjänsten<");
    expect(html).toContain(">Inte nu<");
    const seen = draw({ me: me({ claimed_by: "dispatcher" }), services: services(), route: "tag", seen: ["duty:d1"] }).html;
    expect(seen).not.toContain("Från trafikledningen");
  });
});

describe("Förare and Jag (LOK-27, LOK-37)", () => {
  it("hides the names and photos when the API gives none, and never shows another's photo it did not give", () => {
    const list = [
      presence("Kim Ek", { me: true, service_number: "1", checkin: { place: "asn", place_name: "Åsen", track: null, train: "t101", train_number: "101", model_time: "06:09", age_seconds: 30, fading: false } }),
      presence(null, { service_number: "2", train_number: "102" }),
      presence(null, { driver: { ...presence(null).driver, id: "forare-c", state: "pause" } }),
    ];
    const { html } = draw({ me: me(), korplan: korplan(), presence: list, services: services(), route: "forare" });
    expect(html).toContain("3 förare på Provbanan");
    expect(html).toContain("På banan nu · längs din tjänst");
    expect(html).toContain("<b>Förare</b>");
    expect(html).toContain("Paus");
    expect(html).toContain("tjänst 2 · tåg 102");
    expect(html).toContain("Namnen visas på träffens nät eller för den som är inloggad.");
    expect(html).not.toContain("<img class=\"lok-ikon");
    expect(html).toContain("Lediga tjänster · nästa börjar 06:00");
    expect(html).toContain("Checka in · station eller Paus");
  });

  it("shows a photo only where the API gives its address", () => {
    const shown = presence("Bo", { driver: { ...presence("Bo").driver, photo: "/api/drift/1/drivers/photos/forare-b?v=1" }, service_number: "2" });
    const { html } = draw({ me: me(), presence: [shown], services: services(), route: "forare" });
    expect(html).toContain('src="/api/drift/1/drivers/photos/forare-b?v=1"');
  });

  it("has the name, the service, Paus or Inväntar start, the reminders, level, language, theme and leaving", () => {
    const { html } = draw({ me: me(), route: "jag", papers: { "duty:d1": "34" } });
    expect(html).toContain("<b>Kim Ek</b>");
    expect(html).toContain("Gäst på träffen · inget konto");
    expect(html).toContain("Tjänst 1 · tåg 101, 104 · 34 på ditt papper");
    expect(html).toContain(">Inväntar start<");
    expect(html).toContain("20 och 10 min före start, med ljud");
    expect(html).toContain(">Min nivå<");
    expect(html).toContain(">Mörkt<");
    expect(html).toContain(">Ljust<");
    expect(html).toContain("Lämna träffen");
  });

  it("shows the general instructions as text and the PDF (LOK-34)", () => {
    const instructions = { text: { sv: "Före start\nHämta ditt köruppdrag hos lokledaren.\n\nPå linjen\nKör aldrig ut utan besked." }, pdf: "/api/drift/1/drivers/instructions.pdf", filename: "instruktioner.pdf" };
    const { html } = draw({ me: me(), route: "instruktioner", instructions });
    expect(html).toContain("<h2>Före start</h2>");
    expect(html).toContain("Hämta ditt köruppdrag hos lokledaren.");
    expect(html).toContain('href="/api/drift/1/drivers/instructions.pdf"');
    expect(html).toContain("Arrangörens PDF · instruktioner.pdf");
  });
});
