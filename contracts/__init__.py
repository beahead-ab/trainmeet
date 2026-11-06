"""TrainMeet's contracts: the only way between the parts.

No part imports another part's inner code; they share these models and the JSON Schemas
generated from them (contracts/schemas). TKL, CAD, TrainMeet Catalog and the apps read the
schemas; the Hub's Python parts import the models.

Step 1, part 1: the meet package (trainmeet.meet/1) and a station's outside
(trainmeet.station-outside/1). Part 2 adds the station and terminal protocols and Drift's API.
"""

from contracts.common import canonical_json, checksum
from contracts.meet import MeetPackage
from contracts.station_outside import StationOutside

__all__ = ["MeetPackage", "StationOutside", "canonical_json", "checksum"]
