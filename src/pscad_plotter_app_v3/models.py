from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

DEFAULT_TOV_WINDOW_S = 0.02
DEFAULT_TOV_WINDOW_COUNT = 2


class PlotMode(str, Enum):
    MM = "MM Overvoltage"


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
class MMElementRecord:
    case_name: str
    voltage_kv: float
    element_name: str
    available_runs: list[int]


@dataclass(slots=True)
class PlotRequest:
    mode: PlotMode
    case_name: str
    run_numbers: list[int]
    elements: list[str]
    voltage_kv: float | None = None
    trace_type: str | None = None
    show_three_phase_overview: bool = True
    show_limits: bool = True
    show_tov_windows: bool = True
    tov_window_s: float = DEFAULT_TOV_WINDOW_S
    tov_window_count: int = DEFAULT_TOV_WINDOW_COUNT
    legends_left: bool = False
    excel_export: bool = False
    time_start_s: float | None = None
    time_end_s: float | None = None
    output_dir: str = ""
    annotate_max: bool = False
    annotate_min: bool = False
    plot_variant: str | None = None


@dataclass(slots=True)
class PlotJob:
    mode: PlotMode
    case_name: str
    run_number: int
    group_label: str
    output_dir: str
    trace_type: str | None = None
    show_three_phase_overview: bool = True
    show_limits: bool = True
    show_tov_windows: bool = True
    tov_window_s: float = DEFAULT_TOV_WINDOW_S
    tov_window_count: int = DEFAULT_TOV_WINDOW_COUNT
    legends_left: bool = False
    excel_export: bool = False
    time_start_s: float | None = None
    time_end_s: float | None = None
    voltage_kv: float | None = None
    limits: VoltageLimitSet | None = None
    annotate_max: bool = False
    annotate_min: bool = False
    plot_variant: str | None = None


@dataclass(slots=True)
class ProjectCatalog:
    mm_elements: list[MMElementRecord] = field(default_factory=list)
    runs_by_case: dict[str, list[int]] = field(default_factory=dict)
    mm_results: list[dict[str, object]] = field(default_factory=list)
