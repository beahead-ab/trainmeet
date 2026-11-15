<#-- The frame of TrainMeet ID's own login pages: the header, the words beside, and the card. -->
<#macro page title>
<!doctype html>
<html lang="${(locale.currentLanguageTag)!'sv'}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="robots" content="noindex, nofollow">
  <title>${title} · TrainMeet ID</title>
  <link rel="icon" href="${url.resourcesPath}/img/favicon.svg" type="image/svg+xml">
  <link rel="stylesheet" href="${url.resourcesPath}/css/trainmeet.css">
  <#-- Keycloak's passkey scripts import this by name. -->
  <script type="importmap">{"imports": {"rfc4648": "${url.resourcesCommonPath}/vendor/rfc4648/rfc4648.js"}}</script>
</head>
<body>
  <a class="id-hoppa" href="#kortet">${msg("tmSkip")}</a>
  <header class="id-sidhuvud">
    <img class="id-skylt" src="${url.resourcesPath}/img/skylt.svg" alt="TrainMeet" width="128" height="36">
    <img class="id-namn" src="${url.resourcesPath}/img/id.svg" alt="ID" width="33" height="21">
    <span class="id-streck" aria-hidden="true"></span>
    <span class="id-plats">id.trainmeet.app</span>
    <span class="id-fyll"></span>
    <#if locale?? && locale.supported?size gt 1>
      <nav class="id-sprak" aria-label="${msg('tmLanguage')}">
        <#list locale.supported as other>
          <#if other.languageTag != locale.currentLanguageTag>
            <a href="${other.url}" lang="${other.languageTag}">${(other.languageTag == "en")?then("English", "Svenska")}</a>
          </#if>
        </#list>
      </nav>
    </#if>
  </header>
  <main class="id-sida">
    <section class="id-intro">
      <p class="id-overrubrik">TrainMeet ID</p>
      <h1>${msg("tmHeroLine1")}<br>${msg("tmHeroLine2")}</h1>
      <p>${msg("tmHeroText")}</p>
    </section>
    <section class="id-kort" id="kortet" aria-labelledby="kort-rubrik" tabindex="-1">
      <h2 id="kort-rubrik">${title}</h2>
      <#if message?has_content && message.type != "success">
        <p class="id-${message.type}" role="${(message.type == 'error')?then('alert', 'status')}">${kcSanitize(message.summary)?no_esc}</p>
      </#if>
      <#nested>
    </section>
  </main>
</body>
</html>
</#macro>
