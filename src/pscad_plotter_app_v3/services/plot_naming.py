"""Shared naming helpers for PNG and waveform-export outputs."""

from __future__ import annotations


def time_range_filename_token(start_s: float | None, end_s: float | None) -> str:
    if start_s is None and end_s is None:
        return ""
    if start_s is None:
        return f"Tto{float(end_s):g}s"
    if end_s is None:
        return f"Tfrom{float(start_s):g}s"
    return f"T{float(start_s):g}-{float(end_s):g}s"
