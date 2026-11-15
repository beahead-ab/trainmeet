<#import "tm-layout.ftl" as layout>
<@layout.page title=msg("tmCreateTitle")>
  <form action="${url.loginAction}" method="post" novalidate>
    <input type="hidden" name="creating" value="1">
    <label for="name">${msg("tmName")}</label>
    <input id="name" name="name" autocomplete="name" required autofocus maxlength="80" value="${(name!'')}">
    <label for="email">${msg("tmEmail")}</label>
    <input id="email" name="email" type="email" autocomplete="email" inputmode="email" required value="${(email!'')}">
    <button class="id-knapp primar" type="submit" name="send" value="1">${msg("tmSendCode")}</button>
  </form>
  <form action="${url.loginAction}" method="post">
    <button class="id-lank" type="submit" name="restart" value="1">${msg("tmHaveAccount")}</button>
  </form>
  <p class="id-liten">${msg("tmPrivacy")}</p>
</@layout.page>
