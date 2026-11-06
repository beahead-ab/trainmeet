"""Trafikledningens sidor (steg 3): Nu, Klienter och Logg, in Kontrollrummet (dark).

S1: everyone sees the same pages; logged in, one also sees the buttons. S2: the header always
has the meet with Byt träff, the meet clock, Anslut and Väntar. S6: Drift is Nu · Klienter ·
Logg. H53: built simply after the design system and adjusted when Casper has seen them.

The pages are drawn here as skeletons; drift.js fills them from Driftens API. Nothing is
fetched from another site.
"""

from __future__ import annotations

from html import escape

from hub.brand import product_name_svg
from hub.build_info import BuildInfo

TABS = (
    ("nu", "Nu", "/drift"),
    ("klienter", "Klienter", "/drift/klienter"),
    ("logg", "Logg", "/drift/logg"),
)

WEEKDAYS = (
    ("mon", "Måndag"),
    ("tue", "Tisdag"),
    ("wed", "Onsdag"),
    ("thu", "Torsdag"),
    ("fri", "Fredag"),
    ("sat", "Lördag"),
    ("sun", "Söndag"),
)


def _days() -> str:
    return "".join(f'<option value="{day}">{name}</option>' for day, name in WEEKDAYS)


def _document(info: BuildInfo, page: str, logged_in: bool, content: str) -> str:
    tabs = "".join(
        f'<a href="{href}"{" aria-current=page" if key == page else ""}>{label}</a>'
        for key, label, href in TABS
    )
    admin = (
        """<button id="connect" type="button" class="hknapp">Anslut</button>
    <a id="waiting" class="hknapp" href="/drift/klienter">Väntar <b id="waiting-count">0</b></a>
    <button id="logout" type="button" class="hknapp">Logga ut</button>"""
        if logged_in
        else '<a class="hknapp" href="/">Logga in</a>'
    )
    return f"""<!doctype html>
<html lang="sv">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TrainMeet Hub · {escape(info.hub_name)}</title>
<link rel="icon" href="/static/favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="/static/drift.css">
<script src="/static/drift.js" defer></script>
</head>
<body data-page="{page}" data-admin="{"ja" if logged_in else "nej"}">
<header class="sidhuvud">
  <a href="/"><img class="skylt" src="/static/skylt.svg" alt="TrainMeet"></a>
  {product_name_svg("HUB")}
  <span class="streck" aria-hidden="true"></span>
  <span class="traff"><span id="meet-name">{escape(info.hub_name)}</span>
    {'<a id="change-meet" class="byt" href="/drift#ny-traff">Byt träff</a>' if logged_in else ""}
  </span>
  <span class="fyll"></span>
  <span id="clock" class="klocka" title="Träffklockan">--:--</span>
  {admin}
</header>
<nav class="flikar">{tabs}</nav>
<section id="connect-panel" class="anslut" hidden>
  <div>
    <p class="etikett">Anslut en box, en TKL eller en skärm med koden</p>
    <p id="connect-code" class="anslutkod">------</p>
    <p class="liten">Eller skanna koden med telefonen. Boxen öppnas på <span id="connect-url"
      class="mono"></span></p>
    <p class="liten">En skärm öppnar <span id="connect-screen" class="mono"></span></p>
  </div>
  <img id="connect-qr" alt="QR-kod som öppnar boxen med koden" width="180" height="180">
</section>
<main>
{content}
<p id="message" class="meddelande" role="alert"></p>
</main>
</body>
</html>
"""


def render_nu(info: BuildInfo, logged_in: bool) -> str:
    controls = (
        f"""<div class="rad" id="clock-controls">
    <button id="clock-toggle" type="button" class="primar">Starta klockan</button>
    <div class="chips" id="speeds" aria-label="Hastighet"></div>
  </div>
  <details id="ny-traff" class="kort">
    <summary>Byt träff</summary>
    <p class="liten">En ny träff tar över. Den gamla arkiveras, och boxar och klienter ansluter
      med den nya koden. Versionerna publiceras i <a href="/planering">Planering</a>.</p>
    <div class="rad">
      <label>Träff <select id="new-choice" class="val"></select></label>
      <label>Trafikdag <select id="new-day">{_days()}</select></label>
      <button id="new-meet" type="button">Starta ny träff</button>
    </div>
  </details>"""
        if logged_in
        else ""
    )
    start = (
        f"""<div class="rad"><label>Träff <select id="first-choice" class="val"></select></label>
      <label>Trafikdag <select id="first-day">{_days()}</select></label>
      <button id="start-meet" type="button" class="primar">Starta träffen</button></div>"""
        if logged_in
        else '<p class="liten">Logga in för att starta en träff.</p>'
    )
    return _document(
        info,
        "nu",
        logged_in,
        f"""<section id="no-meet" class="kort" hidden>
  <h1>Ingen träff är startad</h1>
  <p class="ingress">Hubben kör en träff åt gången: Provbanan, eller en version av en träff som
    publicerats i <a href="/planering">Planering</a>.</p>
  {start}
</section>
<section id="meet" hidden>
  <div class="sidrubrik">
    <h1 id="title">Nu</h1>
    <p id="subtitle" class="liten"></p>
  </div>
  {controls}
  <h2>Öppna klareringar <span id="case-count" class="antal">0</span></h2>
  <ul id="cases" class="lista"></ul>
  <h2>Tågen</h2>
  <div class="chips" id="filters" aria-label="Visa"></div>
  <div class="ram"><table class="tabell">
    <thead><tr><th>Tåg</th><th>Sträcka</th><th>Avgång</th><th>Ankomst</th><th>Läge</th>
      <th>Spår</th></tr></thead>
    <tbody id="legs"></tbody>
  </table></div>
</section>""",
    )


def _login_first() -> str:
    return """<section class="kort"><h1>Logga in</h1>
  <p class="ingress">Den här sidan visar vem som är ansluten och vad de gjort. Logga in med
    hubbens PIN-kod för att se den.</p>
  <p><a href="/">Till inloggningen →</a></p></section>"""


def render_klienter(info: BuildInfo, logged_in: bool) -> str:
    content = (
        """<div class="sidrubrik"><h1>Klienter</h1>
  <p class="liten">Boxar, TKL och skärmar. Nya hamnar överst under Väntar. Anslut finns i
    sidhuvudet.</p></div>
<div class="chips" id="client-filters" aria-label="Visa"></div>
<ul id="clients" class="lista"></ul>"""
        if logged_in
        else _login_first()
    )
    return _document(info, "klienter", logged_in, content)


def render_logg(info: BuildInfo, logged_in: bool) -> str:
    content = (
        """<div class="sidrubrik"><h1>Logg</h1>
  <p class="liten">Det som hänt i träffen, nyast först, och det som klienterna fått nej
    till.</p></div>
<div class="rad">
  <div class="chips" id="log-kinds" aria-label="Visa"></div>
  <label>Tåg <input id="log-train" inputmode="numeric" size="6" autocomplete="off"></label>
</div>
<div class="chips" id="log-places" aria-label="Driftplats"></div>
<div class="ram"><table class="tabell">
  <thead><tr><th>Tid</th><th>Händelse</th><th>Tåg</th><th>Driftplats</th><th>Vem</th></tr>
  </thead>
  <tbody id="log"></tbody>
</table></div>"""
        if logged_in
        else _login_first()
    )
    return _document(info, "logg", logged_in, content)
