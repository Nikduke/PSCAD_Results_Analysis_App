from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import math
import os
import re
from typing import Any

from results_analysis_app.exclusions import (
    ExclusionRule,
    migrate_legacy_project_exclusions,
    normalize_exclusion_rules,
    normalize_project_case_run_exclusions,
    normalize_project_exclusion_rules,
    normalize_project_high_voltage_exclusions,
)
from results_analysis_app.project_config import DEFAULT_EVENT_TIMES, normalize_voltage

DEFAULT_VOLTAGES: tuple[str, ...] = ()
DEFAULT_EVENTS = ("SFO", "TOV", "SA")
DEFAULT_RESONANCE_CHECKS = ("Post_Event_Stress", "Late_Growth", "No_Settle_Growth")
DEFAULT_ENVELOPE_TIME_STEP = 0.002
DEFAULT_ENVELOPE_TIME_END = 1.0
DEFAULT_ENVELOPE_TIME_END_AUTO = True
DEFAULT_ENVELOPE_FALLBACK_FREQUENCY = 50.0
# Automatic plot batches include waveform Excel exports by default.  The
# setting only controls those generated batch rows; manually edited batches
# can still request an export explicitly.
DEFAULT_EXCEL_WAVEFORM_EXPORTS = True
# Zero means automatic worker selection. Positive values remain available as a
# manual override; 60 stays below Windows' ProcessPoolExecutor limit.
DEFAULT_ENVELOPE_WORKERS = 0
MAX_ENVELOPE_WORKERS = 60
DEFAULT_ENVELOPE_CHART_X_MAX = 0.5
DEFAULT_ENVELOPE_CHART_X_MAJOR = 0.05
DEFAULT_ENVELOPE_CHART_TOP_LEFT_CELL = "H1"
DEFAULT_ENVELOPE_CHART_WIDTH = 901.39
DEFAULT_ENVELOPE_CHART_HEIGHT = 418.40
DEFAULT_ENVELOPE_CHART_Y_LIMITS = {
    "22": {"y_min": 15.0, "y_max": None, "y_major": None},
    "66": {"y_min": 50.0, "y_max": None, "y_major": None},
    "161": {"y_min": 100.0, "y_max": None, "y_major": None},
    "230": {"y_min": 150.0, "y_max": None, "y_major": None},
}
DEFAULT_ENVELOPE_CHART_SHOW_SA_LABEL = False
DEFAULT_HIGH_VOLTAGE_LIMIT_FACTOR = 5.0
DEFAULT_NONCONV_CB_IIP_LIMIT = 400.0
DEFAULT_NONCONV_CB_IIR_LIMIT = 200.0
DEFAULT_RESONANCE_LIMIT_MULTIPLIER = 3 ** 0.5
DEFAULT_RESONANCE_TOP_N = 1
DEFAULT_RESONANCE_AUTO_RELEASE = True
DEFAULT_RESONANCE_MANUAL_START = 0.03
DEFAULT_RESONANCE_PEAK_SEARCH_FRACTION = 0.25
DEFAULT_RESONANCE_RELEASE_DECAY_RATIO = 0.80
DEFAULT_RESONANCE_RELEASE_REBOUND_RATIO = 0.95
DEFAULT_RESONANCE_RELEASE_HOLD_TIME = 0.05
DEFAULT_RESONANCE_ROLLING_P95_WINDOW = 0.02
DEFAULT_RESONANCE_ROLLING_MIN_SAMPLES = 10
DEFAULT_RESONANCE_LOG_FLOOR_VLIM_FACTOR = 1e-6
DEFAULT_RESONANCE_LOG_FLOOR_ABSOLUTE = 1e-4
DEFAULT_RESONANCE_GROWTH_WINDOW_FRACTION = 0.20
DEFAULT_RESONANCE_MIN_POSITIVE_FRACTION = 0.60
DEFAULT_RESONANCE_MIN_GROWTH_RATIO = 1.05
DEFAULT_RESONANCE_MIN_LEVEL_OVER_VLIM = 0.50
DEFAULT_RESONANCE_MIN_GROWTH_DELTA_FACTOR = 0.01
DEFAULT_SUSTAINED_SDPF_DURATION_MS = 30.0


def _json_list(value: Any, default: tuple[Any, ...] = ()) -> list[Any]:
    return value if isinstance(value, list) else list(default)


def _json_dict(value: Any) -> dict[Any, Any]:
    return value if isinstance(value, dict) else {}


def normalize_dashboard_figure_selection(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    selection: list[str] = []
    seen: set[str] = set()
    for item in value:
        figure_id = str(item).strip()
        if figure_id and figure_id not in seen:
            seen.add(figure_id)
            selection.append(figure_id)
    return selection


def normalize_project_dashboard_figure_selection(
    value: Any,
) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        return {}
    return {
        str(project): normalize_dashboard_figure_selection(raw_selection)
        for project, raw_selection in value.items()
        if isinstance(raw_selection, list)
    }


def normalize_project_sustained_sdpf_heatmap_settings(value: Any) -> dict[str, list[dict[str, Any]]]:
    """Normalize old single mappings and new ordered heatmap-set lists."""
    if not isinstance(value, dict):
        return {}
    # Keep session persistence and rendering on one normalization path.  The
    # local import avoids making the model layer depend on the renderer during
    # module initialization.
    from results_analysis_app.sustained_sdpf_heatmap import (
        heatmap_sets_from_mapping,
        heatmap_sets_to_mapping,
    )

    output: dict[str, list[dict[str, Any]]] = {}
    for project, raw_settings in value.items():
        output[str(project)] = heatmap_sets_to_mapping(
            heatmap_sets_from_mapping(raw_settings)
        )
    return output


def normalize_project_sustained_sdpf_ranking_settings(
    value: Any,
) -> dict[str, dict[str, bool]]:
    """Normalize project-specific representative-selection controls."""
    if not isinstance(value, dict):
        return {}
    from results_analysis_app.sustained_sdpf import SustainedSDPFRankingSettings

    return {
        str(project): SustainedSDPFRankingSettings.from_mapping(raw).to_mapping()
        for project, raw in value.items()
        if isinstance(raw, dict)
    }


def normalize_project_sustained_sdpf_limit_overrides(
    value: Any,
) -> dict[str, dict[str, dict[str, float]]]:
    if not isinstance(value, dict):
        return {}
    output: dict[str, dict[str, dict[str, float]]] = {}
    for project, raw_limits in value.items():
        if not isinstance(raw_limits, dict):
            continue
        project_limits: dict[str, dict[str, float]] = {}
        for voltage, raw_values in raw_limits.items():
            if not isinstance(raw_values, dict):
                continue
            voltage_key = normalize_voltage(voltage)
            if not voltage_key:
                continue
            values: dict[str, float] = {}
            for measurement in ("LGp", "LLp"):
                number = normalize_positive_float(raw_values.get(measurement), 0.0)
                if number > 0:
                    values[measurement] = number
            if values:
                project_limits[voltage_key] = values
        if project_limits:
            output[str(project)] = project_limits
    return output


def normalize_tokens(text: str | list[str] | tuple[str, ...] | Any) -> list[str]:
    if isinstance(text, str):
        raw_tokens = re.split(r"[,;\s]+", text)
    elif isinstance(text, (list, tuple)):
        raw_tokens = [str(value) for value in text]
    else:
        raw_tokens = []

    tokens: list[str] = []
    seen: set[str] = set()
    for raw in raw_tokens:
        token = raw.strip()
        if not token:
            continue
        key = token.casefold()
        if key in seen:
            continue
        seen.add(key)
        tokens.append(token)
    return tokens


def safe_token(token: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_.-]+", "_", token.strip())
    value = re.sub(r"_+", "_", value).strip("_.")
    return value or "Token"


def normalize_worker_count(value: Any) -> int:
    try:
        return min(MAX_ENVELOPE_WORKERS, max(0, int(value)))
    except (TypeError, ValueError):
        return DEFAULT_ENVELOPE_WORKERS


def automatic_worker_count() -> int:
    """Choose a bounded waveform pool from 80% of detected logical CPUs.

    Raw waveform parsing is both CPU and storage intensive.  Keeping a small
    portion of the machine available leaves headroom for the UI, Excel, and
    the operating system while allowing the SSD-backed read stage to use the
    parallelism it can sustain.
    """
    cpu_counter = getattr(os, "process_cpu_count", None)
    cpu_count = cpu_counter() if callable(cpu_counter) else None
    if cpu_count is None:
        cpu_count = os.cpu_count()
    detected_cpus = max(1, int(cpu_count or 1))
    worker_target = math.ceil(detected_cpus * 0.8)
    return max(1, min(MAX_ENVELOPE_WORKERS, worker_target))


def normalize_positive_int(value: Any, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return number if number > 0 else default


def normalize_positive_float(value: Any, default: float) -> float:
    """Return a finite positive float or the supplied default."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) and number > 0 else default


def normalize_nonnegative_float(value: Any, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if number >= 0 else default


def normalize_fraction(value: Any, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if 0 < number <= 1 else default


def normalize_optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def normalize_chart_y_limits(value: Any = None) -> dict[str, dict[str, float | None]]:
    if not isinstance(value, dict):
        return {voltage: dict(limits) for voltage, limits in DEFAULT_ENVELOPE_CHART_Y_LIMITS.items()}
    output = {voltage: dict(limits) for voltage, limits in DEFAULT_ENVELOPE_CHART_Y_LIMITS.items()}
    for raw_voltage, raw_limits in value.items():
        voltage = normalize_voltage(raw_voltage)
        if not voltage or not isinstance(raw_limits, dict):
            continue
        limits = output.setdefault(voltage, {"y_min": None, "y_max": None, "y_major": None})
        for key in ("y_min", "y_max", "y_major"):
            if key in raw_limits:
                limits[key] = normalize_optional_float(raw_limits.get(key))
    return output


def normalize_project_voltage_um_overrides(value: Any) -> dict[str, dict[str, float]]:
    if not isinstance(value, dict):
        return {}
    output: dict[str, dict[str, float]] = {}
    for project, overrides in value.items():
        if not isinstance(overrides, dict):
            continue
        normalized: dict[str, float] = {}
        for raw_voltage, raw_um in overrides.items():
            voltage = normalize_voltage(raw_voltage)
            um = normalize_positive_float(raw_um, 0.0)
            if voltage and um > 0:
                normalized[voltage] = um
        if normalized:
            output[str(project)] = normalized
    return output


def normalize_project_positive_floats(value: Any) -> dict[str, float]:
    if not isinstance(value, dict):
        return {}
    output: dict[str, float] = {}
    for project, raw_number in value.items():
        number = normalize_positive_float(raw_number, 0.0)
        if str(project).strip() and number > 0:
            output[str(project)] = number
    return output


def scope_folder_name(mode: str, tokens: list[str]) -> str:
    if mode == "full":
        return "Full"
    prefix = "No" if mode == "exclude" else "Only"
    safe_tokens = [safe_token(token) for token in tokens]
    if not safe_tokens:
        return "Full"
    return f"{prefix}_{'_'.join(safe_tokens)}"


@dataclass
class ProjectEntry:
    path: str
    selected: bool = True

    @property
    def name(self) -> str:
        return Path(self.path).name or self.path

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "selected": self.selected}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProjectEntry":
        return cls(path=str(data.get("path", "")), selected=bool(data.get("selected", True)))


@dataclass
class ScopeEntry:
    name: str
    mode: str = "full"
    tokens: list[str] = field(default_factory=list)
    selected: bool = True

    @classmethod
    def full(cls) -> "ScopeEntry":
        return cls(name="Full", mode="full", tokens=[], selected=True)

    @property
    def folder(self) -> str:
        return scope_folder_name(self.mode, self.tokens)

    @property
    def description(self) -> str:
        if self.mode == "full":
            return "all cases"
        verb = "exclude" if self.mode == "exclude" else "include"
        return f"{verb}: {', '.join(self.tokens)}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "mode": self.mode,
            "tokens": self.tokens,
            "selected": self.selected,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ScopeEntry":
        mode = str(data.get("mode", "full"))
        if mode not in {"full", "exclude", "include"}:
            mode = "full"
        tokens = normalize_tokens(data.get("tokens", []))
        if mode == "full":
            tokens = []
        name = str(data.get("name") or scope_folder_name(mode, tokens))
        return cls(
            name=name,
            mode=mode,
            tokens=tokens,
            selected=bool(data.get("selected", True)),
        )


@dataclass(frozen=True)
class DashboardFigure:
    id: str
    workbook: str
    sheet: str
    chart_index: int
    title: str

    @property
    def label(self) -> str:
        title = self.title or f"Chart {self.chart_index}"
        return f"{self.workbook} | {self.sheet} | {title}"


@dataclass
class AppSession:
    projects: list[ProjectEntry] = field(default_factory=list)
    scopes: list[ScopeEntry] = field(default_factory=lambda: [ScopeEntry.full()])
    voltages: list[str] = field(default_factory=lambda: list(DEFAULT_VOLTAGES))
    events: list[str] = field(default_factory=lambda: list(DEFAULT_EVENTS))
    event_times: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_EVENT_TIMES))
    envelope_workers: int = DEFAULT_ENVELOPE_WORKERS
    envelope_workers_auto: bool = True
    envelope_time_step: float = DEFAULT_ENVELOPE_TIME_STEP
    envelope_time_end: float = DEFAULT_ENVELOPE_TIME_END
    envelope_time_end_auto: bool = DEFAULT_ENVELOPE_TIME_END_AUTO
    envelope_fallback_frequency: float = DEFAULT_ENVELOPE_FALLBACK_FREQUENCY
    excel_waveform_exports_enabled: bool = DEFAULT_EXCEL_WAVEFORM_EXPORTS
    envelope_chart_x_max_overrides_by_project: dict[str, float] = field(default_factory=dict)
    envelope_chart_x_major_overrides_by_project: dict[str, float] = field(default_factory=dict)
    envelope_chart_top_left_cell: str = DEFAULT_ENVELOPE_CHART_TOP_LEFT_CELL
    envelope_chart_width: float = DEFAULT_ENVELOPE_CHART_WIDTH
    envelope_chart_height: float = DEFAULT_ENVELOPE_CHART_HEIGHT
    envelope_chart_y_limits_by_voltage: dict[str, dict[str, float | None]] = field(default_factory=normalize_chart_y_limits)
    envelope_chart_show_sa_label: bool = DEFAULT_ENVELOPE_CHART_SHOW_SA_LABEL
    high_voltage_limit_factor: float = DEFAULT_HIGH_VOLTAGE_LIMIT_FACTOR
    nonconv_cb_iip_limit: float = DEFAULT_NONCONV_CB_IIP_LIMIT
    nonconv_cb_iir_limit: float = DEFAULT_NONCONV_CB_IIR_LIMIT
    resonance_enabled_checks: list[str] = field(default_factory=list)
    resonance_top_n: int = DEFAULT_RESONANCE_TOP_N
    resonance_limit_multiplier: float = DEFAULT_RESONANCE_LIMIT_MULTIPLIER
    resonance_auto_release: bool = DEFAULT_RESONANCE_AUTO_RELEASE
    resonance_manual_analysis_start: float = DEFAULT_RESONANCE_MANUAL_START
    resonance_peak_search_fraction: float = DEFAULT_RESONANCE_PEAK_SEARCH_FRACTION
    resonance_release_decay_ratio: float = DEFAULT_RESONANCE_RELEASE_DECAY_RATIO
    resonance_release_rebound_ratio: float = DEFAULT_RESONANCE_RELEASE_REBOUND_RATIO
    resonance_release_hold_time: float = DEFAULT_RESONANCE_RELEASE_HOLD_TIME
    resonance_rolling_p95_window: float = DEFAULT_RESONANCE_ROLLING_P95_WINDOW
    resonance_rolling_min_samples: int = DEFAULT_RESONANCE_ROLLING_MIN_SAMPLES
    resonance_log_floor_vlim_factor: float = DEFAULT_RESONANCE_LOG_FLOOR_VLIM_FACTOR
    resonance_log_floor_absolute: float = DEFAULT_RESONANCE_LOG_FLOOR_ABSOLUTE
    resonance_growth_window_fraction: float = DEFAULT_RESONANCE_GROWTH_WINDOW_FRACTION
    resonance_min_positive_fraction: float = DEFAULT_RESONANCE_MIN_POSITIVE_FRACTION
    resonance_min_growth_ratio: float = DEFAULT_RESONANCE_MIN_GROWTH_RATIO
    resonance_min_level_over_vlim: float = DEFAULT_RESONANCE_MIN_LEVEL_OVER_VLIM
    resonance_min_growth_delta_factor: float = DEFAULT_RESONANCE_MIN_GROWTH_DELTA_FACTOR
    sustained_sdpf_enabled: bool = False
    sustained_sdpf_duration_ms: float = DEFAULT_SUSTAINED_SDPF_DURATION_MS
    sustained_sdpf_ranking_settings_by_project: dict[str, dict[str, bool]] = field(default_factory=dict)
    sustained_sdpf_heatmap_settings_by_project: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    sustained_sdpf_limit_overrides_by_project: dict[str, dict[str, dict[str, float]]] = field(default_factory=dict)
    voltage_um_overrides_by_project: dict[str, dict[str, float]] = field(default_factory=dict)
    manual_exclusions_by_project: dict[str, list[ExclusionRule]] = field(default_factory=dict)
    disabled_nonconv_by_project: dict[str, list[tuple[str, int]]] = field(default_factory=dict)
    high_voltage_include_overrides_by_project: dict[str, list[tuple[str, str, int, str]]] = field(default_factory=dict)
    dashboard_figure_apply_to_all: bool = True
    dashboard_figure_shared_selection: list[str] = field(default_factory=list)
    dashboard_figure_shared_selection_initialized: bool = False
    dashboard_figure_selection_by_project: dict[str, list[str]] = field(default_factory=dict)
    status_cache: dict[str, list[str]] = field(default_factory=dict)

    @classmethod
    def default(cls) -> "AppSession":
        return cls()

    def ensure_full_scope(self) -> None:
        if not any(scope.mode == "full" for scope in self.scopes):
            self.scopes.insert(0, ScopeEntry.full())
        self.scopes.sort(key=lambda scope: 0 if scope.mode == "full" else 1)

    def add_project(self, path: str) -> None:
        resolved = str(Path(path).resolve())
        if any(project.path.casefold() == resolved.casefold() for project in self.projects):
            return
        self.projects.append(ProjectEntry(path=resolved, selected=True))

    def remove_projects(self, paths: set[str]) -> None:
        keys = {path.casefold() for path in paths}
        self.projects = [project for project in self.projects if project.path.casefold() not in keys]
        for mapping in (
            self.envelope_chart_x_max_overrides_by_project,
            self.envelope_chart_x_major_overrides_by_project,
            self.voltage_um_overrides_by_project,
            self.manual_exclusions_by_project,
            self.disabled_nonconv_by_project,
            self.high_voltage_include_overrides_by_project,
            self.dashboard_figure_selection_by_project,
            self.sustained_sdpf_heatmap_settings_by_project,
            self.sustained_sdpf_ranking_settings_by_project,
            self.sustained_sdpf_limit_overrides_by_project,
            self.status_cache,
        ):
            for project in list(mapping):
                if project.casefold() in keys:
                    mapping.pop(project, None)

    def add_scope(self, mode: str, token_text: str) -> ScopeEntry:
        tokens = normalize_tokens(token_text)
        if mode not in {"exclude", "include"} or not tokens:
            raise ValueError("Scope requires include or exclude tokens.")
        folder = scope_folder_name(mode, tokens)
        for scope in self.scopes:
            if scope.folder.casefold() == folder.casefold():
                scope.selected = True
                return scope
        scope = ScopeEntry(name=folder, mode=mode, tokens=tokens, selected=True)
        self.scopes.append(scope)
        return scope

    def to_dict(self) -> dict[str, Any]:
        return {
            "projects": [project.to_dict() for project in self.projects],
            "scopes": [scope.to_dict() for scope in self.scopes],
            "voltages": self.voltages,
            "events": self.events,
            "event_times": self.event_times,
            "envelope_workers": self.envelope_workers,
            "envelope_workers_auto": self.envelope_workers_auto,
            "envelope_time_step": self.envelope_time_step,
            "envelope_time_end": self.envelope_time_end,
            "envelope_time_end_auto": self.envelope_time_end_auto,
            "envelope_fallback_frequency": self.envelope_fallback_frequency,
            "excel_waveform_exports_enabled": self.excel_waveform_exports_enabled,
            "envelope_chart_x_max_overrides_by_project": self.envelope_chart_x_max_overrides_by_project,
            "envelope_chart_x_major_overrides_by_project": self.envelope_chart_x_major_overrides_by_project,
            "envelope_chart_top_left_cell": self.envelope_chart_top_left_cell,
            "envelope_chart_width": self.envelope_chart_width,
            "envelope_chart_height": self.envelope_chart_height,
            "envelope_chart_y_limits_by_voltage": self.envelope_chart_y_limits_by_voltage,
            "envelope_chart_show_sa_label": self.envelope_chart_show_sa_label,
            "high_voltage_limit_factor": self.high_voltage_limit_factor,
            "nonconv_cb_iip_limit": self.nonconv_cb_iip_limit,
            "nonconv_cb_iir_limit": self.nonconv_cb_iir_limit,
            "resonance_enabled_checks": self.resonance_enabled_checks,
            "resonance_top_n": self.resonance_top_n,
            "resonance_limit_multiplier": self.resonance_limit_multiplier,
            "resonance_auto_release": self.resonance_auto_release,
            "resonance_manual_analysis_start": self.resonance_manual_analysis_start,
            "resonance_peak_search_fraction": self.resonance_peak_search_fraction,
            "resonance_release_decay_ratio": self.resonance_release_decay_ratio,
            "resonance_release_rebound_ratio": self.resonance_release_rebound_ratio,
            "resonance_release_hold_time": self.resonance_release_hold_time,
            "resonance_rolling_p95_window": self.resonance_rolling_p95_window,
            "resonance_rolling_min_samples": self.resonance_rolling_min_samples,
            "resonance_log_floor_vlim_factor": self.resonance_log_floor_vlim_factor,
            "resonance_log_floor_absolute": self.resonance_log_floor_absolute,
            "resonance_growth_window_fraction": self.resonance_growth_window_fraction,
            "resonance_min_positive_fraction": self.resonance_min_positive_fraction,
            "resonance_min_growth_ratio": self.resonance_min_growth_ratio,
            "resonance_min_level_over_vlim": self.resonance_min_level_over_vlim,
            "resonance_min_growth_delta_factor": self.resonance_min_growth_delta_factor,
            "sustained_sdpf_enabled": self.sustained_sdpf_enabled,
            "sustained_sdpf_duration_ms": self.sustained_sdpf_duration_ms,
            "sustained_sdpf_ranking_settings_by_project": self.sustained_sdpf_ranking_settings_by_project,
            "sustained_sdpf_heatmap_settings_by_project": self.sustained_sdpf_heatmap_settings_by_project,
            "sustained_sdpf_limit_overrides_by_project": self.sustained_sdpf_limit_overrides_by_project,
            "voltage_um_overrides_by_project": self.voltage_um_overrides_by_project,
            "manual_exclusions_by_project": {
                project: [rule.to_dict() for rule in exclusions]
                for project, exclusions in self.manual_exclusions_by_project.items()
            },
            "disabled_nonconv_by_project": {
                project: [{"case": case, "run": run} for case, run in exclusions]
                for project, exclusions in self.disabled_nonconv_by_project.items()
            },
            "high_voltage_include_overrides_by_project": {
                project: [
                    {"voltage": voltage, "case": case, "run": run, "bus": bus}
                    for voltage, case, run, bus in inclusions
                ]
                for project, inclusions in self.high_voltage_include_overrides_by_project.items()
            },
            "dashboard_figure_apply_to_all": self.dashboard_figure_apply_to_all,
            "dashboard_figure_shared_selection": self.dashboard_figure_shared_selection,
            "dashboard_figure_shared_selection_initialized": (
                self.dashboard_figure_shared_selection_initialized
            ),
            "dashboard_figure_selection_by_project": self.dashboard_figure_selection_by_project,
            "status_cache": self.status_cache,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppSession":
        data = _json_dict(data)
        manual_exclusions = normalize_project_exclusion_rules(
            _json_dict(data.get("manual_exclusions_by_project"))
        )
        legacy_exclusions = migrate_legacy_project_exclusions(
            _json_dict(data.get("bus_exclusions_by_project")),
            _json_dict(data.get("manual_case_run_exclusions_by_project")),
        )
        for project, rules in legacy_exclusions.items():
            manual_exclusions[project] = normalize_exclusion_rules(
                [*manual_exclusions.get(project, []), *rules]
            )
        legacy_dashboard_selection = normalize_dashboard_figure_selection(
            data.get("dashboard_figure_selection")
        )
        project_entries = [
            ProjectEntry.from_dict(value)
            for value in _json_list(data.get("projects"))
            if isinstance(value, dict)
        ]
        dashboard_selection_by_project = normalize_project_dashboard_figure_selection(
            data.get("dashboard_figure_selection_by_project", {})
        )
        if not dashboard_selection_by_project and (
            legacy_dashboard_selection
            or bool(data.get("dashboard_figure_selection_initialized", False))
        ):
            dashboard_selection_by_project = {
                project.path: list(legacy_dashboard_selection)
                for project in project_entries
            }
        has_shared_dashboard_selection = "dashboard_figure_shared_selection" in data
        if has_shared_dashboard_selection:
            shared_dashboard_selection = normalize_dashboard_figure_selection(
                data.get("dashboard_figure_shared_selection")
            )
            shared_dashboard_selection_initialized = bool(
                data.get("dashboard_figure_shared_selection_initialized", True)
            )
        elif legacy_dashboard_selection or bool(
            data.get("dashboard_figure_selection_initialized", False)
        ):
            shared_dashboard_selection = list(legacy_dashboard_selection)
            shared_dashboard_selection_initialized = True
        elif dashboard_selection_by_project:
            shared_dashboard_selection = []
            seen_shared_dashboard_selection: set[str] = set()
            for project in project_entries:
                for figure_id in dashboard_selection_by_project.get(project.path, []):
                    if figure_id not in seen_shared_dashboard_selection:
                        seen_shared_dashboard_selection.add(figure_id)
                        shared_dashboard_selection.append(figure_id)
            shared_dashboard_selection_initialized = True
        else:
            shared_dashboard_selection = []
            shared_dashboard_selection_initialized = False
        raw_event_times = data.get("event_times", {})
        if not isinstance(raw_event_times, dict):
            raw_event_times = {}
        event_times: dict[str, float] = {}
        for event in DEFAULT_EVENTS:
            try:
                event_times[event] = float(raw_event_times.get(event, DEFAULT_EVENT_TIMES[event]))
            except (TypeError, ValueError):
                event_times[event] = DEFAULT_EVENT_TIMES[event]

        raw_events = {
            str(value)
            for value in _json_list(data.get("events"), DEFAULT_EVENTS)
            if str(value) in DEFAULT_EVENTS
        }
        worker_count = normalize_worker_count(
            data.get("envelope_workers", DEFAULT_ENVELOPE_WORKERS)
        )
        worker_auto = bool(data.get("envelope_workers_auto", worker_count == 0))

        session = cls(
            projects=project_entries,
            scopes=[
                ScopeEntry.from_dict(value)
                for value in _json_list(data.get("scopes"))
                if isinstance(value, dict)
            ],
            voltages=[
                str(value)
                for value in _json_list(data.get("voltages"), DEFAULT_VOLTAGES)
                if str(value).strip()
            ],
            events=[event for event in DEFAULT_EVENTS if event in raw_events],
            event_times=event_times,
            envelope_workers=worker_count,
            envelope_workers_auto=worker_auto,
            envelope_time_step=normalize_positive_float(
                data.get("envelope_time_step", DEFAULT_ENVELOPE_TIME_STEP),
                DEFAULT_ENVELOPE_TIME_STEP,
            ),
            envelope_time_end=normalize_positive_float(
                data.get("envelope_time_end", DEFAULT_ENVELOPE_TIME_END),
                DEFAULT_ENVELOPE_TIME_END,
            ),
            envelope_time_end_auto=bool(
                data.get("envelope_time_end_auto", DEFAULT_ENVELOPE_TIME_END_AUTO)
            ),
            envelope_fallback_frequency=normalize_positive_float(
                data.get("envelope_fallback_frequency", DEFAULT_ENVELOPE_FALLBACK_FREQUENCY),
                DEFAULT_ENVELOPE_FALLBACK_FREQUENCY,
            ),
            excel_waveform_exports_enabled=bool(
                data.get("excel_waveform_exports_enabled", DEFAULT_EXCEL_WAVEFORM_EXPORTS)
            ),
            envelope_chart_x_max_overrides_by_project=normalize_project_positive_floats(
                data.get("envelope_chart_x_max_overrides_by_project", {})
            ),
            envelope_chart_x_major_overrides_by_project=normalize_project_positive_floats(
                data.get("envelope_chart_x_major_overrides_by_project", {})
            ),
            envelope_chart_top_left_cell=(
                str(data.get("envelope_chart_top_left_cell", DEFAULT_ENVELOPE_CHART_TOP_LEFT_CELL)).strip()
                or DEFAULT_ENVELOPE_CHART_TOP_LEFT_CELL
            ),
            envelope_chart_width=normalize_positive_float(
                data.get("envelope_chart_width", DEFAULT_ENVELOPE_CHART_WIDTH),
                DEFAULT_ENVELOPE_CHART_WIDTH,
            ),
            envelope_chart_height=normalize_positive_float(
                data.get("envelope_chart_height", DEFAULT_ENVELOPE_CHART_HEIGHT),
                DEFAULT_ENVELOPE_CHART_HEIGHT,
            ),
            envelope_chart_y_limits_by_voltage=normalize_chart_y_limits(
                data.get("envelope_chart_y_limits_by_voltage", {})
            ),
            envelope_chart_show_sa_label=bool(
                data.get("envelope_chart_show_sa_label", DEFAULT_ENVELOPE_CHART_SHOW_SA_LABEL)
            ),
            high_voltage_limit_factor=normalize_positive_float(
                data.get("high_voltage_limit_factor", DEFAULT_HIGH_VOLTAGE_LIMIT_FACTOR),
                DEFAULT_HIGH_VOLTAGE_LIMIT_FACTOR,
            ),
            nonconv_cb_iip_limit=normalize_positive_float(
                data.get("nonconv_cb_iip_limit", DEFAULT_NONCONV_CB_IIP_LIMIT),
                DEFAULT_NONCONV_CB_IIP_LIMIT,
            ),
            nonconv_cb_iir_limit=normalize_positive_float(
                data.get("nonconv_cb_iir_limit", DEFAULT_NONCONV_CB_IIR_LIMIT),
                DEFAULT_NONCONV_CB_IIR_LIMIT,
            ),
            resonance_enabled_checks=[
                str(value)
                for value in _json_list(data.get("resonance_enabled_checks"))
                if str(value) in DEFAULT_RESONANCE_CHECKS
            ],
            resonance_top_n=normalize_positive_int(
                data.get("resonance_top_n", DEFAULT_RESONANCE_TOP_N),
                DEFAULT_RESONANCE_TOP_N,
            ),
            resonance_limit_multiplier=normalize_positive_float(
                data.get("resonance_limit_multiplier", DEFAULT_RESONANCE_LIMIT_MULTIPLIER),
                DEFAULT_RESONANCE_LIMIT_MULTIPLIER,
            ),
            resonance_auto_release=bool(
                data.get("resonance_auto_release", DEFAULT_RESONANCE_AUTO_RELEASE)
            ),
            resonance_manual_analysis_start=normalize_nonnegative_float(
                data.get("resonance_manual_analysis_start", DEFAULT_RESONANCE_MANUAL_START),
                DEFAULT_RESONANCE_MANUAL_START,
            ),
            resonance_peak_search_fraction=normalize_fraction(
                data.get("resonance_peak_search_fraction", DEFAULT_RESONANCE_PEAK_SEARCH_FRACTION),
                DEFAULT_RESONANCE_PEAK_SEARCH_FRACTION,
            ),
            resonance_release_decay_ratio=normalize_fraction(
                data.get("resonance_release_decay_ratio", DEFAULT_RESONANCE_RELEASE_DECAY_RATIO),
                DEFAULT_RESONANCE_RELEASE_DECAY_RATIO,
            ),
            resonance_release_rebound_ratio=normalize_fraction(
                data.get("resonance_release_rebound_ratio", DEFAULT_RESONANCE_RELEASE_REBOUND_RATIO),
                DEFAULT_RESONANCE_RELEASE_REBOUND_RATIO,
            ),
            resonance_release_hold_time=normalize_positive_float(
                data.get("resonance_release_hold_time", DEFAULT_RESONANCE_RELEASE_HOLD_TIME),
                DEFAULT_RESONANCE_RELEASE_HOLD_TIME,
            ),
            resonance_rolling_p95_window=normalize_positive_float(
                data.get("resonance_rolling_p95_window", DEFAULT_RESONANCE_ROLLING_P95_WINDOW),
                DEFAULT_RESONANCE_ROLLING_P95_WINDOW,
            ),
            resonance_rolling_min_samples=normalize_positive_int(
                data.get("resonance_rolling_min_samples", DEFAULT_RESONANCE_ROLLING_MIN_SAMPLES),
                DEFAULT_RESONANCE_ROLLING_MIN_SAMPLES,
            ),
            resonance_log_floor_vlim_factor=normalize_positive_float(
                data.get("resonance_log_floor_vlim_factor", DEFAULT_RESONANCE_LOG_FLOOR_VLIM_FACTOR),
                DEFAULT_RESONANCE_LOG_FLOOR_VLIM_FACTOR,
            ),
            resonance_log_floor_absolute=normalize_positive_float(
                data.get("resonance_log_floor_absolute", DEFAULT_RESONANCE_LOG_FLOOR_ABSOLUTE),
                DEFAULT_RESONANCE_LOG_FLOOR_ABSOLUTE,
            ),
            resonance_growth_window_fraction=normalize_fraction(
                data.get("resonance_growth_window_fraction", DEFAULT_RESONANCE_GROWTH_WINDOW_FRACTION),
                DEFAULT_RESONANCE_GROWTH_WINDOW_FRACTION,
            ),
            resonance_min_positive_fraction=normalize_fraction(
                data.get("resonance_min_positive_fraction", DEFAULT_RESONANCE_MIN_POSITIVE_FRACTION),
                DEFAULT_RESONANCE_MIN_POSITIVE_FRACTION,
            ),
            resonance_min_growth_ratio=normalize_positive_float(
                data.get("resonance_min_growth_ratio", DEFAULT_RESONANCE_MIN_GROWTH_RATIO),
                DEFAULT_RESONANCE_MIN_GROWTH_RATIO,
            ),
            resonance_min_level_over_vlim=normalize_positive_float(
                data.get("resonance_min_level_over_vlim", DEFAULT_RESONANCE_MIN_LEVEL_OVER_VLIM),
                DEFAULT_RESONANCE_MIN_LEVEL_OVER_VLIM,
            ),
            resonance_min_growth_delta_factor=normalize_positive_float(
                data.get("resonance_min_growth_delta_factor", DEFAULT_RESONANCE_MIN_GROWTH_DELTA_FACTOR),
                DEFAULT_RESONANCE_MIN_GROWTH_DELTA_FACTOR,
            ),
            sustained_sdpf_enabled=bool(data.get("sustained_sdpf_enabled", False)),
            sustained_sdpf_duration_ms=normalize_positive_float(
                data.get("sustained_sdpf_duration_ms", DEFAULT_SUSTAINED_SDPF_DURATION_MS),
                DEFAULT_SUSTAINED_SDPF_DURATION_MS,
            ),
            sustained_sdpf_ranking_settings_by_project=normalize_project_sustained_sdpf_ranking_settings(
                data.get("sustained_sdpf_ranking_settings_by_project", {})
            ),
            sustained_sdpf_heatmap_settings_by_project=normalize_project_sustained_sdpf_heatmap_settings(
                data.get("sustained_sdpf_heatmap_settings_by_project", {})
            ),
            sustained_sdpf_limit_overrides_by_project=normalize_project_sustained_sdpf_limit_overrides(
                data.get("sustained_sdpf_limit_overrides_by_project", {})
            ),
            voltage_um_overrides_by_project=normalize_project_voltage_um_overrides(
                data.get("voltage_um_overrides_by_project", {})
            ),
            manual_exclusions_by_project=manual_exclusions,
            disabled_nonconv_by_project=normalize_project_case_run_exclusions(
                data.get("disabled_nonconv_by_project", {})
            ),
            high_voltage_include_overrides_by_project=normalize_project_high_voltage_exclusions(
                data.get("high_voltage_include_overrides_by_project", {})
            ),
            dashboard_figure_apply_to_all=bool(
                data.get("dashboard_figure_apply_to_all", True)
            ),
            dashboard_figure_shared_selection=shared_dashboard_selection,
            dashboard_figure_shared_selection_initialized=shared_dashboard_selection_initialized,
            dashboard_figure_selection_by_project=dashboard_selection_by_project,
            status_cache={
                str(key): [str(item) for item in value]
                for key, value in _json_dict(data.get("status_cache")).items()
                if isinstance(value, list)
            },
        )
        if not session.voltages:
            session.voltages = list(DEFAULT_VOLTAGES)
        if not session.events:
            session.events = list(DEFAULT_EVENTS)
        if not session.scopes:
            session.scopes = [ScopeEntry.full()]
        session.ensure_full_scope()
        return session
