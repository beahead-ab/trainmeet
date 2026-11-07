// Planering: Träffar, and in a meet Data · Bana · Graf · Versioner (S6), filled from
// Planeringens API. Data has every block as a chip (S5): several at once, search, filters,
// source and certainty as columns, the chosen row beside, and changes kept until Spara with
// undo and redo. Lägg till underlag opens from Data. The session is an HttpOnly cookie this
// page never sees; without it the page only looks (S1).
"use strict";

const $ = id => document.getElementById(id);
const page = document.body.dataset.page;
const meetId = document.body.dataset.meet;
const admin = document.body.dataset.admin === "ja";
const API = "/api/planering/1";

const KINDS = { manned: "Bemannad", remote: "Fjärrstyrd", unmanned: "Obemannad",
  shadow_yard: "Skuggbangård", halt: "Hållplats/industri" };
const KINDS_MANY = { manned: "bemannade", remote: "fjärrstyrda", unmanned: "obemannade",
  shadow_yard: "skuggbangårdar", halt: "hållplatser/industrier" };
const CERTAINTY = { sure: "säker", likely: "trolig", unsure: "osäker", confirmed: "bekräftad" };
const CONTENT = { passengers: "Resande", goods: "Gods", service: "Tjänst" };
const MODES = { requested: "Begärd", direct: "Direkt" };
const TRACKS = { single: "Enkel", double: "Dubbel" };
const COUNTRIES = { se: "Sverige", dk: "Danmark", no: "Norge", de: "Tyskland" };
const DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
const DAY_NAMES = ["Mån", "Tis", "Ons", "Tor", "Fre", "Lör", "Sön"];
const LEVELS = [[1, "ST"], [2, "+ BILD"], [3, "+ GRAF"], [4, "JSON"]];
const SHOWN = 300;

let draft = null;
let facts = new Map();
let findings = [];
let versions = [];

function el(tag, attributes = {}, ...children) {
  const node = document.createElement(tag);
  for (const [name, value] of Object.entries(attributes)) {
    if (value === undefined || value === null || value === false) continue;
    if (name === "class") node.className = value;
    else if (name.startsWith("on")) node.addEventListener(name.slice(2), value);
    else node.setAttribute(name, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child !== null && child !== undefined && child !== false) node.append(child);
  }
  return node;
}

function say(text, ok = false) {
  $("message").textContent = text || "";
  $("message").className = "meddelande" + (ok ? " ok" : "");
}

async function api(path, body, { raw = null, name = null } = {}) {
  const options = { credentials: "same-origin", method: "GET", headers: {} };
  if (raw) {
    options.method = "POST";
    options.headers["Content-Type"] = "application/octet-stream";
    options.body = raw;
  } else if (body !== undefined) {
    options.method = "POST";
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  const url = name ? `${path}?name=${encodeURIComponent(name)}` : path;
  const response = await fetch(url, options);
  const answer = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = answer.detail;
    const error = new Error(typeof detail === "string" ? detail : "Det gick inte.");
    error.status = response.status;
    throw error;
  }
  return answer;
}

const number = value => new Intl.NumberFormat("sv-SE").format(value);
const plural = (count, one, many) => `${number(count)} ${count === 1 ? one : many}`;

function dates(meet) {
  const format = value => new Date(value + "T12:00:00").toLocaleDateString("sv-SE",
    { day: "numeric", month: "short", year: "numeric" });
  if (!meet.first_date && !meet.last_date) return "Inget datum";
  if (!meet.last_date || meet.first_date === meet.last_date) return format(meet.first_date);
  if (!meet.first_date) return format(meet.last_date);
  return `${format(meet.first_date)} – ${format(meet.last_date)}`;
}

function when(value) {
  return new Date(value).toLocaleString("sv-SE",
    { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

function days(list) {
  if (list.length === 7) return "Dagl";
  const indexes = list.map(day => DAYS.indexOf(day));
  const run = indexes.every((value, i) => i === 0 || value === indexes[i - 1] + 1);
  if (run && indexes.length > 2) return `${DAY_NAMES[indexes[0]]}–${DAY_NAMES[indexes.at(-1)]}`;
  return indexes.map(i => DAY_NAMES[i]).join(", ");
}

function level(value) {
  if (!value) return el("span", { class: "niva ingen" }, "Inget underlag");
  const names = { 1: "Minimum", 2: "Struktur", 3: "Exakt struktur", 4: "Facit" };
  return el("span", { class: "niva" }, `Nivå ${value} · ${names[value]}`);
}

let grouped = new Map();

/** The facts by ref, and grouped by the thing they are about (place:p5 and place:p5.phone). */
function setFacts() {
  facts = new Map(draft.facts.map(fact => [fact.ref, fact]));
  grouped = new Map();
  for (const fact of draft.facts) {
    const dot = fact.ref.indexOf(".", fact.ref.indexOf(":"));
    const base = dot < 0 ? fact.ref : fact.ref.slice(0, dot);
    if (!grouped.has(base)) grouped.set(base, []);
    grouped.get(base).push(fact);
  }
}

// --- Sources and certainty ----------------------------------------------------------------

/** The facts for a thing and its fields: place:p5 and place:p5.phone. */
function factsOf(ref) {
  return grouped.get(ref) ?? [];
}

function sourceKind(origin) {
  if (origin.source === "planner") return ["PLAN", "andrad", "Ändrat i Planering"];
  if (origin.source === "regelboken") return ["REGEL", "regel", "Regelboken"];
  const source = draft.sources.find(item => item.id === origin.source);
  return ["JSON", "", source ? source.filename : "Underlaget"];
}

function badges(ref) {
  const seen = new Map();
  for (const fact of factsOf(ref)) {
    for (const origin of fact.origins) {
      const [label, kind, title] = sourceKind(origin);
      if (!seen.has(label)) seen.set(label, el("span", { class: `kalla ${kind}`, title }, label));
    }
  }
  return seen.size ? [...seen.values()] : el("span", { class: "svag" }, "–");
}

function certainty(ref) {
  const fact = facts.get(ref);
  if (!fact) return el("span", { class: "svag" }, "–");
  const fields = factsOf(ref).filter(item => item !== fact);
  const shown = fields.some(item => item.certainty === "confirmed") ? "confirmed" : fact.certainty;
  return el("span", { class: "pill " + shown }, CERTAINTY[shown]);
}

function rowSources(ref) {
  return new Set(factsOf(ref).flatMap(fact => fact.origins.map(origin => origin.source)));
}

function rowCertainties(ref) {
  return new Set(factsOf(ref).map(fact => fact.certainty));
}

// --- Träffar ------------------------------------------------------------------------------

async function showMeets() {
  let meets;
  try {
    meets = await api(API + "/meets");
  } catch (error) {
    say(error.message);
    return;
  }
  $("meet-count").textContent = String(meets.length + 1);
  const rows = meets.map(summary => {
    const latest = summary.versions.at(-1);
    return el("tr", {},
      el("td", {}, el("a", { href: `/planering/${summary.meet.id}` }, summary.meet.name),
        el("div", { class: "liten" }, COUNTRIES[summary.meet.country] ?? summary.meet.country)),
      el("td", {}, dates(summary.meet)),
      el("td", {}, level(summary.level)),
      el("td", { class: "tal" }, summary.trains ? number(summary.trains) : "–"),
      el("td", {}, latest
        ? el("span", {}, `Version ${latest.number}`,
          el("span", { class: "liten" }, ` · ${when(latest.published)}`))
        : el("span", { class: "svag" }, "Ingen än")),
      el("td", { class: "tal" }, summary.questions ? String(summary.questions) : "–"));
  });
  rows.push(el("tr", {},
    el("td", {}, el("a", { href: "/provbanan" }, "Provbanan"),
      el("div", { class: "liten" }, "Inbyggd provbana")),
    el("td", { class: "svag" }, "Alltid"), el("td", { class: "svag" }, "–"),
    el("td", { class: "tal" }, "10"), el("td", {}, "Version 1"), el("td", { class: "tal" }, "–")));
  $("meets").replaceChildren(...rows);
}

function setUpMeets() {
  showMeets();
  $("new-meet")?.addEventListener("submit", async event => {
    event.preventDefault();
    const body = { name: $("new-name").value, country: $("new-country").value };
    if ($("new-first").value) body.first_date = $("new-first").value;
    if ($("new-last").value) body.last_date = $("new-last").value;
    try {
      const created = await api(API + "/meets", body);
      location.href = `/planering/${created.meet.id}`;
    } catch (error) {
      say(error.message);
    }
  });
}

// --- One meet -----------------------------------------------------------------------------

async function loadDraft() {
  try {
    draft = await api(`${API}/meets/${meetId}`);
  } catch (error) {
    $("meet-name").textContent = "Träffen finns inte";
    say(error.message);
    return false;
  }
  setFacts();
  $("meet-name").textContent = draft.meet.name;
  document.title = `${draft.meet.name} · Planering`;
  fillSwitch();
  return true;
}

async function fillSwitch() {
  try {
    const meets = await api(API + "/meets");
    const here = location.pathname.split("/").slice(3).join("/");
    $("switch-list").replaceChildren(...meets.map(summary => el("li", {},
      el("a", { href: `/planering/${summary.meet.id}${here ? "/" + here : ""}`,
        "aria-current": summary.meet.id === meetId ? "page" : null }, summary.meet.name))));
  } catch (error) {
    $("switch-list").replaceChildren();
  }
}

function placeName(id) {
  return draft?.package?.places.find(place => place.id === id)?.name ?? id;
}

// --- Data: the blocks ---------------------------------------------------------------------

const pending = [];
const undone = [];
let chosen = new Set(["places", "sections"]);
let selected = null;
let opened = new Set();

function value(kind, id, field, original) {
  for (let i = pending.length - 1; i >= 0; i--) {
    const edit = pending[i];
    if (edit.kind === kind && edit.id === id && edit.field === field) return edit.after;
  }
  return original;
}

function edit(kind, id, field, before, after) {
  if (before === after) return;
  pending.push({ kind, id, field, before, after });
  undone.length = 0;
  showData();
}

const trainName = train => [train.train_type, train.number].filter(Boolean).join(" ");

function calls() {
  const rows = [];
  for (const train of draft.package.trains) {
    train.calls.forEach((call, index) => rows.push({ train, call, index }));
  }
  return rows;
}

function callKind({ train, call, index }) {
  if (index === 0) return "Utgångsstation";
  if (index === train.calls.length - 1) return "Slutstation";
  if (!call.stops) return "Ej uppehåll";
  if (!call.exchange) return "Inget utbyte";
  return "Uppehåll";
}

function phoneCell(place) {
  const shown = value("place", place.id, "phone", place.phone ?? null);
  // The field opens on the chosen row; the others read as text (as in the sketch).
  if (!admin || selected?.ref !== `place:${place.id}`) return shown ?? "–";
  const input = el("input", { value: shown ?? "", inputmode: "tel", maxlength: "40",
    "aria-label": `Telefon ${place.name}`, placeholder: "–", class: "cell" });
  input.addEventListener("click", event => event.stopPropagation());
  input.addEventListener("change", () => {
    edit("place", place.id, "phone", shown, input.value.trim() || null);
  });
  input.addEventListener("keydown", event => { if (event.key === "Enter") input.blur(); });
  return input;
}

function selectCell(options, current, label, onChange) {
  const select = el("select", { "aria-label": label, class: "cell" },
    ...options.map(([key, text]) => el("option", { value: key }, text)));
  select.value = current;
  select.addEventListener("click", event => event.stopPropagation());
  select.addEventListener("change", () => onChange(select.value));
  return select;
}

function tracksCell(section) {
  const shown = value("tracks", section.id, "tracks", section.tracks);
  if (!admin) return TRACKS[shown];
  return selectCell(Object.entries(TRACKS), shown, "Spår",
    next => edit("tracks", section.id, "tracks", shown, next));
}

function modeCell(section) {
  const base = MODES[draft.meet.clearance_mode];
  const shown = value("section", section.id, "clearance_mode", section.clearance_mode ?? null);
  if (!admin) return shown ? MODES[shown] : `${base} (träffens)`;
  return selectCell([["", `${base} (träffens)`], ...Object.entries(MODES)], shown ?? "",
    "Klareringsläge", next => edit("section", section.id, "clearance_mode", shown, next || null));
}

function via(section) {
  const names = section.parts.slice(0, -1).map(part => placeName(part.to_place));
  return names.length ? "via " + names.join(", ") : "–";
}

function findingsFor(ref) {
  const id = ref.split(":")[1];
  return findings.filter(finding => finding.refs.includes(id));
}

const BLOCKS = [
  {
    key: "trains", label: "Tåg", text: "planens tåg, med trafikdagar och första och sista besök",
    rows: () => draft.package.trains,
    ref: train => `train:${train.id}`,
    places: train => train.calls.map(call => call.place),
    columns: [
      ["Tåg", train => el("b", {}, trainName(train))],
      ["Bolag", train => train.operator ?? "–"],
      ["Dagar", train => days(train.days)],
      ["Från", train => placeName(train.calls[0].place)],
      ["Avg", train => train.calls[0].departure ?? "–"],
      ["Till", train => placeName(train.calls.at(-1).place)],
      ["Ank", train => (train.calls.at(-1).arrival ?? "–") + (train.calls.at(-1).day_offset ? " +1" : "")],
      ["Besök", train => String(train.calls.length), "tal"],
    ],
    title: train => trainName(train),
    detail: train => [
      ["Bolag", train.operator ?? "–"],
      ["Dagar", days(train.days)],
      ["Isärhållning", train.service_key ?? "–"],
      ["Väg", train.calls.filter(call => call.stops).map(call => placeName(call.place)).join(" – ")],
    ],
  },
  {
    key: "calls", label: "Tågbesök", text: "varje tågs besök i tur och ordning",
    rows: () => calls(),
    ref: row => `call:${row.call.id}`,
    places: row => [row.call.place],
    columns: [
      ["Tåg", row => el("b", {}, trainName(row.train))],
      ["Driftplats", row => placeName(row.call.place)],
      ["Spår", row => row.call.track ?? "–"],
      ["Ank", row => (row.call.arrival ?? "") + (row.call.arrival && row.call.day_offset ? " +1" : "")],
      ["Avg", row => row.call.departure ?? ""],
      ["Sort", row => callKind(row)],
      ["Anmärkning", row => el("span", { class: "liten" }, row.call.note ?? "")],
    ],
    title: row => `${trainName(row.train)} · ${placeName(row.call.place)}`,
    detail: row => [
      ["Tåg", trainName(row.train)], ["Spår", row.call.track ?? "–"],
      ["Ankomst", row.call.arrival ?? "–"], ["Avgång", row.call.departure ?? "–"],
      ["Sort", callKind(row)], ["Anmärkning", row.call.note ?? "–"],
    ],
  },
  {
    key: "places", label: "Driftplatser",
    text: "planens platser; ett ställverk eller en handbox kopplas när den ansluter",
    rows: () => draft.package.places,
    ref: place => `place:${place.id}`,
    places: place => [place.id],
    columns: [
      ["Kod", place => el("span", { class: "kod" }, place.code)],
      ["Driftplats", place => place.name],
      ["Platstyp", place => el("span", {}, KINDS[place.kind] ?? place.kind,
        place.remote_from ? el("div", { class: "liten" }, "från " + placeName(place.remote_from)) : null)],
      ["Telefon", place => phoneCell(place)],
      ["Kopplad", () => el("span", { class: "svag" }, "–")],
      ["Spår", place => String(place.tracks.length), "tal"],
    ],
    title: place => `${place.code} · ${place.name}`,
    detail: place => [
      ["Platstyp", KINDS[place.kind] + (place.remote_from ? `, från ${placeName(place.remote_from)}` : "")],
      ["Telefon", value("place", place.id, "phone", place.phone ?? null) ?? "–"],
      ["Spår", place.tracks.map(track => track.name).join(" ") || "–"],
      ["Instruktioner", Object.values(place.instructions ?? {})[0] ?? "–"],
    ],
  },
  {
    key: "tracks", label: "Spår", text: "driftplatsernas spår i tidtabellen",
    rows: () => draft.package.places.flatMap(place => place.tracks.map(track => ({ place, track }))),
    ref: row => `place:${row.place.id}`,
    places: row => [row.place.id],
    columns: [
      ["Driftplats", row => row.place.name],
      ["Spår", row => el("b", {}, row.track.name)],
      ["Ordning", row => String(row.track.sort_order + 1), "tal"],
    ],
    title: row => `${row.place.name} · spår ${row.track.name}`,
    detail: row => [["Driftplats", row.place.name], ["Spår", row.track.name]],
  },
  {
    key: "sections", label: "Sträckor", text: "klareringssträckor mellan driftplatser",
    rows: () => draft.package.sections,
    ref: section => `section:${section.id}`,
    places: section => [section.place_a, section.place_b, ...section.parts.map(part => part.to_place)],
    columns: [
      ["Från", section => placeName(section.place_a)],
      ["Till", section => placeName(section.place_b)],
      ["Delsträckor", section => via(section)],
      ["Spår", section => tracksCell(section)],
      ["Klarering", section => modeCell(section)],
    ],
    title: section => `${placeName(section.place_a)} – ${placeName(section.place_b)}`,
    detail: section => [
      ["Spår", TRACKS[value("tracks", section.id, "tracks", section.tracks)]],
      ["Delsträckor", section.parts.map(part =>
        `${placeName(part.from_place)} – ${placeName(part.to_place)}`).join(" · ") || "–"],
      ["Driftplatser emellan", section.parts.slice(0, -1).map(part => placeName(part.to_place)).join(", ") || "–"],
    ],
  },
  {
    key: "parts", label: "Delsträckor", text: "de fysiska bitarna mellan platserna",
    rows: () => draft.package.sections.flatMap(section => section.parts.map(part => ({ section, part }))),
    ref: row => `part:${row.part.id}`,
    places: row => [row.part.from_place, row.part.to_place],
    columns: [
      ["Från", row => placeName(row.part.from_place)],
      ["Till", row => placeName(row.part.to_place)],
      ["Sträcka", row => `${placeName(row.section.place_a)} – ${placeName(row.section.place_b)}`],
    ],
    title: row => `${placeName(row.part.from_place)} – ${placeName(row.part.to_place)}`,
    detail: row => [["Sträcka", `${placeName(row.section.place_a)} – ${placeName(row.section.place_b)}`]],
  },
  {
    key: "duties", label: "Köruppdrag", text: "förarnas uppdrag, tåg för tåg",
    rows: () => draft.package.duties,
    ref: duty => `duty:${duty.id}`,
    places: duty => duty.legs.flatMap(leg => trainCalls(leg.train).map(call => call.place)),
    columns: [
      ["Uppdrag", duty => el("b", {}, duty.name)],
      ["Tåg", duty => duty.legs.map(leg => trainLabel(leg.train)).join(", ")],
      ["Delar", duty => String(duty.legs.length), "tal"],
    ],
    title: duty => `Köruppdrag ${duty.name}`,
    detail: duty => [["Tåg", duty.legs.map(leg => trainLabel(leg.train)).join(", ")]],
  },
  {
    key: "turns", label: "Omlopp", text: "fordonens omlopp",
    rows: () => draft.package.turns,
    ref: turn => `turn:${turn.id}`,
    places: turn => turn.trains.flatMap(id => trainCalls(id).map(call => call.place)),
    columns: [
      ["Omlopp", turn => el("b", {}, turn.name)],
      ["Tåg", turn => turn.trains.map(trainLabel).join(", ")],
    ],
    title: turn => `Omlopp ${turn.name}`,
    detail: turn => [["Tåg", turn.trains.map(trainLabel).join(", ")]],
  },
  {
    key: "shunting", label: "Växling", text: "växlingsuppdrag på driftplatserna",
    rows: () => draft.package.shunting,
    ref: task => `shunting:${task.id}`,
    places: task => [task.place],
    columns: [
      ["Driftplats", task => placeName(task.place)],
      ["Uppdrag", task => el("b", {}, task.name)],
      ["Tid", task => task.time ?? "–"],
      ["Beskrivning", task => task.description ?? ""],
    ],
    title: task => `Växling ${task.name}`,
    detail: task => [["Driftplats", placeName(task.place)], ["Beskrivning", task.description ?? "–"]],
  },
  {
    key: "types", label: "Tågslag", text: "regelboken: tågslagen och förkortningarna",
    rows: () => draft.rulebook.train_types,
    ref: rule => `train_type:${rule.code}`,
    places: () => [],
    columns: [
      ["Förkortning", rule => el("span", { class: "kod" }, rule.code)],
      ["Tågslag i underlaget", rule => rule.names.join(", ") || "–"],
      ["Kör", rule => rule.content ? CONTENT[rule.content] : el("span", { class: "osaker" }, "Okänt")],
    ],
    title: rule => `Tågslaget ${rule.code}`,
    detail: rule => [["Namn", rule.names.join(", ") || "–"], ["Kör", CONTENT[rule.content] ?? "Okänt"]],
  },
  {
    key: "sources", label: "Underlag", text: "filerna träffen bygger på, som de kom",
    rows: () => draft.sources,
    ref: source => `source:${source.id}`,
    places: () => [],
    columns: [
      ["Fil", source => admin
        ? el("a", { href: `${API}/meets/${meetId}/sources/${source.id}` }, source.filename)
        : source.filename],
      ["Slag", () => el("span", { class: "kalla" }, "JSON")],
      ["Nivå", source => level(source.level)],
      ["Storlek", source => `${number(Math.round(source.size / 1024))} kB`, "tal"],
      ["Läst", source => when(source.added)],
    ],
    title: source => source.filename,
    detail: () => reportLines(),
  },
  {
    key: "check", label: "Kontroll", text: "trafikkontrollens fynd; de stoppar inte publiceringen",
    rows: () => [...findings, ...draft.questions.filter(question => question.answer === null)
      .map(question => ({ id: question.id, severity: "question", message: question.message, refs: [], question }))],
    ref: finding => `finding:${finding.id}`,
    places: finding => finding.refs,
    columns: [
      ["Fynd", finding => el("span", { class: "pill " + finding.severity },
        { conflict: "Konflikt", observation: "Iakttagelse", question: "Fråga" }[finding.severity])],
      ["", finding => finding.message],
    ],
    title: finding => ({ conflict: "Konflikt", observation: "Iakttagelse", question: "Fråga" })[finding.severity],
    detail: finding => [["Fynd", finding.message], ["Gäller", finding.refs.map(refName).join(", ") || "–"]],
  },
];

/** A finding's ref as a name: a place, a train or a call. */
function refName(id) {
  const place = draft.package.places.find(item => item.id === id);
  if (place) return place.name;
  const train = draft.package.trains.find(item => item.id === id);
  if (train) return trainName(train);
  return id;
}

function trainCalls(id) {
  return draft.package.trains.find(train => train.id === id)?.calls ?? [];
}

function trainLabel(id) {
  const train = draft.package.trains.find(item => item.id === id);
  return train ? trainName(train) : id;
}

function reportLines() {
  const report = draft.report;
  if (!report) return [];
  const placeCount = Object.values(report.places).reduce((sum, value) => sum + value, 0);
  const kinds = Object.entries(report.places)
    .map(([kind, count]) => `${count} ${KINDS_MANY[kind] ?? kind}`).join(", ");
  return [
    ["Gav", `${plural(placeCount, "driftplats", "driftplatser")} (${kinds}), ` +
      `${plural(report.sections, "klareringssträcka", "klareringssträckor")}, ` +
      `${plural(report.trains, "tåg", "tåg")} med ${plural(report.calls, "besök", "besök")}, ` +
      `${plural(report.duties, "köruppdrag", "köruppdrag")}, ${plural(report.turns, "omlopp", "omlopp")}, ` +
      `${plural(report.shunting, "växlingsuppdrag", "växlingsuppdrag")}`],
    ["Reglerna", report.notes.length ? el("ul", { class: "punkter" },
      ...report.notes.map(note => el("li", {}, note))) : "Inget särskilt."],
    ["Lästes inte", el("ul", { class: "punkter" },
      ...report.left_out.map(note => el("li", {}, note)),
      el("li", {}, "Deltagare, fordonsbidrag och ägare är personuppgifter och läses aldrig."))],
  ];
}

// --- Data: drawing ------------------------------------------------------------------------

function matches(block, row, filters) {
  const ref = block.ref(row);
  if (filters.place && !block.places(row).includes(filters.place)) return false;
  if (filters.source && !rowSources(ref).has(filters.source)) return false;
  if (filters.certainty && !rowCertainties(ref).has(filters.certainty)) return false;
  if (filters.search) {
    const text = block.columns.map(([, cell]) => {
      const shown = cell(row);
      return typeof shown === "string" ? shown : shown?.value ?? shown?.textContent ?? "";
    }).join(" ").toLowerCase();
    if (!text.includes(filters.search)) return false;
  }
  return true;
}

function filters() {
  return {
    search: $("search").value.trim().toLowerCase(),
    place: $("filter-place").value,
    source: $("filter-source").value,
    certainty: $("filter-certainty").value,
  };
}

function showChips() {
  const all = BLOCKS.every(block => chosen.has(block.key));
  const chips = [el("button", { type: "button", class: "chip", "aria-pressed": all ? "true" : "false",
    onclick: () => { chosen = all ? new Set(["places"]) : new Set(BLOCKS.map(b => b.key)); showData(); },
  }, "Alla")];
  for (const block of BLOCKS) {
    const count = block.rows().length;
    const extra = block.key === "check"
      ? (findings.some(finding => finding.severity === "conflict") ? " fel" : count ? " varning" : "")
      : "";
    chips.push(el("button", {
      type: "button", class: "chip" + extra, "aria-pressed": chosen.has(block.key) ? "true" : "false",
      onclick: () => {
        if (chosen.has(block.key) && chosen.size > 1) chosen.delete(block.key);
        else chosen.add(block.key);
        showData();
      },
    }, block.key === "check" ? `${block.label} ` : el("b", {}, number(count) + " "),
    block.key === "check" ? el("b", {}, number(count)) : block.label));
  }
  $("blocks").replaceChildren(...chips);
}

function showTables() {
  const given = filters();
  let total = 0;
  const sections = [];
  for (const block of BLOCKS.filter(item => chosen.has(item.key))) {
    const all = block.rows();
    const rows = all.filter(row => matches(block, row, given));
    total += rows.length;
    const limit = opened.has(block.key) ? rows.length : SHOWN;
    const body = rows.slice(0, limit).map(row => {
      const ref = block.ref(row);
      const marked = findingsFor(ref).length;
      return el("tr", {
        class: (selected?.ref === ref ? "vald-rad" : "") + (marked ? " markerad" : ""),
        onclick: () => { selected = { block: block.key, ref, row }; showData(); },
      },
      ...block.columns.map(([, cell, cls]) => el("td", { class: cls }, cell(row))),
      el("td", {}, badges(ref)),
      el("td", {}, certainty(ref)));
    });
    if (!body.length) {
      body.push(el("tr", {}, el("td", { colspan: block.columns.length + 2, class: "tom" },
        all.length ? "Inget som passar filtret." : "Inget här än.")));
    }
    sections.push(el("section", { class: "block" },
      el("h3", {}, block.label, el("span", { class: "liten" },
        ` ${number(rows.length)} av ${number(all.length)} · ${block.text}`)),
      el("div", { class: "rulla" }, el("table", { class: "tabell" },
        el("thead", {}, el("tr", {}, ...block.columns.map(([name, , cls]) => el("th", { class: cls }, name)),
          el("th", {}, "Källa"), el("th", {}, "Säkerhet"))),
        el("tbody", {}, ...body))),
      rows.length > limit ? el("button", { type: "button", class: "lank visa-fler",
        onclick: () => { opened.add(block.key); showData(); } }, `Visa alla ${number(rows.length)}`) : null));
  }
  $("tables").replaceChildren(...sections);
  $("row-count").textContent = `${plural(total, "rad", "rader")}` +
    (pending.length ? ` · ${plural(pending.length, "osparad ändring", "osparade ändringar")}` : "");
}

function origins(ref) {
  return factsOf(ref).flatMap(fact => fact.origins.map(origin => {
    const [label, kind] = sourceKind(origin);
    const field = fact.ref === ref ? "" : ` (${fact.ref.slice(ref.length + 1)})`;
    return el("li", {}, el("span", { class: `kalla ${kind}` }, label),
      el("span", {}, origin.at + field, fact.note ? el("div", { class: "liten" }, fact.note) : null),
      el("span", { class: "pill " + fact.certainty }, CERTAINTY[fact.certainty]));
  }));
}

function questionsFor(ref) {
  return draft.questions.filter(question => question.refs.includes(ref));
}

function showDetail() {
  const aside = $("detail");
  if (!selected) {
    aside.hidden = true;
    return;
  }
  const block = BLOCKS.find(item => item.key === selected.block);
  const fact = facts.get(selected.ref);
  const label = { trains: "Valt tåg", calls: "Valt tågbesök", places: "Vald driftplats",
    tracks: "Valt spår", sections: "Vald sträcka", parts: "Vald delsträcka", duties: "Valt köruppdrag",
    turns: "Valt omlopp", shunting: "Vald växling", types: "Valt tågslag", sources: "Valt underlag",
    check: "Valt fynd" }[block.key];
  const asked = questionsFor(selected.ref);
  const flagged = findingsFor(selected.ref);
  aside.hidden = false;
  aside.replaceChildren(...[
    el("header", {}, el("span", { class: "overrubrik" }, label),
      fact ? el("span", { class: "pill " + fact.certainty }, CERTAINTY[fact.certainty]) : null,
      el("button", { type: "button", class: "ikon", "aria-label": "Stäng",
        onclick: () => { selected = null; showData(); } }, "×")),
    el("h2", {}, block.title(selected.row)),
    el("dl", {}, ...block.detail(selected.row).flatMap(([name, shown]) =>
      [el("dt", {}, name), el("dd", {}, shown)])),
    ...flagged.map(finding => el("div", { class: "att-kolla" },
      el("b", {}, finding.severity === "conflict" ? "▲ Konflikt" : "Iakttagelse"),
      el("p", {}, finding.message))),
    ...asked.map(question => el("div", { class: "att-kolla" },
      el("b", {}, "▲ Att kolla"), el("p", {}, question.message),
      el("div", { class: "svar" }, ...question.alternatives.map(alternative => admin
        ? el("button", { type: "button", "aria-pressed": question.answer === alternative.value ? "true" : "false",
          onclick: () => answer(question.id, alternative.value) }, alternative.label)
        : (question.answer === alternative.value ? el("b", {}, alternative.label) : null))))),
    factsOf(selected.ref).length
      ? el("div", { class: "varifran" }, el("p", { class: "overrubrik" }, "Varifrån"),
        el("ul", {}, ...origins(selected.ref)))
      : null].filter(Boolean));
}

async function answer(question, given) {
  try {
    draft = await api(`${API}/meets/${meetId}/answers`, { question, value: given });
    setFacts();
    say("Svaret är sparat i regelboken.", true);
    showData();
  } catch (error) {
    say(error.message);
  }
}

function showEditing() {
  if (!admin) return;
  $("undo").disabled = !pending.length;
  $("redo").disabled = !undone.length;
  $("save").disabled = !pending.length;
}

function showData() {
  showChips();
  showTables();
  showDetail();
  showEditing();
}

function fillFilters() {
  const keep = id => $(id).value;
  const place = keep("filter-place"), source = keep("filter-source"), sure = keep("filter-certainty");
  $("filter-place").replaceChildren(el("option", { value: "" }, "Alla driftplatser"),
    ...draft.package.places.map(item => el("option", { value: item.id }, `${item.name} (${item.code})`)));
  $("filter-source").replaceChildren(el("option", { value: "" }, "Alla underlag"),
    ...draft.sources.map(item => el("option", { value: item.id }, item.filename)),
    el("option", { value: "planner" }, "Ändrat i Planering"),
    el("option", { value: "regelboken" }, "Regelboken"));
  $("filter-certainty").replaceChildren(el("option", { value: "" }, "Alla säkerheter"),
    ...Object.entries(CERTAINTY).map(([key, text]) => el("option", { value: key }, text)));
  $("filter-place").value = place;
  $("filter-source").value = source;
  $("filter-certainty").value = sure;
}

async function loadAround() {
  try {
    [{ findings }, versions] = await Promise.all([
      api(`${API}/meets/${meetId}/check`), api(`${API}/meets/${meetId}/versions`)]);
  } catch (error) {
    findings = [];
    versions = [];
  }
  const latest = versions.at(-1);
  $("draft-badge").textContent = latest ? `Utkast · bygger på version ${latest.number}` : "Utkast";
}

async function showDataPage() {
  await loadAround();
  const empty = !draft.package;
  $("empty").hidden = !empty;
  $("data").hidden = empty;
  if (empty) return;
  fillFilters();
  showData();
}

async function save() {
  const changes = [];
  for (const item of pending) {
    if (item.kind === "place") changes.push({ place: item.id, phone: item.after });
    else if (item.kind === "tracks") changes.push({ section: item.id, tracks: item.after });
    else changes.push({ section: item.id, clearance_mode: item.after });
  }
  $("save").disabled = true;
  try {
    draft = await api(`${API}/meets/${meetId}/changes`, { changes });
    setFacts();
    pending.length = 0;
    undone.length = 0;
    say(changes.length === 1 ? "Ändringen är sparad." : `${number(changes.length)} ändringar är sparade.`, true);
    await showDataPage();
  } catch (error) {
    say(error.message);
    showEditing();
  }
}

function setUpData() {
  for (const id of ["search", "filter-place", "filter-source", "filter-certainty"]) {
    $(id).addEventListener("input", () => { opened = new Set(); showData(); });
  }
  $("clear").addEventListener("click", () => {
    for (const id of ["search", "filter-place", "filter-source", "filter-certainty"]) $(id).value = "";
    showData();
  });
  if (admin) {
    $("undo").addEventListener("click", () => { if (pending.length) undone.push(pending.pop()); showData(); });
    $("redo").addEventListener("click", () => { if (undone.length) pending.push(undone.pop()); showData(); });
    $("save").addEventListener("click", save);
    window.addEventListener("beforeunload", event => {
      if (pending.length) event.preventDefault();
    });
    setUpDrawer();
  }
  showDataPage();
}

// --- Lägg till underlag -------------------------------------------------------------------

let waiting = null;

function openDrawer() {
  waiting = null;
  $("files").replaceChildren();
  $("preview").hidden = true;
  $("apply").disabled = true;
  $("drawer").hidden = false;
}

function closeDrawer() {
  $("drawer").hidden = true;
}

function describe(preview) {
  const parts = [];
  const things = [["trains", "tåg", "tåg"], ["places", "driftplats", "driftplatser"],
    ["sections", "sträcka", "sträckor"], ["lines", "linje i grafen", "linjer i grafen"]];
  if (preview.first) {
    return "Allt är nytt: " + things.filter(([key]) => preview[key].added).map(([key, one, many]) =>
      plural(preview[key].added, one, many)).join(", ") + ".";
  }
  for (const [key, one, many] of things) {
    const diff = preview[key];
    if (diff.added) parts.push(`${plural(diff.added, one, many)} nya`);
    if (diff.removed) parts.push(`${plural(diff.removed, one, many)} borta`);
    if (diff.changed) parts.push(`${plural(diff.changed, one, many)} ändrade`);
  }
  if (preview.times) parts.push(`${plural(preview.times, "tid", "tider")} ändrade`);
  if (preview.tracks) parts.push(`${plural(preview.tracks, "spår", "spår")} ändrade`);
  if (preview.questions) parts.push(plural(preview.questions, "fråga", "frågor"));
  let text = parts.length ? parts.join(" · ") + "." : "Inget ändras: filen ger samma utkast.";
  if (preview.kept) text += ` ${plural(preview.kept, "ändring", "ändringar")} från Planering står kvar.`;
  return text;
}

async function readFile(file) {
  const status = el("span", { class: "pill likely" }, "Läser …");
  $("files").replaceChildren(el("li", {}, el("span", { class: "kalla" }, "JSON"),
    el("div", {}, el("b", {}, file.name), el("div", { class: "liten" }, "Stefans plan")), status));
  $("preview").hidden = true;
  $("apply").disabled = true;
  try {
    const preview = await api(`${API}/meets/${meetId}/sources`, undefined, { raw: file, name: file.name });
    waiting = preview.source.id;
    const report = preview.report;
    const places = Object.values(report.places).reduce((sum, value) => sum + value, 0);
    $("files").replaceChildren(el("li", {}, el("span", { class: "kalla" }, "JSON"),
      el("div", {}, el("b", {}, file.name), el("div", { class: "liten" },
        `Stefans plan · ${plural(report.trains, "tåg", "tåg")} · ` +
        `${plural(places, "driftplats", "driftplatser")} · ${plural(report.sections, "sträcka", "sträckor")}`)),
      el("span", { class: "pill sure" }, "Läst")));
    $("levels").replaceChildren(...LEVELS.map(([step, name]) =>
      el("div", { class: step <= report.level ? "fylld" : "" }, el("i"), `${step} ${name}`)));
    $("changes").textContent = describe(preview);
    $("preview").hidden = false;
    $("apply").disabled = false;
  } catch (error) {
    status.className = "pill conflict";
    status.textContent = "Gick inte";
    say(error.message);
  }
}

function setUpDrawer() {
  for (const id of ["add-source", "add-first"]) $(id)?.addEventListener("click", openDrawer);
  for (const node of document.querySelectorAll("[data-close]")) node.addEventListener("click", closeDrawer);
  document.addEventListener("keydown", event => {
    if (event.key === "Escape" && !$("drawer").hidden) closeDrawer();
  });
  $("file").addEventListener("change", () => { if ($("file").files[0]) readFile($("file").files[0]); });
  const drop = $("drop");
  drop.addEventListener("dragover", event => { event.preventDefault(); drop.classList.add("over"); });
  drop.addEventListener("dragleave", () => drop.classList.remove("over"));
  drop.addEventListener("drop", event => {
    event.preventDefault();
    drop.classList.remove("over");
    const file = event.dataTransfer.files[0];
    if (file) readFile(file);
  });
  $("apply").addEventListener("click", async () => {
    if (!waiting) return;
    $("apply").disabled = true;
    try {
      draft = await api(`${API}/meets/${meetId}/sources/${waiting}/apply`, {});
      setFacts();
      closeDrawer();
      say("Underlaget är inlagt i utkastet.", true);
      selected = null;
      await showDataPage();
    } catch (error) {
      say(error.message);
      $("apply").disabled = false;
    }
  });
}

// --- Versioner ----------------------------------------------------------------------------

async function showVersions() {
  let check, list;
  try {
    [check, list] = await Promise.all([
      api(`${API}/meets/${meetId}/check`), api(`${API}/meets/${meetId}/versions`)]);
  } catch (error) {
    say(error.message);
    return;
  }
  $("findings").replaceChildren(...(draft.package
    ? (check.findings.length
      ? check.findings.map(finding => el("li", {},
        el("span", { class: "pill " + finding.severity },
          finding.severity === "conflict" ? "Konflikt" : "Iakttagelse"),
        el("span", {}, finding.message)))
      : [el("li", { class: "tom" }, "Inga fynd.")])
    : [el("li", { class: "tom" }, "Lägg till underlag under Data först.")]));
  const next = (list.at(-1)?.number ?? 0) + 1;
  if ($("publish")) {
    $("publish").disabled = !draft.package;
    $("publish").textContent = `Publicera version ${next}`;
    $("publish-text").textContent = draft.package
      ? "Utkastet fryses som en ny version. Den ändras aldrig." : "";
  }
  if (!list.length) {
    $("versions").replaceChildren(el("tr", {},
      el("td", { colspan: 6, class: "tom" }, "Ingen version är publicerad än.")));
    return;
  }
  $("versions").replaceChildren(...list.slice().reverse().map(version => el("tr", {},
    el("td", {}, el("b", {}, `Version ${version.number}`)),
    el("td", {}, when(version.published)),
    el("td", { class: "tal" }, String(version.conflicts)),
    el("td", { class: "tal" }, String(version.observations)),
    el("td", { class: "kod", title: version.checksum }, version.checksum.slice(0, 12)),
    el("td", {}, el("a", {
      href: `/drift?traff=${encodeURIComponent(meetId)}&version=${version.number}#ny-traff`,
    }, "Kör i Drift →")))));
}

function setUpVersions() {
  showVersions();
  $("publish")?.addEventListener("click", async () => {
    $("publish").disabled = true;
    try {
      const version = await api(`${API}/meets/${meetId}/versions`, {});
      say(`Version ${version.number} är publicerad.`, true);
    } catch (error) {
      say(error.message);
    }
    await showVersions();
  });
}

// --- Bana ---------------------------------------------------------------------------------

let mapChoice = null;

/** A section's short name: the plan's number for its clearance section. */
function sectionLabel(section) {
  return section.source_ids?.planning_json ?? section.id;
}

function originList(ref) {
  const found = factsOf(ref);
  if (!found.length) return null;
  return el("div", { class: "varifran" }, el("p", { class: "overrubrik" }, "Varifrån"),
    el("ul", {}, ...origins(ref)));
}

async function saveNow(change, text) {
  try {
    draft = await api(`${API}/meets/${meetId}/changes`, { changes: [change] });
    setFacts();
    say(text, true);
    showMap();
  } catch (error) {
    say(error.message);
  }
}

function sectionChoice(section) {
  const between = section.parts.slice(0, -1).map(part => {
    const place = draft.package.places.find(item => item.id === part.to_place);
    return `${place.name} (${KINDS[place.kind].toLowerCase()})`;
  });
  const base = MODES[draft.meet.clearance_mode];
  const tracks = admin
    ? el("div", { class: "segment" }, ...Object.entries(TRACKS).map(([key, text]) =>
      el("button", { type: "button", "aria-pressed": section.tracks === key ? "true" : "false",
        onclick: () => section.tracks !== key && saveNow({ section: section.id, tracks: key },
          `${placeName(section.place_a)} – ${placeName(section.place_b)} är ${text.toLowerCase()}spår.`),
      }, text)))
    : TRACKS[section.tracks] + "spår";
  const mode = admin
    ? selectCell([["", `${base} (träffens grundläge)`], ...Object.entries(MODES)],
      section.clearance_mode ?? "", "Klarering",
      next => saveNow({ section: section.id, clearance_mode: next || null }, "Klareringsläget är sparat."))
    : (section.clearance_mode ? MODES[section.clearance_mode] : `${base} (träffens grundläge)`);
  const fact = facts.get(`section:${section.id}`);
  return [
    el("header", {}, el("span", { class: "overrubrik" }, "Vald sträcka"),
      fact ? el("span", { class: "pill " + fact.certainty }, CERTAINTY[fact.certainty]) : null),
    el("h2", {}, `${sectionLabel(section)} · ${placeName(section.place_a)} – ${placeName(section.place_b)}`),
    el("dl", {},
      el("dt", {}, "Spår"), el("dd", {}, tracks),
      el("dt", {}, "Klarering"), el("dd", {}, mode),
      el("dt", {}, "Delsträckor"), el("dd", {}, section.parts.map(part =>
        `${placeName(part.from_place)} – ${placeName(part.to_place)}`).join(" · ")),
      el("dt", {}, "Driftplatser emellan"), el("dd", {}, between.join(", ") || "Inga"),
      el("dt", {}, "Sidor och utfarter"), el("dd", { class: "liten" },
        "Kommer från stationernas utsida när ställverken ansluter.")),
    originList(`section:${section.id}`),
  ];
}

function placeChoice(place) {
  const fact = facts.get(`place:${place.id}`);
  const sections = draft.package.sections.filter(section =>
    section.place_a === place.id || section.place_b === place.id);
  return [
    el("header", {}, el("span", { class: "overrubrik" }, "Vald driftplats"),
      fact ? el("span", { class: "pill " + fact.certainty }, CERTAINTY[fact.certainty]) : null),
    el("h2", {}, `${place.code} · ${place.name}`),
    el("dl", {},
      el("dt", {}, "Platstyp"), el("dd", {}, KINDS[place.kind] +
        (place.remote_from ? `, från ${placeName(place.remote_from)}` : "")),
      el("dt", {}, "Telefon"), el("dd", {}, place.phone ?? "–"),
      el("dt", {}, "Spår"), el("dd", {}, place.tracks.map(track => track.name).join(" ") || "–"),
      el("dt", {}, "Sträckor"), el("dd", {}, sections.map(section =>
        `${placeName(section.place_a)} – ${placeName(section.place_b)}`).join(" · ") || "Inga")),
    originList(`place:${place.id}`),
  ];
}

function showMap() {
  const unsure = new Set(draft.facts.filter(fact => fact.certainty === "unsure").map(fact => fact.ref));
  TrainMeetMap.draw($("map"), draft.package, {
    selected: mapChoice,
    label: sectionLabel,
    unsure,
    onSelect: (kind, id) => { mapChoice = { kind, id }; showMap(); },
  });
  const places = draft.package.places.length, sections = draft.package.sections.length;
  $("map-count").textContent = `${plural(sections, "sträcka", "sträckor")} · ${plural(places, "driftplats", "driftplatser")}`;
  const section = mapChoice?.kind === "section"
    && draft.package.sections.find(item => item.id === mapChoice.id);
  const place = mapChoice?.kind === "place" && draft.package.places.find(item => item.id === mapChoice.id);
  $("choice").replaceChildren(...(section ? sectionChoice(section) : place ? placeChoice(place)
    : [el("p", { class: "liten" }, "Välj en sträcka eller en driftplats på kartan.")]).filter(Boolean));
  const doubtful = [...unsure].filter(ref => ref.startsWith("place:") || ref.startsWith("section:"));
  $("unsure").hidden = !doubtful.length;
  if (doubtful.length) {
    $("unsure").replaceChildren(el("b", {}, `▲ ${plural(doubtful.length, "uppgift", "uppgifter")} är osäkra.`),
      " Kontrollera dem under Data, med filtret Osäker.");
  }
}

function setUpMap() {
  if (!draft.package) {
    $("empty").hidden = false;
    return;
  }
  $("map-page").hidden = false;
  showMap();
}

// --- Graf ---------------------------------------------------------------------------------

const DAY_FULL = { mon: "Måndag", tue: "Tisdag", wed: "Onsdag", thu: "Torsdag", fri: "Fredag",
  sat: "Lördag", sun: "Söndag" };
const ZOOM = [1, 2, 3, 4, 6, 8];
const graph = { line: null, day: null, zoom: 3, lines: [], kinds: new Map(), marks: [] };

/** The check's findings as marks in the graph: a ring at a moment, or a band between places. */
function graphMarks(found) {
  const calls = new Map();
  for (const train of draft.package.trains) {
    for (const call of train.calls) calls.set(call.id, { train, call });
  }
  return found.map((finding, index) => {
    const mark = { number: index + 1, severity: finding.severity, finding };
    if (finding.code === "no_section") {
      mark.from = finding.refs[0];
      mark.to = finding.refs[1];
    } else if (finding.code === "track_conflict") {
      const hit = calls.get(finding.refs[1]);
      const { arrival, departure } = TrainMeetGraph.times(hit?.call ?? {});
      mark.place = finding.refs[0];
      mark.minute = arrival ?? departure;
      mark.days = hit?.train.days ?? [];
    }
    return mark;
  });
}

function onLine(mark, line) {
  if (mark.from !== undefined) return line.places.includes(mark.from) && line.places.includes(mark.to);
  return mark.place !== undefined && line.places.includes(mark.place);
}

function drawGraph(keepTime = null) {
  const line = graph.lines.find(item => item.id === graph.line);
  const scroll = document.querySelector(".graf-rulla");
  const middle = keepTime ?? (scroll && graph.drawnZoom
    ? (scroll.scrollLeft + scroll.clientWidth / 2) / graph.drawnZoom : null);
  const marks = graph.marks.filter(mark => !mark.days || mark.days.includes(graph.day));
  const drawn = TrainMeetGraph.draw($("graph"), draft.package,
    { line, day: graph.day, kinds: graph.kinds, marks, perMinute: ZOOM[graph.zoom] });
  graph.drawnZoom = ZOOM[graph.zoom];
  const area = document.querySelector(".graf-rulla");
  const start = TrainMeetGraph.minutes(draft.package.clock.start_time) ?? 360;
  // First time: the clock's start, where the game begins (the night before stands to the left).
  const target = middle ?? Math.max(0, start - 30) + area.clientWidth / 2 / ZOOM[graph.zoom];
  area.scrollLeft = Math.max(0, target * ZOOM[graph.zoom] - area.clientWidth / 2);
  $("graph-count").textContent = `${plural(drawn.trains, "tåg", "tåg")} på ` +
    `${DAY_FULL[graph.day].toLowerCase()} på ${line.name} · dra i sidled för resten av dygnet`;
  $("graph-findings").replaceChildren(...(graph.marks.length
    ? graph.marks.map(mark => el("li", { class: onLine(mark, line) ? "" : "annan" },
      el("span", { class: "pill " + mark.severity },
        mark.severity === "conflict" ? "Konflikt" : "Iakttagelse"),
      el("p", {}, mark.finding.message),
      onLine(mark, line) ? null : el("p", { class: "liten" }, "Inte på den här linjen.")))
    : [el("li", { class: "tom" }, "Inga fynd.")]));
}

function graphControls() {
  $("days").replaceChildren(...TrainMeetGraph.trafficDays(draft.package).map(day =>
    el("button", { type: "button", "aria-pressed": day === graph.day ? "true" : "false",
      onclick: () => { graph.day = day; graphControls(); drawGraph(); } }, DAY_FULL[day])));
}

function printGraph(lines) {
  const host = $("print");
  host.replaceChildren();
  for (const line of lines) {
    const page = el("section", { class: "utskriftssida" },
      el("h1", {}, `${draft.meet.name} · ${line.name} · ${DAY_FULL[graph.day]}`));
    const sheet = el("div");
    page.append(sheet);
    host.append(page);
    TrainMeetGraph.draw(sheet, draft.package, { line, day: graph.day, kinds: graph.kinds,
      marks: graph.marks.filter(mark => !mark.days || mark.days.includes(graph.day)),
      perMinute: 1, compact: true, height: 780 });
  }
  window.print();
}

async function setUpGraph() {
  if (!draft.package) {
    $("empty").hidden = false;
    return;
  }
  $("graph-page").hidden = false;
  graph.lines = TrainMeetGraph.lines(draft.package);
  graph.line = graph.lines[0].id;
  graph.day = TrainMeetGraph.trafficDays(draft.package)[0];
  graph.kinds = new Map(draft.rulebook.train_types.map(rule => [rule.code, rule.content]));
  try {
    graph.marks = graphMarks((await api(`${API}/meets/${meetId}/check`)).findings);
  } catch (error) {
    graph.marks = [];
  }
  $("line").replaceChildren(...graph.lines.map(line => el("option", { value: line.id }, line.name)));
  $("line").addEventListener("change", () => { graph.line = $("line").value; drawGraph(); });
  $("zoom-in").addEventListener("click", () => {
    graph.zoom = Math.min(graph.zoom + 1, ZOOM.length - 1);
    drawGraph();
  });
  $("zoom-out").addEventListener("click", () => {
    graph.zoom = Math.max(graph.zoom - 1, 0);
    drawGraph();
  });
  $("print-line").addEventListener("click",
    () => printGraph(graph.lines.filter(line => line.id === graph.line)));
  $("print-all").addEventListener("click", () => printGraph(graph.lines));
  graphControls();
  drawGraph(null);
  // Drag the sheet sideways with the mouse, as in the old graph.
  const area = document.querySelector("#graph");
  let dragging = null;
  area.addEventListener("pointerdown", event => {
    const scroll = document.querySelector(".graf-rulla");
    if (!scroll || event.button !== 0) return;
    dragging = { x: event.clientX, left: scroll.scrollLeft };
  });
  window.addEventListener("pointermove", event => {
    if (!dragging) return;
    document.querySelector(".graf-rulla").scrollLeft = dragging.left - (event.clientX - dragging.x);
  });
  window.addEventListener("pointerup", () => { dragging = null; });
}

// --- Start --------------------------------------------------------------------------------

$("logout")?.addEventListener("click", async () => {
  await fetch("/api/hub/logout", { method: "POST", credentials: "same-origin" });
  location.reload();
});

(async () => {
  if (page === "traffar") {
    setUpMeets();
    return;
  }
  if (!(await loadDraft())) return;
  if (page === "data") setUpData();
  else if (page === "bana") setUpMap();
  else if (page === "graf") setUpGraph();
  else if (page === "versioner") setUpVersions();
})();
