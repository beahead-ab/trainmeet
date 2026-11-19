# TrainMeet TKL as a container image (KLAR-22): TKL in the cloud, test.tkl.trainmeet.app.
# Build from the repo root:
#   docker build -f tkl/Dockerfile -t trainmeet-tkl .
# On a station's computer TKL runs without a container: `uv run python -m tkl`. The image runs
# TKL in the cloud (TKL_MODE=cloud), one station per browser, reaching only the hubs in
# TKL_HUBBAR. With TKL_MODE=local and the USB bus given to it, it owns Stream Decks over USB
# (tkl/README.md). Nothing secret goes in the image.

FROM node:22-slim AS web
WORKDIR /src
COPY package.json package-lock.json ./
COPY apps/design/package.json apps/design/
COPY apps/hubben/package.json apps/hubben/
COPY apps/catalog/package.json apps/catalog/
COPY apps/id/package.json apps/id/
COPY apps/skarmar/package.json apps/skarmar/
COPY apps/tmbox-webb/package.json apps/tmbox-webb/
COPY apps/trafikledning/package.json apps/trafikledning/
COPY apps/planering/package.json apps/planering/
COPY apps/tkl/package.json apps/tkl/
COPY apps/lokforaren/package.json apps/lokforaren/
RUN npm ci --no-audit --no-fund
COPY contracts/tkl.d.ts contracts/
# The four reference stations, which the web app's tests draw in Foto.
COPY tkl/referens tkl/referens
COPY apps/design apps/design
COPY apps/tkl apps/tkl
# Types and tests first: a red web app never becomes an image.
RUN npm run check -w apps/design -w apps/tkl \
    && npm run test -w apps/design -w apps/tkl \
    && npm run build -w apps/tkl

FROM python:3.12-slim AS build
RUN pip install --no-cache-dir "uv>=0.11,<0.12"
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /src
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN uv sync --locked --no-default-groups --group tkl --no-install-project
COPY contracts ./contracts
COPY tkl ./tkl
RUN uv sync --locked --no-default-groups --group tkl --no-editable

FROM python:3.12-slim
# libhidapi: a local TKL owns its Stream Decks over USB (#86, SD50); in the cloud it is never used.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libhidapi-libusb0 \
    && rm -rf /var/lib/apt/lists/*
RUN useradd --system --uid 10001 --home-dir /app --shell /usr/sbin/nologin tkl \
    && mkdir /data && chown tkl:tkl /data
COPY --from=build /app/.venv /app/.venv
COPY --from=web /src/apps/tkl/dist /app/web
WORKDIR /app

ARG TRAINMEET_COMMIT=""
LABEL org.opencontainers.image.revision=$TRAINMEET_COMMIT
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    TKL_WEB_DIR=/app/web \
    TKL_DATA_DIR=/data \
    TKL_MODE=cloud \
    TRAINMEET_COMMIT=$TRAINMEET_COMMIT

USER tkl
EXPOSE 8090
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8090/healthz', timeout=2)"]
CMD ["uvicorn", "tkl.app:from_environment", "--factory", "--host", "0.0.0.0", "--port", "8090", "--proxy-headers"]
