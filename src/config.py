"""Application configuration loader (YAML -> dict with fail-soft defaults)."""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict

import yaml

ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_SETTINGS_PATH = ROOT_DIR / "config" / "settings.yaml"

logger = logging.getLogger(__name__)


def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively merge override on top of base."""
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def settings_path() -> Path:
    return DEFAULT_SETTINGS_PATH


@lru_cache(maxsize=1)
def load_settings(path: str | Path | None = None) -> Dict[str, Any]:
    """Load settings once per process; anchored on the repo's settings.yaml."""
    target = Path(path) if path else DEFAULT_SETTINGS_PATH
    if target.exists():
        with open(target, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
        return raw
    logger.warning("Settings file not found at %s — using built-in defaults.", target)
    return {}