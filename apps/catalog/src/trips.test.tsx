import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { Session, Trip, TripRow, TripSummary, Vehicle } from "./api";
import { Shell } from "./App";
import type { Ctx } from "./common";
import { text } from "./i18n";
import { meetLine, MeetsView, rowLine, simulatedTags, TripView } from "./TripsPage";

const ctx = (language: "sv" | "en" = "sv"): Ctx => ({ t: (key, vars) => text(language, key, vars), language });
const NOW = "2026-11-15T12:00:00Z";
const MEET = "3c1e5f0a-2222-4333-8444-955566667777";

function vehicle(id: string, litt: string, number: string, change: Partial<Vehicle> = {}): Vehicle {
  return {
    id,
    version: 1,
    status: "ready",
    kind: "freight_wagon",
    litt,
    number,
    operator: "Green Cargo",
    epoch: "",
    scale: "H0",
    maker: "",
    article_number: "",
    note: "",
    dcc_address: "",
    functions: [],
    place: "5f0c7a2e-0000-4000-8000-000000000001",
    place_name: "Låda 3",
    state: "home",
    lending: null,
    evn: null,
    field_sources: {},
    tags: [],
    tagged: false,
    notices: [],
    picture: null,
    created_at: NOW,
    updated_at: NOW,
    ...change,
  };
}

const tick = (step: "pack" | "arrive" | "home", by: "tap" | "press" = "tap") => ({ step, at: NOW, by });

function row(v: Vehicle, ticks: ReturnType<typeof tick>[]): TripRow {
  return { vehicle: v, added_at: NOW, ticks, last: ticks[ticks.length - 1] ?? null, missing: !ticks.some((k) => k.step === "home") };
}

function trip(rows: TripRow[], change: Partial<Trip> = {}): Trip {
  const done = { pack: 0, arrive: 0, home: 0 };
  for (const r of rows) for (const k of r.ticks) done[k.step] += 1;
  return {
    id: MEET,
    name: "Höstträffen",
    date: "2026-11-13",
    archived_at: null,
    created_at: NOW,
    template_of: null,
    vehicles: rows.length,
    done,
    step: "pack",
    rows,
    ...change,
  };
}

const RC6 = vehicle("1b9d6bcd-bbfd-4b2d-9b5d-ab8dfbbd4be1", "Rc6", "1340", { kind: "locomotive", place_name: "Hyllan" });
const B7 = vehicle("1b9d6bcd-bbfd-4b2d-9b5d-ab8dfbbd4be2", "B7", "5180", { place_name: "Låda 1" });
const HBIS = vehicle("1b9d6bcd-bbfd-4b2d-9b5d-ab8dfbbd4be3", "Hbis", "2253");
const GBS = vehicle("1b9d6bcd-bbfd-4b2d-9b5d-ab8dfbbd4be4", "Gbs", "3087", {
  notices: [{ id: "9b1d2c3e-0000-4000-8000-000000000001", text: "Står på Gårdsjö, spår 3.", at: NOW }],
});

describe("the meets (CAT-174, CAT-183)", () => {
  const summary = (change: Partial<TripSummary>): TripSummary => ({
    id: MEET,
    name: "Höstträffen",
    date: "2026-11-13",
    archived_at: null,
    created_at: NOW,
    template_of: null,
    vehicles: 4,
    done: { pack: 2, arrive: 0, home: 0 },
    step: "pack",
    ...change,
  });

  it("lists the coming ones with how far the trip is, and the earlier ones with a template", () => {
    const spring = summary({ id: "3c1e5f0a-2222-4333-8444-955566667778", name: "Vårträffen", date: "2026-05-09", archived_at: NOW, vehicles: 6, done: { pack: 6, arrive: 6, home: 6 }, step: "home" });
    const html = renderToStaticMarkup(<MeetsView ctx={ctx()} meets={[summary({}), spring]} error={null} />);
    expect(html).toContain(`href="/traffar/${MEET}"`);
    expect(html).toContain("13 november · 4 fordon · 2 av 4 packade");
    expect(html).toContain("Tidigare träffar");
    expect(html).toContain("9 maj · 6 fordon · alla kom hem");
    expect(html).toContain(">Ny träff från den här<");
    expect(html).toContain(">Ny träff<");
    expect(html).toContain("Packlistan är din egen.");
  });

  it("says how many came home when not all did, and when there are no meets", () => {
    expect(meetLine(ctx(), summary({ archived_at: NOW, done: { pack: 4, arrive: 4, home: 3 }, step: "home" }))).toBe("13 november · 4 fordon · 3 av 4 kom hem");
    expect(renderToStaticMarkup(<MeetsView ctx={ctx()} meets={[]} error={null} />)).toContain("Inga träffar än.");
  });
});

describe("the three steps (CAT-176–CAT-178)", () => {
  it("packs: 2 av 4, a tick by pressing the row, and Blippa for att packa", () => {
    const packing = trip([row(RC6, [tick("pack")]), row(B7, [tick("pack", "press")]), row(HBIS, []), row(GBS, [])]);
    const html = renderToStaticMarkup(<TripView ctx={ctx()} trip={packing} step="pack" error={null} reader="nfc" />);
    expect(html).toContain("Höstträffen · 13 november");
    expect(html).toContain(">Packlistan<");
    expect(html).toContain("Blippa fordonet när du lägger det i väskan.");
    expect(html).toMatch(/<b>2 av 4 packade<\/b>/);
    expect(html).toContain('value="2" max="4"');
    expect(html.match(/aria-pressed="true"[^>]*class="cat-resrad"|class="cat-resrad" aria-pressed="true"/g)).toHaveLength(2);
    expect(html).toContain("Ligger i Låda 3");
    expect(html).toContain("Bocka av i Packa");
    expect(html).toContain(">Blippa för att packa<");
    expect(html).toContain(">Ändra packlistan<");
    expect(html).toContain(">Arkivera packlistan<");
  });

  it("shows each step's count in the step switch, and what is left in the box at På plats", () => {
    const arriving = trip([row(RC6, [tick("pack"), tick("arrive")]), row(B7, [tick("pack")])], { step: "arrive" });
    const html = renderToStaticMarkup(<TripView ctx={ctx()} trip={arriving} step="arrive" error={null} reader="nfc" />);
    expect(html).toContain("1 · Packa");
    expect(html).toContain("2 av 2 packade");
    expect(html).toMatch(/aria-pressed="true"><span>2 · På plats/);
    expect(html).toContain("1 av 2 på banan");
    expect(html).toContain("Kvar i lådan");
    expect(html).toContain(">Blippa in<");
  });

  it("at Hem puts what is missing first, with its last tick and what someone said (CAT-179, CAT-180)", () => {
    const home = trip(
      [row(RC6, [tick("pack"), tick("arrive"), tick("home")]), row(GBS, [tick("pack"), tick("arrive")]), row(HBIS, [tick("pack"), tick("arrive"), tick("home", "press")])],
      { step: "home" },
    );
    const html = renderToStaticMarkup(<TripView ctx={ctx()} trip={home} step="home" error={null} reader="nfc" />);
    expect(html).toContain(">Dags att åka hem<");
    expect(html).toContain("2 av 3 i lådan");
    expect(html).toContain("Saknas · 1 fordon");
    expect(html.indexOf("Gbs 3087")).toBeLessThan(html.indexOf("Rc6 1340"));
    expect(html).toContain("Senast blippad i På plats");
    expect(html).toContain("Någon sa till");
    expect(html).toContain("Står på Gårdsjö, spår 3.");
    expect(html).toContain("I lådan · Hyllan");
    expect(html).toContain(">Blippa in i lådan<");
  });

  it("says how the row stands in each step", () => {
    const lent = row(vehicle("1b9d6bcd-bbfd-4b2d-9b5d-ab8dfbbd4be5", "Gbs", "1", { state: "lent", lending: { to: "Olle", since: NOW, until: null } }), []);
    expect(rowLine(ctx(), lent, "pack")).toBe("Utlånad till Olle");
    expect(rowLine(ctx(), row(HBIS, []), "arrive")).toBe("Inte packad");
    expect(rowLine(ctx(), row(HBIS, []), "home")).toBe("Inte bockad under resan");
    expect(rowLine(ctx(), row(HBIS, [tick("pack", "press")]), "home")).toMatch(/^Senast bockad i Packa /);
    expect(rowLine(ctx("en"), row(HBIS, [tick("pack")]), "home")).toMatch(/^Last tapped in Pack /);
  });
});

describe("tapping in the trip", () => {
  it("offers to add a tapped vehicle that is not on the pack list (CAT-181)", () => {
    const html = renderToStaticMarkup(<TripView ctx={ctx()} trip={trip([row(HBIS, [])])} step="pack" error={null} asking={{ uid: "x", title: "Rc6 1340" }} />);
    expect(html).toContain("Rc6 1340 står inte på packlistan. Lägga till det?");
    expect(html).toContain(">Lägg till<");
  });

  it("without NFC takes the tag's address, and in the test environment the simulated tags", () => {
    const sim = { assignment: "a", tag: "b", uid: "6f1d2c1e-6a43-4b8e-9c5a-0c3a7d4f9b21", name: "SIM-001", kind: "sim" as const, address: "https://x/t/6f1d", linked_at: NOW };
    const tags = simulatedTags(ctx().t, [vehicle(HBIS.id, "Hbis", "2253", { tags: [sim] }), RC6]);
    expect(tags).toEqual([{ uid: sim.uid, label: "SIM-001 · Hbis 2253" }]);
    const html = renderToStaticMarkup(<TripView ctx={ctx()} trip={trip([row(HBIS, [])])} step="pack" error={null} reader="none" simulated={tags} />);
    expect(html).toContain("Utan NFC: skanna QR-etiketten, eller skriv taggens adress.");
    expect(html).toContain("Taggens adress eller serienummer");
    expect(html).toContain(">SIM-001 · Hbis 2253<");
    expect(html).not.toContain("Blippa för att packa");
  });
});

describe("an archived pack list (CAT-183)", () => {
  it("does not change, and starts the next meet", () => {
    const done = trip([row(HBIS, [tick("pack"), tick("home")])], { archived_at: NOW, step: "home" });
    const html = renderToStaticMarkup(<TripView ctx={ctx()} trip={done} step="home" error={null} reader="nfc" />);
    expect(html).toContain("Arkiverad 15 november.");
    expect(html).toContain("disabled");
    expect(html).not.toContain("Blippa in i lådan");
    expect(html).not.toContain("Arkivera packlistan");
    expect(html).not.toContain("Ändra packlistan");
    expect(html).toContain(">Ny träff från den här<");
  });
});

describe("the right (CAT-174, CAT-182)", () => {
  it("keeps the meets the owner's own", () => {
    const account = { id: "8a3e1f0c-1111-5222-8333-944455556666", name: "Provkonto B", initials: "PB" };
    const session: Session = { account, login: "trial", simulated_tags: false, share_url: null, help_url: null, apps: null, tokens: null, tokens_url: null, logout_url: null };
    const owner = "8a3e1f0c-1111-5222-8333-944455550000";
    const html = renderToStaticMarkup(
      <Shell
        page="meets"
        language="sv"
        host="test.catalog.trainmeet.app"
        session={session}
        version={null}
        offline={false}
        working={owner}
        fleets={[{ owner, title: "Vagnparken · Provkonto A", right: "edit", share_url: null }]}
      />,
    );
    expect(html).toContain("Träffarna är ägarens egna.");
    expect(html).toContain('href="/traffar" aria-current="page"');
  });
});
