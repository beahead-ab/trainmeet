"""Fjärrstyrning i TKL (#36 del c): the remote interlocking and the fjärrbild.

TKL started in the remote role is a remote interlocking (fjärrställverk) with no station of its
own, run by the fjärrtågklarerare (FR1, TKL47). At first start TKL offers it next to the station;
the role, its name and its remote area are kept on the computer (roles.py). It connects as the
station protocol's client kind `remote`, with the plan's remote area or driftplatser written by
hand, waits for Trafikledningen's approval and keeps following it as TKL does (FR4).

A station's own TKL controls a neighbour with the same fjärrbild (FR3), as the same client: the
neighbour is in its snapshot's `controls` once it has taken the offer.

The fjärrbild is Hubben's Overview (contracts/station.py), drawn in the web app (apps/tkl): only
what the stations report, never what was sent (FR13). An offer is answered, a route from a
station's remote catalogue asked for and taken away, and a controlled station cleared, with
ordinary station commands; Hubben checks who asks and the catalogue, and the station's own
interlocking the safety (FR11, FR12, FR17).

Nothing here names a station (RS13).
"""

from __future__ import annotations

from tkl.fjarr.hub import areas, connect_request, picture, remote_id
from tkl.fjarr.roles import Roles

__all__ = ["Roles", "areas", "connect_request", "picture", "remote_id"]
