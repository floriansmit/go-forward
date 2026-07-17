"""Shared facies-label configuration for the multi-realization builders."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT / "dashboard" / "facies_config.json"


def facies_names(config_path: Path | None = None) -> dict[int, str]:
    """Return configured labels keyed by facies code; missing codes remain valid."""
    path = config_path or DEFAULT_CONFIG_PATH
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return {int(code): str(label) for code, label in payload.get("facies_names", {}).items()}
    except (OSError, ValueError, TypeError):
        return {}


def facies_label(code: int, config_path: Path | None = None) -> str:
    """Get a display label for an observed code without restricting valid codes."""
    return facies_names(config_path).get(code, f"facies_{code}")
