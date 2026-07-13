from __future__ import annotations

from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import math
import os
import threading
import time

import numpy as np
import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from results_analysis_app import resonance_checks
from results_analysis_app.envelope_chart import create_combined_envelope_plot, create_resonance_check_charts
from results_analysis_app.excel import excel_app
from results_analysis_app.models import (
    DEFAULT_ENVELOPE_CHART_X_MAJOR,
    DEFAULT_ENVELOPE_CHART_X_MAX,
    DEFAULT_ENVELOPE_CHART_HEIGHT,
    DEFAULT_ENVELOPE_CHART_WIDTH,
    DEFAULT_ENVELOPE_FALLBACK_FREQUENCY,
    DEFAULT_ENVELOPE_TIME_END,
    DEFAULT_ENVELOPE_TIME_STEP,
    DEFAULT_HIGH_VOLTAGE_LIMIT_FACTOR,
    DEFAULT_NONCONV_CB_IIP_LIMIT,
    DEFAULT_NONCONV_CB_IIR_LIMIT,
    ScopeEntry,
    normalize_bus_exclusions,
    normalize_case_run_exclusions,
    normalize_high_voltage_exclusions,
)
from results_analysis_app.project_config import load_project_frequency, load_voltage_configs
from pscad_plotter_app_v3.services.waveform_io import (
    InfDescriptor,
    case_run_from_inf_path,
    load_out_columns,
    out_file_for_pgb,
    parse_inf_descriptors,
)


LogFn = Callable[[str], None]
CancelFn = Callable[[], None]
FrequencyFallbackFn = Callable[[str], None]
OutFileData = tuple[np.ndarray, dict[int, np.ndarray]]

FREQUENCY_FALLBACK_MESSAGE_PREFIX = "FREQUENCY_FALLBACK|"
HIGH_VOLTAGE_LIMIT_FACTOR = DEFAULT_HIGH_VOLTAGE_LIMIT_FACTOR
NONCONV_CB_IIP_LIMIT = DEFAULT_NONCONV_CB_IIP_LIMIT
NONCONV_CB_IIR_LIMIT = DEFAULT_NONCONV_CB_IIR_LIMIT
TIME_STEP = DEFAULT_ENVELOPE_TIME_STEP
TIME_END = DEFAULT_ENVELOPE_TIME_END
DEFAULT_MAX_WORKERS = 8
MAX_WORKERS_ENV = "RESULTS_ANALYSIS_ENVELOPE_WORKERS"

ENVELOPE_HEADERS = [
    "Time (s)",
    "Max_A", "Max_B", "Max_C",
    "Case_A", "Case_B", "Case_C",
    "Run_A", "Run_B", "Run_C",
    "Fault_type_A", "Fault_type_B", "Fault_type_C",
    "MM_name_A", "MM_name_B", "MM_name_C",
    "Max_all", "Case_all", "Run_all", "Fault_type_all", "MM_name_all",
]
NONCONV_COLUMNS = ["Case", "Run", "Fault_type", "Source", "Signal", "Reason", "Value", "File"]
HIGH_VOLTAGE_COLUMNS = ["Case", "Run", "Fault_type", "MM_name", "Measurement", "Signal", "File", "Excluded_values", "Max_abs", "Limit"]


@dataclass
class _VoltageBuildResult:
    chart_inputs: list[tuple[str, Path, Path]]
    resonance_results: list[resonance_checks.ResonanceResult]
    data_outputs: list[Path]


def build_voltage_envelopes(
    project_root: Path,
    scopes: Iterable[ScopeEntry],
    voltages: Iterable[str],
    log: LogFn | None = None,
    check_cancel: CancelFn | None = None,
    envelope_workers: int | None = None,
    bus_exclusions_by_voltage: dict[str, list[str]] | None = None,
    manual_case_run_exclusions: list[tuple[str, int]] | None = None,
    high_voltage_exclusions: list[tuple[str, str, int, str]] | None = None,
    envelope_time_step: float | None = None,
    envelope_time_end: float | None = None,
    envelope_fallback_frequency: float | None = None,
    envelope_chart_x_max: float | None = None,
    envelope_chart_x_major: float | None = None,
    envelope_chart_y_limits_by_voltage: dict[str, dict[str, float | None]] | None = None,
    envelope_chart_show_sa_label: bool = False,
    envelope_chart_top_left_cell: str | None = None,
    envelope_chart_width: float | None = None,
    envelope_chart_height: float | None = None,
    high_voltage_limit_factor: float | None = None,
    nonconv_cb_iip_limit: float | None = None,
    nonconv_cb_iir_limit: float | None = None,
    event_times: dict[str, float] | None = None,
    voltage_um_overrides: dict[str, float] | None = None,
    resonance_settings: dict[str, Any] | None = None,
    build_charts: bool = True,
) -> list[Path]:
    started = time.perf_counter()
    project_root = Path(project_root)
    case_root = project_root / "Case_folder"
    if not case_root.is_dir():
        raise FileNotFoundError(f"Case_folder not found: {case_root}")

    _log(log, f"Reading statistic and convergence data: {project_root.name}")
    stat_started = time.perf_counter()
    df_stat = _read_stat_files(project_root)
    cb_iip_limit = _positive_float(nonconv_cb_iip_limit, NONCONV_CB_IIP_LIMIT)
    cb_iir_limit = _positive_float(nonconv_cb_iir_limit, NONCONV_CB_IIR_LIMIT)
    df_nonconv = _find_non_convergent_cases(case_root, df_stat, cb_iip_limit, cb_iir_limit)
    _log(log, f"Envelope setup complete: {project_root.name} | {_elapsed(stat_started)}")
    detected_nonconv_keys = _nonconv_keys(df_nonconv)
    manual_nonconv_keys = set(normalize_case_run_exclusions(manual_case_run_exclusions or []))
    nonconv_keys = manual_nonconv_keys
    if detected_nonconv_keys:
        _log(log, f"Detected non-convergent proposals: {len(detected_nonconv_keys)}")
    if manual_nonconv_keys:
        _log(log, f"Applied case/run exclusions: {len(manual_nonconv_keys)}")
    bus_exclusions = normalize_bus_exclusions(bus_exclusions_by_voltage or {})
    applied_high_voltage = normalize_high_voltage_exclusions(high_voltage_exclusions or [])
    chart_axis_limits = _chart_axis_limits(envelope_chart_x_max, envelope_chart_x_major)
    limit_factor = _positive_float(high_voltage_limit_factor, HIGH_VOLTAGE_LIMIT_FACTOR)
    time_step = _positive_float(envelope_time_step, TIME_STEP)
    time_end = _positive_float(envelope_time_end, TIME_END)
    resonance_settings_obj = resonance_checks.ResonanceSettings.from_mapping(resonance_settings)
    if resonance_settings_obj.enabled and not resonance_settings_obj.auto_release:
        if not (0.0 <= resonance_settings_obj.manual_analysis_start < time_end):
            raise ValueError("Manual analysis start time must be within [0, envelope time end).")
        if resonance_checks.NO_SETTLE_GROWTH in resonance_settings_obj.enabled_checks:
            _log(log, "No-settle growth skipped: manual analysis start time is enabled, so physical release detection is bypassed.")
    settings_fallback_frequency = _positive_float(envelope_fallback_frequency, DEFAULT_ENVELOPE_FALLBACK_FREQUENCY)
    project_frequency = load_project_frequency(project_root)
    fallback_frequency = project_frequency or settings_fallback_frequency
    if project_frequency is not None:
        _log(log, f"Fallback frequency from Input_Data!B16: {fallback_frequency:g} Hz")
    else:
        _log(log, f"Fallback frequency from Settings: {fallback_frequency:g} Hz")
    frequency_warning_lock = threading.Lock()
    frequency_warning_sent = False

    def notify_frequency_fallback(context: str) -> None:
        nonlocal frequency_warning_sent
        with frequency_warning_lock:
            first_warning = not frequency_warning_sent
            frequency_warning_sent = True
        if project_frequency is not None:
            _log(log, f"Frequency auto-detection failed; using Input_Data!B16 {fallback_frequency:g} Hz: {context}")
            return
        if first_warning:
            _log(
                log,
                f"{FREQUENCY_FALLBACK_MESSAGE_PREFIX}{project_root.name}|{fallback_frequency:g}|{context}",
            )
        else:
            _log(log, f"Frequency auto-detection failed; using fallback {fallback_frequency:g} Hz: {context}")

    chart_size = {
        "width": _positive_float(envelope_chart_width, DEFAULT_ENVELOPE_CHART_WIDTH),
        "height": _positive_float(envelope_chart_height, DEFAULT_ENVELOPE_CHART_HEIGHT),
    }
    voltage_configs = load_voltage_configs(project_root, um_overrides=voltage_um_overrides)
    outputs: list[Path] = []

    selected_scopes = list(scopes)
    scope_inf_paths = {
        scope.folder: _selected_inf_paths(case_root, scope, nonconv_keys)
        for scope in selected_scopes
    }
    for scope in selected_scopes:
        if not scope_inf_paths[scope.folder]:
            _log(log, f"No PSCAD run files match scope: {project_root.name} | {scope.folder}")

    voltage_keys = [str(voltage).strip() for voltage in voltages if str(voltage).strip()]
    all_inf_paths = sorted({path for paths in scope_inf_paths.values() for path in paths})
    total_workers = _configured_worker_count(envelope_workers)
    inf_descriptor_cache = _read_inf_descriptor_cache(all_inf_paths, total_workers, check_cancel)
    voltage_worker_count = max(1, min(len(voltage_keys) or 1, total_workers))
    per_voltage_workers = max(1, total_workers // voltage_worker_count)
    _log(log, f"Envelope worker plan: voltages={voltage_worker_count}, per voltage={per_voltage_workers}, total={total_workers}")

    chart_inputs: list[tuple[str, Path, Path]] = []
    data_outputs: list[Path] = []
    resonance_results: list[resonance_checks.ResonanceResult] = []
    with ThreadPoolExecutor(max_workers=voltage_worker_count) as executor:
        futures = {
            executor.submit(
                _build_voltage_workbooks,
                project_root,
                selected_scopes,
                scope_inf_paths,
                all_inf_paths,
                inf_descriptor_cache,
                voltage_key,
                voltage_configs,
                bus_exclusions,
                applied_high_voltage,
                limit_factor,
                time_step,
                time_end,
                fallback_frequency,
                df_stat,
                df_nonconv,
                per_voltage_workers,
                log,
                check_cancel,
                notify_frequency_fallback,
                resonance_settings_obj,
                event_times,
            ): voltage_key
            for voltage_key in voltage_keys
        }
        for future in as_completed(futures):
            _cancel(check_cancel)
            result = future.result()
            chart_inputs.extend(result.chart_inputs)
            data_outputs.extend(result.data_outputs)
            resonance_results.extend(result.resonance_results)

    resonance_workbooks: list[Path] = []
    if resonance_settings_obj.enabled:
        for workbook_path in resonance_checks.write_workbooks(
            project_root,
            selected_scopes,
            resonance_results,
            resonance_settings_obj,
            event_times,
        ):
            resonance_workbooks.append(workbook_path)
            _log(log, f"Resonance checks workbook finished: {workbook_path}")

    if build_charts:
        chart_inputs.sort(key=lambda item: (voltage_keys.index(item[0]) if item[0] in voltage_keys else 999, str(item[1])))
        with ExitStack() as stack:
            excel = stack.enter_context(excel_app()) if chart_inputs or resonance_workbooks else None
            for voltage_key, envelope_path, combined_path in chart_inputs:
                chart_started = time.perf_counter()
                create_combined_envelope_plot(
                    envelope_path,
                    combined_path,
                    excel,
                    axis_limits_override=chart_axis_limits,
                    axis_limits_by_voltage=envelope_chart_y_limits_by_voltage,
                    event_times=event_times,
                    show_sa_label=envelope_chart_show_sa_label,
                    chart_top_left_cell=envelope_chart_top_left_cell,
                    chart_size=chart_size,
                )
                outputs.append(combined_path)
                _log(log, f"Envelope chart finished: {voltage_key} kV | {combined_path.name} | {_elapsed(chart_started)}")
            for workbook_path in resonance_workbooks:
                chart_started = time.perf_counter()
                if create_resonance_check_charts(workbook_path, excel):
                    _log(log, f"Analysis charts finished: {workbook_path.name} | {_elapsed(chart_started)}")
    else:
        outputs.extend(data_outputs)
        outputs.extend(resonance_workbooks)

    _log(log, f"Envelope build total: {project_root.name} | {_elapsed(started)}")
    return outputs


def _log(log: LogFn | None, message: str) -> None:
    if log is not None:
        log(message)


def _cancel(check_cancel: CancelFn | None) -> None:
    if check_cancel is not None:
        check_cancel()


def _elapsed(started: float) -> str:
    return f"{time.perf_counter() - started:.1f}s"


def _configured_worker_count(envelope_workers: int | None = None) -> int:
    if envelope_workers is not None:
        return max(1, int(envelope_workers))
    try:
        configured = int(os.environ.get(MAX_WORKERS_ENV, str(DEFAULT_MAX_WORKERS)))
    except ValueError:
        configured = DEFAULT_MAX_WORKERS
    return max(1, configured)


def _positive_float(value: float | None, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if number > 0 else default


def _nominal_voltage_from_key(voltage_key: str, default: float) -> float:
    try:
        number = float(str(voltage_key).strip())
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) and number > 0 else default


def _chart_axis_limits(x_max: float | None, x_major: float | None) -> dict[str, float]:
    return {
        "x_max": _positive_float(x_max, DEFAULT_ENVELOPE_CHART_X_MAX),
        "x_major": _positive_float(x_major, DEFAULT_ENVELOPE_CHART_X_MAJOR),
    }


def _build_voltage_workbooks(
    project_root: Path,
    selected_scopes: list[ScopeEntry],
    scope_inf_paths: dict[str, list[Path]],
    all_inf_paths: list[Path],
    inf_descriptor_cache: dict[Path, list[InfDescriptor]],
    voltage_key: str,
    voltage_configs,
    bus_exclusions: dict[str, list[str]],
    applied_high_voltage: list[tuple[str, str, int, str]],
    high_voltage_limit_factor: float,
    time_step: float,
    time_end: float,
    fallback_frequency: float,
    df_stat: pd.DataFrame,
    df_nonconv: pd.DataFrame,
    worker_count: int,
    log: LogFn | None,
    check_cancel: CancelFn | None,
    frequency_fallback: FrequencyFallbackFn | None = None,
    resonance_settings: resonance_checks.ResonanceSettings | None = None,
    event_times: dict[str, float] | None = None,
) -> _VoltageBuildResult:
    started = time.perf_counter()
    _cancel(check_cancel)
    config = voltage_configs.get(voltage_key)
    if config is None:
        _log(log, f"Envelope voltage skipped; no MM_blocks Um config: {voltage_key} kV")
        return _VoltageBuildResult([], [], [])

    if not all_inf_paths:
        return _VoltageBuildResult([], [], [])

    bus_prefix, bus_um = config.bus_prefix, config.um
    nominal_voltage = _nominal_voltage_from_key(voltage_key, bus_um)
    excluded_buses = set(bus_exclusions.get(voltage_key, []))
    if excluded_buses:
        _log(log, f"Bus exclusions: {voltage_key} kV | {len(excluded_buses)} buses")
    excluded_bus_runs = {
        (case, run, bus)
        for voltage, case, run, bus in applied_high_voltage
        if voltage == voltage_key
    }
    if excluded_bus_runs:
        _log(log, f"High-voltage bus/run exclusions: {voltage_key} kV | {len(excluded_bus_runs)}")

    _log(log, f"Envelope source read started: {voltage_key} kV | {len(all_inf_paths)} unique runs")
    read_started = time.perf_counter()
    run_cache = _read_voltage_run_cache(
        all_inf_paths,
        bus_prefix,
        bus_um,
        excluded_buses,
        excluded_bus_runs,
        worker_count,
        log,
        check_cancel,
        high_voltage_limit_factor=high_voltage_limit_factor,
        time_step=time_step,
        time_end=time_end,
        fallback_frequency=fallback_frequency,
        frequency_fallback=frequency_fallback,
        inf_descriptor_cache=inf_descriptor_cache,
    )
    _log(log, f"Envelope source read finished: {voltage_key} kV | {_elapsed(read_started)}")

    chart_inputs: list[tuple[str, Path, Path]] = []
    data_outputs: list[Path] = []
    resonance_results: list[resonance_checks.ResonanceResult] = []
    resonance_settings = resonance_settings or resonance_checks.ResonanceSettings()
    for scope in selected_scopes:
        inf_paths = scope_inf_paths[scope.folder]
        if not inf_paths:
            continue

        _cancel(check_cancel)
        scope_started = time.perf_counter()
        _log(log, f"Envelope merge started: {scope.folder} | {voltage_key} kV | {len(inf_paths)} runs")
        entries, high_voltage = _entries_for_inf_paths(inf_paths, run_cache)
        if resonance_settings.enabled:
            records = []
            for voltage_type in resonance_checks.VOLTAGE_TYPES:
                records.extend(
                    resonance_checks.records_from_entries(
                        scope.folder,
                        voltage_key,
                        voltage_type,
                        nominal_voltage,
                        entries,
                    )
                )
            scope_results = resonance_checks.analyze_records(records, resonance_settings, event_times)
            resonance_results.extend(scope_results)
            _log(
                log,
                f"Resonance checks finished: {scope.folder} | {voltage_key} kV | selected={len(scope_results)}",
            )
        lg_df = _final_envelope([df for measurement, df in entries if measurement == "LGp"], df_stat, time_step)
        ll_df = _final_envelope([df for measurement, df in entries if measurement == "LLp"], df_stat, time_step)
        if lg_df.empty or ll_df.empty:
            _log(log, f"No waveform envelope data: {scope.folder} | {voltage_key} kV")
            continue
        high_voltage_df = _map_exclusion_fault_types(pd.DataFrame(high_voltage), df_stat, HIGH_VOLTAGE_COLUMNS)
        high_voltage_df = _filter_dataframe_by_scope(high_voltage_df, scope)
        nonconv_df = _filter_dataframe_by_scope(df_nonconv, scope)

        write_started = time.perf_counter()
        envelope_path = project_root / "Voltage_envelope" / scope.folder / f"MM_{voltage_key}.xlsx"
        combined_path = envelope_path.with_name(f"{envelope_path.stem}_with_combined_plot.xlsx")
        _write_workbook(envelope_path, lg_df, ll_df, nonconv_df, high_voltage_df)
        data_outputs.append(envelope_path)
        chart_inputs.append((voltage_key, envelope_path, combined_path))
        _log(
            log,
            f"Envelope workbook finished: {scope.folder} | {voltage_key} kV | "
            f"LG rows={len(lg_df)}, LL rows={len(ll_df)} | merge+write={_elapsed(scope_started)}, write={_elapsed(write_started)}",
        )

    _log(log, f"Envelope voltage finished: {voltage_key} kV | {_elapsed(started)}")
    return _VoltageBuildResult(chart_inputs, resonance_results, data_outputs)


def _scope_text(path: Path) -> str:
    try:
        case, run = case_run_from_inf_path(path)
    except ValueError:
        case, run = path.stem, ""
    return f"{case} {run} {path.parent.name} {path}".casefold()


def _path_matches_scope(path: Path, scope: ScopeEntry) -> bool:
    if scope.mode == "full":
        return True
    tokens = [token.casefold() for token in scope.tokens]
    matched = any(token in _scope_text(path) for token in tokens)
    return matched if scope.mode == "include" else not matched


def _selected_inf_paths(case_root: Path, scope: ScopeEntry, excluded_keys: set[tuple[str, int]]) -> list[Path]:
    paths: list[Path] = []
    for path in sorted(case_root.rglob("*.inf")):
        try:
            key = case_run_from_inf_path(path)
        except ValueError:
            continue
        if key in excluded_keys:
            continue
        if _path_matches_scope(path, scope):
            paths.append(path)
    return paths


def _worker_count(item_count: int, configured: int) -> int:
    if item_count <= 0:
        return 1
    return max(1, min(item_count, os.cpu_count() or 1, configured))


def _read_inf_descriptor_cache(
    inf_paths: list[Path],
    worker_count: int,
    check_cancel: CancelFn | None,
) -> dict[Path, list[InfDescriptor]]:
    if not inf_paths:
        return {}

    descriptor_cache: dict[Path, list[InfDescriptor]] = {}
    workers = _worker_count(len(inf_paths), worker_count)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(parse_inf_descriptors, inf_path): inf_path for inf_path in inf_paths}
        for future in as_completed(futures):
            _cancel(check_cancel)
            inf_path = futures[future]
            try:
                descriptor_cache[inf_path] = future.result()
            except ValueError:
                continue
    return descriptor_cache


def _read_voltage_run_cache(
    inf_paths: list[Path],
    bus_prefix: str,
    bus_um: float,
    excluded_buses: set[str],
    excluded_bus_runs: set[tuple[str, int, str]],
    worker_count: int,
    log: LogFn | None,
    check_cancel: CancelFn | None,
    high_voltage_limit_factor: float = HIGH_VOLTAGE_LIMIT_FACTOR,
    time_step: float = TIME_STEP,
    time_end: float = TIME_END,
    fallback_frequency: float = DEFAULT_ENVELOPE_FALLBACK_FREQUENCY,
    frequency_fallback: FrequencyFallbackFn | None = None,
    inf_descriptor_cache: dict[Path, list[InfDescriptor]] | None = None,
) -> dict[Path, tuple[list[tuple[str, pd.DataFrame]], list[dict[str, Any]]]]:
    limit = high_voltage_limit_factor * bus_um * math.sqrt(2)
    run_cache: dict[Path, tuple[list[tuple[str, pd.DataFrame]], list[dict[str, Any]]]] = {}

    workers = _worker_count(len(inf_paths), worker_count)
    completed = 0
    executor = ThreadPoolExecutor(max_workers=workers)
    try:
        futures = {}
        for inf_path in inf_paths:
            _cancel(check_cancel)
            futures[
                executor.submit(
                    _read_run_entries,
                    inf_path,
                    limit,
                    bus_prefix,
                    excluded_buses,
                    excluded_bus_runs,
                    time_step,
                    time_end,
                    fallback_frequency,
                    frequency_fallback,
                    check_cancel,
                    inf_descriptor_cache,
                )
            ] = inf_path
        for future in as_completed(futures):
            _cancel(check_cancel)
            inf_path = futures[future]
            try:
                run_entries, run_exclusions = future.result()
            except ValueError as exc:
                if "no results" not in str(exc).casefold():
                    raise
                run_entries, run_exclusions = [], []
            run_cache[inf_path] = (run_entries, run_exclusions)
            completed += 1
            if completed == 1 or completed == len(inf_paths) or completed % 10 == 0:
                _log(log, f"Envelope source files read: {bus_prefix} | {completed}/{len(inf_paths)}")
    except Exception:
        executor.shutdown(wait=True, cancel_futures=True)
        raise
    else:
        executor.shutdown(wait=True)

    return run_cache


def _entries_for_inf_paths(
    inf_paths: list[Path],
    run_cache: dict[Path, tuple[list[tuple[str, pd.DataFrame]], list[dict[str, Any]]]],
) -> tuple[list[tuple[str, pd.DataFrame]], list[dict[str, Any]]]:
    entries: list[tuple[str, pd.DataFrame]] = []
    high_voltage: list[dict[str, Any]] = []
    for inf_path in inf_paths:
        run_entries, run_exclusions = run_cache.get(inf_path, ([], []))
        entries.extend(run_entries)
        high_voltage.extend(run_exclusions)
    return entries, high_voltage


def _read_run_entries(
    inf_path: Path,
    limit: float,
    bus_prefix: str,
    excluded_buses: set[str],
    excluded_bus_runs: set[tuple[str, int, str]],
    time_step: float = TIME_STEP,
    time_end: float = TIME_END,
    fallback_frequency: float = DEFAULT_ENVELOPE_FALLBACK_FREQUENCY,
    frequency_fallback: FrequencyFallbackFn | None = None,
    check_cancel: CancelFn | None = None,
    inf_descriptor_cache: dict[Path, list[InfDescriptor]] | None = None,
) -> tuple[list[tuple[str, pd.DataFrame]], list[dict[str, Any]]]:
    _cancel(check_cancel)
    case_name, run = case_run_from_inf_path(inf_path)
    if inf_descriptor_cache is None or inf_path not in inf_descriptor_cache:
        df_desc = _parse_inf(inf_path, bus_prefix, excluded_buses)
    else:
        df_desc = _filter_inf_descriptors(inf_descriptor_cache[inf_path], bus_prefix, excluded_buses)
    _cancel(check_cancel)
    out_cache = _read_out_files(df_desc, inf_path, check_cancel)
    candidates: list[tuple[str, str, pd.DataFrame]] = []
    high_voltage: list[dict[str, Any]] = []

    for measurement in ("LGp", "LLp"):
        _cancel(check_cancel)
        df_meas = df_desc[df_desc["Description"].str.contains(measurement, na=False)]
        for bus in df_meas["Group"].unique():
            _cancel(check_cancel)
            df_bus = df_meas[df_meas["Group"] == bus]
            envelope_df, exclusions = _build_bus_envelope(
                df_bus,
                bus,
                out_cache,
                inf_path,
                limit,
                case_name,
                run,
                measurement,
                time_step,
                time_end,
                fallback_frequency,
                frequency_fallback,
                check_cancel,
            )
            if envelope_df is not None:
                candidates.append((measurement, bus, envelope_df))
            high_voltage.extend(exclusions)

    entries: list[tuple[str, pd.DataFrame]] = []
    for measurement, bus, envelope_df in candidates:
        _cancel(check_cancel)
        if (case_name, int(run), bus) in excluded_bus_runs:
            continue
        envelope_df["MM_name"] = bus
        envelope_df["Case"] = f"{case_name}-{run}"
        entries.append((measurement, envelope_df))

    return entries, high_voltage


def _parse_inf(inf_path: Path, bus_prefix: str, excluded_buses: set[str] | None = None) -> pd.DataFrame:
    try:
        descriptors = parse_inf_descriptors(inf_path)
    except ValueError as exc:
        raise ValueError("There are no results in your data") from exc
    return _filter_inf_descriptors(descriptors, bus_prefix, excluded_buses)


def _filter_inf_descriptors(
    descriptors: list[InfDescriptor],
    bus_prefix: str,
    excluded_buses: set[str] | None = None,
) -> pd.DataFrame:
    excluded = {bus.strip() for bus in excluded_buses or () if bus.strip()}
    records = [
        {"PGB": descriptor.PGB, "Description": descriptor.Description, "Group": descriptor.Group}
        for descriptor in descriptors
        if descriptor.Group.startswith(bus_prefix)
        and "p_" in descriptor.Description
        and descriptor.Group.strip() not in excluded
    ]
    df_desc = pd.DataFrame(
        records,
        index=[int(record["PGB"]) - 1 for record in records],
        columns=["PGB", "Description", "Group"],
    )
    if df_desc.empty:
        raise ValueError("There are no results in your data")
    return df_desc


def _read_out_files(
    df_desc: pd.DataFrame,
    inf_path: Path,
    check_cancel: CancelFn | None = None,
) -> dict[Path, OutFileData]:
    file_col_map: dict[Path, set[int]] = {}
    for phase_index in df_desc.index:
        _cancel(check_cancel)
        out_path, col_number = out_file_for_pgb(inf_path, int(phase_index) + 1)
        file_col_map.setdefault(out_path, set()).add(col_number)

    out_cache: dict[Path, OutFileData] = {}
    for out_path, cols in file_col_map.items():
        _cancel(check_cancel)
        read_cols = sorted([0, *cols])
        columns = load_out_columns(out_path, read_cols)
        time_values = np.round(columns[0], 6)
        out_cache[out_path] = (
            time_values,
            {
                column: columns[column]
                for column in read_cols[1:]
            },
        )
        _cancel(check_cancel)
    return out_cache


def _build_bus_envelope(
    df_bus: pd.DataFrame,
    bus: str,
    out_cache: dict[Path, OutFileData],
    inf_path: Path,
    limit: float,
    case_name: str,
    run: int,
    measurement: str,
    time_step: float,
    time_end: float,
    fallback_frequency: float,
    frequency_fallback: FrequencyFallbackFn | None = None,
    check_cancel: CancelFn | None = None,
) -> tuple[pd.DataFrame | None, list[dict[str, Any]]]:
    times: list[np.ndarray] = []
    values: list[np.ndarray] = []
    signals: list[str] = []
    exclusions: list[dict[str, Any]] = []
    for phase_index in df_bus.index:
        _cancel(check_cancel)
        signal = bus + "-" + str(df_bus.loc[phase_index, "Description"]).replace("MM_", "")
        out_path, col_number = out_file_for_pgb(inf_path, int(phase_index) + 1)
        time_values, columns = out_cache[out_path]
        phase_values = columns[col_number]
        times.append(time_values)
        values.append(phase_values)
        signals.append(signal)

        abs_values = np.abs(phase_values)
        over_limit = abs_values > limit
        if over_limit.any():
            exclusions.append(
                {
                    "Case": case_name,
                    "Run": int(run),
                    "MM_name": bus,
                    "Measurement": measurement,
                    "Signal": signal,
                    "File": out_path.name,
                    "Excluded_values": int(over_limit.sum()),
                    "Max_abs": float(abs_values[over_limit].max()),
                    "Limit": limit,
                }
            )

    if not values:
        return None, exclusions
    context = f"{case_name} run {run} | {bus} | {measurement}"
    _cancel(check_cancel)
    if _arrays_share_timebase(times):
        envelope = _apply_envelope_arrays(
            times[0],
            values,
            time_step,
            time_end,
            fallback_frequency,
            context,
            frequency_fallback,
        )
        _cancel(check_cancel)
        return envelope, exclusions
    envelope = _apply_envelope(
        _phase_dataframe_from_arrays(times, values, signals),
        time_step,
        time_end,
        fallback_frequency,
        context,
        frequency_fallback,
    )
    _cancel(check_cancel)
    return envelope, exclusions


def _arrays_share_timebase(times: list[np.ndarray]) -> bool:
    first = times[0]
    return all(time_values.shape == first.shape and np.array_equal(time_values, first) for time_values in times[1:])


def _phase_dataframe_from_arrays(
    times: list[np.ndarray],
    values: list[np.ndarray],
    signals: list[str],
) -> pd.DataFrame:
    output = pd.DataFrame({"Time (s)": times[0], signals[0]: values[0]})
    for time_values, phase_values, signal in zip(times[1:], values[1:], signals[1:]):
        phase_df = pd.DataFrame({"Time (s)": time_values, signal: phase_values})
        output = pd.merge(output, phase_df, on="Time (s)", how="outer")
    return output


def _apply_envelope_arrays(
    time_values: np.ndarray,
    phase_values: list[np.ndarray],
    time_step: float,
    time_end: float,
    fallback_frequency: float = DEFAULT_ENVELOPE_FALLBACK_FREQUENCY,
    frequency_context: str = "",
    frequency_fallback: FrequencyFallbackFn | None = None,
) -> pd.DataFrame | None:
    dt = round(float(np.median(np.diff(time_values))), 6)
    if not np.isfinite(dt) or dt <= 0:
        return None

    detected_freq = _detect_frequency_from_arrays(
        time_values,
        phase_values,
        fallback_frequency,
        frequency_context,
        frequency_fallback,
    )

    window_size = max(1, int((1 / (2 * detected_freq)) / dt))
    new_time = np.round(np.arange(0.0, time_end, time_step), 6)
    interpolated = {}
    for index, values in enumerate(phase_values):
        abs_values = np.abs(values)
        if np.nanmax(abs_values) < 1e-4:
            continue
        rolling_values = (
            pd.Series(abs_values, index=time_values)
            .rolling(window=window_size, min_periods=1, center=True)
            .max()
            .to_numpy(dtype=float)
        )
        interpolated["Max_" + chr(65 + index)] = np.interp(
            new_time,
            time_values,
            rolling_values,
            left=rolling_values[0],
            right=0.0,
        )
    if not interpolated:
        return None
    output = pd.DataFrame(interpolated, index=new_time)
    output.index.name = "Time (s)"
    return output


def _apply_envelope(
    df: pd.DataFrame,
    time_step: float = TIME_STEP,
    time_end: float = TIME_END,
    fallback_frequency: float = DEFAULT_ENVELOPE_FALLBACK_FREQUENCY,
    frequency_context: str = "",
    frequency_fallback: FrequencyFallbackFn | None = None,
) -> pd.DataFrame | None:
    df = df.copy()
    df.set_index("Time (s)", inplace=True)
    dt = round(df.index.to_series().diff().median(), 6)
    if not np.isfinite(dt) or dt <= 0:
        return None

    phase_cols = list(df.columns)
    max_phase_cols = {col: "Max_" + chr(65 + i) for i, col in enumerate(phase_cols)}
    detected_freq = _detect_frequency_from_arrays(
        df.index.to_numpy(dtype=float),
        [df[col].to_numpy(dtype=float) for col in phase_cols],
        fallback_frequency,
        frequency_context,
        frequency_fallback,
    )

    window_size = max(1, int((1 / (2 * detected_freq)) / dt))
    drop_cols = []
    for col in phase_cols:
        if df[col].abs().max() < 1e-4:
            drop_cols.append(col)
            continue
        df.loc[:, col] = df[col].abs().rolling(window=window_size, min_periods=1, center=True).max()
    df.drop(columns=drop_cols, inplace=True)
    if df.empty:
        return None

    new_time = np.round(np.arange(0.0, time_end, time_step), 6)
    interpolated = {}
    for col in df.columns:
        x = df.index.to_numpy(dtype=float)
        y = df[col].to_numpy(dtype=float)
        interpolated[max_phase_cols[col]] = np.interp(new_time, x, y, left=y[0], right=0.0)
    output = pd.DataFrame(interpolated, index=new_time)
    output.index.name = "Time (s)"
    return output


def _detect_frequency_from_arrays(
    time_values: np.ndarray,
    phase_values: list[np.ndarray],
    fallback_frequency: float,
    frequency_context: str = "",
    frequency_fallback: FrequencyFallbackFn | None = None,
) -> float:
    for values in phase_values:
        if np.nanmax(np.abs(values)) < 1e-4:
            continue
        zero_crossings = np.where(np.diff(np.sign(values)))[0]
        if len(zero_crossings) < 4:
            continue
        detected = round(1 / (2 * np.diff(time_values[zero_crossings[:4]]).mean()), 0)
        if np.isfinite(detected) and detected > 0:
            return float(detected)
    if frequency_fallback is not None:
        frequency_fallback(frequency_context)
    return fallback_frequency


def _final_envelope(
    source_dfs: list[pd.DataFrame],
    df_stat: pd.DataFrame,
    time_step: float = TIME_STEP,
) -> pd.DataFrame:
    if not source_dfs:
        return pd.DataFrame(columns=ENVELOPE_HEADERS)
    merged = _reduce_merge(source_dfs, time_step)
    merged = _map_fault_types_phase(merged, df_stat)
    return _organize_phase_columns(merged)


def _reduce_merge(source_dfs: list[pd.DataFrame], time_step: float = TIME_STEP) -> pd.DataFrame:
    work = list(source_dfs)
    while len(work) > 1:
        merged: list[pd.DataFrame] = []
        for idx in range(0, len(work) - 1, 2):
            merged.append(_merge_list([work[idx], work[idx + 1]], time_step))
        if len(work) % 2 == 1:
            merged.append(work[-1])
        work = merged

    df = _merge_list([work[0]], time_step)
    df = _add_phase_source_cols(df)
    df.reset_index(inplace=True)
    for suffix in _phase_suffixes(df):
        case_col = f"Case_{suffix}"
        run_col = f"Run_{suffix}"
        parts = df[case_col].astype(str).str.split("-", n=1, expand=True)
        df[case_col] = parts[0].replace("nan", np.nan)
        df[run_col] = pd.to_numeric(parts[1] if parts.shape[1] > 1 else np.nan, errors="coerce")
        df[f"Max_{suffix}"] = df[f"Max_{suffix}"].round(1)
    return df


def _merge_list(source_dfs: list[pd.DataFrame], time_step: float = TIME_STEP) -> pd.DataFrame:
    treated = []
    for df in source_dfs:
        sort_df = "MM_name" in df.columns and "Case" in df.columns
        df = _add_phase_source_cols(df)
        if sort_df:
            phase_dfs = []
            for suffix in _phase_suffixes(df):
                max_col = f"Max_{suffix}"
                mm_col = f"MM_name_{suffix}"
                case_col = f"Case_{suffix}"
                phase_df = df[[max_col, mm_col, case_col]].sort_values(by=max_col, ascending=False).reset_index(drop=True)
                phase_df.index = np.round(np.arange(len(phase_df)) * time_step, 6)
                phase_df.index.name = "Time (s)"
                phase_dfs.append(phase_df)
            df = pd.concat(phase_dfs, axis=1, join="outer", sort=False)
        treated.append(df)

    merged = pd.concat(treated, axis=1, join="outer", sort=False)
    grouped = pd.DataFrame(index=merged.index)
    for suffix in _phase_suffixes(merged):
        max_col = f"Max_{suffix}"
        mm_col = f"MM_name_{suffix}"
        case_col = f"Case_{suffix}"
        max_cols = _duplicate_cols(merged, max_col)
        case_cols = _duplicate_cols(merged, case_col)
        mm_cols = _duplicate_cols(merged, mm_col)
        max_values = max_cols.max(axis=1, skipna=True)
        max_idx = max_cols.fillna(-np.inf).to_numpy().argmax(axis=1)
        row_indices = np.arange(len(max_cols))
        grouped[max_col] = max_values
        grouped[mm_col] = mm_cols.to_numpy()[row_indices, max_idx]
        grouped[case_col] = case_cols.to_numpy()[row_indices, max_idx]
    grouped.index.name = "Time (s)"
    return grouped


def _phase_suffixes(df: pd.DataFrame) -> list[str]:
    return list(dict.fromkeys(col.replace("Max_", "") for col in df.columns if str(col).startswith("Max_")))


def _add_phase_source_cols(df: pd.DataFrame) -> pd.DataFrame:
    if "MM_name" not in df.columns or "Case" not in df.columns:
        return df
    df = df.copy()
    for suffix in _phase_suffixes(df):
        df[f"MM_name_{suffix}"] = df["MM_name"]
        df[f"Case_{suffix}"] = df["Case"]
    return df.drop(columns=["MM_name", "Case"])


def _duplicate_cols(df: pd.DataFrame, col: str) -> pd.DataFrame:
    return df.loc[:, df.columns == col]


def _map_fault_types_phase(df: pd.DataFrame, df_stat: pd.DataFrame) -> pd.DataFrame:
    if df_stat.empty:
        for suffix in _phase_suffixes(df):
            df[f"Fault_type_{suffix}"] = ""
        return df
    for suffix in _phase_suffixes(df):
        case_col = f"Case_{suffix}"
        run_col = f"Run_{suffix}"
        fault_col = f"Fault_type_{suffix}"
        df_stat_phase = df_stat[["Case", "Run#", "Fault_type"]].copy()
        df_stat_phase.columns = [case_col, run_col, fault_col]
        df = df.merge(df_stat_phase, left_on=[case_col, run_col], right_on=[case_col, run_col], how="left")
    return df


def _organize_phase_columns(df: pd.DataFrame) -> pd.DataFrame:
    for col in ENVELOPE_HEADERS:
        if col not in df.columns:
            df[col] = np.nan
    max_cols = ["Max_A", "Max_B", "Max_C"]
    df["Max_all"] = df[max_cols].max(axis=1, skipna=True)
    max_idx = df[max_cols].fillna(-np.inf).to_numpy().argmax(axis=1)
    row_indices = np.arange(len(df))
    for target, sources in (
        ("Case_all", ["Case_A", "Case_B", "Case_C"]),
        ("Run_all", ["Run_A", "Run_B", "Run_C"]),
        ("Fault_type_all", ["Fault_type_A", "Fault_type_B", "Fault_type_C"]),
        ("MM_name_all", ["MM_name_A", "MM_name_B", "MM_name_C"]),
    ):
        df[target] = df[sources].to_numpy(dtype=object)[row_indices, max_idx]
    return df[ENVELOPE_HEADERS]


def _read_stat_files(project_root: Path) -> pd.DataFrame:
    files = sorted((project_root / "Case_folder").rglob("Statistic*.out"))
    if not files:
        return pd.DataFrame(columns=["Case", "Run#", "Fault_type"])

    all_dfs = []
    for path in files:
        case_name = path.parent.name.split(".")[0]
        raw = pd.read_csv(path, skiprows=[0], header=None, sep=" +Output+ ", engine="python")
        raw.reset_index(drop=True, inplace=True)
        raw[0] = raw[0].str.replace("Run #", "Run#", regex=False)
        summary_rows = raw[raw[0].str.startswith("Statistical Summary", na=False)].index
        last_row = int(summary_rows[0]) - 1 if len(summary_rows) else len(raw) - 1
        split = raw.iloc[0:last_row + 1, 0].str.split(" +", expand=True)
        if split.empty:
            continue
        df_stat = pd.DataFrame(split.values[1:], columns=split.iloc[0])
        df_stat = df_stat.apply(pd.to_numeric, errors="coerce")
        df_stat.dropna(subset=["Run#"], inplace=True)
        df_stat.insert(0, "Case", case_name)
        all_dfs.append(df_stat)

    if not all_dfs:
        return pd.DataFrame(columns=["Case", "Run#", "Fault_type"])
    return _map_faults(pd.concat(all_dfs, ignore_index=True))


def _map_faults(df: pd.DataFrame) -> pd.DataFrame:
    replacement_dict = {0.0: "None", 11.0: "ABC", 1.0: "AG", 4.0: "ABG", 7.0: "ABCG", 8.0: "AB"}
    df = df.copy()
    if "Fault_type" in df.columns:
        df["Fault_type"] = df["Fault_type"].replace(replacement_dict, regex=True)
    return df


def _find_non_convergent_cases(
    case_root: Path,
    df_stat: pd.DataFrame,
    cb_iip_limit: float = NONCONV_CB_IIP_LIMIT,
    cb_iir_limit: float = NONCONV_CB_IIR_LIMIT,
) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    for path in sorted(case_root.rglob("CB_*.out")):
        records.extend(_read_non_convergent_file(path, cb_iip_limit, cb_iir_limit))
    if not records:
        return pd.DataFrame(columns=NONCONV_COLUMNS)
    df_nonconv = pd.DataFrame(records).drop_duplicates()
    df_nonconv = _map_exclusion_fault_types(df_nonconv, df_stat, NONCONV_COLUMNS)
    return df_nonconv[NONCONV_COLUMNS].sort_values(by=["Case", "Run", "Source", "Signal"]).reset_index(drop=True)


def find_non_convergent_cases_for_project(
    project_root: str | Path,
    cb_iip_limit: float | None = None,
    cb_iir_limit: float | None = None,
) -> list[dict[str, Any]]:
    root = Path(project_root)
    case_root = root / "Case_folder"
    if not case_root.is_dir():
        return []
    df_nonconv = _find_non_convergent_cases(
        case_root,
        _read_stat_files(root),
        _positive_float(cb_iip_limit, NONCONV_CB_IIP_LIMIT),
        _positive_float(cb_iir_limit, NONCONV_CB_IIR_LIMIT),
    )
    return df_nonconv.astype(object).where(pd.notna(df_nonconv), "").to_dict("records")


def _read_non_convergent_file(
    path: Path,
    cb_iip_limit: float = NONCONV_CB_IIP_LIMIT,
    cb_iir_limit: float = NONCONV_CB_IIR_LIMIT,
) -> list[dict[str, Any]]:
    case_name = path.parent.name.split(".")[0]
    source = path.stem.replace("_01_0001", "")
    records: list[dict[str, Any]] = []
    df_summary = _read_cb_summary(path)
    if df_summary.empty or "Run#" not in df_summary.columns:
        return records

    current_cols = [col for col in df_summary.columns if "II" in str(col)]
    for _, row in df_summary.iterrows():
        run = pd.to_numeric(row["Run#"], errors="coerce")
        if pd.isna(run):
            continue
        for signal in current_cols:
            value_raw = row[signal]
            value = pd.to_numeric(value_raw, errors="coerce")
            reason = None
            if pd.isna(value):
                reason = "Non-numeric or NaN current"
            elif not np.isfinite(value):
                reason = "Non-finite current"
            elif signal == "CB_IIp" and abs(value) > cb_iip_limit:
                reason = f"CB_IIp above {cb_iip_limit:g}"
            elif signal == "CB_IIr" and abs(value) > cb_iir_limit:
                reason = f"CB_IIr above {cb_iir_limit:g}"
            if reason:
                records.append({"Case": case_name, "Run": int(run), "Source": source, "Signal": signal, "Reason": reason, "Value": value_raw, "File": path.name})
    return records


def _read_cb_summary(path: Path) -> pd.DataFrame:
    for skiprows in ([0], None):
        try:
            df = pd.read_csv(path, skiprows=skiprows, header=0, sep=r"\s+", engine="python", dtype=str)
        except Exception:
            continue
        if "Run#" in df.columns:
            return df
    return pd.DataFrame()


def _nonconv_keys(df_nonconv: pd.DataFrame) -> set[tuple[str, int]]:
    if df_nonconv.empty:
        return set()
    return set(zip(df_nonconv["Case"], df_nonconv["Run"].astype(int)))


def _map_exclusion_fault_types(df: pd.DataFrame, df_stat: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=columns)
    df = df.copy()
    df["Run"] = pd.to_numeric(df["Run"], errors="coerce")
    if not df_stat.empty:
        df = df.merge(df_stat[["Case", "Run#", "Fault_type"]], left_on=["Case", "Run"], right_on=["Case", "Run#"], how="left")
        df.drop(columns=["Run#"], inplace=True)
    elif "Fault_type" not in df.columns:
        df["Fault_type"] = ""
    df["Run"] = df["Run"].astype("Int64")
    for col in columns:
        if col not in df.columns:
            df[col] = ""
    return df[columns]


def _filter_dataframe_by_scope(df: pd.DataFrame, scope: ScopeEntry) -> pd.DataFrame:
    if df.empty or scope.mode == "full":
        return df
    tokens = [token.casefold() for token in scope.tokens]
    row_text = df.astype(str).agg(" ".join, axis=1).str.casefold()
    matched = row_text.apply(lambda value: any(token in value for token in tokens))
    return df[matched] if scope.mode == "include" else df[~matched]


def _write_workbook(
    path: Path,
    lg_df: pd.DataFrame,
    ll_df: pd.DataFrame,
    nonconv_df: pd.DataFrame,
    high_voltage_df: pd.DataFrame,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        lg_df.to_excel(writer, index=False, sheet_name="LGp")
        ll_df.to_excel(writer, index=False, sheet_name="LLp")
        nonconv_df.to_excel(writer, index=False, sheet_name="NonConv cases")
        high_voltage_df.to_excel(writer, index=False, sheet_name="High voltage exclusions")
    _format_workbook(path)


def _format_workbook(path: Path) -> None:
    import openpyxl

    wb = openpyxl.load_workbook(path)
    try:
        for ws in wb.worksheets:
            if ws.max_column:
                ws.freeze_panes = "A2"
                ws.auto_filter.ref = f"A1:{get_column_letter(ws.max_column)}1"
            for col_idx in range(1, ws.max_column + 1):
                header = ws.cell(1, col_idx).value
                cell = ws.cell(1, col_idx)
                cell.font = Font(bold=True)
                cell.fill = PatternFill("solid", fgColor="D9EAF7")
                cell.alignment = Alignment(horizontal="center")
                ws.column_dimensions[get_column_letter(col_idx)].width = max(12, min(28, len(str(header or "")) + 2))
        wb.save(path)
    finally:
        wb.close()
