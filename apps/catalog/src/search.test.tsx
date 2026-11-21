// Sök på webben (#53 del b, CAT-166–CAT-172, CAT-219): the flow and its views, and the
// reviewer's evidence per field. The search itself is never made here: its answers are written
// by the tests, with made-up sources at pretend publishers.
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ApiError, type FieldEvidence, type FieldRegister, type Prototype, type PrototypeRevision, type PrototypeSearch, type PrototypeSearchConsent } from "./api";
import type { Ctx } from "./common";
import { EvidenceTable, hostOf, staleCount } from "./Evidence";
import { text } from "./i18n";
import { PrototypesView, PrototypeView, ReviewQueueView } from "./PrototypesPage";
import { routeFor, searchPath, tabOf } from "./routes";
import { askOf, canPay, draftOf, EMPTY_FORM, markingOk, needsConsent, proposalOf, readyToSend, runSearch, searchProblem } from "./search";
import { SearchConsentView, SearchView } from "./SearchPage";

const ctx = (language: "sv" | "en" = "sv"): Ctx => ({ t: (key, vars) => text(language, key, vars), language, tokensUrl: "https://id.example.test/tokens" });
const NOW = "2026-11-21T09:00:00Z";
const SEARCH_ID = "0f8fad5b-d9cb-469f-a165-70867728950e";
const HBIS_ID = "7c9e6679-7425-40de-944b-e07fc1f90ae7";
const MUSEUM = "https://museum.example.org/fordon/hbis";
const PAGE = "https://tagsidor.example.org/godsvagnar/hbis";

const SHOWN = [
  ["litt", "Littera", "Class", "", "text"],
  ["operator", "Bolag", "Operator", "", "text"],
  ["length_over_buffers", "Längd över buffertar", "Length over buffers", "mm", "number"],
  ["weight", "Vikt", "Weight", "t", "number"],
  ["max_speed", "Största hastighet", "Top speed", "km/h", "number"],
  ["axles", "Axlar", "Axles", "", "integer"],
  ["built", "Byggår", "Built", "", "text"],
] as const;

/** The register as Catalog publishes it, cut to what the tests show. */
const REGISTER: FieldRegister = {
  fields: SHOWN.map(([key, label, label_en, unit, kind]) => ({ key, kind, unit, label, label_en, max_length: 40 })),
  profiles: [
    { profile: "SE", name: "Sverige", name_en: "Sweden", fields: SHOWN.map(([key, label, label_en]) => ({ key, label, label_en })) },
    { profile: "EU", name: "Europa", name_en: "Europe", fields: [{ key: "litt", label: "UIC-typ eller littera", label_en: "UIC type or class" }] },
    { profile: "US", name: "USA", name_en: "USA", fields: [{ key: "litt", label: "Klass", label_en: "Class" }] },
  ],
};

function evidence(change: Partial<FieldEvidence> = {}): FieldEvidence {
  return {
    value: "14020",
    url: MUSEUM,
    title: "Hbis – Museet (påhittad sida)",
    publisher: "museum",
    excerpt: "Längd över buffertar 14 020 mm",
    searched_at: NOW,
    agrees: true,
    ...change,
  };
}

const EVIDENCE = {
  length_over_buffers: [evidence()],
  max_speed: [
    evidence({ value: "100", excerpt: "sth 100 km/tim" }),
    evidence({ value: "100", url: PAGE, title: "Hbis – Tågsidor (påhittad sida)", publisher: "unknown", excerpt: "Största hastighet 100 km/h" }),
  ],
  axles: [evidence({ value: "2", url: PAGE, title: "", publisher: "unknown", excerpt: "En tvåaxlig vagn" })],
};

function search(change: Partial<PrototypeSearch> = {}): PrototypeSearch {
  return {
    id: SEARCH_ID,
    status: "done",
    litt: "Hbis",
    operator: "Green Cargo",
    kind: "freight_wagon",
    profile: "SE",
    fields: { litt: "Hbis", operator: "Green Cargo", length_over_buffers: "14020", max_speed: "100", axles: "2" },
    evidence: EVIDENCE,
    dropped: [
      { key: "weight", reason: "invented_source" },
      { key: "built", reason: "unsupported" },
    ],
    sources: 2,
    cost: 24,
    model: "claude-sonnet-5-5",
    searched_at: NOW,
    revision: null,
    prototype: null,
    refunded: false,
    existing: null,
    ...change,
  };
}

function consent(change: Partial<PrototypeSearchConsent> = {}): PrototypeSearchConsent {
  return {
    available: true,
    message: null,
    given: false,
    version: "2026-11-21",
    sent_to: "Claudes webbsökning hos Anthropic, utanför EU",
    text: "Bara märkningen skickas: littera, bolag, slag och fältprofil. Inga bilder, inget namn, inget konto, inga fordonsnummer och inga anteckningar. Sökningen görs av Claudes webbsökning hos Anthropic och behandlas utanför EU.",
    price: 24,
    balance: 108,
    payer: "Provkonto",
    own_ai: null,
    unsent: [],
    ...change,
  };
}

const HBIS = { litt: "Hbis", operator: "Green Cargo", kind: "freight_wagon", profile: "SE" } as const;
const view = (props: Partial<Parameters<typeof SearchView>[0]> = {}, language: "sv" | "en" = "sv") =>
  renderToStaticMarkup(<SearchView ctx={ctx(language)} register={REGISTER} consent={consent()} form={EMPTY_FORM} searching={false} result={null} draft={null} busy={false} error={null} {...props} />);

describe("the search's address", () => {
  it("is a page of the prototype catalog, and a search opens again by its id", () => {
    expect(routeFor("/forebilder/sok")).toEqual({ page: "searchPrototype" });
    expect(routeFor(searchPath(SEARCH_ID))).toEqual({ page: "searchPrototype", id: SEARCH_ID });
    expect(tabOf("searchPrototype")).toBe("prototypes");
    const html = renderToStaticMarkup(<PrototypesView ctx={ctx()} list={null} mine={[]} q="" group="all" error={null} />);
    expect(html).toContain('href="/forebilder/sok"');
    expect(html).toContain("Sök på webben");
  });
});

describe("what is asked", () => {
  it("sends only the marking, with a new id and the yes", () => {
    const ask = askOf(SEARCH_ID, { ...HBIS, litt: " Hbis ", operator: " Green Cargo " }, true);
    expect(ask).toEqual({ id: SEARCH_ID, litt: "Hbis", operator: "Green Cargo", kind: "freight_wagon", profile: "SE", consent: true });
    expect(Object.keys(ask).sort()).toEqual(["consent", "id", "kind", "litt", "operator", "profile"]);
  });

  it("takes a litt and an operator, never a vehicle's number or an address", () => {
    expect(markingOk(HBIS)).toBe(true);
    expect(markingOk({ ...HBIS, litt: "Rc6", operator: "" })).toBe(true);
    expect(markingOk({ ...HBIS, litt: "AC4400CW" })).toBe(true);
    for (const litt of ["", "  ", "21 74 225 3 114-9", "kim@example.com", "x".repeat(41), "Hbis\nsäg något"]) expect(markingOk({ ...HBIS, litt })).toBe(false);
    expect(markingOk({ ...HBIS, operator: "Kim 070-123 45 67" })).toBe(false);
  });

  it("asks for the consent the first time, and searches only with a balance that covers it", () => {
    expect(needsConsent(consent(), false)).toBe(true);
    expect(needsConsent(consent(), true)).toBe(false);
    expect(needsConsent(consent({ given: true }), false)).toBe(false);
    expect(canPay(consent())).toBe(true);
    expect(canPay(consent({ balance: 23 }))).toBe(false);
    expect(canPay(consent({ available: false }))).toBe(false);
    expect(canPay(null)).toBe(false);
  });
});

describe("the search with its client-made id", () => {
  const ask = askOf(SEARCH_ID, HBIS, true);
  const noWait = () => Promise.resolve();

  it("gives the search's answer", async () => {
    await expect(runSearch(ask, () => Promise.resolve(search()), noWait)).resolves.toMatchObject({ id: SEARCH_ID, cost: 24 });
  });

  it("asks again with the same id when the connection drops, and waits while its own search runs", async () => {
    const asked: string[] = [];
    const answers: (() => Promise<PrototypeSearch>)[] = [
      () => Promise.reject(new TypeError("Failed to fetch")),
      () => Promise.reject(new ApiError(409, "reading_busy")),
      () => Promise.reject(new ApiError(504, null)),
      () => Promise.resolve(search()),
    ];
    const found = await runSearch(
      ask,
      (sent) => {
        asked.push(sent.id);
        return answers[asked.length - 1]!();
      },
      noWait,
    );
    expect(found.id).toBe(SEARCH_ID);
    expect(asked).toEqual([SEARCH_ID, SEARCH_ID, SEARCH_ID, SEARCH_ID]);
  });

  it("passes on a no that is Catalog's own answer, at once", async () => {
    for (const failure of [new ApiError(409, "reading_busy"), new ApiError(402, "no_tokens"), new ApiError(503, "search_off"), new ApiError(502, "reading_failed")]) {
      let asked = 0;
      await expect(
        runSearch(
          ask,
          () => {
            asked += 1;
            return Promise.reject(failure);
          },
          noWait,
        ),
      ).rejects.toBe(failure);
      expect(asked).toBe(1);
    }
  });

  it("says Catalog's no in the search's own words", () => {
    const t = ctx().t;
    expect(searchProblem(t, new ApiError(402, "no_tokens"))).toBe("Saldot räcker inte för en webbsökning. Köp tokens i TrainMeet ID.");
    expect(searchProblem(t, new ApiError(503, "search_off"))).toBe("Webbsökningen är inte inkopplad här. Föreslå förebilden för hand.");
    expect(searchProblem(t, new ApiError(409, "reading_busy"))).toContain("pågår redan");
    expect(searchProblem(t, new ApiError(429, "too_many"))).toContain("Högst 10 webbsökningar");
    expect(searchProblem(t, new ApiError(422, "bad_type_data"))).toContain("aldrig på ett fordonsnummer");
    expect(searchProblem(t, new TypeError("nere"))).toContain("Inget drogs");
    expect(searchProblem(ctx("en").t, new ApiError(503, "unavailable"))).toBe("The web search cannot be used just now. Nothing was drawn. Try again later.");
  });
});

describe("the search page", () => {
  it("shows the price and the balance before the search, and what is sent", () => {
    const html = view({ form: HBIS });
    expect(html).toContain("Finns typen inte i katalogen än?");
    expect(html).toContain("Webbsökningen fyller katalogen, inte det enskilda fordonet.");
    expect(html).toContain("Sökningen görs med TrainMeets AI och kostar 24 tokens. De kommer tillbaka när förebilden godkänns.");
    expect(html).toContain("Saldo: 108 tokens · Provkonto");
    expect(html).toContain("Sök · 24 tokens");
    expect(html).toContain("Bara märkningen skickas: littera, bolag, slag och fältprofil.");
    expect(html).toContain('value="Hbis"');
    expect(html).not.toContain("disabled");
    // No marking yet: nothing to search for.
    expect(view()).toMatch(/<button type="submit" class="tm-knapp primar" disabled="">Sök · 24 tokens/);
    expect(view({ form: HBIS }, "en")).toContain("Search · 24 tokens");
  });

  it("says what is sent and to whom before the first search", () => {
    const html = renderToStaticMarkup(<SearchConsentView ctx={ctx()} consent={consent()} />);
    expect(html).toContain("Inga bilder, inget namn, inget konto, inga fordonsnummer och inga anteckningar.");
    expect(html).toContain("Söks av: Claudes webbsökning hos Anthropic, utanför EU.");
    expect(html).toContain("Sökningen kostar 24 tokens, som kommer tillbaka när förebilden godkänns.");
    expect(html).toContain("Ja, sök");
    expect(html).toContain("Avbryt");
  });

  it("says that own AI is not used, and when the balance is short", () => {
    expect(view({ consent: consent({ own_ai: "egen-modell" }) })).toContain("Din egen AI (egen-modell) har ingen webbsökning, så den används inte här.");
    const short = view({ form: HBIS, consent: consent({ balance: 10 }) });
    expect(short).toContain("Saldot räcker inte för en webbsökning.");
    expect(short).toContain('href="https://id.example.test/tokens"');
    expect(short).toMatch(/disabled="">Sök · 24 tokens/);
  });

  it("says that the search is not connected, and offers proposing by hand", () => {
    const html = view({ form: HBIS, consent: consent({ available: false, balance: null, message: "Webbsökningen är inte inkopplad här. Föreslå förebilden för hand." }) });
    expect(html).toContain("Webbsökningen är inte inkopplad här.");
    expect(html).toContain("Föreslå förebilden för hand");
    expect(html).toContain('href="/forebilder/ny"');
    expect(html).not.toContain("Sök · 24 tokens");
    expect(html).not.toContain('type="submit"');
  });

  it("waits while the search runs", () => {
    const html = view({ form: HBIS, searching: true });
    expect(html).toContain('role="status"');
    expect(html).toContain("Söker på webben …");
    expect(html).toContain("Söker efter Hbis · Green Cargo.");
    expect(html).toContain("inget dras två gånger");
    expect(html).toMatch(/<button type="submit" class="tm-knapp primar" disabled="">/);
    expect(html).toMatch(/<input[^>]*disabled=""[^>]*value="Hbis"|<input[^>]*value="Hbis"[^>]*disabled=""/);
  });

  it("shows the proposal with each field's sources, and what was taken away", () => {
    const found = search();
    const html = view({ form: HBIS, result: found, draft: draftOf(found) });
    expect(html).toContain("Hbis finns inte i katalogen än");
    expect(html).toContain("AI:ns förslag");
    expect(html).toContain("3 fält med källa av 2 sidor i sökningen.");
    expect(html).toContain("Sökningen kostade 24 tokens (claude-sonnet-5-5).");
    // The value with its unit, the source as a link, the publisher's class and the excerpt.
    expect(html).toContain("14020 mm");
    expect(html).toContain(`<a href="${MUSEUM}" target="_blank" rel="noopener noreferrer nofollow">Hbis – Museet (påhittad sida)</a>`);
    expect(html).toContain("Museum");
    expect(html).toContain("Okänd utgivare");
    expect(html).toContain("Längd över buffertar 14 020 mm");
    expect(html).toContain("2 källor");
    expect(html).toContain("1 källa");
    expect(html).toContain("museum.example.org");
    expect(html.match(/Belägget stämmer</g)).toHaveLength(4);
    // A source without a title is named by its host.
    expect(html).toContain(`rel="noopener noreferrer nofollow">tagsidor.example.org</a>`);
    // The marking itself has no source: it is what was searched for.
    expect(html.match(/angiven i sökningen/g)).toHaveLength(2);
    // What the AI proposed without a source that holds.
    expect(html).toContain("Vikt: källan fanns inte i sökresultatet.");
    expect(html).toContain("Byggår: utdraget ur källan stämde inte med värdet.");
    // On to the review queue, after the yes to sharing.
    expect(html).toMatch(/<button type="submit" class="tm-knapp primar" disabled="">Skicka till granskning/);
    expect(html).toContain("Ändra först");
    expect(html).toContain("Sök igen · 24 tokens");
    const ready = view({ form: HBIS, result: found, draft: { ...draftOf(found), mayShare: true } });
    expect(ready).toMatch(/<button type="submit" class="tm-knapp primar">Skicka till granskning/);
  });

  it("lets the person change the proposal first, and marks a changed value's evidence", () => {
    const found = search();
    const editing = view({ form: HBIS, result: found, draft: { ...draftOf(found), editing: true } });
    expect(editing).toContain('value="14020"');
    expect(editing).toContain("Källorna följer med fälten.");
    expect(editing).toContain("Klar med ändringarna");
    const changed = view({ form: HBIS, result: found, draft: { ...draftOf(found), fields: { ...found.fields, max_speed: "120" } } });
    expect(changed).toContain("120 km/h");
    expect(changed.match(/Belägget stämmer inte längre/g)).toHaveLength(2);
    expect(changed).toContain("Källan belade 100 km/h. Värdet har ändrats sedan dess.");
    expect(changed.match(/Belägget stämmer</g)).toHaveLength(2);
  });

  it("says when nothing was found, and when the type is in the catalog already", () => {
    const nothing = search({ fields: { litt: "Hbis" }, evidence: {}, dropped: [{ key: "weight", reason: "no_source" }], operator: "" });
    const html = view({ result: nothing, draft: draftOf(nothing) });
    expect(html).toContain("Sökningen hittade ingen uppgift med en källa som håller.");
    expect(html).toContain("Vikt: AI:n gav ingen källa.");
    const existing = search({ existing: { id: HBIS_ID, name: "Hbis", revision: 2 } });
    const known = view({ result: existing, draft: draftOf(existing) });
    expect(known).toContain("Hbis finns redan i katalogen.");
    expect(known).toContain(`href="/forebilder/${HBIS_ID}"`);
  });

  it("shows a sent search, and when its tokens have come back", () => {
    const sent = search({ revision: "3fa85f64-5717-4562-b3fc-2c963f66afa6", prototype: HBIS_ID });
    const waiting = view({ result: sent, draft: draftOf(sent) });
    expect(waiting).toContain("Hbis är skickad till granskning");
    expect(waiting).toContain("Förslaget väntar på granskning. Tokens kommer tillbaka när det godkänns.");
    expect(waiting).toContain(`href="/forebilder/${HBIS_ID}"`);
    expect(waiting).not.toContain("Skicka till granskning</button>");
    const back = search({ revision: "3fa85f64-5717-4562-b3fc-2c963f66afa6", prototype: HBIS_ID, refunded: true });
    expect(view({ result: back, draft: draftOf(back) })).toContain("Förebilden är godkänd, och sökningens 24 tokens har kommit tillbaka.");
  });

  it("lists the searches that are not sent yet, so that none is lost", () => {
    const html = view({ consent: consent({ unsent: [{ id: SEARCH_ID, litt: "Hbis", operator: "Green Cargo", searched_at: NOW, fields: 3 }] }) });
    expect(html).toContain("Sökningar du inte har skickat");
    expect(html).toContain(`href="/forebilder/sok/${SEARCH_ID}"`);
    expect(html).toContain("Hbis · Green Cargo · 3 fält med källa");
  });
});

describe("the proposal that is sent", () => {
  it("names the search, never the evidence, and needs a name and the yes to sharing", () => {
    const found = search();
    const draft = { ...draftOf(found), fields: { ...found.fields, max_speed: "120", weight: " ", owner: "Kim" }, mayShare: true };
    expect(readyToSend(draft)).toBe(true);
    expect(readyToSend({ ...draft, mayShare: false })).toBe(false);
    expect(readyToSend({ ...draft, name: " " })).toBe(false);
    const keys = SHOWN.map(([key]) => key);
    const sent = proposalOf(found, draft, [...keys], "Webbsökning");
    expect(sent).toEqual({
      prototype: null,
      base: null,
      name: "Hbis",
      kind: "freight_wagon",
      profile: "SE",
      fields: { litt: "Hbis", operator: "Green Cargo", length_over_buffers: "14020", max_speed: "120", axles: "2" },
      source: { kind: "web_search", text: "Webbsökning" },
      may_share: true,
      search: SEARCH_ID,
    });
    expect(JSON.stringify(sent)).not.toContain("museum.example.org");
  });
});

describe("the reviewer's evidence", () => {
  const fields = SHOWN.map(([key, label, , unit]) => ({ key, label, unit }));
  const revision = (change: Partial<PrototypeRevision> = {}): PrototypeRevision => ({
    id: "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    prototype: HBIS_ID,
    number: 1,
    base: null,
    status: "proposed",
    name: "Hbis",
    kind: "freight_wagon",
    profile: "SE",
    fields: { litt: "Hbis", operator: "Green Cargo", length_over_buffers: "14020", max_speed: "120", axles: "2" },
    source: { kind: "web_search", text: "Webbsökning 2026-11-21. Källorna står per fält." },
    mine: false,
    proposed_by: "Provkonto B",
    created_at: NOW,
    comment: "",
    reviewed_at: null,
    evidence: { ...EVIDENCE, max_speed: EVIDENCE.max_speed.map((item) => ({ ...item, agrees: false })) },
    ...change,
  });

  it("shows each field's value, source, publisher and excerpt in the review queue", () => {
    const html = renderToStaticMarkup(<ReviewQueueView ctx={ctx()} queue={[revision()]} register={REGISTER} comments={{}} busy={null} error={null} />);
    expect(html).toContain("Hbis: ny förebild");
    expect(html).toContain("Webbsökning:</b> Webbsökning 2026-11-21. Källorna står per fält.");
    expect(html).toContain("Belägg per fält");
    expect(html).toContain("Utgivaren är klassad mot Catalogs granskade lista.");
    for (const said of ["14020 mm", "Hbis – Museet (påhittad sida)", "Museum", "Okänd utgivare", "Längd över buffertar 14 020 mm", "En tvåaxlig vagn", "museum.example.org"]) expect(html).toContain(said);
    // The proposer changed the speed after the search: the reviewer sees that the evidence
    // no longer agrees with the value that stands there (CAT-170).
    expect(html).toContain("120 km/h");
    expect(html).toContain("Belägget stämmer inte längre: 1");
    expect(html.match(/<b class="cat-varning">Belägget stämmer inte längre<\/b>/g)).toHaveLength(2);
    expect(html).toContain("Källan belade 100 km/h. Värdet har ändrats sedan dess.");
    expect(html.match(/Belägget stämmer</g)).toHaveLength(2);
    expect(html).toContain("Godkänn");
    expect(staleCount(revision().evidence)).toBe(1);
  });

  it("shows nothing about evidence for a proposal made by hand", () => {
    const html = renderToStaticMarkup(
      <ReviewQueueView ctx={ctx()} queue={[revision({ evidence: {}, source: { kind: "own", text: "Egen mätning" } })]} register={REGISTER} comments={{}} busy={null} error={null} />,
    );
    expect(html).not.toContain("Belägg per fält");
    expect(html).toContain("Egen mätning eller kunskap");
  });

  it("shows the evidence on the prototype's page, with whether it still agrees", () => {
    const prototype: Prototype = {
      id: HBIS_ID,
      status: "reviewed",
      revision: 2,
      name: "Hbis",
      kind: "freight_wagon",
      profile: "SE",
      fields: revision().fields,
      source: { kind: "own", text: "Egen mätning" },
      evidence: revision().evidence,
      reviewed_at: NOW,
      vehicles: 0,
      waiting: 0,
      revisions: [],
    };
    const html = renderToStaticMarkup(<PrototypeView ctx={ctx("en")} prototype={prototype} register={REGISTER} />);
    expect(html).toContain("Evidence per field");
    expect(html).toContain("The evidence no longer agrees: 1");
    expect(html).toContain("The source held 100 km/h. The value has been changed since.");
    expect(html).toContain("Unknown publisher");
  });

  it("never makes a link of anything but a web address", () => {
    expect(hostOf("https://www.museum.example.org/x")).toBe("museum.example.org");
    expect(hostOf("javascript:alert(1)")).toBeNull();
    expect(hostOf("inte en adress")).toBeNull();
    const html = renderToStaticMarkup(
      <EvidenceTable ctx={ctx()} fields={fields} values={{ axles: "2" }} evidence={{ axles: [evidence({ value: "2", url: "javascript:alert(1)", title: "Klicka här" })] }} />,
    );
    expect(html).not.toContain("href");
    expect(html).toContain("Klicka här");
    // Only the fields with a value are shown, and with onlyEvidence only those with a source.
    expect(renderToStaticMarkup(<EvidenceTable ctx={ctx()} fields={fields} values={{ litt: "Hbis" }} evidence={{}} onlyEvidence />)).toBe("");
  });
});
