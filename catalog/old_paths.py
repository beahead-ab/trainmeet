"""The old TrainCatalog's addresses, sent on for good to Catalog's own (#57, CAT-206).

When the old TrainCatalog has been tried and given way, its domain sends every request on to
Catalog with the whole path (docs/flytten.md). Tags and QR codes carry /t/<uid>, which is
Catalog's own address too: the old forms of the uid, in capitals, with colons or dashes, sim:
in front or a slash after, go to the one form (catalog/tags.py). A vehicle keeps its id in the
move (catalog/flytten.py), so /fordon/<id> is the same page; its old edit page and the old pages
for adding vehicles have new addresses, and the old account pages go to the vehicles and the
login. The answer is 301 Moved Permanently, so browsers and bookmarks remember it.
"""

from __future__ import annotations

import re
from typing import Final

from catalog.fleet import Refused
from catalog.tags import normalize

_UUID: Final = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
_TAG: Final = re.compile(r"/t/([^/]{1,80})/?")
_EDIT: Final = re.compile(rf"/fordon/({_UUID})/redigera/?")
_FIXED: Final = {
    "/nytt": "/fordon/nytt",
    "/nytt/flera": "/fordon/nytt/flera",
    "/konto": "/fordon",
    "/anvandare": "/fordon",
}
"""The old pages that have a new address of their own (old config/urls.py)."""
_LOGIN: Final = "/logga-in"


def new_address(path: str) -> str | None:
    """Where an old TrainCatalog path goes now, or None when Catalog answers it as it is."""
    tag = _TAG.fullmatch(path)
    if tag is not None:
        try:
            found = normalize(tag[1])
        except Refused:
            return None  # not a tag's address: the web app says so
        target = f"/t/{found.value}"
        return target if target != path else None
    edit = _EDIT.fullmatch(path)
    if edit is not None:
        return f"/fordon/{edit[1].lower()}/andra"
    fixed = _FIXED.get(path.rstrip("/"))
    if fixed is not None:
        return fixed
    if path == "/accounts" or path.startswith("/accounts/"):
        return _LOGIN  # the old login, sign-up and e-mail pages
    return None
