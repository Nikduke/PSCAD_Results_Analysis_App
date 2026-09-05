from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
import time
from typing import Any

from results_analysis_app import analysis_engine
from results_analysis_app import resonance_checks
from results_analysis_app import sustained_sdpf
from results_analysis_app import voltage_envelope
from results_analysis_app.envelope_chart import create_combined_envelope_plot, create_resonance_check_charts
from results_analysis_app.common import LogFn, log_message as _log
from results_analysis_app.exclusions import ExclusionRule
from results_analysis_app.excel import EXCEL_AUTOMATION_ERRORS, excel_app
from results_analysis_app.models import (
    DEFAULT_ENVELOPE_CHART_HEIGHT,
    DEFAULT_ENVELOPE_CHART_WIDTH,
    ScopeEntry,
)
from results_analysis_app.project_config import ProjectTiming
from results_analysis_app.reporting import build_reports_from_existing_plots


def _project_value(values: dict[str, object] | None, root: Path):
    return (values or {}).get(str(root))


def ensure_output_tree(
    project_root: str | Path,
    scopes: Iterable[ScopeEntry],
) -> None:
    """Create output roots needed for selected scopes and batch workbooks."""
    root = Path(project_root).resolve()
    for scope in scopes:
        for folder in (
            root / "Voltage_envelope" / scope.folder,
            root / "Reports" / scope.folder,
        ):
            folder.mkdir(parents=True, exist_ok=True)

    batch_dir = root / "Plots" / "Plot_batch"
    batch_dir.mkdir(parents=True, exist_ok=True)


def refresh_dashboards(project_root: str | Path, log: LogFn | None = None) -> None:
    """Refresh all Excel dashboard workbooks in ProjectRoot/Dashboards."""
    dashboard_root = Path(project_root).resolve() / "Dashboards"
    if not dashboard_root.is_dir():
        raise FileNotFoundError(f"Dashboard folder not found: {dashboard_root}")

    workbooks = [
        path
        for pattern in ("*.xlsx", "*.xlsm", "*.xlsb")
        for path in sorted(dashboard_root.glob(pattern))
        if not path.name.startswith("~$")
    ]
    if not workbooks:
        raise FileNotFoundError(f"No dashboard workbooks found in {dashboard_root}")

    with excel_app() as excel:
        _log(log, "Starting Microsoft Excel in the background.")
        for workbook_path in workbooks:
            _log(log, f"Opening dashboard workbook: {workbook_path.name}")
            workbook = excel.Workbooks.Open(str(workbook_path), UpdateLinks=0, ReadOnly=False)
            try:
                _log(log, f"Refreshing data connections: {workbook_path.name}")
                workbook.RefreshAll()
                try:
                    _log(log, f"Waiting for Excel queries to finish: {workbook_path.name}")
                    excel.CalculateUntilAsyncQueriesDone()
                except EXCEL_AUTOMATION_ERRORS as exc:
                    _log(log, f"Excel query wait skipped: {workbook_path.name} | {exc}")
                time.sleep(0.2)
                _log(log, f"Saving refreshed dashboard: {workbook_path.name}")
                workbook.Save()
            finally:
                _log(log, f"Closing dashboard workbook: {workbook_path.name}")
                workbook.Close(SaveChanges=True)


def build_voltage_envelopes(
    project_roots: Iterable[str | Path],
    scopes: Iterable[ScopeEntry],
    voltages: Iterable[str],
    envelope_workers: int | None = None,
    envelope_time_step: float | None = None,
    envelope_time_end: float | None = None,
    envelope_fallback_frequency: float | None = None,
    envelope_chart_x_max_by_project: dict[str, float | None] | None = None,
    envelope_chart_x_major_by_project: dict[str, float | None] | None = None,
    envelope_chart_y_limits_by_voltage: dict[str, dict[str, float | None]] | None = None,
    envelope_chart_show_sa_label: bool = False,
    envelope_chart_top_left_cell: str | None = None,
    envelope_chart_width: float | None = None,
    envelope_chart_height: float | None = None,
    high_voltage_limit_factor: float | None = None,
    nonconv_cb_iip_limit: float | None = None,
    nonconv_cb_iir_limit: float | None = None,
    event_times: dict[str, float] | None = None,
    project_timing_by_project: dict[str, dict[str, float | None]] | None = None,
    voltage_um_overrides_by_project: dict[str, dict[str, float]] | None = None,
    exclusions_by_project: dict[str, list[ExclusionRule]] | None = None,
    high_voltage_proposals_by_project: dict[str, list[dict[str, object]]] | None = None,
    high_voltage_include_overrides_by_project: dict[
        str, list[tuple[str, str, int, str]]
    ] | None = None,
    resonance_settings: dict[str, object] | None = None,
    build_charts: bool = True,
    log: LogFn | None = None,
    check_cancel: Callable[[], None] | None = None,
    sustained_sdpf_settings: dict[str, object] | None = None,
    sustained_sdpf_limit_overrides_by_project: dict[str, dict[str, dict[str, float]]] | None = None,
    voltage_configs_by_project: dict[str, dict[str, Any]] | None = None,
    sustained_sdpf_limits_by_project: dict[str, dict[str, Any]] | None = None,
    nonconv_cases_by_project: dict[str, list[Any]] | None = None,
) -> list[Path]:
    """Build scope-aware voltage envelope workbooks for selected projects."""
    selected_scopes = list(scopes)
    selected_voltages = list(voltages)
    outputs: list[Path] = []
    for project_root in project_roots:
        root = Path(project_root).resolve()
        ensure_output_tree(root, selected_scopes)
        _log(log, f"Building voltage envelopes: {root.name}")
        project_key = str(root)
        raw_timing = _project_value(project_timing_by_project, root)
        project_timing = (
            ProjectTiming(**raw_timing)
            if isinstance(raw_timing, dict)
            else None
        )
        outputs.extend(
            voltage_envelope.build_voltage_envelopes(
                root,
                selected_scopes,
                selected_voltages,
                log=log,
                check_cancel=check_cancel,
                envelope_workers=envelope_workers,
                exclusions=(exclusions_by_project or {}).get(project_key, []),
                high_voltage_proposals=(high_voltage_proposals_by_project or {}).get(
                    project_key,
                    [],
                ),
                high_voltage_include_overrides=(
                    high_voltage_include_overrides_by_project or {}
                ).get(project_key, []),
                envelope_time_step=envelope_time_step,
                envelope_time_end=envelope_time_end,
                envelope_fallback_frequency=envelope_fallback_frequency,
                envelope_chart_x_max=_project_value(envelope_chart_x_max_by_project, root),
                envelope_chart_x_major=_project_value(envelope_chart_x_major_by_project, root),
                envelope_chart_y_limits_by_voltage=envelope_chart_y_limits_by_voltage,
                envelope_chart_show_sa_label=envelope_chart_show_sa_label,
                envelope_chart_top_left_cell=envelope_chart_top_left_cell,
                envelope_chart_width=envelope_chart_width,
                envelope_chart_height=envelope_chart_height,
                high_voltage_limit_factor=high_voltage_limit_factor,
                nonconv_cb_iip_limit=nonconv_cb_iip_limit,
                nonconv_cb_iir_limit=nonconv_cb_iir_limit,
                event_times=event_times,
                project_timing=project_timing,
                voltage_um_overrides=(voltage_um_overrides_by_project or {}).get(project_key, {}),
                resonance_settings=resonance_settings,
                sustained_sdpf_settings=sustained_sdpf_settings,
                sustained_sdpf_limit_overrides=(
                    sustained_sdpf_limit_overrides_by_project or {}
                ).get(project_key, {}),
                voltage_configs=(voltage_configs_by_project or {}).get(project_key),
                sustained_sdpf_limits_by_voltage=(sustained_sdpf_limits_by_project or {}).get(project_key),
                nonconv_cases=(nonconv_cases_by_project or {}).get(project_key),
                build_charts=build_charts,
            )
        )
    return outputs


def rebuild_envelope_charts(
    project_roots: Iterable[str | Path],
    scopes: Iterable[ScopeEntry],
    voltages: Iterable[str],
    event_times: dict[str, float] | None = None,
    envelope_chart_x_max_by_project: dict[str, float | None] | None = None,
    envelope_chart_x_major_by_project: dict[str, float | None] | None = None,
    envelope_chart_y_limits_by_voltage: dict[str, dict[str, float | None]] | None = None,
    envelope_chart_show_sa_label: bool = False,
    envelope_chart_top_left_cell: str | None = None,
    envelope_chart_width: float | None = None,
    envelope_chart_height: float | None = None,
    log: LogFn | None = None,
    check_cancel: Callable[[], None] | None = None,
) -> list[Path]:
    """Recreate combined envelope plot workbooks from existing envelope workbooks."""
    selected_scopes = list(scopes)
    selected_voltages = [str(voltage) for voltage in voltages]
    chart_size = {
        "width": float(envelope_chart_width or DEFAULT_ENVELOPE_CHART_WIDTH),
        "height": float(envelope_chart_height or DEFAULT_ENVELOPE_CHART_HEIGHT),
    }
    outputs: list[Path] = []
    with excel_app() as excel:
        for project_root in project_roots:
            root = Path(project_root).resolve()
            chart_x_max = _project_value(envelope_chart_x_max_by_project, root)
            chart_x_major = _project_value(envelope_chart_x_major_by_project, root)
            ensure_output_tree(root, selected_scopes)
            _log(log, f"Rebuilding envelope charts: {root.name}")
            for scope in selected_scopes:
                for voltage in selected_voltages:
                    if check_cancel is not None:
                        check_cancel()
                    input_path = root / "Voltage_envelope" / scope.folder / f"MM_{voltage}.xlsx"
                    if not input_path.exists():
                        _log(log, f"Envelope workbook missing, skipped: {input_path.name}")
                        continue
                    output_path = input_path.with_name(f"{input_path.stem}_with_combined_plot.xlsx")
                    _log(log, f"Rebuilding envelope chart: {scope.folder} / {input_path.name}")
                    outputs.append(
                        create_combined_envelope_plot(
                            input_path,
                            output_path,
                            excel,
                            axis_limits_override={
                                "x_max": chart_x_max,
                                "x_major": chart_x_major,
                            },
                            axis_limits_by_voltage=envelope_chart_y_limits_by_voltage,
                            event_times=event_times,
                            show_sa_label=envelope_chart_show_sa_label,
                            chart_top_left_cell=envelope_chart_top_left_cell,
                            chart_size=chart_size,
                        )
                    )
    return outputs


def rebuild_analysis_charts(
    project_roots: Iterable[str | Path],
    scopes: Iterable[ScopeEntry],
    envelope_chart_x_max_by_project: dict[str, float | None] | None = None,
    envelope_chart_x_major_by_project: dict[str, float | None] | None = None,
    log: LogFn | None = None,
    check_cancel: Callable[[], None] | None = None,
) -> list[Path]:
    """Recreate chart sheets inside existing resonance check workbooks."""
    selected_scopes = list(scopes)
    outputs: list[Path] = []
    try:
        with excel_app() as excel:
            for project_root in project_roots:
                root = Path(project_root).resolve()
                chart_x_max = _project_value(envelope_chart_x_max_by_project, root)
                chart_x_major = _project_value(envelope_chart_x_major_by_project, root)
                _log(log, f"Rebuilding analysis charts: {root.name}")
                for scope in selected_scopes:
                    if check_cancel is not None:
                        check_cancel()
                    workbook_path = root / "Voltage_envelope" / scope.folder / resonance_checks.WORKBOOK_NAME
                    if not workbook_path.exists():
                        _log(log, f"Analysis workbook missing, skipped: {scope.folder} / {resonance_checks.WORKBOOK_NAME}")
                        continue
                    if create_resonance_check_charts(
                        workbook_path,
                        excel,
                        x_max=chart_x_max,
                        x_major=chart_x_major,
                    ):
                        outputs.append(workbook_path)
                        _log(log, f"Rebuilt analysis charts: {scope.folder} / {resonance_checks.WORKBOOK_NAME}")
                    else:
                        _log(log, f"No analysis chart sheets found: {scope.folder} / {resonance_checks.WORKBOOK_NAME}")
    except EXCEL_AUTOMATION_ERRORS as exc:
        _log(log, f"Excel chart styling unavailable; analysis chart rebuild skipped: {exc}")
    return outputs


def create_plot_batches(
    project_roots: Iterable[str | Path],
    scopes: Iterable[ScopeEntry],
    voltages: Iterable[str],
    events: Iterable[str],
    event_times: dict[str, float] | None = None,
    resonance_settings: dict[str, object] | None = None,
    log: LogFn | None = None,
    check_cancel: Callable[[], None] | None = None,
    sustained_sdpf_settings: dict[str, object] | None = None,
    sustained_sdpf_heatmap_settings_by_project: dict[str, object] | None = None,
    sustained_sdpf_ranking_settings_by_project: dict[str, object] | None = None,
    sustained_payloads_by_scope: Mapping[str, Mapping[str, Any]] | None = None,
    excel_waveform_exports_enabled: bool = True,
    sustained_cache_validations_by_scope: Mapping[
        str, sustained_sdpf.SustainedSDPFCacheValidation
    ] | None = None,
) -> list[Path]:
    """Create scope/event plot batch workbooks from existing envelope workbooks."""
    selected_scopes = list(scopes)
    selected_voltages = list(voltages)
    selected_events = list(events)
    outputs: list[Path] = []
    for project_root in project_roots:
        root = Path(project_root).resolve()
        ensure_output_tree(root, selected_scopes)
        _log(log, f"Creating plot batches: {root.name}")
        outputs.extend(
            analysis_engine.create_plot_batches(
                root,
                selected_scopes,
                selected_voltages,
                selected_events,
                event_times,
                resonance_settings,
                log,
                check_cancel,
                sustained_sdpf_settings=sustained_sdpf_settings,
                sustained_sdpf_heatmap_settings_by_project=sustained_sdpf_heatmap_settings_by_project,
                sustained_sdpf_ranking_settings=(
                    sustained_sdpf_ranking_settings_by_project or {}
                ).get(str(root)),
                sustained_payloads_by_scope=sustained_payloads_by_scope,
                excel_waveform_exports_enabled=excel_waveform_exports_enabled,
                sustained_cache_validations_by_scope=sustained_cache_validations_by_scope,
            )
        )
    return outputs


def render_plot_batches(
    project_roots: Iterable[str | Path],
    scopes: Iterable[ScopeEntry],
    events: Iterable[str],
    resonance_settings: dict[str, object] | None = None,
    log: LogFn | None = None,
    check_cancel: Callable[[], None] | None = None,
    sustained_sdpf_settings: dict[str, object] | None = None,
    sustained_sdpf_heatmap_settings_by_project: dict[str, object] | None = None,
    sustained_sdpf_ranking_settings_by_project: dict[str, object] | None = None,
    event_times: dict[str, float] | None = None,
    sustained_sdpf_limit_overrides_by_project: dict[str, dict[str, dict[str, float]]] | None = None,
    sustained_payloads_by_scope: Mapping[str, Mapping[str, Any]] | None = None,
    sustained_voltage_keys: Iterable[str] | None = None,
    excel_waveform_exports_enabled: bool = True,
    sustained_cache_validations_by_scope: Mapping[
        str, sustained_sdpf.SustainedSDPFCacheValidation
    ] | None = None,
) -> None:
    """Render existing scope/event plot batches into generated plot folders."""
    selected_scopes = list(scopes)
    selected_events = [
        *list(events),
        *resonance_checks.selected_plot_events(resonance_settings),
    ]
    if sustained_sdpf.SustainedSDPFSettings.from_mapping(sustained_sdpf_settings).enabled:
        selected_events.append("Sustained_SDPF")
    for project_root in project_roots:
        root = Path(project_root).resolve()
        ensure_output_tree(root, selected_scopes)
        _log(log, f"Rendering plot batches: {root.name}")
        analysis_engine.render_plot_batches(
            root,
            selected_scopes,
            selected_events,
            log,
            check_cancel,
            sustained_sdpf_settings=sustained_sdpf_settings,
            sustained_sdpf_heatmap_settings=(sustained_sdpf_heatmap_settings_by_project or {}).get(str(root)),
            sustained_sdpf_ranking_settings=(
                sustained_sdpf_ranking_settings_by_project or {}
            ).get(str(root)),
            event_times=event_times,
            sustained_sdpf_limit_overrides=(sustained_sdpf_limit_overrides_by_project or {}).get(str(root)),
            sustained_payloads_by_scope=sustained_payloads_by_scope,
            sustained_voltage_keys=sustained_voltage_keys,
            excel_waveform_exports_enabled=excel_waveform_exports_enabled,
            sustained_cache_validations_by_scope=sustained_cache_validations_by_scope,
        )


def rebuild_heatmaps(
    project_roots: Iterable[str | Path],
    scopes: Iterable[ScopeEntry],
    sustained_sdpf_settings: dict[str, object] | None = None,
    sustained_sdpf_heatmap_settings_by_project: dict[str, object] | None = None,
    event_times: dict[str, float] | None = None,
    log: LogFn | None = None,
    check_cancel: Callable[[], None] | None = None,
) -> None:
    """Regenerate Sustained SDPF heatmaps without rendering other plots."""
    selected_scopes = list(scopes)
    for project_root in project_roots:
        root = Path(project_root).resolve()
        _log(log, f"Rebuilding Sustained SDPF heatmaps: {root.name}")
        analysis_engine.render_sustained_heatmaps(
            root,
            selected_scopes,
            log=log,
            check_cancel=check_cancel,
            sustained_sdpf_settings=sustained_sdpf_settings,
            sustained_sdpf_heatmap_settings=(sustained_sdpf_heatmap_settings_by_project or {}).get(str(root)),
            event_times=event_times,
        )


def run_analysis_pipeline(
    project_roots: Iterable[str | Path],
    scopes: Iterable[ScopeEntry],
    voltages: Iterable[str],
    events: Iterable[str],
    event_times: dict[str, float] | None = None,
    dashboard_figure_ids_by_project: Mapping[str, Iterable[str]] | None = None,
    envelope_workers: int | None = None,
    envelope_time_step: float | None = None,
    envelope_time_end: float | None = None,
    envelope_fallback_frequency: float | None = None,
    envelope_chart_x_max_by_project: dict[str, float | None] | None = None,
    envelope_chart_x_major_by_project: dict[str, float | None] | None = None,
    envelope_chart_y_limits_by_voltage: dict[str, dict[str, float | None]] | None = None,
    envelope_chart_show_sa_label: bool = False,
    envelope_chart_top_left_cell: str | None = None,
    envelope_chart_width: float | None = None,
    envelope_chart_height: float | None = None,
    high_voltage_limit_factor: float | None = None,
    nonconv_cb_iip_limit: float | None = None,
    nonconv_cb_iir_limit: float | None = None,
    project_timing_by_project: dict[str, dict[str, float | None]] | None = None,
    voltage_um_overrides_by_project: dict[str, dict[str, float]] | None = None,
    exclusions_by_project: dict[str, list[ExclusionRule]] | None = None,
    high_voltage_proposals_by_project: dict[str, list[dict[str, object]]] | None = None,
    high_voltage_include_overrides_by_project: dict[
        str, list[tuple[str, str, int, str]]
    ] | None = None,
    resonance_settings: dict[str, object] | None = None,
    log: LogFn | None = None,
    check_cancel: Callable[[], None] | None = None,
    sustained_sdpf_settings: dict[str, object] | None = None,
    sustained_sdpf_limit_overrides_by_project: dict[str, dict[str, dict[str, float]]] | None = None,
    sustained_sdpf_heatmap_settings_by_project: dict[str, object] | None = None,
    sustained_sdpf_ranking_settings_by_project: dict[str, object] | None = None,
    voltage_configs_by_project: dict[str, dict[str, Any]] | None = None,
    sustained_sdpf_limits_by_project: dict[str, dict[str, Any]] | None = None,
    nonconv_cases_by_project: dict[str, list[Any]] | None = None,
    excel_waveform_exports_enabled: bool = True,
) -> list[Path]:
    """Run the connected analysis path end to end for selected projects/scopes."""
    selected_scopes = list(scopes)
    selected_voltages = [str(voltage) for voltage in voltages]
    selected_events = [str(event) for event in events]
    reports: list[Path] = []

    for project_root in project_roots:
        root = Path(project_root).resolve()
        _log(log, f"Analysis started: {root.name}")

        _log(log, "Building voltage envelope workbooks.")
        build_voltage_envelopes(
            [root],
            selected_scopes,
            selected_voltages,
            envelope_workers=envelope_workers,
            envelope_time_step=envelope_time_step,
            envelope_time_end=envelope_time_end,
            envelope_fallback_frequency=envelope_fallback_frequency,
            envelope_chart_x_max_by_project=envelope_chart_x_max_by_project,
            envelope_chart_x_major_by_project=envelope_chart_x_major_by_project,
            envelope_chart_y_limits_by_voltage=envelope_chart_y_limits_by_voltage,
            envelope_chart_show_sa_label=envelope_chart_show_sa_label,
            envelope_chart_top_left_cell=envelope_chart_top_left_cell,
            envelope_chart_width=envelope_chart_width,
            envelope_chart_height=envelope_chart_height,
            high_voltage_limit_factor=high_voltage_limit_factor,
            nonconv_cb_iip_limit=nonconv_cb_iip_limit,
            nonconv_cb_iir_limit=nonconv_cb_iir_limit,
            event_times=event_times,
            project_timing_by_project=project_timing_by_project,
            voltage_um_overrides_by_project=voltage_um_overrides_by_project,
            exclusions_by_project=exclusions_by_project,
            high_voltage_proposals_by_project=high_voltage_proposals_by_project,
            high_voltage_include_overrides_by_project=(
                high_voltage_include_overrides_by_project
            ),
            resonance_settings=resonance_settings,
            sustained_sdpf_settings=sustained_sdpf_settings,
            sustained_sdpf_limit_overrides_by_project=sustained_sdpf_limit_overrides_by_project,
            voltage_configs_by_project=voltage_configs_by_project,
            sustained_sdpf_limits_by_project=sustained_sdpf_limits_by_project,
            nonconv_cases_by_project=nonconv_cases_by_project,
            log=log,
            check_cancel=check_cancel,
        )

        sustained_payloads_by_scope: dict[str, Mapping[str, Any]] = {}
        sustained_cache_validations_by_scope: dict[
            str, sustained_sdpf.SustainedSDPFCacheValidation
        ] = {}
        parsed_sustained_settings = sustained_sdpf.SustainedSDPFSettings.from_mapping(
            sustained_sdpf_settings
        )
        if parsed_sustained_settings.enabled:
            sustained_payloads_by_scope = {
                scope.folder: sustained_sdpf.load_results(root, scope.folder)
                for scope in selected_scopes
            }
            sustained_cache_validations_by_scope = {
                scope.folder: sustained_sdpf.validate_result_cache(
                    sustained_payloads_by_scope.get(scope.folder),
                    root,
                    parsed_sustained_settings,
                )
                for scope in selected_scopes
            }

        _log(log, "Creating plot batch workbooks.")
        create_plot_batches(
            [root],
            selected_scopes,
            selected_voltages,
            selected_events,
            event_times=event_times,
            resonance_settings=resonance_settings,
            sustained_sdpf_settings=sustained_sdpf_settings,
            sustained_sdpf_heatmap_settings_by_project=sustained_sdpf_heatmap_settings_by_project,
            sustained_sdpf_ranking_settings_by_project=sustained_sdpf_ranking_settings_by_project,
            excel_waveform_exports_enabled=excel_waveform_exports_enabled,
            sustained_payloads_by_scope=sustained_payloads_by_scope,
            sustained_cache_validations_by_scope=sustained_cache_validations_by_scope,
            log=log,
            check_cancel=check_cancel,
        )

        _log(log, "Rendering plots from batch workbooks.")
        render_plot_batches(
            [root],
            selected_scopes,
            selected_events,
            resonance_settings=resonance_settings,
            sustained_sdpf_settings=sustained_sdpf_settings,
            sustained_sdpf_heatmap_settings_by_project=sustained_sdpf_heatmap_settings_by_project,
            sustained_sdpf_ranking_settings_by_project=sustained_sdpf_ranking_settings_by_project,
            event_times=event_times,
            sustained_sdpf_limit_overrides_by_project=sustained_sdpf_limit_overrides_by_project,
            sustained_payloads_by_scope=sustained_payloads_by_scope,
            sustained_cache_validations_by_scope=sustained_cache_validations_by_scope,
            sustained_voltage_keys=selected_voltages,
            excel_waveform_exports_enabled=excel_waveform_exports_enabled,
            log=log,
            check_cancel=check_cancel,
        )

        _log(log, "Building reports from generated plots and selected dashboard figures.")
        reports.extend(
            build_reports_from_existing_plots(
                [root],
                selected_scopes,
                selected_voltages,
                selected_events,
                dashboard_figure_ids_by_project=dashboard_figure_ids_by_project,
                resonance_settings=resonance_settings,
                sustained_sdpf_settings=sustained_sdpf_settings,
                sustained_sdpf_heatmap_settings_by_project=sustained_sdpf_heatmap_settings_by_project,
                sustained_sdpf_ranking_settings_by_project=sustained_sdpf_ranking_settings_by_project,
                render_heatmaps=False,
                sustained_payloads_by_project_scope={
                    str(root): sustained_payloads_by_scope,
                },
                sustained_cache_validations_by_project_scope={
                    str(root): sustained_cache_validations_by_scope,
                },
                event_times=event_times,
                log=log,
                check_cancel=check_cancel,
            )
        )
        _log(log, f"Analysis complete: {root.name}")

    return reports
