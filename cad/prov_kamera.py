"""Skriver en låtsad kamera för webbläsarprovet av CAD i mobilen (#90).

    python -m cad.prov_kamera kamera.mjpeg [--bilder 4]

Chrome kan ta kamerans bild ur en fil (--use-fake-device-for-media-stream och
--use-file-for-fake-video-capture=<fil>.mjpeg). Filen är det syntetiska stationsfotot ur
bildkedjans egen renderare (cad/bildkedjan/syntetisk.py, scenen station), 3200 × 2400 bildpunkter
som en telefon som håller sig stilla över modulens mitt, i jämnt ljus, utan kamerans data: några
lika JPEG-bilder efter varandra (Motion JPEG). Den långa sidan är över 3 000 bildpunkter, så att
slutbilden har full upplösning också där ImageCapture inte finns. Nothing here is a real station.
"""

from __future__ import annotations

import argparse
import io
from pathlib import Path

from PIL import Image

from cad.bildkedjan import syntetisk

SIZE = (3200, 2400)


def frame() -> bytes:
    """One frame: the station from above, as the phone sees it, as a plain JPEG."""
    photo = syntetisk.take(
        syntetisk.station_scene(), syntetisk.Shot(size=SIZE, fill=0.86, shadow=False)
    )
    picture = io.BytesIO()
    Image.fromarray(photo.pixels).save(picture, format="JPEG", quality=90)
    return picture.getvalue()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("fil", type=Path, help="kameran som Motion JPEG, t.ex. kamera.mjpeg")
    parser.add_argument("--bilder", type=int, default=4, help="hur många lika bilder")
    args = parser.parse_args(argv)
    one = frame()
    args.fil.write_bytes(one * max(1, args.bilder))


if __name__ == "__main__":
    main()
