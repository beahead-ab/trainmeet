// A meet screen: join with the code, wait for a view, then show it (steg 3: the clock).
// The key lives in sessionStorage and goes as Authorization: Bearer, never in the address.
"use strict";

const $ = id => document.getElementById(id);
const STORE = "trainmeet-skarm";
const DAYS = { mon: "måndag", tue: "tisdag", wed: "onsdag", thu: "torsdag", fri: "fredag",
  sat: "lördag", sun: "söndag" };

let picture = null;
let fetchedAt = 0;

function key() {
  try { return sessionStorage.getItem(STORE); } catch { return null; }
}

function show(id) {
  for (const section of ["login", "waiting", "clock-view"]) $(section).hidden = section !== id;
}

function clockText() {
  const { clock } = picture;
  const passed = clock.running ? (Date.now() - fetchedAt) / 1000 * clock.speed : 0;
  const minutes = Math.floor((clock.seconds + passed) / 60) % 1440;
  return `${String(Math.floor(minutes / 60)).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}`;
}

function draw() {
  if (!picture) return;
  if (!picture.view) {
    $("screen-name").textContent = picture.name;
    show("waiting");
    return;
  }
  show("clock-view");
  $("clock-view").className = "klocka " + (picture.clock.running ? "gar" : "star");
  $("meet").textContent = `${picture.meet} · trafikdag ${DAYS[picture.traffic_day]}`;
  $("time").textContent = clockText();
  $("state").textContent = picture.clock.running
    ? `Klockan går i ${picture.clock.speed}×` : "Klockan står still";
}

async function refresh() {
  const saved = key();
  if (!saved) { show("login"); return; }
  const response = await fetch("/api/screen/picture",
    { headers: { Authorization: "Bearer " + saved } }).catch(() => null);
  if (!response) return;  // The hub is out of reach; keep showing what we have.
  if (response.status === 401) {
    try { sessionStorage.removeItem(STORE); } catch {}
    picture = null;
    $("message").textContent = "Skärmen är inte ansluten längre. Anslut igen med koden.";
    show("login");
    return;
  }
  if (!response.ok) return;
  picture = await response.json();
  fetchedAt = Date.now();
  draw();
}

$("login-form").addEventListener("submit", async event => {
  event.preventDefault();
  const response = await fetch("/api/screen/session", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: $("name").value.trim(), code: $("code").value.trim() }),
  });
  const answer = await response.json().catch(() => ({}));
  if (!response.ok) {
    $("message").textContent = typeof answer.detail === "string" ? answer.detail : "Det gick inte.";
    return;
  }
  try { sessionStorage.setItem(STORE, answer.session_key); } catch {}
  $("message").textContent = "";
  await refresh();
});

const code = new URLSearchParams(location.hash.slice(1)).get("kod");
if (code) $("code").value = code;
refresh();
setInterval(refresh, 2000);
setInterval(draw, 1000);
