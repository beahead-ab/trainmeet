"""TrainMeet Catalog's API, trainmeet.catalog/1 (CAT-36): what the web app and others read.

Catalog is its own service with its own database (C16, CAT-30). It never calls the Hub and
the Hub never calls it (K7, CAT-37). Step 1 (#48) has the version, the session and the trial
login. The vehicle, the mini card, the tag, the lookup and the prototype come with their steps
(#50, #54 and #53), in this file.

Addresses:
    GET    /api/version                       CatalogVersion
    GET    /api/catalog/1/session             Session
    DELETE /api/catalog/1/session             Session, logged out
    GET    /api/catalog/1/trial/accounts      [Account], only with the trial login
    POST   /api/catalog/1/trial/login         TrialLogin -> Session, only with the trial login

Rules:
- The session is an HttpOnly cookie. Every changing call checks it on the server (CAT-195).
- The trial login exists only in the test environment, until TrainMeet ID (C21, CAT-214).
  Its accounts are fixed and hold no personal data.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import Field

from contracts.common import Contract, Text


class CatalogVersion(Contract):
    """What is running, so a tester can see which change the test environment has."""

    product: Literal["TrainMeet Catalog"] = "TrainMeet Catalog"
    version: str = Field(description="The package version, for example 0.1.0.")
    commit: str | None = Field(default=None, description="The git commit, or null locally.")
    pr: int | None = Field(default=None, description="The pull request the change came from.")
    title: str | None = Field(default=None, description="The title of that pull request.")
    built: datetime | None = Field(default=None, description="When the image was built, UTC.")


class LoginKind(StrEnum):
    """How people log in to this Catalog."""

    TRIAL = "trial"
    """The trial login in the test environment, until TrainMeet ID (CAT-214)."""
    ID = "id"
    """TrainMeet ID (#49)."""


class Account(Contract):
    """The person who is logged in, as Catalog knows them. The id comes from the login."""

    id: UUID
    name: Text = Field(max_length=80, description="The name the person shows.")
    initials: str = Field(min_length=1, max_length=3, description="For the account button.")


class Session(Contract):
    """Who is logged in, if anyone, and how one logs in here."""

    account: Account | None = None
    login: LoginKind


class TrialLogin(Contract):
    """Log in as one of the trial login's fixed accounts (GET /api/catalog/1/trial/accounts)."""

    account: UUID
