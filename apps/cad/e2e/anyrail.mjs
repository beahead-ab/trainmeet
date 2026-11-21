// Webbläsarprovet för Import från AnyRail (#91), körs från bibliotek.mjs med samma inloggade sida.
// En syntetisk AnyRail-fil (cad/tests/anyrail_syntetisk.py, AnyRail 2.0:s XML-export) väljs under
// Ny modul › AnyRail. Sidan visar modulerna på ritningen, växlarna med den antagna gul, måtten med
// Fler mått hopfällt, kontrollerna och exporten. Den antagna växeln bekräftas, Skapa modulerna gör
// modulerna som utkast och en anläggning, anläggningen visar modulerna, och hela stationens DXF
// hämtas. Inget här är en riktig station.
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");

export async function anyrail(page, { base, shot, check }) {
  const started = Date.now();
  const file = join(mkdtempSync(join(tmpdir(), "anyrail-")), "Exempelstation.xml");
  execFileSync("uv", ["run", "--locked", "python", "-m", "cad.tests.anyrail_syntetisk", file], { cwd: ROOT, stdio: "inherit" });

  // Ny modul › AnyRail.
  await page.goto(`${base}/moduler/ny`);
  await page.getByRole("link", { name: "AnyRail", exact: true }).click();
  await page.getByRole("heading", { name: "Import från AnyRail" }).waitFor();
  await page.locator('input[name="fil"]').setInputFiles(file);

  // Förslaget: sex moduler på ritningen, fyra växlar varav en antagen och gul.
  await page.getByText("74 delar · 6 moduler · 4 växlar, varav 1 antagna · 1 korsningar").waitFor();
  check((await page.locator("svg.cad-anyrail-bild .cad-skiva").count()) === 6, "Ritningen ska visa sex moduler.");
  check((await page.locator("svg.cad-anyrail-bild .cad-anyrail-vaxel.antagen").count()) === 1, "Den antagna växeln ska vara gul på ritningen.");
  for (const number of ["1", "2a", "2b", "3", "Ä1", "Ä2"]) {
    check(await page.getByLabel(`Namn på modul ${number}`).isVisible(), `Modul ${number} saknas.`);
  }
  check(!(await page.locator('input[name="crossing_angle"]').isVisible()), "Fler mått ska vara hopfällt.");
  check(await page.locator('input[name="track_width"]').isVisible(), "Spårbredden ska synas.");
  await page.locator('li.antagen[data-vaxel="4"]').waitFor();
  await shot(page, "40-anyrail-forslag");

  // Fler mått fälls ut; måtten läses om med förvalen.
  await page.getByText("Fler mått").click();
  await page.locator('input[name="crossing_angle"]').waitFor();
  check((await page.locator('input[name="tight_radius"]').inputValue()) === "400", "Den snäva radien ska vara 400 mm.");
  await shot(page, "41-anyrail-fler-matt");

  // Den antagna växeln bekräftas (AR3).
  await page.getByLabel("Bekräfta växel 4").check();
  await page.getByText("Alla antagna växlar är bekräftade.").waitFor();
  check(!(await page.locator("svg.cad-anyrail-bild .cad-anyrail-vaxel.antagen").count()), "Den bekräftade växeln är fortfarande gul.");

  // Hela stationens DXF hämtas.
  const [download] = await Promise.all([page.waitForEvent("download"), page.getByRole("link", { name: "DXF, hela stationen" }).click()]);
  const saved = join(dirname(file), download.suggestedFilename());
  await download.saveAs(saved);
  check(download.suggestedFilename() === "exempelstation-anlaggning.dxf", `DXF-filen heter ${download.suggestedFilename()}.`);
  const dxf = readFileSync(saved, "latin1");
  check(dxf.startsWith("  0\r\nSECTION") && dxf.includes("ANYRAIL-RITNING"), "DXF:en är inte hela stationen.");

  // Skapa modulerna: utkast i biblioteket och en anläggning.
  await page.getByRole("button", { name: "Skapa modulerna" }).click();
  await page.getByRole("heading", { name: "Modulerna är skapade" }).waitFor();
  await shot(page, "42-anyrail-skapade");
  await page.locator(".cad-anyrail-skapa").getByRole("link", { name: "Exempelstation" }).click();
  await page.getByRole("heading", { name: "Exempelstation", exact: true }).waitFor();
  for (const name of ["Modul 1", "Modul 2a", "Modul 2b", "Modul 3", "Ändmodul Ä1", "Ändmodul Ä2"]) {
    await page.locator("li[data-modul]", { hasText: name }).first().waitFor();
  }
  check((await page.locator("svg.cad-anl-bild .cad-skiva").count()) === 6, "Anläggningen ska visa sex moduler.");
  await page.getByText("utkast", { exact: false }).first().waitFor();
  await shot(page, "43-anyrail-anlaggningen");
  console.log(`AnyRail-provet tog ${((Date.now() - started) / 1000).toFixed(1)} s.`);
}
