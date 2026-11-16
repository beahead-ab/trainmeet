"""A stand-in for an AI service, for the tests: a small HTTP server on this machine that talks
the ordinary chat API and Claude's own, as the real ones do. It reads the hub's probe picture by
drawing every number until one matches, and answers other pictures from a table the test gives,
by the picture's sha256. Nothing leaves the machine and no key is real."""

from __future__ import annotations

import base64
import hashlib
import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from integrationer.ai import drawn

KEY = "test-key-not-real"


@dataclass
class FakeAi:
    """What the service knows and what it was asked."""

    # sha256 of a picture: the answer. Never a picture the hub's probe could draw (three digits
    # at drawn()'s own scale), or the probe gets that answer instead of its number.
    answers: dict[str, str] = field(default_factory=dict)
    blind: bool = False  # a model that cannot read pictures
    asked: list[dict[str, Any]] = field(default_factory=list)
    address: str = ""

    def read(self, picture: bytes) -> str:
        digest = hashlib.sha256(picture).hexdigest()
        if digest in self.answers:
            return self.answers[digest]
        if self.blind:
            return "Jag kan inte se bilder."
        for n in range(1000):
            if drawn(f"{n:03d}") == picture:
                return f"{n:03d}"
        return "Jag ser ingen tabell."


@contextmanager
def serving(given: FakeAi | None = None) -> Iterator[FakeAi]:
    fake = given or FakeAi()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:  # quiet in the tests
            return

        def do_POST(self) -> None:
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            claude = self.path == "/v1/messages"
            key = (
                self.headers.get("x-api-key")
                if claude
                else self.headers.get("Authorization", "").removeprefix("Bearer ")
            )
            if self.path not in ("/v1/messages", "/chat/completions"):
                return self.reply(404, {"error": "no such path"})
            if key != KEY:
                # A real service quotes part of the key; the hub must never pass it on.
                return self.reply(401, {"error": {"message": f"Incorrect API key: {key}"}})
            fake.asked.append({"path": self.path, "body": body})
            pictures = []
            for part in body["messages"][0]["content"]:
                if part["type"] == "image":
                    pictures.append(base64.b64decode(part["source"]["data"]))
                elif part["type"] == "image_url":
                    pictures.append(base64.b64decode(part["image_url"]["url"].split(",", 1)[1]))
            text = " ".join(fake.read(p) for p in pictures) or "Hej."
            if claude:
                return self.reply(200, {"content": [{"type": "text", "text": text}]})
            return self.reply(200, {"choices": [{"message": {"content": text}}]})

        def reply(self, status: int, body: dict[str, Any]) -> None:
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    fake.address = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        yield fake
    finally:
        server.shutdown()
        server.server_close()
