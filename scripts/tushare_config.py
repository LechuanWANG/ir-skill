#!/usr/bin/env python3
"""Resolve TuShare configuration consistently across every local entry point."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from project_context import project_paths


TUSHARE_TOKEN_KEY = "TUSHARE_TOKEN"
TUSHARE_ENV_FILE_KEY = "TUSHARE_ENV_FILE"
DEFAULT_ENV_PATH = project_paths().env_path
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class ResolvedTushareToken:
    """Keep the token value and provenance separate so callers never log the secret."""

    value: str
    source: str
    env_path: Path | None = None

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(self.value.encode("utf-8")).hexdigest()[:12]


def _strip_inline_comment(value: str) -> str:
    quoted: str | None = None
    for index, character in enumerate(value):
        if character in {"'", '"'}:
            if quoted is None:
                quoted = character
            elif quoted == character:
                quoted = None
        elif character == "#" and quoted is None and index and value[index - 1].isspace():
            return value[:index].rstrip()
    return value.strip()


def _parse_env_value(raw_value: str) -> str:
    value = _strip_inline_comment(raw_value.strip())
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def read_env_values(path: Path = DEFAULT_ENV_PATH) -> dict[str, str]:
    """Read a small dotenv-style file without importing or mutating process state."""

    env_path = Path(path).expanduser()
    if not env_path.is_file():
        return {}
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(env_path.read_text(encoding="utf-8", errors="replace").splitlines()):
        line = raw_line.lstrip("\ufeff").strip() if line_number == 0 else raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        key = key.strip()
        if _ENV_NAME.fullmatch(key):
            values[key] = _parse_env_value(raw_value)
    return values


def update_env_values(updates: Mapping[str, str], path: Path = DEFAULT_ENV_PATH) -> None:
    """Atomically update selected dotenv keys while preserving comments and unrelated keys."""

    env_path = Path(path).expanduser()
    env_path.parent.mkdir(parents=True, exist_ok=True)
    clean_updates = {
        key: str(value).strip()
        for key, value in updates.items()
        if _ENV_NAME.fullmatch(key)
    }
    existing_lines = env_path.read_text(encoding="utf-8", errors="replace").splitlines() if env_path.is_file() else []
    output: list[str] = []
    handled: set[str] = set()
    for raw_line in existing_lines:
        stripped = raw_line.strip()
        candidate = stripped[7:].lstrip() if stripped.startswith("export ") else stripped
        if not candidate or candidate.startswith("#") or "=" not in candidate:
            output.append(raw_line)
            continue
        key = candidate.split("=", 1)[0].strip()
        if key not in clean_updates:
            output.append(raw_line)
            continue
        if key in handled:
            continue
        handled.add(key)
        value = clean_updates[key]
        if value:
            output.append(f"{key}={value}")
    for key, value in clean_updates.items():
        if key not in handled and value:
            output.append(f"{key}={value}")

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=env_path.parent,
            prefix=f".{env_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write("\n".join(output).rstrip() + "\n")
            temporary.flush()
            os.fsync(temporary.fileno())
        temporary_path.chmod(0o600)
        os.replace(temporary_path, env_path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def configured_env_path(
    *,
    environ: Mapping[str, str] | None = None,
    env_path: Path | None = None,
) -> Path:
    if env_path is not None:
        return Path(env_path).expanduser().resolve()
    source = os.environ if environ is None else environ
    configured = source.get(TUSHARE_ENV_FILE_KEY, "").strip()
    return Path(configured).expanduser().resolve() if configured else DEFAULT_ENV_PATH


def resolve_tushare_token(
    *,
    environ: Mapping[str, str] | None = None,
    env_path: Path | None = None,
    read_file: bool = True,
) -> ResolvedTushareToken:
    """Resolve the active token without caching file credentials in ``os.environ``."""

    source = os.environ if environ is None else environ
    token = source.get(TUSHARE_TOKEN_KEY, "").strip()
    if token:
        return ResolvedTushareToken(value=token, source="process_environment")

    path = configured_env_path(environ=source, env_path=env_path)
    token = read_env_values(path).get(TUSHARE_TOKEN_KEY, "").strip() if read_file else ""
    if token:
        return ResolvedTushareToken(value=token, source="env_file", env_path=path)
    raise RuntimeError(
        f"{TUSHARE_TOKEN_KEY} is required. Set it in the process environment or in {path}."
    )


def tushare_config_status(
    *,
    environ: Mapping[str, str] | None = None,
    env_path: Path | None = None,
) -> dict[str, object]:
    """Return a secret-safe configuration diagnostic suitable for CLI and UI output."""

    source = os.environ if environ is None else environ
    path = configured_env_path(environ=source, env_path=env_path)
    try:
        resolved = resolve_tushare_token(environ=source, env_path=env_path)
    except RuntimeError as error:
        return {
            "status": "missing",
            "env_path": str(path),
            "process_environment_has_token": bool(source.get(TUSHARE_TOKEN_KEY, "").strip()),
            "message": str(error),
        }
    return {
        "status": "configured",
        "source": resolved.source,
        "env_path": str(resolved.env_path or path),
        "fingerprint": resolved.fingerprint,
    }
