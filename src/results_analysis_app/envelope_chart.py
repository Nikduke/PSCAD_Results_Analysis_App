from __future__ import annotations

from pathlib import Path
import shutil
import time
import uuid
import zipfile
import xml.etree.ElementTree as ET
import re

from results_analysis_app.excel import EXCEL_AUTOMATION_ERRORS, excel_app
from results_analysis_app.models import (
    DEFAULT_ENVELOPE_CHART_HEIGHT,
    DEFAULT_ENVELOPE_CHART_WIDTH,
    DEFAULT_ENVELOPE_CHART_X_MAJOR,
    DEFAULT_ENVELOPE_CHART_X_MAX,
    DEFAULT_ENVELOPE_CHART_Y_LIMITS,
)
from results_analysis_app.project_config import DEFAULT_EVENT_TIMES, automatic_time_major


LG_SHEET_NAME = "LGp"
LL_SHEET_NAME = "LLp"
CHART_SHEET_NAME = "LLp"
TIME_HEADER = "Time (s)"
VALUE_HEADER = "Max_all"
VALUE_HEADER_FALLBACKS = ("Max",)

CHART_TITLE = "Representative overvoltages envelope curve"
X_AXIS_TITLE = "Time (s)"
Y_AXIS_TITLE = "Voltage (kV)"
CHART_TOP_LEFT_CELL = "H1"
DEFAULT_CHART_SIZE_POINTS = {"width": DEFAULT_ENVELOPE_CHART_WIDTH, "height": DEFAULT_ENVELOPE_CHART_HEIGHT}

DEFAULT_AXIS_LIMITS = {
    "x_min": 0.0,
    "x_max": DEFAULT_ENVELOPE_CHART_X_MAX,
    "x_major": DEFAULT_ENVELOPE_CHART_X_MAJOR,
    "y_min": 0.0,
    "y_max": None,
    "y_major": None,
}

LL_SERIES_NAME = "Max LL"
LG_SERIES_NAME = "Max LG"

OOXML_DATALABEL_LAYOUTS_BY_SERIES = {
    LL_SERIES_NAME: {
        0.004: {"x": "5.2646481481481502E-2", "y": "3.7886159310370343E-2"},
        0.03: {"x": "0.17521296296296301", "y": "-4.1044433756335832E-2"},
    },
    LG_SERIES_NAME: {
        0.004: {"x": "4.7037037037037016E-2", "y": "-0.11041843945391991"},
        0.03: {"x": "0.17168518518518522", "y": "-4.2287912982352377E-2"},
        0.1: {"x": "0.22577777777777777", "y": "-8.6141049855292331E-17"},
    },
}
OOXML_DATALABEL_BODY_INSETS_BY_SERIES = {
    LL_SERIES_NAME: {"lIns": "36576", "tIns": "18288", "rIns": "36576", "bIns": "18288"},
    LG_SERIES_NAME: {"lIns": "38100", "tIns": "19050", "rIns": "38100", "bIns": "19050"},
}

TIME_TOLERANCE = 1e-9
MAX_NEAREST_TIME_ERROR = 0.001
TEXT_COLOR = (89, 89, 89)
GRID_COLOR = (217, 217, 217)
CHART_BORDER_COLOR = (217, 217, 217)
CHART_TITLE_FONT_NAME = "Calibri Light"
CHART_TITLE_FONT_SIZE = 21.6
CHART_TITLE_BOLD = True
AXIS_TITLE_FONT_NAME = "Calibri Light"
AXIS_TITLE_FONT_SIZE = 18
AXIS_TITLE_BOLD = True
AXIS_TICK_FONT_NAME = "Calibri Light"
AXIS_TICK_FONT_SIZE = 18
AXIS_TICK_BOLD = True
SERIES_LINE_WEIGHT = 1.5

xlUp = -4162
xlToLeft = -4159
xlXYScatterLinesNoMarkers = 75
xlCategory = 1
xlValue = 2
xlPrimary = 1
xlMarkerStyleNone = -4142
xlLegendPositionRight = -4152
msoFalse = 0
msoTrue = -1
msoLineDash = 4

OOXML_NS = {
    "c": "http://schemas.openxmlformats.org/drawingml/2006/chart",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
    "c14": "http://schemas.microsoft.com/office/drawing/2007/8/2/chart",
    "c15": "http://schemas.microsoft.com/office/drawing/2012/chart",
    "c16": "http://schemas.microsoft.com/office/drawing/2014/chart",
    "c16r2": "http://schemas.microsoft.com/office/drawing/2015/06/chart",
    "c16r3": "http://schemas.microsoft.com/office/drawing/2017/03/chart",
    "a14": "http://schemas.microsoft.com/office/drawing/2010/main",
}
for _prefix, _uri in OOXML_NS.items():
    ET.register_namespace(_prefix, _uri)


def create_combined_envelope_plot(
    input_path: Path,
    output_path: Path | None = None,
    excel=None,
    axis_limits_override: dict | None = None,
    axis_limits_by_voltage: dict | None = None,
    event_times: dict[str, float] | None = None,
    show_sa_label: bool = False,
    chart_top_left_cell: str | None = None,
    chart_size: dict | None = None,
) -> Path:
    input_path = Path(input_path).resolve()
    output_path = Path(output_path or input_path.with_name(f"{input_path.stem}_with_combined_plot{input_path.suffix}")).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    staged_path = output_path.with_name(
        f".{output_path.stem}.{uuid.uuid4().hex}.tmp{output_path.suffix}"
    )
    try:
        shutil.copy2(input_path, staged_path)
        series_definitions = _series_definitions(event_times, show_sa_label)
        if excel is None:
            with excel_app() as app:
                _create_combined_envelope_plot_with_excel(
                    app,
                    input_path,
                    staged_path,
                    axis_limits_override,
                    axis_limits_by_voltage,
                    series_definitions,
                    chart_top_left_cell,
                    chart_size,
                )
        else:
            _create_combined_envelope_plot_with_excel(
                excel,
                input_path,
                staged_path,
                axis_limits_override,
                axis_limits_by_voltage,
                series_definitions,
                chart_top_left_cell,
                chart_size,
            )
        _patch_workbook_native_data_labels(staged_path, series_definitions)
        staged_path.replace(output_path)
    except Exception:
        staged_path.unlink(missing_ok=True)
        raise
    return output_path


def create_resonance_check_charts(
    workbook_path: Path,
    excel=None,
    x_max: float | None = None,
    x_major: float | None = None,
) -> bool:
    workbook_path = Path(workbook_path).resolve()
    if not workbook_path.is_file():
        return False
    if excel is None:
        with excel_app() as app:
            return _create_resonance_check_charts_with_excel(app, workbook_path, x_max, x_major)
    return _create_resonance_check_charts_with_excel(excel, workbook_path, x_max, x_major)


def _create_combined_envelope_plot_with_excel(
    excel,
    input_path: Path,
    output_path: Path,
    axis_limits_override: dict | None,
    axis_limits_by_voltage: dict | None,
    series_definitions: list[dict],
    chart_top_left_cell: str | None,
    chart_size: dict | None,
) -> None:
    wb = excel.Workbooks.Open(str(output_path))
    try:
        _create_combined_plot(
            wb,
            _get_axis_limits(input_path, axis_limits_override, axis_limits_by_voltage),
            input_path,
            series_definitions,
            chart_top_left_cell,
            chart_size,
        )
        wb.Save()
    finally:
        try:
            wb.Close(SaveChanges=False)
        except EXCEL_AUTOMATION_ERRORS:
            pass


def _rgb(r: int, g: int, b: int) -> int:
    return r + (g * 256) + (b * 65536)


def _rgb_tuple(color_tuple) -> int:
    return _rgb(color_tuple[0], color_tuple[1], color_tuple[2])


def _as_float(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _format_time(value: float) -> str:
    return f"{value:.6f}".rstrip("0").rstrip(".")


def _extract_voltage_level(path: Path) -> str | None:
    match = re.match(r"^MM_(\d+)", path.stem, flags=re.IGNORECASE)
    return match.group(1) if match else None


def _series_definitions(event_times: dict[str, float] | None, show_sa_label: bool) -> list[dict]:
    sfo = float((event_times or {}).get("SFO", DEFAULT_EVENT_TIMES["SFO"]))
    tov = float((event_times or {}).get("TOV", DEFAULT_EVENT_TIMES["TOV"]))
    sa = float((event_times or {}).get("SA", DEFAULT_EVENT_TIMES["SA"]))
    lg_times = [sfo, tov]
    if show_sa_label:
        lg_times.append(sa)
    return [
        {"name": LL_SERIES_NAME, "sheet_name": LL_SHEET_NAME, "color": (79, 129, 189), "annotation_times": [sfo, tov]},
        {"name": LG_SERIES_NAME, "sheet_name": LG_SHEET_NAME, "color": (192, 80, 77), "annotation_times": lg_times},
    ]


def _get_axis_limits(
    path: Path,
    axis_limits_override: dict | None = None,
    axis_limits_by_voltage: dict | None = None,
) -> dict:
    limits = DEFAULT_AXIS_LIMITS.copy()
    voltage = _extract_voltage_level(path)
    if voltage in DEFAULT_ENVELOPE_CHART_Y_LIMITS:
        limits.update(DEFAULT_ENVELOPE_CHART_Y_LIMITS[voltage])
    if axis_limits_by_voltage and voltage in axis_limits_by_voltage:
        limits.update(
            {key: value for key, value in axis_limits_by_voltage[voltage].items() if value is not None}
        )
    if axis_limits_override:
        for key, value in axis_limits_override.items():
            if value is not None or key in {"x_max", "x_major"}:
                limits[key] = value
    return limits


def _worksheet(wb, sheet_name: str):
    for ws in wb.Worksheets:
        if ws.Name.strip().lower() == sheet_name.strip().lower():
            return ws
    raise ValueError(f"Worksheet '{sheet_name}' not found.")


def _find_header_col(ws, header_name: str, header_row: int = 1):
    last_col = ws.Cells(header_row, ws.Columns.Count).End(xlToLeft).Column
    for col in range(1, last_col + 1):
        value = ws.Cells(header_row, col).Value
        if value is not None and str(value).strip().lower() == header_name.strip().lower():
            return col
    return None


def _find_first_header_col(ws, header_names, header_row: int = 1):
    for header_name in header_names:
        col = _find_header_col(ws, header_name, header_row)
        if col is not None:
            return col, header_name
    return None, None


def _last_used_row_in_column(ws, col: int):
    return ws.Cells(ws.Rows.Count, col).End(xlUp).Row


def _series_source(series_cfg: dict, wb):
    ws = _worksheet(wb, series_cfg["sheet_name"])
    time_col = _find_header_col(ws, TIME_HEADER)
    value_col, value_header = _find_first_header_col(ws, (VALUE_HEADER, *VALUE_HEADER_FALLBACKS))
    if time_col is None or value_col is None:
        raise ValueError(f"Sheet '{ws.Name}' does not contain '{TIME_HEADER}' and '{VALUE_HEADER}'.")
    last_row = min(_last_used_row_in_column(ws, time_col), _last_used_row_in_column(ws, value_col))
    if last_row < 3:
        raise ValueError(f"Sheet '{ws.Name}' does not contain enough data.")
    return ws, time_col, value_col, last_row, value_header


def _find_time_row(ws, time_col: int, value_col: int, last_row: int, target_time: float):
    best_row = None
    best_time = None
    best_value = None
    best_error = None
    for row in range(2, last_row + 1):
        t = _as_float(ws.Cells(row, time_col).Value)
        v = _as_float(ws.Cells(row, value_col).Value)
        if t is None or v is None:
            continue
        error = abs(t - target_time)
        if error <= TIME_TOLERANCE:
            return row, t, v
        if best_error is None or error < best_error:
            best_row = row
            best_time = t
            best_value = v
            best_error = error
    if best_row is not None and best_error is not None and best_error <= MAX_NEAREST_TIME_ERROR:
        return best_row, best_time, best_value
    raise ValueError(f"Could not find time {_format_time(target_time)} s on sheet '{ws.Name}'.")


def _delete_existing_charts(ws) -> None:
    for i in range(ws.ChartObjects().Count, 0, -1):
        ws.ChartObjects(i).Delete()


def _chart_bounds(ws, chart_top_left_cell: str | None, chart_size: dict | None):
    top_left = ws.Range(chart_top_left_cell or CHART_TOP_LEFT_CELL)
    size = chart_size or DEFAULT_CHART_SIZE_POINTS
    return top_left.Left, top_left.Top, size["width"], size["height"]


def _safe_set_textframe2_font(text_range, name=None, size=None, color=None, bold=None):
    try:
        font = text_range.Font
        if name is not None:
            font.Name = name
        if size is not None:
            font.Size = size
        if color is not None:
            font.Fill.ForeColor.RGB = color
        if bold is not None:
            font.Bold = msoTrue if bold else msoFalse
        return True
    except EXCEL_AUTOMATION_ERRORS:
        return False


def _safe_set_chart_title_font(chart, name=None, size=None, color=None, bold=False):
    try:
        if _safe_set_textframe2_font(chart.ChartTitle.Format.TextFrame2.TextRange, name, size, color, bold):
            return
    except EXCEL_AUTOMATION_ERRORS:
        pass
    try:
        if name is not None:
            chart.ChartTitle.Font.Name = name
        if size is not None:
            chart.ChartTitle.Font.Size = size
        if color is not None:
            chart.ChartTitle.Font.Color = color
        chart.ChartTitle.Font.Bold = bold
    except EXCEL_AUTOMATION_ERRORS:
        pass


def _safe_set_axis_title_font(axis, name=None, size=None, color=None, bold=False):
    try:
        if _safe_set_textframe2_font(axis.AxisTitle.Format.TextFrame2.TextRange, name, size, color, bold):
            return
    except EXCEL_AUTOMATION_ERRORS:
        pass
    try:
        if name is not None:
            axis.AxisTitle.Font.Name = name
        if size is not None:
            axis.AxisTitle.Font.Size = size
        if color is not None:
            axis.AxisTitle.Font.Color = color
        axis.AxisTitle.Font.Bold = bold
    except EXCEL_AUTOMATION_ERRORS:
        pass


def _safe_set_tick_label_font(axis, name=None, size=None, color=None, bold=False):
    try:
        if name is not None:
            axis.TickLabels.Font.Name = name
        if size is not None:
            axis.TickLabels.Font.Size = size
        if color is not None:
            axis.TickLabels.Font.Color = color
        axis.TickLabels.Font.Bold = bold
    except EXCEL_AUTOMATION_ERRORS:
        pass


def _safe_set_legend_font(chart, name=None, size=None, color=None, bold=False):
    try:
        if name is not None:
            chart.Legend.Font.Name = name
        if size is not None:
            chart.Legend.Font.Size = size
        if color is not None:
            chart.Legend.Font.Color = color
        chart.Legend.Font.Bold = bold
    except EXCEL_AUTOMATION_ERRORS:
        pass


def _apply_axis_limits(axis, limits: dict, axis_name: str):
    if limits.get(f"{axis_name}_min") is not None:
        axis.MinimumScale = limits[f"{axis_name}_min"]
    if limits.get(f"{axis_name}_max") is not None:
        axis.MaximumScale = limits[f"{axis_name}_max"]
    if limits.get(f"{axis_name}_major") is not None:
        axis.MajorUnit = limits[f"{axis_name}_major"]


def _format_chart(
    chart,
    axis_limits: dict,
    title: str = CHART_TITLE,
    x_title: str = X_AXIS_TITLE,
    y_title: str = Y_AXIS_TITLE,
    x_number_format: str = "General",
    y_number_format: str = "General",
) -> None:
    text_color = _rgb_tuple(TEXT_COLOR)
    chart.HasTitle = True
    chart.ChartTitle.Text = title
    _safe_set_chart_title_font(chart, CHART_TITLE_FONT_NAME, CHART_TITLE_FONT_SIZE, text_color, CHART_TITLE_BOLD)

    chart.HasLegend = True
    chart.Legend.Position = xlLegendPositionRight
    _safe_set_legend_font(chart, AXIS_TICK_FONT_NAME, AXIS_TICK_FONT_SIZE, text_color, AXIS_TICK_BOLD)

    chart.ChartArea.Format.Fill.ForeColor.RGB = _rgb(255, 255, 255)
    chart.ChartArea.Format.Line.ForeColor.RGB = _rgb_tuple(CHART_BORDER_COLOR)
    chart.ChartArea.Format.Line.Weight = 1.0
    chart.PlotArea.Format.Fill.ForeColor.RGB = _rgb(255, 255, 255)
    try:
        chart.PlotArea.Format.Line.Visible = msoFalse
    except EXCEL_AUTOMATION_ERRORS:
        pass

    x_axis = chart.Axes(xlCategory, xlPrimary)
    x_axis.HasTitle = True
    x_axis.AxisTitle.Text = x_title
    _apply_axis_limits(x_axis, axis_limits, "x")
    x_axis.TickLabels.NumberFormat = x_number_format
    _safe_set_tick_label_font(x_axis, AXIS_TICK_FONT_NAME, AXIS_TICK_FONT_SIZE, text_color, AXIS_TICK_BOLD)
    _safe_set_axis_title_font(x_axis, AXIS_TITLE_FONT_NAME, AXIS_TITLE_FONT_SIZE, text_color, AXIS_TITLE_BOLD)

    y_axis = chart.Axes(xlValue, xlPrimary)
    y_axis.HasTitle = True
    y_axis.AxisTitle.Text = y_title
    _apply_axis_limits(y_axis, axis_limits, "y")
    y_axis.TickLabels.NumberFormat = y_number_format
    _safe_set_tick_label_font(y_axis, AXIS_TICK_FONT_NAME, AXIS_TICK_FONT_SIZE, text_color, AXIS_TICK_BOLD)
    _safe_set_axis_title_font(y_axis, AXIS_TITLE_FONT_NAME, AXIS_TITLE_FONT_SIZE, text_color, AXIS_TITLE_BOLD)

    x_axis.HasMajorGridlines = True
    y_axis.HasMajorGridlines = True
    for axis in (x_axis, y_axis):
        try:
            axis.MajorGridlines.Format.Line.ForeColor.RGB = _rgb_tuple(GRID_COLOR)
            axis.MajorGridlines.Format.Line.Weight = 0.75
        except EXCEL_AUTOMATION_ERRORS:
            pass


def _excel_series_name(name):
    try:
        address = name.Address
        sheet_name = str(name.Worksheet.Name).replace("'", "''")
        return f"='{sheet_name}'!{address}"
    except EXCEL_AUTOMATION_ERRORS:
        return name


def _add_chart_series(
    chart,
    name,
    xvalues,
    yvalues,
    color: tuple[int, int, int],
    weight: float,
    dashed: bool = False,
):
    series = chart.SeriesCollection().NewSeries()
    series.Name = _excel_series_name(name)
    series.XValues = xvalues
    series.Values = yvalues
    series.MarkerStyle = xlMarkerStyleNone
    series.Format.Line.ForeColor.RGB = _rgb_tuple(color)
    series.Format.Line.Weight = weight
    if dashed:
        series.Format.Line.DashStyle = msoLineDash
    return series


def _create_combined_plot(
    wb,
    axis_limits: dict,
    workbook_path: Path,
    series_definitions: list[dict],
    chart_top_left_cell: str | None,
    chart_size: dict | None,
) -> None:
    chart_ws = _worksheet(wb, CHART_SHEET_NAME)
    for series_cfg in series_definitions:
        _delete_existing_charts(_worksheet(wb, series_cfg["sheet_name"]))

    left, top, width, height = _chart_bounds(chart_ws, chart_top_left_cell, chart_size)
    chart_obj = chart_ws.ChartObjects().Add(left, top, width, height)
    chart_obj.Name = "Representative_Overvoltage_Envelope"
    chart = chart_obj.Chart
    chart.ChartType = xlXYScatterLinesNoMarkers

    while chart.SeriesCollection().Count > 0:
        chart.SeriesCollection(1).Delete()

    data_ends: list[float] = []
    for series_cfg in series_definitions:
        source_ws, time_col, value_col, last_row, _value_header = _series_source(series_cfg, wb)
        data_ends.append(_worksheet_time_end(source_ws, time_col, last_row))
        _add_chart_series(
            chart,
            series_cfg["name"],
            source_ws.Range(source_ws.Cells(2, time_col), source_ws.Cells(last_row, time_col)),
            source_ws.Range(source_ws.Cells(2, value_col), source_ws.Cells(last_row, value_col)),
            series_cfg["color"],
            SERIES_LINE_WEIGHT,
        )
        for target_time in series_cfg["annotation_times"]:
            _find_time_row(source_ws, time_col, value_col, last_row, target_time)

    _format_chart(chart, _bounded_x_axis(axis_limits, max(data_ends)))
    chart_obj.Activate()
    time.sleep(0.2)


def _create_resonance_check_charts_with_excel(
    excel,
    workbook_path: Path,
    x_max: float | None,
    x_major: float | None,
) -> bool:
    wb = excel.Workbooks.Open(str(workbook_path), UpdateLinks=0, ReadOnly=False)
    changed = False
    try:
        for ws in wb.Worksheets:
            if not _is_resonance_chart_data_sheet(ws):
                continue
            _delete_existing_charts(ws)
            if _create_resonance_check_chart(ws, x_max, x_major):
                changed = True
        if changed:
            wb.Save()
        return changed
    finally:
        try:
            wb.Close(SaveChanges=False)
        except EXCEL_AUTOMATION_ERRORS:
            pass


def _is_resonance_chart_data_sheet(ws) -> bool:
    try:
        return [ws.Cells(1, col).Value for col in range(1, 5)] == ["Time (s)", "E(t)", "E_s(t)", "Vlim"]
    except EXCEL_AUTOMATION_ERRORS:
        return False


def _create_resonance_check_chart(
    ws,
    x_max: float | None = None,
    x_major: float | None = None,
) -> bool:
    last_row = int(ws.Cells(ws.Rows.Count, 1).End(xlUp).Row)
    if last_row < 3:
        return False

    t_start = _as_float(ws.Range("G4").Value) or 0.0
    vlim = _as_float(ws.Range("G6").Value)
    if vlim is None:
        vlim = _as_float(ws.Cells(2, 4).Value) or 0.0
    t_end = _worksheet_time_end(ws, 1, last_row)
    y_max = max(
        _excel_range_max(ws, 2, last_row, 0.0),
        _excel_range_max(ws, 3, last_row, 0.0),
        _excel_range_max(ws, 4, last_row, vlim),
        vlim,
        1.0,
    ) * 1.08

    ws.Range("I1").Value = "Start x"
    ws.Range("J1").Value = "Start y"
    ws.Range("I2").Value = t_start
    ws.Range("J2").Value = 0.0
    ws.Range("I3").Value = t_start
    ws.Range("J3").Value = y_max
    _set_vlim_label_cell(ws.Range("L1"), vlim)

    anchor = ws.Range("F7")
    chart_obj = ws.ChartObjects().Add(
        anchor.Left,
        anchor.Top,
        DEFAULT_CHART_SIZE_POINTS["width"],
        DEFAULT_CHART_SIZE_POINTS["height"],
    )
    chart_obj.Name = "Resonance_Check"
    chart = chart_obj.Chart
    chart.ChartType = xlXYScatterLinesNoMarkers
    while chart.SeriesCollection().Count > 0:
        chart.SeriesCollection(1).Delete()

    x_range = ws.Range(ws.Cells(2, 1), ws.Cells(last_row, 1))
    _add_chart_series(chart, "E(t)", x_range, ws.Range(ws.Cells(2, 2), ws.Cells(last_row, 2)), (79, 129, 189), 1.5)
    _add_chart_series(chart, "E_s(t)", x_range, ws.Range(ws.Cells(2, 3), ws.Cells(last_row, 3)), (192, 80, 77), 1.75)
    _add_chart_series(
        chart,
        ws.Range("L1"),
        x_range,
        ws.Range(ws.Cells(2, 4), ws.Cells(last_row, 4)),
        (112, 173, 71),
        1.5,
        dashed=True,
    )
    _add_chart_series(
        chart,
        f"Start {_format_compact_number(t_start)} s",
        ws.Range("I2:I3"),
        ws.Range("J2:J3"),
        (127, 127, 127),
        1.25,
        dashed=True,
    )

    _format_chart(
        chart,
        _bounded_x_axis(
            {
                "x_min": 0.0,
                "x_max": x_max,
                "x_major": x_major,
                "y_min": 0.0,
                "y_max": y_max,
            },
            t_end,
        ),
        title=_resonance_chart_title(ws),
        y_title=Y_AXIS_TITLE,
        x_number_format="0.000",
        y_number_format="0",
    )
    chart_obj.Activate()
    time.sleep(0.2)
    return True


def _excel_range_max(ws, col: int, last_row: int, default: float) -> float:
    try:
        value = float(ws.Application.WorksheetFunction.Max(ws.Range(ws.Cells(2, col), ws.Cells(last_row, col))))
    except EXCEL_AUTOMATION_ERRORS:
        return default
    return value if value == value else default


def _worksheet_time_end(ws, time_col: int, last_row: int) -> float:
    last_time = _as_float(ws.Cells(last_row, time_col).Value) or 0.0
    previous_time = _as_float(ws.Cells(last_row - 1, time_col).Value) if last_row > 2 else None
    if previous_time is None or previous_time >= last_time:
        return last_time
    return last_time + (last_time - previous_time)


def _bounded_x_axis(axis_limits: dict, data_end: float) -> dict:
    bounded = dict(axis_limits)
    requested = _as_float(bounded.get("x_max"))
    if data_end > 0:
        bounded["x_max"] = min(requested, data_end) if requested is not None else data_end
    if _as_float(bounded.get("x_major")) is None:
        bounded["x_major"] = automatic_time_major(_as_float(bounded.get("x_max")))
    return bounded


def _set_vlim_label_cell(cell, vlim: float) -> None:
    text = f"Vlim {_format_compact_number(vlim)} kVpeak"
    cell.Value = text
    try:
        cell.Characters(2, 3).Font.Subscript = True
        peak_start = text.index("peak") + 1
        cell.Characters(peak_start, 4).Font.Subscript = True
    except EXCEL_AUTOMATION_ERRORS:
        pass


def _format_compact_number(value: float) -> str:
    if value != value:
        return ""
    if abs(value) >= 100:
        return f"{value:.0f}"
    if abs(value) >= 10:
        return f"{value:.1f}"
    return f"{value:.3g}"


def _resonance_chart_title(ws) -> str:
    case = ws.Range("G1").Value or ""
    run = ws.Range("G2").Value or ""
    mm_name = ws.Range("G3").Value or ""
    return f"{ws.Name} | {case} r{run} | {mm_name}".strip(" |")


def _qn(prefix: str, tag: str) -> str:
    return f"{{{OOXML_NS[prefix]}}}{tag}"


def _sub(parent, prefix: str, tag: str, attrs=None):
    return ET.SubElement(parent, _qn(prefix, tag), attrs or {})


def _series_x_values_by_index(series):
    values = {}
    cache = series.find("c:xVal/c:numRef/c:numCache", OOXML_NS)
    if cache is None:
        cache = series.find("c:xVal/c:numLit", OOXML_NS)
    if cache is None:
        return values
    for pt in cache.findall("c:pt", OOXML_NS):
        idx_raw = pt.attrib.get("idx")
        v_node = pt.find("c:v", OOXML_NS)
        if idx_raw is None or v_node is None or v_node.text is None:
            continue
        try:
            values[int(idx_raw)] = float(v_node.text)
        except (TypeError, ValueError):
            continue
    return values


def _nearest_x_index(x_values: dict, target_time: float):
    best_idx = None
    best_value = None
    best_error = None
    for idx, value in x_values.items():
        error = abs(value - target_time)
        if best_error is None or error < best_error:
            best_idx = idx
            best_value = value
            best_error = error
    if best_idx is not None and best_error is not None and best_error <= max(TIME_TOLERANCE, MAX_NEAREST_TIME_ERROR):
        return best_idx, best_value, best_error
    return None, best_value, best_error


def _add_show_flags(parent, show_val: str, show_cat: str):
    _sub(parent, "c", "showLegendKey", {"val": "0"})
    _sub(parent, "c", "showVal", {"val": show_val})
    _sub(parent, "c", "showCatName", {"val": show_cat})
    _sub(parent, "c", "showSerName", {"val": "0"})
    _sub(parent, "c", "showPercent", {"val": "0"})
    _sub(parent, "c", "showBubbleSize", {"val": "0"})


def _series_name_from_xml(series) -> str:
    direct_value = series.find("c:tx/c:v", OOXML_NS)
    if direct_value is not None and direct_value.text:
        return direct_value.text.strip()
    cached_value = series.find("c:tx/c:strRef/c:strCache/c:pt/c:v", OOXML_NS)
    if cached_value is not None and cached_value.text:
        return cached_value.text.strip()
    return series.findtext("c:tx/c:strRef/c:f", default="", namespaces=OOXML_NS).strip()


def _series_cfg_for_xml_series(series, series_index: int, series_definitions: list[dict]):
    series_name = _series_name_from_xml(series)
    for cfg in series_definitions:
        if series_name == cfg["name"]:
            return cfg
    if 0 <= series_index < len(series_definitions):
        return series_definitions[series_index]
    return None


def _build_data_labels_xml(label_indices_by_time: dict, series_cfg: dict):
    dlabels = ET.Element(_qn("c", "dLbls"))
    series_name = series_cfg["name"]
    layouts_by_time = OOXML_DATALABEL_LAYOUTS_BY_SERIES.get(series_name, {})

    for target_time in series_cfg["annotation_times"]:
        idx = label_indices_by_time.get(target_time)
        if idx is None:
            continue
        layout_cfg = layouts_by_time.get(target_time, {"x": "0", "y": "0"})
        dlabel = _sub(dlabels, "c", "dLbl")
        _sub(dlabel, "c", "idx", {"val": str(idx)})
        manual_layout = _sub(_sub(dlabel, "c", "layout"), "c", "manualLayout")
        _sub(manual_layout, "c", "x", {"val": layout_cfg["x"]})
        _sub(manual_layout, "c", "y", {"val": layout_cfg["y"]})
        _add_show_flags(dlabel, show_val="1", show_cat="1")
        ext_list = _sub(dlabel, "c", "extLst")
        _sub(ext_list, "c", "ext", {"uri": "{CE6537A1-D6FC-4f65-9D91-7224C49458BB}"})
        ext = _sub(ext_list, "c", "ext", {"uri": "{C3380CC4-5D6E-409C-BE32-E72D297353CC}"})
        _sub(ext, "c16", "uniqueId", {"val": "{" + str(uuid.uuid4()).upper() + "}"})

    sp_pr = _sub(dlabels, "c", "spPr")
    solid_fill = _sub(sp_pr, "a", "solidFill")
    _sub(solid_fill, "a", "sysClr", {"val": "window", "lastClr": "FFFFFF"})
    line = _sub(sp_pr, "a", "ln")
    line_fill = _sub(line, "a", "solidFill")
    sys_clr = _sub(line_fill, "a", "sysClr", {"val": "windowText", "lastClr": "000000"})
    _sub(sys_clr, "a", "lumMod", {"val": "25000"})
    _sub(sys_clr, "a", "lumOff", {"val": "75000"})
    _sub(sp_pr, "a", "effectLst")

    insets = OOXML_DATALABEL_BODY_INSETS_BY_SERIES.get(series_name, {"lIns": "36576", "tIns": "18288", "rIns": "36576", "bIns": "18288"})
    tx_pr = _sub(dlabels, "c", "txPr")
    body_pr = _sub(
        tx_pr,
        "a",
        "bodyPr",
        {
            "rot": "0",
            "spcFirstLastPara": "1",
            "vertOverflow": "clip",
            "horzOverflow": "clip",
            "vert": "horz",
            "wrap": "square",
            "lIns": insets["lIns"],
            "tIns": insets["tIns"],
            "rIns": insets["rIns"],
            "bIns": insets["bIns"],
            "anchor": "ctr",
            "anchorCtr": "1",
        },
    )
    _sub(body_pr, "a", "spAutoFit")
    _sub(tx_pr, "a", "lstStyle")
    paragraph = _sub(tx_pr, "a", "p")
    def_r_pr = _sub(
        _sub(paragraph, "a", "pPr"),
        "a",
        "defRPr",
        {
            "sz": "1800",
            "b": "1",
            "i": "0",
            "u": "none",
            "strike": "noStrike",
            "kern": "1200",
            "baseline": "0",
        },
    )
    font_fill = _sub(def_r_pr, "a", "solidFill")
    scheme_clr = _sub(font_fill, "a", "schemeClr", {"val": "dk1"})
    _sub(scheme_clr, "a", "lumMod", {"val": "65000"})
    _sub(scheme_clr, "a", "lumOff", {"val": "35000"})
    _sub(def_r_pr, "a", "latin", {"typeface": "Calibri Light", "panose": "020F0302020204030204", "pitchFamily": "34", "charset": "0"})
    _sub(def_r_pr, "a", "ea", {"typeface": "+mn-ea"})
    _sub(def_r_pr, "a", "cs", {"typeface": "Calibri Light", "panose": "020F0302020204030204", "pitchFamily": "34", "charset": "0"})
    _sub(paragraph, "a", "endParaRPr", {"lang": "en-US"})
    _add_show_flags(dlabels, show_val="0", show_cat="0")

    ext_list = _sub(dlabels, "c", "extLst")
    ext = _sub(ext_list, "c", "ext", {"uri": "{CE6537A1-D6FC-4f65-9D91-7224C49458BB}"})
    c15_sp_pr = _sub(ext, "c15", "spPr")
    prst_geom = _sub(c15_sp_pr, "a", "prstGeom", {"prst": "wedgeRectCallout"})
    _sub(prst_geom, "a", "avLst")
    _sub(c15_sp_pr, "a", "noFill")
    c15_line = _sub(c15_sp_pr, "a", "ln")
    _sub(c15_line, "a", "noFill")
    _sub(ext, "c15", "showLeaderLines", {"val": "0"})
    return dlabels


def _remove_existing_dlabels(series):
    for child in list(series):
        if child.tag == _qn("c", "dLbls"):
            series.remove(child)


def _insert_dlabels(series, dlabels):
    children = list(series)
    insert_pos = len(children)
    for idx, child in enumerate(children):
        if child.tag in {_qn("c", "xVal"), _qn("c", "yVal"), _qn("c", "smooth")}:
            insert_pos = idx
            break
    series.insert(insert_pos, dlabels)


def _patch_chart_xml(chart_xml: bytes, series_definitions: list[dict]):
    root = ET.fromstring(chart_xml)
    patched_count = 0
    for series_index, series in enumerate(root.findall(".//c:scatterChart/c:ser", OOXML_NS)):
        series_cfg = _series_cfg_for_xml_series(series, series_index, series_definitions)
        if series_cfg is None:
            continue
        x_values = _series_x_values_by_index(series)
        label_indices_by_time = {}
        for target_time in series_cfg["annotation_times"]:
            idx, _actual_time, _error = _nearest_x_index(x_values, target_time)
            if idx is not None:
                label_indices_by_time[target_time] = idx
        if not label_indices_by_time:
            continue
        _remove_existing_dlabels(series)
        _insert_dlabels(series, _build_data_labels_xml(label_indices_by_time, series_cfg))
        patched_count += 1
    if patched_count == 0:
        return chart_xml, 0
    return ET.tostring(root, encoding="utf-8", xml_declaration=True), patched_count


def _patch_workbook_native_data_labels(xlsx_path: Path, series_definitions: list[dict]) -> None:
    temp_path = xlsx_path.with_name(xlsx_path.stem + "__tmp_ooxml_patch" + xlsx_path.suffix)
    total_patched = 0
    with zipfile.ZipFile(xlsx_path, "r") as zin, zipfile.ZipFile(temp_path, "w", compression=zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename.startswith("xl/charts/chart") and item.filename.endswith(".xml"):
                data, patched_count = _patch_chart_xml(data, series_definitions)
                total_patched += patched_count
            zout.writestr(item, data)
    temp_path.replace(xlsx_path)
    if total_patched == 0:
        raise RuntimeError(f"No chart XML series were patched in {xlsx_path.name}.")
