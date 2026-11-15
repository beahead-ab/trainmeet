package app.trainmeet.id;

import jakarta.ws.rs.core.MultivaluedMap;
import jakarta.ws.rs.core.Response;
import java.security.SecureRandom;
import java.text.MessageFormat;
import java.time.Instant;
import java.util.HashMap;
import java.util.Locale;
import java.util.Map;
import java.util.Properties;
import org.jboss.logging.Logger;
import org.keycloak.authentication.AuthenticationFlowContext;
import org.keycloak.authentication.Authenticator;
import org.keycloak.authentication.authenticators.browser.WebAuthnConditionalUIAuthenticator;
import org.keycloak.email.EmailException;
import org.keycloak.email.EmailSenderProvider;
import org.keycloak.forms.login.LoginFormsProvider;
import org.keycloak.models.Constants;
import org.keycloak.models.KeycloakSession;
import org.keycloak.models.RealmModel;
import org.keycloak.models.SingleUseObjectProvider;
import org.keycloak.models.UserModel;
import org.keycloak.models.credential.WebAuthnCredentialModel;
import org.keycloak.sessions.AuthenticationSessionModel;
import org.keycloak.theme.Theme;

/**
 * Log in with a code to the email, without a password (ID5, KONTO-33).
 *
 * <p>Logga in: the email, then the code. Skapa konto: the name and the email, then the code. The
 * account is made when the code is right, never before, so a mistyped address leaves nothing
 * behind. A code is sent whether or not there is an account, so the page never tells whether an
 * address has one. Someone who logs in for the first time without a name gives one after the code.
 * The address is verified by the code, so the token says email_verified (KONTO-10).
 *
 * <p>Passkey is the option (KONTO-33): the email page offers Logga in med passkey, and the
 * browser suggests a passkey in the email field. Keycloak's own passkey login checks it. After a
 * login with the code, someone without a passkey is asked once whether to add one; the answer is
 * kept for 30 days.
 */
public class EmailCodeAuthenticator implements Authenticator {
    private static final Logger LOG = Logger.getLogger(EmailCodeAuthenticator.class);
    private static final SecureRandom RANDOM = new SecureRandom();

    static final String EMAIL_PAGE = "tm-email.ftl";
    static final String CREATE_PAGE = "tm-create.ftl";
    static final String CODE_PAGE = "tm-code.ftl";
    static final String NAME_PAGE = "tm-name.ftl";
    static final String PASSKEY_PAGE = "tm-passkey.ftl";

    /** When the person last answered the question about a passkey, in epoch seconds. */
    static final String PASSKEY_ASKED = "tmPasskeyAsked";
    static final long ASK_AGAIN_AFTER_SECONDS = 30L * 24 * 3600;

    private static final String NOTE = "tm.code.";
    private static final String EMAIL = NOTE + "email";
    private static final String NAME = NOTE + "name";
    private static final String HASH = NOTE + "hash";
    private static final String SALT = NOTE + "salt";
    private static final String EXPIRES = NOTE + "expires";
    private static final String ATTEMPTS = NOTE + "attempts";
    private static final String SENDS = NOTE + "sends";
    private static final String LAST_SENT = NOTE + "last";
    private static final String VERIFIED = NOTE + "verified";
    private static final String OFFERED = NOTE + "offered";

    private final WebAuthnConditionalUIAuthenticator passkeys;

    public EmailCodeAuthenticator(KeycloakSession session) {
        // Keycloak's passkey login, shown on the email page, which also shows its errors.
        this.passkeys = new WebAuthnConditionalUIAuthenticator(session, context -> show(context, EMAIL_PAGE, null));
    }

    @Override
    public void authenticate(AuthenticationFlowContext context) {
        context.challenge(show(context, EMAIL_PAGE, null));
    }

    @Override
    public void action(AuthenticationFlowContext context) {
        MultivaluedMap<String, String> form = context.getHttpRequest().getDecodedFormParameters();
        AuthenticationSessionModel login = context.getAuthenticationSession();
        if (passkeys.isPasskeysEnabled() && (form.containsKey("authenticatorData") || form.containsKey("error"))) {
            passkeys.action(context); // logs in, or shows the email page with the error
        } else if (form.containsKey("passkey") && "true".equals(login.getAuthNote(OFFERED))) {
            answer(context, form.getFirst("passkey"));
        } else if (form.containsKey("restart")) {
            clear(login);
            context.challenge(show(context, EMAIL_PAGE, null));
        } else if (form.containsKey("create")) {
            context.challenge(show(context, CREATE_PAGE, null));
        } else if (form.containsKey("send")) {
            send(context, form);
        } else if (form.containsKey("resend")) {
            resend(context);
        } else if (form.containsKey("code")) {
            check(context, form.getFirst("code"));
        } else if (form.containsKey("name") && "true".equals(login.getAuthNote(VERIFIED))) {
            name(context, form.getFirst("name"));
        } else {
            context.challenge(show(context, EMAIL_PAGE, null));
        }
    }

    private void send(AuthenticationFlowContext context, MultivaluedMap<String, String> form) {
        boolean creating = form.containsKey("creating");
        String returnPage = creating ? CREATE_PAGE : EMAIL_PAGE;
        String email = Codes.normalizeEmail(form.getFirst("email"));
        String name = Codes.normalizeName(form.getFirst("name"));
        if (email == null) {
            context.challenge(page(context, returnPage, "tmInvalidEmail").setAttribute("name", name).createForm(returnPage));
            return;
        }
        if (creating && name == null) {
            context.challenge(page(context, CREATE_PAGE, "tmNameMissing").setAttribute("email", email).createForm(CREATE_PAGE));
            return;
        }
        AuthenticationSessionModel login = context.getAuthenticationSession();
        clear(login);
        login.setAuthNote(EMAIL, email);
        if (name != null) {
            login.setAuthNote(NAME, name);
        }
        sendCode(context, null);
    }

    private void resend(AuthenticationFlowContext context) {
        AuthenticationSessionModel login = context.getAuthenticationSession();
        if (login.getAuthNote(EMAIL) == null) {
            context.challenge(show(context, EMAIL_PAGE, null));
            return;
        }
        long last = number(login.getAuthNote(LAST_SENT));
        if (Instant.now().getEpochSecond() - last < Codes.RESEND_AFTER_SECONDS) {
            context.challenge(codePage(context, "tmWait").createForm(CODE_PAGE));
            return;
        }
        sendCode(context, "tmCodeSentAgain");
    }

    /** A new code to the address in the login, within the limits. */
    private void sendCode(AuthenticationFlowContext context, String infoKey) {
        AuthenticationSessionModel login = context.getAuthenticationSession();
        int sends = (int) number(login.getAuthNote(SENDS));
        if (sends >= Codes.MAX_SENDS || !allowedForAddress(context.getSession(), login.getAuthNote(EMAIL))) {
            context.challenge(show(context, EMAIL_PAGE, "tmTooManyCodes"));
            return;
        }
        String code = Codes.newCode(RANDOM);
        String salt = Codes.newSalt(RANDOM);
        long now = Instant.now().getEpochSecond();
        login.setAuthNote(SALT, salt);
        login.setAuthNote(HASH, Codes.hash(code, salt));
        login.setAuthNote(EXPIRES, Long.toString(now + Codes.LIFETIME_SECONDS));
        login.setAuthNote(ATTEMPTS, "0");
        login.setAuthNote(SENDS, Integer.toString(sends + 1));
        login.setAuthNote(LAST_SENT, Long.toString(now));
        try {
            mail(context.getSession(), context.getRealm(), login.getAuthNote(EMAIL), code);
        } catch (EmailException e) {
            // The address is personal data: it is never written to the log.
            LOG.warnf("Koden gick inte att skicka: %s", e.getClass().getSimpleName());
            context.challenge(show(context, EMAIL_PAGE, "tmMailFailed"));
            return;
        }
        LoginFormsProvider page = codePage(context, null);
        if (infoKey != null) {
            page.setInfo(infoKey);
        }
        context.challenge(page.createForm(CODE_PAGE));
    }

    private boolean allowedForAddress(KeycloakSession session, String email) {
        SingleUseObjectProvider counts = session.singleUseObjects();
        String key = Codes.addressKey(email);
        Map<String, String> found = counts.get(key);
        int sent = found == null ? 0 : (int) number(found.get("sent"));
        if (sent >= Codes.MAX_PER_ADDRESS) {
            return false;
        }
        Map<String, String> next = new HashMap<>();
        next.put("sent", Integer.toString(sent + 1));
        if (found == null) {
            counts.put(key, Codes.ADDRESS_WINDOW_SECONDS, next);
        } else {
            counts.replace(key, next);
        }
        return true;
    }

    private void check(AuthenticationFlowContext context, String typed) {
        AuthenticationSessionModel login = context.getAuthenticationSession();
        if (login.getAuthNote(HASH) == null) {
            context.challenge(show(context, EMAIL_PAGE, null));
            return;
        }
        if (Instant.now().getEpochSecond() > number(login.getAuthNote(EXPIRES))) {
            context.challenge(codePage(context, "tmCodeExpired").createForm(CODE_PAGE));
            return;
        }
        int attempts = (int) number(login.getAuthNote(ATTEMPTS));
        if (attempts >= Codes.MAX_ATTEMPTS) {
            context.challenge(codePage(context, "tmTooManyAttempts").createForm(CODE_PAGE));
            return;
        }
        if (!Codes.matches(typed, login.getAuthNote(SALT), login.getAuthNote(HASH))) {
            login.setAuthNote(ATTEMPTS, Integer.toString(attempts + 1));
            String key = attempts + 1 >= Codes.MAX_ATTEMPTS ? "tmTooManyAttempts" : "tmWrongCode";
            context.challenge(codePage(context, key).createForm(CODE_PAGE));
            return;
        }
        // The code is used: it cannot be used again.
        login.removeAuthNote(HASH);
        login.setAuthNote(VERIFIED, "true");
        String email = login.getAuthNote(EMAIL);
        UserModel user = context.getSession().users().getUserByEmail(context.getRealm(), email);
        if (user != null) {
            finish(context, user);
        } else if (login.getAuthNote(NAME) != null) {
            finish(context, create(context, email, login.getAuthNote(NAME)));
        } else {
            context.challenge(page(context, NAME_PAGE, null).setAttribute("email", email).createForm(NAME_PAGE));
        }
    }

    private void name(AuthenticationFlowContext context, String typed) {
        String name = Codes.normalizeName(typed);
        String email = context.getAuthenticationSession().getAuthNote(EMAIL);
        if (name == null) {
            context.challenge(page(context, NAME_PAGE, "tmNameMissing").setAttribute("email", email).createForm(NAME_PAGE));
            return;
        }
        UserModel user = context.getSession().users().getUserByEmail(context.getRealm(), email);
        finish(context, user != null ? user : create(context, email, name));
    }

    private UserModel create(AuthenticationFlowContext context, String email, String name) {
        UserModel user = context.getSession().users().addUser(context.getRealm(), email);
        user.setEnabled(true);
        user.setEmail(email);
        user.setEmailVerified(true);
        user.setFirstName(name);
        context.getEvent().detail("registered", "true");
        return user;
    }

    private void finish(AuthenticationFlowContext context, UserModel user) {
        if (!user.isEnabled()) {
            context.challenge(show(context, EMAIL_PAGE, "tmDisabled"));
            return;
        }
        if (!user.isEmailVerified()) {
            user.setEmailVerified(true);
        }
        AuthenticationSessionModel login = context.getAuthenticationSession();
        clear(login);
        context.setUser(user);
        if (offerPasskey(user)) {
            login.setAuthNote(OFFERED, "true");
            context.challenge(show(context, PASSKEY_PAGE, null));
            return;
        }
        context.success();
    }

    /** Ask about a passkey: passkeys are on, the person has none, and was not asked lately. */
    private boolean offerPasskey(UserModel user) {
        if (!passkeys.isPasskeysEnabled()) {
            return false;
        }
        boolean hasOne = user.credentialManager()
                .getStoredCredentialsByTypeStream(WebAuthnCredentialModel.TYPE_PASSWORDLESS)
                .findAny()
                .isPresent();
        long asked = number(user.getFirstAttribute(PASSKEY_ASKED));
        return !hasOne && Instant.now().getEpochSecond() - asked > ASK_AGAIN_AFTER_SECONDS;
    }

    /**
     * Ja: Keycloak's own page for adding a passkey follows, as if the app had asked for it, so it
     * can be skipped there too. Inte nu: not asked again for 30 days. A browser without passkeys
     * answers nothing and is asked again next time.
     */
    private void answer(AuthenticationFlowContext context, String answer) {
        AuthenticationSessionModel login = context.getAuthenticationSession();
        login.removeAuthNote(OFFERED);
        UserModel user = context.getUser();
        if (user == null) {
            context.challenge(show(context, EMAIL_PAGE, null));
            return;
        }
        if ("yes".equals(answer) || "no".equals(answer)) {
            user.setSingleAttribute(PASSKEY_ASKED, Long.toString(Instant.now().getEpochSecond()));
        }
        if ("yes".equals(answer)) {
            login.setClientNote(Constants.KC_ACTION, RealmUpdates.PASSKEY_ACTION);
        }
        context.success();
    }

    // --- The pages and the mail -----------------------------------------------------------

    private LoginFormsProvider form(AuthenticationFlowContext context, String errorKey) {
        LoginFormsProvider form = context.form();
        if (errorKey != null) {
            form.setError(errorKey);
        }
        return form;
    }

    private LoginFormsProvider page(AuthenticationFlowContext context, String template, String errorKey) {
        LoginFormsProvider form = form(context, errorKey).setAttribute("tmPage", template);
        if (EMAIL_PAGE.equals(template) && passkeys.isPasskeysEnabled()) {
            passkeys.fillContextForm(context); // a new challenge for Logga in med passkey
        }
        return form;
    }

    private Response show(AuthenticationFlowContext context, String template, String errorKey) {
        return page(context, template, errorKey).createForm(template);
    }

    private LoginFormsProvider codePage(AuthenticationFlowContext context, String errorKey) {
        AuthenticationSessionModel login = context.getAuthenticationSession();
        return form(context, errorKey)
                .setAttribute("tmPage", CODE_PAGE)
                .setAttribute("email", login.getAuthNote(EMAIL))
                .setAttribute("minutes", Codes.LIFETIME_SECONDS / 60);
    }

    private static void mail(KeycloakSession session, RealmModel realm, String to, String code) throws EmailException {
        Locale locale = session.getContext().resolveLocale(null);
        Properties messages;
        try {
            Theme theme = session.theme().getTheme(Theme.Type.LOGIN);
            messages = theme.getEnhancedMessages(realm, locale);
        } catch (java.io.IOException e) {
            throw new EmailException("Temat gick inte att läsa", e);
        }
        String spaced = code.substring(0, 3) + " " + code.substring(3);
        Object[] args = {spaced, Codes.LIFETIME_SECONDS / 60};
        String subject = format(messages, "tmMailSubject", locale, args);
        String intro = format(messages, "tmMailIntro", locale, args);
        String valid = format(messages, "tmMailValid", locale, args);
        String ignore = format(messages, "tmMailIgnore", locale, args);
        String text = intro + "\n\n    " + spaced + "\n\n" + valid + "\n\n" + ignore + "\n\nTrainMeet ID\n";
        String html = "<!doctype html><html><body style=\"font-family:Inter,Arial,sans-serif;color:#111317\">"
                + "<p>" + escape(intro) + "</p>"
                + "<p style=\"font-size:32px;font-weight:700;letter-spacing:0.12em;font-family:monospace\">"
                + escape(spaced) + "</p>"
                + "<p>" + escape(valid) + "</p><p style=\"color:#5b606b\">" + escape(ignore) + "</p>"
                + "<p style=\"color:#5b606b\">TrainMeet ID</p></body></html>";
        EmailSenderProvider sender = session.getProvider(EmailSenderProvider.class);
        sender.send(realm.getSmtpConfig(), to, subject, text, html);
    }

    private static String format(Properties messages, String key, Locale locale, Object[] args) {
        String pattern = messages.getProperty(key, key);
        return new MessageFormat(pattern, locale).format(args);
    }

    private static String escape(String text) {
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\"", "&quot;");
    }

    private static long number(String value) {
        try {
            return value == null ? 0 : Long.parseLong(value);
        } catch (NumberFormatException e) {
            return 0;
        }
    }

    private static void clear(AuthenticationSessionModel login) {
        for (String note : new String[] {EMAIL, NAME, HASH, SALT, EXPIRES, ATTEMPTS, SENDS, LAST_SENT, VERIFIED, OFFERED}) {
            login.removeAuthNote(note);
        }
    }

    @Override
    public boolean requiresUser() {
        return false;
    }

    @Override
    public boolean configuredFor(KeycloakSession session, RealmModel realm, UserModel user) {
        return true;
    }

    @Override
    public void setRequiredActions(KeycloakSession session, RealmModel realm, UserModel user) {}

    @Override
    public void close() {}
}
