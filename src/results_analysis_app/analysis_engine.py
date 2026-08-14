from __future__ import annotations

from collections.abc import Callable, Iterable
import math
from pathlib import Path
import shutil
from typing import Any
import uuid

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from results_analysis_app import resonance_checks
from results_analysis_app.background import OperationCancelled
from results_analysis_app.envelope_rows import nearest_rows, row_value
from results_analysis_app.models import ScopeEntry
from results_analysis_app.project_config import DEFAULT_EVENT_TIMES


LogFn = Callable[[str], None]
CancelFn = Callable[[], None]

EVENT_DEFINITIONS = {
    "TOV": {"source_sheet": "LLp", "trace": "Both"},
    "SFO": {"source_sheet": "LLp", "trace": "Both"},
    "SA": {"source_sheet": "LGp", "trace": "LGp"},
}


def _log(log: LogFn | None, message: str) -> None:
    if log is not None:
        log(message)


def _cancel(check_cancel: CancelFn | None) -> None:
    if check_cancel is not None:
        check_cancel()


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    if math.isnan(number):
        return None
    return number


def _as_int_if_possible(value: Any) -> Any:
    number = _as_float(value)
    if number is None:
        return value
    if number.is_integer():
        return int(number)
    return number


def _batch_points_from_sheet(
    workbook,
    sheet_name: str,
    event_times: dict[str, float],
) -> dict[str, dict[str, Any] | None]:
    output = {event_name: None for event_name in event_times}
    if sheet_name not in workbook.sheetnames:
        return output
    headers, matches = nearest_rows(workbook[sheet_name], event_times)
    for event_name, row in matches.items():
        if row is None:
            continue
        output[event_name] = {
            "case": row_value(row, headers, "Case_all", "Case"),
            "run": row_value(row, headers, "Run_all", "Run"),
            "element": row_value(row, headers, "MM_name_all", "MM_name"),
            "fault": row_value(row, headers, "Fault_type_all", "Fault_type"),
        }
    return output


def _read_batch_points(
    workbook_path: Path,
    selected_events: Iterable[str],
    event_times: dict[str, float],
) -> dict[str, dict[str, Any] | None]:
    wb = openpyxl.load_workbook(workbook_path, data_only=True, read_only=True)
    try:
        by_sheet: dict[str, dict[str, float]] = {}
        for event_name in selected_events:
            by_sheet.setdefault(EVENT_DEFINITIONS[event_name]["source_sheet"], {})[event_name] = event_times[event_name]
        output: dict[str, dict[str, Any] | None] = {event_name: None for event_name in selected_events}
        for sheet_name, sheet_event_times in by_sheet.items():
            output.update(_batch_points_from_sheet(wb, sheet_name, sheet_event_times))
        return output
    finally:
        wb.close()


def _create_batch_workbook(path: Path, mm_rows: list[dict[str, Any]]) -> None:
    from pscad_plotter_app_v3.services.batch_excel import BatchExcelService

    path.parent.mkdir(parents=True, exist_ok=True)
    wb = openpyxl.Workbook()
    try:
        for index, (sheet_name, (_mode, headers)) in enumerate(BatchExcelService.SHEET_DEFINITIONS.items()):
            ws = wb.active if index == 0 else wb.create_sheet(sheet_name)
            ws.title = sheet_name
            ws.append(headers)
            ws.freeze_panes = "A2"
            if headers:
                ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}1"
            for col_idx, header in enumerate(headers, start=1):
                cell = ws.cell(1, col_idx)
                cell.font = Font(bold=True)
                cell.fill = PatternFill("solid", fgColor="D9EAF7")
                cell.alignment = Alignment(horizontal="center")
                ws.column_dimensions[get_column_letter(col_idx)].width = max(12, len(str(header)) + 2)
        header_to_col = {
            str(wb["MM"].cell(1, col).value): col
            for col in range(1, wb["MM"].max_column + 1)
        }
        for row_idx, row_data in enumerate(mm_rows, start=2):
            for key, value in row_data.items():
                col = header_to_col.get(key)
                if col is not None:
                    wb["MM"].cell(row_idx, col).value = value
        wb.save(path)
    finally:
        wb.close()


def create_plot_batches(
    project_root: Path,
    scopes: Iterable[ScopeEntry],
    voltages: Iterable[str],
    events: Iterable[str],
    event_times: dict[str, float] | None = None,
    resonance_settings: dict[str, Any] | None = None,
    log: LogFn | None = None,
    check_cancel: CancelFn | None = None,
) -> list[Path]:
    outputs: list[Path] = []
    selected_events = list(events)
    selected_voltages = list(voltages)
    selected_event_times = {
        event: float((event_times or {}).get(event, DEFAULT_EVENT_TIMES[event]))
        for event in selected_events
    }
    for scope in scopes:
        scenario_dir = project_root / "Voltage_envelope" / scope.folder
        rows_by_event: dict[str, list[dict[str, Any]]] = {
            event_name: [] for event_name in selected_events
        }
        for voltage in selected_voltages:
            _cancel(check_cancel)
            workbook = scenario_dir / f"MM_{voltage}.xlsx"
            if not workbook.is_file():
                continue
            points = _read_batch_points(workbook, selected_events, selected_event_times)
            for event_name, point in points.items():
                if point is None or not point.get("case") or not point.get("element"):
                    _log(log, f"No plot point found: {scope.folder} | {event_name} | {voltage} kV")
                    continue
                event = EVENT_DEFINITIONS[event_name]
                rows_by_event[event_name].append(
                    {
                        "case": point["case"],
                        "run": _as_int_if_possible(point["run"]),
                        "element": point["element"],
                        "trace": event["trace"],
                        "overview": True,
                        "tov_windows": True,
                        "tov_window_count": 4,
                        "limits": True,
                        "excel_export": True,
                    }
                )
        for event_name, mm_rows in rows_by_event.items():
            _cancel(check_cancel)
            output_path = project_root / "Plots" / "Plot_batch" / f"batch_paste_{scope.folder}_{event_name}.xlsx"
            _create_batch_workbook(output_path, mm_rows)
            outputs.append(output_path)
            _log(log, f"Wrote batch: {output_path.name} | MM rows={len(mm_rows)}")

        if resonance_settings is None:
            continue
        parsed_resonance = resonance_checks.ResonanceSettings.from_mapping(resonance_settings)
        selected_resonance_events = resonance_checks.selected_plot_events(parsed_resonance)
        selected_resonance_event_set = set(selected_resonance_events)
        for check in resonance_checks.CHECK_DEFINITIONS:
            for voltage_type in resonance_checks.VOLTAGE_TYPES:
                stale_event = resonance_checks.plot_event_name(check, voltage_type)
                if stale_event in selected_resonance_event_set:
                    continue
                stale_path = (
                    project_root
                    / "Plots"
                    / "Plot_batch"
                    / f"batch_paste_{scope.folder}_{stale_event}.xlsx"
                )
                if stale_path.is_file():
                    stale_path.unlink()
                    _log(log, f"Removed obsolete resonance batch: {stale_path.name}")
        resonance_rows = resonance_checks.create_plot_batch_rows(
            project_root,
            scope.folder,
            parsed_resonance.effective_enabled_checks,
        )
        for event_name in selected_resonance_events:
            _cancel(check_cancel)
            mm_rows = resonance_rows.get(event_name, [])
            output_path = project_root / "Plots" / "Plot_batch" / f"batch_paste_{scope.folder}_{event_name}.xlsx"
            _create_batch_workbook(output_path, mm_rows)
            outputs.append(output_path)
            _log(log, f"Wrote resonance batch: {output_path.name} | MM rows={len(mm_rows)}")
    return outputs


def _load_embedded_plotter_session(
    project_root: Path,
    log: LogFn | None = None,
    check_cancel: CancelFn | None = None,
):
    import pscad_plotter_app_v3
    from pscad_plotter_app_v3.services.exporter import ExcelExporter
    from pscad_plotter_app_v3.services.limits import LimitService
    from pscad_plotter_app_v3.services.project import (
        CatalogCache,
        ProjectDiscoveryService,
        ResultsCatalogService,
        RunAvailabilityService,
    )
    from pscad_plotter_app_v3.services.renderer import MatplotlibRenderer

    version = getattr(pscad_plotter_app_v3, "__version__", "embedded")
    _log(log, f"Using embedded plotter engine: pscad_plotter_app_v3 {version}")

    discovery_service = ProjectDiscoveryService()
    run_service = RunAvailabilityService()
    results_service = ResultsCatalogService()
    limit_service = LimitService()

    context = discovery_service.discover(project_root)
    context.state_dir.mkdir(parents=True, exist_ok=True)
    cache = CatalogCache(context.state_dir)
    try:
        _log(log, "plotter: Indexing runs...")
        run_index = run_service.build_index(context)
        _log(log, "plotter: Loading MM results...")
        catalog = results_service.build_base_catalog(context, run_index, cache)
        limits = limit_service.load_effective_limits(context)
        renderer = MatplotlibRenderer(run_index, check_cancel)
        exporter = ExcelExporter(renderer)
        return catalog, limits, renderer, exporter
    finally:
        cache.close()


def _render_plot_batches_direct(
    project_root: Path,
    scopes: Iterable[ScopeEntry],
    events: Iterable[str],
    log: LogFn | None = None,
    check_cancel: CancelFn | None = None,
) -> None:
    _cancel(check_cancel)
    selected_scopes = list(scopes)
    selected_events = list(events)
    catalog, limits, renderer, exporter = _load_embedded_plotter_session(
        project_root,
        log,
        check_cancel,
    )

    from pscad_plotter_app_v3.models import PlotMode
    from pscad_plotter_app_v3.services.batch_excel import BatchExcelService
    from pscad_plotter_app_v3.services.batching import build_mm_jobs
    from pscad_plotter_app_v3.services.limits import LimitService

    batch_service = BatchExcelService()
    limit_service = LimitService()
    batch_dir = project_root / "Plots" / "Plot_batch"

    for scope in selected_scopes:
        for event_name in selected_events:
            _cancel(check_cancel)
            batch_file = batch_dir / f"batch_paste_{scope.folder}_{event_name}.xlsx"
            if not batch_file.is_file():
                continue

            output_dir = _desired_output_dir(project_root, scope.folder, event_name)
            _log(log, f"Rendering plots with embedded plotter: {batch_file.name}")
            import_result = batch_service.load_requests(batch_file, catalog)
            for error in import_result.errors:
                _log(log, f"Batch import error: {batch_file.name} | {error.sheet_name} row {error.row_number}: {error.message}")
            if import_result.errors:
                raise RuntimeError(f"Batch import failed for {batch_file.name}.")
            if not import_result.requests:
                _log(log, f"No plot rows to render: {batch_file.name}")
                _remove_generated_directory(
                    output_dir,
                    project_root / "Plots" / "Generated" / scope.folder,
                )
                continue

            stage_dir = output_dir.parent / f".{output_dir.name}.render-{uuid.uuid4().hex}"
            jobs = []
            for request in import_result.requests:
                _cancel(check_cancel)
                request.output_dir = str(stage_dir)
                if request.mode is not PlotMode.MM:
                    raise RuntimeError(
                        f"Unsupported batch mode in analysis app: {request.mode.value}. "
                        "Only MM voltage-envelope batches are supported."
                    )
                limit = limit_service.get_limit_for_voltage(limits, request.voltage_kv)
                if request.mode is PlotMode.MM and request.show_limits and limit is None:
                    request.show_limits = False
                    _log(
                        log,
                        f"No MM limits found; plotting without limits: "
                        f"{request.case_name} | {request.elements[0] if request.elements else ''}",
                    )
                jobs.extend(build_mm_jobs(request, limit))

            if not jobs:
                _log(log, f"No plot jobs to render: {batch_file.name}")
                _remove_generated_directory(
                    output_dir,
                    project_root / "Plots" / "Generated" / scope.folder,
                )
                continue

            _log(log, f"Rendering {len(jobs)} plot(s): {scope.folder} | {event_name}")
            current_job = None
            try:
                for job in jobs:
                    current_job = job
                    _cancel(check_cancel)
                    _log(log, f"plotter: Rendering {job.case_name} | {job.group_label} | run {job.run_number}")
                    output = renderer.render(job)
                    _log(log, f"plotter: Saved {output}")
                    if job.excel_export:
                        excel_output = exporter.export(job)
                        _log(log, f"plotter: Saved {excel_output}")
                _cancel(check_cancel)
                _replace_generated_directory(stage_dir, output_dir)
            except OperationCancelled:
                shutil.rmtree(stage_dir, ignore_errors=True)
                raise
            except Exception as exc:
                shutil.rmtree(stage_dir, ignore_errors=True)
                job_context = event_name
                if current_job is not None:
                    job_context = (
                        f"{current_job.case_name} | {current_job.group_label} | "
                        f"run {current_job.run_number}"
                    )
                raise RuntimeError(
                    f"Plot rendering failed for {batch_file.name}: {job_context} | {exc}"
                ) from exc


def _replace_generated_directory(stage_dir: Path, output_dir: Path) -> None:
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    backup_dir = output_dir.parent / f".{output_dir.name}.previous-{uuid.uuid4().hex}"
    had_previous = output_dir.exists()
    if had_previous:
        output_dir.replace(backup_dir)
    try:
        stage_dir.replace(output_dir)
    except Exception:
        if had_previous and backup_dir.exists():
            backup_dir.replace(output_dir)
        raise
    shutil.rmtree(backup_dir, ignore_errors=True)


def _remove_generated_directory(output_dir: Path, scope_root: Path) -> None:
    if output_dir.exists():
        shutil.rmtree(output_dir)
    parent = output_dir.parent
    while parent != scope_root.parent and parent != scope_root:
        try:
            parent.rmdir()
        except OSError:
            break
        parent = parent.parent

def _desired_output_dir(project_root: Path, scope_folder: str, event_name: str) -> Path:
    resonance_dir = resonance_checks.output_dir_for_event(project_root, scope_folder, event_name)
    if resonance_dir is not None:
        return resonance_dir
    return project_root / "Plots" / "Generated" / scope_folder / event_name


def render_plot_batches(
    project_root: Path,
    scopes: Iterable[ScopeEntry],
    events: Iterable[str],
    log: LogFn | None = None,
    check_cancel: CancelFn | None = None,
) -> None:
    _render_plot_batches_direct(project_root, scopes, events, log, check_cancel)
