"""Where CAD keeps the module photos (CAD-19): CAD's own bucket in Object Storage, or CAD's own
disk when there is none, as Catalog keeps its pictures (CAT-130). The two never share a bucket.

The files are private. The browser fetches them with signed addresses that expire: Object
Storage's presigned ones, or, on disk, addresses CAD signs itself with an HMAC and serves at
FILES_PATH. An address stays the same for half an hour, so the browser can keep the picture.

A key is random, under the owner's id, never guessable: <owner>/<32 hex>.<jpg|png>. Keys and
secrets are never written to the log.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
import secrets
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, Protocol
from urllib.parse import quote
from uuid import UUID

import httpx
from botocore.auth import S3SigV4Auth, S3SigV4QueryAuth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials

LOGGER = logging.getLogger("cad.store")

LINK_LIFETIME: Final = 3600
FILES_PATH: Final = "/api/cad/1/photos/file/"
KEY: Final = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/[0-9a-f]{32}\.(?:jpg|png)"
)
TYPES: Final = {"jpg": "image/jpeg", "png": "image/png"}


class StoreFailed(Exception):
    """The store did not do what was asked. Never holds a key or a secret."""


class Store(Protocol):
    def put(self, key: str, data: bytes) -> None: ...

    def get(self, key: str) -> bytes: ...

    def delete(self, key: str) -> None: ...

    def url(self, key: str, now: float | None = None) -> str: ...


def new_key(owner: UUID, ending: str = "jpg") -> str:
    return f"{owner}/{uuid.uuid4().hex}.{ending}"


def kind_of(key: str) -> str:
    return TYPES.get(key.rsplit(".", 1)[-1], "image/jpeg")


def signed_at(now: float) -> int:
    half = LINK_LIFETIME // 2
    return int(now) // half * half


class DiskStore:
    """The files in a folder of CAD's own, fetched through CAD at FILES_PATH with an
    HMAC-SHA256 signature and an expiry. For running locally, the tests and a test environment
    without a bucket. The signing key is made at every start."""

    def __init__(self, directory: Path, signing_key: bytes) -> None:
        self.directory = directory
        self._signing_key = signing_key

    def __repr__(self) -> str:
        return f"DiskStore({str(self.directory)!r})"

    def path(self, key: str) -> Path | None:
        return self.directory / key if KEY.fullmatch(key) else None

    def put(self, key: str, data: bytes) -> None:
        target = self.path(key)
        if target is None:
            raise StoreFailed("Ingen giltig nyckel.")
        partial = target.with_name(f".{target.name}.part")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            partial.write_bytes(data)
            os.replace(partial, target)
        except OSError as error:
            partial.unlink(missing_ok=True)
            LOGGER.warning("Fotot kunde inte sparas på disken: %s", type(error).__name__)
            raise StoreFailed("Fotot kunde inte sparas på disken.") from error

    def get(self, key: str) -> bytes:
        target = self.path(key)
        if target is None:
            raise StoreFailed("Ingen giltig nyckel.")
        try:
            return target.read_bytes()
        except OSError as error:
            raise StoreFailed("Fotot kunde inte läsas från disken.") from error

    def delete(self, key: str) -> None:
        target = self.path(key)
        if target is None:
            return
        try:
            target.unlink(missing_ok=True)
        except OSError as error:
            raise StoreFailed("Fotot kunde inte tas bort från disken.") from error

    def _signature(self, key: str, expires: int) -> str:
        return hmac.new(self._signing_key, f"{key}\n{expires}".encode(), hashlib.sha256).hexdigest()

    def url(self, key: str, now: float | None = None) -> str:
        expires = signed_at(time.time() if now is None else now) + LINK_LIFETIME
        return f"{FILES_PATH}{key}?expires={expires}&sig={self._signature(key, expires)}"

    def check(self, key: str, expires: str, signature: str, now: float | None = None) -> bool:
        if self.path(key) is None or not expires.isdigit() or len(expires) > 12:
            return False
        expected = self._signature(key, int(expires)).encode()
        if not hmac.compare_digest(expected, signature.encode()):
            return False
        return int(expires) >= (time.time() if now is None else now)


class _PresignedAt(S3SigV4QueryAuth):  # type: ignore[misc]
    def __init__(self, credentials: Credentials, region: str, at: datetime) -> None:
        super().__init__(credentials, "s3", region, expires=LINK_LIFETIME)
        self._at = at

    def _modify_request_before_signing(self, request: AWSRequest) -> None:
        request.context["timestamp"] = self._at.strftime("%Y%m%dT%H%M%SZ")
        super()._modify_request_before_signing(request)


class S3Store:
    """CAD's own bucket in Object Storage, S3 compatible, private; signed with SigV4."""

    def __init__(
        self,
        endpoint: str,
        bucket: str,
        region: str,
        access_key: str,
        secret_key: str,
        http: httpx.Client,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.bucket = bucket
        self.region = region
        self._credentials = Credentials(access_key, secret_key)
        self.http = http

    def __repr__(self) -> str:
        return f"S3Store({self.endpoint!r}, bucket={self.bucket!r}, region={self.region!r})"

    def _address(self, key: str) -> str:
        return f"{self.endpoint}/{self.bucket}/{quote(key, safe='/')}"

    def _send(
        self, method: str, key: str, data: bytes = b"", headers: dict[str, str] | None = None
    ) -> httpx.Response:
        signed = AWSRequest(method=method, url=self._address(key), data=data, headers=headers)
        S3SigV4Auth(self._credentials, "s3", self.region).add_auth(signed)
        try:
            return self.http.request(
                method, self._address(key), content=data, headers=dict(signed.headers.items())
            )
        except httpx.HTTPError as error:
            LOGGER.warning("Object Storage svarar inte: %s", type(error).__name__)
            raise StoreFailed("Object Storage svarar inte.") from error

    def put(self, key: str, data: bytes) -> None:
        headers = {"Content-Type": kind_of(key), "Cache-Control": "private, max-age=86400"}
        answer = self._send("PUT", key, data, headers)
        if answer.status_code != 200:
            LOGGER.warning("Object Storage svarade %s på en uppladdning.", answer.status_code)
            raise StoreFailed("Object Storage tog inte emot fotot.")

    def get(self, key: str) -> bytes:
        answer = self._send("GET", key)
        if answer.status_code != 200:
            LOGGER.warning("Object Storage svarade %s på en hämtning.", answer.status_code)
            raise StoreFailed("Object Storage lämnade inte ut fotot.")
        return answer.content

    def delete(self, key: str) -> None:
        answer = self._send("DELETE", key)
        if answer.status_code not in (200, 204, 404):
            LOGGER.warning("Object Storage svarade %s på en borttagning.", answer.status_code)
            raise StoreFailed("Object Storage tog inte bort fotot.")

    def url(self, key: str, now: float | None = None) -> str:
        at = datetime.fromtimestamp(signed_at(time.time() if now is None else now), UTC)
        request = AWSRequest(method="GET", url=self._address(key))
        _PresignedAt(self._credentials, self.region, at).add_auth(request)
        address: str = request.url
        return address


def disk(directory: Path) -> DiskStore:
    return DiskStore(directory, secrets.token_bytes(32))
