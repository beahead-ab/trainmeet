// Webbläsarprovet för Lägg till flera (#52 del d, CAT-154): den riktiga kön och det riktiga
// godkännandet i webbappen, mot Catalog med en låtsad TrainMeet ID och en låtsad AI
// (catalog/prov_webblasare.py). Inget anropar en AI-leverantör på riktigt.
//
//   CHROME_PATH=/opt/pw-browsers/chromium node apps/catalog/e2e/omgang.mjs
//
// PROV_ADRESS är Catalogs adress (http://127.0.0.1:8090), och PROV_BILDER en mapp för
// skärmbilderna. Catalog ska ha en tom databas (prov_webblasare.py --ny).
//
// Först Lägg till med foto en gång, som Provkonto B: samtycket, förslaget, Spara, och fordonet har
// AI:n som källa till det som sparades som det föreslogs (CAT-64, CAT-136). Sedan Lägg till flera
// som Provkonto A, som har tokens för tre foton: fyra foton i en omgång, kön läser tre och det
// fjärde blir att fylla i för hand med ett besked (CAT-147, CAT-152). Godkänn alla stoppas av det
// tomma fotot, som pekas ut (CAT-150); det fylls i, alla fyra godkänns och står bland fordonen
// med sina bilder.
import { chromium } from "playwright-core";
import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { deflateSync } from "node:zlib";

const BASE = (process.env.PROV_ADRESS ?? "http://127.0.0.1:8090").replace(/\/+$/, "");
const SHOTS = process.env.PROV_BILDER ?? "";
const CHROME = process.env.CHROME_PATH ?? "";

// --- Fotona: PNG-bilder i färgerna som den låtsade AI:n känner igen ------------------------------

const CRC = Array.from({ length: 256 }, (_, n) => {
  let c = n;
  for (let k = 0; k < 8; k += 1) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
  return c >>> 0;
});

function crc32(data) {
  let c = 0xffffffff;
  for (const byte of data) c = CRC[(c ^ byte) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

function chunk(type, data) {
  const head = Buffer.alloc(4);
  head.writeUInt32BE(data.length);
  const body = Buffer.concat([Buffer.from(type, "latin1"), data]);
  const sum = Buffer.alloc(4);
  sum.writeUInt32BE(crc32(body));
  return Buffer.concat([head, body, sum]);
}

/** A 360×240 photo of one colour, with dark wheels under it. The note makes each run's files new,
 * so that the same file is never already a draft (CAT-149). */
function photo([r, g, b], note) {
  const width = 360;
  const height = 240;
  const row = width * 3 + 1;
  const raw = Buffer.alloc(row * height);
  for (let y = 0; y < height; y += 1) {
    const wheels = y > height * 0.82;
    for (let x = 0; x < width; x += 1) {
      const at = y * row + 1 + x * 3;
      raw[at] = wheels ? 40 : r;
      raw[at + 1] = wheels ? 40 : g;
      raw[at + 2] = wheels ? 40 : b;
    }
  }
  const header = Buffer.alloc(13);
  header.writeUInt32BE(width, 0);
  header.writeUInt32BE(height, 4);
  header.set([8, 2, 0, 0, 0], 8);
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk("IHDR", header),
    chunk("tEXt", Buffer.from(`Comment\0${note}`, "latin1")),
    chunk("IDAT", deflateSync(raw)),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

const RUN = `webblasarprovet ${Date.now()}`;
const file = (name, colour) => ({ name, mimeType: "image/png", buffer: photo(colour, RUN) });

// --- Kontrollerna -------------------------------------------------------------------------------

class ProvFel extends Error {}

function check(condition, message) {
  if (!condition) throw new ProvFel(message);
}

let shot = 0;
async function screenshot(page, name) {
  if (!SHOTS) return;
  shot += 1;
  // From the top, so that the sticky header stays where it belongs in the full page.
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: join(SHOTS, `${String(shot).padStart(2, "0")}-${name}.png`), fullPage: true });
}

/** Catalog's answer to the browser itself, with its cookie. */
const fromCatalog = (page, path) => page.evaluate(async (address) => (await fetch(address)).json(), path);

const heading = (page, name) => page.getByRole("heading", { name, level: 1, exact: true }).waitFor();

async function logIn(page, name) {
  await page.goto(`${BASE}/logga-in`);
  await page.getByRole("button", { name, exact: true }).click();
  await page.waitForURL(`${BASE}/fordon`);
  // Opened again, as when one comes back: the session has the balance and where to buy tokens.
  await page.goto(`${BASE}/fordon`);
  await heading(page, "Fordon");
}

/** Every thumbnail on the page has come, from Catalog's own signed addresses (CAT-130). */
async function picturesShown(page, selector, count) {
  await page.waitForFunction(
    ([css, n]) => {
      const found = [...document.querySelectorAll(css)];
      return found.length === n && found.every((image) => image.complete && image.naturalWidth > 0);
    },
    [selector, count],
  );
}

async function singlePhoto(page) {
  await logIn(page, "Provkonto B");
  await page.getByRole("link", { name: "Lägg till med foto", exact: true }).click();
  await heading(page, "Fota fordonet");
  await page.locator('input[type="file"]').setInputFiles(file("rc4.png", [130, 60, 160]));
  await page.getByRole("button", { name: "Läs av 1 bild", exact: true }).click();
  // The first time: what is sent and to whom (CAT-142).
  const dialog = page.getByRole("dialog", { name: "Innan AI:n läser av" });
  await dialog.waitFor();
  await screenshot(page, "foto-samtycke");
  await dialog.getByRole("button", { name: "Ja, läs av", exact: true }).click();
  await heading(page, "Stämmer det här?");
  check((await page.getByLabel("Littera", { exact: true }).inputValue()) === "Rc4", "AI:ns littera står inte i formuläret.");
  check((await page.getByLabel("Nummer", { exact: true }).inputValue()) === "1145", "AI:ns nummer står inte i formuläret.");
  check((await page.locator(".cat-formular .cat-pill-ai").count()) === 4, "Förslagen är inte märkta som AI:ns.");
  await screenshot(page, "foto-forslag");
  await page.getByRole("button", { name: "Spara", exact: true }).click();
  await heading(page, "Var bor den?");
  await page.getByText("Fotona är sparade som fordonets bilder.").waitFor();
  await page.getByRole("button", { name: "Klar", exact: true }).click();
  await heading(page, "Rc4 1145 är sparat");
  // Spara sent the reading's id: what was kept as suggested has the AI as its source (CAT-64).
  const list = await fromCatalog(page, "/api/catalog/1/vehicles");
  check(list.total === 1, `Provkonto B har ${list.total} fordon, inte 1.`);
  const [saved] = list.vehicles;
  const sources = JSON.stringify(saved.field_sources);
  check(sources === JSON.stringify({ kind: "ai", litt: "ai", number: "ai", operator: "ai" }), `Källorna är ${sources}.`);
  check(saved.picture !== null, "Fotot blev inte fordonets bild.");
  await screenshot(page, "foto-sparat");
  console.log("Lägg till med foto: samtycket, förslaget, Spara, och AI:n som källa.");
}

async function batch(page) {
  await logIn(page, "Provkonto A");
  // 1–2. Four photos in a batch, with tokens for three (CAT-147, CAT-19).
  await page.getByRole("link", { name: "Lägg till flera", exact: true }).click();
  await heading(page, "Många foton på en gång");
  await page.locator('input[type="file"]').setInputFiles([
    file("IMG_4410.png", [200, 40, 40]),
    file("IMG_4411.png", [40, 150, 60]),
    file("IMG_4412.png", [40, 80, 200]),
    file("IMG_4413.png", [220, 190, 40]),
  ]);
  const cost = page.locator(".cat-sidokolumn");
  for (const said of ["4 × 12 tokens", "48 tokens", "Saldo: 36 tokens · Provkonto", "Saldot räcker inte för den här avläsningen."]) {
    await cost.getByText(said, { exact: true }).waitFor();
  }
  await screenshot(page, "omgang-valda");
  await page.getByRole("button", { name: "Läs av 4 foton", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Innan AI:n läser av" });
  await dialog.waitFor();
  await dialog.getByRole("button", { name: "Ja, läs av", exact: true }).click();
  await page.waitForURL(/\/fordon\/omgangar\/[0-9a-f-]{36}$/);

  // 3. The queue reads one at a time, in turn (CAT-147); the page follows it.
  await page.waitForFunction(() => document.querySelectorAll(".cat-omgangskort").length === 4 && !document.querySelector(".cat-pill-kort-waiting, .cat-pill-kort-reading"), null, {
    timeout: 60_000,
  });

  // 4. Three with suggestions, and the fourth to fill in by hand, with the message (CAT-152).
  const rows = page.locator(".cat-omgangskort");
  const names = await rows.locator("b").allInnerTexts();
  check(JSON.stringify(names) === JSON.stringify(["Gbs 3087", "Hbis 2253", "Sgns 1209", "Inget ifyllt än"]), `Utkasten är ${names.join(", ")}.`);
  for (const index of [0, 1, 2]) {
    const marked = await rows.nth(index).locator(".cat-aitext").first().innerText();
    check(marked.startsWith("AI-förslag") && marked.includes(`Littera ${names[index].split(" ")[0]}`), `Foto ${index + 1} har inga förslag: ${marked}`);
  }
  check((await rows.nth(3).locator(".cat-pill-ai").count()) === 0, "Det fjärde fotot har förslag.");
  const statuses = await rows.locator(".cat-pill[class*='cat-pill-kort-']").allInnerTexts();
  check(JSON.stringify(statuses) === JSON.stringify(["Klar", "Att kolla", "Klar", "Fyll i själv"]), `Lägena är ${statuses.join(", ")}.`);
  const out = page.getByRole("status").filter({ hasText: "Tokens tog slut. Fotona som är kvar fyller du i för hand, eller köper tokens i TrainMeet ID och läser av dem igen." });
  await out.getByRole("link", { name: "Köp tokens i TrainMeet ID", exact: true }).waitFor();
  await page.getByRole("button", { name: "Läs av foto 4 igen", exact: true }).waitFor();
  await picturesShown(page, ".cat-omgangskort img.cat-listbild", 4);
  await screenshot(page, "omgang-kon");
  // The batch waits under Fordon until it is approved, and opens again from there.
  const address = page.url();
  await page.getByRole("link", { name: "Fordon", exact: true }).first().click();
  await heading(page, "Fordon");
  const waiting = page.locator(".cat-omgangar");
  await waiting.getByText("4 av 4 foton kvar att godkänna · 2 klara · 2 att kolla · 0 kvar").waitFor();
  // The drafts are not vehicles (CAT-148): the list is empty until they are approved.
  await page.locator(".cat-tom-lista").waitFor();
  check((await page.locator(".cat-tabell tbody tr").count()) === 0, "Utkasten står bland fordonen.");
  await screenshot(page, "omgang-under-fordon");
  await waiting.getByRole("link").click();
  await page.waitForURL(address);
  await rows.nth(3).waitFor();

  // 5. Godkänn alla while the fourth is empty: nothing is approved, and it is named (CAT-150).
  const fourth = await rows.nth(3).getAttribute("id");
  await page.getByRole("button", { name: "Godkänn alla (4)", exact: true }).click();
  await page.getByRole("alert").filter({ hasText: "Inget godkändes. Ett foto behöver fyllas i eller ändras först." }).waitFor();
  check((await rows.nth(3).getAttribute("class")).includes("cat-stoppad"), "Det tomma fotot pekas inte ut.");
  check((await page.locator(".cat-stoppad").count()) === 1, "Fler än ett foto pekas ut.");
  await rows.nth(3).getByText("Fyll i eller ändra det här fotot.", { exact: true }).waitFor();
  await page.waitForFunction((id) => document.activeElement?.id === id, fourth);
  check((await fromCatalog(page, "/api/catalog/1/vehicles")).total === 0, "Något godkändes ändå.");
  await screenshot(page, "omgang-stoppad");

  // 6. The fourth filled in, in the same form as Lägg till med foto.
  await page.getByRole("button", { name: "Ändra foto 4", exact: true }).click();
  await heading(page, "Foto 4 i omgången");
  await page.getByLabel("Slag", { exact: true }).selectOption("freight_wagon");
  await page.getByLabel("Littera", { exact: true }).fill("Zans");
  await page.getByLabel("Nummer", { exact: true }).fill("7720");
  await page.getByLabel("Bolag", { exact: true }).fill("Green Cargo");
  await screenshot(page, "omgang-fyll-i");
  await page.getByRole("button", { name: "Spara", exact: true }).click();
  await heading(page, "Många foton på en gång");
  await rows.nth(3).locator("b", { hasText: "Zans 7720" }).waitFor();
  check((await page.locator(".cat-stoppad").count()) === 0, "Det ifyllda fotot pekas fortfarande ut.");
  await screenshot(page, "omgang-ifylld");

  // 7–8. Godkänn alla: four vehicles, each with its photo as its picture (CAT-150, CAT-131).
  await page.getByRole("button", { name: "Godkänn alla (4)", exact: true }).click();
  await page.waitForURL(`${BASE}/fordon`);
  await heading(page, "Fordon");
  await page.waitForFunction(() => document.querySelectorAll(".cat-tabell tbody tr").length === 4);
  const listed = await page.locator(".cat-tabell tbody .cat-fordon b").allInnerTexts();
  check(JSON.stringify([...listed].sort()) === JSON.stringify(["Gbs 3087", "Hbis 2253", "Sgns 1209", "Zans 7720"]), `Fordonen är ${listed.join(", ")}.`);
  await picturesShown(page, ".cat-tabell img.cat-listbild", 4);
  check((await page.getByText("Omgångar att gå igenom").count()) === 0, "Omgången står kvar att gå igenom.");
  const vehicles = (await fromCatalog(page, "/api/catalog/1/vehicles")).vehicles;
  const gbs = vehicles.find((vehicle) => vehicle.litt === "Gbs");
  const zans = vehicles.find((vehicle) => vehicle.litt === "Zans");
  check(gbs?.field_sources.litt === "ai" && gbs?.field_sources.number === "ai", "Gbs har inte AI:n som källa.");
  check(zans?.field_sources.litt === "owner", "Det ifyllda fotot har inte ägaren som källa.");
  await screenshot(page, "fordonen");
  console.log("Lägg till flera: fyra foton, tre lästa och ett för hand, stoppat, ifyllt och godkänt.");
}

async function main() {
  check(CHROME, "CHROME_PATH saknas: sökvägen till Chrome eller Chromium.");
  if (SHOTS) mkdirSync(SHOTS, { recursive: true });
  // Playwright starts Chrome without its sandbox unless asked (chromiumSandbox), also as root.
  const browser = await chromium.launch({ executablePath: CHROME, headless: true });
  const problems = [];
  let page;
  try {
    const context = await browser.newContext({ locale: "sv-SE", viewport: { width: 1280, height: 900 } });
    page = await context.newPage();
    page.setDefaultTimeout(20_000);
    page.on("pageerror", (error) => problems.push(`Fel i sidan: ${error.message}`));
    page.on("console", (message) => {
      // A no from Catalog is part of the test (422 for Godkänn alla); anything else is not.
      if (message.type() === "error" && !message.text().startsWith("Failed to load resource")) problems.push(`Konsolen: ${message.text()}`);
    });
    await singlePhoto(page);
    await batch(page);
    check(problems.length === 0, problems.join("\n"));
    console.log("Webbläsarprovet gick igenom.");
  } catch (error) {
    if (page) await screenshot(page, "fel").catch(() => undefined);
    console.error(error instanceof ProvFel ? `Webbläsarprovet: ${error.message}` : error);
    if (problems.length) console.error(problems.join("\n"));
    process.exitCode = 1;
  } finally {
    await browser.close();
  }
}

await main();
