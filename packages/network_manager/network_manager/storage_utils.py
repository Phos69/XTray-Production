"""Shared filesystem helpers for Network Manager persistence."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def network_manager_data_dir() -> Path:
    root = os.environ.get("APPDATA")
    base = Path(root) if root else Path.home() / ".config"
    path = base / "Network_Manager"
    path.mkdir(parents=True, exist_ok=True)
    return path


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    serialized = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_name = tempfile.mkstemp(prefix=f".{path.stem}.", suffix=".tmp", dir=str(parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise
