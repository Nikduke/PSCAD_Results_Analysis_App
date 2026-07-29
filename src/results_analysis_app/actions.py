from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path
import time

from results_analysis_app import analysis_engine
from results_analysis_app import resonance_checks
from results_analysis_app import voltage_envelope
from results_analysis_app.envelope_chart import create_combined_envelope_plot, create_resonance_check_charts
from results_analysis_app.exclusions import ExclusionRule
from results_analysis_app.excel import EXCEL_AUTOMATION_ERRORS, excel_app
from results_analysis_app.models import (
    DEFAULT_ENVELOPE_CHART_HEIGHT,
    DEFAULT_ENVELOPE_CHART_WIDTH,
    ScopeEntry,
)
from results_analysis_app.reporting import build_reports_from_existing_plots


LogFn = Callable[[str], None]


def _log(log: LogFn | None, message: str) -> None:
    if log is not None:
        log(message)


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
    events: Iterable[str],
    envelope_workers: int | None = None,
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
    voltage_um_overrides_by_project: dict[str, dict[str, float]] | None = None,
    exclusions_by_project: dict[str, list[ExclusionRule]] | None = None,
    resonance_settings: dict[str, object] | None = None,
    build_charts: bool = True,
    log: LogFn | None = None,
    check_cancel: Callable[[], None] | None = None,
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
        outputs.extend(
            voltage_envelope.build_voltage_envelopes(
                root,
                selected_scopes,
                selected_voltages,
                log=log,
                check_cancel=check_cancel,
                envelope_workers=envelope_workers,
                exclusions=(exclusions_by_project or {}).get(project_key, []),
                envelope_time_step=envelope_time_step,
                envelope_time_end=envelope_time_end,
                envelope_fallback_frequency=envelope_fallback_frequency,
                envelope_chart_x_max=envelope_chart_x_max,
                envelope_chart_x_major=envelope_chart_x_major,
                envelope_chart_y_limits_by_voltage=envelope_chart_y_limits_by_voltage,
                envelope_chart_show_sa_label=envelope_chart_show_sa_label,
                envelope_chart_top_left_cell=envelope_chart_top_left_cell,
                envelope_chart_width=envelope_chart_width,
                envelope_chart_height=envelope_chart_height,
                high_voltage_limit_factor=high_voltage_limit_factor,
                nonconv_cb_iip_limit=nonconv_cb_iip_limit,
                nonconv_cb_iir_limit=nonconv_cb_iir_limit,
                event_times=event_times,
                voltage_um_overrides=(voltage_um_overrides_by_project or {}).get(project_key, {}),
                resonance_settings=resonance_settings,
                build_charts=build_charts,
            )
        )
    return outputs


def rebuild_envelope_charts(
    project_roots: Iterable[str | Path],
    scopes: Iterable[ScopeEntry],
    voltages: Iterable[str],
    event_times: dict[str, float] | None = None,
    envelope_chart_x_max: float | None = None,
    envelope_chart_x_major: float | None = None,
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
                                "x_max": envelope_chart_x_max,
                                "x_major": envelope_chart_x_major,
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
    envelope_chart_x_max: float | None = None,
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
                        x_max=envelope_chart_x_max,
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
) -> None:
    """Render existing scope/event plot batches into generated plot folders."""
    selected_scopes = list(scopes)
    selected_events = [*list(events), *resonance_checks.selected_plot_events(resonance_settings)]
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
        )


def run_analysis_pipeline(
    project_roots: Iterable[str | Path],
    scopes: Iterable[ScopeEntry],
    voltages: Iterable[str],
    events: Iterable[str],
    event_times: dict[str, float] | None = None,
    dashboard_figure_ids: Iterable[str] = (),
    envelope_workers: int | None = None,
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
    voltage_um_overrides_by_project: dict[str, dict[str, float]] | None = None,
    exclusions_by_project: dict[str, list[ExclusionRule]] | None = None,
    resonance_settings: dict[str, object] | None = None,
    log: LogFn | None = None,
    check_cancel: Callable[[], None] | None = None,
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
            selected_events,
            envelope_workers=envelope_workers,
            envelope_time_step=envelope_time_step,
            envelope_time_end=envelope_time_end,
            envelope_fallback_frequency=envelope_fallback_frequency,
            envelope_chart_x_max=envelope_chart_x_max,
            envelope_chart_x_major=envelope_chart_x_major,
            envelope_chart_y_limits_by_voltage=envelope_chart_y_limits_by_voltage,
            envelope_chart_show_sa_label=envelope_chart_show_sa_label,
            envelope_chart_top_left_cell=envelope_chart_top_left_cell,
            envelope_chart_width=envelope_chart_width,
            envelope_chart_height=envelope_chart_height,
            high_voltage_limit_factor=high_voltage_limit_factor,
            nonconv_cb_iip_limit=nonconv_cb_iip_limit,
            nonconv_cb_iir_limit=nonconv_cb_iir_limit,
            event_times=event_times,
            voltage_um_overrides_by_project=voltage_um_overrides_by_project,
            exclusions_by_project=exclusions_by_project,
            resonance_settings=resonance_settings,
            log=log,
            check_cancel=check_cancel,
        )

        _log(log, "Creating plot batch workbooks.")
        create_plot_batches(
            [root],
            selected_scopes,
            selected_voltages,
            selected_events,
            event_times=event_times,
            resonance_settings=resonance_settings,
            log=log,
            check_cancel=check_cancel,
        )

        _log(log, "Rendering plots from batch workbooks.")
        render_plot_batches(
            [root],
            selected_scopes,
            selected_events,
            resonance_settings=resonance_settings,
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
                dashboard_figure_ids,
                resonance_settings=resonance_settings,
                event_times=event_times,
                log=log,
            )
        )
        _log(log, f"Analysis complete: {root.name}")

    return reports
