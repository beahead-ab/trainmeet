"""Glömd PIN (H46, SYNK-27): a new PIN with physical access to the hub, also without internet.

On the Pi, or in the hub's container:

    python -m hub.pin

asks for the new PIN twice and sets it. The other way is a file on a USB stick: a file named
trainmeet-ny-pin.txt with the new PIN on its first line. The hub takes it within a few seconds
of the stick being in, removes the file so the PIN is not left on the stick, and leaves
trainmeet-pin-klar.txt with the time, or trainmeet-pin-fel.txt with why not. Either way every
login ends, and the name, the meets and everything else stay. The PIN is never written out.
"""

from __future__ import annotations

import getpass
import logging
import sys
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from hub import provbanan
from hub.local import InvalidSetup, LocalLogin, NotSetUp

FILE: Final = "trainmeet-ny-pin.txt"
DONE: Final = "trainmeet-pin-klar.txt"
FAILED: Final = "trainmeet-pin-fel.txt"
LOGGER = logging.getLogger("hub.pin")


def take_pin_file(usb: Path, login: LocalLogin) -> bool:
    """A new PIN from a file on the USB stick, if there is one. True when it was set."""
    path = usb / FILE
    try:
        if not path.is_file():
            return False
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        path.unlink()
    except OSError:
        return False
    stamp = datetime.now(UTC).astimezone().strftime("%Y-%m-%d %H:%M")
    try:
        login.reset_pin(lines[0].strip() if lines else "")
    except (InvalidSetup, NotSetUp) as error:
        reason = str(error) if isinstance(error, InvalidSetup) else "Hubben har ingen PIN än."
        _leave(usb / FAILED, f"{stamp}: PIN-koden byttes inte. {reason}\n")
        LOGGER.warning("En PIN-fil på USB-minnet gick inte att använda")
        return False
    _leave(usb / DONE, f"{stamp}: PIN-koden är bytt. Alla inloggningar har slutat gälla.\n")
    LOGGER.warning("PIN-koden byttes med en fil på USB-minnet")
    return True


def _leave(path: Path, text: str) -> None:
    with suppress(OSError):
        path.write_text(text, encoding="utf-8")


def main(ask: Callable[[str], str] = getpass.getpass, data_dir: Path | None = None) -> int:
    login = LocalLogin(
        (data_dir or provbanan.database_path(None).parent) / "hubben.sqlite3", "Hubben"
    )
    first = ask("Ny PIN-kod (6–12 siffror): ")
    if ask("Samma PIN-kod igen: ") != first:
        print("PIN-koderna var olika. Ingenting ändrades.", file=sys.stderr)
        return 1
    try:
        login.reset_pin(first)
    except InvalidSetup as error:
        print(f"{error} Ingenting ändrades.", file=sys.stderr)
        return 1
    except NotSetUp:
        print("Hubben har ingen PIN än. Välj en i webbläsaren.", file=sys.stderr)
        return 1
    print("PIN-koden är bytt. Alla inloggningar har slutat gälla.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
