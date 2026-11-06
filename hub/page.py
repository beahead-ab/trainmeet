"""The start page of an empty hub: the header, the version and the change that runs.

Colours follow the TrainMeet Design System (proposal 4 November 2026): the control room
(dark) by default, the library (light) when the device asks for light. The header is dark
in both. No fonts or scripts are fetched from other sites.
"""

from __future__ import annotations

from html import escape

from hub.brand import product_name_svg
from hub.build_info import REPO_URL, BuildInfo

SPEC_URL = "https://platform.trainmeet.app"

_STYLE = """
@font-face { font-family: Inter; src: url(/static/fonts/inter.woff2) format("woff2");
  font-weight: 100 900; font-display: swap; }
@font-face { font-family: "JetBrains Mono"; src: url(/static/fonts/jetbrains-mono.woff2)
  format("woff2"); font-weight: 100 800; font-display: swap; }
:root { color-scheme: dark light; --bg: #0e1114; --panel: #161a1e; --line: #262c33;
  --text: #e9ebef; --mute: #8d94a0; --link: #5aa9ff; --ok: #46d36b; --warn: #f5c518; }
@media (prefers-color-scheme: light) {
  :root { --bg: #f6f5f2; --panel: #ffffff; --line: #e5e5e2; --text: #0a0a0a;
    --mute: #6b6b66; --link: #2256c3; --ok: #15803d; --warn: #a16207; }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text);
  font: 15px/1.5 Inter, system-ui, -apple-system, "Segoe UI", sans-serif; }
header { height: 44px; display: flex; align-items: center; gap: 12px; padding: 0 16px;
  background: #121418; color: #e9ebef; border-bottom: 1px solid #333944; }
header .skylt { height: 28px; width: auto; display: block; }
header .namn { height: 16px; width: auto; display: block; }
header .streck { width: 1px; height: 20px; background: #333944; }
header .sida { font-size: 14px; font-weight: 600; white-space: nowrap; overflow: hidden;
  text-overflow: ellipsis; }
main { max-width: 640px; margin: 48px auto; padding: 0 16px; }
.kort { background: var(--panel); border: 1px solid var(--line); border-radius: 12px;
  padding: 24px; }
h1 { font-size: 22px; line-height: 1.25; margin: 0 0 6px; font-weight: 700; }
.ingress { color: var(--mute); margin: 0 0 20px; }
dl { display: grid; grid-template-columns: 110px 1fr; gap: 8px 16px; margin: 0; }
dt { color: var(--mute); }
dd { margin: 0; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
.kod { font-family: "JetBrains Mono", ui-monospace, Menlo, monospace; font-size: 13px; }
.status { display: inline-flex; align-items: center; gap: 8px; }
.status::before { content: ""; width: 8px; height: 8px; border-radius: 50%;
  background: var(--ok); }
.lokal { color: var(--warn); }
a { color: var(--link); text-decoration: none; }
a:hover { text-decoration: underline; }
footer { margin-top: 16px; color: var(--mute); font-size: 13px; display: flex; gap: 16px;
  flex-wrap: wrap; }
#hubben { margin-bottom: 16px; }
.formular { display: grid; gap: 12px; max-width: 320px; }
.formular label { display: grid; gap: 4px; color: var(--mute); font-size: 13px; }
#hubben input { font: inherit; color: var(--text); background: var(--bg);
  border: 1px solid var(--line); border-radius: 8px; padding: 8px 10px; }
#hubben button { font: inherit; font-weight: 600; color: #fff; background: var(--link);
  border: 0; border-radius: 8px; padding: 9px 14px; cursor: pointer; justify-self: start; }
.meddelande { color: var(--warn); min-height: 1.5em; margin: 8px 0 0; }
""".strip()


def _change(info: BuildInfo) -> str:
    if info.is_local:
        return '<span class="lokal">Lokalt bygge</span>'
    if info.pr is not None:
        label = f"#{info.pr}"
        if info.title:
            label += f" {info.title}"
        return f'<a href="{escape(info.pr_url or "")}">{escape(label)}</a>'
    return escape(info.title or "Direkt på main")


def _commit(info: BuildInfo) -> str:
    if info.commit is None:
        return "–"
    return (
        f'<a class="kod" href="{escape(info.commit_url or "")}">'
        f"{escape(info.short_commit or '')}</a>"
    )


def _built(info: BuildInfo) -> str:
    if info.built is None:
        return "–"
    return escape(info.built.strftime("%Y-%m-%d %H:%M %Z").strip())


def _document(info: BuildInfo, content: str, extra_head: str = "") -> str:
    hub_name = escape(info.hub_name)
    return f"""<!doctype html>
<html lang="sv">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TrainMeet Hub · {hub_name}</title>
<link rel="icon" href="/static/favicon.svg" type="image/svg+xml">
<style>
{_STYLE}
</style>
{extra_head}
</head>
<body>
<header>
  <img class="skylt" src="/static/skylt.svg" alt="TrainMeet">
  {product_name_svg("HUB")}
  <span class="streck" aria-hidden="true"></span>
  <span class="sida">{hub_name}</span>
</header>
{content}
</body>
</html>
"""


def _hub_card(set_up: bool, logged_in: bool, name: str) -> str:
    """Den här hubben: first start, logging in, or who one is (S1, H52)."""
    if not set_up:
        return f"""<section class="kort" id="hubben">
    <h1>Välkommen till hubben</h1>
    <p class="ingress">Välj ett namn på hubben och en PIN-kod. Du blir hubbens lokala
      administratör och loggar in med koden.</p>
    <form id="setup-form" class="formular">
      <label>Hubbens namn <input id="hub-name" maxlength="40" required
        value="{escape(name)}" autocomplete="off"></label>
      <label>PIN-kod, 6–12 siffror <input id="pin" type="password" inputmode="numeric"
        pattern="[0-9]{{6,12}}" minlength="6" maxlength="12" required
        autocomplete="new-password"></label>
      <label>Samma PIN-kod igen <input id="pin-again" type="password" inputmode="numeric"
        pattern="[0-9]{{6,12}}" minlength="6" maxlength="12" required
        autocomplete="new-password"></label>
      <button type="submit">Spara och logga in</button>
    </form>
    <p id="hub-message" class="meddelande" role="alert"></p>
  </section>
"""
    if not logged_in:
        return """<section class="kort" id="hubben">
    <h1>Logga in</h1>
    <p class="ingress">Utan inloggning kan du titta. Logga in med hubbens PIN-kod för att
      köra träffen.</p>
    <form id="login-form" class="formular">
      <label>PIN-kod <input id="pin" type="password" inputmode="numeric"
        pattern="[0-9]{6,12}" minlength="6" maxlength="12" required
        autocomplete="current-password"></label>
      <button type="submit">Logga in</button>
    </form>
    <p id="hub-message" class="meddelande" role="alert"></p>
  </section>
"""
    return """<section class="kort" id="hubben">
    <h1>Inloggad</h1>
    <p class="ingress">Du är inloggad som hubbens lokala administratör.</p>
    <p><a href="/drift">Kör träffen →</a></p>
    <button id="logout" type="button">Logga ut</button>
  </section>
"""


def render_start_page(info: BuildInfo, *, set_up: bool = True, logged_in: bool = False) -> str:
    return _document(
        info,
        f"""<main>
  {_hub_card(set_up, logged_in, info.hub_name)}
  <section class="kort">
    <h1>Prova Drift</h1>
    <p class="ingress">Här kan du prova Drift med en påhittad träff på Provbanan.</p>
    <p><a href="/provbanan">Öppna Provbanan →</a> &nbsp; <a href="/drift">Se träffen →</a></p>
    <dl>
      <dt>Status</dt><dd><span class="status">Igång</span></dd>
      <dt>Version</dt><dd>{escape(info.version)}</dd>
      <dt>Ändring</dt><dd>{_change(info)}</dd>
      <dt>Commit</dt><dd>{_commit(info)}</dd>
      <dt>Byggd</dt><dd>{_built(info)}</dd>
    </dl>
  </section>
  <footer>
    <a href="{REPO_URL}">Koden på GitHub</a>
    <a href="{SPEC_URL}">Specen</a>
    <span>AGPL-3.0</span>
  </footer>
</main>
<script src="/static/hubben.js" defer></script>
""",
    )


def render_preview(info: BuildInfo) -> str:
    return _document(
        info,
        """<main class="prov">
  <a href="/">← Hubben</a>
  <section class="kort">
    <h1>Provbanan</h1>
    <p class="ingress">Prova Drift på fyra driftplatser med måndagens tio tåg.
      Du agerar från den driftplats som anges på knappen.</p>
    <button id="start" type="button">Starta provkörning</button>
    <p id="notice" role="status" aria-live="polite"></p>
    <div id="run" hidden>
      <div class="controls">
        <output id="clock" class="kod"></output>
        <button id="toggle-clock" type="button">Starta klockan</button>
        <label>Hastighet <input id="speed" type="number" min="0.1" max="60" step="0.1"></label>
        <button id="set-speed" type="button">Spara hastighet</button>
      </div>
      <h2>Tidtabell och klarering</h2>
      <p class="ingress">Prova tåg 101 från Norrby för begärd klarering. Prova tåg 102 från
        Sjövik för direktklarering. Välj ett tågbesök och följ ärendet till ankomst.</p>
      <div class="controls">
        <label for="leg">Avgång</label>
        <select id="leg"></select>
        <button id="request" type="button">Begär klarering</button>
      </div>
      <p id="leg-info" class="ingress"></p>
      <h2>Boxar</h2>
      <p class="ingress">Öppna en box i en ny flik, och anslut den med koden
        <strong id="join-code" class="kod">–</strong>. Tilldela den sedan en driftplats här.
        En TKL eller TMBox-appen ansluter med samma kod och godkänns här.</p>
      <p><a id="box-link" href="/provbanan/box" target="_blank"
        rel="noopener">Öppna en box →</a></p>
      <ul id="clients" class="cases"></ul>
      <h2>Klareringar</h2>
      <ul id="cases" class="cases"></ul>
      <button id="restart" type="button">Ny provkörning</button>
    </div>
  </section>
  <p class="ingress">Din provkörning sparas i ett dygn i den här webbläsaren.</p>
</main>
""",
        """<link rel="stylesheet" href="/static/provbanan.css">
<script src="/static/provbanan.js" defer></script>""",
    )


def render_box(info: BuildInfo) -> str:
    """TMBox web: one box per tab. The tab logs in with the run's code and waits to be assigned."""
    return _document(
        info,
        """<main class="tmbox">
  <a href="/provbanan">← Provbanan</a>
  <section id="login" class="kort" hidden>
    <h1>TMBox</h1>
    <p class="ingress">Anslut boxen till en provkörning med koden som står på Provbanan
      under Boxar. Varje flik blir en egen box.</p>
    <form id="login-form" class="falt">
      <label>Boxens namn <input id="name" maxlength="40" required autocomplete="off"></label>
      <label>Kod <input id="code" inputmode="numeric" pattern="[0-9]{6}" maxlength="6"
        required autocomplete="off"></label>
      <label>Display <select id="display">
        <option value="2x16">16 × 2, som de flesta boxar</option>
        <option value="4x20">20 × 4</option>
      </select></label>
      <button type="submit">Anslut</button>
    </form>
    <p id="login-error" class="fel" role="alert"></p>
  </section>
  <section id="box" class="kort" hidden>
    <div class="boxhuvud">
      <h1 id="box-name">TMBox</h1>
      <button id="logout" type="button" class="lank">Koppla från</button>
    </div>
    <p id="status" class="boxstatus"></p>
    <p id="queue" class="boxko" role="status"></p>
    <div class="tmbox-case">
      <div class="lcd-frame"><div id="lcd" class="lcd" role="img"></div></div>
      <div id="keypad" class="keypad"></div>
    </div>
    <div id="hints" class="key-hints"></div>
    <p id="message" class="fel" role="status"></p>
    <p class="ingress tips">Tangentbordet fungerar också: siffror, A–D, * och #.
      Enter är #, Backsteg är B och Esc är *.</p>
  </section>
</main>
""",
        """<link rel="stylesheet" href="/static/tmbox.css">
<script src="/static/tmbox.js" defer></script>""",
    )
