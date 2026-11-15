<#import "tm-layout.ftl" as layout>
<@layout.page title=msg("tmCodeTitle")>
  <p>${msg("tmCodeSent", (email!''), (minutes!10))}</p>
  <form action="${url.loginAction}" method="post" novalidate>
    <label for="code">${msg("tmCode")}</label>
    <input id="code" name="code" class="id-kod" inputmode="numeric" autocomplete="one-time-code" pattern="[0-9 -]*" maxlength="9" required autofocus>
    <button class="id-knapp primar" type="submit">${msg("tmLogIn")}</button>
  </form>
  <form class="id-rad" action="${url.loginAction}" method="post">
    <button class="id-lank" type="submit" name="resend" value="1">${msg("tmResend")}</button>
    <button class="id-lank" type="submit" name="restart" value="1">${msg("tmOtherEmail")}</button>
  </form>
  <p class="id-liten">${msg("tmCodeSpam")}</p>
</@layout.page>
