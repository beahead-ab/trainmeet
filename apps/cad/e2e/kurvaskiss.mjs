// Webbläsarprovet för del c2 (#89), efter Foto och kontroll i foto.mjs och i samma webbläsare: CI-steget
// kör bibliotek.mjs, som kör det här. CAD:s låtsade AI (cad/prov_webblasare.py) svarar på andra moduler
// än stationen med raka förbindelser och en korsning för varje förstorat parti.
//
// Kurvmodul ur ett foto:
// 1. Ett syntetiskt foto av en kurvmodul, 20° med Kant 1 ytterst på R 2000 och 400 mm bred, dubbelspår
//    140 och 197 mm från Kant 1 (cad/bildkedjan/syntetisk.py, scenen kurvmodul), laddas upp som en ny
//    modul med kordan och pilhöjden på spår 1.
// 2. Hörnen är hittade längs bågarna. Kant 1 sätts till den yttre långsidan och gavel A till den andra
//    gaveln än den föreslagna, genom att trycka på dem i fotot.
// 3. Fotot läses av med AI; kurvans kanter är cirkelbågar, så inget frågas om kurvan.
// 4. Gavlarnas spår 2 tas från fotot, och efter läsningen byts gavel A och B utan kostnad.
// 5. Ritningen visar spåren som bågar över mätbilden, och spårplanen godkänns.
//
// Modul ur en skiss:
// 6. En syntetisk skiss med två modulramar, färgpenna, norsk text och hänvisningslinjer över spåren laddas
//    upp under Från skiss, 1500 × 600 mm.
// 7. Ramen till vänster väljs, med Kant 1 upptill och gavel A till vänster som ritat.
// 8. Skissen läses med AI, som bara frågas om de två partier koden inte kan avgöra (12 tokens), och
//    modulen får spårplanen ur skissen: tre växlar och två korsningar, märkta Förslag ur skissen.
import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");

function synthetic(scene, name) {
  const dir = mkdtempSync(join(tmpdir(), "cad-c2-"));
  const file = join(dir, name);
  execFileSync("uv", ["run", "--locked", "python", "-m", "cad.bildkedjan.syntetisk", scene, file], { cwd: ROOT, stdio: "inherit" });
  return { file, done: () => rmSync(dir, { recursive: true, force: true }) };
}

async function cornersOnPhoto(page) {
  return page
    .locator("svg.cad-fotobild circle.cad-fotohorn")
    .evaluateAll((circles) => circles.map((c) => [Number(c.getAttribute("cx")), Number(c.getAttribute("cy"))]));
}

async function sideOf(page, kind) {
  return Number(await page.locator(`svg.cad-fotobild line.${kind}`).getAttribute("data-sida"));
}

export async function kurvaOchSkiss(page, { base, shot, check }) {
  // --- Kurvmodul ur ett foto ------------------------------------------------------------------
  const curve = synthetic("kurvmodul", "kurvmodul.jpg");
  try {
    // 1. Ny modul ur ett foto, Kurva: kordan och pilhöjden på spår 1 (R 1860, 20°).
    await page.goto(`${base}/moduler/ny/foto`);
    await page.getByRole("heading", { name: "Ny modul ur ett foto" }).waitFor();
    await page.locator('input[name="foto-namn"]').fill("Kurvmodul ur foto");
    await page.getByRole("radio", { name: "Kurva", exact: true }).click();
    await page.locator('input[name="foto-bredd"]').fill("400");
    await page.locator('input[name="foto-korda"]').fill("645,96");
    await page.locator('input[name="foto-pilhojd"]').fill("28,26");
    await page.locator('input[name="foto-spar1"]').fill("140");
    await page.locator('input[name="foton"]').setInputFiles(curve.file);
    await shot(page, "30-kurvmodul-ladda-upp");
    await page.getByRole("button", { name: "Ladda upp", exact: true }).click();

    // 2. Hörnen; Kant 1 är den längre långsidan (den yttre bågen), gavel A den andra gaveln.
    await page.getByRole("heading", { name: "Foto och kontroll" }).waitFor({ timeout: 60_000 });
    await page.getByText(/4 hörn hittade/).first().waitFor();
    const corners = await cornersOnPhoto(page);
    check(corners.length === 4, "Fyra hörn ska synas på kurvmodulen.");
    const length = (i) => Math.hypot(corners[(i + 1) % 4][0] - corners[i][0], corners[(i + 1) % 4][1] - corners[i][1]);
    const longSides = [0, 1, 2, 3].sort((a, b) => length(b) - length(a)).slice(0, 2);
    const outer = longSides.sort((a, b) => length(b) - length(a))[0];
    if ((await sideOf(page, "cad-fotokant1")) !== outer) await page.locator(`svg.cad-fotobild line[data-sida="${outer}"]`).click();
    check((await sideOf(page, "cad-fotokant1")) === outer, "Kant 1 ska vara den yttre långsidan.");
    const proposed = await sideOf(page, "cad-fotogavela");
    const other = (proposed + 2) % 4;
    await page.locator(`svg.cad-fotobild line[data-sida="${other}"]`).click();
    check((await sideOf(page, "cad-fotogavela")) === other, "Gavel A ska vara den gavel som trycktes på.");
    await page.getByText("Speglad: från gavel A längs Kant 1 ligger modulen till vänster, sett ovanifrån.").waitFor();
    await shot(page, "31-kurvmodul-kant1-och-gavel-a");

    // 3. Läs av med AI (ja:et gavs i foto.mjs).
    await page.getByRole("button", { name: "Läs av med AI · 12 tokens" }).click();
    await page.getByRole("heading", { name: "Spårplanen" }).waitFor({ timeout: 120_000 });
    check((await page.getByText("Kurvans kanter stämmer inte med fotot").count()) === 0, "Kurvans kanter ska vara cirkelbågar.");
    await page.getByRole("heading", { name: "Kant 1 och gavel A" }).waitFor();
    await shot(page, "32-kurvmodul-avlast");

    // 4. Spår 2 vid gavlarna ur fotot, och sedan byts gavel A och B utan kostnad.
    for (let i = 0; i < 2; i++) {
      const use = page.getByRole("button", { name: /^Använd 19\d(,\d)?$/ }).first();
      if ((await use.count()) === 0) break;
      await use.click();
      await page.getByRole("heading", { name: "Foto och kontroll" }).waitFor();
      await page.waitForLoadState("networkidle");
    }
    const balance = async () => Number(((await page.locator(".cad-saldo").first().textContent()) ?? "").replace(/[^\d]/g, ""));
    const before = await balance();
    await page.getByRole("button", { name: "Byt gavel A och B" }).click();
    await page.getByText("Modulen ligger till höger om Kant 1 från gavel A, som CAD ritar den.").waitFor({ timeout: 60_000 });
    await page.waitForLoadState("networkidle");
    check((await balance()) === before, "Att byta gavel A och B ska inte kosta något.");
    await shot(page, "33-kurvmodul-bytt-gavel");

    // 5. Ritningen: bågar över mätbilden, och spårplanen godkänns.
    await page.getByRole("link", { name: "Rätta i ritningen" }).click();
    await page.getByRole("heading", { name: "Ritningen", exact: true }).waitFor();
    await page.locator("svg.cad-duk-yta image.cad-fotolager").waitFor();
    await page.waitForLoadState("networkidle");
    await shot(page, "34-kurvmodul-ritningen");
    await page.getByText("Inget att kolla. Spårplanen kan godkännas.").waitFor();
    await page.getByRole("button", { name: "✓ Godkänn spårplanen" }).click();
    await page.getByText(/✓ Godkänd/).first().waitFor();
  } finally {
    curve.done();
  }

  // --- Modul ur en skiss ----------------------------------------------------------------------
  const sketch = synthetic("skiss", "skiss.jpg");
  try {
    // 6. Ny modul → Från en skiss.
    await page.goto(`${base}/moduler/ny`);
    await page.getByRole("heading", { name: "Ny modul", exact: true }).waitFor();
    await page.getByRole("link", { name: "Ladda upp skiss", exact: true }).click();
    await page.getByRole("heading", { name: "Ny modul ur en skiss" }).waitFor();
    await page.locator('input[name="skiss-namn"]').fill("Depå ur skiss");
    await page.locator('input[name="skiss-langd"]').fill("1500");
    await page.locator('input[name="skiss-bredd"]').fill("600");
    await page.locator('input[name="skiss"]').setInputFiles(sketch.file);
    await shot(page, "35-skiss-ladda-upp");
    await page.getByRole("button", { name: "Ladda upp skissen", exact: true }).click();

    // 7. Ramen till vänster, Kant 1 upptill och gavel A till vänster.
    await page.getByRole("heading", { name: "Foto och kontroll" }).waitFor({ timeout: 60_000 });
    await page.getByText("2 ramar hittade, välj modulens").waitFor();
    const left = async () => Math.min(...(await cornersOnPhoto(page)).map((c) => c[0]));
    await page.getByRole("radio", { name: "Ram 1" }).click();
    const first = await left();
    await page.getByRole("radio", { name: "Ram 2" }).click();
    const second = await left();
    if (first < second) await page.getByRole("radio", { name: "Ram 1" }).click();
    await page.getByText("Från gavel A längs Kant 1 ligger modulen till höger, sett ovanifrån.").waitFor();
    await shot(page, "36-skiss-ram-och-kant1");

    // 8. Läs av med AI: bara de två partier koden inte kan avgöra.
    await page.getByRole("button", { name: "Läs av med AI · 12 tokens" }).click();
    await page.getByRole("heading", { name: "Spårplanen" }).waitFor({ timeout: 120_000 });
    await page.getByText("Förslag ur skissen, ± 20 mm").first().waitFor();
    const facts = await page.locator(".cad-fakta-lista").first().textContent();
    check(/Växlar\s*3/.test(facts ?? ""), `Skissen ska ge tre växlar: ${facts}`);
    await shot(page, "37-skiss-avlast");
    await page.getByRole("link", { name: "Rätta i ritningen" }).click();
    await page.getByRole("heading", { name: "Ritningen", exact: true }).waitFor();
    await page.waitForLoadState("networkidle");
    await shot(page, "38-skiss-ritningen");
  } finally {
    sketch.done();
  }
}
