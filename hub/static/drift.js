// Trafikledningen (steg 3): the header, Nu, Klienter and Logg, filled from Driftens API.
// The session is an HttpOnly cookie this page never sees; without it the page only looks (S1).
"use strict";

const $ = id => document.getElementById(id);
const page = document.body.dataset.page;
const admin = document.body.dataset.admin === "ja";
const API = "/api/drift/1";

let now = null;          // The last Nu from the hub.
let fetchedAt = 0;       // When it came, for the clock between fetches.
let clients = [];
let legFilter = "all";
let clientFilter = "all";
let logKind = "events";
let logPlace = null;

const STATES = {
  planned: "Ej begärd", requested: "Begärd", cleared: "Klar att avgå",
  on_the_way: "På väg", arrived: "Framme",
};
const CASES = { waiting: "Väntar på svar", approved: "Klart givet" };
const KINDS = { tmbox_web: "Webbox", tmbox: "TMBox", tmbox_app: "TMBox-appen", tkl: "TKL",
  dispatch: "Trafikledningen", screen: "Skärm" };
const APPROVAL = { waiting: "Väntar", approved: "Ansluten", refused: "Nekad",
  revoked: "Återkallad" };
const SIDES = { both: "Båda sidor", left: "Vänster", right: "Höger" };
const LANGUAGES = { sv: "Svenska", en: "English", da: "Dansk", nb: "Norsk", de: "Deutsch" };
const SPEEDS = [1, 2, 3, 4, 6, 8, 12];
const VIEWS = { clock: "Klocka" };
const EVENTS = {
  "meet.started": "Träffen startade", "clock.started": "Klockan startade",
  "clock.stopped": "Klockan stoppades", "clock.speed": "Ny hastighet",
  "clearance.requested": "Klarering begärd", "clearance.cancelled": "Begäran återtagen",
  "clearance.invalidated": "Klareringen blev ogiltig (spårbyte)",
  "clearance.reminded": "Påminnelse", "train.departed": "Avgång", "train.arrived": "Ankomst",
  "train.moved_here": "Flyttad hit", "train.set_aside": "Undanställd",
  "train.track_changed": "Spårbyte", "train.positioned": "Uppställd",
  "train.crew_ready": "Föraren på plats", "line.available": "Ledig linje",
  "line.acknowledged": "Ledig linje kvitterad",
};

function el(tag, attributes = {}, ...children) {
  const node = document.createElement(tag);
  for (const [name, value] of Object.entries(attributes)) {
    if (name === "class") node.className = value;
    else if (name.startsWith("on")) node.addEventListener(name.slice(2), value);
    else node.setAttribute(name, value);
  }
  for (const child of children) node.append(child);
  return node;
}

function say(text) { $("message").textContent = text || ""; }

async function api(path, body) {
  const response = await fetch(path, {
    method: body === undefined ? "GET" : "POST",
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    credentials: "same-origin",
  });
  const answer = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(typeof answer.detail === "string" ? answer.detail : "Det gick inte.");
    error.status = response.status;
    throw error;
  }
  return answer;
}

function placeName(id) {
  return now?.places.find(place => place.place === id)?.name ?? id;
}

function placeCode(id) {
  return now?.places.find(place => place.place === id)?.code ?? id;
}

// --- The header: the meet, its clock, Anslut and Väntar (S2) -----------------------------

function clockText() {
  if (!now) return "--:--";
  const { clock } = now;
  const passed = clock.running ? (Date.now() - fetchedAt) / 1000 * clock.speed : 0;
  const minutes = Math.floor((clock.seconds + passed) / 60) % 1440;
  return `${String(Math.floor(minutes / 60)).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}`;
}

function drawClock() {
  $("clock").textContent = clockText();
  $("clock").className = "klocka " + (now ? (now.clock.running ? "gar" : "star") : "");
}

async function refreshNow() {
  try {
    now = await api(API + "/now");
    fetchedAt = Date.now();
    $("meet-name").textContent = now.name;
  } catch (error) {
    if (error.status !== 404) return;
    now = null;
  }
  drawClock();
  if (page === "nu") drawNu();
}

async function refreshWaiting() {
  if (!admin) return;
  try {
    clients = await api(API + "/clients");
  } catch {
    clients = [];
  }
  const waiting = clients.filter(client => client.status === "waiting").length;
  $("waiting-count").textContent = waiting;
  $("waiting").classList.toggle("har", waiting > 0);
  if (page === "klienter") drawClients();
}

async function toggleConnect() {
  const panel = $("connect-panel");
  if (!panel.hidden) { panel.hidden = true; return; }
  try {
    const joining = await api(API + "/connect");
    $("connect-code").textContent = joining.code;
    $("connect-url").textContent = joining.url;
    $("connect-screen").textContent = joining.url.replace("/box#", "/skarm#");
    $("connect-qr").src = API + "/connect.svg?" + Date.now();
    panel.hidden = false;
  } catch (error) {
    say(error.message);
  }
}

// --- Nu --------------------------------------------------------------------------------

function chip(label, pressed, onclick, count) {
  const button = el("button", { type: "button", class: "chip", "aria-pressed": String(pressed),
    onclick }, label);
  if (count !== undefined) button.append(el("span", { class: "antal" }, String(count)));
  return button;
}

function drawNu() {
  $("no-meet").hidden = now !== null;
  $("meet").hidden = now === null;
  if (!now) return;
  const day = { mon: "måndag", tue: "tisdag", wed: "onsdag", thu: "torsdag", fri: "fredag",
    sat: "lördag", sun: "söndag" }[now.traffic_day];
  $("title").textContent = now.name;
  $("subtitle").textContent = `Trafikdag ${day} · dag ${now.game_day} · `
    + (now.clock.running ? `klockan går i ${now.clock.speed}×` : "klockan står still");
  if (admin) {
    $("clock-toggle").textContent = now.clock.running ? "Stoppa klockan" : "Starta klockan";
    $("speeds").replaceChildren(...SPEEDS.map(speed => chip(`${speed}×`,
      now.clock.speed === speed, () => clockControl({ action: "speed", speed }))));
  }
  $("case-count").textContent = now.clearances.length;
  $("cases").replaceChildren(...(now.clearances.length ? now.clearances.map(clearance =>
    el("li", {}, el("div", { class: "vem" },
      el("b", {}, `${clearance.train_number} · ${placeCode(clearance.from_place)} → `
        + placeCode(clearance.to_place)),
      el("span", { class: "liten" }, (clearance.departed ? "På väg" :
        CASES[clearance.status] ?? clearance.status) + ` · begärd ${clearance.requested_at}`))))
    : [el("li", { class: "tom" }, "Inga öppna klareringar.")]));
  const counts = {};
  for (const leg of now.legs) counts[leg.state] = (counts[leg.state] ?? 0) + 1;
  $("filters").replaceChildren(
    chip("Alla", legFilter === "all", () => { legFilter = "all"; drawNu(); }, now.legs.length),
    ...Object.entries(STATES).map(([state, label]) => chip(label, legFilter === state,
      () => { legFilter = state; drawNu(); }, counts[state] ?? 0)));
  const legs = now.legs.filter(leg => legFilter === "all" || leg.state === legFilter);
  $("legs").replaceChildren(...legs.map(leg => el("tr", { class: leg.state === "arrived" ? "klar" : "" },
    el("td", { class: "tag" }, leg.train_number),
    el("td", {}, `${placeName(leg.from_place)} → ${placeName(leg.to_place)}`),
    el("td", {}, leg.departure ?? "–"),
    el("td", {}, leg.arrival ?? "–"),
    el("td", {}, el("span", { class: "pill " + leg.state }, STATES[leg.state])),
    el("td", {}, leg.track ?? "–"))));
}

async function clockControl(control) {
  try {
    await api(API + "/clock", control);
    say("");
    await refreshNow();
  } catch (error) {
    say(error.message);
  }
}

async function startMeet(day) {
  try {
    await api(API + "/start", { version: 1, traffic_day: day });
    say("");
    $("connect-panel").hidden = true;
    await refreshNow();
    await refreshWaiting();
  } catch (error) {
    say(error.message);
  }
}

function setUpNu() {
  if (!admin) return;
  $("start-meet")?.addEventListener("click", () => startMeet($("first-day").value));
  $("clock-toggle").addEventListener("click",
    () => clockControl({ action: now?.clock.running ? "stop" : "start" }));
  // Two presses to start a new meet: the old one is archived and its clients let go.
  let armed = 0;
  $("new-meet").addEventListener("click", () => {
    if (Date.now() - armed > 5000) {
      armed = Date.now();
      $("new-meet").textContent = "Tryck igen för att byta";
      $("new-meet").classList.add("fara");
      return;
    }
    armed = 0;
    $("new-meet").textContent = "Starta ny träff";
    $("new-meet").classList.remove("fara");
    startMeet($("new-day").value);
  });
  if (location.hash === "#ny-traff") $("ny-traff").open = true;
}

// --- Klienter (S3) ---------------------------------------------------------------------

function select(label, options, value) {
  const node = el("select", { "aria-label": label });
  for (const [id, text] of options) node.append(new Option(text, id));
  if (value) node.value = value;
  return node;
}

async function change(action, body) {
  try {
    await api(`${API}/clients/${action}`, body);
    say("");
    await refreshWaiting();
  } catch (error) {
    say(error.message);
  }
}

function clientRow(client) {
  const places = (now?.places ?? []).map(place => [place.place, place.name]);
  const where = client.places.length ? client.places.map(placeName).join(", ") : "";
  const details = [KINDS[client.kind] ?? client.kind, APPROVAL[client.status] ?? client.status];
  if (where) details.push(where + (client.side && client.side !== "both"
    ? " · " + SIDES[client.side].toLowerCase() : ""));
  if (client.display) details.push(`${client.display.cols}×${client.display.rows}`);
  if (client.language && client.kind.startsWith("tmbox")) details.push(LANGUAGES[client.language]);
  const controls = el("div", { class: "kontroller" });
  if (client.kind === "screen") {
    details[1] = client.view ? "Visar " + (VIEWS[client.view] ?? client.view) : "Väntar på en vy";
    const view = select("Vy för " + client.name, Object.entries(VIEWS), client.view);
    controls.append(view, el("button", { type: "button", onclick: () => change("view",
      { client_id: client.client_id, view: view.value }) }, client.view ? "Byt vy" : "Visa"));
  } else if (client.kind.startsWith("tmbox")) {
    const place = select("Driftplats för " + client.name, places, client.places[0]);
    const side = select("Sida för " + client.name, Object.entries(SIDES), client.side);
    const language = select("Språk för " + client.name, Object.entries(LANGUAGES), client.language);
    controls.append(place, side, language, el("button", { type: "button", onclick: () => change(
      "assign", { client_id: client.client_id, places: [place.value], side: side.value,
        language: language.value }) }, client.places.length ? "Ändra" : "Tilldela"));
  } else if (client.status === "approved") {
    controls.append(el("button", { type: "button", class: "fara", onclick: () => change(
      "revoke", { client_id: client.client_id }) }, "Återkalla"));
  } else {
    const place = select("Driftplats för " + client.name, places, client.places[0]);
    controls.append(place, el("button", { type: "button", onclick: () => change("approve",
      { client_id: client.client_id, places: [place.value] }) }, "Godkänn"));
  }
  return el("li", { class: client.status === "waiting" ? "vantar" : "" },
    el("div", { class: "vem" }, el("b", {}, client.name),
      el("span", { class: "liten" }, details.join(" · "))), controls);
}

function drawClients() {
  const groups = {
    all: ["Alla", () => true],
    waiting: ["Väntar", client => client.status === "waiting"],
    boxes: ["Boxar", client => client.kind.startsWith("tmbox")],
    stations: ["TKL", client => client.kind === "tkl"],
    screens: ["Skärmar", client => client.kind === "screen"],
  };
  $("client-filters").replaceChildren(...Object.entries(groups).map(([key, [label, test]]) =>
    chip(label, clientFilter === key, () => { clientFilter = key; drawClients(); },
      clients.filter(test).length)));
  // Opening a list must never move a row under the pointer: only redraw what changed.
  const shown = clients.filter(groups[clientFilter][1]);
  const signature = JSON.stringify(shown);
  if ($("clients").dataset.signature === signature) return;
  $("clients").dataset.signature = signature;
  if (document.activeElement?.closest?.("#clients")) return;
  $("clients").replaceChildren(...(shown.length ? shown.map(clientRow)
    : [el("li", { class: "tom" }, "Inga klienter här. Anslut finns i sidhuvudet.")]));
}

// --- Logg (B15) ------------------------------------------------------------------------

function trainNumber(trainId) {
  return now?.legs.find(leg => leg.train === trainId)?.train_number ?? "";
}

function trainId(number) {
  return now?.legs.find(leg => leg.train_number === number)?.train ?? number;
}

async function drawLog() {
  $("log-kinds").replaceChildren(
    chip("Händelser", logKind === "events", () => { logKind = "events"; drawLog(); }),
    chip("Nekade", logKind === "refusals", () => { logKind = "refusals"; drawLog(); }));
  $("log-places").replaceChildren(
    chip("Alla driftplatser", logPlace === null, () => { logPlace = null; drawLog(); }),
    ...(now?.places ?? []).map(place => chip(place.name, logPlace === place.place,
      () => { logPlace = place.place; drawLog(); })));
  const number = $("log-train").value.trim();
  try {
    if (logKind === "events") {
      const query = new URLSearchParams();
      if (logPlace) query.set("place", logPlace);
      if (number) query.set("train", trainId(number));
      const events = await api(`${API}/log?${query}`);
      $("log").replaceChildren(...(events.length ? events.map(event => el("tr", {},
        el("td", {}, event.model_time),
        el("td", {}, describe(event)),
        el("td", { class: "tag" }, trainNumber(event.train)),
        el("td", {}, event.place ? placeName(event.place) : ""),
        el("td", {}, actor(event.actor)))) : [empty("Inget har hänt här än.")]));
    } else {
      const refusals = (await api(`${API}/refusals`)).filter(refusal =>
        !logPlace || refusal.place === logPlace);
      $("log").replaceChildren(...(refusals.length ? refusals.map(refusal => el("tr", {},
        el("td", {}, refusal.model_time),
        el("td", {}, `${refusal.what}: ${refusal.message}`),
        el("td", {}, ""),
        el("td", {}, refusal.place ? placeName(refusal.place) : ""),
        el("td", { class: "kod" }, refusal.client_id))) : [empty("Ingen har fått nej.")]));
    }
    say("");
  } catch (error) {
    say(error.message);
  }
}

// Who did it: the client's name if it is still connected, else its id; the hub itself.
function actor(who) {
  if (!who || who.kind === "system") return "Hubben";
  if (who.kind === "dispatcher") return "Trafikledningen";
  const known = clients.find(client => client.client_id === who.id);
  return known ? known.name : (who.id ?? who.kind);
}

function empty(text) {
  return el("tr", {}, el("td", { colspan: "5", class: "tom" }, text));
}

function describe(event) {
  if (event.kind === "clearance.answered") {
    return event.data.approved ? "Klart givet" : "Begäran nekad";
  }
  if (event.kind === "clock.speed") return `Ny hastighet ${event.data.speed}×`;
  if (event.kind === "train.arrived" && event.data.track) return `Ankomst spår ${event.data.track}`;
  return EVENTS[event.kind] ?? event.kind;
}

// --- Start ---------------------------------------------------------------------------

if (admin) {
  $("connect").addEventListener("click", toggleConnect);
  $("logout").addEventListener("click", async () => {
    await fetch("/api/hub/logout", { method: "POST", credentials: "same-origin" });
    location.href = "/";
  });
}
if (page === "nu") setUpNu();
if (page === "logg" && admin) {
  $("log-train").addEventListener("input", () => drawLog());
}

(async () => {
  await refreshNow();
  await refreshWaiting();
  if (page === "logg" && admin) await drawLog();
  setInterval(drawClock, 1000);
  setInterval(refreshNow, 2000);
  setInterval(refreshWaiting, 3000);
  if (page === "logg" && admin) setInterval(drawLog, 5000);
})();
