"""Källsidorna: Catalog reads the page a citation points to, itself, to see the value further on
than the search's short excerpt (#53 del b, CAT-169, förslag 22 november).

Claude's web search gives at most about 150 characters of the passage it cites (cited_text), and
in a table the value often stands further in: DB Cargo's speed, year and brake, Wikipedia's
infobox. Catalog then reads the page from its own server in the EU, without AI and without
tokens, and catalog/evidence.py looks for the value in the page's text from the cited words on.
Only a page the real search found is read (CAT-167): the addresses come from the evidence check,
which has already refused every other.

Only open web pages are read, and nothing of the person goes with the request:

- http or https on the usual ports, an address that safe_url() takes (no login, no IP number, no
  local name), and at most three redirects, each checked the same way.
- The name must resolve to public addresses only, and the connection is made to the address that
  was checked (_Guarded), so that a name cannot turn into an address inside the network between
  the check and the request. No proxy from the environment.
- At most 3 MB, HTML, plain text or PDF. A PDF's text is read with pdfminer in a process of its
  own, at most 20 pages and 20 seconds, as the hub reads its PDFs (DRIFT-20).
- At most 6 pages per search, 4 at a time, 20 seconds for each.

A page that cannot be read is no evidence: the value is dropped as before, never kept.
"""

from __future__ import annotations

import ipaddress
import logging
import re
import socket
import time
from collections.abc import Iterable, Sequence
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass
from html.parser import HTMLParser
from io import BytesIO
from multiprocessing import get_context
from threading import Lock
from typing import Final, Protocol
from urllib.parse import urljoin

import httpcore
import httpx

from catalog.publishers import safe_url

LOGGER = logging.getLogger("catalog.source_pages")

MOST_PAGES: Final = 6
"""Pages read for one search: the cited ones whose excerpt was too short, the first ones."""
AT_ONCE: Final = 4
SECONDS: Final = 10.0
"""For one page: to connect, and between two parts of the answer."""
WHOLE_SECONDS: Final = 20.0
"""For one page from the first request to the last byte, redirects included."""
MOST_BYTES: Final = 3_000_000
MOST_REDIRECTS: Final = 3
MOST_TEXT: Final = 400_000
"""Characters of text kept from one page."""
PDF_PAGES: Final = 20
PDF_SECONDS: Final = 20.0
KINDS: Final = frozenset({"text/html", "application/xhtml+xml", "text/plain", "application/pdf"})
AGENT: Final = "TrainMeetCatalog/1.0 (+https://platform.trainmeet.app)"
"""Who reads: the app, never the person who searched."""


class SourcePages(Protocol):
    def read(self, urls: Sequence[str]) -> dict[str, str]:
        """The text of each page that could be read, by its address. Never raises."""
        ...


# --- Only open web pages ------------------------------------------------------------------------


def _public(address: str) -> bool:
    ip = ipaddress.ip_address(address.split("%", 1)[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def public_addresses(host: str, port: int) -> list[str]:
    """The addresses the name resolves to, IPv4 first, if every one of them is public. Raises
    httpcore.ConnectError otherwise: a name that points into a network, even beside a public
    address, is not read."""
    try:
        found = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (OSError, UnicodeError) as error:
        raise httpcore.ConnectError("Namnet finns inte.") from error
    addresses = list(dict.fromkeys(str(each[4][0]) for each in found))
    if not addresses or not all(_public(each) for each in addresses):
        raise httpcore.ConnectError("Adressen är inte en öppen webbsida.")
    return sorted(addresses, key=lambda each: ":" in each)


class _Guarded(httpcore.SyncBackend):
    """Connects to an address that public_addresses() has checked, never to the name again."""

    def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.NetworkStream:
        last: Exception | None = None
        for address in public_addresses(host, port):
            try:
                return super().connect_tcp(address, port, timeout, local_address, socket_options)
            except httpcore.ConnectError as error:
                last = error
        raise httpcore.ConnectError("Sidan svarar inte.") from last


class _GuardedTransport(httpx.HTTPTransport):
    def __init__(self) -> None:
        super().__init__(retries=0)
        self._pool = httpcore.ConnectionPool(
            ssl_context=httpx.create_ssl_context(),
            max_connections=AT_ONCE,
            network_backend=_Guarded(),
        )


# --- A page's text -------------------------------------------------------------------------------

_SKIPPED: Final = frozenset({"script", "style", "noscript", "template", "svg", "head", "iframe"})
_BLOCKS: Final = frozenset(
    {
        "p", "div", "section", "article", "main", "aside", "header", "footer", "nav", "ul", "ol",
        "li", "dl", "dt", "dd", "table", "thead", "tbody", "tfoot", "tr", "caption", "h1", "h2",
        "h3", "h4", "h5", "h6", "pre", "blockquote", "figure", "figcaption", "form", "hr",
    }
)  # fmt: skip


class _Text(HTMLParser):
    """The visible words of a page in their order. A table's cells in a row stand with the middle
    dot between them, Maximum speed (km/h) · 120, as a search's own excerpts show them."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skipping = 0
        self.first_cell = True

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIPPED:
            self.skipping += 1
        elif tag in ("td", "th"):
            self.parts.append(" " if self.first_cell else " · ")
            self.first_cell = False
        elif tag == "br":
            self.parts.append("\n")
        elif tag in _BLOCKS:
            self.parts.append("\n")
            if tag == "tr":
                self.first_cell = True

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "br":
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIPPED:
            self.skipping = max(0, self.skipping - 1)
        elif tag in _BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skipping:
            self.parts.append(data)

    def text(self) -> str:
        lines = (" ".join(line.split()) for line in "".join(self.parts).split("\n"))
        return "\n".join(line for line in lines if line)


def html_text(page: str) -> str:
    parser = _Text()
    try:
        parser.feed(page)
        parser.close()
    except (AssertionError, ValueError):  # a page broken beyond what the parser forgives
        pass
    return parser.text()[:MOST_TEXT]


def _pdf_text(data: bytes) -> str:
    """In the reading process: the first pages' text, with pdfminer."""
    from pdfminer.high_level import extract_text

    return str(extract_text(BytesIO(data), maxpages=PDF_PAGES))


_pool: ProcessPoolExecutor | None = None
_pool_lock = Lock()


def pdf_text(data: bytes) -> str | None:
    """A PDF's text, read in a process of its own, or None when it cannot be read in time."""
    global _pool
    if not data.startswith(b"%PDF-"):
        return None
    with _pool_lock:
        if _pool is None:
            _pool = ProcessPoolExecutor(max_workers=1, mp_context=get_context("spawn"))
        pool = _pool
    try:
        text = pool.submit(_pdf_text, data).result(timeout=PDF_SECONDS)
    except TimeoutError:
        LOGGER.warning("En källas PDF tog mer än %d sekunder att läsa", int(PDF_SECONDS))
        _stop(pool)
        return None
    except BrokenProcessPool:
        _stop(pool)
        return None
    except Exception:  # pdfminer's own errors: a broken PDF is no evidence
        return None
    return text[:MOST_TEXT]


def _stop(pool: ProcessPoolExecutor) -> None:
    global _pool
    with _pool_lock:
        if _pool is pool:
            _pool = None
    for process in list(getattr(pool, "_processes", {}).values()):
        process.terminate()
    pool.shutdown(wait=False, cancel_futures=True)


_CHARSET: Final = re.compile(rb"""<meta[^>]+charset=["']?([\w-]+)""", re.IGNORECASE)


def _decoded(data: bytes, declared: str | None) -> str:
    named = declared
    if named is None and (meta := _CHARSET.search(data[:4096])) is not None:
        named = meta[1].decode("ascii")
    for encoding in (named, "utf-8", "cp1252"):
        if not encoding:
            continue
        try:
            return data.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return data.decode("utf-8", errors="replace")


# --- Reading -------------------------------------------------------------------------------------


@dataclass
class WebPages:
    """The pages, read from Catalog's own server."""

    seconds: float = SECONDS
    transport: httpx.BaseTransport | None = None

    def _client(self) -> httpx.Client:
        return httpx.Client(
            transport=self.transport or _GuardedTransport(),
            timeout=httpx.Timeout(self.seconds),
            follow_redirects=False,
            trust_env=False,
            headers={
                "user-agent": AGENT,
                "accept": "text/html,application/xhtml+xml,text/plain,application/pdf;q=0.9",
            },
        )

    def read(self, urls: Sequence[str]) -> dict[str, str]:
        wanted = list(dict.fromkeys(url for url in urls if safe_url(url) == url))[:MOST_PAGES]
        if not wanted:
            return {}
        with self._client() as client, ThreadPoolExecutor(max_workers=AT_ONCE) as threads:
            texts = list(threads.map(lambda url: self.text(client, url), wanted))
        return {url: text for url, text in zip(wanted, texts, strict=True) if text}

    def text(self, client: httpx.Client, url: str) -> str | None:
        """One page's text, or None. Never raises: an unreadable page is no evidence."""
        try:
            return self._text(client, url)
        except (httpx.HTTPError, httpcore.ConnectError, OSError, ValueError) as error:
            LOGGER.info("En källa gick inte att läsa: %s", type(error).__name__)
            return None

    def _text(self, client: httpx.Client, url: str) -> str | None:
        address = url
        until = time.monotonic() + WHOLE_SECONDS
        for _ in range(MOST_REDIRECTS + 1):
            with client.stream("GET", address) as answer:
                if answer.is_redirect:
                    following = safe_url(urljoin(address, answer.headers.get("location", "")))
                    if following is None:
                        return None
                    address = following
                    continue
                if answer.status_code != 200:
                    return None
                kind = answer.headers.get("content-type", "").split(";")[0].strip().lower()
                if kind not in KINDS:
                    return None
                data = bytearray()
                for piece in answer.iter_bytes():
                    data += piece
                    if len(data) > MOST_BYTES or time.monotonic() > until:
                        return None
                if kind == "application/pdf":
                    return pdf_text(bytes(data))
                text = _decoded(bytes(data), answer.charset_encoding)
                return html_text(text) if kind != "text/plain" else text[:MOST_TEXT]
        return None
