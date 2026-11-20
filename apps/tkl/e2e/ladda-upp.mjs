// Webbläsarprovet för Ladda upp ritning och Från CAD i Studio (#89 del c4 och d2), i en riktig Chrome mot en TKL ur
// bilden, en låtsad TrainMeet ID och en låtsad TrainMeet CAD som provet själv kör. TKL startar
// som Uppby med PIN, loggar in med TrainMeet ID under Inställningar, och i Studio › Rita blir
// Ladda upp ritning öppen. Provet laddar upp den syntetiska signalplanen, ser priset (gratis, en
// vektor-PDF), läser den, ser frågorna med teckenförklaringen först, svarar att ▲ är en knapp på
// panelen och gör förslaget: Rita visar stationen gul med motorns panel, Använd ritningen väntar på
// ägarens ja, Bekräfta förslaget tar bort det gula, och ritningen tas i bruk. Den låtsade CAD:en
// svarar med kontraktets exempel, CAD:s egen avläsning av samma ritning
// (contracts/examples/exempelby.drawing-read.json), och godtar bara personens token från ID.
//
// Från CAD (#89 del d2): samma låtsade CAD listar en syntetisk anläggning, vars spårgraf CAD:s egen
// kod gör (python -m cad.assembly_example, eller PROV_CAD_FORE och PROV_CAD_EFTER). Förslaget blir
// gult i Rita, bekräftas och tas i bruk, och TKL säger då till CAD vilken station som använder
// anläggningen. Sedan ändras anläggningen i CAD, och Läs in igen visar skillnaden: ett nytt spår och
// ett som flyttat, gula tills ägaren bekräftar dem.
//
//   PROV_TKL=http://127.0.0.1:8096 PROV_LATSAS=8097 PROV_RITNING=ritning.pdf \
//     CHROME_PATH=/usr/bin/google-chrome node apps/tkl/e2e/ladda-upp.mjs
//
// TKL ska vara startad med TKL_ID_ISSUER=http://127.0.0.1:$PROV_LATSAS/realms/trainmeet,
// TKL_ID_INTERNAL och TKL_CAD mot samma låtsade tjänster som TKL når dem, och TKL_PUBLIC_URL=$PROV_TKL.
// PROV_BILDER är en mapp för skärmbilderna; PROV_UNDERLAG en PNG som den låtsade CAD:en ger som
// den uträtade ritningen.
import { chromium } from "playwright-core";
import { execFileSync } from "node:child_process";
import { createServer } from "node:http";
import { generateKeyPairSync, randomUUID, sign } from "node:crypto";
import { mkdirSync, mkdtempSync, readFileSync, existsSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const TKL = (process.env.PROV_TKL ?? "http://127.0.0.1:8096").replace(/\/+$/, "");
const PORT = Number(process.env.PROV_LATSAS ?? "8097");
const ISSUER = `http://127.0.0.1:${PORT}/realms/trainmeet`;
const PIN = process.env.PROV_TKL_PIN ?? "4711";
const SHOTS = process.env.PROV_BILDER ?? "";
const CHROME = process.env.CHROME_PATH ?? "";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const EXAMPLE = JSON.parse(readFileSync(join(ROOT, "contracts/examples/exempelby.drawing-read.json"), "utf8"));
const DRAWING = process.env.PROV_RITNING && existsSync(process.env.PROV_RITNING) ? process.env.PROV_RITNING : "";
const ACCESS = `prov-${randomUUID()}`;

/** The synthetic assembly's track graph before and after its change, as CAD's own code makes it. */
function cadGraphs() {
  const given = [process.env.PROV_CAD_FORE, process.env.PROV_CAD_EFTER];
  if (given.every((f) => f && existsSync(f))) return given.map((f) => JSON.parse(readFileSync(f, "utf8")));
  const dir = mkdtempSync(join(tmpdir(), "cad-graf-"));
  try {
    const files = [join(dir, "fore.json"), join(dir, "efter.json")];
    execFileSync("uv", ["run", "--locked", "python", "-m", "cad.assembly_example", ...files], { cwd: ROOT, stdio: "inherit" });
    return files.map((f) => JSON.parse(readFileSync(f, "utf8")));
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}
const [BEFORE, AFTER] = cadGraphs();
let graph = BEFORE;
const stationUses = [];
const PERSON = randomUUID();

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

// --- The pretend TrainMeet ID: the public client tkl, its code for tokens, and the keys -------

const { privateKey, publicKey } = generateKeyPairSync("rsa", { modulusLength: 2048 });
const jwk = { ...publicKey.export({ format: "jwk" }), kid: "prov", alg: "RS256", use: "sig" };
const codes = new Map();
const b64 = (data) => Buffer.from(data).toString("base64url");

function token(claims) {
  const now = Math.floor(Date.now() / 1000);
  const head = b64(JSON.stringify({ alg: "RS256", typ: "JWT", kid: "prov" }));
  const body = b64(JSON.stringify({ iss: ISSUER, sub: PERSON, iat: now, exp: now + 3600, ...claims }));
  return `${head}.${body}.${b64(sign("RSA-SHA256", Buffer.from(`${head}.${body}`), privateKey))}`;
}

// --- The pretend TrainMeet CAD: one job, read with the contract's example ----------------------

const jobs = new Map();
let asked = 0;

function job(id, state, answers = {}) {
  const read = state === "done" ? { ...EXAMPLE, job: id, questions: EXAMPLE.questions.map((q) => ({ ...q, answer: answers[q.key] ?? null })) } : null;
  return {
    id,
    name: "Exempelby signalplan.pdf",
    state,
    progress: state === "done" ? 100 : 0,
    step: state === "done" ? "Klart" : "Väntar på Läs",
    created_at: new Date().toISOString(),
    format: "pdf",
    pages: [{ number: 1, kind: "vector", width: 842, height: 595, text: true, tokens: 0 }],
    page: 1,
    price: { tokens: 0, why: "vector", text: "Gratis: sidan har ritade linjer och text, som koden läser utan AI." },
    ai: { available: true, given: false, version: "1", sent_to: "TrainMeets AI", text: "Ritningens sida skickas till TrainMeets AI.", balance: 86, message: null },
    read,
    cost: 0,
    chain: "1.0.0",
    key: "0".repeat(64),
    message: null,
  };
}

const UNDERLAY = process.env.PROV_UNDERLAG && existsSync(process.env.PROV_UNDERLAG)
  ? readFileSync(process.env.PROV_UNDERLAG)
  : Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4//8/AAX+Av4N70a4AAAAAElFTkSuQmCC", "base64");

function reply(res, status, body, type = "application/json") {
  res.writeHead(status, { "Content-Type": type, "Cache-Control": "no-store" });
  res.end(type === "application/json" ? JSON.stringify(body) : body);
}

async function body(req) {
  const parts = [];
  for await (const part of req) parts.push(part);
  return Buffer.concat(parts);
}

const pretend = createServer(async (req, res) => {
  const url = new URL(req.url ?? "/", `http://127.0.0.1:${PORT}`);
  const path = url.pathname;
  const sent = await body(req);
  if (path.endsWith("/protocol/openid-connect/auth")) {
    const code = randomUUID();
    codes.set(code, url.searchParams.get("nonce"));
    const back = new URL(url.searchParams.get("redirect_uri") ?? "");
    back.searchParams.set("code", code);
    back.searchParams.set("state", url.searchParams.get("state") ?? "");
    res.writeHead(302, { Location: back.toString() });
    res.end();
    return;
  }
  if (path.endsWith("/protocol/openid-connect/token")) {
    const form = new URLSearchParams(sent.toString());
    if (form.get("grant_type") === "authorization_code" && codes.has(form.get("code"))) {
      const nonce = codes.get(form.get("code"));
      const idToken = token({ aud: "tkl", azp: "tkl", nonce, email: "prov@example.com", email_verified: true, name: "Provare Uppby" });
      reply(res, 200, { id_token: idToken, access_token: ACCESS, refresh_token: "prov-refresh", expires_in: 3600, token_type: "Bearer" });
      return;
    }
    reply(res, 200, { access_token: ACCESS, refresh_token: "prov-refresh", expires_in: 3600 });
    return;
  }
  if (path.endsWith("/protocol/openid-connect/certs")) {
    reply(res, 200, { keys: [jwk] });
    return;
  }
  if (path.startsWith("/api/cad/1/studio")) {
    if (req.headers.authorization !== `Bearer ${ACCESS}`) {
      reply(res, 401, { code: "login", message: "Logga in först." });
      return;
    }
    const where = `/api/cad/1/studio/assembly/${graph.source.id}`;
    if (path === "/api/cad/1/studio") reply(res, 200, { sources: [graph.source] });
    else if (path === where) reply(res, 200, graph);
    else if (path === `${where}/station` && req.method === "PUT") {
      stationUses.push(JSON.parse(sent.toString()));
      reply(res, 200, graph.source);
    } else reply(res, 404, { code: "not_found", message: "Finns inte." });
    return;
  }
  if (path.startsWith("/api/cad/1/drawings")) {
    if (req.headers.authorization !== `Bearer ${ACCESS}`) {
      reply(res, 401, { code: "login", message: "Logga in först." });
      return;
    }
    asked += 1;
    const rest = path.slice("/api/cad/1/drawings".length).replace(/^\//, "");
    if (req.method === "POST" && rest === "") {
      if (!sent.includes(Buffer.from('name="file"'))) {
        reply(res, 422, { code: "invalid", message: "Ingen fil." });
        return;
      }
      const id = randomUUID();
      jobs.set(id, job(id, "waiting"));
      reply(res, 201, jobs.get(id));
      return;
    }
    const [id, action] = rest.split("/");
    if (!jobs.has(id)) {
      reply(res, 404, { code: "not_found", message: "Finns inte." });
      return;
    }
    if (action === "read") jobs.set(id, job(id, "done"));
    if (action === "answers") {
      const given = Object.fromEntries(JSON.parse(sent.toString()).answers.map((a) => [a.key, a.answer]));
      jobs.set(id, job(id, "done", given));
    }
    if (action === "underlay") {
      reply(res, 200, UNDERLAY, "image/png");
      return;
    }
    reply(res, 200, jobs.get(id));
    return;
  }
  reply(res, 404, { detail: "Finns inte." });
});

// --- The test ---------------------------------------------------------------------------------

async function firstStart(page) {
  await page.goto(`${TKL}/`);
  await page.getByRole("heading", { level: 1 }).waitFor();
  if (await page.getByText("Första start · tre rutor").isVisible()) {
    await page.getByLabel("Namn", { exact: true }).fill("Uppby");
    await page.getByLabel("Kort namn").fill("upb");
    await page.getByLabel("Välj PIN").fill(PIN);
    await page.getByLabel("Skriv den igen").fill(PIN);
    await page.getByRole("button", { name: "Lås med PIN och starta" }).click();
  } else if (await page.getByText("TKL är låst. Skriv PIN-koden.").isVisible()) {
    await page.getByLabel("PIN").fill(PIN);
    await page.getByRole("button", { name: "Lås upp" }).click();
  }
  await page.getByRole("link", { name: "Studio" }).first().waitFor();
}

// --- Från CAD (#89 del d2) --------------------------------------------------------------------

async function openFromCad(page) {
  await page.goto(`${TKL}/studio/rita`);
  const way = page.getByRole("navigation", { name: "Väg in" }).getByRole("button", { name: "Från CAD" });
  await way.waitFor();
  await page.waitForFunction(() => {
    const button = [...document.querySelectorAll("nav.rita-vagar button")].find((b) => b.textContent === "Från CAD");
    return button && !button.disabled;
  });
  await way.click();
  const panel = page.getByRole("region", { name: "Från CAD" });
  await panel.locator(`li[data-kalla="${graph.source.id}"]`).waitFor();
  return panel;
}

async function franCad(page) {
  let panel = await openFromCad(page);
  await screenshot(page, "fran-cad-listan");
  await panel.getByRole("button", { name: "Gör förslaget i Rita" }).click();
  // Rita: CAD's track graph yellow, the engine's panel, and Använd ritningen waiting for the yes.
  await page.getByText("Förslaget ur TrainMeet CAD är gult").waitFor();
  await page.getByRole("region", { name: "Skillnaden mot CAD" }).getByText("Förslaget ur TrainMeet CAD").waitFor();
  await page.locator("svg.rita-rutnat .antagen").first().waitFor({ state: "attached" });
  check(await page.getByRole("button", { name: "Använd ritningen" }).isDisabled(), "Förslaget ur CAD kunde användas utan ägarens ja.");
  check(stationUses.length === 0, "CAD fick veta stationen före ägarens ja.");
  await screenshot(page, "fran-cad-forslag-gult");
  await page.getByRole("button", { name: /Bekräfta förslaget \(\d+\)/ }).click();
  await page.waitForFunction(() => document.querySelectorAll("svg.rita-rutnat .antagen").length === 0);
  await page.waitForFunction(() => {
    const button = [...document.querySelectorAll("button")].find((b) => b.textContent === "Använd ritningen");
    return button && !button.disabled;
  });
  await page.getByRole("button", { name: "Använd ritningen" }).click();
  await page.getByText("Används i Ställverket").waitFor();
  check(stationUses.length === 1 && stationUses[0].station_id === "upb" && stationUses[0].revision === BEFORE.source.revision, `CAD fick inte veta stationen: ${JSON.stringify(stationUses)}`);
  // The assembly changes in CAD: Läs in igen shows the difference.
  graph = AFTER;
  panel = await openFromCad(page);
  await panel.getByText("CAD visar stationen under Används i.").waitFor();
  await screenshot(page, "fran-cad-kopplad");
  await panel.getByRole("button", { name: "Läs in igen" }).click();
  const diff = page.getByRole("region", { name: "Skillnaden mot CAD" });
  await diff.getByText("Skillnaden mot förra gången").waitFor();
  await diff.locator('[data-skillnad="nytt"]', { hasText: "Nytt 1" }).waitFor();
  await diff.locator('[data-skillnad="flyttat"]', { hasText: "Flyttat 1" }).waitFor();
  await diff.getByText("M-003 Linje bortom · spår 1").waitFor();
  await page.getByRole("button", { name: /Bekräfta förslaget \(3\)/ }).waitFor();
  await screenshot(page, "fran-cad-skillnad");
}

async function main() {
  if (SHOTS) mkdirSync(SHOTS, { recursive: true });
  await new Promise((resolve) => pretend.listen(PORT, "0.0.0.0", resolve));
  const browser = await chromium.launch({ executablePath: CHROME || undefined, headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, locale: "sv-SE" });
  try {
    await firstStart(page);
    // Without a login with ID the way in is grey, with the reason; Rita still works.
    await page.goto(`${TKL}/studio/rita`);
    const way = page.getByRole("navigation", { name: "Väg in" }).getByRole("button", { name: "Ladda upp ritning" });
    await way.waitFor();
    check(await way.isDisabled(), "Ladda upp ritning är öppen utan inloggning med TrainMeet ID.");
    await page.getByText("kräver inloggning med TrainMeet ID").first().waitFor();
    await screenshot(page, "gra-utan-inloggning");
    // Logga in med TrainMeet ID under Inställningar: through the pretend ID and back.
    await page.goto(`${TKL}/installningar`);
    await page.getByText("TrainMeet ID och molnet", { exact: true }).click();
    await page.locator("#id-login").click();
    await page.waitForURL((url) => url.toString().startsWith(TKL), { timeout: 20000 });
    await page.goto(`${TKL}/studio/rita`);
    await way.waitFor();
    await page.waitForFunction(() => {
      const button = [...document.querySelectorAll("nav.rita-vagar button")].find((b) => b.textContent === "Ladda upp ritning");
      return button && !button.disabled;
    });
    await way.click();
    const panel = page.getByRole("region", { name: "Ladda upp ritning" });
    await panel.waitFor();
    const file = DRAWING ? DRAWING : { name: "Exempelby signalplan.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4\n% syntetisk\n") };
    await panel.getByLabel("Välj ritning").setInputFiles(file);
    await panel.getByText("Pris: Gratis").waitFor();
    await screenshot(page, "pris");
    await panel.getByRole("button", { name: "Läs ritningen" }).click();
    await panel.getByText("Frågor om ritningen · teckenförklaringen först").waitFor();
    const questions = await panel.locator("ol.ladda-fragor > li strong").allTextContents();
    check(questions[0] === "Vad är de orange linjerna?" && questions[1] === "Vad betyder ▲ i den här ritningen?", `Frågorna: ${questions.join(" | ")}`);
    check(await panel.getByRole("button", { name: "Gör förslaget i Rita" }).isDisabled(), "Förslaget kom före svaret om ▲.");
    await screenshot(page, "fragorna");
    await panel.locator('li[data-fraga="symbol.triangle-grona"]').getByRole("button", { name: /Knapp eller lampa/ }).click();
    await page.waitForFunction(() => {
      const button = [...document.querySelectorAll(".ladda-upp button")].find((b) => b.textContent === "Gör förslaget i Rita");
      return button && !button.disabled;
    });
    await panel.getByRole("button", { name: "Gör förslaget i Rita" }).click();
    // Rita: the proposal yellow, the engine's panel, and Använd ritningen waiting for the yes.
    await page.getByText("Förslaget ur ritningen är gult").waitFor();
    await page.locator("svg.rita-rutnat .antagen").first().waitFor({ state: "attached" });
    const confirm = page.getByRole("button", { name: /Bekräfta förslaget \(\d+\)/ });
    await confirm.waitFor();
    check(await page.getByRole("button", { name: "Använd ritningen" }).isDisabled(), "Förslaget kunde användas utan ägarens ja.");
    await page.getByText("inte bekräftade").first().waitFor();
    await screenshot(page, "forslaget-gult");
    await confirm.click();
    await page.waitForFunction(() => document.querySelectorAll("svg.rita-rutnat .antagen").length === 0);
    await page.waitForFunction(() => {
      const button = [...document.querySelectorAll("button")].find((b) => b.textContent === "Använd ritningen");
      return button && !button.disabled;
    });
    await screenshot(page, "bekraftat");
    await page.getByRole("button", { name: "Använd ritningen" }).click();
    await page.getByText("Används i Ställverket").waitFor();
    await screenshot(page, "i-bruk");
    check(asked >= 4, "TKL frågade inte CAD.");
    console.log("Ladda upp ritning: grå utan inloggning, priset, frågorna med teckenförklaringen först, förslaget gult och bekräftat, i bruk.");
    await franCad(page);
    console.log("Från CAD: anläggningen listad, förslaget gult, bekräftat och i bruk, CAD fick veta stationen, och omimporten visade skillnaden.");
  } catch (error) {
    await screenshot(page, "fel");
    throw error;
  } finally {
    await browser.close();
    pretend.close();
  }
}

main().catch((error) => {
  console.error(error instanceof ProvFel ? `Provet gick inte igenom: ${error.message}` : error);
  process.exit(1);
});
