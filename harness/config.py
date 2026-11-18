"""Settings: .env / environment variables + run profiles (profiles.toml)."""

from __future__ import annotations

import os
import subprocess
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # tutor-cambridge/
PROMPTS_DIR = ROOT / "prompts"
RUNS_DIR = ROOT / "runs"


def _load_dotenv(path: Path = ROOT / ".env") -> None:
    """Minimal .env loader: KEY=VALUE lines, '#' comments. Real env vars win."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


_load_dotenv()

MARKING_BASE = os.environ.get("MARKING_BASE", "http://localhost:3000").rstrip("/")
MARKING_KEY = os.environ.get("MARKING_KEY", "")
OLLAMA_BASE = os.environ.get("OLLAMA_BASE", "http://localhost:11434").rstrip("/")
HTTP_TIMEOUT = float(os.environ.get("HTTP_TIMEOUT", "600"))  # CPU offload is slow

# Defaults for every profile; profiles.toml [default] and CLI flags override them.
DEFAULTS = {
    "model": os.environ.get("TUTOR_MODEL", "qwen3.5:9b"),
    "prompt": "marker-compact",
    "think": "off",
    "temperature": 0.2,
    "num_ctx": 4096,
    "max_tokens": 1024,
    "keep_alive": "10m",
    "repeats": 1,
    "limit": 5,          # few answers per run: the laptop is slow
    "question": "",      # only answers of this question id ("" = any)
    "post": "",          # deterministic rules after parsing (harness/post.py), e.g. "numeric,implied,sum"
}


def load_profile(name: str = "default", overrides: dict | None = None,
                 path: Path = ROOT / "profiles.toml") -> dict:
    """DEFAULTS <- [default] <- [name] <- CLI overrides (None = not given)."""
    raw = tomllib.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if name not in raw and name != "default":
        raise KeyError(f"unknown profile '{name}' (available: {', '.join(sorted(raw))})")
    profile = dict(DEFAULTS)
    for layer in (raw.get("default", {}), raw.get(name, {}), overrides or {}):
        profile.update({k: v for k, v in layer.items() if k in DEFAULTS and v is not None})
    profile["profile"] = name
    return profile


def git_state() -> tuple[str, bool]:
    """(short commit, dirty) recorded with every run."""
    try:
        head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                              capture_output=True, text=True, check=True).stdout.strip()
        dirty = bool(subprocess.run(["git", "status", "--porcelain"], cwd=ROOT,
                                    capture_output=True, text=True).stdout.strip())
        return head, dirty
    except Exception:
        return "unknown", False
