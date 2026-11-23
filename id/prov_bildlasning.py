"""Provet av bildläsningen med den riktiga nyckeln (#79, TOKEN-28, TK14, CAD19).

    python -m id.prov_bildlasning
    python -m id.prov_bildlasning --nyckelfil /tmp/trainmeet_bedrock-key

Läser en syntetisk bild med TrainMeets AI genom mätarens egen väg (id/meter.py, BedrockClaude):
en avskrift med bildläsningens modell (Claude Sonnet 5.5 med EU-profilen) och en svår fråga med
fasta svar med CAD:s modell för svåra frågor (Claude Opus 5.5 med EU-profilen), båda från
Stockholm. Nyckeln är filen som ID_METER_KEY_FILE pekar på (eller --nyckelfil), med nyckelns id
och hemligheten på var sin rad, som jobbet "Testmiljön" skriver den till ID:s valv.

För varje fråga skrivs modellen ut, om svaret var det väntade, tokens in och ut och vad det kostade
ungefär. Nekar AWS skrivs AWS:s feltyp och förklaring ut, med kontots nummer bortsuddat, så att
det syns vilken modell eller region som saknas i nyckelns policy. Nyckeln skrivs aldrig ut.

Bilden ritas här, med bara standardbiblioteket: fyra siffror och en fylld ruta till höger om dem.
Den visar ingenting verkligt och ingen person.

Programmet körs aldrig av testerna. I GitHub körs det bara av jobbet "Prov av bildläsningen"
(.github/workflows/prov-bildlasning.yml), när någon startar det för hand: i ID:s container i
testmiljön, med nyckeln i valvet, eller hos GitHub med nyckeln i repots hemligheter. Det kostar
riktiga pengar hos AWS, några cent, men drar inga TrainMeet-tokens och rör ingen databas.

I testmiljön, på servern:

    docker compose exec -T id-api python -m id.prov_bildlasning
"""

from __future__ import annotations

import argparse
import base64
import os
import re
import struct
import sys
import zlib
from dataclasses import dataclass

import httpx

from id.meter import BedrockClaude, ClaudeRead, MeterFailed, settings_from

DIGITS = "4071"
"""What the picture shows: Claude's transcription is right when it is these four digits."""

FONT: dict[str, tuple[str, ...]] = {
    # Five by seven pixels a digit, enough for the four in the picture.
    "0": ("01110", "10001", "10011", "10101", "11001", "10001", "01110"),
    "1": ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    "4": ("00010", "00110", "01010", "10010", "11111", "00010", "00010"),
    "7": ("11111", "00001", "00010", "00100", "01000", "01000", "01000"),
}
SCALE = 12
MARGIN = 48
GAP = 2  # font pixels between digits
SQUARE = 6  # font pixels


@dataclass(frozen=True)
class Fraga:
    """One question to TrainMeets AI about the picture, and the answer that is right."""

    namn: str
    prompt: str
    max_tokens: int
    hard: bool
    ratt: str


FRAGOR = (
    Fraga(
        namn="Avskrift",
        prompt="Skriv av siffrorna i bilden. Svara bara med siffrorna, utan mellanslag.",
        max_tokens=256,
        hard=False,
        ratt=DIGITS,
    ),
    Fraga(
        # As CAD's hard questions (CAD18, CAD19): fixed answers, where the code was unsure.
        namn="Svår fråga",
        prompt=(
            "Ligger den fyllda svarta rutan till vänster eller till höger om siffrorna? "
            "Svara med ett enda ord: vänster eller höger."
        ),
        max_tokens=64,
        hard=True,
        ratt="höger",
    ),
)


def picture() -> bytes:
    """A grey-scale PNG: the digits in black on white, and a filled square to their right."""
    columns = len(DIGITS) * 5 + (len(DIGITS) - 1) * GAP + 2 * GAP + SQUARE
    width = columns * SCALE + 2 * MARGIN
    height = 7 * SCALE + 2 * MARGIN
    black: set[tuple[int, int]] = set()
    left = 0
    for digit in DIGITS:
        for row, line in enumerate(FONT[digit]):
            for column, pixel in enumerate(line):
                if pixel == "1":
                    black.add((left + column, row))
        left += 5 + GAP
    left += GAP
    top = (7 - SQUARE) // 2
    for row in range(top, top + SQUARE):
        for column in range(left, left + SQUARE):
            black.add((column, row))
    rows = bytearray()
    for y in range(height):
        rows.append(0)  # no filter
        for x in range(width):
            inside = MARGIN <= x < width - MARGIN and MARGIN <= y < height - MARGIN
            spot = ((x - MARGIN) // SCALE, (y - MARGIN) // SCALE)
            rows.append(0 if inside and spot in black else 255)
    header = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(bytes(rows), 9))
        + _chunk(b"IEND", b"")
    )


def _chunk(kind: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + kind
        + data
        + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    )


@dataclass
class Svar:
    """What AWS last answered when it did not answer 200: the error's type and message."""

    status: int = 0
    typ: str = ""
    meddelande: str = ""


def _record(seen: Svar, transport: httpx.BaseTransport | None = None) -> httpx.Client:
    """The meter's own HTTP client, which also notes AWS's refusal, so that the trial can say
    which model or region the key's policy lacks. The meter itself only logs the status."""

    def hook(response: httpx.Response) -> None:
        if response.status_code == 200:
            return
        response.read()
        seen.status = response.status_code
        seen.typ = response.headers.get("x-amzn-errortype", "").split(":")[0]
        try:
            message = response.json().get("message") or response.json().get("Message") or ""
        except ValueError:
            message = response.text
        seen.meddelande = _hidden(str(message))[:400]

    return httpx.Client(timeout=120.0, event_hooks={"response": [hook]}, transport=transport)


def _hidden(text: str) -> str:
    """AWS names the account's number in a refusal: it is never printed."""
    return re.sub(r"\b\d{12}\b", "<kontot>", text)


def _ratt(svar: str, ratt: str) -> bool:
    return svar.strip().strip(".").replace(" ", "").lower() == ratt


def main(argv: list[str] | None = None, *, transport: httpx.BaseTransport | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m id.prov_bildlasning", description=__doc__.split("\n\n")[0]
    )
    parser.add_argument("--nyckelfil", default=None, help="i stället för ID_METER_KEY_FILE")
    # Claude Sonnet 5.5's list prices; Opus 5.5 costs ID_METER_HARD_FACTOR times as much, and
    # the EU profile ID_METER_PROFILE_FACTOR more (TK14, CAD19).
    parser.add_argument("--in-usd", type=float, default=2.0, help="dollar per miljon tokens in")
    parser.add_argument("--ut-usd", type=float, default=10.0, help="dollar per miljon tokens ut")
    args = parser.parse_args(argv)

    env = dict(os.environ)
    if args.nyckelfil:
        env["ID_METER_KEY_FILE"] = args.nyckelfil
    settings = settings_from(env)
    if settings is None:
        print("Nyckeln saknas: ID_METER_KEY_FILE pekar inte på en fil.", file=sys.stderr)
        return 2
    seen = Svar()
    claude = BedrockClaude(settings, http=_record(seen, transport))
    image = base64.standard_b64encode(picture()).decode("ascii")
    print(f"Region: {settings.region} (EU-profilerna skickar vidare inom EU)")

    failed = 0
    total = 0.0
    for fraga in FRAGOR:
        model = settings.hard_model if fraga.hard else settings.model
        print(f"\n{fraga.namn}: {model}")
        seen.status = 0
        try:
            read: ClaudeRead = claude.read(
                fraga.prompt, [("image/png", image)], fraga.max_tokens, hard=fraga.hard
            )
        except MeterFailed as error:
            failed += 1
            print(f"Gick inte: {error}", file=sys.stderr)
            if seen.status:
                print(f"AWS: {seen.typ or 'fel'} {seen.status}: {seen.meddelande}", file=sys.stderr)
            continue
        factor = settings.profile_factor * (settings.hard_factor if fraga.hard else 1.0)
        usd = (read.input_tokens * args.in_usd + read.output_tokens * args.ut_usd) / 1e6 * factor
        total += usd
        right = _ratt(read.text, fraga.ratt)
        print(f"Svar: {read.text.strip()[:40]!r} ({'rätt' if right else 'väntade ' + fraga.ratt})")
        print(f"Tokens in: {read.input_tokens}")
        print(f"Tokens ut: {read.output_tokens}")
        print(f"Kostnad ungefär: {usd:.4f} dollar")
        if not right:
            failed += 1
    print(f"\nTotalt ungefär {total:.4f} dollar. {len(FRAGOR) - failed} av {len(FRAGOR)} rätt.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
