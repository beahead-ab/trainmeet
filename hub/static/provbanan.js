"use strict";

const element = id => document.getElementById(id);
const legSelect = element("leg");
const notice = element("notice");
const speed = element("speed");
let state;
let lastUpdate;
let busy = false;

const reasons = {
  invalid_departure: "Tåget har redan kört den här sträckan.",
  call_already_requested: "Tåget har redan en pågående klarering.",
  channel_occupied: "Sträckan är upptagen.",
};

function addButton(parent, text, action) {
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = text;
  button.onclick = action;
  parent.append(button);
}

function showClock() {
  if (!state) return;
  const clock = state.clock;
  const elapsed = clock.running ? (performance.now() - lastUpdate) / 1000 : 0;
  const minute = Math.floor((clock.seconds + elapsed * clock.speed) / 60) % 1440;
  const pad = number => String(number).padStart(2, "0");
  element("clock").textContent = pad(Math.floor(minute / 60)) + ":" + pad(minute % 60);
}

function selectedLeg() {
  return state?.legs.find(leg => leg.departure.id === legSelect.value);
}

function showLeg() {
  const leg = selectedLeg();
  element("request").disabled = !leg || Boolean(leg.blocked);
  if (!leg) return;
  const mode = state.sections[leg.section] === "direct" ? "Direktklarering" : "Begärd klarering";
  const track = leg.arrival.track ? " · planerat ankomstspår " + leg.arrival.track : "";
  const status = leg.complete ? " · framme" : leg.blocked ? " · " + reasons[leg.blocked] : "";
  element("leg-info").textContent = mode + track + status;
}

function render(next) {
  const selected = legSelect.value;
  const previous = state;
  state = next;
  lastUpdate = performance.now();
  element("start").hidden = true;
  element("run").hidden = false;
  element("toggle-clock").textContent = state.clock.running ? "Stanna klockan" : "Starta klockan";
  if (!previous || previous.clock.speed !== state.clock.speed) speed.value = state.clock.speed;
  showClock();

  if (previous?.revision === state.revision) return;
  const { places } = state;
  legSelect.replaceChildren(...state.legs.map(leg => {
    const label = [
      leg.departure.departure ?? "Utan avgångstid",
      "tåg " + leg.train,
      places[leg.departure.place] + " → " + places[leg.arrival.place],
    ].join(" · ");
    return new Option(label, leg.departure.id);
  }));
  legSelect.value = state.legs.some(leg => leg.departure.id === selected)
    ? selected : state.legs.find(leg => !leg.blocked)?.departure.id ?? "";
  showLeg();

  const labels = { waiting: "Väntar på svar", approved: "Klart", rejected: "Nekad",
    cancelled: "Återkallad" };
  const cases = element("cases");
  cases.replaceChildren();
  if (!state.cases.length) {
    const empty = document.createElement("li");
    empty.textContent = "Inga klareringar ännu.";
    cases.append(empty);
  }
  const active = state.cases.filter(item =>
    !item.arrived && ["waiting", "approved"].includes(item.status));
  const finished = state.cases.filter(item => !active.includes(item)).slice(-5).reverse();
  for (const item of [...active, ...finished]) {
    const row = document.createElement("li");
    const status = item.arrived ? "Ankommen" : item.departed ? "På väg" : labels[item.status];
    row.textContent = "Tåg " + item.train + " · " + places[item.from_place] + " → "
      + places[item.to_place] + " · " + status;
    const actions = document.createElement("div");
    actions.className = "controls";
    if (item.status === "waiting") {
      addButton(actions, places[item.to_place] + ": Ge klart",
        () => answer(item, true));
      addButton(actions, places[item.to_place] + ": Neka", () => answer(item, false));
    }
    if (!item.departed && ["waiting", "approved"].includes(item.status)) {
      addButton(actions, places[item.from_place] + ": Återkalla",
        () => command(item.from_place, "clearance.cancel", { clearance_id: item.id }, item));
    }
    if (item.status === "approved" && !item.departed) {
      addButton(actions, places[item.from_place] + ": Avgå",
        () => command(item.from_place, "train.departed", { call: item.departure }));
    }
    if (item.departed && !item.arrived) {
      addButton(actions, places[item.to_place] + ": Ankom",
        () => command(item.to_place, "train.arrived", { call: item.arrival }));
    }
    if (actions.childElementCount) row.append(actions);
    cases.append(row);
  }
}

async function request(path = "", body, fresh = false) {
  if (busy) return;
  busy = true;
  notice.textContent = "";
  try {
    const init = body ? {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    } : {};
    const response = await fetch("/api/provbanan" + path, init);
    if (response.status === 404 && !body) return;
    if (!response.ok) {
      const error = await response.json();
      notice.textContent = typeof error.detail === "string" ? error.detail : "Åtgärden gick inte.";
      return;
    }
    const next = await response.json();
    if (fresh) { state = undefined; clientsShown = ""; }
    render(next);
    if (fresh) refreshClients();
  } catch {
    notice.textContent = "Kontakten med Hubben bröts. Ladda om sidan för att läsa läget.";
  } finally {
    busy = false;
  }
}

function command(place, action, payload, item) {
  const body = {
    message_id: crypto.randomUUID(), client_id: "prov-" + place, place,
    context: state.context, action, payload,
  };
  if (item) body.expected_revision = { scope: "case", key: item.id, value: item.revision };
  return request("/command", body);
}

function answer(item, approved) {
  return command(item.to_place, "clearance.response", { clearance_id: item.id, approved }, item);
}

let clientsShown = "";

function showClients(data) {
  element("join-code").textContent = data.code;
  element("box-link").href = "/provbanan/box#kod=" + data.code;
  const shown = JSON.stringify(data.clients) + JSON.stringify(state?.stations);
  if (shown === clientsShown) return;
  clientsShown = shown;
  const list = element("clients");
  list.replaceChildren();
  if (!data.clients.length) {
    const empty = document.createElement("li");
    empty.textContent = "Inga boxar anslutna ännu.";
    list.append(empty);
  }
  for (const client of data.clients) {
    const row = document.createElement("li");
    const where = client.places.length
      ? "Tilldelad " + client.places.map(place => state.places[place]).join(", ")
        + (client.side === "both" ? "" : " · " + SIDES[client.side].toLowerCase())
      : "Väntar på tilldelning";
    const size = client.display ? " · " + client.display.cols + "×" + client.display.rows : "";
    row.textContent = client.name + " · " + where + size;
    const controls = document.createElement("div");
    controls.className = "controls";
    const place = choice("Driftplats för " + client.name,
      (state?.stations ?? []).map(id => [id, state.places[id]]), client.places[0]);
    // Left and right as the box shows the place; both, the default, is the whole place.
    const side = choice("Sida för " + client.name, Object.entries(SIDES), client.side);
    const language = choice("Språk för " + client.name, Object.entries(LANGUAGES), client.language);
    controls.append(place, side, language);
    addButton(controls, client.places.length ? "Ändra" : "Tilldela",
      () => assign(client, place.value, side.value, language.value));
    row.append(controls);
    list.append(row);
  }
}

const SIDES = { both: "Båda sidor", left: "Vänster", right: "Höger" };
const LANGUAGES = { sv: "Svenska", en: "English", da: "Dansk", nb: "Norsk", de: "Deutsch" };

function choice(label, options, value) {
  const select = document.createElement("select");
  select.setAttribute("aria-label", label);
  for (const [id, text] of options) select.append(new Option(text, id));
  if (value) select.value = value;
  return select;
}

async function refreshClients() {
  try {
    const response = await fetch("/api/provbanan/clients", { cache: "no-store" });
    if (response.ok) showClients(await response.json());
  } catch { /* The next round tries again. */ }
}

async function assign(client, place, side, language) {
  notice.textContent = "";
  const response = await fetch("/api/provbanan/clients/assign", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ client_id: client.client_id, places: [place], side, language }),
  });
  const answer = await response.json();
  if (!response.ok) {
    notice.textContent = typeof answer.detail === "string" ? answer.detail : "Det gick inte.";
    return;
  }
  showClients(answer);
}

// What the boxes do shows here too: the run is read again every other second.
async function poll() {
  if (busy || !state) return;
  try {
    const response = await fetch("/api/provbanan", { cache: "no-store" });
    if (response.ok && !busy) render(await response.json());
  } catch { /* The next round tries again. */ }
  refreshClients();
}

function start() { return request("/start", { version: 1 }, true); }
element("start").onclick = start;
element("restart").onclick = start;
element("toggle-clock").onclick = () =>
  request("/clock", { action: state.clock.running ? "stop" : "start" });
element("set-speed").onclick = () => {
  if (speed.reportValidity() && speed.value) request("/clock", { action: "speed", speed: +speed.value });
};
element("request").onclick = () => {
  const leg = selectedLeg();
  if (leg) command(leg.departure.place, "clearance.request", {
    call: leg.departure.id, section: leg.section, clearance_id: crypto.randomUUID(),
  });
};
legSelect.onchange = showLeg;
setInterval(showClock, 1000);
setInterval(poll, 2000);
request().then(refreshClients);
