"""The images that build web apps run `npm ci` over the whole workspace, which needs every
workspace's package.json, even the apps the image does not build. A new app under apps/ must
therefore be named in each of them (it was missed once and would have stopped the build)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
IMAGES = ["hub/Dockerfile", "catalog/Dockerfile", "id/api.Dockerfile"]


def workspaces() -> list[str]:
    data = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    return list(data["workspaces"])


@pytest.mark.parametrize("image", IMAGES)
def test_every_web_image_has_every_workspace_before_npm_ci(image: str) -> None:
    text = (ROOT / image).read_text(encoding="utf-8")
    before = text.split("RUN npm ci", 1)[0]
    copied = set(re.findall(r"COPY (apps/[\w-]+)/package\.json", before))
    assert copied == set(workspaces()), sorted(set(workspaces()) ^ copied)


def test_the_hub_serves_every_app_it_builds() -> None:
    """hub/web.py serves the apps the hub's image builds and copies, from HUB_WEB_DIR."""
    from hub.web import APPS

    text = (ROOT / "hub" / "Dockerfile").read_text(encoding="utf-8")
    assert "HUB_WEB_DIR=/app/web" in text
    for app in APPS:
        assert f"npm run build -w apps/{app.folder}" in text or f"-w apps/{app.folder}" in text
        assert f"COPY --from=web /src/apps/{app.folder}/dist /app/web/{app.folder}" in text
