# TrainMeet ID as a container image: Keycloak (ID4, KONTO-23) with the code to the email
# (id/email-code, ID5) and the realm (id/realm). Build from the repo root:
#   docker build -f id/Dockerfile -t trainmeet-id .
# The database, the hostname and the mail server come from the environment when it starts; the
# mail server's password from Keycloak's vault (KC_VAULT_DIR), never from the image.
# Nothing in it is tied to one cloud: a container and PostgreSQL (ST14).

ARG KEYCLOAK=quay.io/keycloak/keycloak:26.8.2

FROM maven:3-eclipse-temurin-21 AS extension
WORKDIR /src
COPY id/email-code/pom.xml .
RUN mvn -B -q dependency:go-offline
COPY id/email-code/src src
# The extension's tests run here: a red extension never becomes an image.
RUN mvn -B -q package

FROM ${KEYCLOAK} AS build
COPY --from=extension /src/target/trainmeet-email-code.jar /opt/keycloak/providers/
# The vault is chosen when Keycloak is built, the folder when it starts.
ENV KC_DB=postgres \
    KC_HEALTH_ENABLED=true \
    KC_METRICS_ENABLED=false \
    KC_VAULT=file
RUN /opt/keycloak/bin/kc.sh build

FROM ${KEYCLOAK}
COPY --from=build /opt/keycloak/ /opt/keycloak/
COPY id/realm/trainmeet.json /opt/keycloak/data/import/trainmeet.json

ARG TRAINMEET_COMMIT=""
LABEL org.opencontainers.image.title="TrainMeet ID" \
      org.opencontainers.image.revision=$TRAINMEET_COMMIT \
      org.opencontainers.image.licenses="AGPL-3.0-only"
ENV KC_DB=postgres \
    KC_HEALTH_ENABLED=true \
    KC_HTTP_ENABLED=true \
    KC_PROXY_HEADERS=xforwarded \
    KC_VAULT=file \
    KC_VAULT_DIR=/opt/keycloak/vault \
    TRAINMEET_COMMIT=$TRAINMEET_COMMIT

EXPOSE 8080 9000
ENTRYPOINT ["/opt/keycloak/bin/kc.sh"]
# The realm is read the first time; after that the database holds it.
CMD ["start", "--optimized", "--import-realm"]
