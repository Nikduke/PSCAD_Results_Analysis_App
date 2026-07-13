from __future__ import annotations

from collections.abc import Iterable
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np


@dataclass(slots=True)
class InfDescriptor:
    PGB: int
    Description: str
    Group: str
    Unit: str = ""


@dataclass(slots=True)
class WaveformFrame:
    values: np.ndarray
    columns: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.values = np.asarray(self.values, dtype=float)
        if self.values.ndim == 1:
            self.values = self.values.reshape(1, -1)
        if not self.columns:
            self.columns = [str(index) for index in range(self.values.shape[1])]
        if len(self.columns) != self.values.shape[1]:
            raise ValueError(f"Expected {self.values.shape[1]} column names, got {len(self.columns)}")

    @property
    def shape(self) -> tuple[int, int]:
        return self.values.shape

    def column_values(self, index: int) -> np.ndarray:
        return self.values[:, index]

    def renamed(self, columns: list[str]) -> "WaveformFrame":
        return WaveformFrame(self.values, list(columns))

    def time_window(self, start_s: float | None, end_s: float | None) -> "WaveformFrame":
        if start_s is None and end_s is None:
            return self
        if start_s is not None and end_s is not None and float(end_s) <= float(start_s):
            raise ValueError("Custom time range end must be greater than start.")
        time_values = self.column_values(0)
        mask = np.ones(time_values.shape, dtype=bool)
        if start_s is not None:
            mask &= time_values >= float(start_s)
        if end_s is not None:
            mask &= time_values <= float(end_s)
        if not np.any(mask):
            raise ValueError("Custom time range contains no data.")
        return WaveformFrame(self.values[mask], list(self.columns))

    def peak_abs(self) -> tuple[float, float, int]:
        if self.values.shape[1] < 2:
            raise ValueError(f"Expected at least 2 columns (time + signal), got {self.values.shape[1]}")
        y_values = self.values[:, 1:]
        flat_index = int(np.nanargmax(np.abs(y_values)))
        row_idx, y_col_idx = np.unravel_index(flat_index, y_values.shape)
        return float(self.values[row_idx, 0]), float(y_values[row_idx, y_col_idx]), int(y_col_idx)

    def y_limits(self, limits_pack: dict[str, float], pad_ratio: float) -> tuple[float, float]:
        y_values = self.values[:, 1:].reshape(-1)
        y_min = float(np.nanmin(y_values))
        y_max = float(np.nanmax(y_values))
        if limits_pack:
            y_min = min(y_min, -max(limits_pack.values()))
            y_max = max(y_max, max(limits_pack.values()))
        pad = (y_max - y_min) * pad_ratio if y_max != y_min else 1.0
        return y_min - pad, y_max + pad

    def rows_for_excel(self):
        yield list(self.columns)
        for row in self.values:
            yield [float(value) for value in row]


def parse_inf_descriptors(inf_path: Path) -> list[InfDescriptor]:
    records: list[InfDescriptor] = []
    with inf_path.open("r", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            if not line.strip().startswith("PGB"):
                continue
            desc = re.search(r'Desc\s*=\s*"([^"]+)"', line)
            group = re.search(r'Group\s*=\s*"([^"]+)"', line)
            pgb = re.search(r'PGB\((\d+)\)', line)
            unit = re.search(r'Units\s*=\s*"([^"]*)"', line)
            if pgb and desc and group:
                records.append(InfDescriptor(int(pgb.group(1)), desc.group(1), group.group(1), unit.group(1) if unit else ""))
    if not records:
        raise ValueError(f"{inf_path} contains no valid variable descriptors.")
    return sorted(records, key=lambda record: record.PGB)


def pgb_to_out_location(pgb: int) -> tuple[int, int]:
    return ((pgb - 1) // 10) + 1, ((pgb - 1) % 10) + 1


def case_run_from_inf_path(inf_path: Path) -> tuple[str, int]:
    match = re.match(r"(?P<case>.+?)_r(?P<run>\d+)$", inf_path.stem, flags=re.IGNORECASE)
    if not match:
        raise ValueError(f"Cannot read case/run from {inf_path.name}")
    return match.group("case"), int(match.group("run"))


def standard_out_file_path(inf_file: Path, file_number: int) -> Path:
    return inf_file.with_suffix("").with_name(f"{inf_file.stem}_{file_number:02d}.out")


def out_file_for_pgb(inf_file: Path, pgb: int) -> tuple[Path, int]:
    file_number, column_number = pgb_to_out_location(pgb)
    return standard_out_file_path(inf_file, file_number), column_number


def _missing_out_file_error(out_file: Path) -> FileNotFoundError:
    siblings = sorted(out_file.parent.glob("*.out"))
    sample_names = ", ".join(path.name for path in siblings[:5])
    detail = f"Expected .out file not found: {out_file}"
    if siblings:
        detail += (
            " | Available .out files in the same folder do not match the standard PSCAD legacy "
            f"stem-based naming. Sample files: {sample_names}"
        )
    return FileNotFoundError(detail)


def _first_time_value(line: str) -> float | None:
    stripped = line.strip()
    if not stripped:
        return None
    try:
        return float(stripped.split()[0])
    except (IndexError, ValueError):
        return None


def _reverse_text_lines(path: Path, block_size: int = 64 * 1024):
    with path.open("rb") as handle:
        handle.seek(0, 2)
        position = handle.tell()
        pending = b""
        while position > 0:
            read_size = min(block_size, position)
            position -= read_size
            handle.seek(position)
            chunk = handle.read(read_size)
            lines = (chunk + pending).splitlines()
            if position and lines:
                pending = lines[0]
                lines = lines[1:]
            else:
                pending = b""
            for line in reversed(lines):
                yield line.decode("utf-8", errors="ignore")
        if pending:
            yield pending.decode("utf-8", errors="ignore")


def read_out_time_bounds(out_file: Path) -> tuple[float, float]:
    if not out_file.exists():
        raise _missing_out_file_error(out_file)
    first_time: float | None = None
    with out_file.open("r", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            first_time = _first_time_value(line)
            if first_time is not None:
                break
    last_time: float | None = None
    for line in _reverse_text_lines(out_file):
        last_time = _first_time_value(line)
        if last_time is not None:
            break
    if first_time is None or last_time is None:
        raise ValueError(f"{out_file} contains no numeric time values.")
    return first_time, last_time


def load_out_frame(out_file: Path) -> WaveformFrame:
    if not out_file.exists():
        raise _missing_out_file_error(out_file)
    try:
        data = np.loadtxt(out_file, skiprows=1, ndmin=2)
        return WaveformFrame(data)
    except (OSError, ValueError, IndexError):
        rows: list[list[float]] = []
        with out_file.open("r", encoding="utf-8", errors="ignore") as handle:
            next(handle, None)
            for line in handle:
                stripped = line.strip()
                if not stripped:
                    continue
                rows.append([float(token) for token in stripped.split()])
        return WaveformFrame(np.asarray(rows, dtype=float))


def load_out_columns(out_file: Path, columns: Iterable[int]) -> dict[int, np.ndarray]:
    if not out_file.exists():
        raise _missing_out_file_error(out_file)
    ordered = list(dict.fromkeys(int(column) for column in columns))
    if not ordered:
        return {}
    values = np.loadtxt(
        out_file,
        dtype=np.float64,
        skiprows=1,
        usecols=ordered,
        ndmin=2,
    )
    values = np.asarray(values, dtype=np.float64)
    if values.ndim == 1:
        values = values.reshape(-1, 1)
    if values.shape[1] != len(ordered):
        values = values.reshape(-1, len(ordered))
    return {
        column: values[:, index]
        for index, column in enumerate(ordered)
    }
