// Den här hubben: first start, logging in and out. The session is an HttpOnly cookie;
// this page never sees it.
"use strict";

const $ = id => document.getElementById(id);

async function send(path, body) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    credentials: "same-origin",
  });
  if (response.ok) {
    location.reload();
    return;
  }
  const answer = await response.json().catch(() => ({}));
  $("hub-message").textContent =
    typeof answer.detail === "string" ? answer.detail : "Kontrollera fälten och försök igen.";
}

$("setup-form")?.addEventListener("submit", event => {
  event.preventDefault();
  if ($("pin").value !== $("pin-again").value) {
    $("hub-message").textContent = "PIN-koderna är inte lika.";
    return;
  }
  send("/api/hub/setup", { name: $("hub-name").value, pin: $("pin").value });
});

$("login-form")?.addEventListener("submit", event => {
  event.preventDefault();
  send("/api/hub/login", { pin: $("pin").value });
});

$("logout")?.addEventListener("click", () => send("/api/hub/logout"));
