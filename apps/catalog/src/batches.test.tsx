import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, type Batch, type BatchCard, type BatchSummary, type ReadingConsent, type VehicleList } from "./api";
import { BatchesSection, BatchPage, BatchView, CardEditView, CardRow } from "./BatchPage";
import { approveAll, canApprove, cardChange, cardFlow, choosePhotos, sendPhotos, sendProblem, tally, tokensRanOut, unreadableCards } from "./batches";
import type { Ctx } from "./common";
import { text, TEXTS } from "./i18n";
import { accept, answer, edit, openQuestion, stillUnreadable } from "./reading";
import { batchPath, PATHS, routeFor, tabOf } from "./routes";
import { VehiclesView } from "./VehiclesPage";

const ctx = (language: "sv" | "en" = "sv"): Ctx => ({ t: (key, vars) => text(language, key, vars), language, tokensUrl: "https://test.id.trainmeet.app/tokens" });
const editor: Ctx = { ...ctx(), right: "edit", fleetTitle: "Vagnparken · Provkonto A" };
const viewer: Ctx = { ...ctx(), right: "view", fleetTitle: "Vagnparken · Provkonto A" };
const t = ctx().t;
const account = { id: "8a3e1f0c-1111-5222-8333-944455556666", name: "Provkonto A", initials: "PA" };
const BATCH = "5b2c9e1a-0000-4000-8000-000000000147";
const NOW = "2026-11-18T12:00:00Z";
const card = (n: number) => `5b2c9e1a-0000-4000-8000-00000000000${n}`;

const consent = (change: Partial<ReadingConsent> = {}): ReadingConsent => ({
  available: true,
  message: null,
  given: true,
  version: "2026-11-18",
  sent_to: "TrainMeets AI: Claude från Anthropic via Amazon Bedrock i EU",
  text: "Fotona, utan platsuppgifter och annan metadata, skickas till TrainMeets AI: Claude från Anthropic via Amazon Bedrock i EU.",
  own_ai: null,
  price_per_picture: 12,
  balance: 36,
  payer: null,
  ...change,
});

const suggestion = (value: string, confidence: "high" | "medium" | "low" = "high") => ({ value, confidence, basis: "visible_text" as const, evidence: "På vagnens sida" });

const EMPTY_VALUES: BatchCard["values"] = {
  status: "draft",
  kind: null,
  litt: "",
  number: "",
  operator: "",
  epoch: "",
  scale: "",
  maker: "",
  article_number: "",
  note: "",
  dcc_address: "",
  functions: [],
  place: null,
};

function draft(n: number, change: Partial<BatchCard> = {}): BatchCard {
  return {
    id: card(n),
    batch: BATCH,
    position: n - 1,
    source: "photo",
    file_name: null,
    status: "waiting",
    version: 1,
    values: EMPTY_VALUES,
    suggestions: {},
    question: null,
    warnings: [],
    message: "",
    picture: { thumb_url: `/api/catalog/1/pictures/file/t${n}.jpg`, display_url: `/api/catalog/1/pictures/file/d${n}.jpg` },
    vehicle: null,
    attempts: 0,
    prototype: null,
    ...change,
  };
}

/** Gbs 3087, read with nothing to check. */
const gbs = (change: Partial<BatchCard> = {}) =>
  draft(1, {
    status: "ready",
    version: 2,
    values: { ...EMPTY_VALUES, status: "ready", kind: "freight_wagon", litt: "Gbs", number: "3087", operator: "Green Cargo" },
    suggestions: { kind: { ...suggestion("freight_wagon"), basis: "visual_inference" }, litt: suggestion("Gbs"), number: suggestion("3087"), operator: suggestion("Green Cargo", "low") },
    attempts: 1,
    ...change,
  });

/** Sgns with an uncertain digit in its EVN (CAT-140). */
const sgns = (change: Partial<BatchCard> = {}) =>
  draft(2, {
    status: "review",
    version: 2,
    values: { ...EMPTY_VALUES, status: "ready", kind: "freight_wagon", litt: "Sgns", number: "31 74 4?5 1 209-6" },
    suggestions: { kind: { ...suggestion("freight_wagon"), basis: "visual_inference" }, litt: suggestion("Sgns"), number: suggestion("31 74 4?5 1 209-6", "medium") },
    question: { field: "number", options: ["31 74 455 1 209-6", "31 74 485 1 209-6"] },
    warnings: ["Numret är delvis skymt."],
    attempts: 1,
    ...change,
  });

const TOKENS_OUT = "Tokens tog slut. Fyll i resten för hand eller köp tokens i TrainMeet ID.";
const left = (n: number, change: Partial<BatchCard> = {}) => draft(n, { status: "manual", message: TOKENS_OUT, ...change });

function batch(cards: BatchCard[], change: Partial<Batch> = {}): Batch {
  return { id: BATCH, ai: true, source: "photo", mine: true, created_at: NOW, cards, waiting_until: null, message: null, already: [], ...change };
}

const view = (props: Partial<Parameters<typeof BatchView>[0]> = {}) =>
  renderToStaticMarkup(<BatchView ctx={ctx()} batch={null} ai consent={consent()} chosen={[]} {...props} />);

const photo = (name = "IMG_4410.jpg", type = "image/jpeg", size = 1000) => new File([new Uint8Array(size)], name, { type });

/** fetch, answering in turn, and remembering what was asked. */
function answers(...replies: (Response | Error)[]) {
  const asked: { url: string; init: RequestInit }[] = [];
  const fetch = vi.fn(async (url: string, init: RequestInit) => {
    asked.push({ url, init });
    const reply = replies.shift();
    if (!reply) throw new Error(`Nothing more was expected: ${url}`);
    if (reply instanceof Error) throw reply;
    return reply;
  });
  vi.stubGlobal("fetch", fetch);
  return asked;
}

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const problem = (status: number, code: string, more: Record<string, unknown> = {}) => json({ code, message: "på svenska", ...more }, status);
const sentAsk = (init: RequestInit) => JSON.parse(String((init.body as FormData).get("data"))) as Record<string, unknown>;

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Lägg till flera on the vehicles page (CAT-147, CAT-153)", () => {
  const list: VehicleList = { vehicles: [], counts: { home: 0, packed: 0, at_meet: 0, lent: 0 }, total: 0 };
  const vehicles = (c: Ctx, batches: BatchSummary[] | null = null) =>
    renderToStaticMarkup(<VehiclesView ctx={c} account={account} list={list} q="" state={null} group="all" selected={new Set()} error={null} batches={batches} />);

  it("is beside Lägg till med foto for the owner, and Lämna foton till ägaren for an editor", () => {
    expect(vehicles(ctx())).toContain('<a class="tm-knapp" href="/fordon/nytt/flera">Lägg till flera</a>');
    expect(vehicles(ctx())).toContain('href="/fordon/nytt/foto">Lägg till med foto</a>');
    const theirs = vehicles(editor);
    expect(theirs).toContain('<a class="tm-knapp" href="/fordon/nytt/flera">Lämna foton till ägaren</a>');
    expect(theirs).not.toContain("Lägg till flera");
    expect(vehicles(viewer)).not.toContain("/fordon/nytt/flera");
    // The address itself tells someone who only looks so.
    expect(renderToStaticMarkup(<BatchPage ctx={viewer} />)).toContain("Du kan bara titta i den här vagnparken.");
  });

  it("has addresses of its own in the Fordon tab", () => {
    expect(routeFor(PATHS.newBatch)).toEqual({ page: "newBatch" });
    expect(routeFor(batchPath(BATCH))).toEqual({ page: "batch", id: BATCH });
    expect(routeFor(`${batchPath(BATCH)}?fanns=2`)).toEqual({ page: "batch", id: BATCH });
    expect(tabOf("newBatch")).toBe("vehicles");
    expect(tabOf("batch")).toBe("vehicles");
  });

  it("lists the batches still to approve under the vehicles, with what is left", () => {
    const summary: BatchSummary = { id: BATCH, ai: true, source: "photo", mine: true, created_at: NOW, cards: 8, open: 8, counts: { waiting: 3, reading: 1, ready: 3, review: 1, failed: 0, manual: 0, approved: 0 } };
    const html = vehicles(ctx(), [summary, { ...summary, id: card(9), mine: false, cards: 2, open: 1, counts: { manual: 1, approved: 1 } }]);
    expect(html).toContain("<h2");
    expect(html).toContain("Omgångar att gå igenom");
    expect(html).toContain(`href="/fordon/omgangar/${BATCH}"`);
    expect(html).toContain("8 av 8 foton kvar att godkänna · 3 klara · 1 att kolla · 4 kvar");
    expect(html).toContain("1 av 2 foton kvar att godkänna · 0 klara · 1 att kolla · 0 kvar · Lämnad av någon annan");
    expect(renderToStaticMarkup(<BatchesSection ctx={editor} batches={[summary]} />)).toContain("Dina foton till ägaren");
    expect(vehicles(ctx(), [])).not.toContain("Omgångar att gå igenom");
  });
});

describe("choosing the photos and the price (CAT-147, CAT-19, CAT-142)", () => {
  it("takes up to 30 photos Catalog can read, with those already in the batch", () => {
    const many = Array.from({ length: 31 }, (_, n) => photo(`IMG_${4400 + n}.jpg`));
    const all = choosePhotos([], many, 0);
    expect(all.photos).toHaveLength(30);
    expect(all.problem).toBe("batch_full");
    expect(choosePhotos([], [photo()], 30)).toEqual({ photos: [], problem: "batch_full" });
    const some = choosePhotos([photo("a.jpg")], [photo("b.gif", "image/gif"), photo("c.png", "image/png"), photo("d.jpg", "image/jpeg", 16 * 1024 * 1024)], 27);
    expect(some.photos.map((p) => p.name)).toEqual(["a.jpg", "c.png"]);
    expect(some.problem).toBe("picture_too_large");
  });

  it("shows the price, the balance and that it runs short before anything is sent", () => {
    const html = view({ chosen: [photo("1.jpg"), photo("2.jpg"), photo("3.jpg"), photo("4.jpg")] });
    expect(html).toContain("<h1>Många foton på en gång</h1>");
    expect(html).toContain("Ett foto per fordon. De läses i tur och ordning medan du gör annat.");
    expect(html).toContain("4 × 12 tokens");
    expect(html).toContain("<b>48 tokens</b>");
    expect(html).toContain("Saldo: 36 tokens");
    expect(html).toContain("Saldot räcker inte för den här avläsningen.");
    expect(html).toContain('<a class="tm-knapp" href="https://test.id.trainmeet.app/tokens">Köp tokens i TrainMeet ID</a>');
    expect(html).toContain("Räcker saldot inte blir resten foton att fylla i för hand.");
    expect(html).toContain('<button type="button" class="tm-knapp primar">Läs av 4 foton</button>');
    expect(view({ chosen: [photo()], consent: consent({ own_ai: "Claude Sonnet", price_per_picture: 0 }) })).toContain("Din egen AI läser av (Claude Sonnet). Det kostar inga tokens.");
  });

  it("leaves the photos for the owner without AI and without tokens for an editor", () => {
    const html = renderToStaticMarkup(<BatchView ctx={editor} batch={null} ai={false} consent={null} chosen={[photo("1.jpg"), photo("2.jpg")]} />);
    expect(html).toContain("<h1>Foton till ägaren</h1>");
    expect(html).toContain("Ingen AI läser dem");
    expect(html).toContain("Utan AI kostar fotona inga tokens.");
    expect(html).toContain(">Lämna 2 foton<");
    expect(html).not.toContain("tokens per bild");
    expect(html).not.toContain("Godkänn alla");
  });

  it("shows the progress while the photos are sent", () => {
    const html = view({ chosen: [photo("1.jpg"), photo("2.jpg"), photo("3.jpg")], sending: { done: 1, of: 3 } });
    expect(html).toContain('<progress max="3" value="1" aria-hidden="true"></progress><span>Skickar foto 2 av 3 …</span>');
    expect(html).toContain('<button type="button" class="tm-knapp primar" disabled="">Läs av 3 foton</button>');
  });
});

describe("sending the photos (CAT-147, CAT-149)", () => {
  it("sends one photo a request with the batch's id, and gathers the cards they already were", async () => {
    const one = batch([draft(1)]);
    const two = batch([draft(1), draft(2)], { already: [card(7)] });
    const asked = answers(json(one), json(two), json(batch([draft(1), draft(2)], { already: [card(7)] })));
    const done: number[] = [];
    const sent = await sendPhotos({ id: BATCH, ai: true, consent: true }, [photo("1.jpg"), photo("2.jpg"), photo("3.jpg")], (n) => done.push(n));
    expect(sent).toMatchObject({ sent: 3, error: null, already: [card(7)] });
    expect(sent.batch?.cards).toHaveLength(2);
    expect(done).toEqual([1, 2, 3]);
    expect(asked.map((call) => [call.url, call.init.method])).toEqual([
      ["/api/catalog/1/batches", "POST"],
      ["/api/catalog/1/batches", "POST"],
      ["/api/catalog/1/batches", "POST"],
    ]);
    expect(asked.map((call) => sentAsk(call.init))).toEqual([0, 1, 2].map(() => ({ id: BATCH, ai: true, consent: true })));
    expect(asked.map((call) => (call.init.body as FormData).getAll("images").length)).toEqual([1, 1, 1]);
  });

  it("stops at the first no, so the rest can be sent again with the same id", async () => {
    answers(json(batch([draft(1)])), problem(415, "bad_picture"));
    const sent = await sendPhotos({ id: BATCH, ai: false, consent: false }, [photo("1.jpg"), photo("2.jpg"), photo("3.jpg")]);
    expect(sent.sent).toBe(1);
    expect(sent.error).toBeInstanceOf(ApiError);
    expect(sendProblem(t, sent.error)).toBe(t("problem_bad_picture"));
    expect(sendProblem(t, new ApiError(413, null))).toBe("Bilden är för stor. Högst 15 MB per bild.");
    expect(sendProblem(t, new ApiError(422, "too_many_pictures"))).toContain("Högst 30 foton i en omgång");
    expect(sendProblem(t, new ApiError(422, "bad_form"))).toBe("Formuläret kunde inte läsas. Försök igen.");
  });
});

describe("the queue and the drafts (CAT-147, CAT-148, CAT-152)", () => {
  const read = batch([gbs(), sgns(), draft(3, { status: "reading", attempts: 1 }), draft(4)]);

  it("shows the cards in order with thumbnail, status and the suggestions marked", () => {
    const html = view({ batch: read });
    expect(html).toContain("<h2");
    expect(html).toContain(">4 foton</h2>");
    expect(html).toContain("1 klara · 1 att kolla · 2 kvar");
    expect(html).toContain('<progress class="cat-kostapel" max="4" value="2" aria-hidden="true"></progress>');
    const order = ["Gbs 3087", "Sgns 31 74 4?5 1 209-6", "läser …", "väntar"].map((name) => html.indexOf(name));
    expect(order.every((at, index) => at > 0 && (index === 0 || at > order[index - 1]!))).toBe(true);
    expect(html).toContain('<img class="cat-listbild" src="/api/catalog/1/pictures/file/t1.jpg" alt="Foto 1"');
    expect(html).toContain('<span class="cat-pill cat-pill-kort-ready">Klar</span>');
    expect(html).toContain('<span class="cat-pill cat-pill-kort-review">Att kolla</span>');
    expect(html).toContain('<span class="cat-pill cat-pill-kort-reading">Läser</span>');
    expect(html).toContain('<span class="cat-pill cat-pill-kort-waiting">I kö</span>');
    expect(html).toContain('<span class="cat-pill cat-pill-ai">AI-förslag</span><span class="cat-under">Slag Godsvagn · Littera Gbs · Nummer 3087</span>');
    expect(html).toContain('<span class="cat-pill cat-pill-ai">AI-förslag, osäkert</span><span class="cat-under">Bolag Green Cargo</span>');
    expect(html).toContain("En siffra i numret är osäker.");
    // Nothing in the queue is edited; Godkänn alla waits for it.
    expect(html).not.toContain('aria-label="Ändra foto 3"');
    expect(html).toContain('aria-label="Ändra foto 1"');
    expect(html).toContain('<button type="button" class="tm-knapp primar" disabled="">Godkänn alla (4)</button>');
    expect(html).toContain("Godkänn alla går när alla foton är lästa.");
    expect(canApprove(read)).toBe(false);
    expect(tally(read.cards)).toEqual({ ready: 1, check: 1, left: 2, total: 4 });
  });

  it("a value the owner changed is no longer marked as the AI's", () => {
    const changed = gbs({ values: { ...gbs().values, operator: "SJ" } });
    const html = renderToStaticMarkup(<CardRow ctx={ctx()} card={changed} n={1} ai stopped={false} busy={false} />);
    expect(html).not.toContain("Green Cargo");
    expect(html).toContain("Godsvagn · SJ");
    expect(html).toContain('<span class="cat-under">Slag Godsvagn · Littera Gbs · Nummer 3087</span>');
    expect(html).not.toContain("AI-förslag, osäkert");
  });

  it("shows the queue's wait and when it goes on (CAT-146)", () => {
    const html = view({ batch: batch([draft(1)], { waiting_until: "2026-11-18T13:00:00Z", message: "Högst 30 avläsningar i timmen för en omgång. Omgången fortsätter om 60 minuter." }) });
    expect(html).toContain("Högst 30 avläsningar i timmen för en omgång. Omgången fortsätter om 60 minuter. Den fortsätter av sig själv 18 nov.");
    const english = renderToStaticMarkup(<BatchView ctx={ctx("en")} batch={batch([draft(1)], { waiting_until: "2026-11-18T13:00:00Z", message: "på svenska" })} ai consent={consent()} chosen={[]} />);
    expect(english).toContain("The queue is waiting. It goes on by itself at 18 Nov");
    expect(english).not.toContain("på svenska");
  });

  it("says when the tokens ran out, links to Köp tokens, and offers to read the rest again", () => {
    const out = batch([gbs(), gbs({ id: card(2), position: 1 }), gbs({ id: card(3), position: 2 }), left(4)]);
    expect(tokensRanOut(out)).toBe(true);
    expect(tokensRanOut(batch([left(1)], { ai: false }))).toBe(false);
    const html = view({ batch: out, onRetry: () => undefined });
    expect(html).toContain("Tokens tog slut. Fotona som är kvar fyller du i för hand, eller köper tokens i TrainMeet ID och läser av dem igen.");
    expect(html).toContain('<a class="tm-knapp" href="https://test.id.trainmeet.app/tokens">Köp tokens i TrainMeet ID</a>');
    expect(html).toContain("Inget ifyllt än");
    expect(html).toContain(`<p class="cat-hjalp">${TOKENS_OUT}</p>`);
    expect(html).toContain('<span class="cat-pill cat-pill-kort-manual">Fyll i själv</span>');
    expect(html).toContain('aria-label="Läs av foto 4 igen">Läs av igen</button>');
    expect(html.match(/Läs av igen</g)).toHaveLength(1);
    expect(html).toContain('<button type="button" class="tm-knapp primar">Godkänn alla (4)</button>');
    expect(canApprove(out)).toBe(true);
    // In English the card says it in English.
    expect(renderToStaticMarkup(<CardRow ctx={ctx("en")} card={left(4)} n={4} ai stopped={false} busy={false} />)).toContain("Without AI: fill in the details yourself.");
  });

  it("someone who edits sees their photos without AI, and nothing to approve or read again", () => {
    const theirs = batch([left(1, { message: "Utan AI: fyll i fälten för hand." })], { ai: false });
    const html = renderToStaticMarkup(<BatchView ctx={editor} batch={theirs} ai={false} consent={null} chosen={[]} />);
    expect(html).toContain("Utan AI: fyll i fälten för hand.");
    expect(html).toContain("Ägaren går igenom fotona och godkänner dem.");
    expect(html).not.toContain("Godkänn alla");
    expect(html).not.toContain("Läs av igen");
    expect(html).not.toContain("Tokens tog slut");
    expect(html).toContain('aria-label="Ändra foto 1"');
    expect(html).toContain('aria-label="Ta bort foto 1"');
  });

  it("removes and reads again through the batch's own addresses", async () => {
    const asked = answers(json({ id: card(4) }), json(left(4, { status: "waiting", message: "" })));
    await api.removeCard(BATCH, card(4));
    expect((await api.retryCard(BATCH, card(4))).status).toBe("waiting");
    expect(asked.map((call) => [call.init.method, call.url])).toEqual([
      ["DELETE", `/api/catalog/1/batches/${BATCH}/cards/${card(4)}`],
      ["POST", `/api/catalog/1/batches/${BATCH}/cards/${card(4)}/retry`],
    ]);
  });
});

describe("a draft in the form of Lägg till med foto (CAT-136, CAT-138, CAT-140)", () => {
  const editView = (c: BatchCard, flow = cardFlow(c)) =>
    renderToStaticMarkup(<CardEditView ctx={ctx()} batch={batch([gbs(), c])} card={c} n={2} flow={flow} places={[]} busy={false} error={null} />);

  it("marks the suggestions still as the AI made them, and asks about the uncertain digit", () => {
    const flow = cardFlow(sgns());
    expect(Object.keys(flow.marks).sort()).toEqual(["kind", "litt", "number"]);
    expect(stillUnreadable(flow)).toEqual(["number"]);
    expect(openQuestion(flow)).toEqual(["31 74 455 1 209-6", "31 74 485 1 209-6"]);
    const html = editView(sgns());
    expect(html).toContain("<h1>Foto 2 i omgången</h1>");
    expect(html).toContain("AI:n föreslår");
    expect(html).toContain('<img class="cat-kortbild" src="/api/catalog/1/pictures/file/d2.jpg" alt="Foto 2"/>');
    expect(html).toContain("Står det 455 eller 485 i numret?");
    expect(html).toContain("<li>Numret är delvis skymt.</li>");
    expect(html).toContain('aria-label="Godkänn förslaget för Littera"');
    expect(html).toContain(">Godkänn alla förslag<");
    expect(html).toContain("Ett tecken i Nummer kunde inte läsas och står som ?. Rätta det innan du sparar.");
    expect(html).toContain('<button type="submit" class="tm-knapp primar" disabled="">Spara</button>');
  });

  it("the answer, an edit and Godkänn work as in Lägg till med foto, and the change carries the version", () => {
    const answered = answer(cardFlow(sgns()), "31 74 485 1 209-6");
    expect(stillUnreadable(answered)).toEqual([]);
    expect(answered.marks.number).toBeUndefined();
    const edited = edit(answered, { ...answered.fields, litt: "Sgnss" });
    expect(Object.keys(edited.marks)).toEqual(["kind"]);
    expect(accept(edited).marks).toEqual({});
    expect(cardChange(edited, sgns())).toEqual({
      values: { ...sgns().values, status: "ready", litt: "Sgnss", number: "31 74 485 1 209-6", dcc_address: "", functions: [] },
      version: 2,
    });
    expect(editView(sgns(), answered)).toContain('<button type="submit" class="tm-knapp primar">Spara</button>');
  });

  it("a photo to fill in by hand is simply the form", () => {
    const html = editView(left(2));
    expect(html).toContain("Fyll i för hand");
    expect(html).not.toContain("cat-ai");
    expect(html).toContain("Ändringen sparas i utkastet. Det blir ett fordon när omgången godkänns.");
    expect(cardFlow(left(2)).marks).toEqual({});
  });

  it("sends the change of a card on the version seen", async () => {
    const asked = answers(json(gbs({ version: 3 })));
    await api.changeCard(BATCH, card(1), cardChange(cardFlow(gbs()), gbs()));
    expect(asked[0]?.url).toBe(`/api/catalog/1/batches/${BATCH}/cards/${card(1)}`);
    expect(JSON.parse(String(asked[0]?.init.body))).toMatchObject({ version: 2, values: { litt: "Gbs", number: "3087", kind: "freight_wagon" } });
  });
});

describe("Godkänn alla (CAT-150, CAT-136)", () => {
  const out = batch([gbs(), gbs({ id: card(2), position: 1, version: 4 }), left(3)]);

  it("sends every open card with the version shown, and gives the batch back", async () => {
    const asked = answers(json(batch(out.cards.map((c) => ({ ...c, status: "approved" as const })))));
    const outcome = await approveAll(batch([...out.cards, draft(5, { status: "approved" })]));
    expect(outcome.kind).toBe("approved");
    expect(asked[0]?.url).toBe(`/api/catalog/1/batches/${BATCH}/approve`);
    expect(asked[0]?.init.method).toBe("POST");
    expect(JSON.parse(String(asked[0]?.init.body))).toEqual({
      cards: [
        { id: card(1), version: 2 },
        { id: card(2), version: 4 },
        { id: card(3), version: 1 },
      ],
    });
  });

  it("names the cards that stopped it, when nothing was approved", async () => {
    answers(problem(422, "not_ready", { cards: [card(3)] }));
    const outcome = await approveAll(out);
    expect(outcome).toMatchObject({ kind: "stopped", cards: [card(3)], unreadable: false });
    const html = view({ batch: out, stopped: [card(3)], approveError: t("batchStoppedOne") });
    expect(html).toContain(`<li id="kort-${card(3)}" class="cat-omgangskort cat-stoppad" tabindex="-1">`);
    expect(html).toContain('<p class="cat-fel">Fyll i eller ändra det här fotot.</p>');
    expect(html).toContain('role="alert">Inget godkändes. Ett foto behöver fyllas i eller ändras först.</p>');
    expect(html.match(/cat-stoppad/g)).toHaveLength(1);
    expect(text("sv", "batchStopped", { n: 2 })).toBe("Inget godkändes. 2 foton behöver fyllas i eller ändras först.");
  });

  it("waits for a ? the AI could not read, as Spara does, without asking Catalog", async () => {
    const asked = answers();
    const unsure = batch([gbs(), sgns()]);
    expect(unreadableCards(unsure)).toEqual([card(2)]);
    expect(await approveAll(unsure)).toEqual({ kind: "stopped", cards: [card(2)], unreadable: true, error: null });
    expect(asked).toHaveLength(0);
  });

  it("anything else is said as Catalog's problem", async () => {
    answers(problem(409, "changed"), problem(409, "reading_busy"));
    const changed = await approveAll(out);
    expect(changed.kind === "failed" && changed.error instanceof ApiError && changed.error.code).toBe("changed");
    const busy = await approveAll(out);
    expect(busy.kind === "failed" && busy.error instanceof ApiError && busy.error.cards).toEqual([]);
  });
});

describe("the texts", () => {
  it("has a text for the new problem, and the card statuses, in both languages", () => {
    for (const language of ["sv", "en"] as const) {
      expect(TEXTS[language]).toHaveProperty("problem_bad_form");
      for (const status of ["waiting", "reading", "ready", "review", "failed", "manual", "approved"]) expect(TEXTS[language]).toHaveProperty(`cardStatus_${status}`);
    }
  });
});
