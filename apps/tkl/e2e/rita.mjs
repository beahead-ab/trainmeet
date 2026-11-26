// Webbläsarprovet för Rita i Studio (#85 del a), i en riktig Chrome mot en TKL utan hubb. Första
// start som Ritby, sedan ritas en liten station från ingenting: linjen från utfart A till utfart B,
// växel 1 till spår 2 med en stoppbock, växel 2 till ett stickspår med en stoppbock, infarterna
// A1 och B1 och utfarterna 1V och 1Ö på spår 1. Två växlar och två linjeutfarter ger sex spårändar
// mot en stoppbock: varje växel har tre ben, så antalet ändar är jämnt, och provet har därför två
// stoppbockar. Provet ser att de röda punkterna försvinner när ändarna får stoppbock och utfart,
// att motorn räknar fram vägarna, tar ritningen i bruk och lägger tågvägen A1 → 1Ö i Ställverket.
// Stickspåret får spårspärren 3 (TKL129, trainmeet #37): tågvägen B1 → 1V går rakt förbi växel 2,
// och spärren läggs på och blir gul som sidoskydd för den; när vägen är utlöst släpps den.
// Sist delas stationen i Studio › Dela stationen (#87 del b): spår 2 blir delen Lastplatsen med
// växel 1 som gränsväxel och en växelgata till spår 2. Använd väntar med 409 medan tågvägen
// ligger, och går igenom när den är utlöst. På delens skärm /del/lastplatsen läggs gatan, och
// växel 1 ligger i minus.
//
//   PROV_TKL=http://127.0.0.1:8090 CHROME_PATH=/usr/bin/google-chrome node apps/tkl/e2e/rita.mjs
//
// PROV_TKL är en nystartad TKL:s adress; PROV_BILDER en mapp för skärmbilderna.
import { chromium } from "playwright-core";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const TKL = (process.env.PROV_TKL ?? "http://127.0.0.1:8090").replace(/\/+$/, "");
const PIN = process.env.PROV_TKL_PIN ?? "4711";
const SHOTS = process.env.PROV_BILDER ?? "";
const CHROME = process.env.CHROME_PATH ?? "";

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

/** TKL's first start as Ritby, or the PIN when it is already set up. */
async function firstStart(page) {
  await page.goto(`${TKL}/`);
  await page.getByRole("heading", { level: 1 }).waitFor();
  if (await page.getByText("Första start · tre rutor").isVisible()) {
    await page.getByLabel("Namn", { exact: true }).fill("Ritby");
    await page.getByLabel("Kort namn").fill("rtb");
    await page.getByLabel("Välj PIN").fill(PIN);
    await page.getByLabel("Skriv den igen").fill(PIN);
    await page.getByRole("button", { name: "Lås med PIN och starta" }).click();
  } else if (await page.getByText("TKL är låst. Skriv PIN-koden.").isVisible()) {
    await page.getByLabel("PIN").fill(PIN);
    await page.getByRole("button", { name: "Lås upp" }).click();
  }
  await page.getByRole("link", { name: "Studio" }).first().waitFor();
}

const grid = (page) => page.locator("svg.rita-rutnat");

/** A grid point's place on the screen, read from the drawing's own scale. */
async function at(page, column, row) {
  return grid(page).evaluate(
    (svg, [c, r]) => {
      const p = new DOMPoint(c * Number(svg.dataset.dx), r * Number(svg.dataset.dy)).matrixTransform(svg.getScreenCTM());
      return { x: p.x, y: p.y };
    },
    [column, row],
  );
}

async function tool(page, name) {
  await page.getByRole("toolbar", { name: "Verktyg" }).getByRole("button", { name, exact: true }).click();
}

async function click(page, column, row) {
  const p = await at(page, column, row);
  await page.mouse.click(p.x, p.y);
}

async function drawTrack(page, from, to) {
  await tool(page, "Spår");
  const a = await at(page, ...from);
  const b = await at(page, ...to);
  await page.mouse.move(a.x, a.y);
  await page.mouse.down();
  await page.mouse.move(b.x, b.y, { steps: 6 });
  await page.mouse.up();
}

async function signal(page, column, row, facing, name) {
  await tool(page, "Signal");
  await page.getByRole("button", { name: facing === "east" ? "→ österut" : "← västerut" }).click();
  await click(page, column, row);
  const field = page.getByLabel("Namn", { exact: true });
  await field.waitFor();
  await field.fill(name);
  await field.press("Enter");
  await page.locator(`g[data-signal="${name}"]`).waitFor();
}

const loose = (page) => grid(page).locator('circle[data-loose="ja"]').count();

/** Studio › Dela stationen: a part on track 2, its border switch, a street, the checks and
 * Använd, which waits while the train route is set; then the part's own screen lays the street. */
async function dela(page) {
  const plan = await (await page.request.get(`${TKL}/api/tkl/1/studio/model`)).json();
  const below = plan.panel.lines.filter((l) => l.cells.some(([, y]) => y > 4.5)).map((l) => l.piece);
  check(below.length >= 1, "Spår 2 saknas på panelen.");
  await page.goto(`${TKL}/studio/dela`);
  await page.getByRole("heading", { name: "Dela stationen", exact: true }).waitFor();
  await page.getByRole("button", { name: "+ Ny del" }).click();
  await page.getByLabel("Delens namn").fill("Lastplatsen");
  check((await page.getByLabel("Delens id").inputValue()) === "lastplatsen", "Id:t följer inte namnet.");
  const svg = page.locator("svg.dela-svg");
  // The area is clicked section by section: a click takes the whole section in.
  for (const piece of below) {
    const line = svg.locator(`polyline[data-piece="${piece}"]`);
    if ((await line.getAttribute("data-area")) !== "ja") await line.click({ force: true });
    await svg.locator(`polyline[data-piece="${piece}"][data-area="ja"]`).waitFor({ state: "attached" });
  }
  const checks = page.getByRole("region", { name: "Kontroller" });
  await checks.getByText("växel 1 står vid gränsen", { exact: false }).waitFor();
  await page.getByRole("navigation", { name: "Verktyg" }).getByRole("button", { name: "Gränsväxlar", exact: true }).click();
  await svg.getByRole("button", { name: "Växel 1", exact: true }).click();
  await page.locator('tr[data-border-row="1"]').waitFor();
  check((await page.getByLabel("Läge mot delen för 1").inputValue()) === "-", "Gränsväxeln 1 ligger inte mot delen i minus.");
  await page.getByRole("group", { name: "Ände" }).getByRole("button", { name: "Vänster" }).click();
  await page.locator('[data-offer-street="2"]').click();
  await page.locator('li[data-street="V2"]').waitFor();
  await checks.getByText("Inga problem", { exact: false }).waitFor();
  await page.getByText("Inga problem: delarna kan användas.").waitFor();
  await screenshot(page, "dela-stationen");
  // Använd medan tågvägen B1 → 1V ligger: 409, och utkastet står kvar.
  await page.getByRole("button", { name: "Använd", exact: true }).click();
  await page.locator(".fel, .notis", { hasText: "Ställverket har lagda vägar" }).waitFor();
  await page.getByText("Utkast, sparat på datorn", { exact: true }).waitFor();
  const state = await (await page.request.get(`${TKL}/api/tkl/1/stallverk`)).json();
  for (const route of state.routes) {
    const done = await page.request.post(`${TKL}/api/tkl/1/stallverk/release`, { data: { route: route.id } });
    check(done.ok() && (await done.json()).accepted, `Tågvägen ${route.id} löstes inte ut.`);
  }
  // Utlöst släpper vägen sidoskyddet: spårspärren 3 ligger kvar på men är inte längre låst.
  const released = (await (await page.request.get(`${TKL}/api/tkl/1/stallverk`)).json()).switches["3"];
  check(released?.position === "-" && !released.protection && !released.routes?.length, `Spårspärren 3 är låst fast vägen är utlöst: ${JSON.stringify(released)}`);
  await page.getByRole("button", { name: "Använd", exact: true }).click();
  await page.getByText("Används i Ställverket", { exact: true }).waitFor();
  await screenshot(page, "dela-anvand");
  // Delens skärm: gatan till 2 lägger växel 1 i minus.
  await page.goto(`${TKL}/del/lastplatsen`);
  await page.getByRole("heading", { name: "Lastplatsen", exact: true }).waitFor();
  await page.locator('[data-street="V2"]').click();
  await page.locator(".stv-svar", { hasText: "V 2" }).waitFor();
  const after = await (await page.request.get(`${TKL}/api/tkl/1/stallverk`)).json();
  check(after.switches["1"]?.position === "-", `Gatan lade inte växel 1 i minus: ${JSON.stringify(after.switches["1"])}`);
  await page.locator('[data-street="V2"].ligger').waitFor();
  await screenshot(page, "del-gatan");
}

const errors = [];
const started = Date.now();
const browser = await chromium.launch(CHROME ? { executablePath: CHROME } : {});
try {
  if (SHOTS) mkdirSync(SHOTS, { recursive: true });
  const context = await browser.newContext({ locale: "sv-SE", viewport: { width: 1600, height: 1100 } });
  const page = await context.newPage();
  page.on("pageerror", (error) => errors.push(String(error)));

  // 1. Första start, och Studio › Rita med de fyra vägarna in (STUDIO-01). Utan TrainMeet CAD är
  //    Ladda upp ritning grå med skälet, och Rita fungerar ändå (CAD6).
  await firstStart(page);
  await page.goto(`${TKL}/studio/rita`);
  await page.getByRole("heading", { name: "Rita", exact: true }).waitFor();
  check(await page.getByRole("button", { name: "Ladda upp ritning", exact: true }).isDisabled(), "Ladda upp ritning går att välja utan CAD.");
  await page.locator("p.ladda-gra").waitFor();
  await page.getByText("Ny ritning", { exact: true }).waitFor();

  // 2. Linjen från A till B: två röda punkter, en i var ände, tills utfarterna sätts (RS7).
  await drawTrack(page, [2, 4], [30, 4]);
  await page.waitForFunction(() => document.querySelectorAll('svg.rita-rutnat circle[data-loose="ja"]').length === 2);
  await screenshot(page, "linjen-roda-punkter");
  await tool(page, "Linjeutfart");
  await click(page, 2, 4);
  await click(page, 30, 4);
  check((await loose(page)) === 0, "Utfarterna tog inte bort de röda punkterna.");

  // Växel 1 med avvikande ben ↘ till spår 2, växel 2 med ↗ till ett stickspår.
  await tool(page, "Växel");
  await page.getByRole("button", { name: "Avvikande ↘" }).click();
  await click(page, 8, 4);
  await page.getByRole("button", { name: "Avvikande ↗" }).click();
  await click(page, 24, 4);
  await drawTrack(page, [11, 7], [20, 7]);
  check((await loose(page)) === 2, `Två ändar ska vara röda, är ${await loose(page)}.`);
  await screenshot(page, "vaxlarna");
  await tool(page, "Stoppbock");
  await click(page, 20, 7);
  await click(page, 27, 1);
  check((await loose(page)) === 0, "Stoppbockarna tog inte bort de röda punkterna.");
  // Spårspärren 3 på stickspåret från växel 2, mellan växeln och stoppbocken (TKL129).
  await tool(page, "Spårspärr");
  await click(page, 26, 2);
  await grid(page).locator('g[data-derailer="3"]').waitFor();
  check((await loose(page)) === 0, "Spårspärren gav röda punkter.");

  // Fyra signaler: infarterna A1 och B1, utfarterna 1V och 1Ö på spår 1.
  await signal(page, 5, 4, "east", "A1");
  await signal(page, 27, 4, "west", "B1");
  await signal(page, 10, 4, "west", "1V");
  await signal(page, 22, 4, "east", "1Ö");

  // Stationsspår 1 och 2.
  await tool(page, "Markera");
  for (const row of [4, 7]) {
    await click(page, 16, row);
    await page.getByRole("button", { name: "Gör till stationsspår" }).click();
  }
  await grid(page).locator("g.sparbeteckning", { hasText: "2" }).waitFor();

  // 3. Vägarna räknas fram ur ritningen (STUDIO-16) och lyser på ritningen vid ett klick.
  const routes = page.getByRole("region", { name: "Vägar" });
  await routes.getByRole("button", { name: "A1 → 1Ö" }).waitFor({ timeout: 15_000 });
  for (const name of ["A1 → Stoppbock 1", "B1 → 1V", "1Ö → Stoppbock 2"]) {
    check(await routes.getByRole("button", { name }).count(), `Vägen ${name} saknas.`);
  }
  await routes.getByRole("button", { name: "A1 → 1Ö" }).click();
  check((await grid(page).locator("polyline[data-lit]").count()) >= 3, "Tågvägen A1 → 1Ö lyser inte på ritningen.");
  await page.getByText("Inga problem: ritningen kan användas.").waitFor();
  await page.getByText("Utkast, sparat på datorn", { exact: true }).waitFor();
  await screenshot(page, "ritad-station");

  // 4. Använd ritningen: den blir stationens modell, och Ställverket kör den.
  await page.getByRole("button", { name: "Använd ritningen" }).click();
  await page.getByText("Används i Ställverket", { exact: true }).waitFor();
  await screenshot(page, "anvand");

  // 5. Tågvägen A1 → 1Ö i Ställverket.
  await page.goto(`${TKL}/`);
  const panel = page.locator("svg.stv-panel");
  await panel.waitFor();
  await page.getByText("Nivå 2", { exact: true }).waitFor();
  await panel.getByRole("button", { name: "Signal A1", exact: true }).click();
  await panel.locator('circle[data-start="A1"]').waitFor();
  await panel.getByRole("button", { name: "Signal 1Ö", exact: true }).click();
  await page.getByRole("button", { name: /^Tågväg A1 → 1Ö/ }).waitFor();
  check((await panel.locator('g[data-signal="A1"]').getAttribute("data-aspect")) === "proceed", "A1 visar inte kör.");
  await screenshot(page, "stallverket-tagvag");

  // 5b. Sidoskyddet (TKL129, STV-20): tågvägen B1 → 1V går rakt förbi växel 2, så spårspärren 3 på
  //     stickspåret läggs på och låses som skydd, gul på panelen. Först löses A1 → 1Ö ut, som korsar.
  const derailer = panel.locator('g[data-derailer="3"]');
  await derailer.waitFor();
  check((await derailer.getAttribute("data-protection")) === null, "Spårspärren 3 är gul fast ingen väg behöver den.");
  const laid = await (await page.request.get(`${TKL}/api/tkl/1/stallverk`)).json();
  for (const route of laid.routes) {
    const done = await page.request.post(`${TKL}/api/tkl/1/stallverk/release`, { data: { route: route.id } });
    check(done.ok() && (await done.json()).accepted, `Tågvägen ${route.id} löstes inte ut.`);
  }
  await page.getByRole("button", { name: /^Tågväg A1 → 1Ö/ }).waitFor({ state: "detached" });
  await panel.getByRole("button", { name: "Signal B1", exact: true }).click();
  await panel.locator('circle[data-start="B1"]').waitFor();
  await panel.getByRole("button", { name: "Signal 1V", exact: true }).click();
  await page.getByRole("button", { name: /^Tågväg B1 → 1V/ }).waitFor();
  await panel.locator('g[data-derailer="3"][data-protection="3"][data-position="-"]').waitFor();
  const guarded = await (await page.request.get(`${TKL}/api/tkl/1/stallverk`)).json();
  check(guarded.switches["3"]?.position === "-" && guarded.switches["3"]?.protection === true, `Spårspärren 3 ligger inte på som skydd: ${JSON.stringify(guarded.switches["3"])}`);
  await page.locator(".stv-svar", { hasText: /Tågväg B1 → 1V lagd: 2 \+, 3 [−-]/ }).waitFor();
  const title = await panel.getByRole("button", { name: "Spårspärr 3", exact: true }).locator("title").textContent();
  check(/på/.test(title ?? "") && /skydd/i.test(title ?? ""), `Spårspärren 3 säger inte att den ligger på som skydd: ${title}`);
  check((await panel.locator('g[data-signal="B1"]').getAttribute("data-aspect")) === "proceed", "B1 visar inte kör.");
  await screenshot(page, "stallverket-sparsparr");

  // 6. Dela stationen (#87 del b): spår 2 och benet dit från växel 1 blir delen Lastplatsen.
  await dela(page);
  check(!errors.length, `Fel i sidan: ${errors.join("; ")}`);
  console.log(`Rita i TKL: stationen ritades, togs i bruk och tågvägen A1 → 1Ö lades i Ställverket på ${Math.round((Date.now() - started) / 1000)} s.`);
  console.log("Sidoskyddet: tågvägen B1 → 1V lade spårspärren 3 på stickspåret på och låste den gul som skydd, och släppte den när vägen löstes ut.");
  console.log("Dela stationen: Lastplatsen fick spår 2, gränsväxeln 1 och gatan till 2; Använd väntade med 409 medan tågvägen låg, och gatan lades på /del/lastplatsen.");
} catch (error) {
  if (error instanceof ProvFel) {
    console.error(`Provet misslyckades: ${error.message}`);
  } else {
    console.error(error);
  }
  process.exitCode = 1;
} finally {
  await browser.close();
}
