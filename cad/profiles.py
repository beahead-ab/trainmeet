"""The gable profiles (CAD-07, CAD-22): the norms', the general ones and the own ones.

The norms' exact measures are read in before the launch (CAD-N, Öppet in the CAD views). What
the spec states is seeded here, and the rest is marked as not read (read=False) and given per
module meanwhile:

- MMM: track 1 is 140 mm from Kant 1, a double track +57 mm (CAD views, Öppet; the AnyRail
  import found CDA's main tracks at 141/198 mm). Four tracks as at the reference station Gårdsjö:
  140 / 197 / 283 / 340 mm, that is 140 + 57 + 86 + 57.
- FREMO, USMS and FREMO Spur 0: no measures in the spec yet, so Kant 1 → spår 1 and the spacing
  are given per module.
- N: the spec names no norm in N yet (CAD10, CAD-N), so N has only the general profiles.

General profiles are shared by all, with the positions given per module ("Läge och spåravstånd
anges per modul"). Own profiles are a person's or a club's, with every position measured; a
club's can be the club's own norm (CAD11). They live in the table gable_profile.
"""

from __future__ import annotations

import itertools
from collections.abc import Sequence
from typing import Any

from contracts.cad import (
    MAX_TRACKS,
    NORM_NAMES,
    NORMS,
    POSITION_TOLERANCE,
    Gable,
    GableProfile,
    Norm,
    NormInfo,
    Owner,
    OwnerKind,
    ProfileKind,
    Scale,
)

NOT_READ = "läses in före lanseringen"


def _norm(
    id: str,
    name: str,
    scale: Scale,
    norm: Norm,
    tracks: int,
    first: float | None = None,
    spacings: Sequence[float | None] | None = None,
    note: str | None = None,
) -> GableProfile:
    return GableProfile(
        id=id,
        name=name,
        kind=ProfileKind.NORM,
        scale=scale,
        norm=norm,
        tracks=tracks,
        first=first,
        spacings=list(spacings) if spacings is not None else [None] * (tracks - 1),
        read=False,
        note=note,
    )


def _general(scale: Scale, tracks: int) -> GableProfile:
    word = {1: "enkelspår", 2: "dubbelspår"}[tracks]
    return GableProfile(
        id=f"{scale.value.lower()}-{word.replace('å', 'a')}",
        name=word.capitalize(),
        kind=ProfileKind.GENERAL,
        scale=scale,
        tracks=tracks,
        spacings=[None] * (tracks - 1),
        note="Läge och spåravstånd anges per modul.",
    )


SEEDED: tuple[GableProfile, ...] = (
    _norm(
        "h0-fremo-enkelspar",
        "FREMO enkelspår",
        Scale.H0,
        Norm.FREMO,
        1,
        note=f"Mått enligt FREMO:s standard, {NOT_READ}. Kant 1 → spår 1 per modul.",
    ),
    _norm(
        "h0-fremo-dubbelspar",
        "FREMO dubbelspår",
        Scale.H0,
        Norm.FREMO,
        2,
        note=f"Mått enligt FREMO:s standard, {NOT_READ}. Lägena per modul.",
    ),
    _norm(
        "h0-mmm-enkelspar",
        "MMM enkelspår",
        Scale.H0,
        Norm.MMM,
        1,
        first=140,
        note="Spåret 140 mm från Kant 1.",
    ),
    _norm(
        "h0-mmm-dubbelspar",
        "MMM dubbelspår",
        Scale.H0,
        Norm.MMM,
        2,
        first=140,
        spacings=[57],
        note="Dubbelspår: 140 mm från Kant 1 + 57 mm.",
    ),
    _norm(
        "h0-mmm-fyrspar",
        "MMM fyrspår",
        Scale.H0,
        Norm.MMM,
        4,
        first=140,
        spacings=[57, 86, 57],
        note=f"140 / 197 / 283 / 340 mm från Kant 1, {NOT_READ}.",
    ),
    _norm(
        "h0-usms-enkelspar",
        "USMS enkelspår",
        Scale.H0,
        Norm.USMS,
        1,
        note=f"Mått enligt USMS-normen, {NOT_READ}. Kant 1 → spår 1 per modul.",
    ),
    _general(Scale.H0, 1),
    _general(Scale.H0, 2),
    _general(Scale.N, 1),
    _general(Scale.N, 2),
    _norm(
        "0-fremo-spur-0-enkelspar",
        "FREMO Spur 0 enkelspår",
        Scale.ZERO,
        Norm.FREMO_SPUR_0,
        1,
        note=f"Mått enligt FREMO Spur 0, {NOT_READ}. Kant 1 → spår 1 per modul.",
    ),
    _general(Scale.ZERO, 1),
    _general(Scale.ZERO, 2),
)

SEEDED_BY_ID = {p.id: p for p in SEEDED}


def norms_in(scale: Scale) -> list[NormInfo]:
    return [NormInfo(norm=n, name=NORM_NAMES[n]) for n in NORMS[scale]]


def own_profile(row: dict[str, Any]) -> GableProfile:
    """An own profile from its row in gable_profile."""
    positions = [float(p) for p in row["positions"]]
    return GableProfile(
        id=str(row["id"]),
        name=str(row["name"]),
        kind=ProfileKind.OWN,
        scale=Scale(row["scale"]),
        norm=Norm(row["norm"]) if row["norm"] else None,
        tracks=len(positions),
        first=positions[0],
        spacings=[round(b - a, 1) for a, b in itertools.pairwise(positions)],
        note=None,
        owner=Owner(
            kind=OwnerKind(row["owner_kind"]), id=row["owner_id"], name=str(row["owner_name"])
        ),
    )


def positions(profile: GableProfile) -> list[float | None]:
    """The profile's fixed positions from Kant 1, None where they are given per module."""
    found: list[float | None] = [profile.first]
    for spacing in profile.spacings:
        before = found[-1]
        found.append(before + spacing if before is not None and spacing is not None else None)
    return found


def check(gable: Gable, profile: GableProfile) -> str | None:
    """Why the gable does not follow its profile, or None. A position the profile fixes must
    lie within 0,5 mm, and so must a spacing it fixes."""
    if len(gable.tracks) != profile.tracks:
        return f"Gavel {gable.end}: {profile.name} har {profile.tracks} spår."
    for n, fixed in enumerate(positions(profile)):
        if fixed is not None and abs(gable.tracks[n] - fixed) > POSITION_TOLERANCE:
            return (
                f"Gavel {gable.end}: spår {n + 1} ligger {fixed:g} mm från Kant 1 i {profile.name}."
            )
    for n, spacing in enumerate(profile.spacings):
        if spacing is None:
            continue
        found = gable.tracks[n + 1] - gable.tracks[n]
        if abs(found - spacing) > POSITION_TOLERANCE:
            return (
                f"Gavel {gable.end}: spår {n + 1} → spår {n + 2} är {spacing:g} mm "
                f"i {profile.name}."
            )
    if profile.kind == ProfileKind.NORM and gable.norm not in (None, profile.norm):
        return f"Gavel {gable.end}: {profile.name} följer en annan norm."
    return None


def label(gable: Gable, profile: GableProfile | None) -> str:
    """The gable as the library shows it."""
    if profile is not None:
        return profile.name
    if not gable.tracks:
        return "Utan spår"
    count = len(gable.tracks)
    return f"Egen gavel · {count} spår" if count <= MAX_TRACKS else "Egen gavel"
