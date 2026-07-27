"""Trusted local paths for Stage 2 storage composition."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LocalStorageConfig:
    """Application-supplied roots; never populated by model tool arguments."""

    database_path: Path
    private_memory_root: Path
    rules_directory: Path
