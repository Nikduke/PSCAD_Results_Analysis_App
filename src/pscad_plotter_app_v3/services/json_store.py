from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


def read_json_file(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        quarantine_corrupt_file(path)
        return None


def quarantine_corrupt_file(path: Path) -> None:
    if not path.exists():
        return
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    target = path.with_name(f"{path.stem}.corrupt-{timestamp}{path.suffix}")
    suffix = 1
    while target.exists():
        target = path.with_name(f"{path.stem}.corrupt-{timestamp}-{suffix}{path.suffix}")
        suffix += 1
    try:
        path.replace(target)
    except OSError:
        pass
