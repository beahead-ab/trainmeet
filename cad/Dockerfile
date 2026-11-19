# TrainMeet CAD as a container image (#89). Build from the repo root:
#   docker build -f cad/Dockerfile -t trainmeet-cad .
# The deploy passes TRAINMEET_COMMIT, TRAINMEET_PR, TRAINMEET_TITLE and TRAINMEET_BUILT so the
# app can show which change runs. Secrets never go in the image; the database address and the
# rest come from the environment when the container starts (cad/settings.py).
# Nothing in it is tied to one cloud: a container and PostgreSQL (ST14).

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
COPY contracts/cad.d.ts contracts/
COPY apps/design apps/design
COPY apps/cad apps/cad
# Types and tests first: a red web app never becomes an image.
RUN npm run check -w apps/design -w apps/cad \
    && npm run test -w apps/design -w apps/cad \
    && npm run build -w apps/cad

FROM python:3.12-slim AS build
RUN pip install --no-cache-dir "uv>=0.11,<0.12"
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /src
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN uv sync --locked --no-default-groups --group cad --no-install-project
COPY contracts ./contracts
COPY cad ./cad
RUN uv sync --locked --no-default-groups --group cad --no-editable

FROM python:3.12-slim
RUN useradd --system --uid 10003 --home-dir /app --shell /usr/sbin/nologin cad
COPY --from=build /app/.venv /app/.venv
COPY --from=web /src/apps/cad/dist /app/web
WORKDIR /app

ARG TRAINMEET_COMMIT=""
ARG TRAINMEET_PR=""
ARG TRAINMEET_TITLE=""
ARG TRAINMEET_BUILT=""
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    CAD_WEB_DIR=/app/web \
    TRAINMEET_COMMIT=$TRAINMEET_COMMIT \
    TRAINMEET_PR=$TRAINMEET_PR \
    TRAINMEET_TITLE=$TRAINMEET_TITLE \
    TRAINMEET_BUILT=$TRAINMEET_BUILT

USER cad
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=2)"]
# No access log: it would hold the visitors' addresses.
CMD ["uvicorn", "cad.app:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--no-access-log"]
