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


def _document(info: BuildInfo, page: str, logged_in: bool, content: str, *, meet: str = "") -> str:
    return f"""<!doctype html>
<html lang="sv">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Planering · TrainMeet Hub · {escape(info.hub_name)}</title>
<link rel="icon" href="/static/favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="/static/planering.css">
<script src="/static/planering.js" defer></script>
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


def render_meets(info: BuildInfo, logged_in: bool) -> str:
    new = (
        """<section class="kort" id="ny">
  <h2>Ny träff</h2>
  <form id="new-meet" class="formular">
    <label>Namn <input id="new-name" maxlength="120" required autocomplete="off"
      placeholder="Värnamo Moduldagar"></label>
    <div class="rad">
      <label>Första dagen <input id="new-first" type="date"></label>
      <label>Sista dagen <input id="new-last" type="date"></label>
      <label>Land <select id="new-country">
        <option value="se">Sverige</option><option value="dk">Danmark</option>
        <option value="no">Norge</option><option value="de">Tyskland</option>
      </select></label>
    </div>
    <button type="submit" class="primar">Skapa träffen</button>
  </form>
</section>"""
        if logged_in
        else '<p class="liten">Logga in för att skapa en träff.</p>'
    )
    return _document(
        info,
        "traffar",
        logged_in,
        f"""<div class="sidrubrik">
  <h1>Träffar <span id="meet-count" class="antal"></span></h1>
  <span class="under">planeras här och körs i Drift</span>
</div>
<section class="kort lista-kort">
  <table class="tabell">
    <thead><tr><th>Träff</th><th>Datum</th><th>Nivå</th><th class="tal">Tåg</th>
      <th>Senaste version</th><th class="tal">Frågor</th></tr></thead>
    <tbody id="meets"><tr><td colspan="6" class="tom">Hämtar träffarna …</td></tr></tbody>
  </table>
</section>
{new}""",
    )


def render_data(info: BuildInfo, meet: str, logged_in: bool) -> str:
    admin = logged_in
    edit = (
        """<span class="fyll"></span>
      <span id="row-count" class="liten"></span>
      <button id="undo" type="button" class="ikon" title="Ångra" aria-label="Ångra"
        disabled>↶</button>
      <button id="redo" type="button" class="ikon" title="Gör om" aria-label="Gör om"
        disabled>↷</button>
      <button id="save" type="button" class="primar" disabled>Spara</button>"""
        if admin
        else '<span class="fyll"></span><span id="row-count" class="liten"></span>'
    )
    add = (
        '<button id="add-source" type="button" class="sekundar">+ Lägg till underlag</button>'
        if admin
        else ""
    )
    drawer = (
        """<div id="drawer" class="lada" hidden>
  <div class="lada-bakgrund" data-close></div>
  <aside class="lada-panel" role="dialog" aria-modal="true" aria-labelledby="drawer-title">
    <header><h2 id="drawer-title">Lägg till underlag</h2>
      <button type="button" class="ikon" data-close aria-label="Stäng">×</button></header>
    <div class="lada-innehall">
      <label class="slapp" id="drop">
        <input id="file" type="file" accept=".json,.gz,application/json" hidden>
        <b>Släpp filen här</b>
        <span>eller välj den. Stefans planeringsfil (JSON). Stationstidtabeller, grafen och
          en bild av banan kommer i nästa del (4c).</span>
      </label>
      <ul id="files" class="filer"></ul>
      <div id="preview" hidden>
        <p class="overrubrik">Underlagets nivå</p>
        <div id="levels" class="nivaer"></div>
        <div class="andras">
          <b>Det här ändras i utkastet</b>
          <p id="changes"></p>
          <p class="liten">Allt får källa och säkerhet och syns som kolumner i Data.</p>
        </div>
        <div class="kostnad"><b>Ingen AI</b><span>Filen läses med kod. Inga tokens.</span></div>
      </div>
    </div>
    <footer>
      <button id="apply" type="button" class="primar" disabled>Lägg in i utkastet</button>
      <button type="button" class="lank" data-close>Avbryt</button>
    </footer>
  </aside>
</div>"""
        if admin
        else ""
    )
    return _document(
        info,
        "data",
        logged_in,
        f"""<div class="sidrubrik">
  <h1>Data</h1><span class="under">allt i träffen, i block</span>
  <span class="fyll"></span><span id="draft-badge" class="bricka"></span>
</div>
<section class="kort data-kort" id="empty" hidden>
  <h2>Inget underlag än</h2>
  <p class="liten">Lägg till Stefans planeringsfil. Den läses med kod, utan AI, och allt i den
    får sitt ursprung och sin säkerhet.</p>
  <div class="rad">{add.replace('id="add-source"', 'id="add-first"')}</div>
</section>
<section class="kort data-kort" id="data" hidden>
  <div class="chiprad"><div id="blocks" class="chips" aria-label="Datablock"></div>{add}</div>
  <div class="filterrad">
    <input id="search" type="search" placeholder="Sök i all data" aria-label="Sök i all data">
    <select id="filter-place" aria-label="Driftplats"></select>
    <select id="filter-source" aria-label="Underlag"></select>
    <select id="filter-certainty" aria-label="Säkerhet"></select>
    <button id="clear" type="button" class="lank">Rensa</button>
    {edit}
  </div>
  <div class="data-yta">
    <div id="tables" class="tabeller"></div>
    <aside id="detail" class="vald" hidden></aside>
  </div>
  <p class="forklaring"><span class="kalla">JSON</span> Stefans plan
    <span class="kalla andrad">PLAN</span> ändrat i Planering
    <span class="kalla regel">REGEL</span> regelboken</p>
</section>
{drawer}""",
        meet=meet,
    )


def render_coming(info: BuildInfo, meet: str, page: str, logged_in: bool) -> str:
    """Bana and Graf, until they are built (4b)."""
    title, text = {
        "bana": ("Bana", "Kartan med driftplatser och klareringssträckor kommer i 4b."),
        "graf": ("Graf", "Tågdiagrammet per linje och trafikdag kommer i 4b."),
    }[page]
    return _document(
        info,
        page,
        logged_in,
        f"""<div class="sidrubrik"><h1>{title}</h1></div>
<section class="kort"><p class="liten">{text}</p></section>""",
        meet=meet,
    )


def render_versions(info: BuildInfo, meet: str, logged_in: bool) -> str:
    publish = (
        """<div class="rad">
    <button id="publish" type="button" class="primar">Publicera</button>
    <span class="liten" id="publish-text"></span>
  </div>"""
        if logged_in
        else ""
    )
    return _document(
        info,
        "versioner",
        logged_in,
        f"""<div class="sidrubrik">
  <h1>Versioner</h1><span class="under">trafikkontrollen och det som publicerats</span>
</div>
<section class="kort">
  <h2>Trafikkontroll</h2>
  <p class="liten">Fynden följer med versionen. De stoppar inte publiceringen.</p>
  <ul id="findings" class="fynd"><li class="tom">Kontrollerar …</li></ul>
  {publish}
</section>
<section class="kort lista-kort">
  <h2>Versioner</h2>
  <p class="liten">En version ändras aldrig och tas aldrig bort. Drift kör en version.</p>
  <table class="tabell">
    <thead><tr><th>Version</th><th>Publicerad</th><th class="tal">Konflikter</th>
      <th class="tal">Iakttagelser</th><th>Kontrollsumma</th><th></th></tr></thead>
    <tbody id="versions"></tbody>
  </table>
</section>""",
        meet=meet,
    )
