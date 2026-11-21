"""The reviewed list of publishers, and what a source's address may be (#53 del b, CAT-167,
CAT-168). Ported from TrainCatalog's catalog/research_provider.py: PRIMARY_PUBLISHERS,
publisher_kind and safe_url.

The web search's sources are classed against this small list, kept here and nowhere else. The
class is Catalog's own: the AI never says who a publisher is. Only the exact host counts, with
or without www: a subdomain, a mirror or an address that merely names a publisher does not
inherit its class. A class says who stands behind the page, never that a fact is right: the
excerpt must still hold the value (catalog/evidence.py), and a reviewer still approves.

A host is added here only after someone has looked at the publisher. Anything else is unknown,
and the reviewer sees that.
"""

from __future__ import annotations

import ipaddress
from typing import Final
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from contracts.catalog import PublisherKind

PUBLISHERS: Final[dict[str, PublisherKind]] = {
    # Builders of the vehicles, and of the models.
    "marklin.com": PublisherKind.MANUFACTURER,
    "maerklin.de": PublisherKind.MANUFACTURER,
    "roco.cc": PublisherKind.MANUFACTURER,
    "fleischmann.de": PublisherKind.MANUFACTURER,
    "mobility.siemens.com": PublisherKind.MANUFACTURER,
    "siemens.com": PublisherKind.MANUFACTURER,
    "stadlerrail.com": PublisherKind.MANUFACTURER,
    "alstom.com": PublisherKind.MANUFACTURER,
    # Railway companies.
    "sj.se": PublisherKind.OPERATOR,
    "greencargo.com": PublisherKind.OPERATOR,
    # Museums.
    "jarnvagsmuseet.se": PublisherKind.MUSEUM,
    "digitaltmuseum.se": PublisherKind.MUSEUM,
    "dbmuseum.de": PublisherKind.MUSEUM,
    # Archives and authorities.
    "trafikverket.se": PublisherKind.ARCHIVE,
    "bransch.trafikverket.se": PublisherKind.ARCHIVE,
}
"""The reviewed publishers, by exact host without www."""

_NOT_PUBLIC: Final = (".local", ".localhost", ".internal", ".invalid", ".test", ".lan")


def safe_url(value: object) -> str | None:
    """A public http(s) address as it is compared and shown, or None. Never an address with a
    login, another port, an IP number or a name that is not public: what an AI or a page writes
    is never turned into a link anywhere. Tracking parameters (utm_) are left out, so the same
    page is the same address."""
    if not isinstance(value, str) or not 0 < len(value) <= 2000 or any(ord(c) < 33 for c in value):
        return None
    try:
        parts = urlsplit(value)
        host = parts.hostname or ""
        if parts.scheme not in ("http", "https") or parts.username or parts.password:
            return None
        if parts.port not in (None, 80, 443):
            return None
        if "." not in host or host.endswith(_NOT_PUBLIC):
            return None
        try:
            ipaddress.ip_address(host)
            return None
        except ValueError:
            pass
        host = host.encode("idna").decode("ascii").lower()
        if not all(c.isalnum() or c in ".-" for c in host):
            return None
        query = urlencode(
            [
                (key, item)
                for key, item in parse_qsl(parts.query, keep_blank_values=True)
                if not key.lower().startswith("utm_")
            ]
        )
        return urlunsplit((parts.scheme, host, parts.path or "/", query, ""))
    except (ValueError, UnicodeError):
        return None


def publisher_kind(url: str) -> PublisherKind:
    """The class of the address's publisher by the reviewed list (CAT-168): unknown for
    anything that is not exactly one of its hosts."""
    safe = safe_url(url)
    if safe is None:
        return PublisherKind.UNKNOWN
    host = (urlsplit(safe).hostname or "").removeprefix("www.")
    return PUBLISHERS.get(host, PublisherKind.UNKNOWN)
