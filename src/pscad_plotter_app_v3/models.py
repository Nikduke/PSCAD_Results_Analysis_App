from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

DEFAULT_TOV_WINDOW_S = 0.02
DEFAULT_TOV_WINDOW_COUNT = 2
DEFAULT_FFT_BASE_FREQUENCY_HZ = 50.0
DEFAULT_FFT_MAX_HARMONIC = 7
DEFAULT_FFT_HARMONICS = "1-7"
FFT_OUTPUT_MAGNITUDES = "magnitudes"
FFT_OUTPUT_PHASE_ANGLES = "phase_angles"
FFT_OUTPUT_DC = "dc_component"
DEFAULT_FFT_OUTPUTS = [FFT_OUTPUT_MAGNITUDES]
FFT_MAGNITUDE_RMS = "RMS"
FFT_MAGNITUDE_PEAK = "Peak"
FFT_PHASE_DEGREES = "Degrees"
FFT_PHASE_RADIANS = "Radians"
FFT_REFERENCE_SINE = "Sine"
FFT_REFERENCE_COSINE = "Cosine"


class PlotMode(str, Enum):
    MM = "MM Overvoltage"
    CB = "CB Current"
    ANY = "Any Channel"
    FFT = "FFT"
    COMB = "Combined"


class ProjectMode(str, Enum):
    STUDY = "study"
    MANUAL = "manual"


@dataclass(slots=True)
class VoltageLimitSet:
    voltage_kv: float
    sdpf_lg: float
    sdpf_ll: float
    siwl_lg: float
    siwl_ll: float
    source: str = "workbook"

    @property
    def key(self) -> str:
        return f"{self.voltage_kv:g}"

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "VoltageLimitSet":
        return cls(
            voltage_kv=float(payload["voltage_kv"]),
            sdpf_lg=float(payload["sdpf_lg"]),
            sdpf_ll=float(payload["sdpf_ll"]),
            siwl_lg=float(payload["siwl_lg"]),
            siwl_ll=float(payload["siwl_ll"]),
            source=str(payload.get("source", "override")),
        )


@dataclass(slots=True)
class ProjectContext:
    root_dir: Path
    results_dir: Path
    case_folder_dir: Path
    compiler_output_dirs: list[Path]
    compiler_output_dirs_by_project: dict[str, list[Path]]
    inf_paths_by_dir: dict[Path, list[Path]]
    plots_dir: Path
    state_dir: Path
    workbook_path: Path | None
    project_file: Path | None
    project_files: list[Path]
    project_mode: ProjectMode


@dataclass(slots=True)
class RunMetadata:
    case_name: str
    run_number: int
    fault_label: str = "No fault"
    fault_raw: str = "0"
    event_time_s: float | None = None


@dataclass(slots=True)
class MMElementRecord:
    case_name: str
    voltage_kv: float
    element_name: str
    available_runs: list[int]


@dataclass(slots=True)
class CBElementRecord:
    case_name: str
    element_name: str
    available_runs: list[int]


@dataclass(slots=True)
class SignalGroupRecord:
    case_name: str
    run_number: int
    group_name: str
    signal_name: str
    descriptions: list[str]
    unit: str = ""
    signal_view: str = "bundle"


@dataclass(slots=True, frozen=True)
class SignalReference:
    group_name: str
    signal_name: str
    unit: str = ""
    case_name: str = ""
    run_number: int = 0

    @property
    def label(self) -> str:
        return f"{self.group_name}: {self.signal_name}"

    @property
    def has_source(self) -> bool:
        return bool(self.case_name and self.run_number)


@dataclass(slots=True)
class PlotRequest:
    mode: PlotMode
    case_name: str
    run_numbers: list[int]
    elements: list[str]
    fault_filter: str = "All faults"
    voltage_kv: float | None = None
    trace_type: str | None = None
    show_three_phase_overview: bool = True
    show_limits: bool = True
    show_tov_windows: bool = True
    tov_window_s: float = DEFAULT_TOV_WINDOW_S
    tov_window_count: int = DEFAULT_TOV_WINDOW_COUNT
    legends_left: bool = False
    annotate_max: bool = False
    annotate_min: bool = False
    any_group: str | None = None
    signals: list[str] = field(default_factory=list)
    any_signal_view: str | None = None
    custom_y_axis_name: str | None = None
    custom_y_axis_name_right: str | None = None
    fft_outputs: list[str] = field(default_factory=lambda: DEFAULT_FFT_OUTPUTS.copy())
    fft_base_frequency_hz: float = DEFAULT_FFT_BASE_FREQUENCY_HZ
    fft_max_harmonic: int = DEFAULT_FFT_MAX_HARMONIC
    fft_harmonics: str = DEFAULT_FFT_HARMONICS
    fft_magnitude: str = FFT_MAGNITUDE_RMS
    fft_phase_units: str = FFT_PHASE_DEGREES
    fft_phase_reference: str = FFT_REFERENCE_SINE
    combined_signals: list[SignalReference] = field(default_factory=list)
    excel_export: bool = False
    time_start_s: float | None = None
    time_end_s: float | None = None
    output_dir: str = ""


@dataclass(slots=True)
class PlotJob:
    job_id: str
    mode: PlotMode
    case_name: str
    run_number: int
    group_label: str
    output_dir: str
    fault_label: str = "No fault"
    trace_type: str | None = None
    show_three_phase_overview: bool = True
    show_limits: bool = True
    show_tov_windows: bool = True
    tov_window_s: float = DEFAULT_TOV_WINDOW_S
    tov_window_count: int = DEFAULT_TOV_WINDOW_COUNT
    legends_left: bool = False
    annotate_max: bool = False
    annotate_min: bool = False
    signal_name: str | None = None
    signal_view: str | None = None
    custom_y_axis_name: str | None = None
    custom_y_axis_name_right: str | None = None
    fft_output: str | None = None
    fft_base_frequency_hz: float = DEFAULT_FFT_BASE_FREQUENCY_HZ
    fft_max_harmonic: int = DEFAULT_FFT_MAX_HARMONIC
    fft_harmonics: str = DEFAULT_FFT_HARMONICS
    fft_magnitude: str = FFT_MAGNITUDE_RMS
    fft_phase_units: str = FFT_PHASE_DEGREES
    fft_phase_reference: str = FFT_REFERENCE_SINE
    combined_signals: list[SignalReference] = field(default_factory=list)
    excel_export: bool = False
    time_start_s: float | None = None
    time_end_s: float | None = None
    voltage_kv: float | None = None
    limits: VoltageLimitSet | None = None


@dataclass(slots=True)
class PlotBatch:
    batch_id: str
    mode: PlotMode
    case_name: str
    summary: str
    jobs: list[PlotJob]
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat(timespec="seconds"))
    request: PlotRequest | None = None

    @classmethod
    def create(
        cls,
        mode: PlotMode,
        case_name: str,
        summary: str,
        jobs: list[PlotJob],
        request: PlotRequest | None = None,
    ) -> "PlotBatch":
        return cls(
            batch_id=uuid4().hex,
            mode=mode,
            case_name=case_name,
            summary=summary,
            jobs=jobs,
            request=request,
        )

    @property
    def plot_count(self) -> int:
        return len(self.jobs)


@dataclass(slots=True)
class ProjectCatalog:
    mm_elements: list[MMElementRecord] = field(default_factory=list)
    cb_elements: list[CBElementRecord] = field(default_factory=list)
    runs_by_case: dict[str, list[int]] = field(default_factory=dict)
    run_metadata_by_case: dict[str, dict[int, RunMetadata]] = field(default_factory=dict)
    time_range_by_case_run: dict[str, dict[int, tuple[float, float]]] = field(default_factory=dict)
    channel_groups_by_case_run: dict[str, dict[int, list[SignalGroupRecord]]] = field(default_factory=dict)
