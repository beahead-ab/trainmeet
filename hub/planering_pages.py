"""Planeringens sidor: Träffar på hubbnivå, och i en träff Data · Bana · Graf · Versioner (S6),
in Biblioteket (light): dark when one runs, light when one plans. The header is dark in both.

S1: everyone sees the same pages; logged in, one also gets the buttons and fields. The pages
are drawn here as skeletons; planering.js fills them from Planeringens API. Lägg till underlag
opens from Data (S6).
"""

from __future__ import annotations

from html import escape

from hub.brand import product_name_svg
from hub.build_info import BuildInfo

PLANNING = (("data", "Data", ""), ("bana", "Bana", "/bana"), ("graf", "Graf", "/graf"))
PLANNING_LAST = ("versioner", "Versioner", "/versioner")
DRIFT = (("Nu", "/drift"), ("Klienter", "/drift/klienter"), ("Logg", "/drift/logg"))


def _header(meet: str, page: str, logged_in: bool) -> str:
    account = (
        '<button id="logout" type="button" class="hknapp">Logga ut</button>'
        if logged_in
        else '<a class="hknapp" href="/">Logga in</a>'
    )
    if meet:
        tabs = "".join(
            f'<a href="/planering/{escape(meet)}{path}"'
            f"{' aria-current=page' if key == page else ''}>{label}</a>"
            for key, label, path in (*PLANNING, PLANNING_LAST)
        )
        drift = "".join(f'<a href="{path}">{label}</a>' for label, path in DRIFT)
        middle = f"""<details class="byt" id="switch">
    <summary><span id="meet-name">…</span><span aria-hidden="true">▾</span></summary>
    <div class="byt-lista"><ul id="switch-list"></ul>
      <a href="/planering">Alla träffar</a></div>
  </details>
  <nav class="flikar" aria-label="Planering"><span class="grupp">Planering</span>{tabs}</nav>
  <span class="streck" aria-hidden="true"></span>
  <nav class="flikar" aria-label="Drift"><span class="grupp">Drift</span>{drift}</nav>"""
    else:
        middle = '<nav class="flikar" aria-label="Hubben"><a aria-current=page>Träffar</a></nav>'
    return f"""<header class="sidhuvud">
  <a href="/"><img class="skylt" src="/static/skylt.svg" alt="TrainMeet"></a>
  {product_name_svg("HUB")}
  <span class="streck" aria-hidden="true"></span>
  {middle}
  <span class="fyll"></span>
  {account}
</header>"""


def _document(
    info: BuildInfo,
    page: str,
    logged_in: bool,
    content: str,
    *,
    meet: str = "",
    scripts: tuple[str, ...] = (),
) -> str:
    extra = "".join(f'<script src="{src}" defer></script>\n' for src in scripts)
    return f"""<!doctype html>
<html lang="sv">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Planering · TrainMeet Hub · {escape(info.hub_name)}</title>
<link rel="icon" href="/static/favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="/static/planering.css">
{extra}<script src="/static/planering.js" defer></script>
</head>
<body data-page="{page}" data-meet="{escape(meet)}" data-admin="{"ja" if logged_in else "nej"}">
{_header(meet, page, logged_in)}
<main>
{content}
<p id="message" class="meddelande" role="alert"></p>
</main>
</body>
</html>
"""


def render_graph(info: BuildInfo, meet: str, logged_in: bool) -> str:
    """Graf: the day's trains along one line, with the traffic check's findings numbered."""
    return _document(
        info,
        "graf",
        logged_in,
        """<div class="sidrubrik">
  <h1>Graf</h1><span class="under">dygnets tåg, med kontrollens fynd</span>
</div>
<section class="kort" id="empty" hidden>
  <p class="liten">Lägg till underlag under Data först.</p>
</section>
<div class="graf-yta" id="graph-page" hidden>
  <section class="kort graf-kort">
    <div class="graf-rad">
      <div id="days" class="segment" role="group" aria-label="Trafikdag"></div>
      <label class="valj">Linje <select id="line"></select></label>
      <span class="fyll"></span>
      <div class="segment" role="group" aria-label="Skala">
        <button type="button" id="zoom-out" aria-label="Visa mer av dygnet">&minus;</button>
        <button type="button" id="zoom-in" aria-label="Visa mindre av dygnet">+</button>
      </div>
    </div>
    <div id="graph" class="graf"></div>
    <footer class="graf-fot">
      <span id="graph-count" class="liten"></span><span class="fyll"></span>
      <span class="teckning resande">resande</span><span class="teckning gods">gods</span>
      <span class="teckning tjanst">tjänst</span><span class="teckning okand">okänt slag</span>
    </footer>
  </section>
  <aside class="kort graf-sida">
    <h2>I grafen <span class="liten">trafikkontrollen</span></h2>
    <ol id="graph-findings" class="numrerade"></ol>
    <p class="overrubrik">Skriv ut</p>
    <p class="liten">PDF på A3 liggande, hela dygnet. Välj Spara som PDF i utskriften.</p>
    <div class="rad">
      <button type="button" id="print-line">Den här linjen</button>
      <button type="button" id="print-all" class="lank">Alla linjer</button>
    </div>
  </aside>
</div>
<div id="print" class="utskrift" aria-hidden="true"></div>""",
        meet=meet,
        scripts=("/static/graf.js",),
    )


def render_map(info: BuildInfo, meet: str, logged_in: bool) -> str:
    """Bana: the map with the places and the clearance sections with their parts."""
    return _document(
        info,
        "bana",
        logged_in,
        """<div class="sidrubrik">
  <h1>Bana</h1><span class="under">klareringssträckor med delsträckor under</span>
</div>
<section class="kort" id="empty" hidden>
  <p class="liten">Lägg till underlag under Data först.</p>
</section>
<div class="notis" id="unsure" hidden></div>
<div class="bana-yta" id="map-page" hidden>
  <section class="kort karta-kort">
    <header class="kort-rubrik"><h2>Banan</h2><span id="map-count" class="liten"></span></header>
    <div id="map" class="karta-yta"></div>
    <footer class="forklaring">
      <span>Fyrkant = driftplats med klarering</span>
      <span>Ring = hållplats eller industri</span>
      <span>Streckad ram = skuggbangård</span>
      <span>Dubbla linjer = dubbelspår</span>
      <span>Grå streckad = spår utan klarering i planen</span>
      <span class="bla">Blå = vald</span>
    </footer>
  </section>
  <aside class="kort vald" id="choice">
    <p class="liten">Välj en sträcka eller en driftplats på kartan.</p>
  </aside>
</div>""",
        meet=meet,
        scripts=("/static/bana.js",),
    )
