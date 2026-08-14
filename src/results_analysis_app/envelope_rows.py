from __future__ import annotations

from collections.abc import Iterable, Mapping
import math
from typing import Any


def header_map(row: tuple[Any, ...]) -> dict[str, int]:
    return {
        str(value).strip().casefold(): index
        for index, value in enumerate(row)
        if value is not None and str(value).strip()
    }


def row_value(row: tuple[Any, ...], headers: Mapping[str, int], *names: str) -> Any:
    for name in names:
        index = headers.get(name.strip().casefold())
        if index is not None and index < len(row):
            return row[index]
    return None


def nearest_rows(
    worksheet,
    targets: Mapping[str, float],
    *,
    tolerance: float = 0.001,
) -> tuple[dict[str, int], dict[str, tuple[Any, ...] | None]]:
    rows: Iterable[tuple[Any, ...]] = worksheet.iter_rows(values_only=True)
    iterator = iter(rows)
    try:
        headers = header_map(tuple(next(iterator)))
    except StopIteration:
        return {}, {name: None for name in targets}

    time_col = headers.get("time (s)")
    if time_col is None:
        return headers, {name: None for name in targets}

    best: dict[str, tuple[float, tuple[Any, ...]] | None] = {
        name: None for name in targets
    }
    for row_values in iterator:
        row = tuple(row_values)
        if time_col >= len(row):
            continue
        try:
            actual = float(row[time_col])
        except (TypeError, ValueError):
            continue
        if not math.isfinite(actual):
            continue
        for name, target in targets.items():
            error = abs(actual - float(target))
            current = best[name]
            if error <= tolerance and (current is None or error < current[0]):
                best[name] = (error, row)

    return headers, {
        name: match[1] if match is not None else None
        for name, match in best.items()
    }
