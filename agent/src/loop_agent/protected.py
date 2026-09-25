"""The protected-path list, read from harness so there is one source of truth."""

import json
import subprocess
from collections.abc import Sequence
from pathlib import Path


def load_protected_paths(repo_dir: Path) -> list[str]:
    out = subprocess.run(
        ["node", "harness/src/cli/protected-paths.mjs"],
        cwd=repo_dir, check=True, capture_output=True, text=True,
    ).stdout
    return json.loads(out)


def is_protected(path: str, entries: Sequence[str]) -> bool:
    """Same three rules as harness/src/protected.mjs isProtectedPath."""
    normalised = path[2:] if path.startswith("./") else path
    for entry in entries:
        if entry.endswith("/"):
            if normalised.startswith(entry):
                return True
        elif entry.endswith(".*"):
            stem = entry[:-2]
            if normalised.startswith(f"{stem}."):
                ext = normalised[len(stem) + 1:]
                if ext and "/" not in ext:
                    return True
        elif normalised == entry:
            return True
    return False
