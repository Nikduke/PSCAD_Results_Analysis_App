"""Instantaneous-to-RMS conversion used by the optional Real RMS method.

The implementation follows the algorithm in the creator's RVC example:
the fundamental is used only to find zero crossings, while the RMS value is
integrated from the original instantaneous waveform over one cycle.  Values
are updated twice per cycle and held on the original PSCAD time grid.

This module intentionally uses NumPy only.  The application does not need a
SciPy dependency just to enable the method, and the small Butterworth SOS
implementation keeps the packaged application compact.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
import math
from pathlib import Path
import re

import numpy as np

from pscad_plotter_app_v3.services.waveform_io import (
    InfDescriptor,
    WaveformFrame,
    load_out_columns,
    parse_inf_descriptors,
    pgb_to_out_location,
    standard_out_file_path,
)


DEFAULT_REAL_RMS_FREQUENCY_HZ = 50.0
REAL_RMS_UPDATE_FREQUENCY = 2
REAL_RMS_FILTER_ORDER = 4
REAL_RMS_FILTER_CUTOFF_MULTIPLIER = 1.8


@dataclass(frozen=True, slots=True)
class RealRMSResult:
    """Computed RMS frame and scalar extrema for one MM quantity."""

    frame: WaveformFrame
    max_kv: float
    min_kv: float


def raw_group_frames(
    inf_path: str | Path,
    group_labels: Iterable[str],
    quantities: Iterable[str],
    *,
    check_cancel: Callable[[], None] | None = None,
) -> dict[tuple[str, str], WaveformFrame]:
    """Load selected raw groups with one source-file read per run."""
    descriptors = parse_inf_descriptors(Path(inf_path))
    selected_by_key: dict[tuple[str, str], list[InfDescriptor]] = {}
    for group_label in dict.fromkeys(str(value) for value in group_labels):
        for quantity in dict.fromkeys(str(value).strip().upper() for value in quantities):
            tag = "LGp" if quantity == "LG" else "LLp"
            pattern = re.compile(rf"(?:^|[_:]){re.escape(tag)}(?:$|[_:])")
            selected = sorted(
                (
                    descriptor
                    for descriptor in descriptors
                    if descriptor.Group == group_label
                    and pattern.search(str(descriptor.Description))
                ),
                key=lambda descriptor: descriptor.Description,
            )
            if selected:
                selected_by_key[(group_label, quantity)] = selected
    if not selected_by_key:
        raise ValueError("No selected instantaneous MM signals are available")

    rows_by_file: dict[int, list[InfDescriptor]] = {}
    for selected in selected_by_key.values():
        for descriptor in selected:
            file_number, _column_number = pgb_to_out_location(int(descriptor.PGB))
            rows_by_file.setdefault(file_number, []).append(descriptor)

    columns_by_pgb: dict[int, np.ndarray] = {}
    time_values: np.ndarray | None = None
    for file_number, rows in rows_by_file.items():
        if check_cancel is not None:
            check_cancel()
        rows = list({int(row.PGB): row for row in rows}.values())
        columns = [pgb_to_out_location(int(row.PGB))[1] for row in rows]
        out_path = standard_out_file_path(Path(inf_path), file_number)
        loaded = load_out_columns(out_path, [0, *columns], check_cancel)
        current_time = np.asarray(loaded[0], dtype=float)
        if time_values is None:
            time_values = current_time
        elif current_time.shape != time_values.shape or not np.allclose(
            current_time,
            time_values,
            rtol=0.0,
            atol=1e-12,
        ):
            raise ValueError(f"Inconsistent time axes in {out_path}")
        for row in rows:
            _file_number, column_number = pgb_to_out_location(int(row.PGB))
            columns_by_pgb[int(row.PGB)] = np.asarray(loaded[column_number], dtype=float)

    if time_values is None:
        raise ValueError(f"No waveform data available for {Path(inf_path).name}")

    frames: dict[tuple[str, str], WaveformFrame] = {}
    ll_mapping = {"a": "ab", "b": "bc", "c": "ca"}
    for (group_label, quantity), selected in selected_by_key.items():
        tag = "LGp" if quantity == "LG" else "LLp"
        values = [time_values]
        labels = ["Time (s)"]
        for descriptor in selected:
            description = str(descriptor.Description)
            phase = description.split(tag, 1)[-1].strip("_:")
            if tag == "LLp":
                phase = ll_mapping.get(phase, phase)
            values.append(columns_by_pgb[int(descriptor.PGB)])
            labels.append(f"V_{phase}")
        frames[(group_label, quantity)] = WaveformFrame(np.column_stack(values), labels)
    return frames


def compute_real_rms(
    frame: WaveformFrame,
    frequency_hz: float = DEFAULT_REAL_RMS_FREQUENCY_HZ,
    *,
    check_cancel: Callable[[], None] | None = None,
) -> RealRMSResult:
    """Compute creator-style full-wave RMS values from an instantaneous frame."""
    values = np.asarray(frame.values, dtype=float)
    if values.ndim != 2 or values.shape[1] < 2:
        raise ValueError("Real RMS requires a time column and at least one voltage channel")
    try:
        frequency = float(frequency_hz)
    except (TypeError, ValueError) as exc:
        raise ValueError("Real RMS frequency must be positive") from exc
    if not math.isfinite(frequency) or frequency <= 0:
        raise ValueError("Real RMS frequency must be positive")

    time_values = values[:, 0]
    signal_values = values[:, 1:]
    if time_values.size < 4:
        raise ValueError("Real RMS requires at least four samples")
    differences = np.diff(time_values)
    dt = float(np.median(differences))
    if (
        not math.isfinite(dt)
        or dt <= 0
        or not np.all(np.isfinite(time_values))
        or not np.all(np.isfinite(signal_values))
        or not np.all(differences > 0)
    ):
        raise ValueError("The time and voltage samples must be finite and chronological")
    if not np.allclose(differences, dt, rtol=0.001, atol=1e-9):
        raise ValueError("The instantaneous voltage samples must have a uniform time step")
    if REAL_RMS_UPDATE_FREQUENCY != 2:
        raise ValueError("Real RMS requires two updates per cycle")

    sample_rate = 1.0 / dt
    cycle_samples = int(round(sample_rate / frequency))
    if cycle_samples < 2:
        raise ValueError("Real RMS frequency is too high for the waveform sample rate")
    cutoff = frequency * REAL_RMS_FILTER_CUTOFF_MULTIPLIER
    if cutoff >= sample_rate / 2.0:
        raise ValueError("Real RMS filter cutoff exceeds the Nyquist frequency")
    sos = _butterworth_lowpass_sos(
        REAL_RMS_FILTER_ORDER,
        cutoff,
        sample_rate,
    )

    output = np.full_like(values, np.nan, dtype=float)
    output[:, 0] = time_values
    for channel_index in range(signal_values.shape[1]):
        if check_cancel is not None:
            check_cancel()
        voltage = signal_values[:, channel_index]
        extension = np.r_[
            np.tile(voltage[:cycle_samples], 3),
            voltage,
            np.tile(voltage[-cycle_samples:], 3),
        ]
        filtered = _sosfiltfilt(sos, extension)
        filtered = filtered[3 * cycle_samples : 3 * cycle_samples + voltage.size]
        crossing_indices = np.flatnonzero(
            np.signbit(filtered[1:]) != np.signbit(filtered[:-1])
        )
        if crossing_indices.size < 3:
            raise ValueError(f"Not enough fundamental zero crossings for channel {channel_index + 1}")
        left = filtered[crossing_indices]
        right = filtered[crossing_indices + 1]
        denominators = right - left
        valid = np.isfinite(left) & np.isfinite(right) & (denominators != 0)
        zero_times = time_values[crossing_indices[valid]] - left[valid] * (
            time_values[crossing_indices[valid] + 1]
            - time_values[crossing_indices[valid]]
        ) / denominators[valid]
        if zero_times.size < 3:
            raise ValueError(f"Not enough usable zero crossings for channel {channel_index + 1}")

        rms_times: list[float] = []
        rms_values: list[float] = []
        for index in range(zero_times.size - 2):
            if check_cancel is not None and index % 32 == 0:
                check_cancel()
            start = float(zero_times[index])
            stop = float(zero_times[index + 2])
            if not math.isfinite(start) or not math.isfinite(stop) or stop <= start:
                continue
            first = int(np.searchsorted(time_values, start, side="right"))
            last = int(np.searchsorted(time_values, stop, side="left"))
            sample_times = np.r_[
                start,
                time_values[first:last],
                stop,
            ]
            sample_values = np.r_[
                np.interp(start, time_values, voltage),
                voltage[first:last],
                np.interp(stop, time_values, voltage),
            ]
            integral = np.sum(
                (sample_values[:-1] ** 2 + sample_values[1:] ** 2)
                * np.diff(sample_times)
            )
            rms = math.sqrt(max(0.0, float(integral) / (2.0 * (stop - start))))
            rms_times.append(stop)
            rms_values.append(rms)

        update_array = np.asarray(rms_times, dtype=float)
        value_array = np.asarray(rms_values, dtype=float)
        if update_array.size:
            display = np.full(voltage.shape, np.nan, dtype=float)
            indices = np.searchsorted(time_values, update_array)
            valid_indices = indices < display.size
            display[indices[valid_indices]] = value_array[valid_indices]
            finite_display = np.isfinite(display)
            if np.any(finite_display):
                first_valid = int(np.flatnonzero(finite_display)[0])
                # Keep the explicit pass so the held waveform is identical to
                # pandas.Series.ffill(), including decreasing RMS values.
                last_value = math.nan
                for row_index in range(first_valid, display.size):
                    if math.isfinite(display[row_index]):
                        last_value = float(display[row_index])
                    elif math.isfinite(last_value):
                        display[row_index] = last_value
            output[:, channel_index + 1] = display

    finite_output = output[:, 1:][np.isfinite(output[:, 1:])]
    if finite_output.size == 0:
        raise ValueError("Real RMS produced no completed RMS windows")
    return RealRMSResult(
        frame=WaveformFrame(output, list(frame.columns)),
        max_kv=float(np.max(finite_output)),
        min_kv=float(np.min(finite_output)),
    )


def compute_groups_real_rms(
    inf_path: str | Path,
    group_labels: Iterable[str],
    quantities: Iterable[str],
    frequency_hz: float = DEFAULT_REAL_RMS_FREQUENCY_HZ,
    *,
    check_cancel: Callable[[], None] | None = None,
) -> dict[tuple[str, str], RealRMSResult]:
    """Compute selected groups after loading their source run only once."""
    frames = raw_group_frames(
        inf_path,
        group_labels,
        quantities,
        check_cancel=check_cancel,
    )
    results: dict[tuple[str, str], RealRMSResult] = {}
    for key, frame in frames.items():
        try:
            results[key] = compute_real_rms(
                frame,
                frequency_hz,
                check_cancel=check_cancel,
            )
        except (ValueError, IndexError):
            continue
    return results


def _butterworth_lowpass_sos(order: int, cutoff_hz: float, sample_rate_hz: float) -> np.ndarray:
    """Return digital Butterworth SOS coefficients for a low-pass filter."""
    if order <= 0 or order % 2:
        raise ValueError("Real RMS filter order must be a positive even number")
    warped = 2.0 * sample_rate_hz * math.tan(math.pi * cutoff_hz / sample_rate_hz)
    poles = [
        warped
        * np.exp(1j * math.pi * (2 * index + 1 + order) / (2 * order))
        for index in range(order)
    ]
    sections: list[list[float]] = []
    for pole in poles:
        if pole.imag <= 1e-12:
            continue
        conjugate = pole.conjugate()
        digital_pole_1 = (2.0 * sample_rate_hz + pole) / (2.0 * sample_rate_hz - pole)
        digital_pole_2 = (2.0 * sample_rate_hz + conjugate) / (2.0 * sample_rate_hz - conjugate)
        # The bilinear transform maps the analog zeros at infinity to z=-1.
        numerator = np.asarray([1.0, 2.0, 1.0], dtype=float)
        denominator = np.asarray(
            [
                1.0,
                -(digital_pole_1 + digital_pole_2).real,
                (digital_pole_1 * digital_pole_2).real,
            ],
            dtype=float,
        )
        sections.append([*numerator, denominator[1], denominator[2]])
    if len(sections) != order // 2:
        raise ValueError("Could not build the real RMS Butterworth filter")
    sos = np.asarray(sections, dtype=float)
    dc_gain = float(np.prod((sos[:, 0] + sos[:, 1] + sos[:, 2]) / (1.0 + sos[:, 3] + sos[:, 4])))
    if not math.isfinite(dc_gain) or dc_gain == 0:
        raise ValueError("Could not normalize the real RMS Butterworth filter")
    sos[0, :3] /= dc_gain
    return sos


def _sosfiltfilt(sos: np.ndarray, values: np.ndarray) -> np.ndarray:
    forward = _sosfilt(sos, values)
    backward = _sosfilt(sos, forward[::-1])
    return backward[::-1]


def _sosfilt(sos: np.ndarray, values: np.ndarray) -> np.ndarray:
    current = np.asarray(values, dtype=float)
    for b0, b1, b2, a1, a2 in np.asarray(sos, dtype=float):
        if current.size == 0:
            continue
        dc_gain = (b0 + b1 + b2) / (1.0 + a1 + a2)
        state_1 = (dc_gain - b0) * current[0]
        state_2 = (b2 - a2 * dc_gain) * current[0]
        filtered = np.empty_like(current)
        for index, sample in enumerate(current):
            result = b0 * sample + state_1
            state_1 = b1 * sample - a1 * result + state_2
            state_2 = b2 * sample - a2 * result
            filtered[index] = result
        current = filtered
    return current
