from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable

import numpy as np


SUSTAINED_SDPF = "Sustained_SDPF"
RESULT_FILENAME = "Sustained_SDpf.json"
DEFAULT_DURATION_S = 0.03
DEFAULT_USE_TOV_SETTING = True
SDPF_MARGIN_FACTOR = 0.85


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off", ""}:
            return False
    return default if value is None else bool(value)


@dataclass(frozen=True, slots=True)
class SustainedSDPFSettings:
    enabled: bool = False
    use_tov_setting: bool = DEFAULT_USE_TOV_SETTING
    duration_s: float = DEFAULT_DURATION_S

    @classmethod
    def from_mapping(cls, data: dict[str, Any] | None) -> "SustainedSDPFSettings":
        data = data if isinstance(data, dict) else {}
        raw_duration = data.get("duration_s", data.get("custom_duration", data.get("duration", DEFAULT_DURATION_S)))
        try:
            duration = float(raw_duration)
        except (TypeError, ValueError):
            duration = DEFAULT_DURATION_S
        if not math.isfinite(duration) or duration <= 0:
            duration = DEFAULT_DURATION_S
        return cls(
            enabled=_as_bool(data.get("enabled", data.get("sustained_sdpf_enabled", False))),
            use_tov_setting=_as_bool(
                data.get("use_tov_setting", data.get("sustained_sdpf_use_tov", DEFAULT_USE_TOV_SETTING))
            ),
            duration_s=duration,
        )

    @classmethod
    def from_session(cls, session: Any) -> "SustainedSDPFSettings":
        return cls.from_mapping(
            {
                "enabled": getattr(session, "sustained_sdpf_enabled", False),
                "use_tov_setting": getattr(session, "sustained_sdpf_use_tov", DEFAULT_USE_TOV_SETTING),
                "duration_s": getattr(session, "sustained_sdpf_duration", DEFAULT_DURATION_S),
            }
        )

    def effective_duration(self, event_times: dict[str, float] | None = None) -> float:
        if self.use_tov_setting:
            try:
                source = event_times if isinstance(event_times, dict) else {}
                tov = float(source.get("TOV", DEFAULT_DURATION_S))
            except (TypeError, ValueError):
                tov = DEFAULT_DURATION_S
            if math.isfinite(tov) and tov > 0:
                return tov
        return self.duration_s

    def to_mapping(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SDPFVoltageLimits:
    voltage_kv: float
    sdpf_lg_rms: float
    sdpf_ll_rms: float
    source: str = "workbook"

    def rms(self, measurement: str) -> float:
        return self.sdpf_lg_rms if measurement == "LGp" else self.sdpf_ll_rms

    def peak(self, measurement: str) -> float:
        return self.rms(measurement) * math.sqrt(2.0)

    def margin_rms(self, measurement: str) -> float:
        return SDPF_MARGIN_FACTOR * self.rms(measurement)

    def margin_peak(self, measurement: str) -> float:
        return SDPF_MARGIN_FACTOR * self.peak(measurement)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def resolve_project_limits(project_root: str | Path) -> tuple[dict[str, SDPFVoltageLimits], list[str]]:
    """Reuse the embedded plotter's effective MM limit source."""
    from pscad_plotter_app_v3.services.limits import LimitService
    from pscad_plotter_app_v3.services.project import ProjectDiscoveryService

    try:
        context = ProjectDiscoveryService().discover(project_root)
    except (OSError, ValueError):
        return {}, ["Could not inspect the project while resolving SDPF limits."]
    service = LimitService()
    workbook_limits, warnings = service.load_workbook_limits_with_warnings(context.workbook_path)
    try:
        overrides = service.load_override_limits(context.state_dir / service.LIMITS_FILENAME)
    except (OSError, TypeError, ValueError, KeyError):
        warnings.append("Invalid embedded plotter SDPF overrides; workbook limits used.")
        overrides = {}
    effective = dict(workbook_limits)
    effective.update(overrides)
    resolved: dict[str, SDPFVoltageLimits] = {}
    for key, limit in effective.items():
        try:
            voltage = float(limit.voltage_kv)
            lg = float(limit.sdpf_lg)
            ll = float(limit.sdpf_ll)
        except (AttributeError, TypeError, ValueError):
            warnings.append(f"Invalid SDPF limits for {key} kV; assessment skipped.")
            continue
        if not all(math.isfinite(value) and value > 0 for value in (voltage, lg, ll)):
            warnings.append(f"Invalid SDPF limits for {key} kV; assessment skipped.")
            continue
        resolved[f"{voltage:g}"] = SDPFVoltageLimits(voltage, lg, ll, str(getattr(limit, "source", "workbook")))
    return resolved, warnings


@dataclass(frozen=True, slots=True)
class PhaseStressResult:
    measurement: str
    phase: str
    sdpf_rms_kv: float
    sdpf_peak_kv: float
    margin_rms_kv: float
    margin_peak_kv: float
    longest_margin_s: float
    longest_sdpf_s: float
    sustained_peak_kv: float
    sustained_rms_kv: float
    sustained_ratio: float
    classification: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PhaseStressResult":
        return cls(
            measurement=str(data.get("measurement", "")),
            phase=str(data.get("phase", "")),
            sdpf_rms_kv=float(data.get("sdpf_rms_kv", 0.0)),
            sdpf_peak_kv=float(data.get("sdpf_peak_kv", 0.0)),
            margin_rms_kv=float(data.get("margin_rms_kv", 0.0)),
            margin_peak_kv=float(data.get("margin_peak_kv", 0.0)),
            longest_margin_s=float(data.get("longest_margin_s", 0.0)),
            longest_sdpf_s=float(data.get("longest_sdpf_s", 0.0)),
            sustained_peak_kv=float(data.get("sustained_peak_kv", 0.0)),
            sustained_rms_kv=float(data.get("sustained_rms_kv", 0.0)),
            sustained_ratio=float(data.get("sustained_ratio", 0.0)),
            classification=str(data.get("classification", "")),
        )


@dataclass(frozen=True, slots=True)
class SustainedSDPFResult:
    scope_folder: str
    voltage: str
    case: str
    run: int
    mm_name: str
    fault_type: str
    duration_s: float
    governing: PhaseStressResult
    phases: tuple[PhaseStressResult, ...]
    signature: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "scope_folder": self.scope_folder,
            "voltage": self.voltage,
            "case": self.case,
            "run": self.run,
            "mm_name": self.mm_name,
            "fault_type": self.fault_type,
            "duration_s": self.duration_s,
            "governing": self.governing.to_dict(),
            "phases": [phase.to_dict() for phase in self.phases],
            "signature": self.signature,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SustainedSDPFResult":
        governing = PhaseStressResult.from_dict(data.get("governing", {}))
        phases = tuple(
            PhaseStressResult.from_dict(item)
            for item in data.get("phases", [])
            if isinstance(item, dict)
        )
        return cls(
            scope_folder=str(data.get("scope_folder", "")),
            voltage=str(data.get("voltage", "")),
            case=str(data.get("case", "")),
            run=int(float(data.get("run", 0))),
            mm_name=str(data.get("mm_name", "")),
            fault_type=str(data.get("fault_type", "")),
            duration_s=float(data.get("duration_s", 0.0)),
            governing=governing,
            phases=phases,
            signature=str(data.get("signature", "")),
        )


def _clean_track(time: np.ndarray, values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    time = np.asarray(time, dtype=float)
    values = np.asarray(values, dtype=float)
    if time.shape != values.shape:
        raise ValueError("Time and amplitude arrays must have the same shape.")
    finite = np.isfinite(time) & np.isfinite(values)
    time = time[finite]
    values = values[finite]
    if len(time) < 2:
        return np.array([], dtype=float), np.array([], dtype=float)
    order = np.argsort(time, kind="stable")
    time = time[order]
    values = np.maximum(values[order], 0.0)
    unique, indices = np.unique(time, return_index=True)
    if len(unique) != len(time):
        values = np.maximum.reduceat(values, indices)
        time = unique
    return time, values


def threshold_intervals(time: np.ndarray, values: np.ndarray, threshold: float) -> list[tuple[float, float]]:
    """Return continuous threshold intervals using linear crossing times."""
    raw_time = np.asarray(time, dtype=float)
    raw_values = np.asarray(values, dtype=float)
    if raw_time.shape != raw_values.shape:
        raise ValueError("Time and amplitude arrays must have the same shape.")
    finite_time = np.isfinite(raw_time)
    if finite_time.sum() < 2:
        return []
    order = np.argsort(raw_time[finite_time], kind="stable")
    sorted_time = raw_time[finite_time][order]
    sorted_values = raw_values[finite_time][order]
    all_intervals: list[tuple[float, float]] = []
    segment_start = 0
    for index in range(len(sorted_time) + 1):
        if index < len(sorted_time) and math.isfinite(sorted_values[index]):
            continue
        if index - segment_start >= 2:
            all_intervals.extend(_threshold_intervals_finite(sorted_time[segment_start:index], sorted_values[segment_start:index], threshold))
        segment_start = index + 1
    return _merge_intervals(all_intervals)


def _threshold_intervals_finite(time: np.ndarray, values: np.ndarray, threshold: float) -> list[tuple[float, float]]:
    time, values = _clean_track(time, values)
    if len(time) < 2 or not math.isfinite(threshold):
        return []
    intervals: list[tuple[float, float]] = []
    start: float | None = None
    for index in range(len(time) - 1):
        t0, t1 = float(time[index]), float(time[index + 1])
        y0, y1 = float(values[index]), float(values[index + 1])
        if t1 <= t0:
            continue
        above0 = y0 >= threshold
        above1 = y1 >= threshold
        if above0 and start is None:
            start = t0
        if above0 == above1:
            continue
        if y1 == y0:
            crossing = t0
        else:
            crossing = t0 + (threshold - y0) * (t1 - t0) / (y1 - y0)
            crossing = min(t1, max(t0, crossing))
        if above0:
            intervals.append((start if start is not None else t0, crossing))
            start = None
        else:
            start = crossing
    if start is not None and values[-1] >= threshold:
        intervals.append((start, float(time[-1])))
    return _merge_intervals(intervals)


def _merge_intervals(intervals: Iterable[tuple[float, float]]) -> list[tuple[float, float]]:
    merged: list[tuple[float, float]] = []
    for start, end in sorted((float(a), float(b)) for a, b in intervals if b >= a):
        if not merged or start > merged[-1][1] + 1e-12:
            merged.append((start, end))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
    return merged


def longest_duration_above(time: np.ndarray, values: np.ndarray, threshold: float) -> float:
    intervals = threshold_intervals(time, values, threshold)
    return max((end - start for start, end in intervals), default=0.0)


def highest_sustained_level(time: np.ndarray, values: np.ndarray, duration_s: float) -> float:
    """Find the highest level present continuously for the requested duration."""
    raw_time = np.asarray(time, dtype=float)
    raw_values = np.asarray(values, dtype=float)
    if raw_time.shape != raw_values.shape:
        raise ValueError("Time and amplitude arrays must have the same shape.")
    finite_time = np.isfinite(raw_time)
    if finite_time.sum() < 2:
        return 0.0
    order = np.argsort(raw_time[finite_time], kind="stable")
    sorted_time = raw_time[finite_time][order]
    sorted_values = raw_values[finite_time][order]
    if duration_s <= 0:
        finite_values = sorted_values[np.isfinite(sorted_values)]
        return float(np.nanmax(finite_values)) if len(finite_values) else 0.0

    best = 0.0
    segment_start = 0
    for index in range(len(sorted_time) + 1):
        if index < len(sorted_time) and math.isfinite(sorted_values[index]):
            continue
        segment_end = index
        segment_time, segment_values = _clean_track(
            sorted_time[segment_start:segment_end],
            sorted_values[segment_start:segment_end],
        )
        if len(segment_time) >= 2 and segment_time[-1] - segment_time[0] >= duration_s:
            queue: deque[int] = deque()
            right = -1
            for left in range(len(segment_time)):
                target = segment_time[left] + duration_s
                while right + 1 < len(segment_time) and segment_time[right + 1] <= target:
                    right += 1
                    while queue and segment_values[queue[-1]] >= segment_values[right]:
                        queue.pop()
                    queue.append(right)
                while queue and queue[0] < left:
                    queue.popleft()
                if right < left or right >= len(segment_time):
                    continue
                candidate = float(segment_values[queue[0]]) if queue else math.inf
                if segment_time[right] < target:
                    if right + 1 >= len(segment_time):
                        continue
                    next_index = right + 1
                    fraction = (target - segment_time[right]) / (segment_time[next_index] - segment_time[right])
                    endpoint = segment_values[right] + fraction * (segment_values[next_index] - segment_values[right])
                    candidate = min(candidate, float(endpoint))
                best = max(best, candidate)
        segment_start = index + 1
    return best


def analyze_phase_amplitude(
    time: np.ndarray,
    amplitude_peak: np.ndarray,
    measurement: str,
    phase: str,
    sdpf_rms: float,
    duration_s: float,
) -> PhaseStressResult:
    sdpf_peak = float(sdpf_rms) * math.sqrt(2.0)
    margin_peak = SDPF_MARGIN_FACTOR * sdpf_peak
    margin_duration = longest_duration_above(time, amplitude_peak, margin_peak)
    sdpf_duration = longest_duration_above(time, amplitude_peak, sdpf_peak)
    sustained_peak = highest_sustained_level(time, amplitude_peak, duration_s)
    ratio = sustained_peak / sdpf_peak if sdpf_peak > 0 else 0.0
    if sdpf_duration + 1e-12 >= duration_s:
        classification = "SDPF exceeded for >= duration"
    elif margin_duration + 1e-12 >= duration_s:
        classification = "SDPF safety margin exceeded; SDPF not exceeded for >= duration"
    else:
        classification = "No SDPF safety-margin exceedance sustained for >= duration"
    return PhaseStressResult(
        measurement=measurement,
        phase=phase,
        sdpf_rms_kv=float(sdpf_rms),
        sdpf_peak_kv=sdpf_peak,
        margin_rms_kv=SDPF_MARGIN_FACTOR * float(sdpf_rms),
        margin_peak_kv=margin_peak,
        longest_margin_s=margin_duration,
        longest_sdpf_s=sdpf_duration,
        sustained_peak_kv=sustained_peak,
        sustained_rms_kv=sustained_peak / math.sqrt(2.0),
        sustained_ratio=ratio,
        classification=classification,
    )


def _half_cycle_amplitude_track(time: np.ndarray, values: np.ndarray, frequency_hz: float) -> tuple[np.ndarray, np.ndarray]:
    """Build a chronological peak track without centred-window edge extension."""
    time = np.asarray(time, dtype=float)
    values = np.asarray(values, dtype=float)
    finite_time = np.isfinite(time)
    time, values = time[finite_time], np.abs(values[finite_time])
    if len(time) < 2:
        return np.array([], dtype=float), np.array([], dtype=float)
    order = np.argsort(time, kind="stable")
    time, values = time[order], values[order]
    if not math.isfinite(frequency_hz) or frequency_hz <= 0:
        return time, values
    half_cycle = 1.0 / (2.0 * frequency_hz)
    if half_cycle <= 0:
        return time, values
    finite_values = np.isfinite(values)
    finite_padded = np.r_[False, finite_values, False]
    segment_starts = np.flatnonzero(~finite_padded[:-1] & finite_padded[1:])
    segment_ends = np.flatnonzero(finite_padded[:-1] & ~finite_padded[1:])

    peak_times: list[float] = []
    peak_values: list[float] = []
    for segment_start, segment_end in zip(segment_starts, segment_ends):
        segment_time = time[segment_start:segment_end]
        segment_values = values[segment_start:segment_end]
        if len(segment_time) == 0:
            continue
        edges = np.arange(float(segment_time[0]), float(segment_time[-1]) + half_cycle, half_cycle)
        if len(edges) < 2 or edges[-1] < segment_time[-1]:
            edges = np.append(edges, float(segment_time[-1]))
        bin_count = len(edges) - 1
        bin_indices = np.searchsorted(edges, segment_time, side="right") - 1
        bin_indices = np.minimum(bin_indices, bin_count - 1)

        # Assign each sample to one half-cycle and reduce all bins in one pass.
        # This preserves the first maximum in each bin while avoiding a full
        # boolean scan of the segment for every edge interval.
        bin_maxima = np.full(bin_count, -np.inf, dtype=float)
        np.maximum.at(bin_maxima, bin_indices, segment_values)
        sample_indices = np.arange(len(segment_time), dtype=np.int64)
        first_maxima = np.full(bin_count, len(segment_time), dtype=np.int64)
        is_first_maximum = segment_values == bin_maxima[bin_indices]
        np.minimum.at(
            first_maxima,
            bin_indices,
            np.where(is_first_maximum, sample_indices, len(segment_time)),
        )
        present_bins = first_maxima < len(segment_time)
        peak_times.extend(segment_time[first_maxima[present_bins]].tolist())
        peak_values.extend(bin_maxima[present_bins].tolist())
        if segment_end < len(values) and peak_times:
            separator = (float(segment_time[-1]) + float(time[segment_end])) / 2.0
            peak_times.append(separator)
            peak_values.append(math.nan)
    if len([value for value in peak_values if math.isfinite(value)]) < 2:
        return time, values
    return np.asarray(peak_times, dtype=float), np.asarray(peak_values, dtype=float)


def analyze_waveform(
    time: np.ndarray,
    values: np.ndarray,
    measurement: str,
    phase: str,
    sdpf_rms: float,
    duration_s: float,
    frequency_hz: float,
) -> PhaseStressResult:
    track_time, track_values = _half_cycle_amplitude_track(time, values, frequency_hz)
    return analyze_phase_amplitude(track_time, track_values, measurement, phase, sdpf_rms, duration_s)


def analyze_bus_waveforms(
    measurement: str,
    times: Iterable[np.ndarray],
    values: Iterable[np.ndarray],
    signals: Iterable[str],
    limits: SDPFVoltageLimits,
    case: str,
    run: int,
    mm_name: str,
    duration_s: float,
    frequency_hz: float,
) -> list[dict[str, Any]]:
    labels = phase_labels(measurement, signals)
    sdpf_rms = limits.rms(measurement)
    rows: list[dict[str, Any]] = []
    for index, (time, waveform) in enumerate(zip(times, values)):
        result = analyze_waveform(
            time,
            waveform,
            measurement,
            labels[index] if index < len(labels) else f"Phase {index + 1}",
            sdpf_rms,
            duration_s,
            frequency_hz,
        )
        rows.append(
            {
                "case": str(case),
                "run": int(run),
                "mm_name": str(mm_name),
                **result.to_dict(),
            }
        )
    return rows


def phase_labels(measurement: str, signals: Iterable[str]) -> list[str]:
    labels: list[str] = []
    fallback_lg = ("A-G", "B-G", "C-G")
    fallback_ll = ("A-B", "B-C", "C-A")
    for index, signal in enumerate(signals):
        text = str(signal).upper().replace("_", "-")
        if measurement == "LGp":
            match = next((phase for phase in "ABC" if re_search_phase(text, phase)), None)
            labels.append(f"{match or fallback_lg[min(index, 2)][0]}-G")
        else:
            match = next((pair for pair in ("AB", "BC", "CA") if pair in text.replace("-", "")), None)
            labels.append(
                f"{match[0]}-{match[1]}" if match else fallback_ll[min(index, 2)]
            )
    return labels


def re_search_phase(text: str, phase: str) -> bool:
    tokens = [token for token in text.replace(":", "-").split("-") if token]
    return phase in tokens or text.endswith(f"-{phase}") or text.endswith(f"{phase}")


def classify_rows(
    scope_folder: str,
    voltage: str,
    case: str,
    run: int,
    mm_name: str,
    rows: Iterable[PhaseStressResult],
    duration_s: float,
    fault_type: str = "",
    signature: str = "",
) -> SustainedSDPFResult | None:
    phases = tuple(row for row in rows if isinstance(row, PhaseStressResult))
    if not phases:
        return None
    governing = max(
        phases,
        key=lambda row: (
            row.sustained_ratio,
            row.sustained_peak_kv,
            row.longest_margin_s,
            -len(row.phase),
            row.measurement,
            row.phase,
        ),
    )
    return SustainedSDPFResult(
        scope_folder=scope_folder,
        voltage=str(voltage),
        case=str(case),
        run=int(run),
        mm_name=str(mm_name),
        fault_type=str(fault_type or ""),
        duration_s=float(duration_s),
        governing=governing,
        phases=tuple(sorted(phases, key=lambda row: (row.measurement, row.phase))),
        signature=signature,
    )


def select_governing(results: Iterable[SustainedSDPFResult]) -> SustainedSDPFResult | None:
    return max(
        results,
        key=lambda result: (
            result.governing.sustained_ratio,
            result.governing.sustained_peak_kv,
            result.governing.longest_margin_s,
            str(result.case).casefold(),
            int(result.run),
            str(result.mm_name).casefold(),
        ),
        default=None,
    )


def make_signature(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def result_path(project_root: str | Path, scope_folder: str) -> Path:
    return Path(project_root) / "Voltage_envelope" / scope_folder / RESULT_FILENAME


def invalidate_results(project_root: str | Path) -> None:
    """Remove app-owned Sustained SDPF metadata after an exclusion/settings edit."""
    root = Path(project_root) / "Voltage_envelope"
    try:
        paths = root.glob(f"*/{RESULT_FILENAME}")
        for path in paths:
            path.unlink(missing_ok=True)
    except OSError:
        return


def load_results(project_root: str | Path, scope_folder: str) -> dict[str, Any]:
    path = result_path(project_root, scope_folder)
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def save_results(
    project_root: str | Path,
    scope_folder: str,
    settings: SustainedSDPFSettings,
    results_by_voltage: dict[str, SustainedSDPFResult | None],
    signatures: dict[str, str],
    warnings: list[str] | None = None,
    signature_inputs: dict[str, dict[str, Any]] | None = None,
) -> Path:
    path = result_path(project_root, scope_folder)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "scope_folder": scope_folder,
        "settings": settings.to_mapping(),
        "results": {
            str(voltage): result.to_dict() if result is not None else None
            for voltage, result in results_by_voltage.items()
        },
        "signatures": {str(key): str(value) for key, value in signatures.items()},
        "signature_inputs": {
            str(key): value
            for key, value in (signature_inputs or {}).items()
            if isinstance(value, dict)
        },
        "warnings": list(warnings or []),
    }
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
    temp.replace(path)
    return path


def result_inputs_current(payload: dict[str, Any], voltage: str) -> bool:
    """Check the recorded source-file manifest without rereading waveform data."""
    inputs = payload.get("signature_inputs", {}).get(str(voltage))
    if not isinstance(inputs, dict):
        # Results written by the first implementation have no manifest and are
        # intentionally treated as stale rather than trusted silently.
        return False
    files = inputs.get("files")
    if not isinstance(files, list) or not files:
        return False
    for entry in files:
        if not isinstance(entry, dict):
            return False
        try:
            path = Path(str(entry["path"]))
            if bool(entry.get("missing", False)):
                if path.exists():
                    return False
                continue
            stat = path.stat()
            size = int(entry["size"])
            mtime_ns = int(entry["mtime_ns"])
        except (KeyError, OSError, TypeError, ValueError):
            return False
        if stat.st_size != size or stat.st_mtime_ns != mtime_ns:
            return False
    return True
