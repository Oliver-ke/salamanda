import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

REQUIRED = ["LOOP_REPO", "LOOP_REPO_DIR", "GITHUB_APP_ID", "GITHUB_APP_INSTALLATION_ID",
            "LOOP_BOT_LOGIN", "LOOP_GIT_AUTHOR_EMAIL"]
PROVIDERS = ("anthropic", "bedrock")
BEDROCK_REQUIRED = ["BEDROCK_MODEL_ID", "AWS_REGION"]
DEFAULT_ANTHROPIC_MODEL = "claude-opus-5-5"
EFFORTS = ("low", "medium", "high", "xhigh", "max")


class ConfigError(Exception):
    pass


def _read_key_file(path: Path, variable: str) -> str:
    """Agent-run commands share the container; a key they could read is theirs."""
    try:
        mode = path.stat().st_mode
        if mode & 0o077:
            raise ConfigError(f"{variable} {path} is readable by group or "
                              f"others (mode {mode & 0o777:o}); chmod 600 it")
        return path.read_text()
    except OSError as exc:
        raise ConfigError(f"{variable} {path} cannot be read: {exc}") from None


def _secret(env: Mapping[str, str], variable: str) -> str | None:
    """A secret from `variable`, or from the file named by `variable`_FILE."""
    value = env.get(variable)
    if not value and env.get(f"{variable}_FILE"):
        value = _read_key_file(Path(env[f"{variable}_FILE"]), f"{variable}_FILE")
    return value or None


@dataclass(frozen=True)
class Config:
    repo: str
    repo_dir: Path
    model_provider: str
    model_id: str
    aws_region: str | None
    anthropic_api_key: str | None
    github_app_id: str
    github_installation_id: str
    github_private_key: str
    bot_login: str
    git_author_email: str
    effort: str = "high"
    snapshot_lock_file: Path | None = None
    command_user: str | None = None
    max_tool_calls: int = 60
    max_verify_retries: int = 2

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> "Config":
        provider = env.get("LOOP_MODEL_PROVIDER") or "anthropic"
        if provider not in PROVIDERS:
            raise ConfigError(f"LOOP_MODEL_PROVIDER must be one of {', '.join(PROVIDERS)}")
        missing = [name for name in REQUIRED if not env.get(name)]
        github_key = _secret(env, "GITHUB_APP_PRIVATE_KEY")
        if not github_key:
            missing.append("GITHUB_APP_PRIVATE_KEY (or GITHUB_APP_PRIVATE_KEY_FILE)")
        anthropic_key = None
        if provider == "anthropic":
            anthropic_key = _secret(env, "ANTHROPIC_API_KEY")
            if not anthropic_key:
                missing.append("ANTHROPIC_API_KEY (or ANTHROPIC_API_KEY_FILE)")
        else:
            missing += [name for name in BEDROCK_REQUIRED if not env.get(name)]
        if missing:
            raise ConfigError(f"missing environment variables: {', '.join(missing)}")
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", env["LOOP_REPO"]):
            raise ConfigError("LOOP_REPO must be owner/name")
        if not env["LOOP_BOT_LOGIN"].endswith("[bot]"):
            raise ConfigError("LOOP_BOT_LOGIN must be the App's bot login, ending in [bot]")
        effort = env.get("LOOP_EFFORT") or "high"
        if effort not in EFFORTS:
            raise ConfigError(f"LOOP_EFFORT must be one of {', '.join(EFFORTS)}")
        try:
            max_tool_calls = int(env.get("LOOP_MAX_TOOL_CALLS", "60"))
        except ValueError:
            raise ConfigError("LOOP_MAX_TOOL_CALLS must be an integer") from None
        lock = env.get("LOOP_SNAPSHOT_LOCK_FILE")
        return cls(
            repo=env["LOOP_REPO"], repo_dir=Path(env["LOOP_REPO_DIR"]),
            model_provider=provider,
            model_id=(env.get("LOOP_MODEL_ID") or DEFAULT_ANTHROPIC_MODEL) if provider == "anthropic"
            else env["BEDROCK_MODEL_ID"],
            aws_region=env.get("AWS_REGION") if provider == "bedrock" else None,
            anthropic_api_key=anthropic_key.strip() if anthropic_key else None,
            github_app_id=env["GITHUB_APP_ID"], github_installation_id=env["GITHUB_APP_INSTALLATION_ID"],
            github_private_key=github_key, bot_login=env["LOOP_BOT_LOGIN"],
            git_author_email=env["LOOP_GIT_AUTHOR_EMAIL"],
            effort=effort,
            snapshot_lock_file=Path(lock) if lock else None,
            command_user=env.get("LOOP_COMMAND_USER") or None,
            max_tool_calls=max_tool_calls,
        )
