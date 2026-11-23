"""Provet av bildläsningen med den riktiga nyckeln (#79, TOKEN-28, TK14, CAD19).

The trial is a program run by hand; here it reads against a pretend Bedrock, which answers as
AWS does. The job that starts it, and the key's policy, are read as files.
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
KEY_ID = "AKIAPROVETPROVET"
SECRET = "hemlig-nyckel-for-provet"
ACCOUNT = "123456789012"


def key_file(tmp_path: Path) -> Path:
    key = tmp_path / "trainmeet_bedrock-key"
    key.write_text(f"{KEY_ID}\n{SECRET}\n")
    return key


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


def test_the_trial_asks_both_models_in_the_eu_and_never_prints_the_key(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A transcription with the meter's model and a hard question with CAD's model, both with
    the EU profiles from Stockholm, through the meter's own BedrockClaude. Without the key's
    file it asks nobody."""
    assert prov_bildlasning.main(["--nyckelfil", str(tmp_path / "saknas")]) == 2
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        hard = "opus" in request.url.path
        return httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": "Höger." if hard else "4071"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 900, "output_tokens": 300 if hard else 8},
            },
        )

    key = key_file(tmp_path)
    assert (
        prov_bildlasning.main(["--nyckelfil", str(key)], transport=httpx.MockTransport(handle)) == 0
    )
    assert [request.url.path for request in seen] == [
        f"/model/{MeterSettings.model}/invoke",
        f"/model/{MeterSettings.hard_model}/invoke",
    ]
    assert {request.url.host for request in seen} == {"bedrock-runtime.eu-north-1.amazonaws.com"}
    first = json.loads(seen[0].content)
    image = first["messages"][0]["content"][0]
    assert image["source"]["media_type"] == "image/png"
    assert base64.b64decode(image["source"]["data"]) == prov_bildlasning.picture()
    assert json.loads(seen[1].content)["output_config"] == {"effort": "high"}
    printed = capsys.readouterr()
    assert "Avskrift: eu.anthropic.claude-sonnet-5-5" in printed.out
    assert "Svår fråga: eu.anthropic.claude-opus-5-5" in printed.out
    assert printed.out.count("(rätt)") == 2 and "2 av 2 rätt" in printed.out
    assert "Tokens in: 900" in printed.out and "Tokens ut: 300" in printed.out
    for hidden in (KEY_ID, SECRET):
        assert hidden not in printed.out + printed.err


def test_a_refusal_from_aws_says_what_the_policy_lacks_without_the_account(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """When AWS says no, the trial prints AWS's error type and message, so that the model or
    region missing in the key's policy shows; the account's number is never printed."""
    refused = (
        f"User: arn:aws:iam::{ACCOUNT}:user/trainmeet-id is not authorized to perform: "
        "bedrock:InvokeModel on resource: "
        "arn:aws:bedrock:eu-west-3::foundation-model/anthropic.claude-opus-5-5"
    )

    def handle(request: httpx.Request) -> httpx.Response:
        if "opus" in request.url.path:
            return httpx.Response(
                403,
                headers={"x-amzn-ErrorType": "AccessDeniedException:http://internal.amazon.com/"},
                json={"message": refused},
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
    assert "AccessDeniedException 403" in printed.err
    assert "eu-west-3::foundation-model/anthropic.claude-opus-5-5" in printed.err
    assert "arn:aws:iam::<kontot>:user/trainmeet-id" in printed.err
    for hidden in (ACCOUNT, KEY_ID, SECRET):
        assert hidden not in printed.out + printed.err


def test_a_wrong_answer_fails_the_trial(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "content": [
                    {"type": "text", "text": "vänster" if "opus" in request.url.path else "4011"}
                ],
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
    for line in job.splitlines():
        if "BEDROCK_" in line and "secrets." not in line:
            assert "echo" not in line or "saknas" in line, line
    # The trial is in ID's image, where the test environment runs it.
    image = (ROOT / "id" / "api.Dockerfile").read_text()
    assert "id/prov_bildlasning.py" in image


def test_the_keys_policy_allows_the_meters_models_only_through_the_eu_profiles() -> None:
    """deploy/bedrock-policy.json, the policy of the key's IAM user (README, Testmiljön step 7):
    InvokeModel on the meter's two EU profiles in the meter's region, and on the models behind
    them in the EU's regions only when the call comes through those profiles, so the pictures
    stay in the EU and a region AWS adds to the profile is not refused."""
    policy = json.loads((ROOT / "deploy" / "bedrock-policy.json").read_text())
    profiles, models = policy["Statement"]
    region = MeterSettings.region
    wanted = [
        f"arn:aws:bedrock:{region}:*:inference-profile/{model}"
        for model in (MeterSettings.model, MeterSettings.hard_model)
    ]
    assert profiles["Effect"] == models["Effect"] == "Allow"
    assert profiles["Action"] == models["Action"] == "bedrock:InvokeModel"
    assert profiles["Resource"] == wanted and "Condition" not in profiles
    assert models["Resource"] == [
        f"arn:aws:bedrock:eu-*::foundation-model/{model.removeprefix('eu.')}"
        for model in (MeterSettings.model, MeterSettings.hard_model)
    ]
    assert models["Condition"] == {"StringLike": {"bedrock:InferenceProfileArn": wanted}}
