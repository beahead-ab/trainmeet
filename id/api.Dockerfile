# ID's API and web app (#67) as a container image, beside Keycloak (id/Dockerfile). Build from
# the repo root:
#   docker build -f id/api.Dockerfile -t trainmeet-idapi .
# Secrets never go in the image; they come from the environment when it starts (id/settings.py).

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
RUN npm ci --no-audit --no-fund
COPY contracts/id.d.ts contracts/
COPY apps/design apps/design
COPY apps/id apps/id
# Types and tests first: a red web app never becomes an image.
RUN npm run check -w apps/design -w apps/id \
    && npm run test -w apps/design -w apps/id \
    && npm run build -w apps/id

FROM python:3.12-slim AS build
RUN pip install --no-cache-dir "uv>=0.11,<0.12"
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /src
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN uv sync --locked --no-default-groups --group id --no-install-project
COPY contracts ./contracts
COPY id/__init__.py id/accounts.py id/app.py id/db.py id/help.py id/login.py id/mail.py id/meter.py id/migrate.py id/own_ai.py id/owner.py id/roles.py id/settings.py id/shop.py id/tickets.py id/tokens.py ./id/
COPY id/migrations ./id/migrations
RUN uv sync --locked --no-default-groups --group id --no-editable

FROM python:3.12-slim
RUN useradd --system --uid 10003 --home-dir /app --shell /usr/sbin/nologin idapi
COPY --from=build /app/.venv /app/.venv
COPY --from=web /src/apps/id/dist /app/web
WORKDIR /app

ARG TRAINMEET_COMMIT=""
LABEL org.opencontainers.image.title="TrainMeet ID:s API" \
      org.opencontainers.image.revision=$TRAINMEET_COMMIT \
      org.opencontainers.image.licenses="AGPL-3.0-only"
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    ID_API_WEB_DIR=/app/web \
    TRAINMEET_COMMIT=$TRAINMEET_COMMIT

USER idapi
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=2)"]
# No access log: the login's return address holds a code.
CMD ["uvicorn", "id.app:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--no-access-log"]
