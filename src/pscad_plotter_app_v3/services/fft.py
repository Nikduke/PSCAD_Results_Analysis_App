from __future__ import annotations

import math
import re
from dataclasses import dataclass

import numpy as np

from pscad_plotter_app_v3.models import (
    FFT_MAGNITUDE_PEAK,
    FFT_PHASE_DEGREES,
    FFT_REFERENCE_SINE,
)
from pscad_plotter_app_v3.services.waveform_io import WaveformFrame


FFT_MAX_HARMONIC_CHOICES = [7, 15, 31, 63, 127, 255, 511, 1023]


@dataclass(slots=True)
class RollingFFTResult:
    time_s: np.ndarray
    harmonic_numbers: list[int]
    harmonic_frequencies_hz: list[float]
    magnitudes: np.ndarray
    phase_angles: np.ndarray
    dc_component: np.ndarray


def samples_per_cycle_for_max_harmonic(max_harmonic: int) -> int:
    if int(max_harmonic) not in FFT_MAX_HARMONIC_CHOICES:
        raise ValueError(f"Max harmonic must be one of: {', '.join(str(value) for value in FFT_MAX_HARMONIC_CHOICES)}.")
    return 2 * (int(max_harmonic) + 1)


def parse_harmonic_selection(value: str, max_harmonic: int) -> list[int]:
    token = value.strip()
    if not token:
        raise ValueError("Select at least one harmonic.")
    harmonics: set[int] = set()
    for part in re.split(r"[,;\s]+", token):
        if not part:
            continue
        if "-" in part:
            bounds = [item.strip() for item in part.split("-", 1)]
            if len(bounds) != 2 or not bounds[0] or not bounds[1]:
                raise ValueError(f"Invalid harmonic range '{part}'.")
            start, stop = int(bounds[0]), int(bounds[1])
            if start > stop:
                raise ValueError(f"Invalid harmonic range '{part}'.")
            harmonics.update(range(start, stop + 1))
        else:
            harmonics.add(int(part))
    if not harmonics:
        raise ValueError("Select at least one harmonic.")
    invalid = [harmonic for harmonic in sorted(harmonics) if harmonic < 1 or harmonic > int(max_harmonic)]
    if invalid:
        raise ValueError(f"Harmonic {invalid[0]} is outside 1-{int(max_harmonic)}.")
    return sorted(harmonics)


def rolling_fft(
    frame: WaveformFrame,
    *,
    base_frequency_hz: float,
    max_harmonic: int,
    harmonics: list[int],
    magnitude_mode: str,
    phase_units: str,
    phase_reference: str,
) -> RollingFFTResult:
    if base_frequency_hz <= 0:
        raise ValueError("Base frequency must be greater than zero.")
    if frame.values.shape[1] != 2:
        raise ValueError("FFT requires one time column and one signal column.")
    samples_per_cycle = samples_per_cycle_for_max_harmonic(max_harmonic)
    if any(harmonic > int(max_harmonic) for harmonic in harmonics):
        raise ValueError(f"Selected harmonics must be within 1-{int(max_harmonic)}.")

    time_values = np.asarray(frame.column_values(0), dtype=float)
    signal_values = np.asarray(frame.column_values(1), dtype=float)
    valid_mask = np.isfinite(time_values) & np.isfinite(signal_values)
    time_values = time_values[valid_mask]
    signal_values = signal_values[valid_mask]
    if time_values.size < 2:
        raise ValueError("FFT requires at least two valid samples.")
    order = np.argsort(time_values)
    time_values = time_values[order]
    signal_values = signal_values[order]
    unique_times, unique_indices = np.unique(time_values, return_index=True)
    time_values = unique_times
    signal_values = signal_values[unique_indices]

    cycle_s = 1.0 / float(base_frequency_hz)
    sample_step_s = cycle_s / samples_per_cycle
    start_s = float(time_values[0])
    end_s = float(time_values[-1])
    if end_s - start_s < cycle_s:
        raise ValueError("FFT requires at least one base-frequency cycle of data.")

    resampled_time = np.arange(start_s, end_s + sample_step_s * 0.5, sample_step_s)
    resampled_signal = np.interp(resampled_time, time_values, signal_values)
    window_count = resampled_signal.size - samples_per_cycle + 1
    if window_count <= 0:
        raise ValueError("FFT requires at least one full base-frequency cycle of data.")

    output_time = resampled_time[samples_per_cycle - 1 :]
    magnitudes = np.empty((window_count, len(harmonics)), dtype=float)
    phase_angles = np.empty((window_count, len(harmonics)), dtype=float)
    dc_component = np.empty(window_count, dtype=float)
    rms_scale = 1.0 if magnitude_mode == FFT_MAGNITUDE_PEAK else 1.0 / math.sqrt(2.0)

    for output_index in range(window_count):
        window = resampled_signal[output_index : output_index + samples_per_cycle]
        spectrum = np.fft.rfft(window)
        window_start_s = float(resampled_time[output_index])
        dc_component[output_index] = float(np.real(spectrum[0]) / samples_per_cycle)
        for harmonic_index, harmonic in enumerate(harmonics):
            complex_peak = (2.0 * spectrum[harmonic] / samples_per_cycle) * np.exp(
                -1j * 2.0 * math.pi * harmonic * base_frequency_hz * window_start_s
            )
            magnitudes[output_index, harmonic_index] = abs(complex_peak) * rms_scale
            phase = math.atan2(float(np.imag(complex_peak)), float(np.real(complex_peak)))
            if phase_reference == FFT_REFERENCE_SINE:
                phase += math.pi / 2.0
            phase = _wrap_radians(phase)
            if phase_units == FFT_PHASE_DEGREES:
                phase = math.degrees(phase)
            phase_angles[output_index, harmonic_index] = phase

    return RollingFFTResult(
        time_s=output_time,
        harmonic_numbers=list(harmonics),
        harmonic_frequencies_hz=[float(harmonic) * float(base_frequency_hz) for harmonic in harmonics],
        magnitudes=magnitudes,
        phase_angles=phase_angles,
        dc_component=dc_component,
    )


def _wrap_radians(value: float) -> float:
    return (value + math.pi) % (2.0 * math.pi) - math.pi
