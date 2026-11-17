"""TrainMeet TKL (KLAR-22): the station's own program, on its computer or a Raspberry Pi.

Level 0 is clearance only (TKL12, TKL21): the tracks and exits as a list, and the clearance
view with Tåg · Klarering · Händelser over the station protocol (TKL19). TKL only uses the
contracts; it never imports the hub's parts (tests/test_boundaries.py).
"""

VERSION = "0.1.0"
