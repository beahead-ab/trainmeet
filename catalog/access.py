"""Who may do what in a fleet, decided in one place (CAT-49, CAT-46, #49).

The owner may do everything. Someone the fleet is shared with gets the right ID says now
(CAT-48): to look, or to edit. 404 when the fleet is not seen at all, 403 when it is seen but
the action needs more.

What each right gives (CAT-46, CAT-47, CAT-71, CAT-74, CAT-77):
- look: the fleet, the cards, the pictures and the places' names. That a vehicle has a tag,
  never the tag.
- edit: as look, and change the core fields, add vehicles, and add, choose and remove
  pictures, which are stored with the owner within the owner's limit (CAT-133). The place
  stays the owner's.
- owner: also the tags and their history, the places, lending, the events, Säg till ägaren's
  messages, removing a vehicle, and the settings. A club's administrators have the owner's
  right to the club's fleet (CAT-51, C36, C39).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from uuid import UUID

from catalog.fleet import Refused, not_found
from catalog.id_roles import IdRoles
from contracts.catalog import ProblemCode, Vehicle, VehicleList


class Right(IntEnum):
    LOOK = 1
    EDIT = 2
    OWNER = 3


@dataclass(frozen=True)
class Work:
    """Who works, in whose fleet, with which right."""

    person: UUID
    owner: UUID
    right: Right

    @property
    def own(self) -> bool:
        return self.right == Right.OWNER


class Access:
    def __init__(self, roles: IdRoles | None) -> None:
        self.roles = roles

    def right(self, person: UUID, owner: UUID) -> Right | None:
        if person == owner:
            return Right.OWNER
        if self.roles is None:
            return None
        found = self.roles.fleet_roles(person, owner)
        if "admin" in found:  # a club's administrators: the owner's right (CAT-51, C39)
            return Right.OWNER
        if "editor" in found:
            return Right.EDIT
        if "viewer" in found:
            return Right.LOOK
        return None

    def work(self, person: UUID, owner: UUID | None, need: Right) -> Work:
        """The person's work in the fleet, or 404 or 403 (CAT-49)."""
        owner = owner or person
        right = self.right(person, owner)
        if right is None:
            raise not_found()
        if right < need:
            raise Refused(403, ProblemCode.FORBIDDEN, "Det får bara ägaren göra.")
        return Work(person=person, owner=owner, right=right)

    def is_club(self, person: UUID, owner: UUID) -> bool:
        """Is the fleet's owner a club, as ID says to the person working in it (TOKEN-29)? A
        person's own fleet never is."""
        if person == owner or self.roles is None:
            return False
        return any(f.owner == owner and f.club for f in self.roles.shared_fleets(person))

    def shared_with(self, asker: UUID, owner: UUID) -> str | None:
        """For the tag lookup's fifth outcome (C35): view, edit, or nothing."""
        try:
            right = self.right(asker, owner)
        except Refused:
            return None
        return (
            {Right.LOOK: "view", Right.EDIT: "edit", Right.OWNER: "edit"}.get(right)
            if right
            else None
        )


def shown(vehicle: Vehicle, work: Work) -> Vehicle:
    """The vehicle as the right lets it be seen: never the tag or the messages to the owner."""
    tagged = bool(vehicle.tags)
    if work.own:
        return vehicle.model_copy(update={"tagged": tagged})
    return vehicle.model_copy(update={"tagged": tagged, "tags": [], "notices": []})


def shown_list(found: VehicleList, work: Work) -> VehicleList:
    return found.model_copy(update={"vehicles": [shown(v, work) for v in found.vehicles]})
