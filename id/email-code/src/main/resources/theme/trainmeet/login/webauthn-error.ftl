<#import "tm-layout.ftl" as layout>
<#-- When adding or using a passkey went wrong: try again, or skip it. -->
<@layout.page title=msg("tmPasskeyErrorTitle")>
  <form id="igen" action="${url.loginAction}" method="post">
    <input type="hidden" name="authenticationExecution" value="${(execution!'')}">
    <input type="hidden" name="isSetRetry" value="retry">
    <button class="id-knapp primar" type="submit">${msg("tmTryAgain")}</button>
  </form>
  <#if isAppInitiatedAction??>
    <form action="${url.loginAction}" method="post">
      <button class="id-knapp" type="submit" name="cancel-aia" value="true">${msg("tmNotNow")}</button>
    </form>
  </#if>
</@layout.page>
