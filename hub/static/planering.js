// Planering (steg 4a): Träffar, and per meet Underlag, Data and Versioner, filled from
// Planeringens API. The session is an HttpOnly cookie this page never sees; without it the
// page only looks (S1).
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
const CERTAINTY = { sure: "Säker", likely: "Trolig", unsure: "Osäker", confirmed: "Bekräftad" };
const CONTENT = { passengers: "Resande", goods: "Gods", service: "Tjänst" };
const MODES = { requested: "Begärd", direct: "Direkt" };
const COUNTRIES = { se: "Sverige", dk: "Danmark", no: "Norge", de: "Tyskland" };
const DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
const DAY_NAMES = ["Mån", "Tis", "Ons", "Tor", "Fre", "Lör", "Sön"];
const LEVELS = { 1: "Minimum", 2: "Struktur", 3: "Exakt struktur", 4: "Facit" };

let draft = null;
let facts = new Map();

function el(tag, attributes = {}, ...children) {
  const node = document.createElement(tag);
  for (const [name, value] of Object.entries(attributes)) {
    if (value === undefined || value === null || value === false) continue;
    if (name === "class") node.className = value;
    else if (name.startsWith("on")) node.addEventListener(name.slice(2), value);
    else node.setAttribute(name, value === true ? "" : value);
  }
  for (const child of children) if (child !== null && child !== undefined) node.append(child);
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
  if (run && indexes.length > 2) {
    return `${DAY_NAMES[indexes[0]]}–${DAY_NAMES[indexes.at(-1)]}`;
  }
  return indexes.map(i => DAY_NAMES[i]).join(", ");
}

function level(value) {
  if (!value) return el("span", { class: "niva ingen" }, "Inget underlag");
  return el("span", { class: "niva" }, `Nivå ${value} · ${LEVELS[value]}`);
}

function certainty(ref) {
  const fact = facts.get(ref);
  if (!fact) return el("span", { class: "svag" }, "–");
  const where = fact.origins.map(origin => {
    if (origin.source === "planner") return "Ändrad i Planering";
    if (origin.source === "regelboken") return "Regelboken: " + origin.at;
    const source = draft?.sources.find(item => item.id === origin.source);
    return `${source ? source.filename : origin.source}: ${origin.at}`;
  });
  if (fact.note) where.push(fact.note);
  return el("span", { class: "pill " + fact.certainty, title: where.join("\n") },
    CERTAINTY[fact.certainty]);
}

function blank(body, columns, text) {
  body.replaceChildren(el("tr", {}, el("td", { colspan: columns, class: "tom" }, text)));
}

// --- Träffar ---------------------------------------------------------------------------

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
    el("td", { class: "svag" }, "Alltid"),
    el("td", { class: "svag" }, "–"),
    el("td", { class: "tal" }, "10"),
    el("td", {}, "Version 1"),
    el("td", { class: "tal" }, "–")));
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

// --- One meet --------------------------------------------------------------------------

async function loadDraft() {
  try {
    draft = await api(`${API}/meets/${meetId}`);
  } catch (error) {
    $("title").textContent = "Träffen finns inte";
    say(error.message);
    return false;
  }
  facts = new Map(draft.facts.map(fact => [fact.ref, fact]));
  $("meet-name").textContent = draft.meet.name;
  $("title").textContent = draft.meet.name;
  document.title = `${draft.meet.name} · Planering`;
  $("meet-meta").textContent =
    `${dates(draft.meet)} · ${COUNTRIES[draft.meet.country] ?? draft.meet.country}`;
  return true;
}

function placeName(id) {
  return draft?.package?.places.find(place => place.id === id)?.name ?? id;
}

// --- Underlag -----------------------------------------------------------------------------

function showReport() {
  const report = draft.report;
  $("no-report").hidden = Boolean(report);
  $("report-body").hidden = !report;
  if (report) {
    const source = draft.sources.find(item => item.id === report.source);
    $("level").replaceChildren(...level(report.level).childNodes);
    $("source-name").replaceChildren(source && admin
      ? el("a", { href: `${API}/meets/${meetId}/sources/${source.id}` }, source.filename)
      : (source?.filename ?? "Underlaget"));
    $("source-meta").textContent = source
      ? `Stefans planeringsfil · ${number(Math.round(source.size / 1024))} kB · ` +
        `läst ${when(source.added)} med kod, utan AI`
      : "";
    const placeCount = Object.values(report.places).reduce((sum, value) => sum + value, 0);
    const kinds = Object.entries(report.places)
      .map(([kind, count]) => `${count} ${KINDS_MANY[kind] ?? kind}`).join(", ");
    const tiles = [
      [placeCount, "driftplatser", kinds],
      [report.sections, "klareringssträckor", `${number(report.parts)} delsträckor`],
      [report.trains, "tåg", `${number(report.calls)} tågbesök`],
      [report.shunting, "växlingsuppdrag"],
      [report.duties, "köruppdrag"],
      [report.turns, "omlopp"],
      [report.train_types, "tågslag"],
    ];
    $("gave").replaceChildren(...tiles.map(([value, label, small]) =>
      el("div", {}, el("b", {}, number(value)), el("span", {}, label),
        small ? el("small", {}, small) : null)));
    const list = (id, items, empty) => $(id).replaceChildren(...(items.length
      ? items.map(text => el("li", {}, text))
      : [el("li", { class: "tom" }, empty)]));
    list("notes", report.notes, "Inget särskilt.");
    list("left-out", [...report.left_out,
      "Deltagare, fordonsbidrag och ägare i filen är personuppgifter och läses aldrig."], "");
  }
  showQuestions();
  showRules();
}

function showQuestions() {
  const open = draft.questions.filter(question => question.answer === null);
  $("question-count").textContent = draft.questions.length ? String(open.length) : "";
  if (!draft.questions.length) {
    $("questions").replaceChildren(el("li", { class: "tom" },
      draft.report ? "Inga frågor. Filen och regelboken räckte." : "Inga frågor än."));
    return;
  }
  $("questions").replaceChildren(...draft.questions.map(question => {
    const choices = question.alternatives.map(alternative => {
      const where = alternative.origins.map(origin => origin.at).join(", ");
      const chosen = question.answer === alternative.value;
      if (!admin) return chosen ? el("b", {}, alternative.label) : null;
      return el("button", {
        type: "button", "aria-pressed": chosen ? "true" : "false",
        title: where || "Inget underlag säger det",
        onclick: () => answer(question.id, alternative.value),
      }, alternative.label);
    });
    return el("li", {}, el("div", {}, question.message), el("div", { class: "svar" }, ...choices));
  }));
}

async function answer(question, value) {
  try {
    draft = await api(`${API}/meets/${meetId}/answers`, { question, value });
    facts = new Map(draft.facts.map(fact => [fact.ref, fact]));
    say("Svaret är sparat i regelboken.", true);
    showQuestions();
    showRules();
  } catch (error) {
    say(error.message);
  }
}

function showRules() {
  const rules = draft.rulebook.train_types;
  if (!rules.length) {
    blank($("rules"), 4, "Regelboken fylls när underlag läses in.");
    return;
  }
  $("rules").replaceChildren(...rules.map(rule => el("tr", {},
    el("td", { class: "kod" }, rule.code),
    el("td", {}, rule.names.join(", ") || "–"),
    el("td", {}, rule.content ? CONTENT[rule.content] : el("span", { class: "svag" }, "Okänt")),
    el("td", {}, certainty(`train_type:${rule.code}`)))));
}

function setUpSources() {
  showReport();
  $("upload")?.addEventListener("submit", async event => {
    event.preventDefault();
    const file = $("file").files[0];
    if (!file) return;
    const button = event.target.querySelector("button");
    button.disabled = true;
    say("Läser filen …", true);
    try {
      draft = await api(`${API}/meets/${meetId}/sources`, undefined,
        { raw: file, name: file.name });
      facts = new Map(draft.facts.map(fact => [fact.ref, fact]));
      say(`${file.name} är inläst.`, true);
      $("file").value = "";
      showReport();
    } catch (error) {
      say(error.message);
    } finally {
      button.disabled = false;
    }
  });
}

// --- Data ---------------------------------------------------------------------------------

let block = "places";
let callPlace = null;
let trainSearch = "";

const BLOCKS = [
  ["places", "Driftplatser", () => draft.package.places.length],
  ["sections", "Sträckor", () => draft.package.sections.length],
  ["trains", "Tåg", () => draft.package.trains.length],
  ["calls", "Tågbesök", () => draft.package.trains.reduce((sum, t) => sum + t.calls.length, 0)],
];

function head(...names) {
  $("data-head").replaceChildren(el("tr", {}, ...names.map(name => typeof name === "string"
    ? el("th", {}, name) : el("th", { class: "tal" }, name[0]))));
}

function showBlocks() {
  $("blocks").replaceChildren(...BLOCKS.map(([key, label, count]) => el("button", {
    type: "button", class: "chip", "aria-pressed": key === block ? "true" : "false",
    onclick: () => { block = key; showData(); },
  }, label, el("span", { class: "antal" }, number(count())))));
}

function phoneField(place) {
  if (!admin) return place.phone ?? "–";
  const input = el("input", { value: place.phone ?? "", inputmode: "tel", maxlength: "40",
    "aria-label": `Telefon ${place.name}`, placeholder: "–" });
  const save = async () => {
    const phone = input.value.trim() || null;
    if (phone === (place.phone ?? null)) return;
    try {
      const changed = await api(`${API}/meets/${meetId}/places`, { place: place.id, phone });
      place.phone = changed.phone;
      facts.set(`place:${place.id}.phone`, { ref: `place:${place.id}.phone`,
        certainty: "confirmed", origins: [{ source: "planner", at: "Planering" }] });
      say(`Telefon för ${place.name} är sparad.`, true);
    } catch (error) {
      input.value = place.phone ?? "";
      say(error.message);
    }
  };
  input.addEventListener("change", save);
  input.addEventListener("keydown", event => { if (event.key === "Enter") input.blur(); });
  return input;
}

function modeField(section) {
  const base = MODES[draft.meet.clearance_mode];
  if (!admin) {
    return section.clearance_mode ? MODES[section.clearance_mode] : `Träffens (${base})`;
  }
  const select = el("select", { "aria-label": "Klareringsläge" },
    el("option", { value: "" }, `Träffens (${base.toLowerCase()})`),
    ...Object.entries(MODES).map(([value, label]) => el("option", { value }, label)));
  select.value = section.clearance_mode ?? "";
  select.addEventListener("change", async () => {
    try {
      const changed = await api(`${API}/meets/${meetId}/sections`,
        { section: section.id, clearance_mode: select.value || null });
      section.clearance_mode = changed.clearance_mode;
      say("Klareringsläget är sparat.", true);
    } catch (error) {
      select.value = section.clearance_mode ?? "";
      say(error.message);
    }
  });
  return select;
}

function showPlaces() {
  head("Signatur", "Namn", "Typ", "Styrs från", "Spår", "Telefon", "Säkerhet");
  const places = draft.package.places;
  $("data-body").replaceChildren(...places.map(place => el("tr", {},
    el("td", { class: "kod" }, place.code),
    el("td", {}, place.name),
    el("td", {}, KINDS[place.kind] ?? place.kind),
    el("td", {}, place.remote_from ? placeName(place.remote_from) : el("span", { class: "svag" }, "–")),
    el("td", {}, place.tracks.map(track => track.name).join(" ") || "–"),
    el("td", {}, phoneField(place)),
    el("td", {}, certainty(`place:${place.id}`)))));
  $("data-foot").textContent = "Peka på säkerheten för att se var i filen uppgiften står.";
}

function showSections() {
  head("Från", "Till", "Via", "Spår", "Klareringsläge", "Säkerhet");
  $("data-body").replaceChildren(...draft.package.sections.map(section => {
    const via = section.parts.slice(0, -1).map(part => placeName(part.to_place));
    return el("tr", {},
      el("td", {}, placeName(section.place_a)),
      el("td", {}, placeName(section.place_b)),
      el("td", {}, via.length ? via.join(", ") : el("span", { class: "svag" }, "–")),
      el("td", {}, section.tracks === "double" ? "Dubbelspår" : "Enkelspår"),
      el("td", {}, modeField(section)),
      el("td", {}, certainty(`section:${section.id}`)));
  }));
  $("data-foot").textContent =
    "En sträcka är planens klareringssträcka: tåget får klart en gång för hela sträckan.";
}

function first(train) { return train.calls[0]; }
function last(train) { return train.calls.at(-1); }

function showTrains() {
  head("Tåg", "Bolag", "Dagar", "Från", "Avg", "Till", "Ank", ["Besök"], "Säkerhet");
  const search = trainSearch.trim();
  const trains = draft.package.trains.filter(train => !search || train.number.startsWith(search));
  $("data-body").replaceChildren(...trains.map(train => el("tr", {},
    el("td", {}, el("b", {}, [train.train_type, train.number].filter(Boolean).join(" ")),
      train.service_key ? el("div", { class: "liten" }, train.service_key) : null),
    el("td", {}, train.operator ?? "–"),
    el("td", {}, days(train.days)),
    el("td", {}, placeName(first(train).place)),
    el("td", {}, first(train).departure ?? "–"),
    el("td", {}, placeName(last(train).place)),
    el("td", {}, (last(train).arrival ?? "–") + (last(train).day_offset ? " +1" : "")),
    el("td", { class: "tal" }, String(train.calls.length)),
    el("td", {}, certainty(`train:${train.id}`)))));
  $("data-foot").textContent = `${number(trains.length)} tåg visas.`;
}

function showCalls() {
  head("Tåg", "Dagar", "Spår", "Ank", "Avg", "Från", "Till", "Sort", "Anmärkning");
  const rows = [];
  for (const train of draft.package.trains) {
    train.calls.forEach((call, index) => {
      if (call.place !== callPlace) return;
      const time = call.arrival ?? call.departure ?? "";
      rows.push({ train, call, index, order: call.day_offset * 1440 + Number(time.slice(0, 2)) * 60 +
        Number(time.slice(3)) });
    });
  }
  rows.sort((a, b) => a.order - b.order);
  const kind = (call, index, train) => {
    if (index === 0) return "Utgångsstation";
    if (index === train.calls.length - 1) return "Slutstation";
    if (!call.stops) return "Ej uppehåll";
    if (!call.exchange) return "Inget utbyte";
    return "Uppehåll";
  };
  $("data-body").replaceChildren(...rows.map(({ train, call, index }) => el("tr", {},
    el("td", {}, el("b", {}, [train.train_type, train.number].filter(Boolean).join(" "))),
    el("td", {}, days(train.days)),
    el("td", {}, call.track ?? "–"),
    el("td", {}, call.arrival ?? "", call.arrival && call.day_offset ? " +1" : ""),
    el("td", {}, call.departure ?? ""),
    el("td", {}, index > 0 ? placeName(train.calls[0].place) : ""),
    el("td", {}, index < train.calls.length - 1 ? placeName(last(train).place) : ""),
    el("td", {}, kind(call, index, train)),
    el("td", { class: "liten" }, call.note ?? ""))));
  $("data-foot").textContent = `${number(rows.length)} tågbesök i ${placeName(callPlace)}.`;
}

function showFilters() {
  const filters = $("filters");
  if (block === "trains") {
    const input = el("input", { type: "search", placeholder: "Tågnummer", value: trainSearch,
      "aria-label": "Sök tågnummer", inputmode: "numeric" });
    input.addEventListener("input", () => { trainSearch = input.value; showTrains(); });
    filters.replaceChildren(el("label", {}, "Sök", input));
  } else if (block === "calls") {
    const places = draft.package.places;
    callPlace ??= (places.find(place => place.kind === "manned") ?? places[0]).id;
    const select = el("select", { "aria-label": "Driftplats" },
      ...places.map(place => el("option", { value: place.id }, `${place.name} (${place.code})`)));
    select.value = callPlace;
    select.addEventListener("change", () => { callPlace = select.value; showCalls(); });
    filters.replaceChildren(el("label", {}, "Driftplats", select));
  } else {
    filters.replaceChildren();
  }
}

function showData() {
  showBlocks();
  showFilters();
  ({ places: showPlaces, sections: showSections, trains: showTrains, calls: showCalls })[block]();
}

function setUpData() {
  if (!draft.package) {
    $("no-data").hidden = false;
    return;
  }
  $("data").hidden = false;
  showData();
}

// --- Versioner ----------------------------------------------------------------------------

async function showVersions() {
  let check, versions;
  try {
    [check, versions] = await Promise.all([
      api(`${API}/meets/${meetId}/check`), api(`${API}/meets/${meetId}/versions`)]);
  } catch (error) {
    say(error.message);
    return;
  }
  const findings = check.findings;
  $("findings").replaceChildren(...(draft.package
    ? (findings.length
      ? findings.map(finding => el("li", {},
        el("span", { class: "pill " + finding.severity },
          finding.severity === "conflict" ? "Konflikt" : "Iakttagelse"),
        el("span", {}, finding.message)))
      : [el("li", { class: "tom" }, "Inga fynd.")])
    : [el("li", { class: "tom" }, "Lägg till underlag först.")]));
  const next = (versions.at(-1)?.number ?? 0) + 1;
  if ($("publish")) {
    $("publish").disabled = !draft.package;
    $("publish").textContent = `Publicera version ${next}`;
    $("publish-text").textContent = draft.package
      ? "Utkastet fryses som en ny version. Den ändras aldrig." : "";
  }
  if (!versions.length) {
    blank($("versions"), 6, "Ingen version är publicerad än.");
    return;
  }
  $("versions").replaceChildren(...versions.slice().reverse().map(version => el("tr", {},
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
  if (page === "underlag") setUpSources();
  else if (page === "data") setUpData();
  else if (page === "versioner") setUpVersions();
})();
