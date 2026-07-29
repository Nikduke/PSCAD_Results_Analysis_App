from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
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
DEFAULT_ENVELOPE_FALLBACK_FREQUENCY = 50.0
DEFAULT_ENVELOPE_WORKERS = 4
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


def normalize_tokens(text: str | list[str] | tuple[str, ...]) -> list[str]:
    if isinstance(text, str):
        raw_tokens = re.split(r"[,;\s]+", text)
    else:
        raw_tokens = [str(value) for value in text]

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
        return max(1, int(value))
    except (TypeError, ValueError):
        return DEFAULT_ENVELOPE_WORKERS


def normalize_positive_int(value: Any, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return number if number > 0 else default


def normalize_positive_float(value: Any, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if number > 0 else default


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
    envelope_time_step: float = DEFAULT_ENVELOPE_TIME_STEP
    envelope_time_end: float = DEFAULT_ENVELOPE_TIME_END
    envelope_fallback_frequency: float = DEFAULT_ENVELOPE_FALLBACK_FREQUENCY
    envelope_chart_x_max: float = DEFAULT_ENVELOPE_CHART_X_MAX
    envelope_chart_x_major: float = DEFAULT_ENVELOPE_CHART_X_MAJOR
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
    voltage_um_overrides_by_project: dict[str, dict[str, float]] = field(default_factory=dict)
    manual_exclusions_by_project: dict[str, list[ExclusionRule]] = field(default_factory=dict)
    disabled_nonconv_by_project: dict[str, list[tuple[str, int]]] = field(default_factory=dict)
    high_voltage_exclusions_by_project: dict[str, list[tuple[str, str, int, str]]] = field(default_factory=dict)
    dashboard_figure_selection: list[str] = field(default_factory=list)
    dashboard_figure_selection_initialized: bool = False
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
            "envelope_time_step": self.envelope_time_step,
            "envelope_time_end": self.envelope_time_end,
            "envelope_fallback_frequency": self.envelope_fallback_frequency,
            "envelope_chart_x_max": self.envelope_chart_x_max,
            "envelope_chart_x_major": self.envelope_chart_x_major,
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
            "voltage_um_overrides_by_project": self.voltage_um_overrides_by_project,
            "manual_exclusions_by_project": {
                project: [rule.to_dict() for rule in exclusions]
                for project, exclusions in self.manual_exclusions_by_project.items()
            },
            "disabled_nonconv_by_project": {
                project: [{"case": case, "run": run} for case, run in exclusions]
                for project, exclusions in self.disabled_nonconv_by_project.items()
            },
            "high_voltage_exclusions_by_project": {
                project: [
                    {"voltage": voltage, "case": case, "run": run, "bus": bus}
                    for voltage, case, run, bus in exclusions
                ]
                for project, exclusions in self.high_voltage_exclusions_by_project.items()
            },
            "dashboard_figure_selection": self.dashboard_figure_selection,
            "dashboard_figure_selection_initialized": self.dashboard_figure_selection_initialized,
            "status_cache": self.status_cache,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppSession":
        manual_exclusions = normalize_project_exclusion_rules(
            data.get("manual_exclusions_by_project", {})
        )
        legacy_exclusions = migrate_legacy_project_exclusions(
            data.get("bus_exclusions_by_project", {}),
            data.get("manual_case_run_exclusions_by_project", {}),
        )
        for project, rules in legacy_exclusions.items():
            manual_exclusions[project] = normalize_exclusion_rules(
                [*manual_exclusions.get(project, []), *rules]
            )
        dashboard_selection = [
            str(item) for item in data.get("dashboard_figure_selection", []) if str(item)
        ]
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
            for value in data.get("events", DEFAULT_EVENTS)
            if str(value) in DEFAULT_EVENTS
        }

        session = cls(
            projects=[
                ProjectEntry.from_dict(value)
                for value in data.get("projects", [])
                if isinstance(value, dict)
            ],
            scopes=[
                ScopeEntry.from_dict(value)
                for value in data.get("scopes", [])
                if isinstance(value, dict)
            ],
            voltages=[
                str(value)
                for value in data.get("voltages", DEFAULT_VOLTAGES)
                if str(value).strip()
            ],
            events=[event for event in DEFAULT_EVENTS if event in raw_events],
            event_times=event_times,
            envelope_workers=normalize_worker_count(data.get("envelope_workers", DEFAULT_ENVELOPE_WORKERS)),
            envelope_time_step=normalize_positive_float(
                data.get("envelope_time_step", DEFAULT_ENVELOPE_TIME_STEP),
                DEFAULT_ENVELOPE_TIME_STEP,
            ),
            envelope_time_end=normalize_positive_float(
                data.get("envelope_time_end", DEFAULT_ENVELOPE_TIME_END),
                DEFAULT_ENVELOPE_TIME_END,
            ),
            envelope_fallback_frequency=normalize_positive_float(
                data.get("envelope_fallback_frequency", DEFAULT_ENVELOPE_FALLBACK_FREQUENCY),
                DEFAULT_ENVELOPE_FALLBACK_FREQUENCY,
            ),
            envelope_chart_x_max=normalize_positive_float(
                data.get("envelope_chart_x_max", DEFAULT_ENVELOPE_CHART_X_MAX),
                DEFAULT_ENVELOPE_CHART_X_MAX,
            ),
            envelope_chart_x_major=normalize_positive_float(
                data.get("envelope_chart_x_major", DEFAULT_ENVELOPE_CHART_X_MAJOR),
                DEFAULT_ENVELOPE_CHART_X_MAJOR,
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
                for value in data.get("resonance_enabled_checks", [])
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
            voltage_um_overrides_by_project=normalize_project_voltage_um_overrides(
                data.get("voltage_um_overrides_by_project", {})
            ),
            manual_exclusions_by_project=manual_exclusions,
            disabled_nonconv_by_project=normalize_project_case_run_exclusions(
                data.get("disabled_nonconv_by_project", {})
            ),
            high_voltage_exclusions_by_project=normalize_project_high_voltage_exclusions(
                data.get("high_voltage_exclusions_by_project", {})
            ),
            dashboard_figure_selection=dashboard_selection,
            dashboard_figure_selection_initialized=bool(
                data.get("dashboard_figure_selection_initialized", bool(dashboard_selection))
            ),
            status_cache={
                str(key): [str(item) for item in value]
                for key, value in data.get("status_cache", {}).items()
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
