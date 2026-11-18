// Webbläsarprovet för Lokföraren (#81 del b, LOK-15): två telefoner och trafikledningen mot en
// hubb med Provbanan som hubbens träff, i en riktig Chrome.
//
//   PROV_ADRESS=http://127.0.0.1:8080 CHROME_PATH=/opt/pw-browsers/chromium node apps/lokforaren/e2e/tva-forare.mjs
//
// PROV_ADRESS är hubbens adress och PROV_PIN hubbens PIN (482915 som i CI:s övriga prov);
// PROV_BILDER en mapp för skärmbilderna. Hubben sätts upp och träffen startas om det behövs.
//
// Trafikledningen läser QR-kodens adress under Förare. Två telefoner öppnar den, skriver namn och
// nivå (LOK-01, LOK-16). Båda vill ha tjänst 1: den första får den, och den andra får beskedet
// att den är tagen (LOK-40) och tar tjänst 4. Den första säger Försenad (LOK-23), och
// trafikledningen ser meddelandet under Förare i Drift och i Nu (TRAFIK-33).
import { chromium } from "playwright-core";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const BASE = (process.env.PROV_ADRESS ?? "http://127.0.0.1:8080").replace(/\/+$/, "");
const PIN = process.env.PROV_PIN ?? "482915";
const SHOTS = process.env.PROV_BILDER ?? "";
const CHROME = process.env.CHROME_PATH ?? "";
const PHONE = { viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true, locale: "sv-SE" };

class ProvFel extends Error {}

function check(condition, message) {
  if (!condition) throw new ProvFel(message);
}

let shot = 0;
async function screenshot(page, name) {
  if (!SHOTS) return;
  shot += 1;
  await page.screenshot({ path: join(SHOTS, `${String(shot).padStart(2, "0")}-${name}.png`) });
}

/** The dispatcher: the hub set up, logged in with its PIN, Provbanan running with the clock. */
async function dispatcher(browser) {
  const context = await browser.newContext({ locale: "sv-SE", viewport: { width: 1280, height: 900 } });
  const api = context.request;
  await api.post(`${BASE}/api/hub/setup`, { data: { name: "Hubben", pin: PIN } }); // already set up: refused, and that is fine
  const login = await api.post(`${BASE}/api/hub/login`, { data: { pin: PIN } });
  check(login.ok(), `Trafikledningen kom inte in med PIN-koden (${login.status()}).`);
  if (!(await api.get(`${BASE}/api/drift/1/now`)).ok()) {
    const started = await api.post(`${BASE}/api/drift/1/start`, { data: { version: 1 } });
    check(started.ok(), `Träffen startade inte (${started.status()}).`);
  }
  const now = await (await api.get(`${BASE}/api/drift/1/now`)).json();
  if (!now.clock.running) await api.post(`${BASE}/api/drift/1/clock`, { data: { action: "start" } });
  // A run before this one may have left drivers on the services: the dispatcher takes them back.
  const before = await (await api.get(`${BASE}/api/drift/1/drivers/overview`)).json();
  for (const row of before.drivers ?? []) {
    if (row.service) await api.post(`${BASE}/api/drift/1/drivers/take-back`, { data: { driver: row.driver.id } });
  }
  const joining = await api.get(`${BASE}/api/drift/1/drivers/connect`);
  check(joining.ok(), `Förare i Drift gav ingen QR-kod (${joining.status()}).`);
  const { url, code } = await joining.json();
  check(url.endsWith(`/lokforaren/#kod=${code}`), `QR-kodens adress är fel: ${url}`);
  return { context, api, address: `${BASE}/lokforaren/#kod=${code}` };
}

/** A phone opens the QR address and comes in with a name and a level. */
async function phone(browser, address, name, level, errors) {
  const context = await browser.newContext(PHONE);
  const page = await context.newPage();
  page.on("pageerror", (error) => errors.push(`${name}: ${error}`));
  await page.goto(address);
  await page.getByRole("heading", { name: "Vad heter du?" }).waitFor();
  await page.getByLabel("Namn").fill(name);
  await page.getByRole("button", { name: level, exact: true }).click();
  await screenshot(page, `kom-in-${name}`);
  await page.getByRole("button", { name: "Börja köra" }).click();
  await page.getByRole("heading", { name: "Välj tjänst" }).waitFor();
  check(!page.url().includes("kod="), "Koden ligger kvar i adressen.");
  return page;
}

async function search(page, number) {
  await page.getByRole("searchbox").fill(number);
  await page.getByText(`Träff på numret ${number}`).waitFor();
}

const errors = [];
const browser = await chromium.launch(CHROME ? { executablePath: CHROME } : {});
try {
  if (SHOTS) mkdirSync(SHOTS, { recursive: true });
  const { context, api, address } = await dispatcher(browser);

  // Två telefoner kommer in med QR-koden och vill båda ha tjänst 1.
  const anna = await phone(browser, address, "Anna", "Medel", errors);
  const bo = await phone(browser, address, "Bo", "Lätt", errors);
  await screenshot(anna, "listan");
  await search(anna, "1");
  await search(bo, "1");
  await screenshot(bo, "traff-pa-numret");
  await anna.getByRole("button", { name: "Det är min tjänst" }).click();
  await anna.getByRole("heading", { name: "Tjänst 1" }).waitFor();
  await anna.locator(".lok-nu").waitFor();
  await screenshot(anna, "korplanen");

  // Bo trycker efter Anna: tjänsten är tagen (LOK-40).
  await bo.getByRole("button", { name: "Det är min tjänst" }).click();
  await bo.getByText("Tjänsten är tagen. Någon annan hann före.").waitFor();
  await screenshot(bo, "tagen");
  await search(bo, "4");
  await bo.getByRole("button", { name: "Det är min tjänst" }).click();
  await bo.getByRole("heading", { name: "Tjänst 4" }).waitFor();
  await screenshot(bo, "tjanst-4");

  // Anna säger Försenad (LOK-23).
  await anna.getByRole("button", { name: "Säg till trafikledningen" }).click();
  await anna.getByRole("radio", { name: /Försenad/ }).click();
  await screenshot(anna, "sag-till");
  await anna.getByRole("button", { name: "Skicka: försenad" }).click();
  await anna.getByText(/Skickat \d\d:\d\d · Försenad/).waitFor();
  await screenshot(anna, "skickat");

  // Trafikledningen ser förarna, tjänsterna och meddelandet under Förare i Drift och i Nu.
  const overview = await (await api.get(`${BASE}/api/drift/1/drivers/overview`)).json();
  const holding = Object.fromEntries(overview.drivers.map((row) => [row.driver.name, row.service?.number ?? null]));
  check(holding.Anna === "1" && holding.Bo === "4", `Förare i Drift ser fel tjänster: ${JSON.stringify(holding)}`);
  check(overview.messages[0]?.kind === "delayed" && overview.messages[0]?.driver_name === "Anna", "Förare i Drift har inte Annas Försenad.");
  const now = await (await api.get(`${BASE}/api/drift/1/now`)).json();
  check(now.driver_messages.some((m) => m.kind === "delayed" && m.service_number === "1"), "Nu har inte meddelandet.");
  check(!JSON.stringify(now).includes("Anna"), "Nu är öppen och ska inte ha förarnas namn (B13).");
  const page = await context.newPage();
  await page.goto(`${BASE}/drift/forare`);
  await page.getByText(/\d\d:\d\d · Försenad/).first().waitFor();
  await page.getByText("Anna").first().waitFor();
  await screenshot(page, "trafikledningen");

  // Förare i appen: båda syns, på träffens nät med sina namn (LOK-27, LOK-37).
  await bo.getByRole("link", { name: "Förare" }).last().click();
  await bo.getByText("Anna").first().waitFor();
  await screenshot(bo, "forare");

  check(errors.length === 0, `Fel i sidan:\n${errors.join("\n")}`);
  console.log("Lokföraren: två telefoner, den första tar tjänsten, den andra får beskedet att den är tagen, och trafikledningen ser Försenad.");
} catch (error) {
  console.error(error instanceof ProvFel ? `Provet gick inte igenom: ${error.message}` : error);
  for (const [index, context] of browser.contexts().entries()) {
    for (const page of context.pages()) await screenshot(page, `fel-${index}`).catch(() => undefined);
  }
  process.exitCode = 1;
} finally {
  await browser.close();
}
