"""For every test process: the hub that hub.app makes when it is imported keeps its files in a
folder of the process's own, not in the shared temporary folder, so that the processes of
"Tester" (pytest-xdist) and an earlier run never share a hub's databases. A folder named in
TRAINMEET_PREVIEW_DB is kept."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

if not os.environ.get("TRAINMEET_PREVIEW_DB"):
    os.environ["TRAINMEET_PREVIEW_DB"] = str(
        Path(tempfile.mkdtemp(prefix="trainmeet-prov-")) / "provbanan.sqlite3"
    )
