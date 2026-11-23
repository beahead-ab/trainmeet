// Webbläsarprovet för skärmlåset (#266 del 1, S4, SKARM-03): en av Pi:ns utgångar mot en hubb
// med Provbanan som hubbens träff, i en riktig Chrome.
//
//   PROV_ADRESS=http://127.0.0.1:8080 CHROME_PATH=/opt/pw-browsers/chromium node apps/skarmar/e2e/skarmlas.mjs
//
// PROV_ADRESS är hubbens adress och PROV_PIN hubbens PIN (482915 som i CI:s övriga prov);
// PROV_BILDER en mapp för skärmbilderna. Hubben sätts upp och träffen startas om det behövs.
//
// Utgång 1 öppnas som Pi:ns kiosk gör, på /skarm?utgang=1. Tangentbordet och musen gör ingenting
// förrän hubbens PIN är skriven: ett fel PIN ger hubbens besked, rätt PIN låser upp. Skärmen
// ansluter med träffens kod och hamnar under Väntar som Pi:ns skärm 1, och får klockan i
// Klienter. Låst igen kommer ett klick inte fram till skärmen. Upplåst går Till hubben till
// hubbens sidor på utgången, och Lås skärmen där tar tillbaka klockan, låst och utloggad.
import { chromium } from "playwright-core";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const BASE = (process.env.PROV_ADRESS ?? "http://127.0.0.1:8080").replace(/\/+$/, "");
const PIN = process.env.PROV_PIN ?? "482915";
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
  await page.screenshot({ path: join(SHOTS, `${String(shot).padStart(2, "0")}-${name}.png`) });
}

/** The dispatcher's API: the hub set up, logged in with its PIN, Provbanan running. */
async function dispatcher(browser) {
  const context = await browser.newContext({ locale: "sv-SE" });
  const api = context.request;
  await api.post(`${BASE}/api/hub/setup`, { data: { name: "Hubben", pin: PIN } }); // already set up: refused, and that is fine
  const login = await api.post(`${BASE}/api/hub/login`, { data: { pin: PIN } });
  check(login.ok(), `Trafikledningen kom inte in med PIN-koden (${login.status()}).`);
  if (!(await api.get(`${BASE}/api/drift/1/now`)).ok()) {
    const started = await api.post(`${BASE}/api/drift/1/start`, { data: { version: 1 } });
    check(started.ok(), `Träffen startade inte (${started.status()}).`);
  }
  const joining = await (await api.get(`${BASE}/api/drift/1/connect`)).json();
  check(/^[0-9]{6}$/.test(joining.code ?? ""), "Träffen gav ingen kod att ansluta med.");
  return { context, api, code: joining.code };
}

/** The output's row under Klienter: Väntar until it has a view. */
async function outputRow(api, name) {
  const clients = await (await api.get(`${BASE}/api/drift/1/clients`)).json();
  return clients.filter((row) => row.kind === "screen" && row.name === name).at(-1) ?? null;
}

async function unlock(page, pin) {
  await page.keyboard.press("Space");
  await page.getByRole("dialog", { name: "Skärmen är låst" }).waitFor();
  await page.locator("#unlock-pin").fill(pin);
  await page.getByRole("button", { name: "Lås upp" }).click();
}

async function main() {
  if (SHOTS) mkdirSync(SHOTS, { recursive: true });
  const browser = await chromium.launch(CHROME ? { executablePath: CHROME } : {});
  const errors = [];
  try {
    const { api, code } = await dispatcher(browser);

    // Pi:ns kiosk: a window of its own at 1920 × 1080 on the first output.
    const kiosk = await browser.newContext({ locale: "sv-SE", viewport: { width: 1920, height: 1080 } });
    const page = await kiosk.newPage();
    page.on("pageerror", (error) => errors.push(String(error)));
    await page.goto(`${BASE}/skarm?utgang=1`);
    await page.getByRole("heading", { name: "Anslut skärmen" }).waitFor();
    check((await page.locator("#name").inputValue()) === "Pi:ns skärm 1", "Utgången heter inte Pi:ns skärm 1.");

    // Locked: a click in the code field asks for the PIN, and nothing is typed there.
    await page.locator("#code").click({ force: true });
    await page.getByRole("dialog", { name: "Skärmen är låst" }).waitFor();
    await page.keyboard.press("Escape");
    await page.getByRole("dialog").waitFor({ state: "detached" });
    await page.keyboard.type("123456");
    check((await page.locator("#code").inputValue()) === "", "Tangentbordet skrev i den låsta skärmen.");
    await screenshot(page, "last");

    // A wrong PIN gets the hub's own answer, and the lock stays.
    await unlock(page, "000000");
    await page.locator("#unlock-message", { hasText: "Fel PIN-kod." }).waitFor();
    check(!(await page.locator("#lock-open").count()), "Fel PIN låste upp skärmen.");
    await page.keyboard.press("Escape");

    // The right PIN unlocks, and the output joins with the meet's code.
    await unlock(page, PIN);
    await page.locator("#lock-open").waitFor();
    await screenshot(page, "upplast");
    await page.locator("#code").fill(code);
    await page.getByRole("button", { name: "Anslut" }).click();
    await page.getByRole("heading", { name: "Väntar på en vy" }).waitFor();
    check((await page.locator("#screen-name").textContent()) === "Pi:ns skärm 1", "Skärmen heter fel under Väntar.");

    // Klienter gives it the clock.
    const row = await outputRow(api, "Pi:ns skärm 1");
    check(row, "Pi:ns skärm 1 syns inte under Klienter.");
    const given = await api.post(`${BASE}/api/drift/1/clients/view`, { data: { client_id: row.client_id, view: "clock" } });
    check(given.ok(), `Klienter gav inte skärmen klockan (${given.status()}).`);
    await page.locator("#clock-view").waitFor();

    // Lås: a click no longer reaches the screen, and the PIN is asked for again.
    await page.locator("#lock").click();
    await page.locator("#lock-open").waitFor({ state: "detached" });
    await page.mouse.click(960, 540);
    await page.getByRole("dialog", { name: "Skärmen är låst" }).waitFor();
    await screenshot(page, "last-med-klockan");
    await page.keyboard.press("Escape");

    // Unlocked again, Till hubben opens the hub's pages on the output, logged in with the PIN.
    await unlock(page, PIN);
    await page.locator("#to-hub").click();
    await page.locator("#lock-output").waitFor();
    await screenshot(page, "hubben-pa-utgangen");

    // Lås skärmen: back to the clock, locked, and the PIN's session has ended.
    await page.locator("#lock-output").click();
    await page.waitForURL(`${BASE}/skarm?utgang=1`);
    await page.locator("#clock-view").waitFor();
    await page.keyboard.press("Space");
    await page.getByRole("dialog", { name: "Skärmen är låst" }).waitFor();
    const info = await (await page.request.get(`${BASE}/api/hub`)).json();
    check(info.logged_in === false, "Utgången är fortfarande inloggad efter Lås skärmen.");
    await screenshot(page, "tillbaka-last");

    check(errors.length === 0, `Fel på sidan: ${errors.join("; ")}`);
    console.log("Skärmlåset på Pi:ns utgång: låst, upplåst med hubbens PIN, ansluten, låst igen och tillbaka från hubbens sidor.");
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error instanceof ProvFel ? `Provet stoppade: ${error.message}` : error);
  process.exit(1);
});
