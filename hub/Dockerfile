# TrainMeet Hub as a container image. Build from the repo root:
#   docker build -f hub/Dockerfile -t trainmeet-hub .
# The deploy passes TRAINMEET_COMMIT, TRAINMEET_PR, TRAINMEET_TITLE and TRAINMEET_BUILT so the
# start page can show which change runs. Secrets never go in the image; they come from the
# environment when the container starts.
#
# The pages rebuilt in React (H62, GRUND-36) are built in the first stage and served by the hub
# from HUB_WEB_DIR (hub/web.py).

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
COPY contracts/types.d.ts contracts/
# Provbanan, which the web apps' tests draw on.
COPY contracts/examples/provbanan.meet.json contracts/examples/
COPY apps/design apps/design
COPY apps/hubben apps/hubben
COPY apps/skarmar apps/skarmar
COPY apps/tmbox-webb apps/tmbox-webb
COPY apps/trafikledning apps/trafikledning
COPY apps/planering apps/planering
COPY apps/lokforaren apps/lokforaren
# Types and tests first: a red web app never becomes an image.
RUN npm run check -w apps/design -w apps/hubben -w apps/skarmar -w apps/tmbox-webb \
       -w apps/trafikledning -w apps/planering -w apps/lokforaren \
    && npm run test -w apps/design -w apps/hubben -w apps/skarmar -w apps/tmbox-webb \
       -w apps/trafikledning -w apps/planering -w apps/lokforaren \
    && npm run build -w apps/skarmar -w apps/tmbox-webb -w apps/trafikledning -w apps/planering \
       -w apps/lokforaren

FROM python:3.12-slim AS build
RUN pip install --no-cache-dir "uv>=0.11,<0.12"
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /src
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN uv sync --locked --no-default-groups --group push --no-install-project
COPY contracts ./contracts
COPY drift ./drift
COPY integrationer ./integrationer
COPY core ./core
COPY planering ./planering
COPY synk ./synk
COPY hub ./hub
RUN uv sync --locked --no-default-groups --group push --no-editable

FROM python:3.12-slim
RUN useradd --system --uid 10001 --home-dir /app --shell /usr/sbin/nologin hub \
    && mkdir /data && chown hub:hub /data
COPY --from=build /app/.venv /app/.venv
COPY --from=web /src/apps/skarmar/dist /app/web/skarmar
COPY --from=web /src/apps/tmbox-webb/dist /app/web/tmbox-webb
COPY --from=web /src/apps/trafikledning/dist /app/web/trafikledning
COPY --from=web /src/apps/planering/dist /app/web/planering
COPY --from=web /src/apps/lokforaren/dist /app/web/lokforaren
WORKDIR /app

ARG TRAINMEET_COMMIT=""
ARG TRAINMEET_PR=""
ARG TRAINMEET_TITLE=""
ARG TRAINMEET_BUILT=""
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    HUB_WEB_DIR=/app/web \
    TRAINMEET_COMMIT=$TRAINMEET_COMMIT \
    TRAINMEET_PR=$TRAINMEET_PR \
    TRAINMEET_TITLE=$TRAINMEET_TITLE \
    TRAINMEET_BUILT=$TRAINMEET_BUILT

USER hub
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=2)"]
CMD ["uvicorn", "hub.app:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers"]
