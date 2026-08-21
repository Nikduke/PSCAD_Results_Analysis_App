"""Small, dependency-free helpers shared by analysis workflow stages."""

from __future__ import annotations

from collections.abc import Callable
import math
from pathlib import Path
from typing import Any

LogFn = Callable[[str], None]
CancelFn = Callable[[], None]


def log_message(log: LogFn | None, message: str) -> None:
    if log is not None:
        log(message)


def check_cancel(check: CancelFn | None) -> None:
    if check is not None:
        check()


def as_float(value: Any, *, finite: bool = True) -> float | None:
    """Parse a numeric value; reject blanks/NaN and infinity by default."""
    if value is None:
        return None
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or (finite and not math.isfinite(number)):
        return None
    return number


def as_bool(value: Any, default: bool = False) -> bool:
    """Parse the boolean values used by persisted settings consistently."""
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off", ""}:
            return False
    return default if value is None else bool(value)


def save_workbook_atomic(workbook: Any, path: Path) -> None:
    """Replace one generated workbook only after it has been saved fully."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        workbook.save(temporary)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
