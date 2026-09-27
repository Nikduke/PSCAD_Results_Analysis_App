"""Compact project-local cache for derived envelope data per PSCAD run."""

from __future__ import annotations

from collections.abc import Mapping
import io
import json
from pathlib import Path
import sqlite3
from typing import Any, TypeAlias
import zipfile

import numpy as np
import pandas as pd

from results_analysis_app import storage


CACHE_VERSION = 1
SUSTAINED_ENTRY = "__Sustained_SDPF__"
RunData: TypeAlias = tuple[
    list[tuple[str, pd.DataFrame | list[dict[str, Any]]]],
    list[dict[str, Any]],
]


def _json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_value(item) for item in value]
    if isinstance(value, np.generic):
        return _json_value(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        return None
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


def _frame_value(frame: pd.DataFrame, column: str) -> str:
    if column not in frame.columns or frame.empty:
        return ""
    value = frame[column].iloc[0]
    return "" if value is None else str(value)


def _encode_run_data(run_data: RunData) -> bytes:
    entries, high_voltage = run_data
    arrays: dict[str, np.ndarray] = {}
    entry_metadata: list[dict[str, Any]] = []
    sustained_rows: list[dict[str, Any]] = []

    for index, (measurement, value) in enumerate(entries):
        if measurement == SUSTAINED_ENTRY:
            if isinstance(value, list):
                sustained_rows.extend(_json_value(value))
            continue
        if not isinstance(value, pd.DataFrame):
            raise TypeError("Envelope cache entries must contain DataFrames.")
        value_columns = [
            str(column)
            for column in value.columns
            if str(column).startswith("Max_")
        ]
        if not value_columns:
            continue
        time_name = f"time_{index}"
        values_name = f"values_{index}"
        arrays[time_name] = value.index.to_numpy(dtype=np.float32)
        arrays[values_name] = value[value_columns].to_numpy(dtype=np.float32)
        entry_metadata.append(
            {
                "measurement": str(measurement),
                "time": time_name,
                "values": values_name,
                "columns": value_columns,
                "mm_name": _frame_value(value, "MM_name"),
                "case": _frame_value(value, "Case"),
            }
        )

    metadata = {
        "version": CACHE_VERSION,
        "entries": entry_metadata,
        "high_voltage": _json_value(high_voltage),
        "sustained": sustained_rows,
    }
    arrays["metadata"] = np.frombuffer(
        json.dumps(metadata, separators=(",", ":"), ensure_ascii=True).encode("utf-8"),
        dtype=np.uint8,
    )
    output = io.BytesIO()
    np.savez_compressed(output, **arrays)
    return output.getvalue()


def _decode_run_data(payload: bytes) -> RunData:
    with np.load(io.BytesIO(payload), allow_pickle=False) as archive:
        raw_metadata = archive["metadata"].tobytes().decode("utf-8")
        metadata = json.loads(raw_metadata)
        if not isinstance(metadata, dict) or metadata.get("version") != CACHE_VERSION:
            raise ValueError("Unsupported envelope data cache version.")
        entries: list[tuple[str, pd.DataFrame | list[dict[str, Any]]]] = []
        raw_entries = metadata.get("entries", [])
        if not isinstance(raw_entries, list):
            raise ValueError("Invalid envelope data cache entries.")
        for item in raw_entries:
            if not isinstance(item, dict):
                raise ValueError("Invalid envelope data cache entry.")
            time_name = item.get("time")
            values_name = item.get("values")
            columns = item.get("columns")
            if (
                not isinstance(time_name, str)
                or not isinstance(values_name, str)
                or not isinstance(columns, list)
                or not columns
            ):
                raise ValueError("Invalid envelope data cache array metadata.")
            time_values = np.asarray(archive[time_name], dtype=float)
            values = np.asarray(archive[values_name], dtype=float)
            if values.ndim != 2 or values.shape != (len(time_values), len(columns)):
                raise ValueError("Envelope data cache array shape mismatch.")
            frame = pd.DataFrame(values, index=time_values, columns=[str(column) for column in columns])
            frame.index.name = "Time (s)"
            frame["MM_name"] = str(item.get("mm_name", ""))
            frame["Case"] = str(item.get("case", ""))
            entries.append((str(item.get("measurement", "")), frame))

        sustained = metadata.get("sustained", [])
        if not isinstance(sustained, list):
            raise ValueError("Invalid envelope data cache sustained rows.")
        if sustained:
            entries.append((SUSTAINED_ENTRY, sustained))

        high_voltage = metadata.get("high_voltage", [])
        if not isinstance(high_voltage, list):
            raise ValueError("Invalid envelope data cache high-voltage rows.")
        return entries, [dict(row) for row in high_voltage if isinstance(row, dict)]


class RunDataCache:
    """Read and write one compact SQLite row for each run and voltage."""

    def __init__(self, project_root: str | Path, *, enabled: bool = True) -> None:
        self.path = storage.project_envelope_data_cache_path(project_root)
        self._connection: sqlite3.Connection | None = None
        self._usable = bool(enabled)
        if not self._usable:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._connection = sqlite3.connect(self.path, timeout=30.0)
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS run_data_cache (
                    cache_key TEXT PRIMARY KEY,
                    calculation_signature TEXT NOT NULL,
                    source_signature TEXT NOT NULL,
                    payload BLOB NOT NULL
                )
                """
            )
            self._connection.commit()
        except (OSError, sqlite3.DatabaseError):
            self._usable = False
            if self._connection is not None:
                self._connection.close()
                self._connection = None

    def __enter__(self) -> "RunDataCache":
        return self

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        self.close()

    def get(
        self,
        cache_key: str,
        calculation_signature: str,
        source_signature: str,
    ) -> RunData | None:
        if not self._usable or self._connection is None:
            return None
        try:
            row = self._connection.execute(
                """
                SELECT payload
                FROM run_data_cache
                WHERE cache_key = ?
                  AND calculation_signature = ?
                  AND source_signature = ?
                """,
                (cache_key, calculation_signature, source_signature),
            ).fetchone()
            return None if row is None else _decode_run_data(bytes(row[0]))
        except (
            OSError,
            sqlite3.DatabaseError,
            TypeError,
            ValueError,
            KeyError,
            IndexError,
            json.JSONDecodeError,
            zipfile.BadZipFile,
        ):
            return None

    def put(
        self,
        cache_key: str,
        calculation_signature: str,
        source_signature: str,
        run_data: RunData,
    ) -> None:
        if not self._usable or self._connection is None:
            return
        try:
            payload = _encode_run_data(run_data)
            self._connection.execute(
                """
                INSERT INTO run_data_cache(
                    cache_key, calculation_signature, source_signature, payload
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    calculation_signature = excluded.calculation_signature,
                    source_signature = excluded.source_signature,
                    payload = excluded.payload
                """,
                (cache_key, calculation_signature, source_signature, payload),
            )
            # Cache writes are committed once when the build closes the
            # context, avoiding one filesystem sync per run.
        except (OSError, sqlite3.DatabaseError, TypeError, ValueError, KeyError):
            try:
                self._connection.rollback()
            except sqlite3.DatabaseError:
                self._usable = False

    def prune(self, valid_keys: set[str]) -> None:
        """Remove rows for source runs that no longer exist in the project."""
        if not self._usable or self._connection is None:
            return
        try:
            stored_keys = {
                str(row[0])
                for row in self._connection.execute("SELECT cache_key FROM run_data_cache")
            }
            stale_keys = stored_keys - valid_keys
            if stale_keys:
                self._connection.executemany(
                    "DELETE FROM run_data_cache WHERE cache_key = ?",
                    ((key,) for key in stale_keys),
                )
                self._connection.commit()
        except (OSError, sqlite3.DatabaseError):
            try:
                self._connection.rollback()
            except sqlite3.DatabaseError:
                self._usable = False

    def close(self) -> None:
        if self._connection is None:
            return
        try:
            try:
                self._connection.commit()
            except sqlite3.DatabaseError:
                self._usable = False
        finally:
            self._connection.close()
            self._connection = None
