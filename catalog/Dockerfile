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
COPY apps/catalog/package.json apps/catalog/
COPY apps/id/package.json apps/id/
COPY apps/skarmar/package.json apps/skarmar/
COPY apps/tmbox-webb/package.json apps/tmbox-webb/
RUN npm ci --no-audit --no-fund
COPY contracts/catalog.d.ts contracts/
COPY apps/design apps/design
COPY apps/catalog apps/catalog
# Types and tests first: a red web app never becomes an image.
RUN npm run check -w apps/design -w apps/catalog \
    && npm run test -w apps/design -w apps/catalog \
    && npm run build -w apps/catalog

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
WORKDIR /app

ARG TRAINMEET_COMMIT=""
ARG TRAINMEET_PR=""
ARG TRAINMEET_TITLE=""
ARG TRAINMEET_BUILT=""
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    CATALOG_WEB_DIR=/app/web \
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
