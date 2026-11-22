"""The test environment's setup (deploy/testmiljo.py), the parts that run without Scaleway."""

from __future__ import annotations

import base64
import json
import re
import shutil
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest
from requests import Response
from scaleway.iam.v1alpha1.types import LocalityType, Quotum, QuotumLimit
from scaleway.instance.v1.custom_api import InstanceUtilsV1API
from scaleway.instance.v1.types import Server, ServerAction, ServerState
from scaleway_core.api import ScalewayException

from deploy import testmiljo
from deploy.testmiljo import Keys, cloud_init, known_hosts_line

ROOT = Path(__file__).resolve().parents[1]

BEGIN, END = "-----BEGIN OPENSSH PRIVATE KEY-----", "-----END OPENSSH PRIVATE KEY-----"
KEYS = Keys(
    deploy_private=f"{BEGIN}\ndeploy-hemlig\n{END}\n",
    deploy_public="ssh-ed25519 AAAAdeploy trainmeet-testmiljo-deploy",
    host_private=f"{BEGIN}\nvard-hemlig\n{END}\n",
    host_public="ssh-ed25519 AAAAhost trainmeet-testmiljo-host",
)


def config() -> dict[str, object]:
    text = cloud_init(KEYS)
    first, rest = text.split("\n", 1)
    assert first == "#cloud-config"
    parsed = json.loads(rest)
    assert isinstance(parsed, dict)
    return parsed


def test_cloud_init_lets_only_the_deploy_key_in() -> None:
    users = config()["users"]
    assert isinstance(users, list)
    deploy = next(u for u in users if isinstance(u, dict) and u["name"] == "deploy")
    assert deploy["ssh_authorized_keys"] == [KEYS.deploy_public]
    assert deploy["lock_passwd"] is True
    assert config()["ssh_pwauth"] is False


def test_the_deploy_private_key_never_leaves_github() -> None:
    assert "deploy-hemlig" not in cloud_init(KEYS)


def test_the_server_gets_a_known_host_key() -> None:
    parsed = config()
    assert parsed["ssh_keys"] == {
        "ed25519_private": KEYS.host_private,
        "ed25519_public": KEYS.host_public,
    }
    assert parsed["ssh_genkeytypes"] == ["ed25519"]


def test_cloud_init_installs_docker_and_prepares_the_hub_folder() -> None:
    parsed = config()
    packages = parsed["packages"]
    assert isinstance(packages, list)
    assert {"docker.io", "docker-compose-v2", "curl"} <= set(packages)
    assert ["chown", "10001:10001", "/srv/trainmeet/hub-data"] in parsed["runcmd"]  # type: ignore[operator]


def test_the_hub_data_folder_belongs_to_the_hub_user_in_the_image() -> None:
    dockerfile = (ROOT / "hub" / "Dockerfile").read_text()
    assert f"--uid {testmiljo.HUB_UID}" in dockerfile


def test_known_hosts_pins_the_server_key() -> None:
    assert known_hosts_line("51.15.0.1", KEYS.host_public) == "51.15.0.1 ssh-ed25519 AAAAhost\n"


def test_keys_survive_the_round_trip_through_secret_manager() -> None:
    assert Keys.from_json(KEYS.to_json()) == KEYS


@pytest.mark.skipif(shutil.which("ssh-keygen") is None, reason="ssh-keygen saknas")
def test_generated_keys_are_two_different_ed25519_pairs() -> None:
    keys = testmiljo.generate_keys()
    assert keys.deploy_public.startswith("ssh-ed25519 ")
    assert keys.host_public.startswith("ssh-ed25519 ")
    assert keys.deploy_public != keys.host_public
    assert "OPENSSH PRIVATE KEY" in keys.deploy_private
    assert "OPENSSH PRIVATE KEY" in keys.host_private


def test_the_ssh_files_are_private(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TESTMILJO_SSH_DIR", str(tmp_path / "ssh"))
    key_file, known_hosts = testmiljo.write_ssh_files(KEYS, "51.15.0.1")
    assert key_file.read_text() == KEYS.deploy_private
    assert key_file.stat().st_mode & 0o777 == 0o600
    assert known_hosts.read_text() == "51.15.0.1 ssh-ed25519 AAAAhost\n"


def test_the_server_files_agree_on_the_names() -> None:
    compose = (ROOT / "deploy" / "testmiljo" / "compose.yaml").read_text()
    caddyfile = (ROOT / "deploy" / "testmiljo" / "Caddyfile").read_text()
    up = (ROOT / "deploy" / "testmiljo" / "up.sh").read_text()
    assert "image: trainmeet-hub:${HUB_TAG" in compose
    assert "./hub-data:/data" in compose
    assert "reverse_proxy hub:8080" in caddyfile
    assert "{$HUB_DOMAIN}" in caddyfile
    assert "HUB_TAG=%s\\nHUB_DOMAIN=%s\\nPI_DOMAIN=%s" in up
    assert "127.0.0.1:8080:8080" in compose


def test_a_pretend_pi_follows_the_test_hub() -> None:
    """Låtsas-Pi (#73): the same hub image as a Pi runs it, at an address of its own behind the
    same Caddy, with its data in a volume of its own. It reaches the test hub by name on
    compose's network, which Synk lets it call over plain HTTP."""
    folder = ROOT / "deploy" / "testmiljo"
    compose = (folder / "compose.yaml").read_text()
    caddyfile = (folder / "Caddyfile").read_text()
    up = (folder / "up.sh").read_text()
    workflow = (ROOT / ".github" / "workflows" / "tester.yml").read_text()
    pi = compose.split("\n  pi:\n")[1].split("\n\n")[0]
    assert "image: trainmeet-hub:${HUB_TAG}" in pi and "TRAINMEET_HUB_NAME: Låtsas-Pi" in pi
    assert "- pi-data:/data" in pi and "127.0.0.1:8084:8080" in pi
    assert "{$PI_DOMAIN}" in caddyfile and "reverse_proxy pi:8080" in caddyfile
    assert 'PI_DOMAIN="${7:-test.pi.trainmeet.app}"' in up and "pi:8084" in up
    assert (
        '"$TAG_BASE" "$PI_DOMAIN" "$TKL_DOMAIN" "$CAD_DOMAIN" < deploy/testmiljo/up.sh' in workflow
    )
    hub_image = (ROOT / "hub" / "Dockerfile").read_text()
    assert "mkdir /data && chown hub:hub /data" in hub_image


def test_the_catalog_check_gives_compose_every_name_it_requires() -> None:
    """The check "Catalogs bild" runs the test environment's compose file, so every variable
    the file requires must be in the check's .env too, or compose refuses to start."""
    compose = (ROOT / "deploy" / "testmiljo" / "compose.yaml").read_text()
    required = set(re.findall(r"\$\{([A-Z_]+):\?", compose))
    workflow = (ROOT / ".github" / "workflows" / "tester.yml").read_text()
    job = workflow.split("\n  catalog:\n")[1].split("\n  id:\n")[0]
    given = set(re.findall(r'echo "([A-Z_]+)=', job.split("} > .env")[0]))
    assert required, "compose.yaml requires nothing?"
    assert required <= given, sorted(required - given)


def test_catalog_has_its_own_database_behind_the_same_caddy() -> None:
    folder = ROOT / "deploy" / "testmiljo"
    compose = (folder / "compose.yaml").read_text()
    caddyfile = (folder / "Caddyfile").read_text()
    up = (folder / "up.sh").read_text()
    backup = (folder / "catalog-backup.sh").read_text()
    assert "image: trainmeet-catalog:${CATALOG_TAG" in compose
    assert "image: postgres:17-alpine" in compose
    assert "catalog-db:/var/lib/postgresql/data" in compose
    assert "127.0.0.1:8081:8080" in compose
    assert "CATALOG_TRIAL_LOGIN: ${CATALOG_TRIAL_LOGIN:?" in compose
    # The trial login goes when TrainMeet ID can send its codes (#66).
    assert "if [ -s id-vault/trainmeet_smtp-password ]; then TRIAL=off; fi" in up
    assert "CATALOG_ID_ISSUER: https://${ID_DOMAIN}/realms/trainmeet" in compose
    assert "CATALOG_ID_INTERNAL: http://id:8080/realms/trainmeet" in compose
    assert "CATALOG_ID_SECRET: ${ID_CATALOG_SECRET}" in compose
    assert "CATALOG_PUBLIC_URL: https://${CATALOG_DOMAIN}" in compose
    assert "CATALOG_ID_API: http://id-api:8080" in compose  # shared fleets (#49)
    assert 'CATALOG_SIMULATED_TAGS: "on"' in compose
    assert "CATALOG_TAG_BASE: ${CATALOG_TAG_BASE:?" in compose
    assert "CATALOG_MIGRATE: check" in compose
    assert "{$CATALOG_DOMAIN}" in caddyfile
    assert "reverse_proxy catalog:8080" in caddyfile
    assert "CATALOG_TAG=%s\\nCATALOG_DOMAIN=%s" in up
    # The backup is taken and verified before the migration, and every night (CAT-39).
    backup_at = up.index("catalog-backup.sh fore-migrering")
    assert backup_at < up.index("python -m catalog.migrate")
    assert "catalog-backup.sh natt" in up
    assert "pg_restore" in backup
    assert "-pass env:CATALOG_BACKUP_KEY" in backup
    # Only the database's own network reaches it: no port is published.
    database = compose.split("  catalog-db:")[1].split("\n  catalog:")[0]
    assert "ports:" not in database


def test_the_tags_final_address_goes_on_to_catalog_once_its_dns_row_is_there() -> None:
    """C38: trainmeet.app/t/<uid> answers in the test environment, and the tags get that address
    only once trainmeet.app points at the server, so no label carries an address that is dead."""
    folder = ROOT / "deploy" / "testmiljo"
    caddyfile = (folder / "Caddyfile").read_text()
    up = (folder / "up.sh").read_text()
    compose = (folder / "compose.yaml").read_text()
    workflow = (ROOT / ".github" / "workflows" / "tester.yml").read_text()
    site = caddyfile.split("{$TAGS_DOMAIN} {")[1].split("\n}")[0]
    assert "redir /t/* https://{$CATALOG_DOMAIN}{uri} 302" in site
    assert "redir https://trainmeet.se 302" in site
    assert "TAGS_DOMAIN: ${TAGS_DOMAIN:?" in compose
    assert 'TAG_BASE="${6:-https://$CATALOG_DOMAIN/t/}"' in up
    assert "printf 'TAGS_DOMAIN=%s\\nCATALOG_TAG_BASE=%s\\n'" in up
    assert "TAGS_DOMAIN: ${{ vars.TESTTAGS_DOMAIN || 'trainmeet.app' }}" in workflow
    assert 'TAG_BASE="https://$TAGS_DOMAIN/t/"' in workflow
    assert (
        '"$TAGS_DOMAIN" "$TAG_BASE" "$PI_DOMAIN" "$TKL_DOMAIN" "$CAD_DOMAIN" '
        "< deploy/testmiljo/up.sh" in workflow
    )
    assert "- name: Prova taggarnas adress" in workflow


def test_tkl_in_the_cloud_reaches_the_test_hub_only_over_the_internet() -> None:
    """KLAR-22, #76: test.tkl.trainmeet.app is TKL in the cloud, one station per browser. It
    reaches the test hub by its public address, through Caddy, so the hub counts it as over the
    internet and asks for a code (H23); never by compose's network, where it would look near."""
    folder = ROOT / "deploy" / "testmiljo"
    compose = (folder / "compose.yaml").read_text()
    caddyfile = (folder / "Caddyfile").read_text()
    up = (folder / "up.sh").read_text()
    workflow = (ROOT / ".github" / "workflows" / "tester.yml").read_text()
    tkl = compose.split("\n  tkl:\n")[1].split("\n\n")[0]
    assert "image: trainmeet-tkl:${HUB_TAG}" in tkl
    assert "TKL_MODE: cloud" in tkl and "TKL_HUBBAR: https://${HUB_DOMAIN}" in tkl
    assert "http://hub" not in tkl
    assert "- tkl-data:/data" in tkl and "127.0.0.1:8085:8090" in tkl
    assert "TKL_DOMAIN: ${TKL_DOMAIN:-test.tkl.trainmeet.app}" in compose
    site = caddyfile.split("{$TKL_DOMAIN} {")[1].split("\n}")[0]
    assert "reverse_proxy tkl:8090" in site and 'X-Robots-Tag "noindex, nofollow"' in site
    assert 'TKL_DOMAIN="${8:-test.tkl.trainmeet.app}"' in up and "tkl:8085" in up
    assert 'docker build -f tkl/Dockerfile -t "trainmeet-tkl:$TAG"' in workflow
    assert "- name: Prova TKL:s adress" in workflow
    assert "name: TKL:s bild" in workflow
    assert "needs: [tester, bilden, catalog, id, tkl, cad]" in workflow


def test_the_cad_check_gives_compose_every_name_it_requires() -> None:
    """The check "CAD:s bild" runs the test environment's compose file too (#89)."""
    compose = (ROOT / "deploy" / "testmiljo" / "compose.yaml").read_text()
    required = set(re.findall(r"\$\{([A-Z_]+):\?", compose))
    workflow = (ROOT / ".github" / "workflows" / "tester.yml").read_text()
    job = workflow.split("\n  cad:\n")[1].split("\n  testmiljon:\n")[0]
    given = set(re.findall(r'echo "([A-Z_]+)=', job.split("} > .env")[0]))
    assert required <= given, sorted(required - given)
    assert {"COMPOSE_PROFILES", "CAD_DB_PASSWORD", "CAD_BACKUP_KEY", "ID_CAD_SECRET"} <= given


def test_cad_has_its_own_database_behind_the_same_caddy() -> None:
    """#89: test.cad.trainmeet.app is CAD with its own PostgreSQL, backed up before every
    migration and every night as Catalog's. Its three secrets come from deploy/testmiljo.py to
    cad.env, as Catalog's, so CAD always runs and no one adds a secret by hand."""
    folder = ROOT / "deploy" / "testmiljo"
    compose = (folder / "compose.yaml").read_text()
    caddyfile = (folder / "Caddyfile").read_text()
    up = (folder / "up.sh").read_text()
    backup = (folder / "cad-backup.sh").read_text()
    workflow = (ROOT / ".github" / "workflows" / "tester.yml").read_text()
    cad = compose.split("\n  cad:\n")[1].split("\n\n")[0]
    database = compose.split("\n  cad-db:\n")[1].split("\n\n")[0]
    assert "image: trainmeet-cad:${CAD_TAG" in cad and '- "127.0.0.1:8086:8080"' in cad
    assert 'profiles: ["cad"]' in cad and 'profiles: ["cad"]' in database
    assert "- cad-db:/var/lib/postgresql/data" in database and "ports:" not in database
    assert "CAD_MIGRATE: check" in cad
    assert "CAD_ID_ISSUER: https://${ID_DOMAIN}/realms/trainmeet" in cad
    assert "CAD_ID_SECRET: ${ID_CAD_SECRET:-}" in cad
    assert "CAD_ID_API: http://id-api:8080" in cad
    assert "ID_CAD_SECRET: ${ID_CAD_SECRET:-}" in compose.split("\n  id:\n")[1]
    assert "ID_API_APPS: catalog,hub,cad" in compose
    site = caddyfile.split("{$CAD_DOMAIN} {")[1].split("\n}")[0]
    assert "reverse_proxy cad:8080" in site and 'X-Robots-Tag "noindex, nofollow"' in site
    assert 'CAD_DOMAIN="${9:-test.cad.trainmeet.app}"' in up
    assert "COMPOSE_PROFILES=cad" in up and "cad:8086" in up
    assert up.index("cad-backup.sh fore-migrering") < up.index("python -m cad.migrate")
    assert "cad-backup.sh natt" in up
    assert "pg_restore" in backup and "-pass env:CAD_BACKUP_KEY" in backup
    assert "cad_migration" in backup and "catalog" not in backup.replace("catalog-backup", "")
    deploy = workflow.split("\n  testmiljon:\n")[1]
    for secret in ("CAD_DB_PASSWORD", "CAD_BACKUP_KEY", "ID_CAD_SECRET"):
        assert f"secrets.{secret}" not in workflow, f"{secret} is made by deploy/testmiljo.py"
        assert secret not in deploy
    assert "CAD_ENV: ${{ steps.server.outputs.cad_env }}" in deploy
    assert "'umask 077; cat > /srv/trainmeet/cad.env' < \"$CAD_ENV\"" in deploy
    assert 'test -s cad.env || { echo "cad.env saknas på servern." >&2; exit 1; }' in up
    assert "for service in hub:8080 pi:8084 tkl:8085 catalog:8081 id-api:8083 cad:8086; do" in up
    assert "for part in hub catalog cad; do" in workflow
    assert "- name: Prova CAD:s adress" in workflow and "name: CAD:s bild" in workflow


def test_help_goes_to_the_support_address_from_the_settings() -> None:
    """ID12: support@trainmeet.se is a setting in the test environment, never in the code."""
    compose = (ROOT / "deploy" / "testmiljo" / "compose.yaml").read_text()
    api = compose.split("\n  id-api:")[1].split("\n  caddy:")[0]
    assert "ID_SUPPORT_ADDRESS: ${ID_SUPPORT_ADDRESS:-support@trainmeet.se}" in api
    assert "ID_API_CATALOG: http://catalog:8080" in api  # KONTO-31, CAT-193
    for code in (ROOT / "id").glob("*.py"):
        assert "support@trainmeet.se" not in code.read_text(), code.name


def test_catalog_secrets_survive_secret_manager_and_stay_private(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    made = testmiljo.generate_catalog_secrets()
    assert testmiljo.CatalogSecrets.from_json(made.to_json()) == made
    assert len(made.backup_key) == 64
    assert made.db_password != made.backup_key
    monkeypatch.setenv("TESTMILJO_SSH_DIR", str(tmp_path))
    path = testmiljo.write_catalog_env(made)
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.read_text() == (
        f"CATALOG_DB_PASSWORD={made.db_password}\nCATALOG_BACKUP_KEY={made.backup_key}\n"
    )


def test_a_secret_is_made_once_and_then_read_back() -> None:
    stored: dict[str, str] = {}

    def list_secrets(**_: object) -> SimpleNamespace:
        found = [SimpleNamespace(id="s1", name="x", version_count=1)] if stored else []
        return SimpleNamespace(secrets=found)

    def create_secret_version(secret_id: str, data: str) -> None:
        stored["data"] = data

    api = Mock()
    api.list_secrets.side_effect = list_secrets
    api.create_secret.return_value = SimpleNamespace(id="s1", name="x", version_count=0)
    api.create_secret_version.side_effect = create_secret_version
    api.access_secret_version.side_effect = lambda **_: SimpleNamespace(data=stored["data"])
    made = Mock(side_effect=["första", "andra"])

    assert testmiljo.ensure_secret(api, "p", "x", "beskrivning", made) == ("första", True)
    assert testmiljo.ensure_secret(api, "p", "x", "beskrivning", made) == ("första", False)
    assert made.call_count == 1


def test_security_group_sends_uppercase_protocols_to_instance_v1() -> None:
    instance = Mock(spec=InstanceUtilsV1API)
    group = SimpleNamespace(name=testmiljo.NAME, id="group")
    instance.list_security_groups.return_value = SimpleNamespace(security_groups=[group])

    assert testmiljo.ensure_security_group(instance, "project") == "group"

    rules = instance.set_security_group_rules.call_args.kwargs["rules"]
    assert [rule.protocol for rule in rules] == ["TCP", "TCP", "TCP", "UDP", "ICMP"] * 2


def test_a_new_server_receives_cloud_init_before_power_on(monkeypatch: pytest.MonkeyPatch) -> None:
    instance = Mock(spec=InstanceUtilsV1API)
    instance.list_servers.return_value = SimpleNamespace(servers=[])
    instance._create_server.return_value = SimpleNamespace(
        server=Mock(spec=Server, id="server", state=ServerState.STOPPED)
    )
    running = Mock(spec=Server, id="server", state=ServerState.RUNNING)
    instance.get_server.return_value = SimpleNamespace(server=running)
    monkeypatch.setattr(testmiljo, "root_volume", lambda *_: ("ubuntu", {}))

    ip = Mock(id="ip")
    assert testmiljo.ensure_server(instance, Mock(), "project", "group", ip, KEYS, "DEV1-S") == (
        running,
        True,
    )
    assert instance.mock_calls[-3:] == [
        call.set_server_user_data(
            server_id="server",
            key="cloud-init",
            content=cloud_init(KEYS).encode(),
            zone=testmiljo.ZONE,
        ),
        call.server_action(zone=testmiljo.ZONE, server_id="server", action=ServerAction.POWERON),
        call.get_server(zone=testmiljo.ZONE, server_id="server"),
    ]


def test_usage_without_command() -> None:
    assert testmiljo.main(["testmiljo.py"]) == 2


def test_a_quota_error_says_what_to_do() -> None:
    body = '{"type": "quotas_exceeded", "message": "quota(s) exceeded for this resource"}'
    text = testmiljo.explain(403, body, "DEV1-S")
    assert "kvoten är slut" in text
    assert "DEV1-S" in text
    assert "Organization → Quotas" in text


def test_a_missing_permission_says_which() -> None:
    assert "InstancesFullAccess" in testmiljo.explain(403, '{"type": "permissions_denied"}', "X")


def test_other_errors_are_passed_on() -> None:
    assert testmiljo.explain(500, "boom", "X") == "Scaleway svarade 500: boom"


def quotum(name: str, limit: int, unlimited: bool = False) -> Quotum:
    return Quotum(
        name=name,
        pretty_name=name,
        unit="",
        description="",
        locality_type=LocalityType.ZONE,
        limits=[QuotumLimit(zone=testmiljo.ZONE, limit=limit, unlimited=unlimited, global_=False)],
        limit=None,
        unlimited=None,
    )


def test_the_quota_report_lists_the_server_types_the_account_may_create() -> None:
    quota = [
        quotum("cp_servers_type_DEV1_S", 0),
        quotum("cp_servers_type_PLAY2_PICO", 10),
        quotum("cp_servers_type_POP2_2C_8G", 1),
        quotum("instances_ip_addresses", 20),
    ]
    assert testmiljo.quota_report(quota) == "Kontot får skapa: PLAY2-PICO (10), POP2-2C-8G (1)."


def test_the_quota_report_says_when_nothing_is_allowed() -> None:
    assert "inte skapa någon" in testmiljo.quota_report([quotum("cp_servers_type_DEV1_S", 0)])


def test_trainmeet_id_has_its_own_database_behind_the_same_caddy() -> None:
    folder = ROOT / "deploy" / "testmiljo"
    compose = (folder / "compose.yaml").read_text()
    caddyfile = (folder / "Caddyfile").read_text()
    up = (folder / "up.sh").read_text()
    assert "image: trainmeet-id:${ID_TAG" in compose
    assert "id-db:/var/lib/postgresql/data" in compose
    assert "./id-vault:/opt/keycloak/vault:ro" in compose
    assert "KC_HOSTNAME: https://${ID_DOMAIN" in compose
    assert "{$ID_DOMAIN}" in caddyfile
    assert "reverse_proxy id:8080" in caddyfile
    # Keycloak's admin pages are not reachable from outside.
    assert "respond /admin* 404" in caddyfile
    assert "respond /realms/master* 404" in caddyfile
    assert "ID_TAG=%s\\nID_DOMAIN=%s" in up
    database = compose.split("  id-db:")[1].split("\n  id:")[0]
    assert "ports:" not in database
    # The mail key is never written in the compose file or .env, only in the vault.
    assert "TEM_SECRET_KEY" not in compose


def test_id_secrets_survive_secret_manager_and_stay_private(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    made = testmiljo.generate_id_secrets()
    assert testmiljo.IdSecrets.from_json(made.to_json()) == made
    assert len({made.db_password, made.admin_password, made.catalog_secret}) == 3
    monkeypatch.setenv("TESTMILJO_SSH_DIR", str(tmp_path))
    path = testmiljo.write_private("testmiljo_id.env", made.env_file())
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.read_text().splitlines() == [
        f"ID_DB_PASSWORD={made.db_password}",
        f"ID_ADMIN_PASSWORD={made.admin_password}",
        f"ID_CATALOG_SECRET={made.catalog_secret}",
    ]


def test_the_id_api_has_a_secret_of_its_own(tmp_path: Path) -> None:
    """#67: a new secret beside the one from #66, so that one is never rewritten."""
    made = testmiljo.generate_id_api_secrets()
    assert testmiljo.IdApiSecrets.from_json(made.to_json()) == made
    assert len(made.app_secret) == 64
    assert made.env_file() == f"ID_APP_SECRET={made.app_secret}\n"
    assert testmiljo.ID_API_SECRET_NAME != testmiljo.ID_SECRET_NAME


def test_keycloak_is_given_every_address_the_realm_file_names() -> None:
    """Keycloak reads the realm file the first time and leaves an unset ${NAME} as it is, which
    makes the client's address invalid and Keycloak does not start (#78, ID_TKL_URL). The test
    environment and the check "ID:s bild" give every one."""
    realm = (ROOT / "id" / "realm" / "trainmeet.json").read_text()
    named = set(re.findall(r"\$\{(ID_[A-Z_]+)\}", realm))
    compose = (ROOT / "deploy" / "testmiljo" / "compose.yaml").read_text()
    keycloak = compose.split("\n  id:\n")[1].split("\n  id-api:\n")[0]
    workflow = (ROOT / ".github" / "workflows" / "tester.yml").read_text()
    job = workflow.split("\n  id:\n")[1]
    check = job.split("- name: Starta ID med databas")[1].split("trainmeet-id:prov\n")[0]
    assert named, "the realm names no addresses?"
    for name in sorted(named):
        assert f"{name}:" in keycloak, f"{name} is not given to Keycloak in the test environment"
        assert f"-e {name}=" in check, f"{name} is not given to Keycloak in the check"


def test_the_hub_has_a_secret_of_its_own_in_id() -> None:
    """#78: the test hub's client in ID gets a secret beside the others, never one of theirs."""
    made = testmiljo.generate_id_hub_secrets()
    assert testmiljo.IdHubSecrets.from_json(made.to_json()) == made
    assert len(made.hub_secret) == 64
    assert made.env_file() == f"ID_HUB_SECRET={made.hub_secret}\n"
    names = {testmiljo.ID_SECRET_NAME, testmiljo.ID_API_SECRET_NAME, testmiljo.ID_HUB_SECRET_NAME}
    assert len(names) == 3
    compose = (ROOT / "deploy" / "testmiljo" / "compose.yaml").read_text()
    assert "TRAINMEET_ID_SECRET: ${ID_HUB_SECRET}" in compose
    assert "ID_HUB_SECRET: ${ID_HUB_SECRET:?ID_HUB_SECRET saknas}" in compose


def test_cad_secrets_survive_secret_manager_and_stay_private(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#89: CAD's database password and backup key, as Catalog's, and its client's secret in ID,
    a secret of its own as the hub's. cad.env has all three, and id.env the client's."""
    made = testmiljo.generate_cad_secrets()
    assert testmiljo.CadSecrets.from_json(made.to_json()) == made
    assert len(made.backup_key) == 64 and made.db_password != made.backup_key
    client = testmiljo.generate_id_cad_secrets()
    assert testmiljo.IdCadSecrets.from_json(client.to_json()) == client
    assert len(client.cad_secret) == 64
    assert client.env_file() == f"ID_CAD_SECRET={client.cad_secret}\n"
    monkeypatch.setenv("TESTMILJO_SSH_DIR", str(tmp_path))
    path = testmiljo.write_cad_env(made, client)
    assert path.name == "testmiljo_cad.env"
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.read_text() == (
        f"CAD_DB_PASSWORD={made.db_password}\nCAD_BACKUP_KEY={made.backup_key}\n"
        f"ID_CAD_SECRET={client.cad_secret}\n"
    )
    names = {
        testmiljo.CATALOG_SECRET_NAME,
        testmiljo.ID_SECRET_NAME,
        testmiljo.ID_API_SECRET_NAME,
        testmiljo.ID_HUB_SECRET_NAME,
        testmiljo.CAD_SECRET_NAME,
        testmiljo.ID_CAD_SECRET_NAME,
    }
    assert len(names) == 6
    # Keycloak's client cad and CAD read the same variable from .env.
    compose = (ROOT / "deploy" / "testmiljo" / "compose.yaml").read_text()
    assert "ID_CAD_SECRET: ${ID_CAD_SECRET:-}" in compose.split("\n  id:\n")[1]
    assert "CAD_ID_SECRET: ${ID_CAD_SECRET:-}" in compose.split("\n  cad:\n")[1]


def test_a_test_environment_from_before_cad_gets_cads_secrets_and_keeps_its_own() -> None:
    """The secrets stored before #89 are read as they are; CAD's two are made once, saved and
    read back at the next deploy."""
    stored: dict[str, str] = {
        testmiljo.CATALOG_SECRET_NAME: testmiljo.generate_catalog_secrets().to_json(),
        testmiljo.ID_HUB_SECRET_NAME: testmiljo.generate_id_hub_secrets().to_json(),
    }
    before = dict(stored)

    def list_secrets(name: str, **_: object) -> SimpleNamespace:
        found = [SimpleNamespace(id=name, name=name, version_count=1)] if name in stored else []
        return SimpleNamespace(secrets=found)

    def create_secret(name: str, **_: object) -> SimpleNamespace:
        return SimpleNamespace(id=name, name=name, version_count=0)

    def create_secret_version(secret_id: str, data: str) -> None:
        stored[secret_id] = base64.b64decode(data).decode()

    def access_secret_version(secret_id: str, **_: object) -> SimpleNamespace:
        return SimpleNamespace(data=base64.b64encode(stored[secret_id].encode()).decode())

    api = Mock()
    api.list_secrets.side_effect = list_secrets
    api.create_secret.side_effect = create_secret
    api.create_secret_version.side_effect = create_secret_version
    api.access_secret_version.side_effect = access_secret_version

    cad = testmiljo.ensure_cad_secrets(api, "proj-1")
    client = testmiljo.ensure_id_cad_secrets(api, "proj-1")
    assert testmiljo.ensure_cad_secrets(api, "proj-1") == cad
    assert testmiljo.ensure_id_cad_secrets(api, "proj-1") == client
    assert api.create_secret_version.call_count == 2
    assert testmiljo.ensure_catalog_secrets(api, "proj-1") == testmiljo.CatalogSecrets.from_json(
        before[testmiljo.CATALOG_SECRET_NAME]
    )
    assert testmiljo.ensure_id_hub_secrets(api, "proj-1") == testmiljo.IdHubSecrets.from_json(
        before[testmiljo.ID_HUB_SECRET_NAME]
    )
    assert {k: v for k, v in stored.items() if k in before} == before


def test_the_deploy_gives_cads_client_secret_to_id_and_to_cad() -> None:
    """main() puts ID_CAD_SECRET in id.env, for Keycloak's client cad, and in cad.env."""
    source = (ROOT / "deploy" / "testmiljo.py").read_text()
    main = source.split("def main(")[1]
    assert "id_cad_secrets = ensure_id_cad_secrets(secrets, project_id)" in main
    assert "+ id_cad_secrets.env_file()" in main.split('output("id_env"')[0]
    assert 'output("cad_env", str(write_cad_env(cad_secrets, id_cad_secrets, cad_photos)))' in main


def test_every_check_stops_its_background_programs() -> None:
    """Programs started through uv hold uv's cache locked; setup-uv's own cleanup after the
    job then waits for the lock and fails the check. It happened on main 15 November (ID),
    and again 19 November in TKL and Catalog when uv.lock changed (#86)."""
    workflow = (ROOT / ".github" / "workflows" / "tester.yml").read_text()
    jobs = re.split(r"\n  ([a-z]+):\n", workflow.split("\njobs:\n", 1)[1])
    checked = []
    for name, job in zip(jobs[1::2], jobs[2::2], strict=True):
        started = re.findall(
            r"nohup uvx? (?:--from \S+ )?(?:run )?python (\S+)|nohup uv run (uvicorn \S+)"
            r"|uv run python -m (\S+)(?:[^\n]*\\\n)*[^\n]*&[ \t]*$",
            job,
            flags=re.MULTILINE,
        )
        if not started:
            continue
        checked.append(name)
        assert "- name: Stäng av provets program" in job, name
        stop = job.split("- name: Stäng av provets program")[1]
        assert "if: always()" in stop, name
        stopped = re.findall(r'pkill -f "([^"]+)"', stop)
        for found in started:
            program = next(part for part in found if part)
            assert any(pattern in program for pattern in stopped), (name, program)
    assert {"tkl", "catalog", "id"} <= set(checked), checked


def test_ids_api_runs_beside_keycloak_at_the_same_address() -> None:
    """#67: Keycloak answers /realms/ and /resources/, ID's API and web app the rest."""
    folder = ROOT / "deploy" / "testmiljo"
    compose = (folder / "compose.yaml").read_text()
    caddyfile = (folder / "Caddyfile").read_text()
    up = (folder / "up.sh").read_text()
    assert "image: trainmeet-idapi:${ID_TAG}" in compose
    assert (
        "ID_API_DATABASE_URL: postgresql://keycloak:${ID_DB_PASSWORD}@id-db:5432/idapi" in compose
    )
    assert "ID_API_SECRET: ${ID_APP_SECRET}" in compose
    assert "ID_APP_SECRET: ${ID_APP_SECRET:?" in compose  # Keycloak's client "id" (update 3)
    assert "@keycloak path /realms/* /resources/*" in caddyfile
    assert "reverse_proxy id-api:8080" in caddyfile
    assert "createdb -U keycloak idapi" in up
    assert "id-api:8083" in up
    service = compose.split("  id-api:")[1].split("\n  caddy:")[0]
    assert '"127.0.0.1:8083:8080"' in service  # only on the server itself


# --- Catalogs bilder (#51, C35, CAT-130) -------------------------------------------------


def _secrets() -> Mock:
    stored: dict[str, str] = {}

    def list_secrets(name: str, **_: object) -> SimpleNamespace:
        found = [SimpleNamespace(id="s1", name=name, version_count=1)] if stored else []
        return SimpleNamespace(secrets=found)

    api = Mock()
    api.list_secrets.side_effect = list_secrets
    api.create_secret.return_value = SimpleNamespace(id="s1", name="x", version_count=0)
    api.create_secret_version.side_effect = lambda secret_id, data: stored.update(data=data)
    api.access_secret_version.side_effect = lambda **_: SimpleNamespace(data=stored["data"])
    return api


def test_the_pictures_get_a_key_that_only_reaches_object_storage_in_the_project() -> None:
    iam = Mock()
    iam.list_applications_all.return_value = []
    iam.create_application.return_value = SimpleNamespace(id="app", name=testmiljo.PICTURES_NAME)
    iam.list_policies_all.return_value = []
    iam.create_api_key.return_value = SimpleNamespace(access_key="SCWNYCKEL", secret_key="hemlig")
    secrets = _secrets()
    key = testmiljo.ensure_picture_key(iam, secrets, "proj-1", "org-1")
    assert (key.access_key, key.secret_key) == ("SCWNYCKEL", "hemlig")
    rules = iam.create_policy.call_args.kwargs["rules"]
    assert [(r.permission_set_names, r.project_ids) for r in rules] == [
        (["ObjectStorageFullAccess"], ["proj-1"])
    ]
    assert "hemlig" not in repr(key)
    assert key.key_file() == "SCWNYCKEL\nhemlig\n"
    # The second deploy reads the key back, makes nothing new and does not ask IAM at all.
    assert testmiljo.ensure_picture_key(iam, secrets, "proj-1", "org-1") == key
    assert iam.list_applications_all.call_count == 1
    assert iam.list_policies_all.call_count == 1
    assert iam.create_application.call_count == 1
    assert iam.create_policy.call_count == 1
    assert iam.create_api_key.call_count == 1


def _refused(status: int) -> ScalewayException:
    """Scaleway's answer when the key lacks the right."""
    response = Response()
    response.status_code = status
    return ScalewayException(response)


def test_a_stored_pictures_key_needs_no_iam_rights() -> None:
    """Once the key is in Secret Manager, the right to make IAM applications can be taken
    from the deploy's key again: IAM is never asked."""
    secrets = _secrets()
    stored = testmiljo.PictureKey(access_key="SCWNYCKEL", secret_key="hemlig")
    testmiljo.ensure_secret(secrets, "proj-1", testmiljo.PICTURES_SECRET_NAME, "", stored.to_json)
    iam = Mock()
    iam.list_applications_all.side_effect = _refused(403)

    def send(method: str, url: str, given: testmiljo.PictureKey) -> int:
        assert given == stored
        return 200

    found = testmiljo.ensure_pictures(iam, secrets, "proj-1", "org-1", send)
    assert found == (testmiljo.bucket_name("proj-1"), stored)
    assert iam.method_calls == []


def test_without_iam_rights_the_notice_says_which_right_and_for_how_long(
    capsys: pytest.CaptureFixture[str],
) -> None:
    iam = Mock()
    iam.list_applications_all.side_effect = _refused(403)
    assert testmiljo.ensure_pictures(iam, _secrets(), "proj-1", "org-1") is None
    said = capsys.readouterr().out
    assert "ligger på serverns disk" in said and "HTTP 403" in said
    assert "IAMManager i organisationen för en körning" in said


def test_the_bucket_is_made_once_and_a_new_policy_is_waited_for() -> None:
    key = testmiljo.PictureKey(access_key="a", secret_key="b")
    answers = iter([403, 404, 200])
    calls: list[tuple[str, str]] = []

    def send(method: str, url: str, given: testmiljo.PictureKey) -> int:
        calls.append((method, url))
        return next(answers)

    waited: list[float] = []
    testmiljo.ensure_bucket(key, "trainmeet-test-bilder-abc", send, waited.append)
    assert calls == [
        ("HEAD", "https://s3.nl-ams.scw.cloud/trainmeet-test-bilder-abc"),
        ("HEAD", "https://s3.nl-ams.scw.cloud/trainmeet-test-bilder-abc"),
        ("PUT", "https://s3.nl-ams.scw.cloud/trainmeet-test-bilder-abc"),
    ]
    assert len(waited) == 1
    assert testmiljo.bucket_name("ABCD1234-ef56-7890") == "trainmeet-test-bilder-abcd1234"


def test_without_the_bucket_the_pictures_lie_on_disk_and_the_deploy_goes_on(
    capsys: pytest.CaptureFixture[str],
) -> None:
    iam = Mock()
    iam.list_applications_all.return_value = [
        SimpleNamespace(id="app", name=testmiljo.PICTURES_NAME)
    ]
    iam.list_policies_all.return_value = [SimpleNamespace(name=testmiljo.PICTURES_NAME)]
    iam.create_api_key.return_value = SimpleNamespace(access_key="SCWNYCKEL", secret_key="hemlig")

    def broken(method: str, url: str, given: testmiljo.PictureKey) -> int:
        return 500

    assert testmiljo.ensure_pictures(iam, _secrets(), "proj-1", "org-1", broken) is None
    said = capsys.readouterr().out
    assert "ligger på serverns disk" in said and "HTTP 500" in said
    assert "hemlig" not in said


def test_catalog_reads_the_pictures_key_from_its_vault_and_keeps_disk_pictures() -> None:
    compose = (ROOT / "deploy" / "testmiljo" / "compose.yaml").read_text()
    catalog = compose.split("\n  catalog:\n", 1)[1].split("\n  # ", 1)[0]
    assert 'user: "${HOST_UID}:0"' in catalog
    assert "CATALOG_PICTURES_S3_KEY_FILE: ${CATALOG_PICTURES_S3_BUCKET:+/vault/" in catalog
    assert "- ./catalog-vault:/vault:ro" in catalog
    assert "- ./catalog-pictures:/pictures" in catalog
    up = (ROOT / "deploy" / "testmiljo" / "up.sh").read_text()
    assert "mkdir -p catalog-pictures" in up
    workflow = (ROOT / ".github" / "workflows" / "tester.yml").read_text()
    assert 'catalog-vault/trainmeet_pictures-key\' < "$PICTURES_KEY"' in workflow


def test_every_file_the_deploy_sends_reaches_the_deploy_step() -> None:
    """Each file the deploy step sends to the server (`< "$NAME"`) is in the step's own env or
    was put in GITHUB_ENV by an earlier step. The pictures' key was neither, so the key never
    reached catalog-vault, and Catalog stopped once the bucket existed (22 november)."""
    workflow = (ROOT / ".github" / "workflows" / "tester.yml").read_text()
    step = workflow.split("      - name: Lägg ut hubben, Catalog och ID\n", 1)[1]
    step = step.split("\n      - name: ", 1)[0]
    env, run = step.split("        run: |\n", 1)
    own = set(re.findall(r"^          ([A-Z_]+): ", env, re.M))
    exported = set(re.findall(r'echo "([A-Z_]+)=\$', workflow))
    sent = set(re.findall(r'< "\$([A-Z_]+)"', run))
    assert {"CATALOG_ENV", "ID_ENV", "CAD_ENV", "PICTURES_KEY"} <= sent
    assert sent <= own | exported, sorted(sent - own - exported)


# --- CAD:s modulfoton (#89 del c1, CAD-19) ---------------------------------------------------


def test_cads_photos_get_their_own_bucket_and_key_never_catalogs() -> None:
    iam = Mock()
    iam.list_applications_all.return_value = []
    iam.create_application.return_value = SimpleNamespace(id="app", name=testmiljo.CAD_PHOTOS_NAME)
    iam.list_policies_all.return_value = []
    iam.create_api_key.return_value = SimpleNamespace(access_key="SCWFOTO", secret_key="hemligt")
    calls: list[tuple[str, str]] = []

    def send(method: str, url: str, given: testmiljo.PictureKey) -> int:
        calls.append((method, url))
        return 404 if method == "HEAD" else 200

    found = testmiljo.ensure_cad_photos(iam, _secrets(), "ABCD1234-ef56", "org-1", send)
    assert found is not None
    bucket, key = found
    assert bucket == "trainmeet-test-cad-foton-abcd1234" != testmiljo.bucket_name("ABCD1234-ef56")
    assert (key.access_key, key.secret_key) == ("SCWFOTO", "hemligt")
    assert calls[-1] == ("PUT", f"https://s3.nl-ams.scw.cloud/{bucket}")
    assert iam.create_application.call_args.kwargs["name"] == testmiljo.CAD_PHOTOS_NAME
    assert testmiljo.CAD_PHOTOS_NAME != testmiljo.PICTURES_NAME
    assert testmiljo.CAD_PHOTOS_SECRET_NAME != testmiljo.PICTURES_SECRET_NAME
    rules = iam.create_policy.call_args.kwargs["rules"]
    assert [(r.permission_set_names, r.project_ids) for r in rules] == [
        (["ObjectStorageFullAccess"], ["ABCD1234-ef56"])
    ]


def test_cads_photos_key_goes_to_its_vault_never_to_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TESTMILJO_SSH_DIR", str(tmp_path))
    made = testmiljo.generate_cad_secrets()
    client = testmiljo.generate_id_cad_secrets()
    key = testmiljo.PictureKey(access_key="SCWFOTO", secret_key="hemligt")
    text = testmiljo.write_cad_env(made, client, ("cad-hink", key)).read_text()
    assert text.endswith(
        "CAD_PHOTOS_S3_BUCKET=cad-hink\n"
        "CAD_PHOTOS_S3_ACCESS_KEY=SCWFOTO\nCAD_PHOTOS_S3_SECRET_KEY=hemligt\n"
    )
    folder = ROOT / "deploy" / "testmiljo"
    up = (folder / "up.sh").read_text()
    assert "mkdir -p cad-vault cad-photos" in up
    assert "} > cad-vault/trainmeet_photos-key" in up
    env = up.split("} > .env")[0].rsplit("\n{\n", 1)[1]
    assert "cat catalog.env id.env\n" in env
    assert "grep -v -e '^CAD_PHOTOS_S3_ACCESS_KEY=' -e '^CAD_PHOTOS_S3_SECRET_KEY=' cad.env" in env
    compose = (folder / "compose.yaml").read_text()
    cad = compose.split("\n  cad:\n", 1)[1].split("\n  # ", 1)[0]
    assert 'user: "${HOST_UID:?HOST_UID saknas}:0"' in cad
    assert "CAD_PHOTOS_S3_KEY_FILE: ${CAD_PHOTOS_S3_BUCKET:+/vault/trainmeet_photos-key}" in cad
    assert "CAD_PHOTOS_DIR: /photos" in cad
    assert "- ./cad-vault:/vault:ro" in cad
    assert "- ./cad-photos:/photos" in cad
    assert "catalog-vault" not in cad and "catalog-pictures" not in cad
