from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any

from results_analysis_app.models import AppSession


def _app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


APP_ROOT = _app_root()
STATE_DIR = APP_ROOT / ".state"
SESSION_DIR = APP_ROOT / "sessions"
AUTOSAVE_PATH = STATE_DIR / "last_session.json"
PROJECT_SCAN_CACHE_PATH = STATE_DIR / "project_scan_cache.json"
PROJECT_ANALYSIS_CACHE_FILENAME = "analysis_cache.json"
PROJECT_ANALYSIS_CACHE_VERSION = 1


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return value


def write_json(path: Path, data: dict[str, Any], *, indent: int | None = 2) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with temp_path.open("w", encoding="utf-8") as handle:
        if indent is None:
            json.dump(data, handle, separators=(",", ":"))
        else:
            json.dump(data, handle, indent=indent)
        handle.write("\n")
    temp_path.replace(path)


def project_analysis_cache_path(project_root: str | Path) -> Path:
    """Return the single compact cache file kept with one PSCAD project."""
    return Path(project_root) / ".state" / PROJECT_ANALYSIS_CACHE_FILENAME


def load_project_analysis_cache(project_root: str | Path) -> dict[str, Any]:
    """Load stage fingerprints without treating them as source data."""
    path = project_analysis_cache_path(project_root)
    try:
        payload = read_json(path)
    except (OSError, UnicodeDecodeError, TypeError, ValueError, json.JSONDecodeError):
        return {"version": PROJECT_ANALYSIS_CACHE_VERSION}
    if payload.get("version") != PROJECT_ANALYSIS_CACHE_VERSION:
        return {"version": PROJECT_ANALYSIS_CACHE_VERSION}
    return payload


def save_project_analysis_cache(project_root: str | Path, payload: dict[str, Any]) -> None:
    """Persist only compact stage metadata in one project-local file."""
    value = dict(payload)
    value["version"] = PROJECT_ANALYSIS_CACHE_VERSION
    write_json(project_analysis_cache_path(project_root), value, indent=None)


def load_autosave() -> AppSession:
    if not AUTOSAVE_PATH.is_file():
        return AppSession.default()
    try:
        return AppSession.from_dict(read_json(AUTOSAVE_PATH))
    except (OSError, UnicodeDecodeError, TypeError, ValueError, json.JSONDecodeError):
        return AppSession.default()


def save_autosave(session: AppSession) -> None:
    write_json(AUTOSAVE_PATH, session.to_dict())


def clear_autosave() -> None:
    if AUTOSAVE_PATH.exists():
        AUTOSAVE_PATH.unlink()


def save_session(path: Path, session: AppSession) -> None:
    write_json(path, session.to_dict())


def load_session(path: Path) -> AppSession:
    return AppSession.from_dict(read_json(path))
