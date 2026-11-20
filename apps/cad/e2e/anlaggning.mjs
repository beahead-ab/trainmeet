// Webbläsarprovet för Anläggningar och Till TKL Studio (#89 del d2), körs från bibliotek.mjs med
// samma inloggade sida. Två syntetiska raka moduler med MMM:s gavel görs och godkänns genom CAD:s
// API, en anläggning skapas på sidan, modulerna läggs till gavel mot gavel och skarven passar. En
// skarv som inte sluter visas röd med skälet och tas bort. Till TKL Studio visar förhandsvisningen,
// verklighetstrogen och mörk, vad som följer med och hur anläggningen kopplas till en station i TKL.
// Inget här är en riktig station.

const API = "/api/cad/1";

async function approvedModule(page, base, name) {
  const made = await page.request.post(`${base}${API}/modules`, {
    data: {
      name,
      scale: "H0",
      shape: { kind: "straight", length: 1500, width: 500 },
      gables: [
        { end: "A", profile: "h0-mmm-enkelspar", tracks: [140] },
        { end: "B", profile: "h0-mmm-enkelspar", tracks: [140] },
      ],
    },
  });
  if (!made.ok()) throw new Error(`Modulen ${name} gick inte att göra: ${made.status()} ${await made.text()}`);
  const module = await made.json();
  const approved = await page.request.post(`${base}${API}/modules/${module.id}/approve`, { data: { version: 1 } });
  if (!approved.ok()) throw new Error(`Modulen ${name} gick inte att godkänna.`);
  return module;
}

export async function anlaggning(page, { base, shot, check }) {
  const first = await approvedModule(page, base, "Provrak 1");
  const second = await approvedModule(page, base, "Provrak 2");

  // Ny anläggning.
  await page.goto(`${base}/anlaggningar`);
  await page.getByRole("heading", { name: "Anläggningar", exact: true }).waitFor();
  await page.locator('input[name="anlaggning"]').fill("Provanläggning");
  await page.getByRole("button", { name: "Skapa anläggningen" }).click();
  await page.getByRole("heading", { name: "Provanläggning", exact: true }).waitFor();

  // Den första modulen, sedan den andra åt samma håll: dess gavel A mot den förstas gavel B.
  const add = page.getByRole("form", { name: "Lägg till modul" });
  await add.locator('select[name="modul"]').selectOption(first.id);
  await add.getByRole("button", { name: "Lägg till" }).click();
  await page.locator(`li[data-modul="${first.id}"]`).waitFor();
  await add.locator('select[name="modul"]').selectOption(second.id);
  await add.locator('select[name="vid"]').selectOption(`${first.id}:B`);
  await add.locator('select[name="hall"]').selectOption("samma");
  await add.getByRole("button", { name: "Lägg till" }).click();
  await page.locator(`li[data-modul="${second.id}"]`).waitFor();
  await page.getByText("✓ Passar").waitFor();
  await page.getByText("Klar för Studio").first().waitFor();
  check((await page.locator("svg.cad-anl-bild .cad-fri-gavel").count()) === 2, "De två fria gavlarna syns inte.");
  check(await page.locator(`li[data-modul="${second.id}"]`).getByText("version 1").isVisible(), "Den låsta versionen syns inte.");
  await shot(page, "10-anlaggning");

  // En skarv mellan de två fria gavlarna sluter inte: röd, med skälet, och anläggningen går inte till Studio.
  const join = page.getByRole("form", { name: "Skarva två gavlar" });
  await join.getByRole("button", { name: "Skarva" }).click();
  await page.getByText("Passar inte").waitFor();
  await page.getByText("Det här hindrar anläggningen från Studio").waitFor();
  await page.locator("svg.cad-anl-bild .cad-skarv-fel").waitFor();
  await shot(page, "11-skarv-som-inte-passar");
  await page.locator('li[data-skarv="1"]').getByRole("button", { name: "Ta bort skarven" }).click();
  await page.getByText("Klar för Studio").first().waitFor();
  check(!(await page.getByText("Passar inte").count()), "Skarven som inte passade finns kvar.");

  // Till TKL Studio: förhandsvisningen, vad som följer med och hur den kopplas till en station.
  await page.getByRole("link", { name: "Till TKL Studio" }).click();
  await page.getByRole("heading", { name: "Till TKL Studio", exact: true }).waitFor();
  await page.getByText("Det här följer med").waitFor();
  await page.getByText("2 spårbitar · 3 m spår").waitFor();
  await page.getByText("2 spår vid fria gavlar · blir linjeutfarter i Studio").waitFor();
  await page.getByText("CAD skapar aldrig en station.", { exact: false }).waitFor();
  check(await page.locator("svg.cad-anl-bild.realistisk").isVisible(), "Den verklighetstrogna förhandsvisningen syns inte.");
  await shot(page, "12-till-tkl-studio");
  await page.getByRole("button", { name: "Mörk" }).click();
  await page.locator("svg.cad-anl-bild.mork").waitFor();
  await shot(page, "13-till-tkl-studio-mork");

  // Modulens sida: Används i anläggningen.
  await page.goto(`${base}/moduler/${first.id}`);
  await page.locator(".cad-anvands").getByText("Provanläggning").waitFor();
}
