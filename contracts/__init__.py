"""TrainMeet's contracts: the only way between the parts.

No part imports another part's inner code; they share these models and the JSON Schemas
generated from them (contracts/schemas). TKL, CAD, TrainMeet Catalog and the apps read the
schemas; the Hub's Python parts import the models.

The meet package (trainmeet.meet/1), a station's outside (trainmeet.station-outside/1), the
station protocol (trainmeet.station/1), the terminal protocol (the 16×2 profile), Drift's API
(trainmeet.drift/1) and Planering's draft and import (trainmeet.planning/1). Synk and the
drivers' API are sketches in SKISSER.md.
"""

from contracts.common import canonical_json, checksum
from contracts.meet import MeetPackage
from contracts.station_outside import StationOutside

__all__ = ["MeetPackage", "StationOutside", "canonical_json", "checksum"]
