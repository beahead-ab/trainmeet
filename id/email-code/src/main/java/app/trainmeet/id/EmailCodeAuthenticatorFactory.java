package app.trainmeet.id;

import java.util.List;
import org.keycloak.Config;
import org.keycloak.authentication.Authenticator;
import org.keycloak.authentication.AuthenticatorFactory;
import org.keycloak.models.AuthenticationExecutionModel;
import org.keycloak.models.KeycloakSession;
import org.keycloak.models.KeycloakSessionFactory;
import org.keycloak.provider.ProviderConfigProperty;

/** Registers the code to the email with Keycloak. Used in the realm's login flow (id/realm). */
public class EmailCodeAuthenticatorFactory implements AuthenticatorFactory {
    public static final String ID = "trainmeet-email-code";
    private static final EmailCodeAuthenticator SINGLETON = new EmailCodeAuthenticator();

    @Override
    public String getId() {
        return ID;
    }

    @Override
    public String getDisplayType() {
        return "TrainMeet: kod till e-posten";
    }

    @Override
    public String getReferenceCategory() {
        return "email-code";
    }

    @Override
    public boolean isConfigurable() {
        return false;
    }

    @Override
    public AuthenticationExecutionModel.Requirement[] getRequirementChoices() {
        return new AuthenticationExecutionModel.Requirement[] {
            AuthenticationExecutionModel.Requirement.REQUIRED,
            AuthenticationExecutionModel.Requirement.ALTERNATIVE,
            AuthenticationExecutionModel.Requirement.DISABLED
        };
    }

    @Override
    public boolean isUserSetupAllowed() {
        return false;
    }

    @Override
    public String getHelpText() {
        return "Logga in eller skapa konto med en kod till e-posten, utan lösenord (ID5).";
    }

    @Override
    public List<ProviderConfigProperty> getConfigProperties() {
        return List.of();
    }

    @Override
    public Authenticator create(KeycloakSession session) {
        return SINGLETON;
    }

    @Override
    public void init(Config.Scope config) {}

    @Override
    public void postInit(KeycloakSessionFactory factory) {}

    @Override
    public void close() {}
}
