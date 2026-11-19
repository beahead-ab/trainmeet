# TrainMeet Catalog as a container image. Build from the repo root:
#   docker build -f catalog/Dockerfile -t trainmeet-catalog .
# The deploy passes TRAINMEET_COMMIT, TRAINMEET_PR, TRAINMEET_TITLE and TRAINMEET_BUILT so the
# app can show which change runs. Secrets never go in the image; the database address and
# the rest come from the environment when the container starts (catalog/settings.py).
# Nothing in it is tied to one cloud: a container and PostgreSQL (ST14, CAT-215).

FROM node:22-slim AS web
WORKDIR /src
COPY package.json package-lock.json ./
COPY apps/design/package.json apps/design/
COPY apps/hubben/package.json apps/hubben/
COPY apps/catalog/package.json apps/catalog/
COPY apps/cad/package.json apps/cad/
COPY apps/id/package.json apps/id/
COPY apps/skarmar/package.json apps/skarmar/
COPY apps/tmbox-webb/package.json apps/tmbox-webb/
COPY apps/trafikledning/package.json apps/trafikledning/
COPY apps/planering/package.json apps/planering/
COPY apps/tkl/package.json apps/tkl/
COPY apps/lokforaren/package.json apps/lokforaren/
RUN npm ci --no-audit --no-fund
COPY contracts/catalog.d.ts contracts/
COPY apps/design apps/design
COPY apps/catalog apps/catalog
# Types and tests first: a red web app never becomes an image.
RUN npm run check -w apps/design -w apps/catalog \
    && npm run test -w apps/design -w apps/catalog \
    && npm run build -w apps/catalog

# The background removal's model (CAT-18, CAT-127): U2NetP, Apache-2.0, about 4.6 MB, from
# rembg's release. Fetched when the image is built and checked against its SHA-256: another file
# stops the build. The same sum is checked again when Catalog loads it (catalog/backgrounds.py).
FROM python:3.12-slim AS model
ARG U2NETP_URL=https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2netp.onnx
ARG U2NETP_SHA256=309c8469258dda742793dce0ebea8e6dd393174f89934733ecc8b14c76f4ddd8
RUN mkdir /model && python -c "import hashlib, sys, urllib.request; \
data = urllib.request.urlopen(sys.argv[1], timeout=120).read(16_000_000); \
found = hashlib.sha256(data).hexdigest(); \
sys.exit(f'U2NetP: fel SHA-256 {found}') if found != sys.argv[2] else None; \
open(sys.argv[3], 'wb').write(data)" "$U2NETP_URL" "$U2NETP_SHA256" /model/u2netp.onnx

FROM python:3.12-slim AS build
RUN pip install --no-cache-dir "uv>=0.11,<0.12"
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /src
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN uv sync --locked --no-default-groups --group catalog --no-install-project
COPY contracts ./contracts
COPY catalog ./catalog
RUN uv sync --locked --no-default-groups --group catalog --no-editable

FROM python:3.12-slim
RUN useradd --system --uid 10002 --home-dir /app --shell /usr/sbin/nologin catalog
COPY --from=build /app/.venv /app/.venv
COPY --from=web /src/apps/catalog/dist /app/web
COPY --from=model /model/u2netp.onnx /app/models/u2netp.onnx
WORKDIR /app
# onnxruntime's wheel needs only libstdc++ and libgcc from the base image, no libgomp. Its
# telemetry to Microsoft is off (CAT-127). The model is loaded once here, so an image whose
# background removal cannot run is never built.
ENV ORT_DISABLE_TELEMETRY=1
RUN /app/.venv/bin/python -c "import sys; from pathlib import Path; \
from catalog.backgrounds import U2NetP; \
sys.exit(0 if U2NetP(Path('/app/models/u2netp.onnx')).available() else 'U2NetP går inte')"

ARG TRAINMEET_COMMIT=""
ARG TRAINMEET_PR=""
ARG TRAINMEET_TITLE=""
ARG TRAINMEET_BUILT=""
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    CATALOG_WEB_DIR=/app/web \
    CATALOG_BACKGROUND_MODEL=/app/models/u2netp.onnx \
    TRAINMEET_COMMIT=$TRAINMEET_COMMIT \
    TRAINMEET_PR=$TRAINMEET_PR \
    TRAINMEET_TITLE=$TRAINMEET_TITLE \
    TRAINMEET_BUILT=$TRAINMEET_BUILT

USER catalog
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=2)"]
# No access log: it would hold the visitors' addresses (CAT-194).
CMD ["uvicorn", "catalog.app:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--no-access-log"]
