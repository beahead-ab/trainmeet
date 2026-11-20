// Webbläsarprovet för Landskapet och Exportera (#89 del d1), efter Foto och kontroll i bibliotek.mjs
// och i samma webbläsare: Fotostationen, som foto.mjs gjorde ur det syntetiska stationsfotot och
// godkände, får sitt landskap.
//
// 1. Landskap-fliken: inget landskap än; Gör landskapet ur mätbilden ger ytorna som ett förslag (orange).
// 2. Måla: en damm med verktyget Måla och ytan Vatten, dragen över gräset; Spara gör en ny version.
// 3. Godkänn landskapet: förslaget blir godkänt, och modulen är godkänd igen.
// 4. Exportera: valen syns; DXF:en hämtas och börjar med DXF:s huvud och har spårmitt som LINE, och
//    FREMO-ritningen hämtas med modulens namn; Skriv ut skriver ut arken.
import { readFileSync } from "node:fs";

export async function landskap(page, { base, shot, check }) {
  // 1. Fotostationen och dess Landskap-flik.
  await page.goto(`${base}/moduler`);
  await page.getByRole("heading", { name: "Moduler", exact: true }).waitFor();
  await page.locator("table.cad-tabell a.cad-namn", { hasText: "Fotostation" }).click();
  await page.getByRole("heading", { name: "Fotostation" }).waitFor();
  await page.getByRole("link", { name: "Landskap", exact: true }).click();
  await page.getByText("Modulen har inget landskap än.").waitFor();
  await page.getByRole("button", { name: "Gör landskapet ur mätbilden" }).click();
  await page.getByText("Förslag", { exact: true }).first().waitFor({ timeout: 60_000 });
  await page.getByText("Färgklustring av mätbilden").first().waitFor();
  await page.locator(".cad-ytlista").getByText("Gräs").waitFor();
  check((await page.locator("svg.cad-landskap-yta path.cad-forslagskant").count()) >= 1, "Förslaget ska ha orange kant.");
  await page.locator(".cad-rubrikrad").getByText("Utkast", { exact: true }).waitFor();
  check(await page.getByRole("button", { name: "Godkänn", exact: true }).isVisible(), "Landskapet ska göra en ny version, ett utkast.");
  await page.waitForLoadState("networkidle");
  await shot(page, "30-landskapet-forslag");

  // 2. Måla en damm på gräset, nära gavel A och långt från spåren.
  await page.getByRole("button", { name: "Måla", exact: true }).click();
  await page.getByRole("radio", { name: "Vatten" }).click();
  await page.locator('select[name="pensel"]').selectOption("40");
  const canvas = page.locator("svg.cad-landskap-yta");
  const box = await canvas.boundingBox();
  check(box !== null, "Landskapets yta syns inte.");
  const at = (x, y) => [box.x + box.width * x, box.y + box.height * y];
  const [x0, y0] = at(0.12, 0.84);
  const [x1, y1] = at(0.3, 0.84);
  await page.mouse.move(x0, y0);
  await page.mouse.down();
  for (let k = 1; k <= 12; k += 1) await page.mouse.move(x0 + ((x1 - x0) * k) / 12, y0 + ((y1 - y0) * k) / 12);
  await page.mouse.up();
  await page.getByText("1 ändring som inte är sparad").waitFor();
  await page.locator(".cad-ytlista").getByText("Vatten").waitFor();
  check((await page.locator('svg.cad-landskap-yta path[data-yta="water"]').count()) >= 1, "Dammen syns inte.");
  await page.getByRole("button", { name: "Spara", exact: true }).click();
  await page.locator("text=ändring som inte är sparad").waitFor({ state: "detached" });
  await page.waitForLoadState("networkidle");
  await shot(page, "31-landskapet-malat");

  // 3. Godkänn landskapet.
  await page.getByRole("button", { name: "✓ Godkänn landskapet" }).click();
  await page.getByText("✓ Godkänt", { exact: true }).waitFor();
  await page.getByText(/✓ Godkänd \d+ \w+ \d{4}/).first().waitFor();
  check(!(await page.locator("svg.cad-landskap-yta path.cad-forslagskant").count()), "Ett godkänt landskap ska inte vara orange.");
  await page.waitForLoadState("networkidle");
  await shot(page, "32-landskapet-godkant");

  // 4. Exportera.
  await page.getByRole("link", { name: "Exportera", exact: true }).click();
  await page.getByRole("heading", { name: "Exportera", exact: true }).waitFor();
  for (const choice of ["FREMO-ritning", "Moduldatabasen", "MMM", "DXF", "Utskrift"]) {
    await page.getByRole("heading", { name: choice, exact: true }).waitFor();
  }
  check(!(await page.getByText("märks Utkast").count()), "Den godkända versionen ska inte märkas Utkast.");
  await page.locator('input[name="dxf-rals"]').check();
  const [dxf] = await Promise.all([page.waitForEvent("download"), page.getByRole("link", { name: "Ladda ner DXF" }).click()]);
  const text = readFileSync(await dxf.path(), "latin1");
  const head = text.split(/\r?\n/).slice(0, 4).map((line) => line.trim());
  check(head.join(",") === "0,SECTION,2,HEADER", `DXF:en börjar inte med sitt huvud: ${head.join(",")}`);
  check(/\r?\n\s*0\r?\nLINE\r?\n\s*8\r?\nSPARMITT/.test(text), "DXF:en har ingen spårmitt som LINE.");
  check(text.includes("\nRALS\r") && text.includes("LANDSKAP-VATTEN"), "DXF:en saknar rälsen eller landskapet.");
  check(dxf.suggestedFilename().endsWith(".dxf"), `DXF:en heter ${dxf.suggestedFilename()}.`);
  const card = (name) => page.locator(".cad-exportval article").filter({ has: page.getByRole("heading", { name, exact: true }) });
  const fremoLink = card("FREMO-ritning").getByRole("link", { name: "Ladda ner SVG" });
  const [fremo] = await Promise.all([page.waitForEvent("download"), fremoLink.click()]);
  const sheet = readFileSync(await fremo.path(), "utf8");
  check(sheet.startsWith("<svg") && sheet.includes("FREMO-ritning") && sheet.includes("Fotostation"), "FREMO-ritningen saknar sitt innehåll.");
  await page.waitForLoadState("networkidle");
  await page.evaluate(() => {
    window.__utskrifter = 0;
    window.print = () => {
      window.__utskrifter += 1;
    };
  });
  await card("Utskrift").getByRole("button", { name: "Skriv ut" }).click();
  check((await page.evaluate(() => window.__utskrifter)) === 1, "Skriv ut skrev inte ut.");
  await shot(page, "33-exportera");
  await page.emulateMedia({ media: "print" });
  await shot(page, "34-utskriften");
  await page.emulateMedia({ media: "screen" });
}
