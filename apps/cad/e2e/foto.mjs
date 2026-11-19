// Webbläsarprovet för Foto och kontroll (#89 del c1), efter Ritningen i bibliotek.mjs och i samma
// webbläsare: CI-steget kör bibliotek.mjs, som kör det här. CAD:s låtsade ID har en låtsad mätare och
// AI (cad/prov_webblasare.py): AI:n svarar som om fotot vore det syntetiska stationsfotot.
//
// 1. Ett syntetiskt foto av en station görs av bildkedjans egen renderare (cad/bildkedjan/syntetisk.py,
//    med perspektiv, linsfel, brus, ojämnt ljus och en skugga) och laddas upp som en ny modul,
//    600 mm bred, med längden ur fotot.
// 2. Hörnen är hittade; Kant 1 sätts till den övre långsidan, där den är i fotot.
// 3. Priset syns: 12 tokens, och vad som skickas och till vem, första gången.
// 4. Fotot läses av med AI.
// 5. Längden ur fotot visas med sitt ± och sliperkontrollen. Osäkert parti: koden ser en korsning och
//    AI:n två växlar; ägaren svarar en korsning.
// 6. Ritningen visar spåren över fotot (Fotot under), märkta AI-förslag, och hur långt de ligger från
//    fotot; stickspårets ände är en stoppbock.
// 7. Spårplanen godkänns, och modulens Foto-flik visar mätbilden.
import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");

function syntheticPhoto() {
  // PROV_FOTO: a photo made beforehand; otherwise the chain's renderer makes one now.
  if (process.env.PROV_FOTO) return { file: process.env.PROV_FOTO, done: () => undefined };
  const dir = mkdtempSync(join(tmpdir(), "cad-foto-"));
  const file = join(dir, "station.jpg");
  execFileSync("uv", ["run", "--locked", "python", "-m", "cad.bildkedjan.syntetisk", "station", file], { cwd: ROOT, stdio: "inherit" });
  return { file, done: () => rmSync(dir, { recursive: true, force: true }) };
}

export async function foto(page, { base, shot, check }) {
  const photo = syntheticPhoto();
  try {
    // 1. Ny modul → Ladda upp foto.
    await page.goto(`${base}/moduler/ny`);
    await page.getByRole("heading", { name: "Ny modul", exact: true }).waitFor();
    await page.getByRole("link", { name: "Ladda upp foto", exact: true }).click();
    await page.getByRole("heading", { name: "Ny modul ur ett foto" }).waitFor();
    await page.locator('input[name="foto-namn"]').fill("Fotostation");
    await page.locator('input[name="foto-bredd"]').fill("600");
    await page.locator('input[name="foton"]').setInputFiles(photo.file);
    await page.getByText("12 tokens", { exact: true }).first().waitFor();
    await shot(page, "20-ladda-upp-foto");
    await page.getByRole("button", { name: "Ladda upp", exact: true }).click();

    // 2. Hörnen och Kant 1.
    await page.getByRole("heading", { name: "Foto och kontroll" }).waitFor({ timeout: 60_000 });
    await page.locator("svg.cad-fotobild circle.cad-fotohorn").nth(3).waitFor();
    check((await page.locator("svg.cad-fotobild circle.cad-fotohorn").count()) === 4, "Fyra hörn ska synas.");
    await page.getByText(/4 hörn hittade/).first().waitFor();
    const kantY = async () => Number(await page.locator("svg.cad-fotobild .cad-fototexter text").first().getAttribute("y"));
    const before = await kantY();
    await page.getByRole("button", { name: "Andra långsidan" }).click();
    check((await kantY()) < before, "Kant 1 ska ha flyttat till den övre långsidan.");

    // 3. Priset och vad som skickas, första gången.
    await page.getByText("Jag godkänner att mätbilden skickas till").waitFor();
    const read = page.getByRole("button", { name: "Läs av med AI · 12 tokens" });
    check(await read.isDisabled(), "Läs av med AI ska vänta på ja:et första gången.");
    await page.locator('input[name="samtycke"]').check();
    await shot(page, "21-horn-och-pris");

    // 4. Läs av.
    await read.click();
    await page.getByRole("heading", { name: "Spårplanen" }).waitFor({ timeout: 120_000 });
    await page.getByText("Skala från spårvidden").first().waitFor();
    await page.getByText("Med AI-spåren").waitFor();
    check((await page.locator("svg.cad-fotobild path.cad-aispar").count()) >= 3, "AI-spåren syns inte över fotot.");
    await page.getByText("1 parti att kontrollera innan spårplanen kan godkännas.").waitFor();
    await shot(page, "22-foto-och-kontroll");

    // 5a. Längden ur fotot.
    await page.getByRole("link", { name: /^Längden ur fotot: \d+ mm ±/ }).click();
    await page.getByRole("heading", { name: "Längden ur fotot" }).waitFor();
    await page.getByText("Sliperdelning, raka spår").waitFor();
    const length = Number((await page.locator(".cad-stortal b").textContent()) ?? "0");
    check(Math.abs(length - 1500) <= 3, `Längden ur fotot ska vara nära 1500 mm, inte ${length}.`);
    await shot(page, "23-langden-ur-fotot");
    await page.getByRole("button", { name: /^✓ Använd \d+ mm$/ }).click();
    await page.getByRole("heading", { name: "Foto och kontroll" }).waitFor();

    // 5b. Osäkert parti: korsning eller två växlar?
    await page.getByRole("link", { name: "Svara", exact: true }).click();
    await page.getByRole("heading", { name: "Ett parti att kontrollera" }).waitFor();
    await page.getByText("Två växlar", { exact: true }).waitFor();
    await page.getByText("Ta en närbild av partiet").waitFor();
    await shot(page, "24-osakert-parti");
    await page.getByRole("radio", { name: /En korsning/ }).check();
    await page.getByRole("button", { name: "✓ Spara: en korsning" }).click();
    await page.getByRole("heading", { name: "Foto och kontroll" }).waitFor();
    await page.locator("text=parti att kontrollera").waitFor({ state: "detached" });

    // 6. Ritningen med fotot under.
    await page.getByRole("link", { name: "Rätta i ritningen" }).click();
    await page.getByRole("heading", { name: "Ritningen", exact: true }).waitFor();
    await page.locator("svg.cad-duk-yta image.cad-fotolager").waitFor();
    check((await page.getByRole("tab", { name: "Fotot under" }).getAttribute("aria-selected")) === "true", "Fotot under ska vara valt.");
    await page.getByText("AI-förslag", { exact: true }).first().waitFor();
    await page.getByText(/Avviker från fotot: median [\d,]+ mm, högst [\d,]+ mm/).waitFor();
    await page.waitForLoadState("networkidle");
    await shot(page, "25-ritningen-fotot-under");

    // 7. Stickspårets ände är en stoppbock, och spårplanen godkänns.
    await page.getByRole("button", { name: "Det är en stoppbock" }).click();
    await page.getByText("Inget att kolla. Spårplanen kan godkännas.").waitFor();
    await page.getByRole("button", { name: "✓ Godkänn spårplanen" }).click();
    await page.getByText(/✓ Godkänd/).first().waitFor();
    await page.goto(`${base}${new URL(page.url()).pathname.replace(/\/ritningen$/, "")}/foto`);
    await page.getByRole("heading", { name: "Mätbilden" }).waitFor();
    await page.getByText("Ja, TrainMeet får använda mätbilden").waitFor();
    // Approved: the original is gone (CAD4), the measuring image stays.
    await page.getByText("Originalet är borttaget. Mätbilden finns kvar.").waitFor();
    await shot(page, "26-foto-fliken");
  } finally {
    photo.done();
  }
}
