# TrainMeet Hub as a container image. Build from the repo root:
#   docker build -f hub/Dockerfile -t trainmeet-hub .
# The deploy passes TRAINMEET_COMMIT, TRAINMEET_PR, TRAINMEET_TITLE and TRAINMEET_BUILT so the
# start page can show which change runs. Secrets never go in the image; they come from the
# environment when the container starts.

FROM python:3.12-slim AS build
RUN pip install --no-cache-dir "uv>=0.11,<0.12"
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /src
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN uv sync --locked --no-dev --no-install-project
COPY contracts ./contracts
COPY hub ./hub
RUN uv sync --locked --no-dev --no-editable

FROM python:3.12-slim
RUN useradd --system --uid 10001 --home-dir /app --shell /usr/sbin/nologin hub
COPY --from=build /app/.venv /app/.venv
WORKDIR /app

ARG TRAINMEET_COMMIT=""
ARG TRAINMEET_PR=""
ARG TRAINMEET_TITLE=""
ARG TRAINMEET_BUILT=""
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    TRAINMEET_COMMIT=$TRAINMEET_COMMIT \
    TRAINMEET_PR=$TRAINMEET_PR \
    TRAINMEET_TITLE=$TRAINMEET_TITLE \
    TRAINMEET_BUILT=$TRAINMEET_BUILT

USER hub
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=2)"]
CMD ["uvicorn", "hub.app:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers"]
