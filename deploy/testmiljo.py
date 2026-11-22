"""Sätter upp testmiljön för TrainMeet Hub hos Scaleway i Amsterdam (zon nl-ams-1).

Körs av jobbet "Testmiljön" i .github/workflows/tester.yml vid varje ändring på main.
Allt skapas första gången och återanvänds sedan, så samma körning fungerar första och
hundrade gången:

- SSH-nycklarna (en för utläggningen och värdens egen nyckel) skapas här och sparas i
  Scaleways Secret Manager. De skrivs aldrig ut och ligger aldrig i repot.
- En säkerhetsgrupp som bara släpper in SSH, HTTP och HTTPS.
- En fast IPv4-adress, så att DNS-raden för test.hub.trainmeet.app står still.
- En server (DEV1-S med Ubuntu 24.04) med Docker, som cloud-init sätter upp vid första start.
- TrainMeet Catalogs två hemligheter i testmiljön (C35): lösenordet till databasen och
  nyckeln som säkerhetskopiorna krypteras med (CAT-39). De skapas här en gång, sparas i
  Secret Manager och skrivs till en fil som jobbet lägger på servern; de skrivs aldrig ut.
- TrainMeet ID:s tre hemligheter (#66): databasens lösenord, den första administratörens
  lösenord och hemligheten som Catalog loggar in i ID med. Likadant som Catalogs.
- TrainMeet CAD:s hemligheter (#89): lösenordet till CAD:s databas och nyckeln som dess
  säkerhetskopior krypteras med, som Catalogs, och hemligheten som CAD loggar in i ID med
  (klienten cad). Den sista sparas för sig, som hubbens, och går både till ID och till CAD.

    python deploy/testmiljo.py ensure

Miljön (secrets i GitHub):
    SCW_ACCESS_KEY, SCW_SECRET_KEY, SCW_DEFAULT_PROJECT_ID, SCW_DEFAULT_ORGANIZATION_ID
Valfritt:
    TESTMILJO_TYPE      servertyp, förval DEV1-S
    TESTMILJO_SSH_DIR   var nyckelfilerna skrivs för jobbets ssh, förval ~/.ssh
- Catalogs bilder (#51, C35): en egen hink i Object Storage och en egen IAM-app med en nyckel
  som bara når Object Storage i det här projektet. Nyckeln sparas i Secret Manager och läggs i
  catalog-vault på servern. Utan rätten att skapa IAM-appar ligger bilderna på serverns disk.
  Rätten behövs bara den körning som skapar appen; finns nyckeln i Secret Manager frågas
  IAM inte alls.
- CAD:s modulfoton (#89 del c1, CAD-19): likadant, en egen hink, aldrig Catalogs, och en egen
  IAM-app med en egen nyckel. Nyckeln följer med i cad.env, och up.sh lägger den i cad-vault på
  servern, aldrig i .env. Utan hinken ligger fotona på serverns disk, i cad-photos.

Resultatet (GITHUB_OUTPUT): ip, user, key_file, known_hosts, catalog_env, id_env, cad_env,
created, och pictures_key när hinken finns.
"""

from __future__ import annotations

import base64
import json
import os
import secrets as random_secrets
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, NoReturn, cast

from scaleway import Client
from scaleway.iam.v1alpha1 import IamV1Alpha1API
from scaleway.iam.v1alpha1.types import Quotum, RuleSpecs
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
from scaleway.secret.v1beta1 import Secret, SecretV1Beta1API
from scaleway_core.api import ScalewayException

ZONE = "nl-ams-1"
REGION = "nl-ams"
NAME = "trainmeet-testhub"
TAG = "trainmeet-testmiljo"
SECRET_NAME = "trainmeet-testmiljo-ssh"
CATALOG_SECRET_NAME = "trainmeet-testmiljo-catalog"
# Catalogs bilder (#51, C35, CAT-130): a bucket of their own in Object Storage, reached with a
# key of their own that only gives Object Storage in this project, never the deploy's key.
PICTURES_NAME = "trainmeet-testmiljo-catalog-bilder"
PICTURES_SECRET_NAME = "trainmeet-testmiljo-catalog-bilder-nyckel"
S3_ENDPOINT = "https://s3.nl-ams.scw.cloud"
ID_SECRET_NAME = "trainmeet-testmiljo-id"
ID_API_SECRET_NAME = "trainmeet-testmiljo-id-api"
ID_HUB_SECRET_NAME = "trainmeet-testmiljo-id-hub"
CAD_SECRET_NAME = "trainmeet-testmiljo-cad"
ID_CAD_SECRET_NAME = "trainmeet-testmiljo-id-cad"
# CAD:s modulfoton (#89 del c1, CAD-19): a bucket of their own, as Catalog's pictures, never
# Catalog's, with a key of their own that only gives Object Storage in this project.
CAD_PHOTOS_NAME = "trainmeet-testmiljo-cad-foton"
CAD_PHOTOS_SECRET_NAME = "trainmeet-testmiljo-cad-foton-nyckel"
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


@dataclass(frozen=True)
class CatalogSecrets:
    """Catalog's database password and backup key in the test environment."""

    db_password: str
    backup_key: str

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, text: str) -> CatalogSecrets:
        data = json.loads(text)
        return cls(**{field: str(data[field]) for field in cls.__dataclass_fields__})

    def env_file(self) -> str:
        """The lines up.sh puts in .env on the server. Hex only, so no quoting is needed."""
        return f"CATALOG_DB_PASSWORD={self.db_password}\nCATALOG_BACKUP_KEY={self.backup_key}\n"


@dataclass(frozen=True)
class IdSecrets:
    """TrainMeet ID in the test environment: its database, its first administrator, and the
    secret Catalog logs in to it with (#66)."""

    db_password: str
    admin_password: str
    catalog_secret: str

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, text: str) -> IdSecrets:
        data = json.loads(text)
        return cls(**{field: str(data[field]) for field in cls.__dataclass_fields__})

    def env_file(self) -> str:
        """The lines up.sh puts in .env on the server. Hex only, so no quoting is needed."""
        return (
            f"ID_DB_PASSWORD={self.db_password}\n"
            f"ID_ADMIN_PASSWORD={self.admin_password}\n"
            f"ID_CATALOG_SECRET={self.catalog_secret}\n"
        )


@dataclass(frozen=True)
class IdApiSecrets:
    """ID's own API and web app in the test environment (#67): the secret it logs in to
    Keycloak with. A secret of its own, so the one from #66 stays as it is."""

    app_secret: str

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, text: str) -> IdApiSecrets:
        data = json.loads(text)
        return cls(**{field: str(data[field]) for field in cls.__dataclass_fields__})

    def env_file(self) -> str:
        return f"ID_APP_SECRET={self.app_secret}\n"


@dataclass(frozen=True)
class IdHubSecrets:
    """The test hub's client in ID (#78): the secret it logs in to Keycloak with, and asks ID's
    API about the roles at a meet with. A secret of its own, so the earlier ones stay as they
    are."""

    hub_secret: str

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, text: str) -> IdHubSecrets:
        data = json.loads(text)
        return cls(**{field: str(data[field]) for field in cls.__dataclass_fields__})

    def env_file(self) -> str:
        return f"ID_HUB_SECRET={self.hub_secret}\n"


@dataclass(frozen=True)
class CadSecrets:
    """TrainMeet CAD's database password and backup key in the test environment (#89), as
    Catalog's."""

    db_password: str
    backup_key: str

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, text: str) -> CadSecrets:
        data = json.loads(text)
        return cls(**{field: str(data[field]) for field in cls.__dataclass_fields__})

    def env_file(self) -> str:
        """The lines up.sh puts in .env on the server. Hex only, so no quoting is needed."""
        return f"CAD_DB_PASSWORD={self.db_password}\nCAD_BACKUP_KEY={self.backup_key}\n"


@dataclass(frozen=True)
class IdCadSecrets:
    """CAD's client in ID (#89): the secret it logs in to Keycloak with, and asks ID's API about
    the clubs and the roles with. A secret of its own, as the hub's, so the earlier ones stay as
    they are. Keycloak's client cad and CAD itself both read it as ID_CAD_SECRET."""

    cad_secret: str

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, text: str) -> IdCadSecrets:
        data = json.loads(text)
        return cls(**{field: str(data[field]) for field in cls.__dataclass_fields__})

    def env_file(self) -> str:
        return f"ID_CAD_SECRET={self.cad_secret}\n"


def generate_cad_secrets() -> CadSecrets:
    return CadSecrets(
        db_password=random_secrets.token_hex(24), backup_key=random_secrets.token_hex(32)
    )


def generate_id_cad_secrets() -> IdCadSecrets:
    return IdCadSecrets(cad_secret=random_secrets.token_hex(32))


def generate_id_hub_secrets() -> IdHubSecrets:
    return IdHubSecrets(hub_secret=random_secrets.token_hex(32))


def generate_id_api_secrets() -> IdApiSecrets:
    return IdApiSecrets(app_secret=random_secrets.token_hex(32))


def generate_id_secrets() -> IdSecrets:
    return IdSecrets(
        db_password=random_secrets.token_hex(24),
        admin_password=random_secrets.token_hex(24),
        catalog_secret=random_secrets.token_hex(32),
    )


def generate_catalog_secrets() -> CatalogSecrets:
    return CatalogSecrets(
        db_password=random_secrets.token_hex(24), backup_key=random_secrets.token_hex(32)
    )


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
        "ssh_genkeytypes": ["ed25519"],
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


def find_secret(secrets: SecretV1Beta1API, project_id: str, name: str) -> Secret | None:
    existing = secrets.list_secrets(
        project_id=project_id, name=name, scheduled_for_deletion=False
    ).secrets
    return next((s for s in existing if s.name == name), None)


def latest_version(secrets: SecretV1Beta1API, secret: Secret | None) -> str | None:
    """The text of the secret's latest version, or None when it has none yet."""
    if secret is None or secret.version_count == 0:
        return None
    version = secrets.access_secret_version(secret_id=secret.id, revision="latest")
    return base64.b64decode(version.data).decode()


def read_secret(secrets: SecretV1Beta1API, project_id: str, name: str) -> str | None:
    """The latest version of a secret, or None when there is none yet."""
    return latest_version(secrets, find_secret(secrets, project_id, name))


def ensure_secret(
    secrets: SecretV1Beta1API,
    project_id: str,
    name: str,
    description: str,
    new: Callable[[], str],
) -> tuple[str, bool]:
    """The latest version of a secret, made with `new` the first time. (text, created)"""
    secret = find_secret(secrets, project_id, name)
    stored = latest_version(secrets, secret)
    if stored is not None:
        return stored, False

    if secret is None:
        secret = secrets.create_secret(
            name=name, protected=False, project_id=project_id, tags=[TAG], description=description
        )
    text = new()
    secrets.create_secret_version(
        secret_id=secret.id, data=base64.b64encode(text.encode()).decode()
    )
    return text, True


def ensure_keys(secrets: SecretV1Beta1API, project_id: str) -> Keys:
    text, created = ensure_secret(
        secrets,
        project_id,
        SECRET_NAME,
        "SSH-nycklarna för testmiljön. Skapas av deploy/testmiljo.py.",
        lambda: generate_keys().to_json(),
    )
    if created:
        print("Nya SSH-nycklar skapade och sparade i Secret Manager.")
    return Keys.from_json(text)


def ensure_catalog_secrets(secrets: SecretV1Beta1API, project_id: str) -> CatalogSecrets:
    text, created = ensure_secret(
        secrets,
        project_id,
        CATALOG_SECRET_NAME,
        "Catalogs databaslösenord och backupnyckel i testmiljön. Skapas av deploy/testmiljo.py.",
        lambda: generate_catalog_secrets().to_json(),
    )
    if created:
        print("Catalogs hemligheter skapade och sparade i Secret Manager.")
    return CatalogSecrets.from_json(text)


def ensure_cad_secrets(secrets: SecretV1Beta1API, project_id: str) -> CadSecrets:
    text, created = ensure_secret(
        secrets,
        project_id,
        CAD_SECRET_NAME,
        "CAD:s databaslösenord och backupnyckel i testmiljön. Skapas av deploy/testmiljo.py.",
        lambda: generate_cad_secrets().to_json(),
    )
    if created:
        print("CAD:s hemligheter skapade och sparade i Secret Manager.")
    return CadSecrets.from_json(text)


def ensure_id_cad_secrets(secrets: SecretV1Beta1API, project_id: str) -> IdCadSecrets:
    text, created = ensure_secret(
        secrets,
        project_id,
        ID_CAD_SECRET_NAME,
        "Hemligheten som CAD loggar in i Keycloak med (#89). Skapas av deploy/testmiljo.py.",
        lambda: generate_id_cad_secrets().to_json(),
    )
    if created:
        print("CAD:s hemlighet mot ID skapad och sparad i Secret Manager.")
    return IdCadSecrets.from_json(text)


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


def write_private(name: str, text: str) -> Path:
    """A private file for the deploy to put on the server. Never printed."""
    folder = Path(os.environ.get("TESTMILJO_SSH_DIR") or Path.home() / ".ssh")
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = folder / name
    path.touch(mode=0o600, exist_ok=True)
    path.chmod(0o600)
    path.write_text(text)
    return path


def write_catalog_env(catalog: CatalogSecrets, bucket: str | None = None) -> Path:
    """Catalog's secrets as a private file, for the deploy to put on the server, with the
    pictures' bucket when there is one (#51)."""
    text = catalog.env_file() + (f"CATALOG_PICTURES_S3_BUCKET={bucket}\n" if bucket else "")
    return write_private("testmiljo_catalog.env", text)


def write_cad_env(
    cad: CadSecrets, id_cad: IdCadSecrets, photos: tuple[str, PictureKey] | None = None
) -> Path:
    """CAD's secrets as a private file, for the deploy to put on the server (#89): its
    database and backups, and the secret it logs in to ID with, which id.env also has. With
    the photos' bucket (#89 del c1), its name and its key: up.sh puts the key in cad-vault,
    which only the deploy user reads, and keeps it out of .env."""
    text = cad.env_file() + id_cad.env_file()
    if photos is not None:
        bucket, key = photos
        text += (
            f"CAD_PHOTOS_S3_BUCKET={bucket}\n"
            f"CAD_PHOTOS_S3_ACCESS_KEY={key.access_key}\n"
            f"CAD_PHOTOS_S3_SECRET_KEY={key.secret_key}\n"
        )
    return write_private("testmiljo_cad.env", text)


# --- Catalogs bilder (#51) --------------------------------------------------------------


class PicturesError(Exception):
    """The bucket could not be made. The message never holds a key."""


@dataclass(frozen=True)
class PictureKey:
    """The key Catalog reaches its bucket with: Object Storage only, in this project."""

    access_key: str
    secret_key: str = field(repr=False)

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, text: str) -> PictureKey:
        data = json.loads(text)
        return cls(access_key=str(data["access_key"]), secret_key=str(data["secret_key"]))

    def key_file(self) -> str:
        """The file Catalog reads the key from (CATALOG_PICTURES_S3_KEY_FILE)."""
        return f"{self.access_key}\n{self.secret_key}\n"


def bucket_name(project_id: str) -> str:
    """A bucket name is unique across Scaleway; the project's first part makes it ours."""
    return f"trainmeet-test-bilder-{project_id.split('-')[0].lower()}"


def cad_bucket_name(project_id: str) -> str:
    """CAD's own bucket for the module photos, beside Catalog's and never the same (CAD-19)."""
    return f"trainmeet-test-cad-foton-{project_id.split('-')[0].lower()}"


def ensure_picture_key(
    iam: IamV1Alpha1API,
    secrets: SecretV1Beta1API,
    project_id: str,
    organization_id: str,
    name: str = PICTURES_NAME,
    secret_name: str = PICTURES_SECRET_NAME,
    what: str = "Catalogs bilder",
) -> PictureKey:
    """An IAM application with a policy for Object Storage in this project only, and its key
    in Secret Manager. Made the first time, then read back. Catalog's pictures and CAD's
    photos have one each.

    A key already in Secret Manager is used as it is, without asking IAM, so the deploy's key
    needs the right to make IAM applications only for the run that makes them."""
    stored = read_secret(secrets, project_id, secret_name)
    if stored is not None:
        return PictureKey.from_json(stored)
    found = iam.list_applications_all(organization_id=organization_id, name=name)
    application = next((a for a in found if a.name == name), None)
    if application is None:
        application = iam.create_application(
            name=name,
            description=f"{what} i testmiljön. Skapas av deploy/testmiljo.py.",
            organization_id=organization_id,
            tags=[TAG],
        )
        print(f"{what} fick en egen IAM-app.")
    policies = iam.list_policies_all(
        organization_id=organization_id, application_ids=[application.id]
    )
    if not any(policy.name == name for policy in policies):
        iam.create_policy(
            name=name,
            description="Bara Object Storage, bara i testmiljöns projekt.",
            organization_id=organization_id,
            application_id=application.id,
            rules=[
                RuleSpecs(
                    condition="",
                    permission_set_names=["ObjectStorageFullAccess"],
                    project_ids=[project_id],
                )
            ],
            tags=[TAG],
        )

    def new() -> str:
        made = iam.create_api_key(
            application_id=application.id,
            description=f"{what} i testmiljön.",
            default_project_id=project_id,
        )
        if not made.secret_key:
            raise PicturesError(f"Scaleway gav ingen hemlig nyckel till {what}.")
        return PictureKey(access_key=made.access_key, secret_key=made.secret_key).to_json()

    text, created = ensure_secret(
        secrets,
        project_id,
        secret_name,
        f"Nyckeln till {what} i testmiljön. Skapas av deploy/testmiljo.py.",
        new,
    )
    if created:
        print(f"{what} fick en egen nyckel, sparad i Secret Manager.")
    return PictureKey.from_json(text)


Send = Callable[[str, str, PictureKey], int]


def s3_send(method: str, url: str, key: PictureKey) -> int:
    """One empty S3 call signed with SigV4, as Object Storage wants it. Gives the status."""
    import hashlib

    import httpx
    from botocore.auth import S3SigV4Auth
    from botocore.awsrequest import AWSRequest
    from botocore.credentials import Credentials

    request = AWSRequest(
        method=method,
        url=url,
        data=b"",
        headers={"x-amz-content-sha256": hashlib.sha256(b"").hexdigest()},
    )
    S3SigV4Auth(Credentials(key.access_key, key.secret_key), "s3", REGION).add_auth(request)
    answer = httpx.request(method, url, headers=dict(request.headers.items()), timeout=30.0)
    return answer.status_code


def ensure_bucket(
    key: PictureKey,
    bucket: str,
    send: Send = s3_send,
    wait: Callable[[float], None] = time.sleep,
    what: str = "Catalogs bilder",
) -> None:
    """The bucket, private as Object Storage makes it. A new policy can take a moment to
    reach Object Storage, so a refusal is tried again a few times."""
    url = f"{S3_ENDPOINT}/{bucket}"
    status = 0
    for attempt in range(8):
        status = send("HEAD", url, key)
        if status == 200:
            return
        if status == 404:
            status = send("PUT", url, key)
            if status == 200:
                print(f"Hinken för {what} skapad.")
                return
        if status not in (401, 403, 409):
            break
        wait(5.0 * (attempt + 1))
    raise PicturesError(f"Hinken för {what} gick inte att nå (HTTP {status}).")


def ensure_pictures(
    iam: IamV1Alpha1API,
    secrets: SecretV1Beta1API,
    project_id: str,
    organization_id: str,
    send: Send = s3_send,
    *,
    name: str = PICTURES_NAME,
    secret_name: str = PICTURES_SECRET_NAME,
    bucket: str | None = None,
    what: str = "Catalogs bilder",
) -> tuple[str, PictureKey] | None:
    """The bucket and its key, or None: then the pictures lie on the server's disk, and the
    deploy goes on. The reason is said, never a key."""
    try:
        key = ensure_picture_key(iam, secrets, project_id, organization_id, name, secret_name, what)
        bucket = bucket or bucket_name(project_id)
        ensure_bucket(key, bucket, send, what=what)
    except ScalewayException as error:
        print(
            f"::notice::{what} ligger på serverns disk: Scaleway nekade IAM-appen "
            f"(HTTP {error.status_code}). Ge GitHub-nyckelns applikation behörigheten "
            "IAMManager i organisationen för en körning; sedan läses nyckeln ur Secret Manager "
            "och behörigheten kan tas bort (README, Engångsuppsättningen)."
        )
        return None
    except PicturesError as error:
        print(f"::notice::{what} ligger på serverns disk: {error}")
        return None
    return bucket, key


def ensure_cad_photos(
    iam: IamV1Alpha1API,
    secrets: SecretV1Beta1API,
    project_id: str,
    organization_id: str,
    send: Send = s3_send,
) -> tuple[str, PictureKey] | None:
    """CAD's own bucket for the module photos and its own key (#89 del c1), exactly as
    Catalog's pictures get theirs; without it the photos lie on the server's disk."""
    return ensure_pictures(
        iam,
        secrets,
        project_id,
        organization_id,
        send,
        name=CAD_PHOTOS_NAME,
        secret_name=CAD_PHOTOS_SECRET_NAME,
        bucket=cad_bucket_name(project_id),
        what="CAD:s modulfoton",
    )


def ensure_id_secrets(secrets: SecretV1Beta1API, project_id: str) -> IdSecrets:
    text, created = ensure_secret(
        secrets,
        project_id,
        ID_SECRET_NAME,
        "TrainMeet ID:s databaslösenord, administratör och Catalogs hemlighet i testmiljön. "
        "Skapas av deploy/testmiljo.py.",
        lambda: generate_id_secrets().to_json(),
    )
    if created:
        print("ID:s hemligheter skapade och sparade i Secret Manager.")
    return IdSecrets.from_json(text)


def ensure_id_api_secrets(secrets: SecretV1Beta1API, project_id: str) -> IdApiSecrets:
    text, created = ensure_secret(
        secrets,
        project_id,
        ID_API_SECRET_NAME,
        "Hemligheten som ID:s API och webbapp loggar in i Keycloak med i testmiljön. "
        "Skapas av deploy/testmiljo.py.",
        lambda: generate_id_api_secrets().to_json(),
    )
    if created:
        print("Hemligheten för ID:s API skapad och sparad i Secret Manager.")
    return IdApiSecrets.from_json(text)


def ensure_id_hub_secrets(secrets: SecretV1Beta1API, project_id: str) -> IdHubSecrets:
    text, created = ensure_secret(
        secrets,
        project_id,
        ID_HUB_SECRET_NAME,
        "Hemligheten som testhubben loggar in i Keycloak med (#78). Skapas av deploy/testmiljo.py.",
        lambda: generate_id_hub_secrets().to_json(),
    )
    if created:
        print("Hubbens hemlighet mot ID skapad och sparad i Secret Manager.")
    return IdHubSecrets.from_json(text)


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
        catalog = ensure_catalog_secrets(secrets, project_id)
        id_secrets = ensure_id_secrets(secrets, project_id)
        id_api_secrets = ensure_id_api_secrets(secrets, project_id)
        id_hub_secrets = ensure_id_hub_secrets(secrets, project_id)
        cad_secrets = ensure_cad_secrets(secrets, project_id)
        id_cad_secrets = ensure_id_cad_secrets(secrets, project_id)
        pictures = ensure_pictures(
            IamV1Alpha1API(client), secrets, project_id, env("SCW_DEFAULT_ORGANIZATION_ID")
        )
        cad_photos = ensure_cad_photos(
            IamV1Alpha1API(client), secrets, project_id, env("SCW_DEFAULT_ORGANIZATION_ID")
        )
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
    output("catalog_env", str(write_catalog_env(catalog, pictures[0] if pictures else None)))
    # The pictures' key goes to catalog-vault on the server, which only the deploy user reads.
    if pictures is not None:
        output("pictures_key", str(write_private("testmiljo_bilder.key", pictures[1].key_file())))
    # up.sh puts the files in .env, so Catalog reads ID_CATALOG_SECRET from there too, the hub
    # ID_HUB_SECRET (#78), and Keycloak's client cad ID_CAD_SECRET (#89). ID sends its codes
    # with Scaleway's Transactional Email in this project (#66).
    id_env = (
        id_secrets.env_file()
        + id_api_secrets.env_file()
        + id_hub_secrets.env_file()
        + id_cad_secrets.env_file()
        + f"TEM_PROJECT_ID={project_id}\n"
    )
    output("id_env", str(write_private("testmiljo_id.env", id_env)))
    # CAD's photos' key travels in cad.env; up.sh moves it to cad-vault (#89 del c1).
    output("cad_env", str(write_cad_env(cad_secrets, id_cad_secrets, cad_photos)))
    output("created", "true" if created else "false")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
