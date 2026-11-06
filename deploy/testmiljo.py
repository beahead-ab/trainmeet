"""Sätter upp testmiljön för TrainMeet Hub hos Scaleway i Amsterdam (zon nl-ams-1).

Körs av jobbet "Testmiljön" i .github/workflows/tester.yml vid varje ändring på main.
Allt skapas första gången och återanvänds sedan, så samma körning fungerar första och
hundrade gången:

- SSH-nycklarna (en för utläggningen och värdens egen nyckel) skapas här och sparas i
  Scaleways Secret Manager. De skrivs aldrig ut och ligger aldrig i repot.
- En säkerhetsgrupp som bara släpper in SSH, HTTP och HTTPS.
- En fast IPv4-adress, så att DNS-raden för test.hub.trainmeet.app står still.
- En server (DEV1-S med Ubuntu 24.04) med Docker, som cloud-init sätter upp vid första start.

    python deploy/testmiljo.py ensure

Miljön (secrets i GitHub):
    SCW_ACCESS_KEY, SCW_SECRET_KEY, SCW_DEFAULT_PROJECT_ID, SCW_DEFAULT_ORGANIZATION_ID
Valfritt:
    TESTMILJO_TYPE      servertyp, förval DEV1-S
    TESTMILJO_SSH_DIR   var nyckelfilerna skrivs för jobbets ssh, förval ~/.ssh
Resultatet (GITHUB_OUTPUT): ip, user, key_file, known_hosts, created.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, NoReturn, cast

from scaleway import Client
from scaleway.iam.v1alpha1 import IamV1Alpha1API
from scaleway.iam.v1alpha1.types import Quotum
from scaleway.instance.v1.custom_api import InstanceUtilsV1API
from scaleway.instance.v1.types import (
    Ip,
    IpType,
    SecurityGroupPolicy,
    SecurityGroupRuleAction,
    SecurityGroupRuleDirection,
    SecurityGroupRuleProtocol,
    Server,
    ServerAction,
    ServerState,
    SetSecurityGroupRulesRequestRule,
    VolumeServerTemplate,
    VolumeVolumeType,
)
from scaleway.marketplace.v2 import MarketplaceV2API
from scaleway.marketplace.v2.types import LocalImageType
from scaleway.secret.v1beta1 import SecretV1Beta1API
from scaleway_core.api import ScalewayException

ZONE = "nl-ams-1"
REGION = "nl-ams"
NAME = "trainmeet-testhub"
TAG = "trainmeet-testmiljo"
SECRET_NAME = "trainmeet-testmiljo-ssh"
DEFAULT_TYPE = "DEV1-S"
IMAGE_LABEL = "ubuntu_noble"
DEPLOY_USER = "deploy"
SBS_SIZE = 20 * 10**9
HUB_UID = 10001  # the user the hub runs as inside its image (hub/Dockerfile)
START_TIMEOUT = 300

# (protocol, port) open to everyone. The rest of the inbound traffic is dropped.
OPEN_PORTS: list[tuple[SecurityGroupRuleProtocol, int | None]] = [
    (SecurityGroupRuleProtocol.TCP, 22),
    (SecurityGroupRuleProtocol.TCP, 80),
    (SecurityGroupRuleProtocol.TCP, 443),
    (SecurityGroupRuleProtocol.UDP, 443),
    (SecurityGroupRuleProtocol.ICMP, None),
]


@dataclass(frozen=True)
class Keys:
    deploy_private: str
    deploy_public: str
    host_private: str
    host_public: str

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, text: str) -> Keys:
        data = json.loads(text)
        return cls(**{field: str(data[field]) for field in cls.__dataclass_fields__})


def fail(message: str) -> NoReturn:
    print(f"::error::{message}", file=sys.stderr)
    sys.exit(1)


def env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        fail(f"Saknar {name}. Lägg in den som secret i GitHub (Settings → Secrets → Actions).")
    return value


def output(key: str, value: str) -> None:
    print(f"{key}={value}")
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as file:
            file.write(f"{key}={value}\n")


# --- Nycklarna -------------------------------------------------------------------------


def generate_keys() -> Keys:
    """Two ed25519 key pairs: one the deploy logs in with, one the server identifies with."""
    with tempfile.TemporaryDirectory() as folder:
        pairs: dict[str, tuple[str, str]] = {}
        for role in ("deploy", "host"):
            path = Path(folder) / role
            command = ["ssh-keygen", "-q", "-t", "ed25519", "-N", ""]
            command += ["-C", f"trainmeet-testmiljo-{role}", "-f", str(path)]
            subprocess.run(command, check=True)
            pairs[role] = (path.read_text(), path.with_suffix(".pub").read_text().strip())
    return Keys(
        deploy_private=pairs["deploy"][0],
        deploy_public=pairs["deploy"][1],
        host_private=pairs["host"][0],
        host_public=pairs["host"][1],
    )


def cloud_init(keys: Keys) -> str:
    """The first-boot setup. JSON is valid YAML, so no YAML library is needed."""
    config: dict[str, Any] = {
        "package_update": True,
        "packages": ["docker.io", "docker-compose-v2", "curl"],
        "ssh_pwauth": False,
        "ssh_deletekeys": True,
        "ssh_genkeytypes": [],
        "ssh_keys": {"ed25519_private": keys.host_private, "ed25519_public": keys.host_public},
        "users": [
            "default",
            {
                "name": DEPLOY_USER,
                "shell": "/bin/bash",
                "lock_passwd": True,
                "ssh_authorized_keys": [keys.deploy_public],
            },
        ],
        "write_files": [
            {
                "path": "/etc/ssh/sshd_config.d/10-trainmeet.conf",
                "content": "PasswordAuthentication no\nKbdInteractiveAuthentication no\n",
            }
        ],
        "runcmd": [
            ["usermod", "-aG", "docker", DEPLOY_USER],
            ["systemctl", "enable", "--now", "docker"],
            ["mkdir", "-p", "/srv/trainmeet/hub-data"],
            ["chown", f"{DEPLOY_USER}:{DEPLOY_USER}", "/srv/trainmeet"],
            ["chown", f"{HUB_UID}:{HUB_UID}", "/srv/trainmeet/hub-data"],
        ],
    }
    return "#cloud-config\n" + json.dumps(config, indent=2) + "\n"


def known_hosts_line(address: str, host_public: str) -> str:
    key_type, key = host_public.split()[:2]
    return f"{address} {key_type} {key}\n"


def ensure_keys(secrets: SecretV1Beta1API, project_id: str) -> Keys:
    existing = secrets.list_secrets(
        project_id=project_id, name=SECRET_NAME, scheduled_for_deletion=False
    ).secrets
    secret = next((s for s in existing if s.name == SECRET_NAME), None)
    if secret is not None and secret.version_count > 0:
        version = secrets.access_secret_version(secret_id=secret.id, revision="latest")
        return Keys.from_json(base64.b64decode(version.data).decode())

    if secret is None:
        secret = secrets.create_secret(
            name=SECRET_NAME,
            protected=False,
            project_id=project_id,
            tags=[TAG],
            description="SSH-nycklarna för testmiljön. Skapas av deploy/testmiljo.py.",
        )
    keys = generate_keys()
    secrets.create_secret_version(
        secret_id=secret.id, data=base64.b64encode(keys.to_json().encode()).decode()
    )
    print("Nya SSH-nycklar skapade och sparade i Secret Manager.")
    return keys


# --- Nätet -----------------------------------------------------------------------------


def ensure_security_group(instance: InstanceUtilsV1API, project_id: str) -> str:
    groups = instance.list_security_groups(zone=ZONE, project=project_id, name=NAME)
    group = next((g for g in groups.security_groups if g.name == NAME), None)
    if group is None:
        group = instance.create_security_group(
            zone=ZONE,
            project=project_id,
            name=NAME,
            description="Testmiljön för TrainMeet Hub: SSH, HTTP och HTTPS in.",
            stateful=True,
            inbound_default_policy=SecurityGroupPolicy.DROP,
            outbound_default_policy=SecurityGroupPolicy.ACCEPT,
            enable_default_security=True,
            tags=[TAG],
        ).security_group
        print("Säkerhetsgruppen skapad.")
    if group is None:
        fail("Scaleway gav ingen säkerhetsgrupp tillbaka.")

    rules: list[SetSecurityGroupRulesRequestRule] = []
    for ip_range in ("0.0.0.0/0", "::/0"):
        for protocol, port in OPEN_PORTS:
            rules.append(
                SetSecurityGroupRulesRequestRule(
                    action=SecurityGroupRuleAction.ACCEPT,
                    # Instance API v1 expects uppercase, but the Python SDK enum uses lowercase.
                    protocol=cast(SecurityGroupRuleProtocol, protocol.value.upper()),
                    direction=SecurityGroupRuleDirection.INBOUND,
                    ip_range=ip_range,
                    position=len(rules) + 1,
                    dest_port_from=port,
                    dest_port_to=None,
                    editable=True,
                )
            )
    instance.set_security_group_rules(zone=ZONE, security_group_id=group.id, rules=rules)
    return group.id


def ensure_ip(instance: InstanceUtilsV1API, project_id: str) -> Ip:
    ips = instance.list_ips(zone=ZONE, project=project_id, tags=[TAG]).ips
    if ips:
        return ips[0]
    ip = instance.create_ip(zone=ZONE, project=project_id, tags=[TAG], type_=IpType.ROUTED_IPV4).ip
    if ip is None:
        fail("Scaleway gav ingen IP-adress tillbaka.")
    print(f"Fast IPv4-adress skapad: {ip.address}")
    return ip


# --- Servern ---------------------------------------------------------------------------


def root_volume(
    instance: InstanceUtilsV1API, marketplace: MarketplaceV2API, commercial_type: str
) -> tuple[str, dict[str, VolumeServerTemplate]]:
    """Ubuntu 24.04 for the server type, on local storage if the type has it, else block."""
    server_type = None
    page = 1
    while server_type is None:
        response = instance.list_servers_types(zone=ZONE, per_page=100, page=page)
        server_type = response.servers.get(commercial_type)
        if server_type is not None or not response.servers or page * 100 >= response.total_count:
            break
        page += 1
    if server_type is None:
        fail(f"Servertypen {commercial_type} finns inte i {ZONE}. Välj en annan i TESTMILJO_TYPE.")

    local_max = server_type.volumes_constraint.max_size if server_type.volumes_constraint else 0
    wanted = LocalImageType.INSTANCE_LOCAL if local_max else LocalImageType.INSTANCE_SBS
    images = marketplace.list_local_images_all(zone=ZONE, image_label=IMAGE_LABEL, type_=wanted)
    image = next(
        (
            i
            for i in images
            if commercial_type in i.compatible_commercial_types and i.arch == "x86_64"
        ),
        None,
    )
    if image is None:
        fail(f"Hittar ingen {IMAGE_LABEL}-bild för {commercial_type} i {ZONE}.")

    if local_max:
        volume = VolumeServerTemplate(volume_type=VolumeVolumeType.L_SSD, size=local_max)
    else:
        volume = VolumeServerTemplate(volume_type=VolumeVolumeType.SBS_VOLUME, size=SBS_SIZE)
    return image.id, {"0": volume}


def wait_until_running(instance: InstanceUtilsV1API, server_id: str) -> Server:
    deadline = time.monotonic() + START_TIMEOUT
    while True:
        server = instance.get_server(zone=ZONE, server_id=server_id).server
        if server is not None and server.state == ServerState.RUNNING:
            return server
        if time.monotonic() > deadline:
            state = server.state if server else "okänt"
            fail(f"Servern startade inte inom {START_TIMEOUT} s (läge: {state}).")
        time.sleep(5)


def ensure_server(
    instance: InstanceUtilsV1API,
    marketplace: MarketplaceV2API,
    project_id: str,
    security_group_id: str,
    ip: Ip,
    keys: Keys,
    commercial_type: str,
) -> tuple[Server, bool]:
    servers = instance.list_servers(zone=ZONE, project=project_id, name=NAME).servers
    server = next((s for s in servers if s.name == NAME), None)
    created = False

    if server is None:
        image_id, volumes = root_volume(instance, marketplace, commercial_type)
        server = instance._create_server(
            zone=ZONE,
            commercial_type=commercial_type,
            name=NAME,
            project=project_id,
            image=image_id,
            volumes=volumes,
            dynamic_ip_required=False,
            routed_ip_enabled=True,
            public_ips=[ip.id],
            security_group=security_group_id,
            protected=False,
            tags=[TAG],
        ).server
        if server is None:
            fail("Scaleway gav ingen server tillbaka.")
        instance.set_server_user_data(
            server_id=server.id, key="cloud-init", content=cloud_init(keys).encode(), zone=ZONE
        )
        created = True
        print(f"Servern {NAME} ({commercial_type}) skapad.")
    elif ip.server is None or ip.server.id != server.id:
        instance.update_ip(zone=ZONE, ip=ip.id, server=server.id)
        print("Den fasta adressen kopplad till servern.")

    if server.state != ServerState.RUNNING:
        if server.state in (ServerState.STOPPED, ServerState.STOPPED_IN_PLACE):
            instance.server_action(zone=ZONE, server_id=server.id, action=ServerAction.POWERON)
            print("Servern startas.")
        server = wait_until_running(instance, server.id)
    return server, created


def write_ssh_files(keys: Keys, address: str) -> tuple[Path, Path]:
    folder = Path(os.environ.get("TESTMILJO_SSH_DIR") or Path.home() / ".ssh")
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    key_file = folder / "testmiljo"
    key_file.touch(mode=0o600, exist_ok=True)
    key_file.write_text(keys.deploy_private)
    key_file.chmod(0o600)
    known_hosts = folder / "testmiljo_known_hosts"
    known_hosts.write_text(known_hosts_line(address, keys.host_public))
    return key_file, known_hosts


def explain(status: int | None, body: str, commercial_type: str) -> str:
    """Scaleway's answer, with what to do about it when it is the account and not the code."""
    if "quotas_exceeded" in body:
        return (
            f"Scaleway-kontot får inte skapa en server av typen {commercial_type}: kvoten är slut. "
            "Ett nytt konto har kvot först när betalsättet är verifierat, och fler typer när "
            "identiteten är verifierad. Se Organization → Quotas i Scaleways konsol, eller välj "
            "en annan typ i variabeln TESTMILJO_TYPE. "
            f"(Scaleway svarade {status}: {body})"
        )
    if status in (401, 403):
        return (
            "Scaleway-nyckeln saknar behörighet. Applikationen behöver InstancesFullAccess och "
            f"SecretManagerFullAccess i projektet. (Scaleway svarade {status}: {body})"
        )
    return f"Scaleway svarade {status}: {body}"


QUOTA_PREFIX = "cp_servers_type_"


def server_type_from_quota(name: str) -> str:
    """cp_servers_type_PLAY2_PICO -> PLAY2-PICO"""
    return name.removeprefix(QUOTA_PREFIX).replace("_", "-")


def quota_limit(quotum: Quotum) -> int | None:
    """The quota for ZONE, or None for unlimited."""
    if quotum.unlimited:
        return None
    limits = [lim for lim in quotum.limits if lim.zone in (None, ZONE) or lim.global_]
    if any(lim.unlimited for lim in limits):
        return None
    values = [lim.limit or 0 for lim in limits] or [quotum.limit or 0]
    return max(values)


def quota_report(quota: list[Quotum]) -> str:
    """Which server types the account may create, cheapest kinds first as Scaleway lists them."""
    allowed: list[str] = []
    for quotum in quota:
        if not quotum.name.startswith(QUOTA_PREFIX):
            continue
        limit = quota_limit(quotum)
        if limit is None or limit > 0:
            count = "obegränsat" if limit is None else str(limit)
            allowed.append(f"{server_type_from_quota(quotum.name)} ({count})")
    if not allowed:
        return "Kontot får inte skapa någon servertyp alls just nu."
    return "Kontot får skapa: " + ", ".join(sorted(allowed)) + "."


def read_quota(client: Client, organization_id: str) -> str:
    try:
        quota = IamV1Alpha1API(client).list_quota_all(organization_id=organization_id)
    except ScalewayException as error:
        return (
            f"Kvoterna gick inte att läsa (Scaleway svarade {error.status_code}). "
            "Ge applikationen behörigheten IAMReadOnly i organisationen för att se dem här."
        )
    return quota_report(quota)


def main(argv: list[str]) -> int:
    if argv[1:] != ["ensure"]:
        print(__doc__)
        return 2

    project_id = env("SCW_DEFAULT_PROJECT_ID")
    client = Client(
        access_key=env("SCW_ACCESS_KEY"),
        secret_key=env("SCW_SECRET_KEY"),
        default_project_id=project_id,
        default_organization_id=env("SCW_DEFAULT_ORGANIZATION_ID"),
        default_region=REGION,
        default_zone=ZONE,
    )
    instance = InstanceUtilsV1API(client)
    marketplace = MarketplaceV2API(client)
    secrets = SecretV1Beta1API(client)
    commercial_type = os.environ.get("TESTMILJO_TYPE", "").strip() or DEFAULT_TYPE

    try:
        keys = ensure_keys(secrets, project_id)
        security_group_id = ensure_security_group(instance, project_id)
        ip = ensure_ip(instance, project_id)
        _, created = ensure_server(
            instance, marketplace, project_id, security_group_id, ip, keys, commercial_type
        )
    except ScalewayException as error:
        message = explain(error.status_code, str(error), commercial_type)
        if "quotas_exceeded" in str(error):
            report = read_quota(client, env("SCW_DEFAULT_ORGANIZATION_ID"))
            message += " " + report
            summary = os.environ.get("GITHUB_STEP_SUMMARY")
            if summary:
                with open(summary, "a", encoding="utf-8") as file:
                    file.write(f"### Kvoten hos Scaleway\n\n{report}\n")
        fail(message)

    key_file, known_hosts = write_ssh_files(keys, ip.address)
    output("ip", ip.address)
    output("user", DEPLOY_USER)
    output("key_file", str(key_file))
    output("known_hosts", str(known_hosts))
    output("created", "true" if created else "false")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
