"""Load configuration from the project ``.env`` without extra dependencies.

Resolution finds the nearest ``.env`` walking up from the working directory, so
commands work from the repo root or a subdirectory. Existing environment
variables always win, which lets CI and shells override the file.

Kept tiny on purpose: `python-dotenv` would be a dependency for forty lines of
parsing, and this project already avoids dependencies where it can.
"""

from __future__ import annotations

import os
from pathlib import Path

_loaded: set[Path] = set()


def find_env_file(start: Path | None = None) -> Path | None:
    """Nearest ``.env`` from ``start`` upward."""
    current = (start or Path.cwd()).resolve()
    for directory in (current, *current.parents):
        candidate = directory / ".env"
        if candidate.is_file():
            return candidate
    return None


def load_env(path: str | Path | None = None) -> dict[str, str]:
    """Load ``.env`` into ``os.environ`` without overwriting existing keys.

    Returns the values found in the file (before os.environ merging), which is
    handy for tests. Repeated calls for the same file are no-ops.
    """
    file = Path(path) if path else find_env_file()
    if file is None or not file.is_file():
        return {}

    resolved = file.resolve()
    parsed: dict[str, str] = {}
    for line in resolved.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if not key:
            continue
        parsed[key] = value

    for key, value in parsed.items():
        # Never clobber a real environment variable; shells and CI win.
        os.environ.setdefault(key, value)

    _loaded.add(resolved)
    return parsed
