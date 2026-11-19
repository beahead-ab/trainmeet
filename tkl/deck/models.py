"""Elgato's models and their grids (SD52, docs/tkl-streamdeck-modeller.md).

The grids are read from the library TKL will use for real decks (del b): keys in columns and
rows, the dials, the touch strip, the info line, the touch points and the pedals. A model TKL
does not know is described by its grid alone and gets the default for that grid (SD53).
Module 6, 15 and 32 and the older editions of the 15 get the profile of their size (SD54).
"""

from __future__ import annotations

from typing import Final

from contracts.tkl import DeckModelId, TklDeckGrid, TklDeckModel

M = DeckModelId

MODELS: Final[tuple[TklDeckModel, ...]] = (
    TklDeckModel(id=M.MINI, name="Mini", grid=TklDeckGrid(columns=3, rows=2), size=M.MINI),
    TklDeckModel(
        id=M.FIFTEEN, name="Stream Deck 15", grid=TklDeckGrid(columns=5, rows=3), size=M.FIFTEEN
    ),
    TklDeckModel(id=M.XL, name="XL", grid=TklDeckGrid(columns=8, rows=4), size=M.XL),
    TklDeckModel(
        id=M.NEO,
        name="Neo",
        grid=TklDeckGrid(columns=4, rows=2, info=True, touch=2),
        size=M.NEO,
    ),
    TklDeckModel(
        id=M.PLUS,
        name="+",
        grid=TklDeckGrid(columns=4, rows=2, dials=4, strip=True),
        size=M.PLUS,
    ),
    TklDeckModel(
        id=M.PLUS_XL,
        name="+ XL",
        grid=TklDeckGrid(columns=9, rows=4, dials=6, strip=True),
        size=M.PLUS_XL,
    ),
    TklDeckModel(
        id=M.STUDIO, name="Studio", grid=TklDeckGrid(columns=16, rows=2, dials=2), size=M.STUDIO
    ),
    TklDeckModel(id=M.MODULE_6, name="Module 6", grid=TklDeckGrid(columns=3, rows=2), size=M.MINI),
    TklDeckModel(
        id=M.MODULE_15,
        name="Module 15",
        grid=TklDeckGrid(columns=5, rows=3),
        size=M.FIFTEEN,
    ),
    TklDeckModel(id=M.MODULE_32, name="Module 32", grid=TklDeckGrid(columns=8, rows=4), size=M.XL),
    TklDeckModel(
        id=M.PEDAL, name="Pedal", grid=TklDeckGrid(columns=0, rows=0, pedals=3), size=M.PEDAL
    ),
)
BY_ID: Final = {m.id: m for m in MODELS}


def model_of(model: DeckModelId) -> TklDeckModel:
    return BY_ID[model]


def size_of(grid: TklDeckGrid) -> DeckModelId | None:
    """The known model with exactly this grid, if any: a deck that reports itself by its grid
    gets that model's profile (SD54)."""
    for found in MODELS:
        if found.grid == grid:
            return found.size
    return None
