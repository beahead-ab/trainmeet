<#import "tm-layout.ftl" as layout>
<@layout.page title=msg("tmLoginTitle")>
  <form action="${url.loginAction}" method="post" novalidate>
    <label for="email">${msg("tmEmail")}</label>
    <input id="email" name="email" type="email" autocomplete="${(enableWebAuthnConditionalUI?has_content)?then('email webauthn', 'email')}" inputmode="email" required autofocus value="${(email!'')}">
    <button class="id-knapp primar" type="submit" name="send" value="1">${msg("tmSendCode")}</button>
  </form>
  <#if enableWebAuthnConditionalUI?has_content>
    <#-- Passkey, the option (KONTO-33): the browser suggests one in the email field, or the link asks for one. -->
    <form id="webauth" action="${url.loginAction}" method="post" hidden>
      <input type="hidden" id="clientDataJSON" name="clientDataJSON">
      <input type="hidden" id="authenticatorData" name="authenticatorData">
      <input type="hidden" id="signature" name="signature">
      <input type="hidden" id="credentialId" name="credentialId">
      <input type="hidden" id="userHandle" name="userHandle">
      <input type="hidden" id="error" name="error">
    </form>
    <button class="id-lank" type="button" id="authenticateWebAuthnButton">${msg("tmPasskeyLogIn")}</button>
    <script type="module">
      <#outputformat "JavaScript">
      import { authenticateByWebAuthn } from "${url.resourcesPath}/js/webauthnAuthenticate.js";
      import { initAuthenticate } from "${url.resourcesPath}/js/passkeysConditionalAuth.js";
      const args = {
        isUserIdentified: ${isUserIdentified},
        challenge: ${challenge?c},
        userVerification: ${userVerification?c},
        rpId: ${rpId?c},
        createTimeout: ${createTimeout?c},
        mediation: "conditional",
        authenticatorAttachment: ${authenticatorAttachment?c},
      };
      const button = document.getElementById("authenticateWebAuthnButton");
      if (!window.PublicKeyCredential) {
        button.hidden = true;
      } else {
        initAuthenticate({ errmsg: ${msg("tmPasskeyUnsupported")?c}, ...args });
        button.addEventListener("click", () => authenticateByWebAuthn({ errmsg: ${msg("tmPasskeyUnsupported")?c}, ...args }));
      }
      </#outputformat>
    </script>
  </#if>
  <p class="id-mellan"><span>${msg("tmFirstTime")}</span></p>
  <form action="${url.loginAction}" method="post">
    <button class="id-knapp" type="submit" name="create" value="1">${msg("tmCreate")}</button>
  </form>
  <p class="id-liten">${msg("tmTrainCatalog")}</p>
</@layout.page>
