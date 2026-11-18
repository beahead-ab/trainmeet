// Webbläsarprovet för Ställverket på nivå 1–2 (#84 del b), i en riktig Chrome: en hubb med
// Provbanan och en TKL, som i nivå 0:s prov (tests/test_tkl_klarering.py). TKL är Åsen och tar
// referensstationen Gårdsjö som sin egen stationsmodell. Mellanå är en klient på
// stationsprotokollet och skickar tåg 102 hit.
//
//   PROV_HUBB=http://127.0.0.1:8080 PROV_TKL=http://127.0.0.1:8090 CHROME_PATH=/usr/bin/google-chrome \
//     node apps/tkl/e2e/stallverk.mjs
//
// PROV_HUBB är hubbens adress och PROV_TKL TKL:s, båda nystartade; PROV_HUBB_I_TKL hubbens adress
// som TKL når den, när TKL kör i en container (annars PROV_HUBB); PROV_BILDER en mapp för
// skärmbilderna. Provet ger klart i Klarering som på nivå 0, sätter ut 102 på linjen vid Öst 2,
// lägger tågvägen 52 → 62 och växlingsvägen 35 → Spår 32 (ett klick till på 35, ringen blir gul),
// byter till skalen 95, 59, Manöver och Foto och tillbaka utan att ställverket ändras (STV-12,
// STV-18, STV-46), kopplar in Gårdsjös Signalstopp väster och får nej på en väg från 21, som står
// i stopp, och kopplar ur det (STV-04), trycker Kör en gång i Foto och ser tåget rulla (STV-06),
// trycker Kör i 85 tills tågnumret har stegat in på spår 2 och trycker Ankommit. Hubben ska ha
// tåg 102 framme på Åsen. En andra skärm visar bara Tåg · Klarering · Händelser och följer med
// (STV-05). Före anslutningen provas Gårdsjö i Studio › Prova (#85 del c): ett simulerat tåg
// genom varje väg med Kör, Klart, och Ställverket utan noten om att stationen inte är provad.
import { chromium } from "playwright-core";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const HUB = (process.env.PROV_HUBB ?? "http://127.0.0.1:8080").replace(/\/+$/, "");
const TKL = (process.env.PROV_TKL ?? "http://127.0.0.1:8090").replace(/\/+$/, "");
const HUB_FOR_TKL = (process.env.PROV_HUBB_I_TKL ?? HUB).replace(/\/+$/, "");
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

async function approve(hub, kind, place) {
  const { clients } = await (await hub.get(`${HUB}/api/provbanan/clients`)).json();
  const found = clients.find((c) => c.kind === kind && c.status === "waiting");
  check(found, `Klienter har ingen ${kind} som väntar.`);
  const done = await hub.post(`${HUB}/api/provbanan/clients/approve`, { data: { client_id: found.client_id, places: [place] } });
  check(done.ok(), `Klienten godkändes inte (${done.status()}).`);
  return found.client_id;
}

/** Mellanå: a client of the station protocol, approved for its place. */
async function neighbour(hub, code) {
  const made = await hub.post(`${HUB}/api/station/1/connect`, { data: { kind: "tmbox_app", name: "Mellanå", software: "prov", code } });
  check(made.ok(), `Mellanå kom inte in (${made.status()}).`);
  const { client_id } = await made.json();
  await hub.post(`${HUB}/api/provbanan/clients/approve`, { data: { client_id, places: ["mla"] } });
  const { key } = await (await hub.get(`${HUB}/api/station/1/connect/${client_id}`)).json();
  const headers = { Authorization: `Bearer ${key}` };
  const seen = async () => (await hub.get(`${HUB}/api/station/1/places/mla`, { headers })).json();
  const send = async (action, payload) => {
    const context = (await seen()).context;
    const answer = await hub.post(`${HUB}/api/station/1/commands`, {
      headers,
      data: { message_id: `prov-${Date.now()}-${Math.random().toString(36).slice(2)}`, client_id, place: "mla", context, action, payload },
    });
    const reply = await answer.json();
    check(reply.status === "accepted", `Mellanå: ${action} nekades: ${reply.message}`);
    return reply;
  };
  return { seen, send };
}

/** TKL's first start as Åsen, or the PIN when it is already set up. */
async function firstStart(page) {
  await page.goto(`${TKL}/`);
  const heading = page.getByRole("heading", { level: 1 });
  await heading.waitFor();
  if (await page.getByText("Första start · tre rutor").isVisible()) {
    await page.getByLabel("Namn", { exact: true }).fill("Åsen");
    await page.getByLabel("Kort namn").fill("asen");
    await page.getByLabel("Välj PIN").fill(PIN);
    await page.getByLabel("Skriv den igen").fill(PIN);
    await page.getByRole("button", { name: "Lås med PIN och starta" }).click();
  } else if (await page.getByText("TKL är låst. Skriv PIN-koden.").isVisible()) {
    await page.getByLabel("PIN").fill(PIN);
    await page.getByRole("button", { name: "Lås upp" }).click();
  }
  await page.getByRole("link", { name: "Studio" }).first().waitFor();
}

/** Studio › Spårplan: Gårdsjö, a reference station, as the station's own model. */
async function useGardsjo(page) {
  await page.goto(`${TKL}/studio/sparplan`);
  await page.getByRole("button", { name: "Gårdsjö" }).click();
  await page.getByRole("button", { name: "Använd som min station" }).click();
  await page.getByText("Min station", { exact: true }).first().waitFor();
  await page.getByRole("heading", { name: /Gårdsjö/ }).waitFor();
}

/** Studio › Prova (STUDIO-05, STUDIO-27): Ställverket says the station is not tried; Prova runs a
 * train through every route in the background, every one passes, and the station is Klart. A
 * click on a route lights it on the panel. Returns how many routes passed. */
async function prova(page) {
  await page.goto(`${TKL}/`);
  await page.getByText("Stationen är inte provad i Studio › Prova.").waitFor();
  await page.goto(`${TKL}/studio/prova`);
  await page.getByRole("heading", { name: "Prova", exact: true, level: 1 }).waitFor();
  await page.getByRole("button", { name: "Starta Prova" }).click();
  await page.locator(".prova-klart", { hasText: "Klart" }).waitFor({ timeout: 30_000 });
  const summary = (await page.locator(".prova-status").textContent()) ?? "";
  const counted = /(\d+) gick igenom · 0 gick inte · (\d+) vägar/.exec(summary);
  check(counted && counted[1] === counted[2] && Number(counted[1]) > 0, `Prova är inte klart: ${summary}`);
  const first = page.locator(".prova-vag").first();
  await first.click();
  check((await first.getAttribute("aria-pressed")) === "true", "Vägen gick inte att välja.");
  check((await page.locator("svg.panel g.vag-linje polyline").count()) > 0, "Vägen lyser inte på panelen.");
  await screenshot(page, "prova-klart");
  await page.goto(`${TKL}/`);
  await panel(page).waitFor();
  check(!(await page.getByText("Stationen är inte provad").count()), "Ställverket säger att stationen inte är provad fast den är klar.");
  return Number(counted[1]);
}

async function connect(page, code) {
  await page.goto(`${TKL}/installningar`);
  await page.getByLabel("Hubbens adress").fill(HUB_FOR_TKL);
  await page.getByLabel("Kod").fill(code);
  await page.getByRole("button", { name: "Anslut", exact: true }).click();
  await page.getByRole("heading", { name: "Väntar på godkännande" }).waitFor();
}

const panel = (page) => page.locator("svg.stv-panel");
const signal = (page, name) => panel(page).getByRole("button", { name: `Signal ${name}`, exact: true });
const goal = (page, name) => panel(page).getByRole("button", { name: `Mål ${name}`, exact: true });
/** Where a number stands on the panel: its translate, or null when it is not there. */
async function numberAt(page, number, colour) {
  const found = panel(page).locator(`g[data-number="${number}"][data-colour="${colour}"]`);
  if (!(await found.count())) return null;
  return found.first().evaluate((g) => g.style.transform);
}

const errors = [];
const browser = await chromium.launch(CHROME ? { executablePath: CHROME } : {});
try {
  if (SHOTS) mkdirSync(SHOTS, { recursive: true });
  const { hub, code } = await provbanan(browser);
  const context = await browser.newContext({ locale: "sv-SE", viewport: { width: 1600, height: 1100 } });
  const page = await context.newPage();
  page.on("pageerror", (error) => errors.push(String(error)));

  // TKL: första start som Åsen, Gårdsjö som stationsmodell (nivå 2), anslut och bli godkänd.
  await firstStart(page);
  await useGardsjo(page);
  await screenshot(page, "sparplan-gardsjo");
  const tried = await prova(page);
  await connect(page, code);
  await approve(hub, "tkl", "asn");
  await page.goto(`${TKL}/`);
  await panel(page).waitFor();
  await page.getByText("Nivå 2", { exact: true }).waitFor();

  await screenshot(page, "ansluten");

  // En andra skärm: bara Tåg · Klarering · Händelser, valt för den skärmen och sparat i webbläsaren.
  const second = await context.newPage();
  second.on("pageerror", (error) => errors.push(`skärm 2: ${String(error)}`));
  await second.goto(`${TKL}/?skarm=2`);
  await second.getByRole("group", { name: "Skärm 2" }).waitFor();
  await second.getByRole("group", { name: "Skärm 2" }).getByRole("combobox").selectOption("row");
  await second.locator("#kol-handelser").waitFor();
  check(!(await second.locator("svg.stv-panel").count()), "Skärm 2 visar panelen fast den ska visa nederraden.");

  // Mellanå begär klart för 102 hit; Åsen ger klart i Klarering, som på nivå 0; 102 avgår.
  const mellana = await neighbour(hub, code);
  await mellana.send("clearance.request", { call: "t102-mla", section: "s-asn-mla", clearance_id: "prov-102" });
  const request = page.locator(".kort.begaran", { hasText: "102" });
  await request.waitFor();
  await request.getByRole("button", { name: "Ge klart" }).click();
  await request.waitFor({ state: "detached" });
  await mellana.send("train.departed", { call: "t102-mla" });

  // Tåg på väg hit: 102 syns från Hubben. Provbanan har Åsens utfarter kopplade i förväg som v och
  // o, som Gårdsjös modell inte har, så ställverket säger nej med skälet i händelseraden. 102 sätts
  // i stället ut med sitt nummer på linjen vid Öst 2, rött på linjens ruta (STV-54).
  const coming = page.locator(".kort.kommer", { hasText: "102" });
  await coming.waitFor({ timeout: 20_000 });
  await coming.getByRole("button", { name: "Sätt ut vid infarten" }).click();
  await page.locator(".stv-handelser li.nej", { hasText: "finns inte i stationsmodellen" }).waitFor();
  await page.getByLabel("Tågnummer", { exact: true }).fill("102");
  await page.getByLabel("Var", { exact: true }).selectOption({ label: "Linjen vid Öst 2" });
  await page.getByRole("button", { name: "Sätt ut", exact: true }).click();
  await panel(page).locator('g[data-number="102"][data-colour="red"]').waitFor();
  await coming.getByText("står i ställverket").waitFor();
  const onTheLine = await numberAt(page, "102", "red");
  check(await panel(page).locator('g[data-number="102"] text', { hasText: "00102" }).count(), "85 visar inte tågnumret med fem siffror.");
  await screenshot(page, "102-pa-linjen");

  // Tågvägen 52 → 62: startsignalen, målen lyser, målet (STV-01).
  await signal(page, "52").click();
  await panel(page).locator('circle[data-start="52"][data-kind="train"]').waitFor();
  check(await panel(page).locator('circle[data-goal="62"]').count(), "Målet 62 lyser inte.");
  await screenshot(page, "start-52");
  await signal(page, "62").click();
  await page.getByRole("button", { name: /^Tågväg 52 → 62/ }).waitFor();
  check((await panel(page).locator('g[data-signal="52"]').getAttribute("data-aspect")) === "proceed", "52 visar inte kör.");
  // Skärm 2 följer med genom väntan, utan att någon laddar om den.
  await second.locator(".stv-handelser li", { hasText: "Tågväg 52 → 62 lagd" }).waitFor({ timeout: 30_000 });
  await screenshot(second, "skarm-2");
  check(await panel(page).locator('g[data-number="102"][data-colour="green"]').count(), "Inget grönt tågnummer i vägens sista sektion.");

  // Växlingsvägen 35 → Spår 32: ett klick till på 35 gör den till växlingsväg, ringen gul (STV-24).
  await signal(page, "35").click();
  await panel(page).locator('circle[data-start="35"][data-kind="train"]').waitFor();
  await signal(page, "35").click();
  await panel(page).locator('circle[data-start="35"][data-kind="shunting"]').waitFor();
  await screenshot(page, "vaxlingsvag-35");
  await goal(page, "Spår 32").click();
  await page.getByRole("button", { name: /^Växlingsväg 35 → Spår 32/ }).waitFor();
  check(await panel(page).locator('polyline[data-state="shunting"]').count(), "Växlingsvägen är inte gul på panelen.");
  await screenshot(page, "tvaa-vagar");

  // Skalen 95, 59, Manöver och Foto och tillbaka till 85 (STV-12): ett skalbyte skickar inga
  // order (STV-18). Manöver har symbolerna ur 85 tills ägaren väljer andra (STV-46).
  const revision = async () => (await (await page.request.get(`${TKL}/api/tkl/1/stallverk`)).json()).revision;
  const skins = [["95", "95"], ["59", "59"], ["Manöver", "manover"], ["Foto", "foto"], ["85", "85"]];
  const before = await revision();
  for (const [name, skin] of skins) {
    await page.getByRole("group", { name: "Skal" }).getByRole("button", { name, exact: true }).click();
    await page.locator(`svg.stv-panel.skal-${skin}`).waitFor();
    await screenshot(page, `skal-${skin}`);
  }
  check((await revision()) === before, "Ett skalbyte ändrade ställverket.");

  // Signalstopp väster, Gårdsjös egen panelfunktion (STV-04): 21 står i stopp, och en väg därifrån nekas.
  const stopWest = page.getByRole("button", { name: /^Signalstopp väster/ });
  await stopWest.click();
  await page.locator(".stv-svar", { hasText: "Signalstopp väster kopplades in" }).waitFor();
  check(await panel(page).locator('g[data-signal="21"][data-blocked="ja"]').count(), "21 visar inte spärrad i stopp.");
  await signal(page, "21").click();
  await panel(page).locator('circle[data-start="21"]').waitFor();
  await signal(page, "31").click();
  await page.locator(".stv-svar.nej", { hasText: "Signalen 21 är i signalstopp (Signalstopp väster)" }).waitFor();
  await screenshot(page, "signalstopp-vaster");
  await stopWest.click();
  await page.locator(".stv-svar", { hasText: "Signalstopp väster kopplades ur" }).waitFor();
  check(!(await panel(page).locator('g[data-signal="21"][data-blocked="ja"]').count()), "21 är spärrad fast signalstoppet är urkopplat.");

  // Foto: tåget står på linjen vid Öst 2, och Kör rullar det in på vägen på ungefär en sekund
  // (STV-06). Sedan tillbaka till 85.
  const skin = (name) => page.getByRole("group", { name: "Skal" }).getByRole("button", { name, exact: true });
  await skin("Foto").click();
  const train = page.locator('svg.stv-panel.skal-foto g[data-train="102"]');
  await train.waitFor();
  const where = () => train.evaluate((g) => `${g.dataset.x},${g.dataset.y}`);
  const onTheLineInFoto = await where();
  await page.getByRole("button", { name: /^Tågväg 52 → 62/ }).click();
  const sayBefore = await page.locator(".stv-svar").textContent().catch(() => "");
  await page.getByRole("button", { name: "Kör", exact: true }).click();
  await page.waitForFunction((was) => (document.querySelector(".stv-svar")?.textContent ?? "") !== was, sayBefore);
  await page.waitForFunction(() => !document.querySelector('svg.stv-panel.skal-foto g[data-rolling="ja"]'), null, { timeout: 5000 });
  const rolledTo = await where();
  check(rolledTo !== onTheLineInFoto, `Tåget rullade inte i Foto: ${onTheLineInFoto} → ${rolledTo}.`);
  await screenshot(page, "foto-kor");
  await skin("85").click();
  await page.locator("svg.stv-panel.skal-85").waitFor();

  // Kör: tågnumret stegar från fält till fält längs vägen, och det syns (STV-06).
  const seen = [onTheLine, await numberAt(page, "102", "red")];
  check(seen[1] && seen[1] !== onTheLine, "Tågnumret flyttade sig inte vid Kör i Foto.");
  for (let i = 0; i < 12; i++) {
    const before = await page.locator(".stv-svar").textContent().catch(() => "");
    await page.getByRole("button", { name: "Kör", exact: true }).click();
    await page.waitForFunction((was) => (document.querySelector(".stv-svar")?.textContent ?? "") !== was, before);
    const said = (await page.locator(".stv-svar").textContent()) ?? "";
    if (said.includes("står vid målet")) break;
    check(!said.startsWith("Nej"), `Kör nekades: ${said}`);
    await page.waitForTimeout(700);
    const at = await numberAt(page, "102", "red");
    check(at && at !== seen[seen.length - 1], `Tågnumret flyttade sig inte vid Kör ${i + 1}.`);
    seen.push(at);
    await screenshot(page, `kor-${i + 1}`);
  }
  check(seen.length >= 4, `Tågnumret stegade bara ${seen.length - 1} gånger.`);
  check(!(await panel(page).locator('g[data-number="102"][data-colour="green"]').count()), "Det gröna numret står kvar när tåget är framme.");
  check(!(await panel(page).locator('text[data-track-name="2"]').count()), "Spårnamnet 2 syns under tågnumret (STV-57).");

  // Ankommit: vägen löses ut och ankomsten går till Hubben (STV-16).
  await page.getByRole("button", { name: "Ankommit", exact: true }).click();
  await page.locator(".stv-svar", { hasText: "har kommit fram" }).waitFor();
  await page.locator(".stv-handelser li", { hasText: "Ankomsten för tåg 102" }).waitFor();
  await screenshot(page, "ankommit");
  const view = await (await page.request.get(`${TKL}/api/tkl/1/places/asn`)).json();
  const call = view.snapshot.calls.find((c) => c.call === "t102-asn");
  check(call?.arrival_state === "arrived", `Hubben har inte 102 framme på Åsen: ${JSON.stringify(call)}`);
  check(!(await mellana.seen()).have_left.some((t) => t.train_number === "102"), "Mellanå ser fortfarande 102 på linjen.");
  await second.reload();
  await second.locator("#kol-handelser").waitFor();
  check(!(await second.locator("svg.stv-panel").count()), "Skärm 2 glömde sitt val.");
  await page.reload();
  await panel(page).waitFor();
  check(!errors.length, `Fel i sidan: ${errors.join("; ")}`);
  console.log(`Prova i TKL: ${tried} vägar gick igenom, Klart.`);
  console.log(`Ställverket i TKL: 102 rullade i Foto från ${onTheLineInFoto} till ${rolledTo} mm, stegade ${seen.length - 1} gånger och kom fram till spår ${call.track ?? "?"} på Åsen.`);
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
