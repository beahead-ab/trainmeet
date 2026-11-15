<#import "tm-layout.ftl" as layout>
<#-- Asked once after a login with the code, when the person has no passkey (KONTO-33). -->
<@layout.page title=msg("tmPasskeyOfferTitle")>
  <p>${msg("tmPasskeyOfferText")}</p>
  <form id="passkey-svar" action="${url.loginAction}" method="post">
    <button class="id-knapp primar" type="submit" name="passkey" value="yes">${msg("tmPasskeyAdd")}</button>
    <button class="id-knapp" type="submit" name="passkey" value="no">${msg("tmNotNow")}</button>
  </form>
  <p class="id-liten">${msg("tmPasskeyOfferSmall")}</p>
  <script>
    // A browser without passkeys answers nothing and goes on; it is asked again next time.
    if (!window.PublicKeyCredential) {
      const form = document.getElementById("passkey-svar");
      const later = document.createElement("input");
      later.type = "hidden";
      later.name = "passkey";
      later.value = "later";
      form.querySelectorAll("button").forEach((button) => button.remove());
      form.appendChild(later);
      form.submit();
    }
  </script>
</@layout.page>
