package app.trainmeet.id;

import java.util.List;
import java.util.Set;
import org.jboss.logging.Logger;
import org.keycloak.models.AdminRoles;
import org.keycloak.models.ClientModel;
import org.keycloak.models.Constants;
import org.keycloak.models.KeycloakSession;
import org.keycloak.models.KeycloakSessionFactory;
import org.keycloak.models.RealmModel;
import org.keycloak.models.RequiredActionProviderModel;
import org.keycloak.models.RoleModel;
import org.keycloak.models.UserModel;
import org.keycloak.models.WebAuthnPolicy;
import org.keycloak.models.utils.KeycloakModelUtils;
import org.keycloak.services.managers.ClientManager;
import org.keycloak.services.managers.RealmManager;

/**
 * Brings a realm that already exists up to date with id/realm/trainmeet.json.
 *
 * <p>Keycloak reads the realm file only the first time, when the realm does not exist. A change to
 * the file therefore also needs an update here, numbered like Catalog's migrations: the realm
 * keeps its number in the attribute trainmeetVersion, and every update above it runs once when
 * Keycloak starts, each in a transaction of its own. The file carries the latest number, so a
 * new realm runs none. The check "Tester" compares the two (id/tests/test_realm.py).
 */
final class RealmUpdates {
    private static final Logger LOG = Logger.getLogger(RealmUpdates.class);

    static final String REALM = "trainmeet";
    static final String VERSION = "trainmeetVersion";
    /** The latest update. The realm file says the same. */
    static final int LATEST = 5;

    static final String PASSKEY_ACTION = "webauthn-register-passwordless";

    private RealmUpdates() {}

    /** One update: the realm as it is, and the session it runs in. */
    interface Step {
        void run(KeycloakSession session, RealmModel realm);
    }

    /** The updates in order; the one at index i takes the realm from i + 1 to i + 2. */
    static final List<Step> STEPS = List.of(
            (session, realm) -> passkeys(realm),
            (session, realm) -> idWebApp(realm),
            RealmUpdates::catalogAsks,
            RealmUpdates::idRemovesAccounts);

    /**
     * Every update runs in a transaction of its own, together with the new number. One that fails
     * is rolled back and logged, and the ones after it wait: Keycloak still starts, and the login
     * still works, with the realm as it was.
     */
    static void apply(KeycloakSessionFactory factory) {
        for (int step = 2; step <= LATEST; step++) {
            int target = step;
            try {
                boolean ran = KeycloakModelUtils.runJobInTransactionWithResult(factory, session -> {
                    RealmModel realm = session.realms().getRealmByName(REALM);
                    if (realm == null || parse(realm.getAttribute(VERSION)) >= target) {
                        return false; // made from the file, or already updated
                    }
                    STEPS.get(target - 2).run(session, realm);
                    realm.setAttribute(VERSION, Integer.toString(target));
                    return true;
                });
                if (ran) {
                    LOG.infof("Realmen %s är uppdaterad till %d.", REALM, target);
                }
            } catch (RuntimeException e) {
                LOG.errorf(e, "Uppdatering %d av realmen %s gick inte och väntar till nästa start.", target, REALM);
                return;
            }
        }
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

    static final String CATALOG_CLIENT = "catalog";

    /**
     * 4: Catalog asks ID's API about the roles with a token of its own, from client credentials
     * (KONTO-34, #49). Its service account has no roles in Keycloak; ID's API knows it by the
     * token's azp.
     */
    static void catalogAsks(KeycloakSession session, RealmModel realm) {
        ClientModel client = realm.getClientByClientId(CATALOG_CLIENT);
        if (client == null || client.isServiceAccountsEnabled()) {
            return;
        }
        client.setServiceAccountsEnabled(true);
        // Keycloak makes the service account in the realm the session works in.
        session.getContext().setRealm(realm);
        new ClientManager(new RealmManager(session)).enableServiceAccount(client);
    }

    static final String ADMIN_API_SCOPE = "kc-admin-api";

    /**
     * 5: ID's API removes the account in Keycloak when the person removes it in ID (KONTO-31, ID7).
     * The client "id" gets a service account with the one role it needs: manage-users, and
     * Keycloak's own scope kc-admin-api, which puts the admin API's audience in its token. Keycloak
     * 26.8 lets no token without it into the admin API.
     */
    static void idRemovesAccounts(KeycloakSession session, RealmModel realm) {
        ClientModel client = realm.getClientByClientId(ID_CLIENT);
        if (client == null) {
            LOG.warn("Klienten id saknas, så ID:s API kan inte ta bort konton.");
            return;
        }
        session.getContext().setRealm(realm);
        if (!client.isServiceAccountsEnabled()) {
            client.setServiceAccountsEnabled(true);
            new ClientManager(new RealmManager(session)).enableServiceAccount(client);
        }
        realm.getClientScopesStream()
                .filter(scope -> ADMIN_API_SCOPE.equals(scope.getName()))
                .forEach(scope -> client.addClientScope(scope, true));
        UserModel account = session.users().getServiceAccount(client);
        ClientModel management = realm.getClientByClientId(Constants.REALM_MANAGEMENT_CLIENT_ID);
        RoleModel manage = management == null ? null : management.getRole(AdminRoles.MANAGE_USERS);
        if (account != null && manage != null && !account.hasRole(manage)) {
            account.grantRole(manage);
        }
    }

    private static int parse(String value) {
        try {
            return value == null ? 1 : Integer.parseInt(value.trim());
        } catch (NumberFormatException e) {
            return 1;
        }
    }
}
