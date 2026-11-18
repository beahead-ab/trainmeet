// Webbläsarprovet för kör efter pappret (#81 del d, LOK-13, LOK-18, LOK-29, LOK-33): förare som
// fotar ett köruppdrag som saknas i planen, mot en hubb med Provbanan och en låtsad AI, i en
// riktig Chrome.
//
//   PROV_ADRESS=http://127.0.0.1:8080 CHROME_PATH=/opt/pw-browsers/chromium node apps/lokforaren/e2e/efter-pappret.mjs
//
// Den låtsade AI:n startas här, på den här datorn, och kopplas in som hubbens egen AI: den läser
// gratis (TOKEN-13), så ingen nyckel och inget saldo behövs. Den läser hubbens provbild med
// siffrorna och svarar på pappret med tjänst 24 på Provbanan, där Åsens avgång inte gick att
// läsa och Bruket inte finns i träffen. Har hubben redan en egen AI avbryts provet: det byter
// aldrig ut en riktig. Kör det mot en provhubb. PROV_AI_ADRESS är adressen hubben når den
// låtsade AI:n på, när hubben inte kör på samma dator (till exempel i Docker).
//
// Cleo fotar två sidor, ser priset och vem som betalar, läser, ser de närmaste tjänsterna först
// (LF16) och kör efter pappret; körplanen är märkt efter pappret med den oläsliga tiden okänd, och
// trafikledningen godkänner den. Dan tar en tjänst i planen i stället, så att pappret släpps.
// Eva får nej med skälet och kan ta en annan tjänst.
import { chromium } from "playwright-core";
import { mkdirSync } from "node:fs";
import { createServer } from "node:http";
import { join } from "node:path";
import { crc32, deflateSync, inflateSync } from "node:zlib";

const BASE = (process.env.PROV_ADRESS ?? "http://127.0.0.1:8080").replace(/\/+$/, "");
const PIN = process.env.PROV_PIN ?? "482915";
const SHOTS = process.env.PROV_BILDER ?? "";
const CHROME = process.env.CHROME_PATH ?? "";
const AI_ADDRESS = process.env.PROV_AI_ADRESS ?? "";
const PHONE = { viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true, locale: "sv-SE" };
const DRIVERS = `${BASE}/api/drift/1/drivers`;
const CAMERA = "GPS 57.1834 N 14.0432 E";

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

// --- The pretend AI ----------------------------------------------------------------------------

/** The hub's probe digits on a 3 × 5 grid (integrationer/ai.py DIGITS). */
const DIGITS = {
  0: ["111", "101", "101", "101", "111"],
  1: ["010", "110", "010", "010", "111"],
  2: ["111", "001", "111", "100", "111"],
  3: ["111", "001", "111", "001", "111"],
  4: ["101", "101", "111", "001", "001"],
  5: ["111", "100", "111", "001", "111"],
  6: ["111", "100", "111", "101", "111"],
  7: ["111", "001", "010", "010", "010"],
  8: ["111", "101", "111", "101", "111"],
  9: ["111", "101", "111", "001", "111"],
};

/** The number in the hub's probe picture (integrationer/ai.py drawn): an 8-bit grey PNG, each
 * digit three cells wide with a cell between, twelve pixels to a cell. */
function readProbe(png) {
  const width = png.readUInt32BE(16);
  const chunks = [];
  for (let at = 8; at < png.length; ) {
    const length = png.readUInt32BE(at);
    if (png.toString("latin1", at + 4, at + 8) === "IDAT") chunks.push(png.subarray(at + 8, at + 8 + length));
    at += 12 + length;
  }
  const pixels = inflateSync(Buffer.concat(chunks));
  const black = (x, y) => pixels[y * (width + 1) + 1 + x] < 128;
  const count = Math.round((width / 12 - 1) / 4);
  let number = "";
  for (let index = 0; index < count; index += 1) {
    const rows = [0, 1, 2, 3, 4].map((row) => [0, 1, 2].map((column) => (black((1 + index * 4 + column) * 12 + 6, (row + 1) * 12 + 6) ? "1" : "0")).join(""));
    number += Object.keys(DIGITS).find((digit) => DIGITS[digit].join() === rows.join()) ?? "?";
  }
  return number;
}

/** Tjänst 24 as an AI would write it: not in Provbanan's plan, starting 06:31 at Norrby. */
const PAPER = JSON.stringify({
  number: "24",
  train: "G 4521",
  operator: "Green Cargo",
  start: { time: "06:31", place: "Norrby" },
  end: { time: "07:20", place: "Sjövik" },
  rows: [
    { place: "Norrby", departure: "06:41", track: "3", note: "Koppla loket." },
    { place: "Åsen", arrival: "06:49", departure: "06:5?" },
    { place: "Bruket", arrival: "06:55", departure: "06:56" },
    { place: "Mellanå", arrival: "06:59", departure: "07:01" },
    { place: "Sjövik", arrival: "07:10", track: "2" },
  ],
});

/** A chat service on this machine that reads the probe and the paper. It notes the pictures it
 * was sent. */
async function pretendAi() {
  const asked = [];
  const server = createServer((request, response) => {
    const parts = [];
    request.on("data", (part) => parts.push(part));
    request.on("end", () => {
      const reply = (status, body) => {
        response.writeHead(status, { "Content-Type": "application/json" });
        response.end(JSON.stringify(body));
      };
      if (request.method !== "POST" || request.url !== "/chat/completions") return reply(404, { error: "no such path" });
      const content = JSON.parse(Buffer.concat(parts).toString("utf8")).messages[0].content;
      const prompt = content.find((part) => part.type === "text")?.text ?? "";
      const pictures = content.filter((part) => part.type === "image_url").map((part) => part.image_url.url);
      asked.push({ prompt, pictures });
      const text = prompt.startsWith("Vilket tal") ? readProbe(Buffer.from(pictures[0].split(",")[1], "base64")) : `Här är avskriften:\n${PAPER}`;
      reply(200, { choices: [{ message: { content: text } }] });
    });
  });
  await new Promise((resolve) => server.listen(0, AI_ADDRESS ? "0.0.0.0" : "127.0.0.1", resolve));
  const { port } = server.address();
  return { server, asked, address: AI_ADDRESS ? AI_ADDRESS.replace(/\/+$/, "") : `http://127.0.0.1:${port}` };
}

/** A photo of a page as a phone's camera might make it: a PNG with a text chunk saying where. */
function photoOfPage(shade) {
  const width = 600;
  const height = 800;
  const rows = [];
  for (let y = 0; y < height; y += 1) {
    const line = Buffer.alloc(width + 1, shade);
    line[0] = 0;
    if (y % 40 < 3) line.fill(40, 1); // the timetable's lines
    rows.push(line);
  }
  const chunk = (kind, data) => {
    const head = Buffer.alloc(4);
    head.writeUInt32BE(data.length);
    const tail = Buffer.alloc(4);
    tail.writeUInt32BE(crc32(Buffer.concat([Buffer.from(kind, "latin1"), data])));
    return Buffer.concat([head, Buffer.from(kind, "latin1"), data, tail]);
  };
  const header = Buffer.alloc(13);
  header.writeUInt32BE(width, 0);
  header.writeUInt32BE(height, 4);
  header[8] = 8; // 8-bit grey
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk("IHDR", header),
    chunk("tEXt", Buffer.from(`Comment\0${CAMERA}`, "latin1")),
    chunk("IDAT", deflateSync(Buffer.concat(rows))),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

const PAGES = [
  { name: "framsidan.png", mimeType: "image/png", buffer: photoOfPage(250) },
  { name: "tidtabellen.png", mimeType: "image/png", buffer: photoOfPage(235) },
];

// --- The dispatcher and the phones ---------------------------------------------------------------

/** The dispatcher: the hub set up, logged in with its PIN, Provbanan running with the clock, no
 * drivers left on the services, and the pretend AI as the hub's own. */
async function dispatcher(browser, ai) {
  const context = await browser.newContext({ locale: "sv-SE", viewport: { width: 1280, height: 900 } });
  const api = context.request;
  await api.post(`${BASE}/api/hub/setup`, { data: { name: "Hubben", pin: PIN } }); // already set up: refused, and that is fine
  const login = await api.post(`${BASE}/api/hub/login`, { data: { pin: PIN } });
  check(login.ok(), `Trafikledningen kom inte in med PIN-koden (${login.status()}).`);
  check((await api.get(`${BASE}/api/hub/ai`)).status() === 404, "Hubben har redan en egen AI. Provet byter inte ut den: kör det mot en provhubb.");
  const connected = await api.post(`${BASE}/api/hub/ai`, { data: { format: "chat", address: ai.address, model: "låtsas-modell", key: "låtsas-nyckel-inte-riktig" } });
  check(connected.ok(), `Den låtsade AI:n gick inte att koppla in (${connected.status()}): ${await connected.text()}`);
  if (!(await api.get(`${BASE}/api/drift/1/now`)).ok()) {
    const started = await api.post(`${BASE}/api/drift/1/start`, { data: { version: 1 } });
    check(started.ok(), `Träffen startade inte (${started.status()}).`);
  }
  const now = await (await api.get(`${BASE}/api/drift/1/now`)).json();
  if (!now.clock.running) await api.post(`${BASE}/api/drift/1/clock`, { data: { action: "start" } });
  await takeBack(api);
  const { code } = await (await api.get(`${DRIVERS}/connect`)).json();
  return { context, api, address: `${BASE}/lokforaren/#kod=${code}` };
}

async function takeBack(api) {
  const overview = await (await api.get(`${DRIVERS}/overview`)).json();
  for (const row of overview.drivers ?? []) {
    if (row.service) await api.post(`${DRIVERS}/take-back`, { data: { driver: row.driver.id } });
  }
}

async function phone(browser, address, name, errors) {
  const context = await browser.newContext(PHONE);
  const page = await context.newPage();
  page.on("pageerror", (error) => errors.push(`${name}: ${error}`));
  await page.goto(address);
  await page.getByLabel("Namn").fill(name);
  await page.getByRole("button", { name: "Medel", exact: true }).click();
  await page.getByRole("button", { name: "Börja köra" }).click();
  await page.getByRole("heading", { name: "Välj tjänst" }).waitFor();
  return page;
}

/** The camera beside the search: two pages, the price first, then Läs pappret. */
async function readPaper(page, name) {
  await page.locator("label.lok-kamera input[type=file]").setInputFiles(PAGES);
  await page.getByRole("heading", { name: "Fota pappret" }).waitFor();
  await page.getByAltText("Sida 2").waitFor();
  await page.getByText("Hubbens egen AI läser, utan tokens.").waitFor();
  if (name) {
    await page.getByRole("button", { name: "Läs pappret" }).scrollIntoViewIfNeeded();
    await screenshot(page, name);
  }
  await page.getByRole("button", { name: "Läs pappret" }).click();
  await page.getByRole("heading", { name: "Pappret och planen" }).waitFor();
}

async function paperOf(api, driverName) {
  const overview = await (await api.get(`${DRIVERS}/overview`)).json();
  return overview.papers.find((paper) => paper.driver_name === driverName && paper.status === "waiting");
}

const errors = [];
const browser = await chromium.launch(CHROME ? { executablePath: CHROME } : {});
const ai = await pretendAi();
let api = null;
try {
  if (SHOTS) mkdirSync(SHOTS, { recursive: true });
  const dispatch = await dispatcher(browser, ai);
  api = dispatch.api;

  // Tåg efter pappret i Nu innan Cleo läser: en tidigare körning kan ha lämnat godkända.
  const paperLegs = async () => ((await (await api.get(`${BASE}/api/drift/1/now`)).json()).legs ?? []).filter((leg) => leg.paper).length;
  const legsBefore = await paperLegs();

  // Cleo hittar inte sin tjänst: hon fotar framsidan och tidtabellen och ser priset först.
  const cleo = await phone(browser, dispatch.address, "Cleo", errors);
  await screenshot(cleo, "tag-med-kameran");
  await readPaper(cleo, "fota-pappret-priset");
  const sent = ai.asked.at(-1);
  check(sent.pictures.length === 2, `AI:n fick ${sent.pictures.length} sidor, inte 2.`);
  for (const picture of sent.pictures) {
    check(!Buffer.from(picture.split(",")[1], "base64").includes(CAMERA), "Kamerans data följde med fotot.");
  }
  // De närmaste tjänsterna i planen först (LF16).
  await cleo.getByText("Ingen tjänst startar 06:31 vid Norrby.").waitFor();
  await cleo.getByText("Närmast i planen").waitFor();
  await screenshot(cleo, "pappret-och-planen");
  await cleo.getByRole("button", { name: "Kör efter pappret" }).click();
  await cleo.getByRole("heading", { name: /Tjänst 24/ }).waitFor();
  await cleo.getByText("Väntar på trafikledningen.").waitFor();
  const show = cleo.getByRole("button", { name: "Visa körplanen" });
  if (await show.isVisible()) await show.click();
  await cleo.getByText("oläslig").first().waitFor();
  await cleo.getByText("inte i träffen").first().waitFor();
  await cleo.waitForTimeout(800); // the NU-line's smooth scroll
  await cleo.evaluate(() => window.scrollTo(0, 0));
  await screenshot(cleo, "korplan-efter-pappret");
  await cleo.getByText("oläslig").first().scrollIntoViewIfNeeded();
  await screenshot(cleo, "korplan-olaslig-tid");
  await cleo.getByRole("button", { name: "Sida 1 av 2" }).first().click();
  await cleo.getByRole("dialog", { name: "Sida 1 av 2" }).waitFor();
  await screenshot(cleo, "fotot");
  await cleo.getByRole("button", { name: "Stäng" }).click();

  // Ingen station ser tåget förrän trafikledningen har godkänt det (LOK-13).
  check((await paperLegs()) === legsBefore, "Nu visar tåget efter pappret före godkännandet.");
  const waiting = await paperOf(api, "Cleo");
  check(waiting, "Förare i Drift har inte Cleos papper.");
  // Trafikledningen ger tåget ett nummer: pappret säger G 4521, men en tidigare körning på samma
  // hubb kan redan ha det numret i dag.
  const number = `G ${4500 + (Date.now() % 400)}`;
  const approved = await api.post(`${DRIVERS}/paper/${waiting.paper}/approve`, { data: { train_number: number } });
  check(approved.ok(), `Godkänn gick inte (${approved.status()}): ${await approved.text()}`);
  await cleo.getByText(`Godkänd · tåg ${number}.`).waitFor();
  check((await paperLegs()) > legsBefore, "Nu visar inte tåget efter pappret när det är godkänt.");
  await screenshot(cleo, "godkand");

  // Dan tar en tjänst i planen i stället: pappret släpps (LF16).
  const dan = await phone(browser, dispatch.address, "Dan", errors);
  await readPaper(dan, null);
  await dan.locator(".lok-lista .lok-tjanst").first().click();
  await dan.getByRole("button", { name: "Ta tjänsten i stället" }).waitFor();
  await screenshot(dan, "ta-i-stallet");
  await dan.getByRole("button", { name: "Ta tjänsten i stället" }).click();
  await dan.getByRole("heading", { name: /Tjänst 3/ }).waitFor();
  await dan.getByText("Papper 24").first().waitFor();
  const danPaper = (await (await api.get(`${DRIVERS}/overview`)).json()).papers.find((paper) => paper.driver_name === "Dan");
  check(danPaper?.status === "withdrawn", `Dans papper släpptes inte: ${danPaper?.status}`);

  // Eva får nej, med skälet, och tar en annan tjänst (LOK-13).
  const eva = await phone(browser, dispatch.address, "Eva", errors);
  await readPaper(eva, null);
  const evas = await paperOf(api, "Eva");
  const rejected = await api.post(`${DRIVERS}/paper/${evas.paper}/reject`, { data: { reason: "Tjänst 3 är samma. Ta den." } });
  check(rejected.ok(), `Avslå gick inte (${rejected.status()}).`);
  await eva.getByText("Trafikledningen avslog tjänsten efter pappret: Tjänst 3 är samma. Ta den.").first().waitFor();
  await screenshot(eva, "avslagen");
  await eva.getByRole("link", { name: "Tåg" }).last().click();
  await eva.getByRole("button", { name: "Hittar inte min tjänst · fota pappret" }).waitFor();

  check(errors.length === 0, `Fel i sidan:\n${errors.join("\n")}`);
  console.log("Efter pappret: priset först, läst med den låtsade AI:n, de närmaste tjänsterna först, körplanen märkt med den oläsliga tiden okänd, godkänd, släppt för en tjänst i planen, och avslagen med skälet.");
} catch (error) {
  console.error(error instanceof ProvFel ? `Provet gick inte igenom: ${error.message}` : error);
  for (const [index, context] of browser.contexts().entries()) {
    for (const page of context.pages()) await screenshot(page, `fel-${index}`).catch(() => undefined);
  }
  process.exitCode = 1;
} finally {
  // The hub as it was: no driver left on a service, and no pretend AI.
  if (api) {
    await takeBack(api).catch(() => undefined);
    await api.post(`${BASE}/api/hub/ai/disconnect`).catch(() => undefined);
  }
  await browser.close();
  ai.server.close();
}
