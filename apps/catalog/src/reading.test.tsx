import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, type Reading, type ReadingConsent, type Vehicle, type VehicleList } from "./api";
import type { Ctx } from "./common";
import { text } from "./i18n";
import { ConsentView, PhotoFlowPage, PhotoStepView, QuestionView, ReviewView, Steps } from "./PhotoFlow";
import {
  accept,
  addPhotos,
  answer,
  applyReading,
  attemptReading,
  edit,
  keepsId,
  needsConsent,
  newFlow,
  openQuestion,
  readingTrouble,
  saveVehicle,
  skipReading,
  stillUnreadable,
  uncertainPart,
  type Flow,
} from "./reading";
import { PATHS, routeFor, tabOf } from "./routes";
import { VehiclesView } from "./VehiclesPage";

const ctx = (language: "sv" | "en" = "sv"): Ctx => ({ t: (key, vars) => text(language, key, vars), language, tokensUrl: "https://test.id.trainmeet.app/tokens" });
const editor: Ctx = { ...ctx(), right: "edit", fleetTitle: "Vagnparken · Provkonto A" };
const t = ctx().t;
const account = { id: "8a3e1f0c-1111-5222-8333-944455556666", name: "Provkonto A", initials: "PA" };
const ID = "5b2c9e1a-0000-4000-8000-000000000052";
const NOW = "2026-11-18T12:00:00Z";

const consent = (change: Partial<ReadingConsent> = {}): ReadingConsent => ({
  available: true,
  message: null,
  given: false,
  version: "2026-11-18",
  sent_to: "TrainMeets AI: Claude från Anthropic via Amazon Bedrock i EU",
  text: "Fotona, utan platsuppgifter och annan metadata, skickas till TrainMeets AI: Claude från Anthropic via Amazon Bedrock i EU.",
  own_ai: null,
  price_per_picture: 12,
  balance: 1240,
  payer: null,
  ...change,
});

const suggestion = (value: string, confidence: "high" | "medium" | "low" = "high") => ({
  value,
  confidence,
  basis: "visible_text" as const,
  evidence: "På vagnens sida",
});

function reading(change: Partial<Reading> = {}): Reading {
  return {
    id: ID,
    status: "done",
    suggestions: {
      kind: { ...suggestion("freight_wagon"), basis: "visual_inference" },
      litt: suggestion("Sgns"),
      number: suggestion("31 74 4?5 1 209-6", "medium"),
      operator: suggestion("privat", "low"),
    },
    question: { field: "number", options: ["31 74 455 1 209-6", "31 74 485 1 209-6"] },
    summary: "En containervagn från sidan, och en närbild på numret.",
    warnings: ["Numret är delvis skymt."],
    suggested_next_photo: "",
    cost: 24,
    model: "Claude",
    ...change,
  };
}

function vehicle(change: Partial<Vehicle> = {}): Vehicle {
  return {
    id: "1b9d6bcd-bbfd-4b2d-9b5d-ab8dfbbd4bed",
    version: 1,
    status: "ready",
    kind: "freight_wagon",
    litt: "Sgns",
    number: "31 74 455 1 209-6",
    operator: "privat",
    epoch: "",
    scale: "",
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
    created_at: NOW,
    updated_at: NOW,
    ...change,
  };
}

const photo = (name = "sidan.jpg", type = "image/jpeg", size = 1000) => new File([new Uint8Array(size)], name, { type });
const twoPhotos = (): Flow => addPhotos(newFlow(), [photo("sidan.jpg"), photo("numret.jpg")]).flow;

const review = (flow: Flow, change: { busy?: boolean; error?: string | null } = {}) =>
  renderToStaticMarkup(<ReviewView ctx={ctx()} flow={flow} previews={[]} busy={change.busy ?? false} error={change.error ?? null} />);

const photoStep = (flow: Flow, change: Partial<Parameters<typeof PhotoStepView>[0]> = {}) =>
  renderToStaticMarkup(<PhotoStepView ctx={ctx()} flow={flow} previews={[]} consent={consent()} trouble={null} problem={null} {...change} />);

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

const json = (body: unknown, status = 200, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", ...headers } });
const problem = (status: number, code: string, headers: Record<string, string> = {}) => json({ code, message: "på svenska" }, status, headers);
const sentAsk = (init: RequestInit) => JSON.parse(String((init.body as FormData).get("data"))) as Record<string, unknown>;

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Lägg till med foto on the vehicles page (CAT-134, CAT-46)", () => {
  const list: VehicleList = { vehicles: [], counts: { home: 0, packed: 0, at_meet: 0, lent: 0 }, total: 0 };
  const view = (c: Ctx) => renderToStaticMarkup(<VehiclesView ctx={c} account={account} list={list} q="" state={null} group="all" selected={new Set()} error={null} />);

  it("is the owner's main button, beside Lägg till för hand", () => {
    const html = view(ctx());
    expect(html).toContain('<a class="tm-knapp primar cat-huvudknapp" href="/fordon/nytt/foto">Lägg till med foto</a>');
    expect(html).toContain('<a class="tm-knapp" href="/fordon/nytt">Lägg till för hand</a>');
  });

  it("an editor sees no AI button, only Lägg till för hand", () => {
    const html = view(editor);
    expect(html).not.toContain("Lägg till med foto");
    expect(html).not.toContain("/fordon/nytt/foto");
    expect(html).toContain('<a class="tm-knapp primar cat-huvudknapp" href="/fordon/nytt">Lägg till för hand</a>');
    // The address itself sends an editor to the form.
    const page = renderToStaticMarkup(<PhotoFlowPage ctx={editor} />);
    expect(page).toContain("Bara ägaren läser av med AI.");
    expect(page).toContain('href="/fordon/nytt"');
    expect(page).not.toContain("Läs av");
  });

  it("has an address of its own in the Fordon tab", () => {
    expect(routeFor(PATHS.newPhoto)).toEqual({ page: "newPhoto" });
    expect(tabOf("newPhoto")).toBe("vehicles");
  });
});

describe("Fota (CAT-135, CAT-19)", () => {
  it("gives the advice, and the price and balance before anything is read", () => {
    const html = photoStep(twoPhotos());
    expect(html).toContain("Ta ett foto av hela fordonet från sidan, och en närbild på numret.");
    expect(html).toContain("Hela fordonet från sidan · Blir huvudbild");
    expect(html).toContain("Närbild på numret");
    expect(html).toContain("2 × 12 tokens");
    expect(html).toContain("<b>24 tokens</b>");
    expect(html).toContain("Saldo: 1\u00a0240 tokens");
    expect(html).toContain(">Läs av 2 bilder<");
    expect(html).toContain(">Hoppa över, fyll i själv<");
    expect(html).toContain('aria-current="step">Foto');
  });

  it("costs nothing with the account's own AI, and offers the form when the AI cannot be used", () => {
    expect(photoStep(twoPhotos(), { consent: consent({ own_ai: "Claude Sonnet", price_per_picture: 0 }) })).toContain("Din egen AI läser av (Claude Sonnet). Det kostar inga tokens.");
    const off = photoStep(twoPhotos(), { consent: consent({ available: false, message: "AI-avläsningen kräver ett konto i TrainMeet ID." }) });
    expect(off).toContain("AI-avläsningen går inte att använda här just nu.");
    expect(off).not.toContain(">Läs av 2 bilder<");
    expect(off).toContain('<button type="button" class="tm-knapp primar">Hoppa över, fyll i själv</button>');
  });

  it("takes 1–4 photos Catalog can read, and other photos are a new reading", () => {
    const four = addPhotos(newFlow(), [photo("1.jpg"), photo("2.jpg"), photo("3.jpg"), photo("4.jpg"), photo("5.jpg")]);
    expect(four.flow.photos.map((p) => p.name)).toEqual(["1.jpg", "2.jpg", "3.jpg", "4.jpg"]);
    expect(four.problem).toBe("photos_full");
    expect(addPhotos(newFlow(), [photo("a.gif", "image/gif")]).problem).toBe("bad_picture");
    const kept = { ...twoPhotos(), readingId: ID };
    expect(addPhotos(kept, [photo("3.jpg")]).flow.readingId).toBeNull();
    expect(photoStep(four.flow)).toContain("Fyra foton är det mesta som läses av på en gång.");
  });
});

describe("the consent the first time (CAT-142)", () => {
  it("shows what is sent and to whom, the price and the balance, before anything is sent", async () => {
    const asked = answers();
    expect(needsConsent(consent(), false)).toBe(true);
    expect(await attemptReading(ID, [photo()], consent(), false)).toEqual({ kind: "consent" });
    expect(asked).toHaveLength(0);
    const html = renderToStaticMarkup(<ConsentView ctx={ctx()} consent={consent()} photos={2} />);
    expect(html).toContain("skickas till TrainMeets AI: Claude från Anthropic via Amazon Bedrock i EU.");
    expect(html).toContain("<b>24 tokens</b>");
    expect(html).toContain("Saldo: 1\u00a0240 tokens");
    expect(html).toContain(">Ja, läs av<");
    const english = renderToStaticMarkup(<ConsentView ctx={ctx("en")} consent={consent({ own_ai: "Claude Sonnet", price_per_picture: 0 })} photos={1} />);
    expect(english).toContain("to your account&#x27;s own AI (Claude Sonnet).");
  });

  it("sends consent only after the yes, and then does not ask again", async () => {
    const asked = answers(json(reading()), json(reading({ id: "5b2c9e1a-0000-4000-8000-000000000053" })));
    const first = await attemptReading(ID, [photo("sidan.jpg"), photo("numret.jpg")], consent(), true);
    expect(first).toEqual({ kind: "read", reading: reading() });
    expect(asked[0]?.url).toBe("/api/catalog/1/readings");
    expect(asked[0]?.init.method).toBe("POST");
    expect(sentAsk(asked[0]!.init)).toEqual({ id: ID, consent: true, vehicle: null, version: null });
    expect((asked[0]!.init.body as FormData).getAll("images")).toHaveLength(2);
    // Said yes: Catalog keeps it, and the dialog does not come back.
    const given = consent({ given: true });
    expect(needsConsent(given, false)).toBe(false);
    const second = await attemptReading("5b2c9e1a-0000-4000-8000-000000000053", [photo()], given, false);
    expect(second.kind).toBe("read");
    expect(sentAsk(asked[1]!.init).consent).toBe(false);
  });

  it("shows the dialog when Catalog says consent_required", async () => {
    answers(problem(422, "consent_required"));
    expect(await attemptReading(ID, [photo()], consent({ given: true }), false)).toEqual({ kind: "consent" });
  });
});

describe("AI:n föreslår (CAT-136, CAT-137)", () => {
  const read = () => applyReading(twoPhotos(), reading());

  it("fills the form with the suggestions, marked until accepted or edited", () => {
    const flow = read();
    expect(flow.step).toBe("review");
    expect(flow.fields).toMatchObject({ kind: "freight_wagon", litt: "Sgns", number: "31 74 4?5 1 209-6", operator: "privat" });
    const html = review(flow);
    expect(html).toContain("AI:n föreslår");
    expect(html).toContain("Stämmer det här?");
    expect(html).toContain("Läst ur dina 2 bilder. Inget sparas förrän du sparar.");
    expect(html.match(/class="cat-ai"/g)).toHaveLength(3); // kind, litt, operator; the number is tm-mono cat-ai
    expect(html).toContain('class="tm-mono cat-ai"');
    expect(html).toContain('aria-label="Godkänn förslaget för Littera"');
    expect(html).toContain("AI-förslag, osäkert"); // the operator, low confidence
    expect(html).toContain(">Godkänn alla förslag<");
    expect(html).toContain("Spara godkänner de förslag som står kvar.");
    expect(html).toContain("En containervagn från sidan, och en närbild på numret.");
    expect(html).toContain("<li>Numret är delvis skymt.</li>");
    expect(html).toContain("Läst av Claude för 24 tokens.");
  });

  it("unmarks a field the owner edits, and Godkänn unmarks one or all", () => {
    const flow = read();
    const edited = edit(flow, { ...flow.fields, litt: "Sgnss" });
    expect(Object.keys(edited.marks).sort()).toEqual(["kind", "number", "operator"]);
    expect(review(edited)).not.toContain('aria-label="Godkänn förslaget för Littera"');
    expect(review(edited)).toContain('aria-label="Godkänn förslaget för Bolag"');
    expect(Object.keys(accept(edited, "operator").marks).sort()).toEqual(["kind", "number"]);
    const all = accept(edited);
    expect(all.marks).toEqual({});
    expect(review(all)).not.toContain("cat-ai");
    expect(review(all)).not.toContain("Godkänn alla förslag");
  });

  it("keeps the owner's own values when another photo is read, and asks for it", () => {
    const flow = edit(read(), { ...read().fields, litt: "Sgnss" });
    const again = applyReading(flow, reading({ suggestions: { litt: suggestion("Sgns"), operator: suggestion("AAE") }, question: null, suggested_next_photo: "En närbild på numret." }));
    expect(again.fields.litt).toBe("Sgnss");
    expect(again.fields.operator).toBe("AAE");
    expect(again.readingId).toBeNull();
    const html = review(again);
    expect(html).toContain("AI:n vill ha ett foto till");
    expect(html).toContain("En närbild på numret.");
    expect(html).toContain(">Lägg till ett foto till<");
  });

  it("never fills the kind with something that is not a kind", () => {
    const flow = applyReading(twoPhotos(), reading({ suggestions: { kind: suggestion("ångvagn") }, question: null }));
    expect(flow.fields.kind).toBeNull();
    expect(flow.marks).toEqual({});
  });
});

describe("an unreadable character and the uncertain digit (CAT-138, CAT-140)", () => {
  it("blocks Spara while a ? remains", () => {
    const flow = applyReading(twoPhotos(), reading({ question: null }));
    expect(stillUnreadable(flow)).toEqual(["number"]);
    const html = review(flow);
    expect(html).toContain("Ett tecken i Nummer kunde inte läsas och står som ?. Rätta det innan du sparar.");
    expect(html).toContain('<button type="submit" class="tm-knapp primar" disabled="">Spara</button>');
    expect(html).toContain('aria-invalid="true"');
    // Accepting is not fixing.
    expect(stillUnreadable(accept(flow))).toEqual(["number"]);
    const fixed = edit(flow, { ...flow.fields, number: "31 74 455 1 209-6" });
    expect(stillUnreadable(fixed)).toEqual([]);
    expect(review(fixed)).toContain('<button type="submit" class="tm-knapp primar">Spara</button>');
  });

  it("does not save a ? even if Spara is reached", async () => {
    const asked = answers();
    await expect(saveVehicle(applyReading(twoPhotos(), reading()))).rejects.toBeInstanceOf(ApiError);
    expect(asked).toHaveLength(0);
  });

  it("asks which digit it is, with the options as buttons and the check digit as the reason", () => {
    const flow = applyReading(twoPhotos(), reading());
    expect(openQuestion(flow)).toEqual(["31 74 455 1 209-6", "31 74 485 1 209-6"]);
    expect(uncertainPart("31 74 4?5 1 209-6", "31 74 485 1 209-6")).toBe("485");
    const html = review(flow);
    expect(html).toContain("Står det 455 eller 485 i numret?");
    expect(html).toContain('aria-label="Det är 31 74 455 1 209-6">Det är 455</button>');
    expect(html).toContain(">Det är 485</button>");
    expect(html).toContain("Bara de här går ihop med EVN-numrets kontrollsiffra.");
    expect(html).toContain(">Ta en närbild<");
  });

  it("fills the digit from the button: the number is the owner's, and Spara can save", () => {
    const answered = answer(applyReading(twoPhotos(), reading()), "31 74 485 1 209-6");
    expect(answered.fields.number).toBe("31 74 485 1 209-6");
    expect(answered.marks.number).toBeUndefined();
    expect(openQuestion(answered)).toBeNull();
    expect(stillUnreadable(answered)).toEqual([]);
    expect(review(answered)).not.toContain("Står det 455 eller 485");
  });

  it("names more than two options, and has no close-up when four photos are read", () => {
    const html = renderToStaticMarkup(<QuestionView ctx={ctx()} number="31 74 4?5" options={["31 74 405", "31 74 455", "31 74 485"]} canAdd={false} />);
    expect(html).toContain("Står det 405, 455 eller 485 i numret?");
    expect(html).not.toContain("Ta en närbild");
  });
});

describe("when the reading does not work (CAT-19, CAT-20, CAT-144, CAT-146)", () => {
  it("402: says so, that nothing was drawn, and links to Köp tokens i TrainMeet ID", async () => {
    answers(problem(402, "no_tokens"));
    const outcome = await attemptReading(ID, [photo()], consent({ given: true }), false);
    expect(outcome).toMatchObject({ kind: "failed", keepId: false });
    const trouble = readingTrouble(t, outcome.kind === "failed" ? outcome.error : null);
    expect(trouble).toEqual({ text: "Saldot räcker inte för avläsningen. Inget drogs.", buyTokens: true, byHand: false });
    const html = photoStep(twoPhotos(), { trouble });
    expect(html).toContain('role="alert"><p class="cat-fel">Saldot räcker inte för avläsningen. Inget drogs.</p>');
    expect(html).toContain('<a class="tm-knapp" href="https://test.id.trainmeet.app/tokens">Köp tokens i TrainMeet ID</a>');
  });

  it("429: waits as long as Catalog says", async () => {
    answers(problem(429, "too_many", { "Retry-After": "150" }));
    const outcome = await attemptReading(ID, [photo()], consent({ given: true }), false);
    expect(outcome.kind === "failed" && outcome.error instanceof ApiError && outcome.error.retryAfter).toBe(150);
    expect(readingTrouble(t, outcome.kind === "failed" ? outcome.error : null).text).toBe("Högst 10 avläsningar i timmen. Försök igen om 3 min. Inget drogs.");
    expect(readingTrouble(t, new ApiError(429, "too_many")).text).toBe("Taket för tokens i dag är nått i TrainMeet ID. Försök i morgon. Inget drogs.");
  });

  it("503: the AI cannot be used, so the form is offered", () => {
    const trouble = readingTrouble(t, new ApiError(503, "unavailable"));
    expect(trouble.byHand).toBe(true);
    expect(trouble.text).toContain("Inget drogs.");
    expect(photoStep(twoPhotos(), { trouble })).toContain('<button type="button" class="tm-knapp primar">Hoppa över, fyll i själv</button>');
  });

  it("keeps the reading's id when Catalog never answered or is still reading, so nothing is drawn twice", async () => {
    const asked = answers(new TypeError("Failed to fetch"), problem(409, "reading_busy"), json(reading()));
    const lost = await attemptReading(ID, [photo()], consent({ given: true }), false);
    expect(lost).toMatchObject({ kind: "failed", keepId: true });
    expect(readingTrouble(t, lost.kind === "failed" ? lost.error : null).text).toBe("Catalog svarade inte. Försök igen: samma avläsning läses och dras aldrig två gånger.");
    expect(await attemptReading(ID, [photo()], consent({ given: true }), false)).toMatchObject({ kind: "failed", keepId: true });
    expect((await attemptReading(ID, [photo()], consent({ given: true }), false)).kind).toBe("read");
    expect(asked.map((call) => sentAsk(call.init).id)).toEqual([ID, ID, ID]);
    // After any other answer nothing was read or drawn, and the next try is a new reading.
    for (const code of ["reading_failed", "no_tokens", "too_many", "unavailable", "changed"] as const) expect(keepsId(new ApiError(409, code))).toBe(false);
    expect(keepsId(new ApiError(504, null))).toBe(true);
    // A form Catalog could not read is an answer too.
    expect(keepsId(new ApiError(422, null))).toBe(false);
    expect(readingTrouble(t, new ApiError(422, null)).text).toBe("Det gick inte. Försök igen. Inget drogs.");
  });
});

describe("saving (CAT-134, CAT-143)", () => {
  it("works by hand, without a reading", async () => {
    const flow = skipReading(newFlow());
    const html = review(flow);
    expect(html).toContain("Fyll i uppgifterna");
    expect(html).toContain("Skriv in det du vet. Resten kan fyllas i senare.");
    expect(html).not.toContain("cat-ai");
    expect(html).not.toContain("AI:n såg");
    const filled = edit(flow, { ...flow.fields, kind: "locomotive", litt: "Rc6", number: "1340" });
    const asked = answers(json(vehicle({ kind: "locomotive", litt: "Rc6", number: "1340" })));
    const saved = await saveVehicle(filled);
    expect(saved.litt).toBe("Rc6");
    expect(asked).toHaveLength(1);
    expect(asked[0]?.url).toBe("/api/catalog/1/vehicles");
    expect(asked[0]?.init.method).toBe("POST");
    expect(JSON.parse(String(asked[0]?.init.body))).toMatchObject({ status: "ready", kind: "locomotive", litt: "Rc6", number: "1340" });
  });

  it("accepts the suggestions left through the vehicle's own address", async () => {
    const flow = answer(applyReading(twoPhotos(), reading()), "31 74 455 1 209-6");
    const asked = answers(json(vehicle()));
    await saveVehicle(flow);
    expect(asked.map((call) => call.url)).toEqual(["/api/catalog/1/vehicles"]);
    expect(JSON.parse(String(asked[0]?.init.body))).toMatchObject({ status: "ready", kind: "freight_wagon", litt: "Sgns", number: "31 74 455 1 209-6", operator: "privat", place: null });
  });

  it("shows the steps, with the ones behind done", () => {
    const html = renderToStaticMarkup(<Steps t={t} step="place" />);
    expect(html).toContain('<li class="cat-gjort">Foto<span class="cat-dold">, klart</span></li>');
    expect(html).toContain('aria-current="step">Plats och tagg');
  });
});
