"""A synthetic measuring image with known surfaces, for the landscape's tests (#89 del d1).

A made-up module, 800 × 400 mm, seen from above at 2 px per mm as the photo chain's measuring
image: grass with patches, a pond, a road, a sand path, a platform beside the track, a red roof,
bushes, and a straight track with ballast, sleepers and rails at 140 mm from Kant 1. The light
falls off toward one corner and the pixels have noise. Nothing here is a real station.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from typing import Any

import cv2
import numpy as np
from numpy.typing import NDArray

from contracts.cad import Surface

PPM = 2.0
LENGTH, WIDTH = 800.0, 400.0
TRACK_Y = 140.0


@dataclass(frozen=True)
class Region:
    surface: Surface
    mask: NDArray[np.bool_]
    """In the image's pixels."""


def _bgr(rgb: tuple[int, int, int]) -> NDArray[Any]:
    return np.array([rgb[2], rgb[1], rgb[0]], np.float32)


@cache
def image(seed: int = 3) -> tuple[NDArray[np.uint8], list[Region]]:
    """The measuring image (BGR, pixel (0, 0)'s centre at (0, 0) mm) and its true regions, made
    once per seed: copy it before changing it."""
    rng = np.random.default_rng(seed)
    h, w = round(WIDTH * PPM), round(LENGTH * PPM)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32) / PPM

    def blobs(scale: float) -> NDArray[Any]:
        small = rng.standard_normal((h // 40 + 2, w // 40 + 2)).astype(np.float32)
        big = cv2.resize(small, (w, h), interpolation=cv2.INTER_CUBIC)
        found: NDArray[Any] = cv2.GaussianBlur(big, (0, 0), scale)
        return found / max(float(found.std()), 1e-6)

    grass = _bgr((76, 108, 64)) + blobs(20)[..., None] * np.array([6, 10, 6], np.float32)
    picture = grass.copy()
    regions: list[Region] = []

    def put(surface: Surface, mask: NDArray[np.bool_], colour: NDArray[Any], grain: float) -> None:
        noise = rng.standard_normal((h, w)).astype(np.float32)
        noise = cv2.GaussianBlur(noise, (0, 0), 1.5) * grain / 0.25
        picture[mask] = (colour + noise[..., None])[mask]
        regions.append(Region(surface, mask))

    pond = ((xx - 620) / 90) ** 2 + ((yy - 300) / 55) ** 2 <= 1
    road = (yy >= 360) & (xx <= 520)
    path = (np.abs(xx - 0.55 * yy - 300) <= 14) & (yy >= 232) & (yy <= 350)
    platform = (xx >= 120) & (xx <= 520) & (yy >= 175) & (yy <= 225)
    roof = (xx >= 40) & (xx <= 140) & (yy >= 250) & (yy <= 330)
    bushes = (((xx - 700) / 50) ** 2 + ((yy - 70) / 35) ** 2 <= 1) | (
        ((xx - 300) / 30) ** 2 + ((yy - 60) / 25) ** 2 <= 1
    )
    put(Surface.WATER, pond, _bgr((60, 100, 148)), 2)
    put(Surface.GROUND, road, _bgr((86, 86, 88)), 3)
    put(Surface.PATH, path & ~pond, _bgr((196, 170, 126)), 3)
    put(Surface.PLATFORM, platform, _bgr((206, 204, 198)), 2)
    put(Surface.BUILDING, roof, _bgr((150, 64, 54)), 3)
    put(Surface.TREES, bushes, _bgr((44, 70, 38)), 16)
    # The track: ballast 46 mm wide, sleepers every 7,09 mm, rails 17,5 mm apart.
    ballast = np.abs(yy - TRACK_Y) <= 23
    stones = rng.standard_normal((h, w)).astype(np.float32) * 16
    picture[ballast] = (_bgr((168, 170, 172)) + stones[..., None])[ballast]
    sleepers = (np.abs(yy - TRACK_Y) <= 14) & ((xx % 7.09) < 2.6)
    picture[sleepers] = _bgr((200, 198, 192))
    rails = np.abs(np.abs(yy - TRACK_Y) - 8.75) <= 0.5
    picture[rails] = _bgr((56, 56, 58))
    regions.append(
        Region(Surface.GRASS, ~(pond | road | path | platform | roof | bushes | ballast))
    )
    # The light falls off toward the far corner (after step 8 only a little is left), and noise.
    light = 1.0 - 0.10 * (xx / LENGTH) * (yy / WIDTH)
    picture = picture * light[..., None] + rng.standard_normal((h, w, 3)).astype(np.float32) * 3
    return np.clip(picture, 0, 255).astype(np.uint8), regions
