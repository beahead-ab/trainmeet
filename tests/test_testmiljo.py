"""The test environment's setup (deploy/testmiljo.py), the parts that run without Scaleway."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

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
    assert parsed["ssh_genkeytypes"] == []


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


def test_usage_without_command() -> None:
    assert testmiljo.main(["testmiljo.py"]) == 2
