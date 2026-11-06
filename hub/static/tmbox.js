"use strict";

// TMBox web: one box per tab. Drift draws the picture (16×2 or 20×4); this page shows it, keeps the
// typed train number until #, and sends the keys. The session key lives in this tab only.

const $ = id => document.getElementById(id);
const STORE = "trainmeet-tmbox";
const KEYS = ["1", "2", "3", "A", "4", "5", "6", "B", "7", "8", "9", "C", "*", "0", "#", "D"];
const TONES = {
  incoming_request: [880, 0, 880],
  request_denied: [392, 0, 262],
  request_approved: [523, 659],
  incoming_train: [660, 0, 660],
};

let session = null;
let frame = null;
let shownAt = 0;
let updatedAt = 0;
let entry = null;
let lastAttention = null;
let audio = null;
let streaming = null;
let messageTimer = null;

function readSession() {
  try { return JSON.parse(sessionStorage.getItem(STORE)); } catch { return null; }
}

function writeSession(value) {
  try {
    if (value) sessionStorage.setItem(STORE, JSON.stringify(value));
    else sessionStorage.removeItem(STORE);
  } catch { /* A tab without storage keeps the box until it is closed. */ }
}

function headers(extra = {}) {
  return { Authorization: "Bearer " + session.session_key, ...extra };
}

function sleep(ms) { return new Promise(resolve => setTimeout(resolve, ms)); }

function say(text) {
  $("message").textContent = text || "";
  clearTimeout(messageTimer);
  if (text) messageTimer = setTimeout(() => { $("message").textContent = ""; }, 4000);
}

function beep(kind) {
  try {
    audio ??= new AudioContext();
    let at = audio.currentTime;
    for (const tone of TONES[kind] ?? [660]) {
      if (tone) {
        const oscillator = audio.createOscillator();
        const gain = audio.createGain();
        oscillator.frequency.value = tone;
        gain.gain.value = 0.08;
        oscillator.connect(gain).connect(audio.destination);
        oscillator.start(at);
        oscillator.stop(at + 0.12);
      }
      at += 0.16;
    }
  } catch { /* No sound in this browser; the picture still says it. */ }
}

function shownLines() {
  if (entry === null || !frame?.entry?.lines) return frame?.lines ?? ["", ""];
  const rows = frame.entry.lines.map(line => [...line]);
  const row = frame.entry.row ?? 0;
  const column = frame.entry.column ?? 5;
  const digits = entry.padEnd(frame.entry.max_length ?? 5, "_");
  [...digits].forEach((digit, index) => { rows[row][column + index] = digit; });
  return rows.map(cells => cells.join(""));
}

function labels() {
  if (!frame || frame.waiting) return {};
  if (entry !== null) return frame.entry?.labels ?? {};
  return Object.fromEntries(Object.entries(frame.keys ?? {}).map(([key, info]) => [key, info.label]));
}

// The display as the box draws it: one row per line, one cell per character (old lcd.js).
// 16 cells are drawn by the frozen style sheet; a box that announced a 20×4 widens the grid
// and shrinks the cells to fit, as the old lcd.js did.
function drawLCD(lines) {
  const lcd = $("lcd");
  lcd.replaceChildren();
  lcd.setAttribute("aria-label", lines.join(". "));
  const columns = Math.max(16, ...lines.map(line => line.normalize("NFC").length));
  for (const line of lines) {
    const row = document.createElement("div");
    row.className = "lcd-row";
    if (columns > 16) row.style.gridTemplateColumns = `repeat(${columns}, minmax(0, 1fr))`;
    for (const character of line.normalize("NFC")) {
      const cell = document.createElement("span");
      cell.className = "lcd-cell";
      cell.textContent = character;
      if (columns > 16) cell.style.fontSize = `clamp(10px, ${(128 / columns).toFixed(2)}cqi, 19px)`;
      row.append(cell);
    }
    lcd.append(row);
  }
}

function draw() {
  drawLCD(shownLines());
  $("status").textContent = entry !== null
    ? "Skriv tågnumret och tryck #. B suddar, * avbryter."
    : frame?.status ?? "";
  const queue = $("queue");
  queue.textContent = frame?.requests?.label ?? "";
  queue.classList.toggle("vantar", Boolean(frame?.requests?.count));
  const shown = labels();
  const hints = $("hints");
  hints.replaceChildren();
  for (const [key, label] of Object.entries(shown)) {
    const hint = document.createElement("span");
    const strong = document.createElement("b");
    strong.textContent = key;
    hint.append(strong, label);
    hints.append(hint);
  }
  // Every key can always be pressed, as on the box. One that cannot do anything right now
  // simply does nothing; nothing lights up or dims.
  for (const button of document.querySelectorAll("#keypad button")) {
    const key = button.dataset.key;
    button.setAttribute("aria-label", shown[key] ? `${key} · ${shown[key]}` : key);
  }
}

function show(next) {
  if (!next) return;
  if (next.view_token !== frame?.view_token) shownAt = performance.now();
  const attention = next.attention;
  if (lastAttention && attention && attention.epoch === lastAttention.epoch
      && attention.seq > lastAttention.seq && attention.kind) beep(attention.kind);
  lastAttention = attention;
  frame = next;
  updatedAt = performance.now();
  $("box-name").textContent = session.name + (frame.waiting ? "" : " · " + frame.station);
  draw();
}

async function send(body) {
  try {
    const response = await fetch("/api/terminal/keys", {
      method: "POST",
      headers: headers({ "Content-Type": "application/json" }),
      body: JSON.stringify({ command_id: crypto.randomUUID(), view_token: frame.view_token, ...body }),
    });
    if (response.status === 401) return leave("Boxen är inte längre ansluten. Anslut igen.");
    const answer = await response.json();
    if (!response.ok) return say(typeof answer.detail === "string" ? answer.detail : "Det gick inte.");
    if (answer.status === "rejected" && answer.message) say(answer.message);
    show(answer.frame);
  } catch {
    say("Kontakten med Hubben bröts. Försöker igen …");
  }
}

function press(key) {
  if (!frame || frame.waiting) return;
  try { audio ??= new AudioContext(); } catch { /* no sound */ }
  if (/^[0-9]$/.test(key)) {
    if (entry === null) entry = "";
    if (entry.length < (frame.entry?.max_length ?? 5)) entry += key;
    return draw();
  }
  if (entry !== null) {
    if (key === "B") { entry = entry.slice(0, -1); return draw(); }
    if (key === "*") { entry = null; return draw(); }
    if (key === "A") { entry = null; draw(); return send({ key: "A" }); }
    if (key === "#") {
      const number = entry;
      entry = null;
      draw();
      if (number) send({ key: "#", train_number: number, entry_context: frame.entry.context });
    }
    return;
  }
  const info = frame.keys?.[key];
  if (!info) return;
  // After a new picture, a key that changes the traffic waits a moment (input_guard_ms).
  if (info.acts && performance.now() - shownAt < (frame.input_guard_ms ?? 500)) return;
  send({ key });
}

async function fetchFrame() {
  const response = await fetch("/api/terminal/frame", { headers: headers(), cache: "no-store" });
  if (response.status === 401) return leave("Boxen är inte längre ansluten. Anslut igen.");
  if (response.ok) show(await response.json());
}

async function stream(token) {
  while (session && streaming === token) {
    const controller = new AbortController();
    token.abort = () => controller.abort();
    try {
      const response = await fetch("/api/terminal/events", {
        headers: headers(), cache: "no-store", signal: controller.signal,
      });
      if (response.status === 401) return leave("Boxen är inte längre ansluten. Anslut igen.");
      if (!response.ok || !response.body) throw new Error("stream");
      const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
      let buffer = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += value;
        let end;
        while ((end = buffer.indexOf("\n\n")) >= 0) {
          const chunk = buffer.slice(0, end);
          buffer = buffer.slice(end + 2);
          let event = "message";
          let data = "";
          for (const line of chunk.split("\n")) {
            if (line.startsWith("event:")) event = line.slice(6).trim();
            else if (line.startsWith("data:")) data += line.slice(5).trim();
          }
          if (event === "frame" && data) show(JSON.parse(data));
          if (event === "gone") return leave("Provkörningen har gått ut. Anslut igen.");
        }
      }
    } catch {
      if (streaming !== token) return;
    }
    await sleep(1000);
  }
}

function start() {
  $("login").hidden = true;
  $("box").hidden = false;
  $("box-name").textContent = session.name;
  const token = {};
  streaming = token;
  fetchFrame();
  stream(token);
}

function leave(text) {
  streaming?.abort?.();
  streaming = null;
  session = null;
  frame = null;
  entry = null;
  lastAttention = null;
  writeSession(null);
  $("box").hidden = true;
  $("login").hidden = false;
  $("login-error").textContent = text || "";
}

function buildKeypad() {
  const pad = $("keypad");
  for (const key of KEYS) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "key" + (/[A-D]/.test(key) ? " function" : "");
    button.textContent = key;
    button.dataset.key = key;
    button.setAttribute("aria-label", key);
    button.onclick = () => press(key);
    pad.append(button);
  }
}

document.addEventListener("keydown", event => {
  if (!frame || event.target instanceof HTMLInputElement || event.metaKey || event.ctrlKey) return;
  const map = { Enter: "#", Backspace: "B", Escape: "*" };
  const key = map[event.key] ?? event.key.toUpperCase();
  if (KEYS.includes(key)) {
    event.preventDefault();
    press(key);
  }
});

// The size the box announces, as a physical box does in its hello.
function chosenDisplay() {
  const [rows, cols] = $("display").value.split("x").map(Number);
  return { rows, cols };
}

$("login-form").onsubmit = async event => {
  event.preventDefault();
  try { audio ??= new AudioContext(); } catch { /* no sound */ }
  $("login-error").textContent = "";
  const name = $("name").value.trim();
  try {
    const response = await fetch("/api/terminal/session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, code: $("code").value.trim(), display: chosenDisplay() }),
    });
    const answer = await response.json();
    if (!response.ok) {
      $("login-error").textContent = typeof answer.detail === "string"
        ? answer.detail : "Kontrollera namnet och koden.";
      return;
    }
    session = { ...answer, name };
    writeSession(session);
    start();
  } catch {
    $("login-error").textContent = "Hubben svarar inte. Försök igen.";
  }
};

$("logout").onclick = () => leave("");

// A picture that stops coming over the stream is fetched instead.
setInterval(() => {
  if (session && performance.now() - updatedAt > 2500) fetchFrame().catch(() => {});
}, 1000);

buildKeypad();
const code = new URLSearchParams(location.hash.slice(1)).get("kod");
if (code) $("code").value = code;
$("name").value = "Box " + Math.floor(Math.random() * 90 + 10);
session = readSession();
if (session?.session_key) start();
else $("login").hidden = false;
