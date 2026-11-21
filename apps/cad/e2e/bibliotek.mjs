// Webbläsarprovet för modulbiblioteket (#89 del a): CAD med sin riktiga databas och webbapp, mot en
// låtsad TrainMeet ID (cad/prov_webblasare.py). Provkonto A loggar in med provinloggningen, ser det
// tomma biblioteket, gör en rak modul och en kurvmodul ur bara mått, godkänner kurvan, och ser
// biblioteket med gavlarna och statusen, modulens sida och gavelprofilerna. Sedan Ritningen och Lås
// mått (#89 del b, ritningen.mjs), Foto och kontroll (#89 del c1, foto.mjs), en kurvmodul ur ett foto
// och en modul ur en skiss (#89 del c2, kurvaskiss.mjs), Landskapet och Exportera (#89 del d1,
// landskap.mjs), en anläggning av två moduler med Till TKL Studio (#89 del d2, anlaggning.mjs), CAD i
// mobilen med QR-koden och en låtsad kamera i en telefon (#90, mobil.mjs), och Import från AnyRail
// med en syntetisk fil (#91, anyrail.mjs), som körs härifrån så att CI-steget är detsamma.
//
//   CHROME_PATH=/usr/bin/google-chrome node apps/cad/e2e/bibliotek.mjs
//
// PROV_ADRESS är CAD:s adress (http://127.0.0.1:8095), och PROV_BILDER en mapp för skärmbilderna.
// CAD ska ha en tom databas (prov_webblasare.py --ny).
import { chromium } from "playwright-core";
import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { anlaggning } from "./anlaggning.mjs";
import { anyrail } from "./anyrail.mjs";
import { foto } from "./foto.mjs";
import { kurvaOchSkiss } from "./kurvaskiss.mjs";
import { landskap } from "./landskap.mjs";
import { mobil } from "./mobil.mjs";
import { ritningen } from "./ritningen.mjs";

const BASE = (process.env.PROV_ADRESS ?? "http://127.0.0.1:8095").replace(/\/+$/, "");
const SHOTS = process.env.PROV_BILDER ?? "";
const CHROME = process.env.CHROME_PATH ?? "";

if (SHOTS) mkdirSync(SHOTS, { recursive: true });

async function shot(page, name) {
  if (!SHOTS) return;
  // From the top, so that the sticky header is where it belongs in the whole page.
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: join(SHOTS, `${name}.png`), fullPage: true });
}
/** Where the phone's screenshots go (mobil.mjs). */
shot.dir = SHOTS;

function check(condition, message) {
  if (!condition) throw new Error(message);
}

const browser = await chromium.launch({ executablePath: CHROME || undefined, args: ["--no-sandbox"] });
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, locale: "sv-SE", colorScheme: "light" });
const problems = [];
page.on("pageerror", (error) => problems.push(String(error)));
page.on("console", (message) => {
  if (message.type() === "error") problems.push(message.text());
});

try {
  // Logga in med provinloggningen.
  await page.goto(`${BASE}/moduler`);
  await page.getByRole("heading", { name: "Logga in i TrainMeet CAD" }).waitFor();
  await page.getByRole("button", { name: "Provkonto A" }).click();

  // Tomt bibliotek: så går det till.
  await page.getByRole("heading", { name: "Bygg ditt modulbibliotek" }).waitFor();
  check(await page.getByText("86 tokens").first().isVisible(), "Saldot syns inte i sidhuvudet.");
  await shot(page, "02-tomt-bibliotek");

  // Ny modul: fyra vägar in, och bara mått går nu.
  await page.getByRole("link", { name: "+ Lägg till första modulen" }).click();
  await page.getByRole("heading", { name: "Ny modul", exact: true }).waitFor();
  await shot(page, "03-ny-modul");

  // Rak modul: FREMO dubbelspår vid A och en egen gavel med tre spår vid B.
  await page.getByRole("link", { name: "Rak modul" }).click();
  await page.getByRole("heading", { name: "Ny rak modul" }).waitFor();
  await page.locator('input[name="namn"]').fill("Exempelstation");
  await page.locator('input[name="langd"]').fill("1500");
  await page.locator('input[name="bredd"]').fill("700");
  await page.locator('select[name="profil-A"]').selectOption("h0-fremo-dubbelspar");
  await page.locator('input[name="gavel-A-0"]').fill("330");
  await page.locator('input[name="gavel-A-1"]').fill("50");
  await page.locator('input[name="lika"]').uncheck();
  await page.locator('select[name="profil-B"]').selectOption("");
  await page.getByRole("button", { name: "+ Lägg till spår" }).click();
  await page.locator('input[name="gavel-B-0"]').fill("245");
  await page.locator('input[name="gavel-B-1"]').fill("50");
  await page.locator('input[name="gavel-B-2"]').fill("50");
  await page.getByText("Spår 3 ligger 345 mm från Kant 1").waitFor();
  await page.getByText("2 spår in vid A, 3 spår ut vid B").waitFor();
  await shot(page, "04-rak-modul");
  await page.getByRole("button", { name: "Spara" }).click();
  await page.getByRole("heading", { name: "Exempelstation" }).waitFor();
  check(await page.getByText("M-001").first().isVisible(), "Modulen fick inget nummer.");
  check(await page.getByText("Utkast").first().isVisible(), "Den raka modulen med olika gavlar ska vara ett utkast.");

  // Kurvmodul: snöret 1035 och pilhöjden 68 ger R 2 003,2 mm · 29,94°, som det räknas fram (CAD16).
  await page.goto(`${BASE}/moduler/ny/kurva`);
  await page.getByRole("heading", { name: "Ny kurvmodul" }).waitFor();
  await page.locator('input[name="namn"]').fill("Kurva 30° · K2");
  await page.locator('input[name="snore"]').fill("1035");
  await page.locator('input[name="pilhojd"]').fill("68");
  await page.getByText("Uträknat: R 2 003,2 mm · 29,94°").waitFor();
  check(!(await page.getByText("Ångra avrundning").count()), "Kurvan ska inte avrundas (CAD16).");
  await page.locator('select[name="profil-A"]').selectOption("h0-dubbelspar");
  await page.locator('input[name="gavel-A-0"]').fill("200");
  await page.locator('input[name="gavel-A-1"]').fill("50");
  await page.getByText("utan avrundning").waitFor();
  await shot(page, "05-kurvmodul");
  await page.getByRole("button", { name: "Spara" }).click();
  await page.getByRole("heading", { name: "Kurva 30° · K2" }).waitFor();
  check(await page.getByText("Mått klara · inget foto").first().isVisible(), "Kurvan ska ha måtten klara.");

  // Godkänn kurvan.
  await page.getByRole("button", { name: "Godkänn" }).click();
  await page.getByText(/✓ Godkänd \d+ \w+ \d{4}/).waitFor();
  await page.getByText("Version 1 godkänd").waitFor();
  await shot(page, "06-modulens-sida");
  // The Ritning tab opens Ritningen for the one who may change the module (#89 del b).
  await page.getByRole("link", { name: "Ritning", exact: true }).click();
  await page.getByRole("heading", { name: "Ritningen", exact: true }).waitFor();
  await page.getByText("Ur måtten").first().waitFor();
  await shot(page, "07-modulens-ritning");

  // En rak linjemodul med MMM:s gavel, 140 mm från Kant 1.
  await page.goto(`${BASE}/moduler/ny/rak`);
  await page.locator('input[name="namn"]').fill("Linje 1500");
  await page.locator('select[name="profil-A"]').selectOption("h0-mmm-enkelspar");
  check((await page.locator('input[name="gavel-A-0"]').inputValue()) === "140", "MMM:s spår ska ligga 140 mm från Kant 1.");
  await page.getByRole("button", { name: "Spara" }).click();
  await page.getByRole("heading", { name: "Linje 1500" }).waitFor();

  // Biblioteket: tre moduler med gavlar och status.
  await page.getByRole("link", { name: "Moduler", exact: true }).first().click();
  await page.getByRole("heading", { name: "Moduler", exact: true }).waitFor();
  const rows = page.locator("table.cad-tabell tbody tr");
  await rows.nth(2).waitFor();
  check((await rows.count()) === 3, "Biblioteket ska ha tre moduler.");
  for (const text of ["Exempelstation", "Kurva 30° · K2", "Linje 1500", "FREMO dubbelspår", "Egen gavel · 3 spår", "MMM enkelspår", "Godkänd", "Utkast"]) {
    check(await page.locator("table.cad-tabell").getByText(text).first().isVisible(), `${text} saknas i biblioteket.`);
  }
  await shot(page, "01-modulerna");

  // Gavelprofilerna räknar gavlarna.
  await page.getByRole("link", { name: "Gavelprofiler" }).first().click();
  await page.getByRole("heading", { name: "Gavelprofiler", exact: true }).waitFor();
  // MMM enkelspår is used by the straight line module's two gables.
  await page.locator("article.cad-profil", { hasText: "MMM enkelspår" }).getByText("2 gavlar").waitFor();
  await shot(page, "08-gavelprofiler");

  await page.getByRole("link", { name: "Anläggningar" }).first().click();
  await page.getByRole("heading", { name: "Anläggningar", exact: true }).waitFor();
  await shot(page, "09-anlaggningar");

  await ritningen(page, { base: BASE, shot, check });
  await foto(page, { base: BASE, shot, check });
  await kurvaOchSkiss(page, { base: BASE, shot, check });
  await landskap(page, { base: BASE, shot, check });
  await anlaggning(page, { base: BASE, shot, check });
  await mobil(page, { base: BASE, shot, check, chrome: CHROME });
  await anyrail(page, { base: BASE, shot, check });

  check(problems.length === 0, `Fel i webbläsaren: ${problems.join(" | ")}`);
  console.log("Webbläsarprovet för modulbiblioteket, Ritningen, Foto och kontroll, kurvmodulen ur foto, skissen, Landskapet och Exportera, anläggningen, CAD i mobilen och AnyRail-importen gick igenom.");
} catch (error) {
  await shot(page, "fel");
  throw error;
} finally {
  await browser.close();
}
