"""The Hub's web apps (H62, GRUND-36): TypeScript, React and Vite under apps/, served from here.

Each app is built with Vite to a folder of its own, with its address as Vite's base, and the hub
serves the built files at that address. An address in an app that is not a file gets the app's
index.html, so the app's own routes work when opened directly or reloaded.

In the image the apps lie in HUB_WEB_DIR (/app/web/<folder>); locally they are read from
apps/<folder>/dist after `npm run build`.

The apps load only their own files (CSP), as Catalog's and ID's do.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, Response

REPO = Path(__file__).resolve().parents[1]

CONTENT_SECURITY_POLICY: Final = (
    "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
    "font-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'self'; "
    "frame-ancestors 'none'; object-src 'none'"
)
HEADERS: Final = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


@dataclass(frozen=True)
class WebApp:
    """One app: its address and its folder under apps/."""

    prefix: str
    folder: str
    title: str


APPS: Final = (WebApp(prefix="/skarm", folder="skarmar", title="Träffens skärmar"),)


def web_dir(app: WebApp, root: Path | None = None) -> Path:
    """Where the app's built files are: HUB_WEB_DIR/<folder>, or apps/<folder>/dist locally."""
    if root is None and os.environ.get("HUB_WEB_DIR", "").strip():
        root = Path(os.environ["HUB_WEB_DIR"].strip())
    return root / app.folder if root is not None else REPO / "apps" / app.folder / "dist"


def _not_built(app: WebApp) -> str:
    return (
        '<!doctype html><html lang="sv"><meta charset="utf-8">'
        f"<title>TrainMeet · {app.title}</title><h1>{app.title}</h1>"
        "<p>Webbappen är inte byggd. Kör <code>npm run build</code>.</p></html>"
    )


def router(root: Path | None = None) -> APIRouter:
    routes = APIRouter()
    for app in APPS:
        _serve(routes, app, web_dir(app, root))
    return routes


def _serve(routes: APIRouter, app: WebApp, folder: Path) -> None:
    def serve(path: str = "") -> Response:
        base = folder.resolve()
        if path:
            candidate = (base / path).resolve()
            if candidate.is_relative_to(base) and candidate.is_file():
                cache = (
                    "public, max-age=31536000, immutable"
                    if path.startswith("assets/")
                    else "public, max-age=3600"
                )
                return FileResponse(candidate, headers={**HEADERS, "Cache-Control": cache})
            if "." in path.rsplit("/", 1)[-1]:
                return PlainTextResponse("Finns inte.", status_code=404, headers=HEADERS)
        index = base / "index.html"
        if not index.is_file():
            return HTMLResponse(_not_built(app), headers=HEADERS)
        return FileResponse(index, headers={**HEADERS, "Cache-Control": "no-cache"})

    routes.add_api_route(app.prefix, serve, methods=["GET", "HEAD"], include_in_schema=False)
    routes.add_api_route(
        app.prefix + "/{path:path}", serve, methods=["GET", "HEAD"], include_in_schema=False
    )
