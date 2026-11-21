// Webbläsarprovet för fjärrstyrningen (#36), i en riktig Chrome: en hubb med Provbanan, TKL A
// som stationen Åsen med referensstationen Gårdsjö på nivå 2, och TKL B som fjärrställverk (ingen
// egen station).
//
//   PROV_HUBB=http://127.0.0.1:8080 PROV_TKL_STATION=http://127.0.0.1:8095 \
//     PROV_TKL_FJARR=http://127.0.0.1:8093 PROV_TKL_GRANNE=http://127.0.0.1:8094 \
//     CHROME_PATH=/usr/bin/google-chrome node apps/tkl/e2e/fjarr.mjs
//
// PROV_HUBB är hubbens adress, PROV_TKL_STATION stationens TKL och PROV_TKL_FJARR fjärrställverkets,
// alla nystartade; PROV_TKL_GRANNE en tredje nystartad TKL, Norrbys, för grannen som fjärrstyr
// (FR3, valfri); PROV_HUBB_I_TKL hubbens adress som TKL når den, när TKL kör i en container (annars
// PROV_HUBB); PROV_BILDER en mapp för skärmbilderna.
//
// Provet: TKL A startas som Åsen, tar Gårdsjö som stationsmodell och väljer sin fjärrkatalog i
// Studio › Inställningar › Fjärrstyrning, alla tågvägar, med en ny version av utsidan. Hubben kör
// Provbanans fasta utsida för Åsen, vars katalog och översikt har Gårdsjös id:n, så att vägarna B
// begär är A:s egna. TKL B startas första gången som Fjärrställverk med driftplatsen asn; båda
// godkänns i Klienter. A lämnar Åsen till B med Lämna till … i Ställverkets rad, och B tar emot
// under Väntar på dig: namnet blir grått och pilarna vid huvudsignalerna röda (FR8, FR32, FR33).
// B trycker 51 och 33: vägen blinkar, och Lägg tågvägen skickar den. A:s eget ställverk låser den
// och B:s fjärrbild ritar spår 3 grönt, bara när A rapporterat (FR11–FR13). B begär 22 till 64, mot
// samma spår: A:s ställverk säger nej med skälet, B visar det och bilden ändras inte (FR14). B
// lägger 22 till 62 och tar bort den med Ta bort. B:s Tåg och klarering visar Åsen (FR17).
//
// Fjärrtågklarerarens Stream Deck på skärmen (#36 del d, SD37), en 15: tangenten för 22 → spår 2
// blinkar efter första trycket, och det andra skickar vägen, som A låser. Sedan tar A tillbaka Åsen
// med Ta tillbaka: namnet blir blått, pilarna försvinner och den låsta vägen ligger kvar (FR7, FR15).
//
// Med PROV_TKL_GRANNE: Norrbys egen TKL, på nivå 0 och godkänd för Norrby, får fliken Fjärr när A
// erbjuder den Åsen, tar emot där och lägger 22 till 62 med samma fjärrbild (FR3). A tar tillbaka.
//
// Delarna (#36 del d, FR50, FR51): A byter till Charlottendal, som har Rangerbangården, och lämnar
// Åsen till B igen. Rangerbangården begär 52 → 3: rutan i A:s Ställverk visar bara och säger varför,
// begäran står under Väntar på dig hos B, och B:s Godkänn lägger vägen i A:s ställverk. Tåg 3795
// anmäls klart att skicka och står i B:s lista Klara att skicka, där B trycker Skickat.
import { chromium } from "playwright-core";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const HUB = (process.env.PROV_HUBB ?? "http://127.0.0.1:8080").replace(/\/+$/, "");
const TKL = (process.env.PROV_TKL_FJARR ?? "http://127.0.0.1:8093").replace(/\/+$/, "");
const STATION = (process.env.PROV_TKL_STATION ?? "http://127.0.0.1:8095").replace(/\/+$/, "");
const NEIGHBOUR = (process.env.PROV_TKL_GRANNE ?? "").replace(/\/+$/, "");
const HUB_FOR_TKL = (process.env.PROV_HUBB_I_TKL ?? HUB).replace(/\/+$/, "");
const PIN = process.env.PROV_TKL_PIN ?? "4711";
const SHOTS = process.env.PROV_BILDER ?? "";
const CHROME = process.env.CHROME_PATH ?? "";
const PLACE = "asn";
const NAME = "Åsen";

class ProvFel extends Error {}

function check(condition, message) {
  if (!condition) throw new ProvFel(message);
}

let shot = 0;
async function screenshot(page, name) {
  if (!SHOTS) return;
  shot += 1;
  await page.screenshot({ path: join(SHOTS, `${String(shot).padStart(2, "0")}-${name}.png`), fullPage: true });
}

/** Provbanan in the hub, as a browser has it: the run and its code for clients over the internet. */
async function provbanan(browser) {
  const context = await browser.newContext();
  const hub = context.request;
  const started = await hub.post(`${HUB}/api/provbanan/start`, { data: { version: 1 } });
  check(started.ok(), `Provbanan startade inte (${started.status()}).`);
  const { code } = await (await hub.get(`${HUB}/api/provbanan/clients`)).json();
  check(/^\d{6}$/.test(code ?? ""), `Provbanan gav ingen kod: ${code}`);
  return { context, hub, code };
}

async function approve(hub, kind, places) {
  for (let i = 0; i < 50; i++) {
    const { clients } = await (await hub.get(`${HUB}/api/provbanan/clients`)).json();
    const found = clients.find((c) => c.kind === kind && c.status === "waiting");
    if (found) {
      const done = await hub.post(`${HUB}/api/provbanan/clients/approve`, { data: { client_id: found.client_id, places } });
      check(done.ok(), `Klienten godkändes inte (${done.status()}).`);
      return found.client_id;
    }
    await new Promise((r) => setTimeout(r, 100));
  }
  throw new ProvFel(`Klienter har ingen ${kind} som väntar.`);
}

// --- Station A: Åsen's own TKL with Gårdsjö, the real station -------------------------------------

/** TKL A: first start as Åsen, Gårdsjö as the station's model, the remote catalogue chosen in
 * Studio › Inställningar › Fjärrstyrning and a new version of the outside, then connected and
 * approved for Åsen. Returns its page and what the test asks of it. */
async function stationA(browser, hub, code) {
  const context = await browser.newContext({ locale: "sv-SE", viewport: { width: 1600, height: 1000 } });
  const page = await context.newPage();
  await page.goto(`${STATION}/`);
  await page.getByText("Första start · tre rutor").waitFor();
  await page.getByLabel("Namn", { exact: true }).fill(NAME);
  await page.getByLabel("Kort namn").fill("asen");
  await page.getByLabel("Välj PIN").fill(PIN);
  await page.getByLabel("Skriv den igen").fill(PIN);
  await page.getByRole("button", { name: "Lås med PIN och starta" }).click();
  await page.getByRole("link", { name: "Studio" }).first().waitFor();
  await page.goto(`${STATION}/studio/sparplan`);
  await page.getByRole("button", { name: "Gårdsjö" }).click();
  // The reference is shown first; used, it takes the station's own name (TKL keeps it
  // with the station), so then the own station's view is waited for.
  await page.getByRole("heading", { name: /Gårdsjö/ }).waitFor();
  await page.getByRole("button", { name: "Använd som min station" }).click();
  await page.locator(".ruta .overrad", { hasText: "Min station" }).waitFor();
  // The catalogue: every train route in and out, kept with the model and the outside's version.
  await page.goto(`${STATION}/studio/installningar/fjarrstyrning`);
  await page.getByRole("heading", { name: "Fjärrkatalogen" }).waitFor();
  const count = await page.locator(".fjarr-vag input[type=checkbox]").count();
  await page.getByRole("group", { name: "Snabbval" }).getByRole("button", { name: "Alla", exact: true }).click();
  await page.getByText(`${count} av ${count} tågvägar i katalogen.`).waitFor();
  await page.getByRole("button", { name: "Spara", exact: true }).click();
  await page.getByRole("status").filter({ hasText: "Sparat" }).waitFor();
  await page.goto(`${STATION}/studio`);
  const version = page.getByRole("button", { name: "Ny version av utsidan" });
  await version.waitFor();
  if (await version.isEnabled()) await version.click();
  await page.waitForFunction(() => !document.querySelector("button.primar:not([disabled])")?.textContent?.includes("Ny version av utsidan"));
  await page.goto(`${STATION}/installningar`);
  await page.getByLabel("Hubbens adress").fill(HUB_FOR_TKL);
  await page.getByLabel("Kod").fill(code);
  await page.getByRole("button", { name: "Anslut", exact: true }).click();
  await page.getByRole("heading", { name: "Väntar på godkännande" }).waitFor();
  await approve(hub, "tkl", [PLACE]);
  await page.goto(`${STATION}/`);
  const bar = page.locator("section.driftform");
  await bar.locator(".driftform-lage", { hasText: "Bemannad" }).waitFor({ timeout: 20_000 });
  const api = (path) => `${STATION}/api/tkl/1${path}`;
  return {
    page,
    count,
    bar,
    /** Lämna till … in Ställverket's row (FR8). */
    offer: async (to) => {
      await page.goto(`${STATION}/`);
      const choose = bar.getByLabel("Lämna till");
      await choose.waitFor({ timeout: 30_000 });
      await choose.selectOption({ label: to });
      await bar.getByRole("button", { name: "Lämna", exact: true }).click();
      await bar.locator(".driftform-lage", { hasText: "Erbjuden till" }).waitFor();
    },
    /** Ta tillbaka, after the question (FR7). */
    takeBack: async () => {
      await page.goto(`${STATION}/`);
      await bar.getByRole("button", { name: "Ta tillbaka", exact: true }).click();
      await bar.getByRole("alertdialog", { name: "Ta tillbaka stationen" }).getByRole("button", { name: "Ja, ta tillbaka" }).click();
      await bar.locator(".driftform-lage", { hasText: "Bemannad" }).waitFor({ timeout: 15_000 });
    },
    state: async () => (await page.request.get(api("/stallverk"))).json(),
    /** Nollställ in A's own interlocking, once it knows the station is manned again. */
    reset: async () => {
      for (let i = 0; i < 50; i++) {
        const done = await (await page.request.post(api("/stallverk/reset"), { data: { confirm: true, trains: true } })).json();
        if (done.accepted) return;
        await page.waitForTimeout(200);
      }
      throw new ProvFel("A:s ställverk nollställdes inte.");
    },
    post: async (path, data) => (await page.request.post(api(path), { data })).json(),
  };
}

// --- TKL B: the remote interlocking ---------------------------------------------------------------

async function firstStartRemote(page) {
  await page.goto(`${TKL}/`);
  await page.getByRole("heading", { level: 1 }).first().waitFor();
  if (await page.getByText("Första start · tre rutor").isVisible()) {
    await page.getByRole("radio", { name: "Fjärrställverk (ingen egen station)" }).click();
    await page.getByLabel("Namn", { exact: true }).fill("Fjärr Väster");
    await page.getByLabel("Driftplatser").fill(PLACE);
    await page.getByLabel("Välj PIN").fill(PIN);
    await page.getByLabel("Skriv den igen").fill(PIN);
    await screenshot(page, "forsta-start-fjarr");
    await page.getByRole("button", { name: "Lås med PIN och starta fjärrställverket" }).click();
  } else if (await page.getByText("TKL är låst. Skriv PIN-koden.").isVisible()) {
    await page.getByLabel("PIN").fill(PIN);
    await page.getByRole("button", { name: "Lås upp" }).click();
  }
  await page.getByRole("link", { name: "Fjärrbild" }).first().waitFor();
}

async function connectRemote(page, code) {
  await page.goto(`${TKL}/installningar`);
  await page.getByLabel("Hubbens adress").fill(HUB_FOR_TKL);
  await page.getByLabel("Kod").fill(code);
  await page.getByRole("button", { name: "Anslut", exact: true }).click();
  await page.getByRole("heading", { name: "Väntar på godkännande" }).waitFor();
}

/** Norrby's own TKL at level 0, connected and approved for its place: the neighbour (FR3). */
async function neighbourTkl(browser, hub, code) {
  const context = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
  const page = await context.newPage();
  await page.goto(`${NEIGHBOUR}/`);
  await page.getByText("Första start · tre rutor").waitFor();
  await page.getByLabel("Namn", { exact: true }).fill("Norrby");
  await page.getByLabel("Kort namn").fill("norrby");
  await page.getByLabel("Välj PIN").fill(PIN);
  await page.getByLabel("Skriv den igen").fill(PIN);
  await page.getByRole("button", { name: "Lås med PIN och starta" }).click();
  await page.getByRole("link", { name: "Studio" }).first().waitFor();
  await page.goto(`${NEIGHBOUR}/installningar`);
  await page.getByLabel("Hubbens adress").fill(HUB_FOR_TKL);
  await page.getByLabel("Kod").fill(code);
  await page.getByRole("button", { name: "Anslut", exact: true }).click();
  await page.getByRole("heading", { name: "Väntar på godkännande" }).waitFor();
  await approve(hub, "tkl", ["nby"]);
  await page.goto(`${NEIGHBOUR}/`);
  await page.getByRole("heading", { name: /Klarering/ }).first().waitFor({ timeout: 15_000 });
  return page;
}

const picture = (page) => page.locator("svg.fjarrbild");
const station = (page) => picture(page).locator(`g.fj-station[data-place="${PLACE}"]`);
/** A station track's state in A's drawing, by the track's id in the outside: the same with the
 * pretend station and with a real one, whatever its overview calls the pieces. */
const trackState = (page, track) => station(page).locator(`line[data-track="${track}"]`).first().getAttribute("data-state");
/** Every piece's state in A's drawing, to see that a no changes nothing. */
async function states(page) {
  return station(page)
    .locator("[data-piece]")
    .evaluateAll((all) => all.map((e) => `${e.getAttribute("data-piece")}=${e.getAttribute("data-state")}`).join(" "));
}
async function waitFor(test, what, page, ms = 15_000) {
  const until = Date.now() + ms;
  while (Date.now() < until) {
    if (await test()) return;
    await page.waitForTimeout(150);
  }
  throw new ProvFel(what);
}

/** Waits until a station's picture says it is remote-controlled or manned. */
const modeIs = (page, mode, what) => waitFor(async () => (await station(page).getAttribute("data-mode")) === mode, what, page);

/** Start and goal in B's picture, then Lägg tågvägen (FR11, FR13). */
async function lay(page, start, goal) {
  await picture(page).getByRole("button", { name: `Start ${start} vid ${NAME}` }).click();
  await picture(page).getByRole("button", { name: `Mål ${goal} vid ${NAME}` }).click();
  await page.getByRole("button", { name: "Lägg tågvägen" }).click();
}

/** Fjärrtågklarerarens Stream Deck on B's screen (#36 del d, SD37): a 15, a route's key pressed
 * once to choose it, blinking, and once more to send it. */
async function remoteDeck(page, label, track) {
  await page.getByRole("button", { name: "Stream Deck", exact: true }).click();
  const deck = page.locator(".sd-panel");
  await deck.getByLabel("Modell").selectOption("15");
  await deck.locator('.sd-deck[data-model="15"]').waitFor();
  const key = deck.locator(`.sd-key[aria-label^="${NAME}: tågväg ${label}"]`);
  await key.waitFor({ timeout: 10_000 });
  await key.click();
  await deck.locator(`.sd-key[aria-label^="${NAME}: tågväg ${label}, vald"] .sd-face[data-blink="ja"]`).waitFor();
  check((await trackState(page, track)) !== "train", "Vägen lades redan vid första trycket.");
  await screenshot(page, "stream-deck-blinkar");
  await key.click();
  await waitFor(async () => (await trackState(page, track)) === "train", `${label} från decket blev inte grön.`, page);
  await deck.locator(`.sd-key[aria-label^="${NAME}: tågväg ${label}, låst"]`).waitFor({ timeout: 10_000 });
  await screenshot(page, "stream-deck-last");
  await deck.getByLabel("Modell").selectOption("xl");
  await deck.locator('.sd-deck[data-model="xl"]').waitFor();
  await deck.locator(`.sd-key[aria-label^="${NAME}: tågväg ${label}, låst"]`).waitFor();
  await screenshot(page, "stream-deck-xl");
  await deck.getByLabel("Modell").selectOption("15");
  await page.getByRole("button", { name: "Stream Deck", exact: true }).click();
}

/** The parts (#36 del d, FR50, FR51): A on Charlottendal with Rangerbangården, handed to B again.
 * The part asks for its route out and announces a train through A's own part operations; B
 * approves in Väntar på dig, and marks the train Skickat in Klara att skicka. */
async function parts(a, page) {
  await a.reset();
  await a.page.goto(`${STATION}/studio/sparplan`);
  await a.page.getByRole("button", { name: "Charlottendal" }).click();
  // The reference is shown first; used, it takes the station's own name (TKL keeps it
  // with the station), so then the own station's view is waited for.
  await a.page.getByRole("heading", { name: /Charlottendal/ }).waitFor();
  await a.page.getByRole("button", { name: "Använd som min station" }).click();
  await a.page.locator(".ruta .overrad", { hasText: "Min station" }).waitFor();
  for (let i = 0; i < 50 && !(await a.state()).parts?.length; i++) await a.page.waitForTimeout(100);
  const [yard] = (await a.state()).parts ?? [];
  check(yard, "Modellen har ingen del.");
  const street = yard.streets.find((s) => s.side === "right" && s.track === "52");
  const out = yard.routes_out.find((r) => r.side === "right" && r.track === "3");
  check(street && out, "Delen har ingen gata till 52 eller väg ut till 3 i höger ände.");
  await a.offer("Fjärr Väster (fjärrställverk)");
  const offer = page.locator(`[data-offer="${PLACE}"]`);
  await offer.waitFor({ timeout: 15_000 });
  await offer.getByRole("button", { name: "Ta emot" }).click();
  await modeIs(page, "remote", "Åsen blev inte fjärrstyrd igen.");
  const part = (path, data) => a.post(`/stallverk/parts/${yard.id}${path}`, data);
  check((await part("/street", { street: street.id })).accepted, "Delen lade inte sin växelgata.");
  const asked = await part("/request", { route_out: out.id });
  check(asked.accepted, `Delen kunde inte begära: ${asked.message}`);
  check((await part("/ready", { number: "3795" })).accepted, "Tåg 3795 anmäldes inte klart att skicka.");
  // A's own box only shows, and says why (TKL100).
  await a.page.goto(`${STATION}/`);
  await a.page.locator(".del-ruta[data-remote] [data-box-remote]", { hasText: "Stationen fjärrstyrs från Fjärr Väster" }).waitFor({ timeout: 15_000 });
  check(await a.page.locator(".del-ruta .del-rad.begaran").getByRole("button", { name: "Godkänn" }).isDisabled(), "A:s ruta svarar fast stationen fjärrstyrs.");
  await screenshot(a.page, "station-rutan-fjarrstyrd");
  // B: the request under Väntar på dig, and the list (FR50, FR51).
  const request = page.locator("[data-part-request]", { hasText: `${yard.name} begär` });
  await request.waitFor({ timeout: 15_000 });
  const listed = page.locator(`[data-ready-place="${PLACE}"] [data-ready="3795"]`);
  await listed.waitFor({ timeout: 15_000 });
  await screenshot(page, "del-begar-och-klara-att-skicka");
  await request.getByRole("button", { name: "Godkänn" }).click();
  await waitFor(async () => (await a.state()).routes.some((r) => r.part === yard.id), "B:s Godkänn lade inte delens väg i A:s ställverk.", page);
  await request.waitFor({ state: "detached", timeout: 15_000 });
  const said = (await a.state()).events.find((e) => /godkände/.test(e.text));
  check(said?.by === "Fjärr Väster", `Händelsen säger inte vem som godkände: ${JSON.stringify(said)}`);
  await listed.getByRole("button", { name: "Tåg 3795 är skickat" }).click();
  await waitFor(async () => !(await a.state()).ready.length, "Skickat tog inte bort 3795 ur A:s lista.", page);
  await listed.waitFor({ state: "detached", timeout: 15_000 });
  await screenshot(page, "del-godkand-och-skickad");
  return yard.name;
}

async function main() {
  if (SHOTS) mkdirSync(SHOTS, { recursive: true });
  const started = Date.now();
  const browser = await chromium.launch({ executablePath: CHROME || undefined, headless: true });
  try {
    const { hub, code } = await provbanan(browser);
    const context = await browser.newContext({ locale: "sv-SE", viewport: { width: 1600, height: 1000 } });
    const page = await context.newPage();
    await firstStartRemote(page);
    await connectRemote(page, code);
    await approve(hub, "remote", [PLACE]);
    const a = await stationA(browser, hub, code);
    await page.goto(`${TKL}/`);
    await station(page).waitFor({ timeout: 20_000 });
    check((await station(page).getAttribute("data-mode")) === "manned", "Åsen är inte bemannad innan den lämnas över.");
    // 3. A offers the station to B from its own Ställverket, and B takes it (FR8).
    await a.offer("Fjärr Väster (fjärrställverk)");
    const left = (await a.bar.textContent()) ?? "";
    check(/\d+ s kvar/.test(left), `A:s rad visar inte tiden kvar: ${left}`);
    const offer = page.locator(`[data-offer="${PLACE}"]`);
    await offer.waitFor({ timeout: 15_000 });
    check(/kvar/.test((await offer.textContent()) ?? ""), "Erbjudandet visar inte tiden kvar.");
    await screenshot(page, "erbjudande");
    await offer.getByRole("button", { name: "Ta emot" }).click();
    await modeIs(page, "remote", "Åsen blev inte fjärrstyrd.");
    await a.bar.locator(".driftform-lage", { hasText: "Fjärrstyrs från Fjärr Väster" }).waitFor({ timeout: 15_000 });
    const signals = await station(page).locator("[data-signal]").count();
    check(signals > 0 && (await station(page).locator('[data-arrow="remote"]').count()) === signals, "Pilarna vid huvudsignalerna är inte röda.");
    check((await station(page).locator(".fj-namn").getAttribute("data-colour")) === "#c4c8cc", "Namnet är inte grått.");
    // 4. B asks for 51 → 33, spår 3; it blinks, is sent, and is green when A has locked it (FR13).
    await picture(page).getByRole("button", { name: `Start 51 vid ${NAME}` }).click();
    await picture(page).getByRole("button", { name: `Mål 33 vid ${NAME}` }).click();
    check((await trackState(page, "3")) === "chosen", "Den valda vägen blinkar inte.");
    await screenshot(page, "vald-blinkar");
    await page.getByRole("button", { name: "Lägg tågvägen" }).click();
    await waitFor(async () => (await trackState(page, "3")) === "train", "51 → spår 3 blev inte grön i fjärrbilden.", page);
    check((await trackState(page, "1")) === "free" && (await trackState(page, "2")) === "free", "Fel spår är gröna.");
    check((await station(page).locator('[data-signal="51"]').getAttribute("data-aspect")) === "proceed", "Signal 51 visar inte kör.");
    const laid = (await a.state()).routes.map((r) => `${r.start}→${r.end}`);
    check(laid.includes("51→33") || laid.some((r) => r.startsWith("51→")), `A:s ställverk har inte vägen från 51: ${laid}`);
    await screenshot(page, "last-gron");
    // 5. Against the same track: A's interlocking says no with its reason; the picture stays.
    const before = await states(page);
    await lay(page, "22", "64");
    const no = page.locator(".fj-rad.nej", { hasText: "22 → 64, spår 3" });
    await no.waitFor({ timeout: 15_000 });
    const why = ((await no.textContent()) ?? "").replace(/^.*vid Åsen\.\s*/, "");
    check(why.length > 3 && why !== "Nej.", `Nejet har inget skäl: ${await no.textContent()}`);
    await page.waitForTimeout(500);
    check((await states(page)) === before, `Bilden ändrades av ett nej: ${before} → ${await states(page)}`);
    await screenshot(page, "nej-med-skal");
    // Ta bort: 22 → 62, spår 2 is laid and taken away again.
    await lay(page, "22", "62");
    await waitFor(async () => (await trackState(page, "2")) === "train", "22 → spår 2 blev inte grön.", page);
    await page.locator(".fj-rad", { hasText: "22 → 62, spår 2" }).getByRole("button", { name: "Ta bort" }).click();
    await waitFor(async () => (await trackState(page, "2")) === "free", "Ta bort löste inte upp 22 → spår 2.", page);
    // FR17: Tåg och klarering for the station B controls.
    await page.getByRole("link", { name: "Tåg och klarering" }).first().click();
    await page.getByRole("navigation", { name: "Stationerna" }).getByRole("button", { name: NAME }).waitFor();
    await page.getByRole("heading", { name: /Klarering/ }).first().waitFor({ timeout: 10_000 });
    await screenshot(page, "tag-och-klarering");
    await page.getByRole("link", { name: "Fjärrbild" }).first().click();
    await station(page).waitFor();
    // SD37: one key on B's screen deck, pressed twice, lays 22 → 62.
    await remoteDeck(page, "22→2", "2");
    // 6. A takes the station back: manned, blue, no arrows; the locked routes stay (FR7, FR15).
    await a.takeBack();
    await modeIs(page, "manned", "Åsen blev inte bemannad igen.");
    check((await station(page).locator("[data-arrow]").count()) === 0, "Pilarna står kvar på en bemannad station.");
    check((await station(page).locator(".fj-namn").getAttribute("data-colour")) === "#4da3ff", "Namnet är inte blått.");
    check((await trackState(page, "3")) === "train", "Den låsta vägen försvann när stationen togs tillbaka.");
    await screenshot(page, "tagen-tillbaka");
    if (NEIGHBOUR) {
      // FR3: Norrby's own TKL controls its neighbour Åsen with the same fjärrbild, under Fjärr.
      // A's own interlocking is reset first, as on the spot, so that the routes are free.
      await a.reset();
      const norrby = await neighbourTkl(browser, hub, code);
      await a.offer("Norrby");
      const tab = norrby.getByRole("link", { name: "Fjärr", exact: true }).first();
      await tab.waitFor({ timeout: 15_000 });
      await tab.click();
      const offered = norrby.locator(`[data-offer="${PLACE}"]`);
      await offered.waitFor({ timeout: 10_000 });
      await offered.getByRole("button", { name: "Ta emot" }).click();
      await modeIs(norrby, "remote", "Åsen blev inte fjärrstyrd från Norrby.");
      await waitFor(async () => (await trackState(norrby, "2")) === "free", "A:s nollställning syns inte hos Norrby.", norrby);
      await lay(norrby, "22", "62");
      await waitFor(async () => (await trackState(norrby, "2")) === "train", "22 → spår 2 blev inte grön hos Norrby.", norrby);
      await screenshot(norrby, "granne-fjarr");
      await a.takeBack();
      await modeIs(norrby, "manned", "Åsen blev inte bemannad igen hos Norrby.");
    }
    // The parts of a remote-controlled station (#36 del d, FR50, FR51).
    const part = await parts(a, page);
    const neighbourDone = NEIGHBOUR ? ", också från grannens TKL" : "";
    console.log(`Fjärrstyrningen fungerar med en riktig station: Åsens katalog har ${a.count} tågvägar; erbjuden, tagen, låst, nekad med skäl, borttagen, lagd från Stream Deck och tagen tillbaka${neighbourDone}.`);
    console.log(`Delarna: ${part} begärde sin väg ut, fjärrställverket godkände och tryckte Skickat, på ${Math.round((Date.now() - started) / 1000)} s.`);
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error instanceof ProvFel ? `Provet gick inte igenom: ${error.message}` : error);
  process.exit(1);
});
