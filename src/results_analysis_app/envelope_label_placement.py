"""Place envelope-chart labels after Excel has rendered the chart.

Excel owns the final chart geometry, so this pass runs through the COM object
model after the workbook has been patched with the requested labels. LL labels
are kept above the LL trace, with the first LL label reserved at the highest
valid vertical position. Each LG label is first placed in the gap below the LL
trace and above the LG trace; when that complete label box does not fit, it is
placed below the LG trace. Labels keep their data-point anchors and original X
positions whenever a vertical position is available. A left-first horizontal
fallback is used only when no vertical position exists. A second vertical-only
pass repairs connector lines that cross another label box, moving the
obstructed label at its existing X while the total conflict count improves. If
no safe position can be found, the native Excel position is retained.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Any, Callable


LABEL_MARGIN_POINTS = 5.0
SEARCH_STEP_POINTS = 1.0
GEOMETRY_TOLERANCE_POINTS = 0.25
XL_LABEL_POSITION_CUSTOM = 7
MAX_NEAREST_TIME_ERROR = 0.001
MAX_LEADER_REPAIR_PASSES = 24


@dataclass(frozen=True)
class Point:
    x: float
    y: float


@dataclass(frozen=True)
class Segment:
    start: Point
    end: Point


@dataclass
class LabelBox:
    series_index: int
    point_index: int
    text: str
    excel_label: Any
    left: float
    top: float
    width: float
    height: float
    anchor: Point | None = None
    preferred_side: str | None = None


@dataclass
class ChartGeometry:
    plot_left: float
    plot_top: float
    plot_right: float
    plot_bottom: float
    segments: list[Segment]
    labels: list[LabelBox]
    reserved_boxes: tuple[tuple[float, float, float, float], ...]


@dataclass(frozen=True)
class PlacementResult:
    moved: int = 0
    unchanged: int = 0
    retained_after_failure: int = 0


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _sequence(value: Any) -> list[Any]:
    if value is None or isinstance(value, (str, bytes)):
        return [] if value is None else [value]
    try:
        return list(value)
    except TypeError:
        return [value]


def _axis(chart: Any, axis_type: int) -> Any | None:
    try:
        return chart.Axes(axis_type, 1)
    except Exception:
        return None


def _axis_bounds(axis: Any) -> tuple[float, float, bool] | None:
    if axis is None:
        return None
    minimum = _finite(axis.MinimumScale)
    maximum = _finite(axis.MaximumScale)
    if minimum is None or maximum is None or maximum <= minimum:
        return None
    try:
        reverse = bool(axis.ReversePlotOrder)
    except Exception:
        reverse = False
    return minimum, maximum, reverse


def _screen_points(
    chart: Any,
    series: Any,
    plot: tuple[float, float, float, float],
) -> list[Point | None]:
    try:
        x_values = _sequence(series.XValues)
        y_values = _sequence(series.Values)
    except Exception:
        return []
    x_bounds = _axis_bounds(_axis(chart, 1))
    y_bounds = _axis_bounds(_axis(chart, 2))
    if x_bounds is None or y_bounds is None:
        return []
    x_min, x_max, x_reverse = x_bounds
    y_min, y_max, y_reverse = y_bounds
    plot_left, plot_top, plot_width, plot_height = plot
    points: list[Point | None] = []
    for x_raw, y_raw in zip(x_values, y_values):
        x_value = _finite(x_raw)
        y_value = _finite(y_raw)
        if x_value is None or y_value is None:
            points.append(None)
            continue
        x_fraction = (x_value - x_min) / (x_max - x_min)
        if x_reverse:
            x_fraction = 1.0 - x_fraction
        y_fraction = (y_value - y_min) / (y_max - y_min)
        y_fraction = y_fraction if y_reverse else 1.0 - y_fraction
        points.append(
            Point(
                plot_left + x_fraction * plot_width,
                plot_top + y_fraction * plot_height,
            )
        )
    return points


def _points_to_segments(points: list[Point | None]) -> list[Segment]:
    segments: list[Segment] = []
    previous: Point | None = None
    for point in points:
        if point is None:
            previous = None
            continue
        if previous is None:
            segments.append(Segment(point, point))
        else:
            segments.append(Segment(previous, point))
        previous = point
    return segments


def _object_box(obj: Any) -> tuple[float, float, float, float] | None:
    try:
        left = _finite(obj.Left)
        top = _finite(obj.Top)
        width = _finite(obj.Width)
        height = _finite(obj.Height)
    except Exception:
        return None
    if None in (left, top, width, height) or width <= 0 or height <= 0:
        return None
    return left, top, left + width, top + height


def _reserved_boxes(chart: Any) -> tuple[tuple[float, float, float, float], ...]:
    boxes: list[tuple[float, float, float, float]] = []
    for attribute in ("ChartTitle", "Legend"):
        try:
            if attribute == "ChartTitle" and not bool(chart.HasTitle):
                continue
            if attribute == "Legend" and not bool(chart.HasLegend):
                continue
            box = _object_box(getattr(chart, attribute))
        except Exception:
            box = None
        if box is not None:
            boxes.append(box)
    return tuple(boxes)


def _nearest_point_index(x_values: list[Any], target_time: float) -> int | None:
    best_index: int | None = None
    best_error: float | None = None
    for index, value in enumerate(x_values):
        number = _finite(value)
        if number is None:
            continue
        error = abs(number - target_time)
        if best_error is None or error < best_error:
            best_index = index
            best_error = error
    if best_index is None or best_error is None or best_error > MAX_NEAREST_TIME_ERROR:
        return None
    return best_index


def _labels_for_series(
    series: Any,
    series_index: int,
    annotation_times: list[float],
    *,
    anchor_points: list[Point | None] | None = None,
    preferred_side: str | None = None,
) -> list[LabelBox]:
    try:
        x_values = _sequence(series.XValues)
        data_labels = series.DataLabels()
    except Exception:
        return []
    labels: list[LabelBox] = []
    seen_indices: set[int] = set()
    for target_time in annotation_times:
        point_index = _nearest_point_index(x_values, float(target_time))
        if point_index is None or point_index in seen_indices:
            continue
        try:
            # OOXML uses zero-based point indexes; COM DataLabels.Item is
            # one-based. Only the configured points are read.
            label = data_labels.Item(point_index + 1)
            text = str(label.Text or "")
            left = _finite(label.Left)
            top = _finite(label.Top)
            width = _finite(label.Width)
            height = _finite(label.Height)
        except Exception:
            continue
        if not text.strip() or None in (left, top, width, height):
            continue
        if width <= 0 or height <= 0:
            continue
        labels.append(
            LabelBox(
                series_index,
                point_index,
                text,
                label,
                left,
                top,
                width,
                height,
                anchor_points[point_index]
                if anchor_points is not None and point_index < len(anchor_points)
                else None,
                preferred_side,
            )
        )
        seen_indices.add(point_index)
    return labels


def _chart_geometry(chart: Any, series_definitions: list[dict[str, Any]]) -> ChartGeometry | None:
    try:
        plot_area = chart.PlotArea
        plot = tuple(
            _finite(value)
            for value in (
                plot_area.InsideLeft,
                plot_area.InsideTop,
                plot_area.InsideWidth,
                plot_area.InsideHeight,
            )
        )
    except Exception:
        return None
    if any(value is None for value in plot) or plot[2] <= 0 or plot[3] <= 0:
        return None
    plot_values = (float(plot[0]), float(plot[1]), float(plot[2]), float(plot[3]))
    try:
        series_count = int(chart.SeriesCollection().Count)
    except Exception:
        return None

    segments: list[Segment] = []
    labels: list[LabelBox] = []
    for series_index in range(1, series_count + 1):
        try:
            series = chart.SeriesCollection().Item(series_index)
        except Exception:
            continue
        points = _screen_points(chart, series, plot_values)
        segments.extend(_points_to_segments(points))
        if series_index <= len(series_definitions):
            series_cfg = series_definitions[series_index - 1]
            annotation_times = [float(value) for value in series_cfg.get("annotation_times", [])]
            labels.extend(
                _labels_for_series(
                    series,
                    series_index,
                    annotation_times,
                    anchor_points=points,
                    preferred_side=series_cfg.get("preferred_label_side"),
                )
            )

    return ChartGeometry(
        plot_left=plot_values[0],
        plot_top=plot_values[1],
        plot_right=plot_values[0] + plot_values[2],
        plot_bottom=plot_values[1] + plot_values[3],
        segments=segments,
        labels=labels,
        reserved_boxes=_reserved_boxes(chart),
    )


def segment_intersects_box(
    segment: Segment,
    left: float,
    top: float,
    right: float,
    bottom: float,
) -> bool:
    """Return whether a line segment enters a rectangle."""

    dx = segment.end.x - segment.start.x
    dy = segment.end.y - segment.start.y
    coefficients = (-dx, dx, -dy, dy)
    values = (
        segment.start.x - left,
        right - segment.start.x,
        segment.start.y - top,
        bottom - segment.start.y,
    )
    lower, upper = 0.0, 1.0
    for coefficient, value in zip(coefficients, values):
        if abs(coefficient) <= 1e-12:
            if value < 0:
                return False
            continue
        ratio = value / coefficient
        if coefficient < 0:
            if ratio > upper:
                return False
            lower = max(lower, ratio)
        else:
            if ratio < lower:
                return False
            upper = min(upper, ratio)
    return lower <= upper + 1e-12


def _leader_segment(
    label: LabelBox,
    left: float,
    top: float,
) -> Segment | None:
    """Approximate Excel's straight leader line for a label position."""

    if label.anchor is None:
        return None
    right = left + label.width
    bottom = top + label.height
    anchor = label.anchor
    if left <= anchor.x <= right and top <= anchor.y <= bottom:
        distances = (
            (abs(anchor.x - left), Point(left, anchor.y)),
            (abs(right - anchor.x), Point(right, anchor.y)),
            (abs(anchor.y - top), Point(anchor.x, top)),
            (abs(bottom - anchor.y), Point(anchor.x, bottom)),
        )
        endpoint = min(distances, key=lambda item: item[0])[1]
    else:
        endpoint = Point(
            min(max(anchor.x, left), right),
            min(max(anchor.y, top), bottom),
        )
    if math.hypot(endpoint.x - anchor.x, endpoint.y - anchor.y) <= 1e-9:
        return None
    return Segment(anchor, endpoint)


def _leader_segments(
    geometry: ChartGeometry,
    positions: dict[int, tuple[float, float]],
) -> dict[int, Segment]:
    segments: dict[int, Segment] = {}
    for label in geometry.labels:
        left, top = positions.get(id(label), (label.left, label.top))
        segment = _leader_segment(label, left, top)
        if segment is not None:
            segments[id(label)] = segment
    return segments


def _leader_conflicts(
    geometry: ChartGeometry,
    positions: dict[int, tuple[float, float]],
) -> list[tuple[LabelBox, LabelBox | None, str]]:
    """Return connector lines that cross another label box."""

    margin = LABEL_MARGIN_POINTS + GEOMETRY_TOLERANCE_POINTS
    segments = _leader_segments(geometry, positions)
    conflicts: list[tuple[LabelBox, LabelBox | None, str]] = []
    for source in geometry.labels:
        segment = segments.get(id(source))
        if segment is None:
            continue
        for target in geometry.labels:
            if target is source:
                continue
            target_left, target_top = positions.get(
                id(target),
                (target.left, target.top),
            )
            if segment_intersects_box(
                segment,
                target_left - margin,
                target_top - margin,
                target_left + target.width + margin,
                target_top + target.height + margin,
            ):
                conflicts.append((source, target, "leader-label"))
    return conflicts


def rectangles_overlap(
    first_left: float,
    first_top: float,
    first_width: float,
    first_height: float,
    second_left: float,
    second_top: float,
    second_width: float,
    second_height: float,
    margin: float,
) -> bool:
    margin += GEOMETRY_TOLERANCE_POINTS
    return not (
        first_left + first_width + margin <= second_left
        or second_left + second_width + margin <= first_left
        or first_top + first_height + margin <= second_top
        or second_top + second_height + margin <= first_top
    )


def _label_inside_plot(geometry: ChartGeometry, label: LabelBox, left: float, top: float) -> bool:
    margin = LABEL_MARGIN_POINTS
    tolerance = GEOMETRY_TOLERANCE_POINTS
    return (
        left >= geometry.plot_left + margin - tolerance
        and left + label.width <= geometry.plot_right - margin + tolerance
        and top >= geometry.plot_top + margin - tolerance
        and top + label.height <= geometry.plot_bottom - margin + tolerance
    )


def _label_overlaps_data(
    geometry: ChartGeometry,
    label: LabelBox,
    left: float,
    top: float,
) -> bool:
    margin = LABEL_MARGIN_POINTS + GEOMETRY_TOLERANCE_POINTS
    box = (
        left - margin,
        top - margin,
        left + label.width + margin,
        top + label.height + margin,
    )
    return any(segment_intersects_box(segment, *box) for segment in geometry.segments)


def _label_side_valid(label: LabelBox, top: float, side: str | None) -> bool:
    if label.anchor is None or side not in {"above", "below"}:
        return True
    margin = LABEL_MARGIN_POINTS + GEOMETRY_TOLERANCE_POINTS
    if side == "above":
        return top + label.height <= label.anchor.y - margin
    return top >= label.anchor.y + margin


def _position_issues(
    geometry: ChartGeometry,
    label: LabelBox,
    left: float,
    top: float,
    positions: dict[int, tuple[float, float]],
) -> tuple[str, ...]:
    issues: list[str] = []
    if not _label_inside_plot(geometry, label, left, top):
        issues.append("plot edge")
    if _label_overlaps_data(geometry, label, left, top):
        issues.append("trace")
    for box_left, box_top, box_right, box_bottom in geometry.reserved_boxes:
        if rectangles_overlap(
            left,
            top,
            label.width,
            label.height,
            box_left,
            box_top,
            box_right - box_left,
            box_bottom - box_top,
            LABEL_MARGIN_POINTS,
        ):
            issues.append("chart object")
            break
    for other in geometry.labels:
        if other is label:
            continue
        other_left, other_top = positions.get(id(other), (other.left, other.top))
        if rectangles_overlap(
            left,
            top,
            label.width,
            label.height,
            other_left,
            other_top,
            other.width,
            other.height,
            LABEL_MARGIN_POINTS,
        ):
            issues.append("another label")
            break
    return tuple(issues)


def _position_issues_without_other_labels(
    geometry: ChartGeometry,
    label: LabelBox,
    left: float,
    top: float,
    positions: dict[int, tuple[float, float]],
) -> tuple[str, ...]:
    """Return geometry issues while allowing other labels to move later."""

    return tuple(
        issue
        for issue in _position_issues(geometry, label, left, top, positions)
        if issue != "another label"
    )


def _trace_y_values(
    points: list[Point | None],
    left: float,
    right: float,
) -> tuple[float, ...]:
    """Return trace Y values across a label's horizontal span."""

    values: list[float] = []
    for segment in _points_to_segments(points):
        values.extend(_segment_y_values(segment, left, right))
    return tuple(values)


def _segment_y_values(segment: Segment, left: float, right: float) -> tuple[float, ...]:
    x1, y1 = segment.start.x, segment.start.y
    x2, y2 = segment.end.x, segment.end.y
    if max(x1, x2) < left or min(x1, x2) > right:
        return ()
    if abs(x2 - x1) <= 1e-12:
        return y1, y2
    clipped_left = max(min(x1, x2), left)
    clipped_right = min(max(x1, x2), right)

    def y_at(x_value: float) -> float:
        return y1 + ((x_value - x1) / (x2 - x1)) * (y2 - y1)

    return y_at(clipped_left), y_at(clipped_right)


def _unique(values: list[float], minimum: float, maximum: float) -> list[float]:
    result: list[float] = []
    for value in values:
        if not math.isfinite(value) or value < minimum - 0.1 or value > maximum + 0.1:
            continue
        value = min(max(value, minimum), maximum)
        if not any(abs(value - existing) <= 0.1 for existing in result):
            result.append(value)
    return result


def _vertical_candidates(
    geometry: ChartGeometry,
    label: LabelBox,
    left: float,
    current_top: float,
    positions: dict[int, tuple[float, float]],
    side: str | None = None,
) -> list[float]:
    minimum = geometry.plot_top + LABEL_MARGIN_POINTS
    maximum = geometry.plot_bottom - LABEL_MARGIN_POINTS - label.height
    if minimum > maximum:
        return []

    values: list[float] = [minimum, maximum, current_top]
    horizontal_left = left - LABEL_MARGIN_POINTS
    horizontal_right = left + label.width + LABEL_MARGIN_POINTS
    for segment in geometry.segments:
        for y_value in _segment_y_values(segment, horizontal_left, horizontal_right):
            values.extend(
                (
                    y_value - LABEL_MARGIN_POINTS - label.height,
                    y_value + LABEL_MARGIN_POINTS,
                )
            )
    for other in geometry.labels:
        if other is label:
            continue
        other_left, other_top = positions.get(id(other), (other.left, other.top))
        if left + label.width + LABEL_MARGIN_POINTS < other_left:
            continue
        if left > other_left + other.width + LABEL_MARGIN_POINTS:
            continue
        values.extend(
            (
                other_top - LABEL_MARGIN_POINTS - label.height,
                other_top + other.height + LABEL_MARGIN_POINTS,
            )
        )
    for box_left, box_top, box_right, box_bottom in geometry.reserved_boxes:
        if left + label.width + LABEL_MARGIN_POINTS < box_left:
            continue
        if left > box_right + LABEL_MARGIN_POINTS:
            continue
        values.extend(
            (
                box_top - LABEL_MARGIN_POINTS - label.height,
                box_bottom + LABEL_MARGIN_POINTS,
            )
        )

    maximum_distance = max(abs(current_top - minimum), abs(maximum - current_top))
    steps = int(math.ceil(maximum_distance / SEARCH_STEP_POINTS)) + 1
    for step in range(1, steps + 1):
        distance = step * SEARCH_STEP_POINTS
        values.extend((current_top - distance, current_top + distance))

    candidates = [
        value
        for value in _unique(values, minimum, maximum)
        if _label_side_valid(label, value, side)
    ]
    if side in {"above", "below"} and label.anchor is not None:
        if side == "above":
            candidates.sort(
                key=lambda value: (
                    abs(label.anchor.y - (value + label.height)),
                    abs(value - current_top),
                    value,
                )
            )
        else:
            candidates.sort(
                key=lambda value: (
                    abs(value - label.anchor.y),
                    abs(value - current_top),
                    value,
                )
            )
        return candidates
    # At equal distances, the upward candidate is selected first.
    candidates.sort(key=lambda value: (abs(value - current_top), 0 if value < current_top else 1, value))
    return candidates


def _find_vertical_position(
    geometry: ChartGeometry,
    label: LabelBox,
    left: float,
    positions: dict[int, tuple[float, float]],
    side: str | None = None,
) -> tuple[float, float] | None:
    current_top = positions.get(id(label), (label.left, label.top))[1]
    for top in _vertical_candidates(geometry, label, left, current_top, positions, side):
        if not _position_issues(geometry, label, left, top, positions):
            return left, top
    return None


def _horizontal_candidates(
    geometry: ChartGeometry,
    label: LabelBox,
    current_left: float,
    direction: int,
) -> list[float]:
    minimum = geometry.plot_left + LABEL_MARGIN_POINTS
    maximum = geometry.plot_right - LABEL_MARGIN_POINTS - label.width
    if minimum > maximum:
        return []
    maximum_distance = max(abs(current_left - minimum), abs(maximum - current_left))
    steps = int(math.ceil(maximum_distance / SEARCH_STEP_POINTS)) + 1
    values = [current_left + direction * step * SEARCH_STEP_POINTS for step in range(1, steps + 1)]
    values.extend((minimum, maximum))
    values = _unique(values, minimum, maximum)
    values.sort(key=lambda value: abs(value - current_left))
    return values


def _first_ll_label(geometry: ChartGeometry) -> LabelBox | None:
    """Return the leftmost/earliest LL annotation in the rendered chart."""

    labels = [label for label in geometry.labels if label.series_index == 1]
    if not labels:
        return None
    return min(
        labels,
        key=lambda label: (
            label.anchor.x if label.anchor is not None else math.inf,
            label.point_index,
        ),
    )


def _reserve_first_ll_label(
    geometry: ChartGeometry,
    positions: dict[int, tuple[float, float]],
) -> tuple[LabelBox | None, bool]:
    """Put the first LL label at the highest safe Y and reserve it."""

    label = _first_ll_label(geometry)
    if label is None:
        return None, False
    left, current_top = positions[id(label)]
    candidates = _vertical_candidates(
        geometry,
        label,
        left,
        current_top,
        positions,
        None,
    )
    valid = [
        top
        for top in candidates
        if not _position_issues_without_other_labels(
            geometry,
            label,
            left,
            top,
            positions,
        )
    ]
    if not valid:
        return label, False
    target = min(valid)
    if abs(target - current_top) <= GEOMETRY_TOLERANCE_POINTS:
        return label, False
    applied = _apply_position(label, left, target)
    if applied is None:
        return label, False
    positions[id(label)] = applied
    return label, True


def _lg_position_ranges(
    geometry: ChartGeometry,
    label: LabelBox,
    candidate_left: float,
    points_by_series: dict[int, list[Point | None]],
) -> tuple[tuple[str, float, float], ...]:
    """Return the allowed vertical ranges for an LG label at one X position."""

    ll_points = points_by_series.get(1, [])
    lg_points = points_by_series.get(2, [])
    point_index = label.point_index
    if (
        point_index >= len(ll_points)
        or point_index >= len(lg_points)
        or ll_points[point_index] is None
        or lg_points[point_index] is None
    ):
        return ()

    margin = LABEL_MARGIN_POINTS + GEOMETRY_TOLERANCE_POINTS
    right = candidate_left + label.width
    ll_values = _trace_y_values(
        ll_points,
        candidate_left - margin,
        right + margin,
    )
    lg_values = _trace_y_values(
        lg_points,
        candidate_left - margin,
        right + margin,
    )
    ll_anchor = ll_points[point_index]
    lg_anchor = lg_points[point_index]
    if ll_anchor is None or lg_anchor is None:
        return ()
    ll_lower = max(ll_values) + margin if ll_values else ll_anchor.y + margin
    lg_upper = (
        min(lg_values) - margin - label.height
        if lg_values
        else lg_anchor.y - margin - label.height
    )
    lg_lower = max(lg_values) + margin if lg_values else lg_anchor.y + margin
    plot_maximum = geometry.plot_bottom - margin - label.height
    ranges: list[tuple[str, float, float]] = []
    if ll_lower <= lg_upper:
        ranges.append(("between", ll_lower, lg_upper))
    if lg_lower <= plot_maximum:
        ranges.append(("below-lg", lg_lower, plot_maximum))
    return tuple(ranges)


def _lg_position_valid(
    geometry: ChartGeometry,
    label: LabelBox,
    left: float,
    top: float,
    points_by_series: dict[int, list[Point | None]],
) -> bool:
    """Check that an LG label obeys the LL/LG trace hierarchy."""

    return any(
        minimum - GEOMETRY_TOLERANCE_POINTS <= top <= maximum + GEOMETRY_TOLERANCE_POINTS
        for _kind, minimum, maximum in _lg_position_ranges(
            geometry,
            label,
            left,
            points_by_series,
        )
    )


def _find_lg_position(
    geometry: ChartGeometry,
    label: LabelBox,
    positions: dict[int, tuple[float, float]],
    points_by_series: dict[int, list[Point | None]],
) -> tuple[tuple[float, float] | None, str]:
    """Find an LG position below LL and, when needed, below LG."""

    current_left, current_top = positions.get(id(label), (label.left, label.top))

    if (
        not _position_issues(geometry, label, current_left, current_top, positions)
        and _lg_position_valid(
            geometry,
            label,
            current_left,
            current_top,
            points_by_series,
        )
    ):
        return None, "valid"

    def search_at(left: float) -> tuple[tuple[float, float] | None, str]:
        for kind, minimum, maximum in _lg_position_ranges(
            geometry,
            label,
            left,
            points_by_series,
        ):
            for top in _vertical_candidates(
                geometry,
                label,
                left,
                current_top,
                positions,
                None,
            ):
                if top < minimum - GEOMETRY_TOLERANCE_POINTS:
                    continue
                if top > maximum + GEOMETRY_TOLERANCE_POINTS:
                    continue
                if _position_issues(geometry, label, left, top, positions):
                    continue
                return (left, top), kind
        return None, "no valid position"

    position, kind = search_at(current_left)
    if position is not None:
        return position, f"vertical-{kind}"

    for direction, reason in ((-1, "left"), (1, "right")):
        for left in _horizontal_candidates(geometry, label, current_left, direction):
            position, kind = search_at(left)
            if position is not None:
                return position, f"{reason}-{kind}"
    return None, "no valid position"


def _vertical_repair_candidates(
    geometry: ChartGeometry,
    label: LabelBox,
    positions: dict[int, tuple[float, float]],
    points_by_series: dict[int, list[Point | None]],
) -> list[tuple[float, float]]:
    """Return same-X candidates ordered for connector-conflict repair."""

    current_left, current_top = positions.get(id(label), (label.left, label.top))
    preferred_side = label.preferred_side if label.anchor is not None else None
    if preferred_side is None and label.anchor is not None and label.series_index == 1:
        preferred_side = "above"

    candidates: list[tuple[int, float]] = []
    if label.series_index == 2 and {1, 2}.issubset(points_by_series):
        side_values = (None,)
    elif preferred_side is None:
        side_values = (None,)
    else:
        opposite_side = "below" if preferred_side == "above" else "above"
        side_values = (preferred_side, opposite_side)

    for side_index, side in enumerate(side_values):
        for top in _vertical_candidates(
            geometry,
            label,
            current_left,
            current_top,
            positions,
            side,
        ):
            if abs(top - current_top) <= GEOMETRY_TOLERANCE_POINTS:
                continue
            if _position_issues(geometry, label, current_left, top, positions):
                continue
            if (
                label.series_index == 2
                and {1, 2}.issubset(points_by_series)
                and not _lg_position_valid(
                    geometry,
                    label,
                    current_left,
                    top,
                    points_by_series,
                )
            ):
                continue
            candidates.append((side_index, top))

    def sort_key(item: tuple[int, float]) -> tuple[int, int, float, float]:
        side_index, top = item
        delta = top - current_top
        if label.series_index == 2:
            # Screen Y increases downwards.  LG repairs therefore try the
            # downward position first, as requested, while retaining the
            # same X and the existing trace hierarchy.
            direction = 0 if delta > 0 else 1
        elif preferred_side == "above":
            direction = 0 if delta < 0 else 1
        elif preferred_side == "below":
            direction = 0 if delta > 0 else 1
        else:
            direction = 0
        return side_index, direction, abs(delta), top

    candidates.sort(key=sort_key)
    result: list[tuple[float, float]] = []
    seen: set[tuple[float, float]] = set()
    for _side_index, top in candidates:
        key = (current_left, top)
        if key in seen:
            continue
        seen.add(key)
        result.append(key)
    return result


def _plan_leader_line_repairs(
    geometry: ChartGeometry,
    positions: dict[int, tuple[float, float]],
    points_by_series: dict[int, list[Point | None]],
    *,
    protect_first_ll: bool = True,
) -> list[tuple[LabelBox, float, float, str]]:
    """Plan vertical-only repairs for leader-line collisions.

    The label boxes are kept at their existing X positions.  A label whose
    box is crossed by another leader line is tried before the source label,
    which makes the common ``second LG line crosses first LG label`` case
    move the first LG label down when that is the smallest valid repair.
    """

    working = dict(positions)
    planned: list[tuple[LabelBox, float, float, str]] = []
    protected = _first_ll_label(geometry) if protect_first_ll else None
    pass_limit = min(
        MAX_LEADER_REPAIR_PASSES,
        max(1, len(geometry.labels) * 3),
    )

    for _pass_index in range(pass_limit):
        conflicts = _leader_conflicts(geometry, working)
        if not conflicts:
            break
        current_score = len(conflicts)
        participant_priority: dict[int, tuple[int, int, LabelBox]] = {}
        for conflict_index, (source, target, _kind) in enumerate(conflicts):
            # Resolve the obstructed label first.  If it cannot move, the
            # label whose line causes the collision is considered next.
            for priority, label in enumerate((target, source)):
                if label is None:
                    continue
                key = id(label)
                candidate = (priority, conflict_index, label)
                previous = participant_priority.get(key)
                if previous is None or candidate[:2] < previous[:2]:
                    participant_priority[key] = candidate

        candidates_to_try = sorted(
            participant_priority.values(),
            key=lambda item: (item[0], item[1], item[2].series_index, item[2].point_index),
        )
        best: tuple[tuple[int, int, float, int, int, int], LabelBox, float, float, str] | None = None
        for priority, conflict_index, label in candidates_to_try:
            if label is protected:
                continue
            current_left, current_top = working.get(
                id(label),
                (label.left, label.top),
            )
            vertical_candidates = _vertical_repair_candidates(
                geometry,
                label,
                working,
                points_by_series,
            )
            for candidate_index, (left, top) in enumerate(vertical_candidates):
                trial = dict(working)
                trial[id(label)] = (left, top)
                score = len(_leader_conflicts(geometry, trial))
                if score >= current_score:
                    continue
                delta = top - current_top
                direction = 0 if label.series_index == 2 and delta > 0 else 1
                rank = (
                    score,
                    priority,
                    abs(delta),
                    direction,
                    conflict_index,
                    candidate_index,
                )
                if best is None or rank < best[0]:
                    best = (
                        rank,
                        label,
                        left,
                        top,
                        "vertical leader-line repair",
                    )
        if best is None:
            break
        _rank, label, left, top, reason = best
        working[id(label)] = (left, top)
        planned.append((label, left, top, reason))

    return planned


def find_new_position(
    geometry: ChartGeometry,
    label: LabelBox,
    positions: dict[int, tuple[float, float]],
) -> tuple[tuple[float, float] | None, str]:
    current_left, current_top = positions.get(id(label), (label.left, label.top))
    current_issues = _position_issues(geometry, label, current_left, current_top, positions)
    preferred_side = label.preferred_side if label.anchor is not None else None
    if preferred_side is None and label.anchor is not None and label.series_index == 1:
        preferred_side = "above"
    if not current_issues and (
        preferred_side is None or _label_side_valid(label, current_top, preferred_side)
    ):
        return None, "valid"

    sides = (None,)
    if preferred_side is not None:
        opposite_side = "below" if preferred_side == "above" else "above"
        sides = (preferred_side, opposite_side)
    for side in sides:
        vertical = _find_vertical_position(geometry, label, current_left, positions, side)
        if vertical is not None:
            if vertical == (current_left, current_top) and not current_issues:
                return None, "valid"
            return vertical, f"vertical-{side}" if side is not None else "vertical"

    # Horizontal movement is the last resort. Search left before right and
    # repeat the same vertical search at each candidate X.
    for direction, reason in ((-1, "left"), (1, "right")):
        for left in _horizontal_candidates(geometry, label, current_left, direction):
            for side in sides:
                vertical = _find_vertical_position(geometry, label, left, positions, side)
                if vertical is not None:
                    if vertical == (current_left, current_top) and not current_issues:
                        return None, "valid"
                    return vertical, reason
    return None, "no valid position"


def _move_priority(
    geometry: ChartGeometry,
    label: LabelBox,
    positions: dict[int, tuple[float, float]],
) -> tuple[int, int, float, int, int]:
    issues = _position_issues(geometry, label, label.left, label.top, positions)
    hard_issues = sum(issue != "another label" for issue in issues)
    return (
        -hard_issues,
        -len(issues),
        -(label.width * label.height),
        label.series_index,
        label.point_index,
    )


def _apply_position(label: LabelBox, left: float, top: float) -> tuple[float, float] | None:
    old_left, old_top = label.left, label.top
    old_width, old_height = label.width, label.height
    try:
        try:
            if int(label.excel_label.Position) != XL_LABEL_POSITION_CUSTOM:
                label.excel_label.Position = XL_LABEL_POSITION_CUSTOM
        except Exception:
            pass
        label.excel_label.Left = left
        label.excel_label.Top = top
        actual_left = _finite(label.excel_label.Left)
        actual_top = _finite(label.excel_label.Top)
        actual_width = _finite(label.excel_label.Width)
        actual_height = _finite(label.excel_label.Height)
    except Exception:
        try:
            label.excel_label.Left = old_left
            label.excel_label.Top = old_top
        except Exception:
            pass
        return None
    if None in (actual_left, actual_top, actual_width, actual_height):
        return None
    if (
        abs(actual_width - old_width) > GEOMETRY_TOLERANCE_POINTS
        or abs(actual_height - old_height) > GEOMETRY_TOLERANCE_POINTS
    ):
        try:
            label.excel_label.Left = old_left
            label.excel_label.Top = old_top
        except Exception:
            pass
        return None
    label.left = actual_left
    label.top = actual_top
    label.width = actual_width
    label.height = actual_height
    return actual_left, actual_top


def _find_chart_object(sheet: Any) -> Any | None:
    try:
        chart_objects = sheet.ChartObjects()
        for index in range(1, int(chart_objects.Count) + 1):
            chart_object = chart_objects.Item(index)
            if str(chart_object.Name) == "Representative_Overvoltage_Envelope":
                return chart_object
    except Exception:
        return None
    return None


def move_envelope_labels(
    excel: Any,
    workbook_path: Path,
    series_definitions: list[dict[str, Any]],
    log: Callable[[str], None] | None = None,
) -> PlacementResult:
    """Move labels in an already-patched workbook using Excel geometry."""

    workbook = excel.Workbooks.Open(
        str(Path(workbook_path).resolve()),
        UpdateLinks=0,
        ReadOnly=False,
    )
    moved = 0
    unchanged = 0
    retained = 0
    try:
        sheet = None
        for candidate in workbook.Worksheets:
            if str(candidate.Name).strip().casefold() == "llp":
                sheet = candidate
                break
        if sheet is None:
            return PlacementResult()
        chart_object = _find_chart_object(sheet)
        if chart_object is None:
            return PlacementResult()
        chart = chart_object.Chart
        try:
            chart.Refresh()
        except Exception:
            pass
        geometry = _chart_geometry(chart, series_definitions)
        if geometry is None or not geometry.labels:
            return PlacementResult()

        positions = {id(label): (label.left, label.top) for label in geometry.labels}
        points_by_series: dict[int, list[Point | None]] = {}
        try:
            series_collection = chart.SeriesCollection()
            plot = (
                geometry.plot_left,
                geometry.plot_top,
                geometry.plot_right - geometry.plot_left,
                geometry.plot_bottom - geometry.plot_top,
            )
            for series_index in range(1, int(series_collection.Count) + 1):
                points_by_series[series_index] = _screen_points(
                    chart,
                    series_collection.Item(series_index),
                    plot,
                )
        except Exception:
            points_by_series = {}

        first_ll, first_ll_moved = _reserve_first_ll_label(geometry, positions)
        moved = int(first_ll_moved)
        unchanged = int(first_ll is not None and not first_ll_moved)
        labels = sorted(
            (label for label in geometry.labels if label is not first_ll),
            key=lambda label: _move_priority(geometry, label, positions),
        )
        for label in labels:
            if label.series_index == 2 and {1, 2}.issubset(points_by_series):
                new_position, reason = _find_lg_position(
                    geometry,
                    label,
                    positions,
                    points_by_series,
                )
            else:
                new_position, reason = find_new_position(geometry, label, positions)
            if reason == "valid":
                unchanged += 1
                continue
            if new_position is None:
                retained += 1
                if log is not None:
                    log(
                        f"Envelope label retained at original position: "
                        f"series={label.series_index}, point={label.point_index}, text={label.text}"
                    )
                continue
            old_position = positions[id(label)]
            applied = _apply_position(label, *new_position)
            if applied is None:
                retained += 1
                if log is not None:
                    log(
                        f"Envelope label could not be moved and was retained: "
                        f"series={label.series_index}, point={label.point_index}, text={label.text}"
                    )
                continue
            actual_left, actual_top = applied
            trial_positions = dict(positions)
            trial_positions[id(label)] = (actual_left, actual_top)
            if _position_issues(geometry, label, actual_left, actual_top, trial_positions) or (
                label.series_index == 2
                and {1, 2}.issubset(points_by_series)
                and not _lg_position_valid(
                    geometry,
                    label,
                    actual_left,
                    actual_top,
                    points_by_series,
                )
            ):
                _apply_position(label, *old_position)
                label.left, label.top = old_position
                retained += 1
                if log is not None:
                    log(
                        f"Envelope label move failed validation and was retained: "
                        f"series={label.series_index}, point={label.point_index}, text={label.text}"
                    )
                continue
            positions[id(label)] = (actual_left, actual_top)
            moved += 1
            if log is not None:
                log(
                    f"Envelope label moved {reason}: series={label.series_index}, "
                    f"point={label.point_index}, text={label.text}"
                )
        first_ll_protected = False
        if first_ll is not None:
            first_ll_left, first_ll_top = positions[id(first_ll)]
            first_ll_protected = not _position_issues(
                geometry,
                first_ll,
                first_ll_left,
                first_ll_top,
                positions,
            ) and _label_side_valid(first_ll, first_ll_top, "above")
        repairs = _plan_leader_line_repairs(
            geometry,
            positions,
            points_by_series,
            protect_first_ll=first_ll_protected,
        )
        for label, left, top, reason in repairs:
            old_position = positions[id(label)]
            applied = _apply_position(label, left, top)
            if applied is None:
                if log is not None:
                    log(
                        f"Envelope leader-line repair could not be applied: "
                        f"series={label.series_index}, point={label.point_index}, text={label.text}"
                    )
                continue
            actual_left, actual_top = applied
            trial_positions = dict(positions)
            trial_positions[id(label)] = (actual_left, actual_top)
            invalid = _position_issues(
                geometry,
                label,
                actual_left,
                actual_top,
                trial_positions,
            )
            if (
                invalid
                or (
                    label.series_index == 2
                    and {1, 2}.issubset(points_by_series)
                    and not _lg_position_valid(
                        geometry,
                        label,
                        actual_left,
                        actual_top,
                        points_by_series,
                    )
                )
            ):
                _apply_position(label, *old_position)
                label.left, label.top = old_position
                if log is not None:
                    log(
                        f"Envelope leader-line repair failed validation and was retained: "
                        f"series={label.series_index}, point={label.point_index}, text={label.text}"
                    )
                continue
            positions[id(label)] = (actual_left, actual_top)
            moved += 1
            if log is not None:
                log(
                    f"Envelope label moved {reason}: series={label.series_index}, "
                    f"point={label.point_index}, text={label.text}"
                )
        remaining_leader_conflicts = _leader_conflicts(geometry, positions)
        if remaining_leader_conflicts and log is not None:
            log(
                "Envelope leader-line conflicts remaining after vertical repair: "
                f"{len(remaining_leader_conflicts)}"
            )
        if moved:
            workbook.Save()
        return PlacementResult(moved, unchanged, retained)
    finally:
        try:
            workbook.Close(SaveChanges=False)
        except Exception:
            pass
