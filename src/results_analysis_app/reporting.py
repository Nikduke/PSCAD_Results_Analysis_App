from __future__ import annotations

from collections.abc import Callable, Iterable
from contextlib import ExitStack, nullcontext
from dataclasses import dataclass
import math
from pathlib import Path
import re
import shutil
import time
from typing import Any

from results_analysis_app import resonance_checks
from results_analysis_app.excel import EXCEL_AUTOMATION_ERRORS, excel_app
from results_analysis_app.models import ScopeEntry
from results_analysis_app.project_config import DEFAULT_EVENT_TIMES


IMAGE_WIDTH_CM = 15.92
BUS_VOLTAGE_SLICER_SOURCE_TEXT = "Bus voltage [kV]"
BUS_VOLTAGE_SLICER_VALUE_OVERRIDES = {"22": "23"}
DASHBOARD_FILTER_SETTLE_S = 0.8
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
JPEG_SIGNATURE = b"\xff\xd8"

LogFn = Callable[[str], None]


@dataclass(frozen=True)
class EnvelopeSummaryRow:
    event: str
    measurement: str
    time_s: float
    peak_kv: float
    rms_kv: float


ENVELOPE_SUMMARY_SHEETS = {"SFO": "LLp", "TOV": "LLp", "SA": "LGp"}
ENVELOPE_SUMMARY_RMS_EVENTS = {"TOV", "SA"}


def _log(log: LogFn | None, message: str) -> None:
    if log is not None:
        log(message)


def _safe_stem(text: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_.-]+", "_", text)
    value = re.sub(r"_+", "_", value)
    return value.strip("_.") or "figure"


def _is_report_image(path: Path) -> bool:
    try:
        if not path.is_file() or path.stat().st_size <= 0:
            return False
        with path.open("rb") as handle:
            header = handle.read(8)
    except OSError:
        return False
    suffix = path.suffix.casefold()
    if suffix == ".png":
        return header.startswith(PNG_SIGNATURE)
    if suffix in {".jpg", ".jpeg"}:
        return header.startswith(JPEG_SIGNATURE)
    return False


def _dashboard_slicer_value(voltage: str) -> str:
    value = str(voltage).strip()
    return BUS_VOLTAGE_SLICER_VALUE_OVERRIDES.get(value, value)


def _slicer_cache_touches_sheet(slicer_cache, sheet_name: str) -> bool:
    wanted = sheet_name.strip().casefold()
    try:
        count = slicer_cache.Slicers.Count
    except EXCEL_AUTOMATION_ERRORS:
        return False

    for index in range(1, count + 1):
        try:
            slicer = slicer_cache.Slicers(index)
            if slicer.Shape.TopLeftCell.Worksheet.Name.strip().casefold() == wanted:
                return True
        except EXCEL_AUTOMATION_ERRORS:
            continue
    return False


def _find_bus_voltage_slicer_cache(workbook, sheet_name: str):
    fallback = None
    try:
        count = workbook.SlicerCaches.Count
    except EXCEL_AUTOMATION_ERRORS:
        return None

    for index in range(1, count + 1):
        slicer_cache = workbook.SlicerCaches(index)
        try:
            source_name = str(slicer_cache.SourceName)
        except EXCEL_AUTOMATION_ERRORS:
            source_name = ""
        try:
            cache_name = str(slicer_cache.Name)
        except EXCEL_AUTOMATION_ERRORS:
            cache_name = ""

        combined = f"{source_name} {cache_name}".casefold()
        if (
            BUS_VOLTAGE_SLICER_SOURCE_TEXT.casefold() not in combined
            and "bus_voltage" not in combined
        ):
            continue

        if _slicer_cache_touches_sheet(slicer_cache, sheet_name):
            return slicer_cache
        if fallback is None:
            fallback = slicer_cache
    return fallback


def _set_dashboard_voltage_filter(
    excel,
    workbook,
    sheet_name: str,
    voltage: str,
    log: LogFn | None,
) -> bool:
    slicer_cache = _find_bus_voltage_slicer_cache(workbook, sheet_name)
    if slicer_cache is None:
        _log(log, f"Dashboard voltage slicer not found: {sheet_name}; exporting current view.")
        return False

    slicer_value = _dashboard_slicer_value(voltage)
    try:
        source_name = str(slicer_cache.SourceName)
        slicer_cache.VisibleSlicerItemsList = (f"{source_name}.&[{slicer_value}]",)
    except EXCEL_AUTOMATION_ERRORS as exc:
        _log(log, f"Dashboard voltage slicer update failed: {sheet_name} | {voltage} kV | {exc}")
        return False

    try:
        excel.CalculateUntilAsyncQueriesDone()
    except EXCEL_AUTOMATION_ERRORS as exc:
        _log(log, f"Dashboard query wait skipped: {sheet_name} | {voltage} kV | {exc}")
    time.sleep(DASHBOARD_FILTER_SETTLE_S)
    _log(log, f"Dashboard voltage slicer set: {sheet_name} | {voltage} kV")
    return True


def _excel_context(get_excel: Callable[[], object] | None):
    return nullcontext(get_excel()) if get_excel is not None else excel_app()


def _find_event_images(project_root: Path, scope: ScopeEntry, event: str, voltage: str) -> list[Path]:
    event_dir = project_root / "Plots" / "Generated" / scope.folder / event
    return _find_voltage_images(event_dir, voltage)


def _find_resonance_images(project_root: Path, scope: ScopeEntry, check: str, voltage_type: str, voltage: str) -> list[Path]:
    folder, type_folder = resonance_checks.report_folder(check, voltage_type)
    event_dir = project_root / "Plots" / "Generated" / scope.folder / folder / type_folder
    return _find_voltage_images(event_dir, voltage)


def _find_voltage_images(event_dir: Path, voltage: str) -> list[Path]:
    if not event_dir.is_dir():
        return []
    voltage_patterns = (
        re.compile(rf"MM_{re.escape(voltage)}(?:_|\.|\b)", re.IGNORECASE),
        re.compile(rf"(?:^|[_ -]){re.escape(voltage)}(?:[_ -]?kV|[_ .-])", re.IGNORECASE),
    )
    return [
        path
        for pattern in ("*.png", "*.jpg", "*.jpeg")
        for path in sorted(event_dir.rglob(pattern))
        if any(regex.search(path.name) for regex in voltage_patterns)
    ]


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _header_map(row: tuple[Any, ...]) -> dict[str, int]:
    return {
        str(value).strip().casefold(): index
        for index, value in enumerate(row)
        if value is not None and str(value).strip()
    }


def _row_value(row: tuple[Any, ...], headers: dict[str, int], *names: str) -> Any:
    for name in names:
        index = headers.get(name.casefold())
        if index is not None and index < len(row):
            return row[index]
    return None


def _envelope_summary_rows(
    workbook_path: Path,
    event_times: dict[str, float] | None = None,
    events: Iterable[str] | None = None,
) -> list[EnvelopeSummaryRow]:
    if not workbook_path.is_file():
        return []

    import openpyxl

    if events is None:
        selected_events = ["SFO", "TOV"]
    else:
        selected_events = []
        for event in events:
            event_name = str(event).strip().upper()
            if event_name in ENVELOPE_SUMMARY_SHEETS and event_name not in selected_events:
                selected_events.append(event_name)
    selected_times = [
        (event, float((event_times or {}).get(event, DEFAULT_EVENT_TIMES[event])))
        for event in selected_events
        if event in DEFAULT_EVENT_TIMES
    ]
    workbook = openpyxl.load_workbook(workbook_path, data_only=True, read_only=True)
    try:
        output: list[EnvelopeSummaryRow] = []
        for event_name, event_time in selected_times:
            sheet_name = ENVELOPE_SUMMARY_SHEETS[event_name]
            if sheet_name not in workbook.sheetnames:
                continue
            worksheet = workbook[sheet_name]
            rows = worksheet.iter_rows(values_only=True)
            try:
                headers = _header_map(tuple(next(rows)))
            except StopIteration:
                continue
            time_col = headers.get("time (s)")
            if time_col is None:
                continue

            best_error = 0.001
            best_row: tuple[Any, ...] | None = None
            for row_values in rows:
                row = tuple(row_values)
                if time_col >= len(row):
                    continue
                actual_time = _as_float(row[time_col])
                if actual_time is None:
                    continue
                error = abs(actual_time - event_time)
                if error <= best_error:
                    best_error = error
                    best_row = row
            if best_row is None:
                continue

            peak = _as_float(_row_value(best_row, headers, "Max_all", "Max"))
            time_s = _as_float(_row_value(best_row, headers, "Time (s)"))
            if peak is None or time_s is None:
                continue
            output.append(
                EnvelopeSummaryRow(
                    event=event_name,
                    measurement=sheet_name,
                    time_s=time_s,
                    peak_kv=peak,
                    rms_kv=abs(peak) / math.sqrt(2.0),
                )
            )
        return output
    finally:
        workbook.close()


def _format_float(value: float, decimals: int = 3) -> str:
    text = f"{value:.{decimals}f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def _add_subscripted_kv_unit(paragraph, subscript: str) -> None:
    paragraph.add_run(" kV")
    run = paragraph.add_run(subscript)
    run.font.subscript = True


def _add_envelope_summary_list(doc, rows: list[EnvelopeSummaryRow]) -> None:
    if not rows:
        return
    doc.add_paragraph("Highest overvoltages are:")
    for row in rows:
        paragraph = doc.add_paragraph(style="List Bullet")
        paragraph.add_run(f"{row.event}: {_format_float(row.peak_kv, 1)}")
        _add_subscripted_kv_unit(paragraph, "peak")
        if row.event in ENVELOPE_SUMMARY_RMS_EVENTS:
            paragraph.add_run(f" ({_format_float(row.rms_kv, 1)}")
            _add_subscripted_kv_unit(paragraph, "RMS")
            paragraph.add_run(")")
    doc.add_paragraph()


def _plot_heading_from_image_path(path: Path) -> str:
    stem = path.stem
    if stem.endswith("_3Ph") or stem.endswith("_1Ch"):
        stem = stem.rsplit("_", 1)[0]
    match = re.match(
        r"(?P<case>.+?)_(?P<element>MM_\d+(?:\.\d+)?(?:_[^_]+)*?)_(?:(?P<fault>[^_]+)_)?(?P<run>\d{3,})_(?P<trace>LGp_LLp|LGp|LLp|[^_]+)(?:_|$)",
        stem,
        flags=re.IGNORECASE,
    )
    if match:
        parts = [
            f"Case: {match.group('case')}",
            f"Run: {int(match.group('run'))}",
            f"Element: {match.group('element')}",
        ]
        fault = match.group("fault")
        if fault:
            parts.append(f"Fault: {fault}")
        trace = match.group("trace")
        if trace:
            parts.append(f"Trace: {trace.replace('_', ' & ') if trace == 'LGp_LLp' else trace}")
        return " | ".join(parts)
    return path.stem


def _export_envelope_chart(
    project_root: Path,
    scope: ScopeEntry,
    voltage: str,
    export_dir: Path,
    log: LogFn | None = None,
    get_excel: Callable[[], object] | None = None,
) -> Path | None:
    workbook_path = (
        project_root
        / "Voltage_envelope"
        / scope.folder
        / f"MM_{voltage}_with_combined_plot.xlsx"
    )
    if not workbook_path.is_file():
        return None
    export_dir.mkdir(parents=True, exist_ok=True)
    output_path = export_dir / f"Envelope_{scope.folder}_{voltage}_kV.png"
    try:
        output_path.unlink(missing_ok=True)
    except OSError:
        pass
    try:
        with _excel_context(get_excel) as excel:
            workbook = excel.Workbooks.Open(str(workbook_path), UpdateLinks=0, ReadOnly=True)
            try:
                worksheet = workbook.Worksheets("LLp")
                if worksheet.ChartObjects().Count < 1:
                    return None
                chart_object = worksheet.ChartObjects(1)
                _log(log, f"Exporting envelope chart: {scope.folder} | {voltage} kV")
                for _attempt in range(2):
                    try:
                        chart_object.Activate()
                    except EXCEL_AUTOMATION_ERRORS:
                        pass
                    time.sleep(0.5)
                    ok = chart_object.Chart.Export(str(output_path), "PNG")
                    if ok and _is_report_image(output_path):
                        return output_path
                    try:
                        output_path.unlink(missing_ok=True)
                    except OSError:
                        pass
                _log(log, f"Excel did not export a valid envelope chart: {output_path.name}")
                return None
            finally:
                workbook.Close(SaveChanges=False)
    except EXCEL_AUTOMATION_ERRORS as exc:
        _log(log, f"Envelope chart export skipped: {exc}")
        return None


def _parse_dashboard_figure_id(figure_id: str) -> tuple[str, str, int, str]:
    parts = figure_id.split("|", 3)
    if len(parts) != 4:
        raise ValueError(f"Unsupported dashboard figure id: {figure_id}")
    workbook, sheet, chart_index, title = [part.strip() for part in parts]
    return workbook, sheet, int(chart_index), title


def _export_dashboard_figures(
    project_root: Path,
    figure_ids: Iterable[str],
    voltage: str,
    export_dir: Path,
    log: LogFn | None = None,
    get_excel: Callable[[], object] | None = None,
    get_dashboard_workbook: Callable[[Path, str], object] | None = None,
) -> list[tuple[str, Path]]:
    selected_ids = [figure_id for figure_id in figure_ids if figure_id]
    if not selected_ids:
        return []
    export_dir.mkdir(parents=True, exist_ok=True)
    exported: list[tuple[str, Path]] = []
    try:
        with _excel_context(get_excel) as excel:
            grouped: dict[str, list[tuple[str, int, str, str]]] = {}
            for figure_id in selected_ids:
                try:
                    workbook_name, sheet_name, chart_index, title = _parse_dashboard_figure_id(figure_id)
                except ValueError as exc:
                    _log(log, str(exc))
                    continue
                grouped.setdefault(workbook_name, []).append((sheet_name, chart_index, title, figure_id))

            for workbook_name, figures in grouped.items():
                workbook_path = project_root / "Dashboards" / workbook_name
                if not workbook_path.is_file():
                    _log(log, f"Dashboard workbook not found, skipping: {workbook_name}")
                    continue

                _log(log, f"Opening dashboard for report figures: {workbook_name}")
                if get_dashboard_workbook is None:
                    workbook = excel.Workbooks.Open(str(workbook_path), UpdateLinks=0, ReadOnly=True)
                    close_workbook = True
                else:
                    workbook = get_dashboard_workbook(project_root, workbook_name)
                    close_workbook = False
                try:
                    filtered_sheets: set[str] = set()
                    for sheet_name, chart_index, title, figure_id in figures:
                        try:
                            sheet_key = sheet_name.strip().casefold()
                            if sheet_key not in filtered_sheets:
                                _set_dashboard_voltage_filter(excel, workbook, sheet_name, str(voltage), log)
                                filtered_sheets.add(sheet_key)
                            worksheet = workbook.Worksheets(sheet_name)
                            chart_object = worksheet.ChartObjects(chart_index)
                            figure_title = title or f"Chart {chart_index}"
                            file_name = _safe_stem(
                                f"{voltage}_kV_{workbook_name}_{sheet_name}_{chart_index}_{figure_title}.png"
                            )
                            output_path = export_dir / file_name
                            try:
                                output_path.unlink(missing_ok=True)
                            except OSError:
                                pass
                            _log(log, f"Exporting dashboard figure: {voltage} kV | {figure_title}")
                            ok = chart_object.Chart.Export(str(output_path), "PNG")
                            if not ok or not _is_report_image(output_path):
                                _log(log, f"Excel did not export dashboard figure: {figure_id}")
                                try:
                                    output_path.unlink(missing_ok=True)
                                except OSError:
                                    pass
                                continue
                            exported.append((figure_title, output_path))
                        except EXCEL_AUTOMATION_ERRORS as exc:
                            _log(log, f"Dashboard figure skipped: {figure_id} | {exc}")
                finally:
                    if close_workbook:
                        workbook.Close(SaveChanges=False)
    except EXCEL_AUTOMATION_ERRORS as exc:
        _log(log, f"Dashboard figure export skipped: {exc}")

    return exported


def build_reports_from_existing_plots(
    project_roots: Iterable[str | Path],
    scopes: Iterable[ScopeEntry],
    voltages: Iterable[str],
    events: Iterable[str],
    dashboard_figure_ids: Iterable[str] = (),
    resonance_settings: dict[str, object] | None = None,
    event_times: dict[str, float] | None = None,
    log: LogFn | None = None,
) -> list[Path]:
    """Build draft Word reports from already generated plot image files."""
    try:
        from docx import Document
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.shared import Cm
    except ImportError as exc:
        raise RuntimeError("python-docx is required to build Word reports.") from exc

    written: list[Path] = []
    selected_scopes = list(scopes)
    selected_events = list(events)
    selected_voltages = list(voltages)
    parsed_resonance = resonance_checks.ResonanceSettings.from_mapping(resonance_settings)

    with ExitStack() as stack:
        excel = None
        dashboard_workbooks: dict[tuple[Path, str], object] = {}

        def get_excel():
            nonlocal excel
            if excel is None:
                excel = stack.enter_context(excel_app())
            return excel

        def get_dashboard_workbook(project_root: Path, workbook_name: str):
            key = (project_root, workbook_name)
            workbook = dashboard_workbooks.get(key)
            if workbook is None:
                workbook_path = project_root / "Dashboards" / workbook_name
                workbook = get_excel().Workbooks.Open(str(workbook_path), UpdateLinks=0, ReadOnly=True)
                dashboard_workbooks[key] = workbook
                stack.callback(lambda wb=workbook: wb.Close(SaveChanges=False))
            return workbook

        for project_root in project_roots:
            root = Path(project_root).resolve()
            for scope in selected_scopes:
                report_dir = root / "Reports" / scope.folder
                report_dir.mkdir(parents=True, exist_ok=True)
                for voltage in selected_voltages:
                    _log(log, f"Building report: {root.name} | {scope.folder} | {voltage} kV")
                    doc = Document()
                    section = doc.sections[0]
                    section.page_width = Cm(21.0)
                    section.page_height = Cm(29.7)
                    section.left_margin = Cm(2.54)
                    section.right_margin = Cm(2.54)
                    section.top_margin = Cm(2.54)
                    section.bottom_margin = Cm(2.54)

                    doc.add_heading(f"Voltage {voltage} kV - {scope.name}", level=1)
                    envelope_chart = _export_envelope_chart(
                        root,
                        scope,
                        str(voltage),
                        report_dir / "_envelope_exports",
                        log,
                        get_excel,
                    )
                    if envelope_chart is not None:
                        doc.add_heading(f"{voltage} kV - Envelope - {scope.name}", level=2)
                        envelope_workbook = root / "Voltage_envelope" / scope.folder / f"MM_{voltage}.xlsx"
                        _add_envelope_summary_list(
                            doc,
                            _envelope_summary_rows(envelope_workbook, event_times, selected_events),
                        )
                        paragraph = doc.add_paragraph()
                        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
                        paragraph.add_run().add_picture(str(envelope_chart), width=Cm(IMAGE_WIDTH_CM))

                    plot_count = 0

                    for event in selected_events:
                        images = _find_event_images(root, scope, event, voltage)
                        if not images:
                            continue
                        doc.add_heading(f"{voltage} kV - {event} - {scope.name}", level=2)
                        for image_path in images:
                            if not _is_report_image(image_path):
                                _log(log, f"Skipping invalid plot image: {image_path}")
                                continue
                            doc.add_heading(_plot_heading_from_image_path(image_path), level=3)
                            paragraph = doc.add_paragraph()
                            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
                            paragraph.add_run().add_picture(str(image_path), width=Cm(IMAGE_WIDTH_CM))
                            plot_count += 1

                    for check in parsed_resonance.effective_enabled_checks:
                        for voltage_type in resonance_checks.VOLTAGE_TYPES:
                            images = _find_resonance_images(root, scope, check, voltage_type, voltage)
                            if not images:
                                continue
                            label = resonance_checks.CHECK_DEFINITIONS[check]["label"]
                            doc.add_heading(f"{voltage} kV - {label} - {voltage_type} - {scope.name}", level=2)
                            for image_path in images:
                                if not _is_report_image(image_path):
                                    _log(log, f"Skipping invalid plot image: {image_path}")
                                    continue
                                doc.add_heading(_plot_heading_from_image_path(image_path), level=3)
                                paragraph = doc.add_paragraph()
                                paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
                                paragraph.add_run().add_picture(str(image_path), width=Cm(IMAGE_WIDTH_CM))
                                plot_count += 1

                    if plot_count == 0:
                        doc.add_paragraph("No generated plot images were found for this report.")

                    dashboard_figures = _export_dashboard_figures(
                        root,
                        dashboard_figure_ids,
                        str(voltage),
                        report_dir / "_dashboard_exports" / f"Voltage_{voltage}_kV",
                        log,
                        get_excel,
                        get_dashboard_workbook,
                    )
                    if dashboard_figures:
                        doc.add_heading(f"{voltage} kV - Dashboard Figures - {scope.name}", level=2)
                        for figure_title, image_path in dashboard_figures:
                            doc.add_heading(figure_title, level=3)
                            paragraph = doc.add_paragraph()
                            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
                            paragraph.add_run().add_picture(str(image_path), width=Cm(IMAGE_WIDTH_CM))
                    elif dashboard_figure_ids:
                        doc.add_paragraph("Selected dashboard figures could not be exported.")

                    output_path = report_dir / f"Voltage_{voltage}_kV.docx"
                    doc.save(output_path)
                    written.append(output_path)
                    _log(log, f"Wrote report: {output_path}")

                for temporary_dir in (
                    report_dir / "_envelope_exports",
                    report_dir / "_dashboard_exports",
                ):
                    shutil.rmtree(temporary_dir, ignore_errors=True)

    return written
