"""The test environment's setup (deploy/testmiljo.py), the parts that run without Scaleway."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest
from scaleway.iam.v1alpha1.types import LocalityType, Quotum, QuotumLimit
from scaleway.instance.v1.custom_api import InstanceUtilsV1API
from scaleway.instance.v1.types import Server, ServerAction, ServerState

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
    assert "HUB_TAG=%s\\nHUB_DOMAIN=%s" in up
    assert "127.0.0.1:8080:8080" in compose


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
