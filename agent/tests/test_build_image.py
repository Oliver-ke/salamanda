import io
import zipfile
from types import SimpleNamespace

import pytest

from deploy.build_image import accepted, image_request, make_artifact, read_image_env

from .conftest import REPO_ROOT


def test_artifact_has_dockerfile_at_root_and_the_agent_tree_without_junk():
    names = zipfile.ZipFile(io.BytesIO(make_artifact(REPO_ROOT))).namelist()
    assert "Dockerfile" in names
    assert "agent/src/loop_agent/server.py" in names
    assert "agent/pyproject.toml" in names and "agent/uv.lock" in names
    assert not any(part in n for n in names for part in (".venv/", "__pycache__/", ".pytest_cache/"))


def test_artifact_contains_only_git_tracked_files():
    secret = REPO_ROOT / "agent" / ".env-test-secret"
    secret.write_text("ANTHROPIC_API_KEY=sk-should-never-ship\n")
    try:
        names = zipfile.ZipFile(io.BytesIO(make_artifact(REPO_ROOT))).namelist()
        assert ".env-test-secret" not in names
        assert not any(n.endswith(".env-test-secret") for n in names)
        assert "agent/src/loop_agent/server.py" in names
    finally:
        secret.unlink()


def test_image_env_refuses_secrets(tmp_path):
    ok = tmp_path / "image.env"
    ok.write_text("# comment\nLOOP_REPO=o/r\n\nLOOP_MODEL_ID=claude-opus-5-5\n")
    assert read_image_env(ok) == {"LOOP_REPO": "o/r", "LOOP_MODEL_ID": "claude-opus-5-5"}
    for line in ("ANTHROPIC_API_KEY=sk", "ANTHROPIC_API_KEY_FILE=/x", "GITHUB_APP_PRIVATE_KEY_FILE=/x",
                 "AWS_REGION=eu-west-1"):
        bad = tmp_path / "bad.env"
        bad.write_text(line + "\n")
        with pytest.raises(SystemExit):
            read_image_env(bad)


def test_image_request_is_arm_with_the_ready_hook():
    req = image_request("n", "s3://b/k.zip", "arn:role", "arn:base", {"LOOP_REPO": "o/r"})
    assert req["cpuConfigurations"] == [{"architecture": "ARM_64"}]
    assert req["hooks"]["port"] == 8080
    assert req["hooks"]["microvmImageHooks"]["ready"] == "ENABLED"
    assert req["codeArtifact"] == {"uri": "s3://b/k.zip"}
    assert "AWS_REGION" not in req["environmentVariables"]


def test_accepted_keeps_only_members_the_operation_takes():
    shape = SimpleNamespace(members={"imageIdentifier": 1, "codeArtifact": 1, "hooks": 1})
    client = SimpleNamespace(meta=SimpleNamespace(service_model=SimpleNamespace(
        operation_model=lambda op: SimpleNamespace(input_shape=shape))))
    assert accepted(client, "UpdateMicrovmImage", {"imageIdentifier": "a", "name": "n", "hooks": {}}) == \
        {"imageIdentifier": "a", "hooks": {}}
