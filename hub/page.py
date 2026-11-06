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


def render_start_page(info: BuildInfo) -> str:
    return _document(
        info,
        f"""<main>
  <section class="kort">
    <h1>Prova Drift</h1>
    <p class="ingress">Här kan du prova Drift med en påhittad träff på Provbanan.</p>
    <p><a href="/provbanan">Öppna Provbanan →</a></p>
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
