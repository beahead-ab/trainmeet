"""TrainMeet CAD for the Hub's import (CAD-11, K4): where the cloud hub reaches CAD, and the
planner's own access token from TrainMeet ID to ask it with (#78).

CAD is a cloud service only (CAD-14): the cloud hub asks it, never a meet's Pi, which gets what
the meet uses with the versions (CAD-12). Without HUB_CAD, or for someone not logged in with ID,
Anläggning från CAD is grey, with the reason.

Settings, from the environment:

HUB_CAD   Where the hub reaches TrainMeet CAD, for example http://cad:8000 beside it in the test
          environment. Empty: no CAD.
"""

from __future__ import annotations

import os
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

import httpx

from hub.id_login import IdLogin
from hub.local import PERSON, LocalLogin
from integrationer.cad_assembly import CadClient

AHEAD: Final = 30.0
"""An access token this close to running out is renewed first, in seconds."""
NO_CAD: Final = "Hubben når inte TrainMeet CAD. Anläggningar från CAD läggs till i molnhubben."
NO_LOGIN: Final = "Logga in med TrainMeet ID för att hämta dina anläggningar från CAD."


def address_from(env: Mapping[str, str] | None = None) -> str | None:
    found = (env if env is not None else os.environ).get("HUB_CAD", "").strip()
    return found.rstrip("/") or None


@dataclass
class CadReach:
    """CAD as the cloud hub reaches it, and the planner's token for it."""

    client: CadClient | None
    login: LocalLogin
    with_id: IdLogin | None

    def why_not(self, session: str | None) -> str | None:
        """Why Anläggning från CAD is grey for this session, or None when it is not."""
        if self.client is None or self.with_id is None:
            return NO_CAD
        if self.login.role(session) != PERSON or self.login.id_access(session) is None:
            return NO_LOGIN
        return None

    def token(self, session: str | None) -> str | None:
        """The person's access token from ID, renewed when it is about to run out."""
        found = self.login.id_access(session)
        if found is None or session is None:
            return None
        if found.until - AHEAD > time.time():
            return found.token
        if found.refresh is None or self.with_id is None:
            return None
        renewed = self.with_id.refreshed(found.refresh)
        if renewed is None:
            return None
        self.login.new_access(session, renewed)
        return renewed.token


def reach_from(
    login: LocalLogin,
    with_id: IdLogin | None,
    address: str | None = None,
    http: httpx.Client | None = None,
) -> CadReach:
    """CAD from HUB_CAD, or the address and client given (in tests, a pretend CAD)."""
    where = address if address is not None else address_from()
    client = CadClient(where, http) if where else None
    return CadReach(client=client, login=login, with_id=with_id)
