// Webbläsarprovet för CAD i mobilen (#90): Fota med mobilen på datorn och flödet i en telefon. Körs från
// bibliotek.mjs med datorns sida, inloggad som Provkonto A, och går också att köra ensamt:
//
//   CHROME_PATH=/usr/bin/google-chrome PROV_ADRESS=http://127.0.0.1:8095 node apps/cad/e2e/mobil.mjs
//
// 1. Datorn: Ny modul › Fota med mobilen visar en QR-kod. Provet läser länken under den, med koden i
//    fragmentet.
// 2. Telefonen är en egen Chrome som en Pixel 7 (Playwrights beskrivning), med en låtsad kamera: det
//    syntetiska stationsfotot ur bildkedjans renderare som kamerans ström (cad/prov_kamera.py). Den
//    öppnar länken utan att logga in; koden försvinner ur adressen och gäller inte igen.
// 3. 0 Välj väg › Fota modulen, 1 Mått utan längd, 2 Gavlar mätta spår för spår, olika i A och B.
// 4. 3 Fota: fotohjälpen hittar modulens fyra hörn i strömmen, vattenpasset visar telefonens lutning,
//    allt blir grönt och bilden tas av sig själv i full upplösning. Hörnen som handtag, Kant 1 på den
//    övre långsidan, priset och ja:et, och Läs av med AI.
// 5. 4 Kontroll: längden ur fotot, AI:n frågar om ett osäkert parti (4b: en korsning), stickspårets
//    stoppbock, och Godkänn spårplanen. 5 Klart.
// 6. Datorn har följt med hela vägen och visar resultatet; Klar i mobilen avslutar telefonens session.
// 7. Från modulens sida gäller koden bara modulen och går direkt till 3 Fota; datorn avslutar den.
import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium, devices } from "playwright-core";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");

function fakeCamera() {
  const dir = mkdtempSync(join(tmpdir(), "cad-kamera-"));
  const file = join(dir, "kamera.mjpeg");
  execFileSync("uv", ["run", "--locked", "python", "-m", "cad.prov_kamera", file], { cwd: ROOT, stdio: "inherit" });
  return { file, done: () => rmSync(dir, { recursive: true, force: true }) };
}

export async function mobil(page, { base, shot, check, chrome }) {
  const started = Date.now();
  const camera = fakeCamera();
  const phoneBrowser = await chromium.launch({
    executablePath: chrome || undefined,
    args: ["--no-sandbox", "--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream", `--use-file-for-fake-video-capture=${camera.file}`],
  });
  const problems = [];
  try {
    // 1. Datorn: Fota med mobilen.
    await page.goto(`${base}/moduler/ny`);
    await page.getByRole("heading", { name: "Ny modul", exact: true }).waitFor();
    await page.getByRole("button", { name: "Visa QR-koden" }).click();
    await page.getByRole("img", { name: "QR-kod till CAD i mobilen" }).waitFor();
    await page.getByText("Väntar på mobilen …").waitFor();
    await page.getByText("Går det inte att skanna?").click();
    const link = await page.locator("[data-mobil-lank]").getAttribute("href");
    check(link && new URL(link).pathname === "/m" && /^#k=[\w-]{32,}$/.test(new URL(link).hash), `QR-länken ska ha koden i fragmentet, inte ${link}.`);
    await shot(page, "40-dator-fota-med-mobilen");

    // 2. Telefonen öppnar länken, utan inloggning.
    const context = await phoneBrowser.newContext({
      ...devices["Pixel 7"],
      locale: "sv-SE",
      colorScheme: "light",
      permissions: ["camera", "accelerometer", "gyroscope", "magnetometer"],
    });
    const phone = await context.newPage();
    phone.on("pageerror", (error) => problems.push(String(error)));
    phone.on("console", (message) => {
      if (message.type() === "error") problems.push(message.text());
    });
    const mshot = async (name) => {
      await phone.screenshot({ path: shot.dir ? join(shot.dir, `${name}.png`) : undefined, fullPage: false });
    };
    await phone.goto(link);
    await phone.getByRole("heading", { name: "Hur vill du börja?" }).waitFor();
    check(!new URL(phone.url()).hash, "Koden ska vara borta ur telefonens adress.");
    check(await phone.getByText(/Du har \d+ tokens kvar\./).isVisible(), "Saldot syns inte i mobilen.");
    await phone.getByText("Inloggad som Provkonto A.").waitFor();
    await mshot("41-mobil-0-valj-vag");
    await page.getByText("Öppnad i mobilen").waitFor();
    // Once: the same link again is refused, and says how to go on.
    const again = await context.newPage();
    await again.goto(link);
    await again.getByRole("heading", { name: "Koden gäller inte" }).waitFor();
    await again.close();

    // 3. 0 Välj väg › 1 Mått › 2 Gavlar.
    await phone.getByRole("button", { name: /Fota modulen/ }).click();
    await phone.locator('input[name="mobil-namn"]').fill("Mobilstation");
    await phone.locator('input[name="mobil-bredd"]').fill("600");
    check((await phone.locator('input[name="mobil-langd"]').getAttribute("placeholder")) === "ur fotot", "Längden ska kunna lämnas tom.");
    await phone.getByText("Lämna längden tom, så räknas den fram ur fotot.", { exact: false }).waitFor();
    await mshot("42-mobil-1-matt");
    await phone.getByRole("button", { name: "Nästa: gavlarna →" }).click();
    await page.getByText("Steg 2 Gavlar").waitFor();
    await phone.getByRole("button", { name: "Egen gavel – mät spår för spår" }).click();
    const steps = async (end, values) => {
      for (let i = 0; i < values.length; i += 1) {
        if (i > 0 && !(await phone.locator(`input[name="mobil-gavel-${end}-${i}"]`).count()))
          await phone.getByRole("button", { name: "+ Lägg till spår" }).click();
        await phone.locator(`input[name="mobil-gavel-${end}-${i}"]`).fill(String(values[i]));
      }
    };
    await steps("A", [140, 57, 253]);
    await phone.getByText("Spår 3 är 450 mm från Kant 1").waitFor();
    await phone.getByRole("tab", { name: /Gavel B/ }).click();
    await phone.locator('input[name="mobil-lika"]').uncheck();
    await phone.getByRole("button", { name: "Egen gavel – mät spår för spår" }).click();
    await steps("B", [140, 57, 63]);
    await phone.getByText("Spår 3 är 260 mm från Kant 1").waitFor();
    await mshot("43-mobil-2-gavlar");
    // The phone's orientation as DeviceOrientation reports it, from before the camera opens.
    const tilt = (beta) =>
      phone.evaluate((b) => {
        window.clearInterval(window.__lutning);
        const send = () => window.dispatchEvent(new DeviceOrientationEvent("deviceorientation", { alpha: 0, beta: b, gamma: 1 }));
        send();
        window.__lutning = window.setInterval(send, 100);
      }, beta);
    await tilt(35);
    await phone.getByRole("button", { name: "Nästa: fota modulen →" }).click();

    // 4. 3 Fota: the photo help on the fake camera's stream, and the photo taken by itself.
    await phone.getByRole("heading", { name: "Fota uppifrån" }).waitFor();
    // The module is found in the stream at once; the photo waits for the level.
    await phone.getByText("✓ 4 av 4 hörn i bild").waitFor({ timeout: 30_000 });
    await phone.locator('.mob-lampor li[data-lampa="ram"].ok').waitFor();
    const level = phone.getByRole("button", { name: "Slå på vattenpasset" });
    if (await level.isVisible()) {
      // As on an iPhone, the page asks before it reads the phone's orientation.
      await phone.getByText("Slå på vattenpasset, så att bilden blir tagen rakt ovanifrån.").waitFor();
      await level.click();
    }
    // The phone held 35° from flat: the level is red and the photo waits.
    await phone.getByText(/Håll telefonen plant, rakt ovanför modulen. Nu 35° snett./).waitFor();
    await phone.locator('.mob-lampor li[data-lampa="vinkel"].warn').waitFor();
    for (const light of ["ram", "skarpa", "ljus", "stilla"]) await phone.locator(`.mob-lampor li[data-lampa="${light}"].ok`).waitFor();
    await mshot("44-mobil-3-fota-vattenpasset");
    // Then held flat over the middle: everything green, and the photo is taken by itself.
    await tilt(4);
    // Everything green: the photo is taken and sent, and the corners come back.
    await phone.getByRole("heading", { name: "Hörnen och Kant 1" }).waitFor({ timeout: 60_000 });
    await page.getByText("Steg 3 Fota").waitFor();
    await page.getByText(/Mobilstation · M-\d+/).waitFor();
    check((await phone.locator("svg.mob-foto circle.cad-fotohorn").count()) === 4, "Fyra hörn ska vara handtag.");
    await phone.getByText("✓ 4 av 4 hörn hittade").waitFor();
    const kantY = async () => Number(await phone.locator("svg.mob-foto .cad-fototexter text").first().getAttribute("y"));
    const before = await kantY();
    await phone.getByRole("button", { name: "Andra långsidan som Kant 1" }).click();
    check((await kantY()) < before, "Kant 1 ska ha flyttat till den övre långsidan.");
    // The magnifier while a corner is dragged.
    const handle = await phone.locator("svg.mob-foto circle.cad-fotohorn").first().boundingBox();
    await phone.mouse.move(handle.x + handle.width / 2, handle.y + handle.height / 2);
    await phone.mouse.down();
    await phone.mouse.move(handle.x + handle.width / 2 + 1, handle.y + handle.height / 2 + 1);
    await phone.getByRole("img", { name: "Luppen" }).waitFor();
    await mshot("45-mobil-3-horn-lupp");
    await phone.mouse.up();
    const read = phone.getByRole("button", { name: "Läs av med AI · 12 tokens" });
    // The first time, the yes to what is sent; after Foto och kontroll on the computer it is given.
    const yes = phone.locator('input[name="mobil-samtycke"]');
    if (await yes.count()) {
      check(await read.isDisabled(), "Läs av med AI ska vänta på ja:et första gången.");
      await yes.check();
    }
    await phone.getByText("12 tokens", { exact: true }).first().scrollIntoViewIfNeeded();
    await mshot("46-mobil-3-pris");
    await read.click();

    // 5. 4 Kontroll, 4b AI:n frågar, the buffer stop, Godkänn spårplanen.
    await phone.getByRole("button", { name: "Godkänn spårplanen" }).waitFor({ timeout: 120_000 });
    await phone
      .getByText(/mått stämmer/)
      .first()
      .waitFor();
    await page.getByText("Steg 4 Kontroll").waitFor();
    await phone.getByRole("heading", { name: "Längden ur fotot" }).waitFor();
    const length = Number(((await phone.locator(".cad-stortal b").textContent()) ?? "0").replace(",", "."));
    check(Math.abs(length - 1500) <= 6, `Längden ur fotot ska vara nära 1500 mm, inte ${length}.`);
    await phone.getByText("AI:n frågar om 1 parti").waitFor();
    check(await phone.getByRole("button", { name: "Godkänn spårplanen" }).isDisabled(), "Godkänn ska vänta på svaret.");
    await mshot("47-mobil-4-kontroll");
    const use = phone.getByRole("button", { name: /^Använd \d+ mm$/ });
    if (await use.count()) {
      await use.click();
      await phone.getByText("✓ Modulen har längden ur fotot.").waitFor();
    }
    await phone.getByRole("button", { name: "Svara", exact: true }).click();
    await phone.getByRole("heading", { name: "AI:n frågar", exact: true }).waitFor();
    await phone.getByText("Fråga 1 av 1").waitFor();
    await phone.getByText("Ta en närbild i stället · 12 tokens").waitFor();
    await page.getByText("Steg 4b AI:n frågar").waitFor();
    await phone.getByRole("radio", { name: /En korsning/ }).check();
    await mshot("48-mobil-4b-fragar");
    await phone.getByRole("button", { name: "Spara svaret →" }).click();
    await phone.getByRole("button", { name: "Godkänn spårplanen" }).waitFor();
    await phone.locator("text=AI:n frågar om").waitFor({ state: "detached" });
    // Att kolla: the siding's end is a buffer stop, and the gables' tracks stay where the owner
    // measured them; answered on the phone and sent with Godkänn spårplanen.
    await phone.getByRole("radio", { name: "Det är en stoppbock" }).click();
    const keep = phone.getByRole("radio", { name: "Behåll läget" });
    for (let i = 0; i < (await keep.count()); i += 1) await keep.nth(i).click();
    await phone.getByRole("radio", { name: "Det är en stoppbock" }).scrollIntoViewIfNeeded();
    await mshot("49-mobil-4-att-kolla");
    await phone.getByRole("button", { name: "Godkänn spårplanen" }).click();
    await phone.getByRole("heading", { name: "Modulen är godkänd" }).waitFor({ timeout: 30_000 });
    await phone.getByText("tokens använda").waitFor();
    await mshot("50-mobil-5-klart");

    // 6. The computer followed: the result, and the phone's session ends.
    await page.getByText("Steg 5 Klart").waitFor();
    await page.getByText(/Mobilstation · M-\d+ · godkänd/).waitFor();
    await page.getByRole("link", { name: "Foto och kontroll" }).waitFor();
    await shot(page, "51-dator-foljde-mobilen");
    await phone.getByRole("button", { name: "Klar i mobilen" }).click();
    await phone.getByRole("heading", { name: "Klart i mobilen" }).waitFor();
    await page.getByText("Mobilen är klar").waitFor();
    await page.getByRole("link", { name: "Foto och kontroll" }).click();
    await page.getByRole("heading", { name: "Foto och kontroll" }).waitFor();

    // 7. From the module's page: a code for a photo of this module only, straight to 3 Fota.
    await page.goto(`${new URL(page.url()).origin}${new URL(page.url()).pathname.replace(/\/foto\/[^/]+$/, "")}/foto`);
    await page.getByRole("heading", { name: "Fota med mobilen" }).waitFor();
    await page.getByRole("button", { name: "Fota med mobilen" }).click();
    await page.getByText("Går det inte att skanna?").click();
    const bound = await page.locator("[data-mobil-lank]").getAttribute("href");
    const second = await context.newPage();
    second.on("pageerror", (error) => problems.push(String(error)));
    await second.goto(bound);
    await second.getByRole("heading", { name: "Fota uppifrån" }).waitFor();
    check(!(await second.getByText("Hur vill du börja?").count()), "En kod från modulens sida ska gå direkt till 3 Fota.");
    await page.getByText("Steg 3 Fota").waitFor();
    await page.getByRole("button", { name: "Avsluta i mobilen" }).click();
    await page.getByText("Mobilen är klar").waitFor();
    check(problems.length === 0, `Fel i telefonens webbläsare: ${problems.join(" | ")}`);
    console.log(`CAD i mobilen gick igenom på ${Math.round((Date.now() - started) / 1000)} s.`);
  } catch (error) {
    for (const context of phoneBrowser.contexts()) {
      for (const p of context.pages()) await p.screenshot({ path: shot.dir ? join(shot.dir, "fel-mobil.png") : undefined }).catch(() => undefined);
    }
    if (problems.length) console.error(`Fel i telefonens webbläsare: ${problems.join(" | ")}`);
    throw error;
  } finally {
    await phoneBrowser.close();
    camera.done();
  }
}

// Alone: log in on the computer with the trial login, then the phone's flow.
if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  const base = (process.env.PROV_ADRESS ?? "http://127.0.0.1:8095").replace(/\/+$/, "");
  const dir = process.env.PROV_BILDER ?? "";
  if (dir) mkdirSync(dir, { recursive: true });
  const shot = async (page, name) => {
    if (!dir) return;
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: join(dir, `${name}.png`), fullPage: true });
  };
  shot.dir = dir;
  const check = (condition, message) => {
    if (!condition) throw new Error(message);
  };
  const chrome = process.env.CHROME_PATH ?? "";
  const browser = await chromium.launch({ executablePath: chrome || undefined, args: ["--no-sandbox"] });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, locale: "sv-SE", colorScheme: "light" });
  try {
    await page.goto(`${base}/logga-in`);
    await page.getByRole("button", { name: "Provkonto A" }).click();
    await page
      .getByRole("heading", { name: /Moduler|Bygg ditt modulbibliotek/ })
      .first()
      .waitFor();
    await mobil(page, { base, shot, check, chrome });
  } finally {
    await browser.close();
  }
}
