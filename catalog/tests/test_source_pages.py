"""Källsidorna (catalog/source_pages.py, CAT-169): Catalog reads a cited page itself, and only an
open web page. No network: the answers are made up here, and the names resolve as the tests say.
"""

from __future__ import annotations

import socket
from collections.abc import Callable
from typing import Any

import httpcore
import httpx
import pytest

from catalog import source_pages
from catalog.source_pages import (
    AGENT,
    MOST_BYTES,
    MOST_PAGES,
    WebPages,
    html_text,
    pdf_text,
    public_addresses,
)

PAGE = "https://www.example.org/vagnar/hbis"


def resolving(*addresses: str) -> Callable[..., list[Any]]:
    def getaddrinfo(host: str, port: int, *args: Any, **kwargs: Any) -> list[Any]:
        return [
            (
                socket.AF_INET6 if ":" in each else socket.AF_INET,
                socket.SOCK_STREAM,
                6,
                "",
                (each, port),
            )
            for each in addresses
        ]

    return getaddrinfo


@pytest.mark.parametrize(
    "addresses",
    [
        ("10.0.0.5",),
        ("127.0.0.1",),
        ("169.254.42.42",),  # the cloud's own metadata
        ("192.168.1.10",),
        ("100.64.0.1",),
        ("::1",),
        ("fd00::1",),
        ("::ffff:10.0.0.1",),
        ("93.184.215.14", "10.0.0.5"),  # a public address beside an inner one is not enough
        (),
    ],
)
def test_a_name_that_points_into_a_network_is_never_read(
    monkeypatch: pytest.MonkeyPatch, addresses: tuple[str, ...]
) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", resolving(*addresses))
    with pytest.raises(httpcore.ConnectError):
        public_addresses("www.example.org", 443)


def test_a_public_name_is_connected_to_at_the_address_that_was_checked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", resolving("2606:2800:21f::1", "93.184.215.14"))
    assert public_addresses("www.example.org", 443) == ["93.184.215.14", "2606:2800:21f::1"]
    connected: list[str] = []

    def connect(self: Any, host: str, port: int, *args: Any) -> Any:
        connected.append(host)
        raise httpcore.ConnectError("no network in the tests")

    monkeypatch.setattr(httpcore.SyncBackend, "connect_tcp", connect)
    with pytest.raises(httpcore.ConnectError):
        source_pages._Guarded().connect_tcp("www.example.org", 443)
    assert connected == ["93.184.215.14", "2606:2800:21f::1"], "never the name itself"

    monkeypatch.setattr(socket, "getaddrinfo", resolving("10.0.0.5"))
    connected.clear()
    with pytest.raises(httpcore.ConnectError):
        source_pages._Guarded().connect_tcp("www.example.org", 443)
    assert connected == [], "an inner address is never connected to"


def test_the_pages_are_read_without_a_proxy_from_the_environment() -> None:
    with WebPages()._client() as client:
        assert not client._mounts, "no proxy: the name would be resolved where it cannot be checked"
        assert client.headers["user-agent"] == AGENT
        assert not client.follow_redirects, "every redirect is checked here"


def test_a_tables_cells_stand_with_the_middle_dot_and_scripts_are_left_out() -> None:
    page = """<html><head><title>Hbis</title><style>td{color:red}</style></head><body>
    <script>var speed = 999;</script><h1>Hbis-tt&nbsp;293</h1>
    <table><tr><th>Maximum speed (km/h)</th><td>120</td></tr>
    <tr><th>First year of delivery</th><td>1976</td></tr></table>
    <p>Bremse &amp; mehr<br>KE-GP-A</p></body></html>"""
    assert html_text(page) == (
        "Hbis-tt 293\nMaximum speed (km/h) · 120\nFirst year of delivery · 1976\n"
        "Bremse & mehr\nKE-GP-A"
    )


def _pdf(text: str) -> bytes:
    """A one-page PDF with the text on it, written by hand."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return bytes(out)


def test_a_pdfs_text_is_read_in_a_process_of_its_own() -> None:
    text = pdf_text(_pdf("Length over buffers 15.500 mm"))
    assert text is not None and "Length over buffers 15.500 mm" in text
    assert pdf_text(b"<html>not a pdf</html>") is None


Handler = Callable[[httpx.Request], httpx.Response]


def pages(handler: Handler) -> tuple[WebPages, list[str]]:
    asked: list[str] = []

    def answer(request: httpx.Request) -> httpx.Response:
        asked.append(str(request.url))
        return handler(request)

    return WebPages(transport=httpx.MockTransport(answer)), asked


def html(body: str, status: int = 200, **headers: str) -> httpx.Response:
    return httpx.Response(
        status, headers={"content-type": "text/html; charset=utf-8", **headers}, text=body
    )


def test_a_cited_page_is_read_to_its_text() -> None:
    reader, asked = pages(lambda request: html("<p>Maximum speed (km/h)</p><p>120</p>"))
    assert reader.read([PAGE]) == {PAGE: "Maximum speed (km/h)\n120"}
    assert asked == [PAGE]


def test_a_redirect_is_followed_only_to_an_open_web_page() -> None:
    def answer(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/vagnar/hbis":
            return httpx.Response(301, headers={"location": "/en/vagnar/hbis"})
        if request.url.path == "/en/vagnar/hbis":
            return html("<p>Speed 120 km/h</p>")
        return html("", 404)

    reader, asked = pages(answer)
    assert reader.read([PAGE]) == {PAGE: "Speed 120 km/h"}
    assert asked == [PAGE, "https://www.example.org/en/vagnar/hbis"]

    def away(to: str) -> Handler:
        return lambda request: httpx.Response(302, headers={"location": to})

    for inside in ("http://127.0.0.1/admin", "http://catalog-db:5432/", "https://id.local/x"):
        reader, asked = pages(away(inside))
        assert reader.read([PAGE]) == {}
        assert asked == [PAGE], f"{inside} is never asked"

    reader, asked = pages(lambda request: httpx.Response(302, headers={"location": PAGE}))
    assert reader.read([PAGE]) == {}
    assert len(asked) == source_pages.MOST_REDIRECTS + 1, "and only a few times"


@pytest.mark.parametrize(
    "answer",
    [
        html("", 404),
        html("", 500),
        httpx.Response(200, headers={"content-type": "image/png"}, content=b"\x89PNG"),
        httpx.Response(
            200, headers={"content-type": "text/plain"}, content=b"x" * (MOST_BYTES + 1)
        ),
    ],
)
def test_a_page_that_cannot_be_read_is_no_text(answer: httpx.Response) -> None:
    reader, _ = pages(lambda request: answer)
    assert reader.read([PAGE]) == {}


def test_an_unreachable_page_is_no_text_and_no_error() -> None:
    def answer(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    reader, _ = pages(answer)
    assert reader.read([PAGE]) == {}


def test_only_safe_addresses_and_only_a_few_pages_are_read() -> None:
    reader, asked = pages(lambda request: html("<p>text</p>"))
    many = [f"https://www.example.org/sida/{number}" for number in range(MOST_PAGES + 3)]
    unsafe = ["http://localhost/x", "https://10.0.0.5/x", "ftp://www.example.org/x"]
    found = reader.read(unsafe + many + many[:2])
    assert sorted(asked) == sorted(many[:MOST_PAGES])
    assert set(found) == set(many[:MOST_PAGES])


def test_a_page_in_another_encoding_is_read_by_its_own_word() -> None:
    body = "<meta charset='iso-8859-1'><p>Längd över buffertar 14 020 mm</p>".encode("latin-1")
    reader, _ = pages(
        lambda request: httpx.Response(200, headers={"content-type": "text/html"}, content=body)
    )
    assert reader.read([PAGE]) == {PAGE: "Längd över buffertar 14 020 mm"}
