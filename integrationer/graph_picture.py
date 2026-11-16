"""Grafen som bild (4c2, IMPORT-33, level 3): the train graph, written down by the hub's own AI.

What the graph is surest about is its axis: each line's stations in order, with their distance
where it is printed. The AI writes that down, and nothing else; code finds the places, gives
the draft the graph's lines (Graf) and confirms the sections that run between stations next to
each other on a line. The trains drawn in the graph are not read: the station lists give them.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Final

LEVEL: Final = 3
VERSION: Final = "graf-1"  # a new prompt is a new transcription
PROMPT: Final = """Bilden visar en grafisk tidtabell (en graf) för en modelljärnvägsträff: en
eller flera linjer, var och en med stationerna i ordning längs en axel och tågen som sneda
linjer. Skriv av axlarna, utan att tolka eller lägga till något, och skriv inte av tågen.

Svara bara med JSON, så här:
{"lines": [{"number": "linjens nummer, eller tomt", "name": "linjens namn, eller tomt",
            "stations": [{"label": "Mkd", "km": 0.0}, {"label": "Lek", "km": 1.2}, ...]}]}

En post per linje, med stationerna i den ordning de står längs axeln. label är signaturen eller
namnet som det står. km är avståndet som står vid stationen, eller null om inget står."""


class GraphError(ValueError):
    """The graph's transcription cannot be read. The message is for the planner."""


@dataclass
class Line:
    name: str
    number: str = ""
    stations: list[tuple[str, float | None]] = field(default_factory=list)


def lines(text: str) -> list[Line]:
    """The lines the AI wrote down. Raises GraphError."""
    match = re.search(r"\{.*\}", text, re.S)
    try:
        answer = json.loads(match[0] if match else text)
        found = []
        for item in answer["lines"]:
            stations = []
            for station in item["stations"]:
                label = str(station["label"]).strip()
                km = station.get("km")
                if label:
                    stations.append((label, float(km) if isinstance(km, int | float) else None))
            if len(stations) >= 2:
                name, number = (str(item.get(k) or "").strip() for k in ("name", "number"))
                found.append(Line(name, number, stations))
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        raise GraphError("AI:ns avskrift av grafen gick inte att läsa.") from error
    if not found:
        raise GraphError("AI:n hittade ingen linje med stationer i grafen.")
    return found
