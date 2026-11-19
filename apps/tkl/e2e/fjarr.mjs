// Webbläsarprovet för fjärrstyrningen (#36 del c), i en riktig Chrome: en hubb med Provbanan,
// TKL B som fjärrställverk (ingen egen station) och station A, Åsen, på nivå 2 med en
// fjärrkatalog i Gårdsjös form.
//
//   PROV_HUBB=http://127.0.0.1:8080 PROV_TKL_FJARR=http://127.0.0.1:8093 PROV_TKL_GRANNE=http://127.0.0.1:8094 \
//     CHROME_PATH=/usr/bin/google-chrome node apps/tkl/e2e/fjarr.mjs
//
// PROV_HUBB är hubbens adress och PROV_TKL_FJARR fjärrställverkets TKL, båda nystartade;
// PROV_TKL_GRANNE en andra nystartad TKL, Norrbys, för grannen som fjärrstyr (FR3, valfri);
// PROV_HUBB_I_TKL hubbens adress som TKL når den, när TKL kör i en container (annars PROV_HUBB);
// PROV_BILDER en mapp för skärmbilderna.
//
// Provet: TKL B startas första gången som Fjärrställverk med driftplatsen asn och ansluter med
// Provbanans kod; trafikledningen godkänner det i Klienter. Station A erbjuder Åsen till B, och B
// tar emot under Väntar på dig: namnet blir grått och pilarna vid huvudsignalerna röda (FR8,
// FR32, FR33). B trycker 21 och spår 3: vägen blinkar, och Lägg tågvägen skickar den. A:s
// ställverk låser den och B:s fjärrbild ritar den grön, bara när A rapporterat (FR11, FR13). B
// begär 24 till spår 3, som krockar: A säger nej med skälet, B visar det och bilden ändras inte
// (FR12–FR14). B lägger 51 till spår 1 och tar bort den med Ta bort. B:s Tåg och klarering visar
// Åsen (FR17). Sist tar A tillbaka Åsen: namnet blir blått, pilarna försvinner och den låsta
// vägen ligger kvar (FR7, FR15).
//
// Med PROV_TKL_GRANNE: Norrbys egen TKL, på nivå 0 och godkänd för Norrby, får fliken Fjärr när A
// erbjuder den Åsen, tar emot där och lägger 52 till spår 2 med samma fjärrbild (FR3). A tar
// tillbaka Åsen igen.
//
// Station A är tills vidare ett låtsat ställverk här i provet (`stationA` nedan), en klient på
// stationsprotokollet som TKL: Studio tar inte fram fjärrkatalogen och översikten än, och
// ställverket svarar inte på route.request (del b). Det svarar som stationen ska: route.response
// med låst eller conflicting_route, och route.state med de låsta vägarna. När del b finns byts
// stationA mot en riktig TKL A med Gårdsjös modell (se README).
import { chromium } from "playwright-core";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const HUB = (process.env.PROV_HUBB ?? "http://127.0.0.1:8080").replace(/\/+$/, "");
const TKL = (process.env.PROV_TKL_FJARR ?? "http://127.0.0.1:8093").replace(/\/+$/, "");
const NEIGHBOUR = (process.env.PROV_TKL_GRANNE ?? "").replace(/\/+$/, "");
const HUB_FOR_TKL = (process.env.PROV_HUBB_I_TKL ?? HUB).replace(/\/+$/, "");
const PIN = process.env.PROV_TKL_PIN ?? "4711";
const SHOTS = process.env.PROV_BILDER ?? "";
const CHROME = process.env.CHROME_PATH ?? "";
const PLACE = "asn";
const NAME = "Åsen";

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

/** Provbanan in the hub, as a browser has it: the run and its code for clients over the internet. */
async function provbanan(browser) {
  const context = await browser.newContext();
  const hub = context.request;
  const started = await hub.post(`${HUB}/api/provbanan/start`, { data: { version: 1 } });
  check(started.ok(), `Provbanan startade inte (${started.status()}).`);
  const { code } = await (await hub.get(`${HUB}/api/provbanan/clients`)).json();
  check(/^\d{6}$/.test(code ?? ""), `Provbanan gav ingen kod: ${code}`);
  return { context, hub, code };
}

async function approve(hub, kind, places) {
  for (let i = 0; i < 50; i++) {
    const { clients } = await (await hub.get(`${HUB}/api/provbanan/clients`)).json();
    const found = clients.find((c) => c.kind === kind && c.status === "waiting");
    if (found) {
      const done = await hub.post(`${HUB}/api/provbanan/clients/approve`, { data: { client_id: found.client_id, places } });
      check(done.ok(), `Klienten godkändes inte (${done.status()}).`);
      return found.client_id;
    }
    await new Promise((r) => setTimeout(r, 100));
  }
  throw new ProvFel(`Klienter har ingen ${kind} som väntar.`);
}

// --- Station A: Åsen at level 2 with a remote catalogue in Gårdsjö's shape ----------------------

const piece = (id, row, start, end, track = null) => ({ id, row, start, end, track });
const OUTSIDE = {
  station_id: "asen-prov",
  name: NAME,
  tracks: ["1", "2", "3", "4"].map((id) => ({ id, label: `Spår ${id}` })),
  exits: [
    { id: "Vast-2", side: "left", name: "Väst 2" },
    { id: "Vast-1", side: "left", name: "Väst 1" },
    { id: "Enkelspar", side: "right", name: "Enkelspår" },
    { id: "Ost-2", side: "right", name: "Öst 2" },
    { id: "Ost-1", side: "right", name: "Öst 1" },
  ],
  remote_routes: [
    { id: "21-2", start: "21", end: "2", exit: "Vast-2", track: "2", direction: "in" },
    { id: "21-3", start: "21", end: "3", exit: "Vast-2", track: "3", direction: "in" },
    { id: "21-4", start: "21", end: "4", exit: "Vast-2", track: "4", direction: "in" },
    { id: "51-1", start: "51", end: "1", exit: "Vast-1", track: "1", direction: "in" },
    { id: "24-3", start: "24", end: "3", exit: "Enkelspar", track: "3", direction: "in" },
    { id: "24-4", start: "24", end: "4", exit: "Enkelspar", track: "4", direction: "in" },
    { id: "52-2", start: "52", end: "2", exit: "Ost-2", track: "2", direction: "in" },
    { id: "22-1", start: "22", end: "1", exit: "Ost-1", track: "1", direction: "in" },
  ],
  automats: [{ code: "A3", kind: "a3", default: true }],
  overview: {
    columns: 28,
    rows: 4,
    tracks: [
      piece("s4", 0, 7, 21, "4"),
      piece("s3a", 1, 5, 6),
      piece("s3", 1, 6, 22, "3"),
      piece("s3b", 1, 22, 23),
      piece("e3", 1, 23, 28),
      piece("v2", 2, 0, 3),
      piece("w2a", 2, 3, 4),
      piece("w2b", 2, 4, 6),
      piece("s2", 2, 6, 22, "2"),
      piece("e2", 2, 22, 28),
      piece("v1", 3, 0, 3),
      piece("s1", 3, 3, 25, "1"),
      piece("e1", 3, 25, 28),
    ],
    links: [
      { id: "l23v", from_row: 2, from_column: 4, to_row: 1, to_column: 5 },
      { id: "l34v", from_row: 1, from_column: 6, to_row: 0, to_column: 7 },
      { id: "l34o", from_row: 0, from_column: 21, to_row: 1, to_column: 22 },
    ],
    signals: [
      { name: "21", row: 2, column: 2, towards: "right" },
      { name: "51", row: 3, column: 2, towards: "right" },
      { name: "24", row: 1, column: 26, towards: "left" },
      { name: "52", row: 2, column: 26, towards: "left" },
      { name: "22", row: 3, column: 26, towards: "left" },
    ],
    exits: [
      { exit: "Vast-2", row: 2, column: 0 },
      { exit: "Vast-1", row: 3, column: 0 },
      { exit: "Enkelspar", row: 1, column: 28 },
      { exit: "Ost-2", row: 2, column: 28 },
      { exit: "Ost-1", row: 3, column: 28 },
    ],
    routes: {
      "21-2": ["v2", "w2a", "w2b", "s2"],
      "21-3": ["v2", "w2a", "l23v", "s3a", "s3"],
      "21-4": ["v2", "w2a", "l23v", "s3a", "l34v", "s4"],
      "51-1": ["v1", "s1"],
      "24-3": ["e3", "s3b", "s3"],
      "24-4": ["e3", "s3b", "l34o", "s4"],
      "52-2": ["e2", "s2"],
      "22-1": ["e1", "s1"],
    },
  },
};
const TRACK_OF = Object.fromEntries(OUTSIDE.remote_routes.map((r) => [r.id, r.track]));

/** Station A: a client of the station protocol as the station's TKL, with its interlocking's
 * answers to the routes asked for from afar. A route to a track that holds a locked route is a
 * conflicting route; anything else is locked. Every change goes up whole in route.state. */
async function stationA(hub, code) {
  const made = await hub.post(`${HUB}/api/station/1/connect`, {
    data: { kind: "tkl", name: `TKL ${NAME}`, software: "prov", code, level: 2, wants: [PLACE], outside: OUTSIDE },
  });
  check(made.ok(), `Station A kom inte in (${made.status()}): ${await made.text()}`);
  const { client_id } = await made.json();
  await hub.post(`${HUB}/api/provbanan/clients/approve`, { data: { client_id, places: [PLACE] } });
  const { key } = await (await hub.get(`${HUB}/api/station/1/connect/${client_id}`)).json();
  check(key, "Station A fick ingen nyckel.");
  const headers = { Authorization: `Bearer ${key}` };
  const seen = async () => (await hub.get(`${HUB}/api/station/1/places/${PLACE}`, { headers })).json();
  const send = async (action, payload) => {
    const context = (await seen()).context;
    const answer = await hub.post(`${HUB}/api/station/1/commands`, {
      headers,
      data: { message_id: `prov-${Date.now()}-${Math.random().toString(36).slice(2)}`, client_id, place: PLACE, context, action, payload },
    });
    const reply = await answer.json();
    check(reply.status === "accepted", `Station A: ${action} nekades: ${reply.message}`);
    return reply;
  };
  // Hubben asks which exit goes towards each neighbour (H26).
  for (const q of (await seen()).questions ?? []) {
    const exit = q.side === "left" ? "Vast-2" : "Enkelspar";
    await hub.post(`${HUB}/api/station/1/places/${PLACE}/exits`, { headers, data: { section: q.section, exit } });
  }
  const locked = new Map();
  const answered = new Set();
  const state = () => send("route.state", { locked: [...locked.values()], automats: [], local_areas: [], occupied: [] });
  let running = true;
  const loop = (async () => {
    while (running) {
      const snapshot = await seen();
      for (const r of snapshot.remote?.routes ?? []) {
        if (r.state === "requested" && !answered.has(r.request_id)) {
          answered.add(r.request_id);
          const busy = [...locked.values()].some((l) => TRACK_OF[l.route] === TRACK_OF[r.route]);
          if (busy) {
            await send("route.response", { request_id: r.request_id, locked: false, reason: "conflicting_route" });
          } else {
            await send("route.response", { request_id: r.request_id, locked: true });
            locked.set(r.request_id, { route: r.route, by: "remote", request_id: r.request_id });
            await state();
          }
        }
        if (r.state === "cancelled" && locked.has(r.request_id)) {
          locked.delete(r.request_id);
          await state();
        }
      }
      await new Promise((resolve) => setTimeout(resolve, 250));
    }
  })();
  return {
    receivers: async () => (await seen()).remote?.receivers ?? [],
    offer: (to) => send("place.offer", { to }),
    takeBack: () => send("place.take_back", {}),
    stop: async () => {
      running = false;
      await loop;
    },
  };
}

// --- TKL B: the remote interlocking ---------------------------------------------------------------

async function firstStartRemote(page) {
  await page.goto(`${TKL}/`);
  await page.getByRole("heading", { level: 1 }).first().waitFor();
  if (await page.getByText("Första start · tre rutor").isVisible()) {
    await page.getByRole("radio", { name: "Fjärrställverk (ingen egen station)" }).click();
    await page.getByLabel("Namn", { exact: true }).fill("Fjärr Väster");
    await page.getByLabel("Driftplatser").fill(PLACE);
    await page.getByLabel("Välj PIN").fill(PIN);
    await page.getByLabel("Skriv den igen").fill(PIN);
    await screenshot(page, "forsta-start-fjarr");
    await page.getByRole("button", { name: "Lås med PIN och starta fjärrställverket" }).click();
  } else if (await page.getByText("TKL är låst. Skriv PIN-koden.").isVisible()) {
    await page.getByLabel("PIN").fill(PIN);
    await page.getByRole("button", { name: "Lås upp" }).click();
  }
  await page.getByRole("link", { name: "Fjärrbild" }).first().waitFor();
}

async function connectRemote(page, code) {
  await page.goto(`${TKL}/installningar`);
  await page.getByLabel("Hubbens adress").fill(HUB_FOR_TKL);
  await page.getByLabel("Kod").fill(code);
  await page.getByRole("button", { name: "Anslut", exact: true }).click();
  await page.getByRole("heading", { name: "Väntar på godkännande" }).waitFor();
}

/** Norrby's own TKL at level 0, connected and approved for its place: the neighbour (FR3). */
async function neighbourTkl(browser, hub, code) {
  const context = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
  const page = await context.newPage();
  await page.goto(`${NEIGHBOUR}/`);
  await page.getByText("Första start · tre rutor").waitFor();
  await page.getByLabel("Namn", { exact: true }).fill("Norrby");
  await page.getByLabel("Kort namn").fill("norrby");
  await page.getByLabel("Välj PIN").fill(PIN);
  await page.getByLabel("Skriv den igen").fill(PIN);
  await page.getByRole("button", { name: "Lås med PIN och starta" }).click();
  await page.getByRole("link", { name: "Studio" }).first().waitFor();
  await page.goto(`${NEIGHBOUR}/installningar`);
  await page.getByLabel("Hubbens adress").fill(HUB_FOR_TKL);
  await page.getByLabel("Kod").fill(code);
  await page.getByRole("button", { name: "Anslut", exact: true }).click();
  await page.getByRole("heading", { name: "Väntar på godkännande" }).waitFor();
  await approve(hub, "tkl", ["nby"]);
  await page.goto(`${NEIGHBOUR}/`);
  await page.getByRole("heading", { name: /Klarering/ }).first().waitFor({ timeout: 15_000 });
  return page;
}

const picture = (page) => page.locator("svg.fjarrbild");
const station = (page) => picture(page).locator(`g.fj-station[data-place="${PLACE}"]`);
/** A station track's state in A's drawing, by the track's id in the outside: the same with the
 * pretend station and with a real one, whatever its overview calls the pieces. */
const trackState = (page, track) => station(page).locator(`line[data-track="${track}"]`).first().getAttribute("data-state");
/** Every piece's state in A's drawing, to see that a no changes nothing. */
async function states(page) {
  return station(page)
    .locator("[data-piece]")
    .evaluateAll((all) => all.map((e) => `${e.getAttribute("data-piece")}=${e.getAttribute("data-state")}`).join(" "));
}
async function waitFor(test, what, page, ms = 15_000) {
  const until = Date.now() + ms;
  while (Date.now() < until) {
    if (await test()) return;
    await page.waitForTimeout(150);
  }
  throw new ProvFel(what);
}

async function main() {
  if (SHOTS) mkdirSync(SHOTS, { recursive: true });
  const started = Date.now();
  const browser = await chromium.launch({ executablePath: CHROME || undefined, headless: true });
  let a = null;
  try {
    const { hub, code } = await provbanan(browser);
    const context = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
    const page = await context.newPage();
    await firstStartRemote(page);
    await connectRemote(page, code);
    await approve(hub, "remote", [PLACE]);
    a = await stationA(hub, code);
    await page.goto(`${TKL}/`);
    await station(page).waitFor({ timeout: 20_000 });
    check((await station(page).getAttribute("data-mode")) === "manned", "Åsen är inte bemannad innan den lämnas över.");
    // 3. A offers the station to B, and B takes it (FR8).
    const receiver = (await a.receivers()).find((r) => r.kind === "remote");
    check(receiver, "Åsen kan inte lämnas till fjärrställverket.");
    await a.offer(receiver.client_id);
    const offer = page.locator(`[data-offer="${PLACE}"]`);
    await offer.waitFor({ timeout: 10_000 });
    check(/kvar/.test((await offer.textContent()) ?? ""), "Erbjudandet visar inte tiden kvar.");
    await screenshot(page, "erbjudande");
    await offer.getByRole("button", { name: "Ta emot" }).click();
    await waitFor(async () => (await station(page).getAttribute("data-mode")) === "remote", "Åsen blev inte fjärrstyrd.", page);
    check((await station(page).locator('[data-arrow="remote"]').count()) === 5, "Pilarna vid huvudsignalerna är inte röda.");
    check((await station(page).locator(".fj-namn").getAttribute("data-colour")) === "#c4c8cc", "Namnet är inte grått.");
    // 4. B requests 21 → spår 3; it blinks, is sent, and is green when A has locked it (FR13).
    await picture(page).getByRole("button", { name: `Start 21 vid ${NAME}` }).click();
    await picture(page).getByRole("button", { name: `Mål spår 3 vid ${NAME}` }).click();
    check((await trackState(page, "3")) === "chosen", "Den valda vägen blinkar inte.");
    await screenshot(page, "vald-blinkar");
    await page.getByRole("button", { name: "Lägg tågvägen" }).click();
    await waitFor(async () => (await trackState(page, "3")) === "train", "21 → spår 3 blev inte grön i fjärrbilden.", page);
    check((await trackState(page, "2")) === "free" && (await trackState(page, "4")) === "free", "Fel spår är gröna.");
    check((await station(page).locator('[data-signal="21"]').getAttribute("data-aspect")) === "proceed", "Signal 21 visar inte kör.");
    await screenshot(page, "last-gron");
    // 5. A conflicting route: a no with the reason, and the picture does not change (FR12–FR14).
    const before = await states(page);
    await picture(page).getByRole("button", { name: `Start 24 vid ${NAME}` }).click();
    await picture(page).getByRole("button", { name: `Mål spår 3 vid ${NAME}` }).click();
    await page.getByRole("button", { name: "Lägg tågvägen" }).click();
    const no = page.locator(".fj-rad.nej", { hasText: "En fientlig väg är lagd." });
    await no.waitFor({ timeout: 15_000 });
    check(/24 → spår 3/.test((await no.textContent()) ?? ""), "Nejet säger inte vilken väg.");
    await page.waitForTimeout(500);
    check((await states(page)) === before, `Bilden ändrades av ett nej: ${before} → ${await states(page)}`);
    await screenshot(page, "nej-med-skal");
    // Ta bort: 51 → spår 1 is laid and taken away again.
    await picture(page).getByRole("button", { name: `Start 51 vid ${NAME}` }).click();
    await picture(page).getByRole("button", { name: `Mål spår 1 vid ${NAME}` }).click();
    await page.getByRole("button", { name: "Lägg tågvägen" }).click();
    await waitFor(async () => (await trackState(page, "1")) === "train", "51 → spår 1 blev inte grön.", page);
    await page.locator(".fj-rad", { hasText: "51 → spår 1" }).getByRole("button", { name: "Ta bort" }).click();
    await waitFor(async () => (await trackState(page, "1")) === "free", "Ta bort löste inte upp 51 → spår 1.", page);
    // FR17: Tåg och klarering for the station B controls.
    await page.getByRole("link", { name: "Tåg och klarering" }).first().click();
    await page.getByRole("navigation", { name: "Stationerna" }).getByRole("button", { name: NAME }).waitFor();
    await page.getByRole("heading", { name: /Klarering/ }).first().waitFor({ timeout: 10_000 });
    await screenshot(page, "tag-och-klarering");
    await page.getByRole("link", { name: "Fjärrbild" }).first().click();
    await station(page).waitFor();
    // 6. A takes the station back: manned, blue, no arrows; the locked route stays (FR7, FR15).
    await a.takeBack();
    await waitFor(async () => (await station(page).getAttribute("data-mode")) === "manned", "Åsen blev inte bemannad igen.", page);
    check((await station(page).locator("[data-arrow]").count()) === 0, "Pilarna står kvar på en bemannad station.");
    check((await station(page).locator(".fj-namn").getAttribute("data-colour")) === "#4da3ff", "Namnet är inte blått.");
    check((await trackState(page, "3")) === "train", "Den låsta vägen försvann när stationen togs tillbaka.");
    await screenshot(page, "tagen-tillbaka");
    if (NEIGHBOUR) {
      // FR3: Norrby's own TKL controls its neighbour Åsen with the same fjärrbild, under Fjärr.
      const norrby = await neighbourTkl(browser, hub, code);
      const to = (await a.receivers()).find((r) => r.kind === "tkl");
      check(to, "Åsen kan inte lämnas till Norrbys TKL.");
      await a.offer(to.client_id);
      const tab = norrby.getByRole("link", { name: "Fjärr", exact: true }).first();
      await tab.waitFor({ timeout: 15_000 });
      await tab.click();
      const offered = norrby.locator(`[data-offer="${PLACE}"]`);
      await offered.waitFor({ timeout: 10_000 });
      await offered.getByRole("button", { name: "Ta emot" }).click();
      await waitFor(async () => (await station(norrby).getAttribute("data-mode")) === "remote", "Åsen blev inte fjärrstyrd från Norrby.", norrby);
      await picture(norrby).getByRole("button", { name: `Start 52 vid ${NAME}` }).click();
      await picture(norrby).getByRole("button", { name: `Mål spår 2 vid ${NAME}` }).click();
      await norrby.getByRole("button", { name: "Lägg tågvägen" }).click();
      await waitFor(async () => (await trackState(norrby, "2")) === "train", "52 → spår 2 blev inte grön hos Norrby.", norrby);
      await screenshot(norrby, "granne-fjarr");
      await a.takeBack();
      await waitFor(async () => (await station(norrby).getAttribute("data-mode")) === "manned", "Åsen blev inte bemannad igen hos Norrby.", norrby);
    }
    const neighbourDone = NEIGHBOUR ? ", också från grannens TKL" : "";
    console.log(`Fjärrstyrningen fungerar: erbjuden, tagen, låst, nekad med skäl, borttagen och tagen tillbaka${neighbourDone}, på ${Math.round((Date.now() - started) / 1000)} s.`);
  } finally {
    if (a) await a.stop();
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error instanceof ProvFel ? `Provet gick inte igenom: ${error.message}` : error);
  process.exit(1);
});
