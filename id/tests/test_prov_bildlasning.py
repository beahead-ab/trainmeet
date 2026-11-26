"""Provet av bildläsningen med den riktiga nyckeln (#79, TOKEN-28, TOKEN-20, CAD18).

The trial is a program run by hand; here it reads against a pretend Anthropic, which answers as
Anthropic's API does. The job that starts it is read as a file.
"""

from __future__ import annotations

import base64
import json
import struct
import zlib
from pathlib import Path

import httpx
import pytest

from id import prov_bildlasning
from id.meter import MeterSettings

ROOT = Path(__file__).resolve().parents[2]
KEY = "sk-ant-provet-hemlig-nyckel"


def key_file(tmp_path: Path) -> Path:
    key = tmp_path / "trainmeet_search-key"
    key.write_text(f"{KEY}\n")
    return key


def hard(request: httpx.Request) -> bool:
    return bool(json.loads(request.content)["model"] == MeterSettings.hard_model)


def test_the_picture_is_a_png_with_the_digits_and_the_square() -> None:
    png = prov_bildlasning.picture()
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    width, height = struct.unpack(">II", png[16:24])
    assert (width, height) == (528, 180)
    data = png[png.index(b"IDAT") + 4 : png.index(b"IEND") - 8]
    pixels = zlib.decompress(data)
    assert len(pixels) == height * (width + 1)
    rows = [pixels[y * (width + 1) + 1 : (y + 1) * (width + 1)] for y in range(height)]
    middle = rows[height // 2]
    # Black digits and, last, the filled square on white, with a white margin all round.
    assert middle[0] == middle[-1] == 255 and 0 in middle
    assert all(value == 255 for value in rows[0]) and all(value == 255 for value in rows[-1])
    square = width - prov_bildlasning.MARGIN - prov_bildlasning.SCALE // 2
    assert middle[square] == 0


def test_the_trial_asks_both_models_and_never_prints_the_key(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A transcription with the meter's model and a hard question with CAD's model, through the
    meter's own AnthropicClaude. Without the key's file it asks nobody."""
    assert prov_bildlasning.main(["--nyckelfil", str(tmp_path / "saknas")]) == 2
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": "Höger." if hard(request) else "4071"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 900, "output_tokens": 300 if hard(request) else 8},
            },
        )

    key = key_file(tmp_path)
    assert (
        prov_bildlasning.main(["--nyckelfil", str(key)], transport=httpx.MockTransport(handle)) == 0
    )
    assert {str(request.url) for request in seen} == {"https://api.anthropic.com/v1/messages"}
    first, second = (json.loads(request.content) for request in seen)
    assert (first["model"], second["model"]) == (MeterSettings.model, MeterSettings.hard_model)
    image = first["messages"][0]["content"][0]
    assert image["source"]["media_type"] == "image/png"
    assert base64.b64decode(image["source"]["data"]) == prov_bildlasning.picture()
    assert second["output_config"] == {"effort": "high"}
    printed = capsys.readouterr()
    assert "Avskrift: claude-sonnet-5-5" in printed.out
    assert "Svår fråga: claude-fable-5-2" in printed.out
    assert printed.out.count("(rätt)") == 2 and "2 av 2 rätt" in printed.out
    assert "Tokens in: 900" in printed.out and "Tokens ut: 300" in printed.out
    # 900 in and 300 out at Fable 5.2's prices: four times Sonnet 5.5's $2/$10 a million.
    assert "Kostnad ungefär: 0.0192 dollar" in printed.out
    assert "Tid: " in printed.out
    assert KEY not in printed.out + printed.err


def test_a_refusal_from_anthropic_says_what_is_missing_without_the_key(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """When Anthropic says no, the trial prints the error's type and message, so that a key, a
    model or an account setting that is missing shows; the key is never printed."""
    refused = f"Your organization's data retention does not allow this model. Key {KEY}."

    def handle(request: httpx.Request) -> httpx.Response:
        if hard(request):
            return httpx.Response(
                400,
                json={
                    "type": "error",
                    "error": {"type": "invalid_request_error", "message": refused},
                },
            )
        return httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": "4071"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 900, "output_tokens": 8},
            },
        )

    key = key_file(tmp_path)
    assert (
        prov_bildlasning.main(["--nyckelfil", str(key)], transport=httpx.MockTransport(handle)) == 1
    )
    printed = capsys.readouterr()
    assert "1 av 2 rätt" in printed.out
    assert "Anthropic: invalid_request_error 400" in printed.err
    assert "data retention does not allow this model" in printed.err
    assert "Key <nyckeln>." in printed.err
    assert KEY not in printed.out + printed.err


def test_a_wrong_answer_fails_the_trial(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": "vänster" if hard(request) else "4011"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 900, "output_tokens": 8},
            },
        )

    key = key_file(tmp_path)
    assert (
        prov_bildlasning.main(["--nyckelfil", str(key)], transport=httpx.MockTransport(handle)) == 1
    )
    printed = capsys.readouterr()
    assert "väntade 4071" in printed.out and "väntade höger" in printed.out
    assert "0 av 2 rätt" in printed.out


def test_the_github_job_runs_the_trial_only_when_started_by_hand() -> None:
    """The trial costs real money: the job "Prov av bildläsningen" starts only when a person
    starts it, never on a PR or on main. In the test environment it runs in ID's container with
    the key in the vault; at GitHub the key goes to a file only the step reads, never to the
    command line or the log, and the input is never part of a script."""
    job = (ROOT / ".github" / "workflows" / "prov-bildlasning.yml").read_text()
    on = job.split("\non:\n")[1].split("\npermissions:")[0]
    assert "workflow_dispatch:" in on
    for other in ("pull_request", "push", "schedule", "workflow_run", "workflow_call"):
        assert other not in on, other
    for script in job.split("run: |")[1:]:
        assert "${{" not in script.split("\n\n")[0], "an input or a secret is never in a script"
    assert "docker compose exec -T id-api python -m id.prov_bildlasning" in job
    assert "uv run python deploy/testmiljo.py ensure" in job
    assert "umask 077" in job and "trap 'rm -f \"$key\"' EXIT" in job
    assert 'python -m id.prov_bildlasning --nyckelfil "$key"' in job
    assert "BEDROCK" not in job
    for line in job.splitlines():
        if "ANTHROPIC_API_KEY_SEARCH" in line and "secrets." not in line:
            assert "echo" not in line or "saknas" in line, line
    # The trial is in ID's image, where the test environment runs it.
    image = (ROOT / "id" / "api.Dockerfile").read_text()
    assert "id/prov_bildlasning.py" in image


def test_the_meter_reads_with_the_same_key_as_the_web_search_in_the_test_environment() -> None:
    """One key to Anthropic's API (GitHub: ANTHROPIC_API_KEY_SEARCH) for the readings and the
    web search; nothing of AWS is left in the test environment."""
    compose = (ROOT / "deploy" / "testmiljo" / "compose.yaml").read_text()
    assert "ID_METER_KEY_FILE: /vault/trainmeet_search-key" in compose
    assert "ID_SEARCH_KEY_FILE: /vault/trainmeet_search-key" in compose
    deploy = (ROOT / ".github" / "workflows" / "tester.yml").read_text()
    assert "BEDROCK" not in deploy and "trainmeet_bedrock-key" not in compose
    assert not (ROOT / "deploy" / "bedrock-policy.json").exists()
