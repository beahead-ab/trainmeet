<#import "tm-layout.ftl" as layout>
<@layout.page title=msg("tmNameTitle")>
  <p>${msg("tmNameIntro", (email!''))}</p>
  <form action="${url.loginAction}" method="post" novalidate>
    <label for="name">${msg("tmName")}</label>
    <input id="name" name="name" autocomplete="name" required autofocus maxlength="80">
    <button class="id-knapp primar" type="submit">${msg("tmCreate")}</button>
  </form>
  <p class="id-liten">${msg("tmPrivacy")}</p>
</@layout.page>
