"""Planeringens sidor (steg 4a): Träffar, and per meet Underlag, Data and Versioner, in
Biblioteket (light): the design system's rule, dark when one runs and light when one plans.

S1: everyone sees the same pages; logged in, one also gets the buttons and fields. The pages
are drawn here as skeletons; planering.js fills them from Planeringens API. Nothing is fetched
from another site.
"""

from __future__ import annotations

from html import escape

from hub.brand import product_name_svg
from hub.build_info import BuildInfo

TABS = (
    ("underlag", "Underlag", ""),
    ("data", "Data", "/data"),
    ("versioner", "Versioner", "/versioner"),
)


def _document(
    info: BuildInfo, page: str, logged_in: bool, content: str, *, meet: str = "", tabs: str = ""
) -> str:
    account = (
        '<button id="logout" type="button" class="hknapp">Logga ut</button>'
        if logged_in
        else '<a class="hknapp" href="/">Logga in</a>'
    )
    crumb = (
        '<a href="/planering">Planering</a><span class="pil">&rsaquo;</span>'
        '<span id="meet-name" class="namnet"></span>'
        if meet
        else "<span>Planering</span>"
    )
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
<header class="sidhuvud">
  <a href="/"><img class="skylt" src="/static/skylt.svg" alt="TrainMeet"></a>
  {product_name_svg("HUB")}
  <span class="streck" aria-hidden="true"></span>
  <nav class="spar" aria-label="Var du är">{crumb}</nav>
  <span class="fyll"></span>
  <a class="hknapp" href="/drift">Drift</a>
  {account}
</header>
{tabs}
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
  <p class="overrubrik">Planering</p>
  <h1>Träffar <span id="meet-count" class="antal"></span></h1>
  <p class="ingress">En träff planeras här och körs i Drift. Lägg till Stefans planeringsfil,
    läs importrapporten och publicera en version.</p>
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


def _tabs(meet: str, page: str) -> str:
    links = "".join(
        f'<a href="/planering/{escape(meet)}{path}"'
        f"{' aria-current=page' if key == page else ''}>{label}</a>"
        for key, label, path in TABS
    )
    return f'<nav class="flikar">{links}</nav>'


def _meet_page(info: BuildInfo, meet: str, page: str, logged_in: bool, content: str) -> str:
    head = """<div class="sidrubrik">
  <p class="overrubrik" id="meet-meta">Träff</p>
  <h1 id="title">…</h1>
</div>"""
    return _document(
        info,
        page,
        logged_in,
        head + content,
        meet=meet,
        tabs=_tabs(meet, page),
    )


def render_sources(info: BuildInfo, meet: str, logged_in: bool) -> str:
    add = (
        """<section class="kort" id="add">
  <h2>Lägg till underlag</h2>
  <p class="liten">Stefans planeringsfil (JSON) läses med kod, utan AI. Det är nivå 4, facit:
    allt i filen är säkert. En ny fil tar den gamlas plats; dina ändringar och svar står kvar.</p>
  <form id="upload" class="rad">
    <input id="file" type="file" accept=".json,.gz,application/json" required>
    <button type="submit" class="primar">Läs in filen</button>
  </form>
</section>"""
        if logged_in
        else ""
    )
    return _meet_page(
        info,
        meet,
        "underlag",
        logged_in,
        f"""{add}
<section class="kort" id="report">
  <h2>Importrapport</h2>
  <p class="liten" id="no-report">Inget underlag än.</p>
  <div id="report-body" hidden>
    <div class="rapporthuvud">
      <span id="level" class="niva"></span>
      <div><p id="source-name" class="fet"></p><p id="source-meta" class="liten"></p></div>
    </div>
    <h3>Filen gav</h3>
    <div id="gave" class="nyckeltal"></div>
    <h3>Reglerna bestämde</h3>
    <ul id="notes" class="punkter"></ul>
    <h3>Lästes inte in</h3>
    <ul id="left-out" class="punkter"></ul>
  </div>
</section>
<section class="kort" id="questions-card">
  <h2>Frågor <span id="question-count" class="antal"></span></h2>
  <p class="liten">Bara där en regel saknas. Det som är säkert frågas inte om.</p>
  <ul id="questions" class="fragor"></ul>
</section>
<section class="kort">
  <h2>Regelboken</h2>
  <p class="liten">Tågslagen och förkortningarna som alla underlag läses med.</p>
  <table class="tabell">
    <thead><tr><th>Förkortning</th><th>Tågslag i underlaget</th><th>Kör</th>
      <th>Säkerhet</th></tr></thead>
    <tbody id="rules"></tbody>
  </table>
</section>""",
    )


def render_data(info: BuildInfo, meet: str, logged_in: bool) -> str:
    return _meet_page(
        info,
        meet,
        "data",
        logged_in,
        """<p class="liten" id="no-data" hidden>Lägg till underlag först.</p>
<div id="data" hidden>
  <div class="chips" id="blocks" aria-label="Datablock"></div>
  <div class="rad" id="filters"></div>
  <section class="kort lista-kort">
    <table class="tabell">
      <thead id="data-head"></thead>
      <tbody id="data-body"></tbody>
    </table>
  </section>
  <p class="liten" id="data-foot"></p>
</div>""",
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
    return _meet_page(
        info,
        meet,
        "versioner",
        logged_in,
        f"""<section class="kort">
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
    )
