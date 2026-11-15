package app.trainmeet.id;

import org.jboss.logging.Logger;
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
    static final int LATEST = 2;

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

    private static int parse(String value) {
        try {
            return value == null ? 1 : Integer.parseInt(value.trim());
        } catch (NumberFormatException e) {
            return 1;
        }
    }
}
