// Webbläsarprovet för Ritningen och Lås mått (#89 del b), efter modulbiblioteket i bibliotek.mjs och
// i samma webbläsare: CI-steget kör bibliotek.mjs, som kör det här.
//
// 1. Exempelstationen öppnas och Ritning-fliken leder till Ritningen. Ett spår ritas från gavel A
//    till gavel B, ett till från 51 mm före gavel A, och ett från mitten av det första: en växel.
// 2. Växeln väljs och visas i växelinspektören, och får radien 300 mm. Att kolla frågar om rälsen
//    som slutar före gaveln och om växelns radie; Det är en passbit tar spåret dit, och växeltypen
//    R 830 ger radien. Ångra och Gör om, Flytta växel; Spara blir version 2.
// 3. En MMM-trapets 685 × 480/280 med Kant 1 förskjuten 131,5 mm görs, och Lås mått låser 140 mm i
//    båda gavlarna: kurvan blir rakt, båge, rakt, båge, rakt, och Använd geometrin sparar den.
// 4. Godkänn spårplanen: inget kvar att kolla, så version 2 godkänns.
// 5. Historiken visar de nya versionerna.

function photoLine() {
  // The photo test's line through the trapezoid, every 10 mm, wobbling by up to a millimetre as a
  // hand does: from gable A's track at 140 mm to gable B's, 131,5 mm further across.
  const parts = [
    [64, 0],
    [645 * ((19 * Math.PI) / 180), 1 / 645],
    [188, 0],
    [645 * ((19 * Math.PI) / 180), -1 / 645],
    [23.25, 0],
  ];
  const points = [[0, 140]];
  let [x, y, heading] = [0, 140, 0];
  for (const [length, curvature] of parts) {
    for (let done = 0; done < length; ) {
      const step = Math.min(2, length - done);
      heading += (curvature * step) / 2;
      x += Math.cos(heading) * step;
      y += Math.sin(heading) * step;
      heading += (curvature * step) / 2;
      done += step;
      if (Math.hypot(x - points[points.length - 1][0], y - points[points.length - 1][1]) >= 10) points.push([x, y + Math.sin(x / 37)]);
    }
  }
  points.push([685, 271.5]);
  return points;
}

async function onCanvas(page, point) {
  // The canvas draws in the module's millimetres; this is where a point lies on the screen.
  return page.evaluate(([x, y]) => {
    const group = document.querySelector("svg.cad-duk-yta > g");
    const m = group.getScreenCTM();
    return { x: m.a * x + m.c * y + m.e, y: m.b * x + m.d * y + m.f };
  }, point);
}

async function dragOn(page, from, to, steps = 12) {
  const a = await onCanvas(page, from);
  const b = await onCanvas(page, to);
  await page.mouse.move(a.x, a.y);
  await page.mouse.down();
  for (let i = 1; i <= steps; i += 1) {
    await page.mouse.move(a.x + ((b.x - a.x) * i) / steps, a.y + ((b.y - a.y) * i) / steps);
  }
  await page.mouse.up();
}

async function clickOn(page, point) {
  const a = await onCanvas(page, point);
  await page.mouse.click(a.x, a.y);
}

async function tool(page, name) {
  await page.getByRole("toolbar", { name: "Verktyg" }).getByRole("button", { name, exact: true }).click();
}

async function settled(page) {
  // Every change goes to CAD and back; wait until the last one is drawn.
  await page.waitForLoadState("networkidle");
}

export async function ritningen(page, { base, shot, check }) {
  // 1. Exempelstationen: FREMO dubbelspår vid A (330, 380) och tre egna spår vid B (245, 295, 345).
  await page.goto(`${base}/moduler`);
  await page.getByRole("link", { name: "Exempelstation" }).first().click();
  await page.getByRole("heading", { name: "Exempelstation" }).waitFor();
  await page.getByRole("link", { name: "Ritning", exact: true }).click();
  await page.getByRole("heading", { name: "Ritningen", exact: true }).waitFor();
  await page.locator("svg.cad-duk-yta").waitFor();

  await tool(page, "Rakt spår");
  await dragOn(page, [0, 330], [1500, 295]);
  await settled(page);
  await dragOn(page, [51, 380], [1500, 345]);
  await settled(page);
  await page.getByRole("heading", { name: /Rälsen slutar 51 mm före gavel A/ }).waitFor();
  // From the middle of the first track to gable B's first track: a switch.
  await dragOn(page, [700, 330 - (35 * 700) / 1500], [1500, 245]);
  await settled(page);
  await page.getByText("1 växel", { exact: true }).waitFor();
  check(await page.locator("[data-switch]").count() === 1, "Växeln syns inte i ritningen.");

  // The switch in the inspector; its radius set to 300 mm, the scale's lower limit.
  await tool(page, "Välj");
  const marker = await page.locator("[data-switch] circle").first().boundingBox();
  await page.mouse.click(marker.x + marker.width / 2, marker.y + marker.height / 2);
  await page.getByRole("heading", { name: "Växel 1", exact: true }).waitFor();
  await page.getByText(/spår från A1 mot B1/).waitFor();
  await page.locator("#vaxel-radie").fill("300");
  await page.locator("#vaxel-radie").press("Enter");
  await settled(page);
  await page.getByRole("heading", { name: /Växel 1: radien blev 300 mm/ }).waitFor();
  await page.getByText("⚠ 3 saker att kolla").waitFor();
  await shot(page, "10-ritningen");

  // 2. Att kolla: the rail short of gable A is a passbit, and the switch gets a known type.
  await page.getByRole("button", { name: "Det är en passbit" }).click();
  await settled(page);
  await page.getByRole("heading", { name: /Rälsen slutar 51 mm före gavel A/ }).waitFor({ state: "detached" });
  await page.getByRole("button", { name: "Välj växeltyp" }).click();
  await page.locator("#vaxel-typ").selectOption("h0-r830-114");
  await settled(page);
  await page.getByText("Inget att kolla. Spårplanen kan godkännas.").waitFor();
  check((await page.locator("#vaxel-radie").inputValue()) === "830", "Växeltypen ska ge radien 830 mm.");
  // Undo and redo the last change, then save.
  await page.locator("svg.cad-duk-yta").click({ position: { x: 5, y: 5 } });
  await page.keyboard.press("Control+z");
  await settled(page);
  await page.getByRole("heading", { name: /Växel 1: radien blev 300 mm/ }).waitFor();
  await page.keyboard.press("Control+Shift+z");
  await settled(page);
  await page.getByText("Inget att kolla. Spårplanen kan godkännas.").waitFor();
  // Flytta växel: the points slide 100 mm along their track toward gable B.
  await tool(page, "Flytta växel");
  await dragOn(page, [700, 330 - (35 * 700) / 1500], [800, 330 - (35 * 800) / 1500]);
  await settled(page);
  await page.getByText(/^8\d\d mm$/).first().waitFor();
  await page.getByRole("button", { name: "Spara", exact: true }).click();
  await page.getByText("Version 2", { exact: true }).waitFor();
  await page.getByText("Ritad", { exact: true }).waitFor();

  // 3. Lås mått on MMM's trapezoid, whose Kant 1 slants: the track at 140 mm in both gables bends.
  await page.goto(`${base}/moduler/ny/trapets`);
  await page.getByRole("heading", { name: "Ny trapetsmodul" }).waitFor();
  await page.locator('input[name="namn"]').fill("Trapets 480/280");
  await page.locator('input[name="forskjutning"]').fill("131,5");
  await page.locator('select[name="profil-A"]').selectOption("h0-mmm-enkelspar");
  await page.getByRole("button", { name: "Spara" }).click();
  await page.getByRole("heading", { name: "Trapets 480/280" }).waitFor();
  await page.getByRole("link", { name: "Ritning", exact: true }).click();
  await page.getByRole("heading", { name: "Ritningen", exact: true }).waitFor();
  await page.locator("svg.cad-duk-yta").waitFor();
  // The measures give a straight track across; the owner draws the curve by hand instead, with
  // Båge and Skift, as the photo test's line went: straight 64, R 645, straight 188 at 19°, R 645.
  await tool(page, "Välj");
  await clickOn(page, [342.5, 205.75]);
  await page.keyboard.press("Delete");
  await settled(page);
  // Utjämning Av keeps the hand's line as it is drawn, for Lås mått to fit.
  await page.getByRole("radiogroup", { name: "Utjämning" }).getByRole("radio", { name: "Av" }).click();
  await settled(page);
  await tool(page, "Båge");
  const line = photoLine();
  const first = await onCanvas(page, line[0]);
  await page.keyboard.down("Shift");
  await page.mouse.move(first.x, first.y);
  await page.mouse.down();
  for (const point of line.slice(1)) {
    const at = await onCanvas(page, point);
    await page.mouse.move(at.x, at.y);
  }
  await page.mouse.up();
  await page.keyboard.up("Shift");
  await settled(page);
  await page.getByText(/Avviker från de ritade linjerna/).waitFor();
  await page.getByRole("toolbar", { name: "Verktyg" }).getByRole("button", { name: "Lås mått" }).click();
  await page.getByRole("heading", { name: "Lås ett mått, räkna om kurvan" }).waitFor();
  await page.getByRole("cell", { name: "Rakt till gavel B" }).waitFor();
  for (const part of ["Rakt från gavel A", "Rakt till gavel B"]) await page.getByRole("cell", { name: part }).waitFor();
  check((await page.getByRole("cell", { name: "Båge", exact: true }).count()) === 2, "Kurvan ska ha två bågar.");
  check((await page.locator('input[name="las-A"]').inputValue()) === "140", "MMM:s 140 mm ska vara låst vid gavel A.");
  await page.getByText(/Kurvan räknas om till raka bitar och bågar/).waitFor();
  await page.getByText(/Avviker median/).waitFor();
  await page.getByLabel("Olika radier").check();
  await settled(page);
  await page.getByText(/Avviker median/).waitFor();
  await page.getByLabel("Samma radie i båda bågarna").check();
  await settled(page);
  await page.getByText(/Avviker median/).waitFor();
  await shot(page, "11-las-matt");
  await page.getByRole("button", { name: "✓ Använd geometrin" }).click();
  await page.getByRole("heading", { name: "Ritningen", exact: true }).waitFor();
  await page.getByText("Version 2", { exact: true }).waitFor();
  await page.getByText("Ritad", { exact: true }).waitFor();
  await settled(page);

  // 4. Godkänn spårplanen: nothing left to check.
  await page.getByText("Inget att kolla. Spårplanen kan godkännas.").waitFor();
  await shot(page, "12-ritningen-efter-las-matt");
  await page.getByRole("button", { name: "✓ Godkänn spårplanen" }).click();
  await page.getByText(/✓ Godkänd/).first().waitFor();

  // 5. The new versions in Historik.
  await page.getByRole("link", { name: "Trapets 480/280" }).first().click();
  await page.getByRole("heading", { name: "Trapets 480/280" }).waitFor();
  await page.getByText(/✓ Godkänd/).first().waitFor();
  await page.getByRole("link", { name: "Historik", exact: true }).click();
  await page.getByText("Version 2: spårplanen godkänd").waitFor();
  await page.getByText(/Version 2: ritningen sparad \(.*Lås mått\)/).waitFor();
  await shot(page, "13-historik");
}
