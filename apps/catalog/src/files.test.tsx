import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, EXPORT_HREF, tellurianForm, tellurianHref, workIn, type Batch, type Session, type TellurianImport, type Vehicle, type VehicleList, type VehicleTag } from "./api";
import { Shell } from "./App";
import { BatchesSection, BatchView, CardRow } from "./BatchPage";
import type { Ctx } from "./common";
import { ImportResult, ImportView, importProblem } from "./ImportPage";
import { text } from "./i18n";
import { chosenFromAddress, labelPlan, labelText, makeLabels, perSheet, printWhenReady, qrLabel, withChanged } from "./labels";
import { LabelSheet, LabelsView } from "./LabelsPage";
import { labelsPath, PATHS, routeFor, tabOf } from "./routes";
import { chooseFiles, importCounts, importFiles, reviewBatch } from "./tellurian";
import { CardView, TagSection } from "./VehicleCard";
import { VehiclesView } from "./VehiclesPage";

const ctx = (language: "sv" | "en" = "sv"): Ctx => ({ t: (key, vars) => text(language, key, vars), language });
const editor: Ctx = { ...ctx(), right: "edit", fleetTitle: "Vagnparken · Provkonto A" };
const viewer: Ctx = { ...ctx(), right: "view", fleetTitle: "Vagnparken · Provkonto A" };
const NOW = "2026-11-18T12:00:00Z";
const account = { id: "8a3e1f0c-1111-5222-8333-944455556666", name: "Provkonto A", initials: "PA" };
const ID = (n: number) => `1b9d6bcd-bbfd-4b2d-9b5d-ab8dfbbd4b0${n}`;
const BATCH = "5b2c9e1a-0000-4000-8000-000000000186";

function label(n: number): VehicleTag {
  return {
    assignment: `9c0e4b6a-0000-4000-8000-00000000000${n}`,
    tag: `9c0e4b6a-1111-4000-8000-00000000000${n}`,
    uid: `qabcdefghjk${n}`,
    name: `QR ABCD`,
    kind: "qr",
    address: `https://trainmeet.app/t/qabcdefghjk${n}`,
    linked_at: NOW,
  };
}

function vehicle(n: number, change: Partial<Vehicle> = {}): Vehicle {
  return {
    id: ID(n),
    version: 1,
    status: "ready",
    kind: "freight_wagon",
    litt: "Gbs",
    number: `21 74 150 3 08${n}`,
    operator: "",
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
    notices: [],
    picture: null,
    prototype: null,
    created_at: NOW,
    updated_at: NOW,
    ...change,
  };
}

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

/** fetch, answering in turn, and remembering what was asked. */
function answers(...replies: Response[]) {
  const asked: { url: string; init: RequestInit }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit) => {
      asked.push({ url, init });
      const reply = replies.shift();
      if (!reply) throw new Error(`Nothing more was expected: ${url}`);
      return reply;
    }),
  );
  return asked;
}

afterEach(() => {
  vi.unstubAllGlobals();
  workIn(null);
});

describe("the QR label sheet (CAT-184)", () => {
  const gbs = vehicle(1, { tags: [label(1)] });
  const hbis = vehicle(2, { litt: "Hbis", number: "2253" });
  const draft = vehicle(3, { status: "draft", litt: "Zans", number: "" });

  it("has an address of its own in the Fordon tab, with the vehicles chosen", () => {
    expect(routeFor(PATHS.labels)).toEqual({ page: "labels" });
    expect(tabOf("labels")).toBe("vehicles");
    expect(labelsPath([ID(1), ID(2)])).toBe(`/fordon/etiketter?fordon=${ID(1)},${ID(2)}`);
    expect(routeFor(labelsPath([ID(1)]))).toEqual({ page: "labels" });
    expect(chosenFromAddress(`?fordon=${ID(1)},${ID(2).toUpperCase()},`)).toEqual(new Set([ID(1), ID(2)]));
  });

  it("puts each code with the litt and the number in plain text under it", () => {
    const html = renderToStaticMarkup(<LabelSheet t={ctx().t} vehicles={[gbs, hbis]} size="small" />);
    expect(html).toContain('class="cat-ark cat-ark-small"');
    expect(html).toContain(`<img src="/api/catalog/1/tags/${label(1).uid}/qr.svg" alt="QR-kod för ${label(1).address}"/>`);
    expect(html).toContain("<figcaption>Gbs 21 74 150 3 081</figcaption>");
    // Hbis has no label yet: it gets one when the sheet is printed.
    expect(html).toContain('aria-label="Ny etikett"');
    expect(html).toContain("<figcaption>Hbis 2253</figcaption>");
    expect(renderToStaticMarkup(<LabelSheet t={ctx().t} vehicles={[gbs]} size="large" />)).toContain("cat-ark-large");
    expect(labelText({ litt: "", number: "3087" })).toBe("3087");
  });

  it("offers a small and a large label, and says how many fit an A4 sheet", () => {
    expect(perSheet("small")).toBe(30);
    expect(perSheet("large")).toBe(12);
    const html = renderToStaticMarkup(<LabelsView ctx={ctx()} vehicles={[gbs, hbis, draft]} chosen={new Set([ID(1), ID(2), ID(3)])} size="small" renew={false} />);
    expect(html).toContain("Liten, 30 mm (30 per A4-ark)");
    expect(html).toContain("Stor, 50 mm (12 per A4-ark)");
    expect(html).toContain("Skriv ut 2 etiketter");
    expect(html).toContain("1 av fordonen får en ny QR-etikett när du skriver ut.");
    // A draft gets no label (CAT-84): it cannot be chosen.
    expect(html).toContain("Utkast: spara det som klart först");
    expect(html).toMatch(/<input type="checkbox" disabled=""\/><b>Zans<\/b>/);
    expect(renderToStaticMarkup(<LabelsView ctx={ctx()} vehicles={[gbs]} chosen={new Set()} size="small" renew={false} />)).toContain("Välj minst ett klart fordon.");
  });

  it("makes a label only for a vehicle without one, and replaces one only when asked", async () => {
    const plan = labelPlan([gbs, hbis, draft], new Set([ID(1), ID(2), ID(3)]), false);
    expect(plan.print.map((v) => v.id)).toEqual([ID(1), ID(2)]);
    expect(plan.make.map((v) => v.id)).toEqual([ID(2)]);
    expect(plan.replace).toEqual([]);
    expect(plan.drafts.map((v) => v.id)).toEqual([ID(3)]);
    const renewed = labelPlan([gbs, hbis], new Set([ID(1), ID(2)]), true);
    expect(renewed.replace.map((v) => v.id)).toEqual([ID(1)]);

    const labelled = vehicle(2, { litt: "Hbis", number: "2253", tags: [label(2)] });
    const relabelled = vehicle(1, { tags: [label(3)] });
    const asked = answers(json(labelled), json(relabelled));
    const done = await makeLabels(renewed);
    expect(done.error).toBeNull();
    expect(asked.map((call) => [call.url, JSON.parse(String(call.init.body))])).toEqual([
      [`/api/catalog/1/vehicles/${ID(2)}/tags/qr`, { replace: null }],
      // The label as it was seen is the one replaced (CAT-89).
      [`/api/catalog/1/vehicles/${ID(1)}/tags/qr`, { replace: label(1).assignment }],
    ]);
    const now = withChanged([gbs, hbis], done.made);
    expect(now.map((v) => qrLabel(v)?.uid)).toEqual([label(3).uid, label(2).uid]);
  });

  it("stops at the first no, and keeps what was made", async () => {
    answers(json({ code: "not_ready", message: "Spara fordonet som klart innan det får en etikett." }, 422));
    const done = await makeLabels(labelPlan([hbis], new Set([ID(2)]), false));
    expect(done.made).toEqual([]);
    expect(done.error).toBeInstanceOf(ApiError);
  });

  it("prints when the codes have come", async () => {
    const print = vi.fn();
    const coming = { complete: false, addEventListener: (event: string, done: () => void) => event === "load" && setTimeout(done, 1) };
    const sheet = { querySelectorAll: () => [{ complete: true }, coming] } as unknown as ParentNode;
    await printWhenReady(sheet, print);
    expect(print).toHaveBeenCalledOnce();
  });

  it("is the owner's, from the list and from the label on the card", () => {
    const list: VehicleList = { vehicles: [gbs], counts: { home: 1, packed: 0, at_meet: 0, lent: 0 }, total: 1 };
    const view = (c: Ctx, selected = new Set<string>()) =>
      renderToStaticMarkup(<VehiclesView ctx={c} account={account} list={list} q="" state={null} group="all" selected={selected} error={null} />);
    expect(view(ctx())).toContain('<a class="tm-knapp" href="/fordon/etiketter">Skriv ut QR-etiketter</a>');
    expect(view(ctx(), new Set([ID(1)]))).toContain(`href="/fordon/etiketter?fordon=${ID(1)}">Skriv ut etiketter för 1 valda</a>`);
    expect(view(editor)).not.toContain("/fordon/etiketter");
    const card = renderToStaticMarkup(<TagSection ctx={ctx()} vehicle={gbs} pending={null} />);
    expect(card).toContain(`href="/fordon/etiketter?fordon=${ID(1)}">Skriv ut etiketten</a>`);
  });
});

describe("Tellurian's format (CAT-185, CAT-186)", () => {
  const file = (name: string, size = 100) => new File([new Uint8Array(size)], name, { type: "application/json" });
  const result = (change: Partial<TellurianImport> = {}): TellurianImport => ({
    batch: null,
    files: [
      { name: "Gbs.json", ok: true, card: ID(1), batch: BATCH, already: false, error: null, notes: ["Typuppgifterna i filen, som beskrivning, hastighet och längd, kom inte med. Koppla fordonet till en förebild för dem."] },
      { name: "Hbis.json", ok: true, card: ID(2), batch: BATCH, already: true, error: null, notes: [] },
      { name: "trasig.json", ok: false, card: null, batch: null, already: false, error: "Filen är inte giltig JSON.", notes: [] },
    ],
    ...change,
  });

  it("exports a vehicle as a file to download, for the owner", () => {
    expect(tellurianHref(ID(1))).toBe(`/api/catalog/1/vehicles/${ID(1)}/tellurian`);
    workIn("2c4f6a8b-0000-4000-8000-000000000001");
    expect(tellurianHref(ID(1))).toBe(`/api/catalog/1/vehicles/${ID(1)}/tellurian?fleet=2c4f6a8b-0000-4000-8000-000000000001`);
    workIn(null);
    const card = (c: Ctx) => renderToStaticMarkup(<CardView ctx={c} vehicle={vehicle(1)} events={[]} error={null} />);
    expect(card(ctx())).toContain(`<a class="tm-knapp" href="/api/catalog/1/vehicles/${ID(1)}/tellurian" download="">Exportera till Tellurian</a>`);
    expect(card(editor)).not.toContain("/tellurian");
    expect(card(viewer)).not.toContain("/tellurian");
  });

  it("has an import page of its own in the Fordon tab, for the owner and for an editor", () => {
    expect(routeFor(PATHS.importFiles)).toEqual({ page: "importFiles" });
    expect(tabOf("importFiles")).toBe("vehicles");
    const list: VehicleList = { vehicles: [], counts: { home: 0, packed: 0, at_meet: 0, lent: 0 }, total: 0 };
    const view = (c: Ctx) => renderToStaticMarkup(<VehiclesView ctx={c} account={account} list={list} q="" state={null} group="all" selected={new Set()} error={null} />);
    expect(view(ctx())).toContain('<a class="tm-knapp" href="/fordon/importera">Importera från Tellurian</a>');
    expect(view(editor)).toContain('href="/fordon/importera"');
    expect(view(viewer)).not.toContain('href="/fordon/importera"');
  });

  it("chooses 1–50 files, at most 20 MB each and 60 MB together", () => {
    const fifty = Array.from({ length: 50 }, (_, n) => file(`fil${n}.json`));
    expect(chooseFiles([], fifty)).toEqual({ files: fifty, problem: null });
    expect(chooseFiles(fifty, [file("en-till.json")])).toEqual({ files: fifty, problem: "too_many" });
    const large = file("stor.json", 20 * 1024 * 1024 + 1);
    expect(chooseFiles([], [large, file("liten.json")]).files.map((f) => f.name)).toEqual(["liten.json"]);
    expect(chooseFiles([], [large]).problem).toBe("too_large");
    const big = Array.from({ length: 4 }, (_, n) => file(`del${n}.json`, 19 * 1024 * 1024));
    expect(chooseFiles([], big)).toMatchObject({ problem: "too_large_together" });
    expect(chooseFiles([], big).files).toHaveLength(3);
  });

  it("sends the files in one form with the import's id and each file's name", async () => {
    const form = tellurianForm({ id: BATCH }, [file("Gbs.json"), file("Hbis.json")]);
    expect(JSON.parse(String(form.get("data")))).toEqual({ id: BATCH });
    expect(form.getAll("files").map((part) => (part as File).name)).toEqual(["Gbs.json", "Hbis.json"]);
    const asked = answers(json(result()));
    const done = await importFiles(BATCH, [file("Gbs.json")]);
    expect(asked[0]?.url).toBe("/api/catalog/1/batches/tellurian");
    expect(asked[0]?.init.method).toBe("POST");
    expect(done.result?.files).toHaveLength(3);
    answers(json({ code: "files_too_large", message: "Filerna är större än 60 MB tillsammans." }, 413));
    const refused = await importFiles(BATCH, [file("Gbs.json")]);
    expect(refused.result).toBeNull();
    expect(importProblem(ctx().t, refused.error)).toBe("Filerna är för stora tillsammans. Importera färre åt gången.");
    expect(importProblem(ctx().t, new ApiError(422, "too_many_pictures"))).toContain("Högst 60 utkast");
  });

  it("tells how each file went, in Swedish, and leads to the drafts to approve", () => {
    const done = result();
    expect(importCounts(done)).toEqual({ made: 1, already: 1, failed: 1 });
    expect(reviewBatch(done)).toBe(BATCH);
    expect(reviewBatch(result({ files: [] }))).toBeNull();
    const html = renderToStaticMarkup(<ImportResult ctx={ctx()} result={done} />);
    expect(html).toContain("1 nya utkast · 1 fanns redan · 1 gick inte");
    expect(html).toContain("<b>trasig.json</b>");
    expect(html).toContain('<p class="cat-fel">Filen är inte giltig JSON.</p>');
    expect(html).toContain("Koppla fordonet till en förebild för dem.");
    expect(html).toContain(`href="/fordon/omgangar/${BATCH}">Granska och godkänn</a>`);
    // An editor's drafts wait for the owner.
    expect(renderToStaticMarkup(<ImportResult ctx={editor} result={done} />)).toContain(">Till utkasten</a>");
    const english = renderToStaticMarkup(<ImportResult ctx={ctx("en")} result={done} />);
    expect(english).toContain("The file could not be read.");
  });

  it("shows the files chosen before they are sent", () => {
    const html = renderToStaticMarkup(<ImportView ctx={ctx()} chosen={[file("Gbs.json"), file("Hbis.json")]} problem="too_many" />);
    expect(html).toContain("Filer i Tellurians format");
    expect(html).toContain('accept=".json,application/json"');
    expect(html).toContain("Importera 2 filer");
    expect(html).toContain('aria-label="Ta bort Hbis.json"');
    expect(html).toContain("Högst 50 filer åt gången.");
  });

  it("reviews the drafts from files in the batch's page, with Godkänn alla", () => {
    const fromFile = {
      id: ID(1),
      batch: BATCH,
      position: 0,
      source: "file" as const,
      file_name: "Gbs.json",
      status: "ready" as const,
      version: 1,
      values: { status: "ready" as const, kind: "freight_wagon" as const, litt: "Gbs", number: "21 74 150 3 087-3", operator: "GC", epoch: "", scale: "H0", maker: "", article_number: "", note: "", dcc_address: "", functions: [], place: null },
      suggestions: {},
      question: null,
      warnings: [],
      message: "",
      picture: null,
      vehicle: null,
      attempts: 0,
      prototype: null,
    };
    const batch: Batch = { id: BATCH, ai: false, source: "file", mine: true, created_at: NOW, cards: [fromFile], waiting_until: null, message: null, already: [] };
    const html = renderToStaticMarkup(<BatchView ctx={ctx()} batch={batch} ai={false} consent={null} chosen={[]} />);
    expect(html).toContain("Importen från Tellurian");
    expect(html).toContain('href="/fordon/importera">Importera fler filer</a>');
    expect(html).not.toContain('type="file"');
    expect(html).toContain("Filerna kostar inga tokens.");
    expect(html).toContain("Godkänn alla (1)");
    const row = renderToStaticMarkup(<CardRow ctx={ctx()} card={fromFile} n={1} ai={false} stopped={false} busy={false} />);
    expect(row).toContain("<b>Gbs 21 74 150 3 087-3</b>");
    expect(row).toContain("Från Gbs.json");
    expect(row).toContain('aria-label="Ändra fil 1"');
    const listed = renderToStaticMarkup(
      <BatchesSection ctx={ctx()} batches={[{ id: BATCH, ai: false, source: "file", mine: true, created_at: NOW, cards: 2, open: 2, counts: { ready: 2 } }]} />,
    );
    expect(listed).toContain("Importen från");
    expect(listed).toContain("2 av 2 filer kvar att godkänna");
  });
});

describe("the account export (CAT-188)", () => {
  const session: Session = { account, login: "id", simulated_tags: false, share_url: null, help_url: null, apps: null, tokens: null, tokens_url: null, logout_url: null };

  it("is Hämta allt mitt in the account menu: one ZIP to download", () => {
    expect(EXPORT_HREF).toBe("/api/catalog/1/export");
    const html = renderToStaticMarkup(<Shell page="vehicles" language="sv" host="test.catalog.trainmeet.app" session={session} version={null} offline={false} fleet={false} />);
    expect(html).toContain('<a id="hamta-allt" href="/api/catalog/1/export" download="">Hämta allt mitt</a>');
    const english = renderToStaticMarkup(<Shell page="vehicles" language="en" host="test.catalog.trainmeet.app" session={session} version={null} offline={false} fleet={false} />);
    expect(english).toContain(">Download all mine</a>");
    // Logged out there is no account, and nothing to download.
    expect(renderToStaticMarkup(<Shell page="vehicles" language="sv" host="test.catalog.trainmeet.app" session={{ ...session, account: null }} version={null} offline={false} fleet={false} />)).not.toContain(
      "/api/catalog/1/export",
    );
  });
});
