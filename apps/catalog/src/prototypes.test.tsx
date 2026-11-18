import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { FieldRegister, Prototype, PrototypeList, PrototypeRevision, Vehicle, VehiclePrototype } from "./api";
import type { Ctx } from "./common";
import { text } from "./i18n";
import { ChooseView, PrototypeBlockView, SuggestedPrototypeView } from "./PrototypeBlock";
import { draftOf, EMPTY_DRAFT, profileFields, proposalOf, PrototypesView, PrototypeView, ProposalView, readyToSend, ReviewQueueView, typeSummary } from "./PrototypesPage";
import { routeFor, tabOf } from "./routes";
import { CardView } from "./VehicleCard";

const ctx = (language: "sv" | "en" = "sv", right: Ctx["right"] = "owner"): Ctx => ({ t: (key, vars) => text(language, key, vars), language, right });
const NOW = "2026-11-18T09:00:00Z";
const HBIS_ID = "7c9e6679-7425-40de-944b-e07fc1f90ae7";

const LABELS: Record<string, string> = { litt: "Littera", operator: "Bolag", description: "Beskrivning", max_speed: "Största hastighet", axles: "Axlar" };

/** The register as Catalog publishes it, cut to what the tests show. */
const REGISTER: FieldRegister = {
  fields: [
    { key: "litt", kind: "text", unit: "", label: "Littera", label_en: "Class", max_length: 40 },
    { key: "operator", kind: "text", unit: "", label: "Bolag", label_en: "Operator", max_length: 80 },
    { key: "description", kind: "text", unit: "", label: "Beskrivning", label_en: "Description", max_length: 1000 },
    { key: "max_speed", kind: "number", unit: "km/h", label: "Största hastighet", label_en: "Top speed", max_length: 20 },
    { key: "axles", kind: "integer", unit: "", label: "Axlar", label_en: "Axles", max_length: 20 },
    { key: "length_ft", kind: "number", unit: "ft", label: "Längd", label_en: "Length", max_length: 20 },
  ],
  profiles: [
    {
      profile: "SE",
      name: "Sverige",
      name_en: "Sweden",
      fields: ["litt", "operator", "description", "max_speed", "axles"].map((key) => ({ key, label: LABELS[key] ?? key, label_en: key })),
    },
    { profile: "EU", name: "Europa", name_en: "Europe", fields: [{ key: "litt", label: "UIC-typ eller littera", label_en: "UIC type or class" }] },
    { profile: "US", name: "USA", name_en: "USA", fields: [{ key: "litt", label: "Klass", label_en: "Class" }, { key: "length_ft", label: "Längd", label_en: "Length" }] },
  ],
};
const HBIS_FIELDS = { litt: "Hbis", operator: "SJ", description: "Täckt godsvagn med skjutväggar", max_speed: "100", axles: "2" };

function prototype(change: Partial<Prototype> = {}): Prototype {
  return {
    id: HBIS_ID,
    status: "reviewed",
    revision: 2,
    name: "Hbis",
    kind: "freight_wagon",
    profile: "SE",
    fields: HBIS_FIELDS,
    source: { kind: "reference", text: "Svenska godsvagnar, del 2." },
    reviewed_at: NOW,
    vehicles: 4,
    waiting: 0,
    revisions: [],
    ...change,
  };
}

function revision(change: Partial<PrototypeRevision> = {}): PrototypeRevision {
  return {
    id: "0f8fad5b-d9cb-469f-a165-70867728950e",
    prototype: HBIS_ID,
    number: 1,
    base: null,
    status: "proposed",
    name: "Zans",
    kind: "freight_wagon",
    profile: "SE",
    fields: { litt: "Zans", operator: "SJ", axles: "4" },
    source: { kind: "own", text: "Egen mätning" },
    mine: false,
    proposed_by: "Olle Berg",
    created_at: NOW,
    comment: "",
    reviewed_at: null,
    ...change,
  };
}

function list(prototypes: Prototype[], change: Partial<PrototypeList> = {}): PrototypeList {
  return { prototypes, reviewer: false, to_review: 0, license: "CC BY-SA 4.0", license_url: "https://creativecommons.org/licenses/by-sa/4.0/", ...change };
}

function linked(change: Partial<VehiclePrototype> = {}): VehiclePrototype {
  return {
    id: HBIS_ID,
    name: "Hbis",
    kind: "freight_wagon",
    profile: "SE",
    revision: 1,
    snapshot: HBIS_FIELDS,
    overrides: { max_speed: "90" },
    fields: { ...HBIS_FIELDS, max_speed: "90" },
    latest: 2,
    newer: true,
    ...change,
  };
}

function vehicle(change: Partial<Vehicle> = {}): Vehicle {
  return {
    id: "1b9d6bcd-bbfd-4b2d-9b5d-ab8dfbbd4bed",
    version: 3,
    status: "ready",
    kind: "freight_wagon",
    litt: "Hbis",
    number: "21 74 245 2 253-0",
    operator: "Green Cargo",
    epoch: "",
    scale: "H0",
    maker: "",
    article_number: "",
    note: "",
    dcc_address: "",
    functions: [],
    place: null,
    place_name: null,
    state: "home",
    lending: null,
    evn: null,
    field_sources: {},
    tags: [],
    tagged: false,
    picture: null,
    prototype: linked(),
    created_at: NOW,
    updated_at: NOW,
    ...change,
  };
}

describe("the prototype catalog (CAT-173, CAT-213)", () => {
  it("lists one type per row with its type data, its use and its state, and says the licence", () => {
    const zans = prototype({ id: "3", name: "Zans", status: "proposed", revision: null, fields: { litt: "Zans", operator: "SJ" }, vehicles: 0 });
    const html = renderToStaticMarkup(<PrototypesView ctx={ctx()} list={list([prototype({ waiting: 1 }), zans])} mine={[]} q="" group="all" error={null} />);
    expect(html).toContain("Förebildskatalogen");
    expect(html).toContain('href="/forebilder/7c9e6679-7425-40de-944b-e07fc1f90ae7"');
    expect(html).toContain("Hbis · SJ · Godsvagn");
    expect(html).toContain("Täckt godsvagn med skjutväggar");
    expect(html).toContain("100 km/h · 2 axlar");
    expect(html).toContain("4 fordon");
    expect(html).toContain("Granskad");
    expect(html).toContain("Ändring väntar");
    expect(html).toContain("väntar på granskning");
    expect(html).toContain("Förslag");
    expect(html).toContain("Katalogens data ges ut under");
    expect(html).toContain('href="https://creativecommons.org/licenses/by-sa/4.0/"');
    expect(html).toContain(">CC BY-SA 4.0<");
    expect(html).toContain('href="/forebilder/ny"');
    expect(html).toContain('placeholder="Sök på littera, bolag eller typ"');
    expect(html).not.toContain("Att granska");
  });

  it("shows the review queue's button only to a reviewer, and one's own proposals with the answer", () => {
    const answered = revision({ status: "rejected", mine: true, comment: "Källan räcker inte." });
    const html = renderToStaticMarkup(<PrototypesView ctx={ctx()} list={list([], { reviewer: true, to_review: 2 })} mine={[answered]} q="" group="wagons" error={null} />);
    expect(html).toMatch(/href="\/forebilder\/granska"[^>]*>Att granska <span class="cat-antal">2<\/span>/);
    expect(html).toContain("Mina förslag");
    expect(html).toContain("Avslagen");
    expect(html).toContain("«Källan räcker inte.»");
    expect(html).toContain("Ingen förebild passar sökningen.");
    expect(html).toMatch(/aria-pressed="true"[^>]*>Godsvagnar</);
  });

  it("is in English too, and sums the type data in short", () => {
    const html = renderToStaticMarkup(<PrototypesView ctx={ctx("en")} list={list([])} mine={[]} q="" group="all" error={null} />);
    expect(html).toContain("The prototype catalog is empty.");
    expect(html).toContain("The catalog&#x27;s data are published under");
    expect(typeSummary(ctx().t, { max_speed_mph: "50", axles: "4" })).toBe("50 mph · 4 axlar");
    expect(typeSummary(ctx().t, {})).toBe("");
  });

  it("shows a prototype with its type data in the profile's order, its source and its revisions", () => {
    const revisions = [revision({ number: 2, base: 1, status: "reviewed", name: "Hbis", proposed_by: null, comment: "Stämmer." }), revision({ number: 1, status: "reviewed", name: "Hbis", proposed_by: null })];
    const html = renderToStaticMarkup(<PrototypeView ctx={ctx()} prototype={prototype({ revisions })} register={REGISTER} />);
    expect(html).toContain("Godsvagn · Sverige · Revision 2");
    expect(html.indexOf("Littera")).toBeLessThan(html.indexOf("Största hastighet"));
    expect(html).toContain("100 km/h");
    expect(html).toContain("Källhänvisning:</b> Svenska godsvagnar, del 2.");
    expect(html).toContain("«Stämmer.»");
    expect(html).toContain('href="/forebilder/7c9e6679-7425-40de-944b-e07fc1f90ae7/andra"');
    expect(html).not.toContain("bidrag från");
  });

  it("has addresses of its own under the tab Förebilder", () => {
    expect(routeFor("/forebilder")).toEqual({ page: "prototypes" });
    expect(routeFor("/forebilder/ny")).toEqual({ page: "newPrototype" });
    expect(routeFor("/forebilder/granska")).toEqual({ page: "reviewQueue" });
    expect(routeFor(`/forebilder/${HBIS_ID}`)).toEqual({ page: "prototype", id: HBIS_ID });
    expect(routeFor(`/forebilder/${HBIS_ID}/andra`)).toEqual({ page: "changePrototype", id: HBIS_ID });
    expect(tabOf("reviewQueue")).toBe("prototypes");
  });
});

describe("the proposal (CAT-163, CAT-213)", () => {
  it("asks for a name, the type data of the profile, a source and the yes to share under CC BY-SA", () => {
    const html = renderToStaticMarkup(<ProposalView ctx={ctx()} draft={EMPTY_DRAFT} register={REGISTER} change={null} busy={false} error={null} />);
    expect(html).toContain("<h1>Föreslå förebild</h1>");
    expect(html).toContain("Benämning");
    expect(html).toContain("Största hastighet (km/h)");
    expect(html).not.toContain("Längd (ft)");
    expect(html).toContain("Egen mätning eller kunskap");
    expect(html).toContain("Jag får dela uppgifterna, och de ges ut under");
    expect(html).toContain(">CC BY-SA 4.0<");
    expect(html).toMatch(/<button type="submit" class="tm-knapp primar" disabled="">Skicka till granskning/);
  });

  it("sends only the profile's filled-in keys, and a change on the revision it was built on", () => {
    const draft = { ...draftOf(prototype()), profile: "SE" as const, fields: { ...HBIS_FIELDS, max_speed: "120", length_ft: "46", axles: " " }, source: "Typritning 1962", mayShare: true };
    expect(readyToSend(draft)).toBe(true);
    expect(readyToSend({ ...draft, mayShare: false })).toBe(false);
    expect(readyToSend({ ...draft, source: " " })).toBe(false);
    const sent = proposalOf(draft, REGISTER, prototype());
    expect(sent).toMatchObject({ prototype: HBIS_ID, base: 2, name: "Hbis", may_share: true, source: { kind: "own", text: "Typritning 1962" } });
    expect(sent.fields).toEqual({ litt: "Hbis", operator: "SJ", description: "Täckt godsvagn med skjutväggar", max_speed: "120" });
    expect(proposalOf({ ...EMPTY_DRAFT, name: "Zans", source: "x", mayShare: true }, REGISTER, null)).toMatchObject({ prototype: null, base: null });
    const html = renderToStaticMarkup(<ProposalView ctx={ctx("en")} draft={draft} register={REGISTER} change={prototype()} busy={false} error={null} />);
    expect(html).toContain("Propose a change of Hbis");
    expect(html).toContain("Change of revision 2");
    expect(html).toContain('value="120"');
    expect(profileFields(REGISTER, "US", "en").map((field) => field.label)).toEqual(["Class", "Length"]);
  });

  it("lets the reviewer approve, or reject only with a comment", () => {
    const change = revision({ id: "b", base: 1, name: "Gbs" });
    const html = renderToStaticMarkup(<ReviewQueueView ctx={ctx()} queue={[revision(), change]} register={REGISTER} comments={{ b: "Fel källa." }} busy={null} error={null} />);
    expect(html).toContain("Zans: ny förebild");
    expect(html).toContain("Gbs: ändring av revision 1");
    expect(html).toContain("bidrag från Olle Berg");
    expect(html).toContain("Öppna förebilden");
    expect(html.match(/>Godkänn</g)).toHaveLength(2);
    expect(html).toMatch(/disabled="">Avslå</);
    expect(html.match(/<button type="button" class="tm-knapp">Avslå</g)).toHaveLength(1);
  });
});

describe("the prototype on the vehicle card (CAT-160, CAT-161, CAT-162)", () => {
  const block = (vehicleChange: Partial<Vehicle> = {}, right: Ctx["right"] = "owner") =>
    renderToStaticMarkup(<PrototypeBlockView ctx={ctx("sv", right)} vehicle={vehicle(vehicleChange)} register={REGISTER} editing={null} busy={false} error={null} />);

  it("shows the type data as a block of its own, the owner's own value marked", () => {
    const html = block();
    expect(html).toContain("Förebild · Hbis");
    expect(html).toContain("Version 1 · Sverige");
    expect(html).toMatch(/<tr class="cat-egen"><th scope="row">Största hastighet<\/th><td>90 km\/h<\/td>/);
    expect(html).toContain("Avvikelse");
    expect(html).toContain("Förebilden: 100 km/h");
    expect(html).toContain("Från förebilden");
    expect(html).toContain("Ny version finns: version 2.");
    expect(html).toContain(">Uppdatera<");
    expect(html).toContain(">Koppla bort<");
    expect(html).toContain(">Ändra typuppgifter<");
  });

  it("offers Koppla förebild without a link, and nothing to change to someone who only looks", () => {
    const none = block({ prototype: null });
    expect(none).toContain("Ingen förebild är kopplad.");
    expect(none).toContain(">Koppla förebild<");
    expect(block({ prototype: null }, "view")).not.toContain("Koppla förebild");
    const looked = block({}, "view");
    expect(looked).toContain("Ny version finns");
    expect(looked).not.toContain("Uppdatera");
    expect(looked).not.toContain("Koppla bort");
    const current = block({ prototype: linked({ newer: false, latest: 1, overrides: {}, fields: HBIS_FIELDS }) });
    expect(current).not.toContain("Ny version finns");
    expect(current).not.toContain("Avvikelse");
  });

  it("is below the core fields on the card, not in them", () => {
    const html = renderToStaticMarkup(<CardView ctx={ctx()} vehicle={vehicle()} events={[]} error={null} prototype={<p>Förebildsblocket</p>} />);
    expect(html.indexOf("Förebildsblocket")).toBeGreaterThan(html.indexOf("cat-falttabell"));
  });

  it("lets the owner change the type data, and chooses among reviewed prototypes only", () => {
    const html = renderToStaticMarkup(
      <PrototypeBlockView ctx={ctx()} vehicle={vehicle()} register={REGISTER} editing={{ ...HBIS_FIELDS, max_speed: "90" }} busy={false} error={null} />,
    );
    expect(html).toContain("Ett värde som är lika med förebildens ärvs.");
    expect(html).toContain('value="90"');
    const chosen = renderToStaticMarkup(
      <ChooseView ctx={ctx()} q="" found={[prototype(), prototype({ id: "x", name: "Zans", status: "proposed", revision: null })]} busy={false} />,
    );
    expect(chosen).toContain("Hbis");
    expect(chosen).not.toContain("Zans");
  });

  it("shows the AI's suggestion with Koppla, and that it is linked (CAT-141)", () => {
    const suggestion = { id: HBIS_ID, name: "Hbis", revision: 2 };
    const html = renderToStaticMarkup(<SuggestedPrototypeView ctx={ctx()} suggestion={suggestion} linked={false} busy={false} error={null} />);
    expect(html).toContain("AI:n föreslår förebilden Hbis, version 2.");
    expect(html).toContain(">Koppla<");
    const done = renderToStaticMarkup(<SuggestedPrototypeView ctx={ctx("en")} suggestion={suggestion} linked busy={false} error={null} />);
    expect(done).toContain("Hbis is linked.");
    expect(done).not.toContain(">Link<");
  });
});
