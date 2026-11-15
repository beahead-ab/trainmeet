package app.trainmeet.id;

import java.util.List;
import java.util.Set;
import org.jboss.logging.Logger;
import org.keycloak.models.ClientModel;
import org.keycloak.models.KeycloakSession;
import org.keycloak.models.RealmModel;
import org.keycloak.models.RequiredActionProviderModel;
import org.keycloak.models.WebAuthnPolicy;

/**
 * Brings a realm that already exists up to date with id/realm/trainmeet.json.
 *
 * <p>Keycloak reads the realm file only the first time, when the realm does not exist. A change to
 * the file therefore also needs an update here, numbered like Catalog's migrations: the realm
 * keeps its number in the attribute trainmeetVersion, and every update above it runs once when
 * Keycloak starts. The file carries the latest number, so a new realm runs none. The check
 * "Tester" compares the two (id/tests/test_realm.py).
 */
final class RealmUpdates {
    private static final Logger LOG = Logger.getLogger(RealmUpdates.class);

    static final String REALM = "trainmeet";
    static final String VERSION = "trainmeetVersion";
    /** The latest update. The realm file says the same. */
    static final int LATEST = 3;

    static final String PASSKEY_ACTION = "webauthn-register-passwordless";

    private RealmUpdates() {}

    static void apply(KeycloakSession session) {
        RealmModel realm = session.realms().getRealmByName(REALM);
        if (realm == null) {
            return; // made from the file, which is up to date
        }
        int version = parse(realm.getAttribute(VERSION));
        if (version >= LATEST) {
            return;
        }
        if (version < 2) {
            passkeys(realm);
        }
        if (version < 3) {
            idWebApp(realm);
        }
        realm.setAttribute(VERSION, Integer.toString(LATEST));
        LOG.infof("Realmen %s är uppdaterad från %d till %d.", REALM, version, LATEST);
    }

    /** 2: passkey as an option beside the code to the email (KONTO-33, ID5). */
    static void passkeys(RealmModel realm) {
        WebAuthnPolicy policy = realm.getWebAuthnPolicyPasswordless();
        policy.setRpEntityName("TrainMeet");
        policy.setResidentKey("required");
        policy.setUserVerificationRequirement("required");
        policy.setPasskeysEnabled(true);
        realm.setWebAuthnPolicyPasswordless(policy);
        if (realm.getRequiredActionProviderByAlias(PASSKEY_ACTION) == null) {
            RequiredActionProviderModel action = new RequiredActionProviderModel();
            action.setAlias(PASSKEY_ACTION);
            action.setName("Webauthn Register Passwordless");
            action.setProviderId(PASSKEY_ACTION);
            action.setEnabled(true);
            action.setDefaultAction(false);
            action.setPriority(80);
            realm.addRequiredActionProvider(action);
        }
    }

    static final String ID_CLIENT = "id";
    static final List<String> SCOPES = List.of("web-origins", "acr", "basic", "profile", "email");

    /**
     * 3: ID's own web app (#67) logs in like Catalog, as the client "id", with its secret and
     * address from the environment (ID_APP_SECRET, ID_PUBLIC_URL).
     */
    static void idWebApp(RealmModel realm) {
        if (realm.getClientByClientId(ID_CLIENT) != null) {
            return;
        }
        String secret = System.getenv("ID_APP_SECRET");
        String address = System.getenv("ID_PUBLIC_URL");
        if (secret == null || secret.isBlank() || address == null || address.isBlank()) {
            LOG.warn("ID_APP_SECRET eller ID_PUBLIC_URL saknas, så ID:s webbapp får ingen klient.");
            return;
        }
        ClientModel client = realm.addClient(ID_CLIENT);
        client.setName("TrainMeet ID");
        client.setEnabled(true);
        client.setProtocol("openid-connect");
        client.setPublicClient(false);
        client.setClientAuthenticatorType("client-secret");
        client.setSecret(secret);
        client.setStandardFlowEnabled(true);
        client.setImplicitFlowEnabled(false);
        client.setDirectAccessGrantsEnabled(false);
        client.setServiceAccountsEnabled(false);
        client.setFrontchannelLogout(false);
        client.setRedirectUris(Set.of(address + "/api/id/1/login/callback"));
        client.setWebOrigins(Set.of(address));
        client.setAttribute("pkce.code.challenge.method", "S256");
        client.setAttribute("post.logout.redirect.uris", address + "/*");
        realm.getClientScopesStream()
                .filter(scope -> SCOPES.contains(scope.getName()))
                .forEach(scope -> client.addClientScope(scope, true));
    }

    private static int parse(String value) {
        try {
            return value == null ? 1 : Integer.parseInt(value.trim());
        } catch (NumberFormatException e) {
            return 1;
        }
    }
}
