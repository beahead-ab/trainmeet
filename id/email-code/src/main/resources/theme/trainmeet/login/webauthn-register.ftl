<#import "tm-layout.ftl" as layout>
<#-- Keycloak's page for adding a passkey, in TrainMeet ID's look (KONTO-33). -->
<@layout.page title=msg("tmPasskeyAddTitle")>
  <p>${msg("tmPasskeyAddText")}</p>
  <form id="register" action="${url.loginAction}" method="post" hidden>
    <input type="hidden" id="clientDataJSON" name="clientDataJSON">
    <input type="hidden" id="attestationObject" name="attestationObject">
    <input type="hidden" id="publicKeyCredentialId" name="publicKeyCredentialId">
    <input type="hidden" id="authenticatorLabel" name="authenticatorLabel">
    <input type="hidden" id="transports" name="transports">
    <input type="hidden" id="authenticatorAttachment" name="authenticatorAttachment">
    <input type="hidden" id="error" name="error">
  </form>
  <button class="id-knapp primar" type="button" id="registerWebAuthn">${msg("tmPasskeyAdd")}</button>
  <#if !isSetRetry?has_content && isAppInitiatedAction?has_content>
    <form action="${url.loginAction}" method="post">
      <button class="id-knapp" type="submit" name="cancel-aia" value="true">${msg("tmNotNow")}</button>
    </form>
  </#if>
  <script type="module">
    <#outputformat "JavaScript">
    import { registerByWebAuthn } from "${url.resourcesPath}/js/webauthnRegister.js";
    // Keycloak asks for a name for the passkey in a dialog; TrainMeet names it itself.
    window.prompt = (question, name) => name;
    document.getElementById("registerWebAuthn").addEventListener("click", () => registerByWebAuthn({
      challenge: ${challenge?c},
      userid: ${userid?c},
      username: ${username?c},
      signatureAlgorithms: [<#list signatureAlgorithms as algorithm>${algorithm?c},</#list>],
      rpEntityName: ${rpEntityName?c},
      rpId: ${rpId?c},
      attestationConveyancePreference: ${attestationConveyancePreference?c},
      authenticatorAttachment: ${authenticatorAttachment?c},
      requireResidentKey: ${requireResidentKey?c},
      residentKey: ${residentKey?c},
      userVerificationRequirement: ${userVerificationRequirement?c},
      createTimeout: ${createTimeout?c},
      excludeCredentialIds: ${excludeCredentialIds?c},
      initLabel: ${msg("tmPasskeyName")?c},
      initLabelPrompt: ${msg("tmPasskeyName")?c},
      errmsg: ${msg("tmPasskeyUnsupported")?c},
    }), { once: true });
    </#outputformat>
  </script>
</@layout.page>
