"""Egen AI (4c2, H58, H59, H70): the AI service the hub is connected to, used only to transcribe
what is not text (IMPORT-15). Code and the rulebook interpret what it wrote.

Two formats: the ordinary chat API (POST {address}/chat/completions, TK4) and Claude's own
(POST {address}/v1/messages), since Claude's compatibility with the standard is only for trying
out (H59). When the service is connected the hub checks that the model can read an image: it
sends a picture of a number it has just drawn and asks which number it is (H70).

The key is sent to the service and nowhere else. It is never part of an error, a log line or an
answer from the hub (H58).
"""

from __future__ import annotations

import base64
import json
import secrets
import struct
import urllib.error
import urllib.request
import zlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, Literal
from urllib.parse import urlsplit

Format = Literal["chat", "claude"]
CLAUDE_VERSION: Final = "2023-06-01"
TIMEOUT: Final = 120.0
MAX_TOKENS: Final = 4096
PROBE: Final = "Vilket tal står i bilden? Svara bara med siffrorna."

# Each digit drawn on a 3 × 5 grid, a row at a time.
DIGITS: Final = {
    "0": ("111", "101", "101", "101", "111"),
    "1": ("010", "110", "010", "010", "111"),
    "2": ("111", "001", "111", "100", "111"),
    "3": ("111", "001", "111", "001", "111"),
    "4": ("101", "101", "111", "001", "001"),
    "5": ("111", "100", "111", "001", "111"),
    "6": ("111", "100", "111", "101", "111"),
    "7": ("111", "001", "010", "010", "010"),
    "8": ("111", "101", "111", "101", "111"),
    "9": ("111", "101", "111", "001", "111"),
}


class AiError(Exception):
    """The service could not be used. The message is for the planner and never holds the key."""


@dataclass(frozen=True)
class Service:
    format: Format
    address: str
    model: str
    key: str = field(repr=False)


@dataclass(frozen=True)
class Image:
    media_type: str
    data: bytes = field(repr=False)


Send = Callable[[urllib.request.Request, float], bytes]


def _send(request: urllib.request.Request, timeout: float) -> bytes:
    with urllib.request.urlopen(request, timeout=timeout) as answer:
        body: bytes = answer.read()
        return body


def check_address(address: str) -> str:
    """The service's address without a slash at the end; http or https only."""
    parts = urlsplit(address.strip())
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise AiError("Adressen ska börja med https:// (eller http:// för en egen server).")
    if parts.query or parts.fragment or parts.username or parts.password:
        raise AiError("Adressen ska vara bara tjänstens adress, utan frågor eller inloggning.")
    return address.strip().rstrip("/")


def ask(
    service: Service,
    prompt: str,
    images: Sequence[Image] = (),
    *,
    max_tokens: int = MAX_TOKENS,
    send: Send = _send,
) -> str:
    """The model's answer, as text. Raises AiError."""
    address = check_address(service.address)
    pictures = [(i.media_type, base64.b64encode(i.data).decode("ascii")) for i in images]
    if service.format == "claude":
        url = f"{address}/v1/messages"
        headers = {"x-api-key": service.key, "anthropic-version": CLAUDE_VERSION}
        content: list[dict[str, Any]] = [
            {"type": "image", "source": {"type": "base64", "media_type": kind, "data": data}}
            for kind, data in pictures
        ]
        content.append({"type": "text", "text": prompt})
    else:
        url = f"{address}/chat/completions"
        headers = {"Authorization": f"Bearer {service.key}"}
        content = [{"type": "text", "text": prompt}]
        content += [
            {"type": "image_url", "image_url": {"url": f"data:{kind};base64,{data}"}}
            for kind, data in pictures
        ]
    body = {
        "model": service.model,
        "max_tokens": max_tokens,
        "temperature": 0,
        "messages": [{"role": "user", "content": content}],
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Accept": "application/json", **headers},
        method="POST",
    )
    try:
        raw = send(request, TIMEOUT)
    except urllib.error.HTTPError as error:
        status = error.code
        error.close()  # the refusal's own body is never read: it can quote the key
        raise AiError(_refused(status)) from None
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise AiError("AI-tjänsten svarar inte på adressen.") from error
    try:
        answer = json.loads(raw)
        if service.format == "claude":
            text = "".join(
                part.get("text", "") for part in answer["content"] if part.get("type") == "text"
            )
        else:
            text = answer["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError, AttributeError) as error:
        raise AiError("AI-tjänsten svarade, men inte i det format som valts.") from error
    if not isinstance(text, str):
        raise AiError("AI-tjänsten svarade, men inte i det format som valts.")
    return text


def _refused(status: int) -> str:
    """What a refusal means, without the service's own words, which can quote the key."""
    if status in (401, 403):
        return "AI-tjänsten godtog inte nyckeln."
    if status == 404:
        return "AI-tjänsten känner inte adressen eller modellen."
    if status == 429:
        return "AI-tjänsten säger att det är för många frågor eller att taket är nått."
    if status == 400:
        return "AI-tjänsten förstod inte frågan. Kan modellen läsa bilder?"
    return f"AI-tjänsten svarade med fel {status}."


def probe(service: Service, *, send: Send = _send, number: str | None = None) -> None:
    """Check that the model reads images: a number the hub has just drawn, which the model
    must read back. Raises AiError."""
    wanted = number or "".join(secrets.choice("0123456789") for _ in range(3))
    answer = ask(service, PROBE, [Image("image/png", drawn(wanted))], max_tokens=20, send=send)
    if "".join(ch for ch in answer if ch.isdigit()) != wanted:
        raise AiError(
            "Modellen svarar, men läste inte talet i provbilden. Välj en modell som kan läsa "
            "bilder."
        )


def drawn(number: str, scale: int = 12) -> bytes:
    """A PNG with the number in large black digits on white: the probe's picture."""
    gap = 1
    width = (len(number) * (3 + gap) + gap) * scale
    height = 7 * scale
    rows = []
    for y in range(height):
        cell_y = y // scale - 1
        line = bytearray(b"\x00")  # filter type none
        for x in range(width):
            cell_x = x // scale - gap
            index, column = divmod(cell_x, 3 + gap)
            black = (
                0 <= cell_y < 5
                and 0 <= index < len(number)
                and column < 3
                and cell_x >= 0
                and DIGITS[number[index]][cell_y][column] == "1"
            )
            line.append(0 if black else 255)
        rows.append(bytes(line))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)  # 8-bit greyscale
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(b"".join(rows), 9))
        + chunk(b"IEND", b"")
    )
