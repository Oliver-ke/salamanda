import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

REQUIRED = ["LOOP_REPO", "LOOP_REPO_DIR", "BEDROCK_MODEL_ID", "AWS_REGION", "GITHUB_APP_ID",
            "GITHUB_APP_INSTALLATION_ID", "LOOP_BOT_LOGIN", "LOOP_GIT_AUTHOR_EMAIL"]


class ConfigError(Exception):
    pass


def _read_key_file(path: Path) -> str:
    """Agent-run commands share the container; a key they could read is theirs."""
    try:
        mode = path.stat().st_mode
        if mode & 0o077:
            raise ConfigError(f"GITHUB_APP_PRIVATE_KEY_FILE {path} is readable by group or "
                              f"others (mode {mode & 0o777:o}); chmod 600 it")
        return path.read_text()
    except OSError as exc:
        raise ConfigError(f"GITHUB_APP_PRIVATE_KEY_FILE {path} cannot be read: {exc}") from None


@dataclass(frozen=True)
class Config:
    repo: str
    repo_dir: Path
    model_id: str
    aws_region: str
    github_app_id: str
    github_installation_id: str
    github_private_key: str
    bot_login: str
    git_author_email: str
    snapshot_lock_file: Path | None = None
    command_user: str | None = None
    max_tool_calls: int = 60
    max_verify_retries: int = 2

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> "Config":
        missing = [name for name in REQUIRED if not env.get(name)]
        key = env.get("GITHUB_APP_PRIVATE_KEY")
        if not key and env.get("GITHUB_APP_PRIVATE_KEY_FILE"):
            key = _read_key_file(Path(env["GITHUB_APP_PRIVATE_KEY_FILE"]))
        if not key:
            missing.append("GITHUB_APP_PRIVATE_KEY (or GITHUB_APP_PRIVATE_KEY_FILE)")
        if missing:
            raise ConfigError(f"missing environment variables: {', '.join(missing)}")
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", env["LOOP_REPO"]):
            raise ConfigError("LOOP_REPO must be owner/name")
        if not env["LOOP_BOT_LOGIN"].endswith("[bot]"):
            raise ConfigError("LOOP_BOT_LOGIN must be the App's bot login, ending in [bot]")
        try:
            max_tool_calls = int(env.get("LOOP_MAX_TOOL_CALLS", "60"))
        except ValueError:
            raise ConfigError("LOOP_MAX_TOOL_CALLS must be an integer") from None
        lock = env.get("LOOP_SNAPSHOT_LOCK_FILE")
        return cls(
            repo=env["LOOP_REPO"], repo_dir=Path(env["LOOP_REPO_DIR"]),
            model_id=env["BEDROCK_MODEL_ID"], aws_region=env["AWS_REGION"],
            github_app_id=env["GITHUB_APP_ID"], github_installation_id=env["GITHUB_APP_INSTALLATION_ID"],
            github_private_key=key, bot_login=env["LOOP_BOT_LOGIN"],
            git_author_email=env["LOOP_GIT_AUTHOR_EMAIL"],
            snapshot_lock_file=Path(lock) if lock else None,
            command_user=env.get("LOOP_COMMAND_USER") or None,
            max_tool_calls=max_tool_calls,
        )
