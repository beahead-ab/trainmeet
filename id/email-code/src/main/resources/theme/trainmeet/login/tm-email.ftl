<#import "tm-layout.ftl" as layout>
<@layout.page title=msg("tmLoginTitle")>
  <form action="${url.loginAction}" method="post" novalidate>
    <label for="email">${msg("tmEmail")}</label>
    <input id="email" name="email" type="email" autocomplete="email" inputmode="email" required autofocus value="${(email!'')}">
    <button class="id-knapp primar" type="submit" name="send" value="1">${msg("tmSendCode")}</button>
  </form>
  <p class="id-mellan"><span>${msg("tmFirstTime")}</span></p>
  <form action="${url.loginAction}" method="post">
    <button class="id-knapp" type="submit" name="create" value="1">${msg("tmCreate")}</button>
  </form>
  <p class="id-liten">${msg("tmTrainCatalog")}</p>
</@layout.page>
