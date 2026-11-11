"""Environment configuration and defaults.

Values come from the environment or a .env file at the project root (never
committed). Names follow the old harness where they existed.
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # tutor-cambridge/


def _load_dotenv(path: Path | None = None) -> None:
    """Minimal .env loader: KEY=VALUE lines, '#' comments, no quoting tricks."""
    env = path if path is not None else ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


_load_dotenv()


def _get(name: str, default: str) -> str:
    return os.environ.get(name, default).strip()


MARKING_BASE = _get("MARKING_BASE", "http://localhost:3000").rstrip("/")
MARKING_KEY = _get("MARKING_KEY", "")
OLLAMA_BASE = _get("OLLAMA_BASE", "http://localhost:11434").rstrip("/")
TUTOR_MODEL = _get("TUTOR_MODEL", "qwen3.5:9b")
TUTOR_PORT = int(_get("TUTOR_PORT", "8780"))

# Local-first defaults on modest hardware: one model at a time, modest context.
NUM_CTX = int(_get("TUTOR_NUM_CTX", "8192"))
TEMPERATURE = float(_get("TUTOR_TEMPERATURE", "0.2"))
MAX_TOKENS = int(_get("TUTOR_MAX_TOKENS", "1024"))
KEEP_ALIVE = _get("TUTOR_KEEP_ALIVE", "10m")

# Hint ladder (tutor mode): level -> what the tutor may reveal.
HINT_MAX_WORDS = int(_get("TUTOR_HINT_MAX_WORDS", "120"))

DB_PATH = Path(_get("TUTOR_DB_PATH", str(ROOT / "data" / "tutor.db")))

PROFILES_PATH = Path(_get("TUTOR_PROFILES", str(ROOT / "profiles.toml")))
DEFAULT_PROFILE = _get("TUTOR_PROFILE", "default")

HTTP_TIMEOUT = float(_get("TUTOR_HTTP_TIMEOUT", "120"))

PROFILE_KEYS = ("model", "prompt", "think", "temperature", "num_ctx",
                "max_tokens", "keep_alive", "repeats", "limit")


def load_profiles(path: Path | None = None) -> dict[str, dict]:
    """Read profiles.toml; every profile inherits [default], unknown keys ignored."""
    import tomllib

    path = path or PROFILES_PATH
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    base = {k: v for k, v in (raw.get("default") or {}).items() if k in PROFILE_KEYS}
    profiles: dict[str, dict] = {}
    for name, values in raw.items():
        if not isinstance(values, dict):
            continue
        merged = dict(base)
        merged.update({k: v for k, v in values.items() if k in PROFILE_KEYS})
        profiles[name] = merged
    return profiles


def resolve_profile(name: str | None = None, overrides: dict | None = None,
                    path: Path | None = None) -> dict:
    """Named profile (falling back to [default] and then env/config defaults),
    with CLI overrides applied on top. Raises KeyError for an unknown profile."""
    profiles = load_profiles(path)
    name = name or DEFAULT_PROFILE
    if profiles and name not in profiles:
        raise KeyError(f"unknown profile '{name}' (available: {', '.join(sorted(profiles))})")
    resolved = dict(profiles.get(name) or profiles.get("default") or {})
    resolved.setdefault("model", TUTOR_MODEL)
    resolved.setdefault("prompt", "marker-full")
    resolved.setdefault("think", "off")
    resolved.setdefault("temperature", TEMPERATURE)
    resolved.setdefault("num_ctx", NUM_CTX)
    resolved.setdefault("max_tokens", MAX_TOKENS)
    resolved.setdefault("keep_alive", KEEP_ALIVE)
    resolved.setdefault("repeats", 1)
    resolved.setdefault("limit", 0)
    for key, value in (overrides or {}).items():
        if value is not None:
            resolved[key] = value
    resolved["name"] = name
    return resolved


def git_state() -> tuple[str, bool]:
    """(short commit, dirty) for run bookkeeping; ('unknown', False) outside git."""
    import subprocess

    try:
        head = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
            capture_output=True, text=True, timeout=5, check=True,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain"], cwd=ROOT,
            capture_output=True, text=True, timeout=5,
        ).stdout.strip() != ""
        return head, dirty
    except Exception:
        return "unknown", False
