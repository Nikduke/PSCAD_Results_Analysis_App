from __future__ import annotations


def _label(
    *,
    left: float,
    top: float,
    width: float = 10.0,
    height: float = 10.0,
    anchor=None,
    preferred_side=None,
    series_index: int = 1,
    point_index: int = 0,
):
    from results_analysis_app.envelope_label_placement import LabelBox

    return LabelBox(
        series_index,
        point_index,
        "label",
        None,
        left,
        top,
        width,
        height,
        anchor,
        preferred_side,
    )


def test_segment_intersection_detects_trace_crossing_label_box() -> None:
    from results_analysis_app.envelope_label_placement import Point, Segment, segment_intersects_box

    diagonal = Segment(Point(0.0, 0.0), Point(10.0, 10.0))
    outside = Segment(Point(0.0, 0.0), Point(3.0, 3.0))

    assert segment_intersects_box(diagonal, 4.0, 4.0, 6.0, 6.0)
    assert not segment_intersects_box(outside, 4.0, 4.0, 6.0, 6.0)


def test_find_new_position_uses_nearest_upward_slot_first() -> None:
    from results_analysis_app.envelope_label_placement import (
        ChartGeometry,
        Point,
        Segment,
        find_new_position,
    )

    label = _label(left=45.0, top=45.0)
    geometry = ChartGeometry(
        0.0,
        0.0,
        100.0,
        100.0,
        [Segment(Point(0.0, 50.0), Point(100.0, 50.0))],
        [label],
        (),
    )

    position, reason = find_new_position(geometry, label, {id(label): (label.left, label.top)})

    assert reason == "vertical"
    assert position == (45.0, 34.0)


def test_find_new_position_avoids_another_label_and_can_move_down() -> None:
    from results_analysis_app.envelope_label_placement import (
        ChartGeometry,
        Point,
        Segment,
        find_new_position,
    )

    label = _label(left=45.0, top=45.0)
    other = _label(left=45.0, top=30.0)
    geometry = ChartGeometry(
        0.0,
        0.0,
        100.0,
        100.0,
        [Segment(Point(0.0, 50.0), Point(100.0, 50.0))],
        [label, other],
        (),
    )
    positions = {id(label): (label.left, label.top), id(other): (other.left, other.top)}

    position, reason = find_new_position(geometry, label, positions)

    assert reason == "vertical"
    assert position == (45.0, 56.0)


def test_find_new_position_retains_label_when_plot_has_no_safe_slot() -> None:
    from results_analysis_app.envelope_label_placement import (
        ChartGeometry,
        Point,
        Segment,
        find_new_position,
    )

    label = _label(left=5.0, top=5.0, width=10.0, height=10.0)
    geometry = ChartGeometry(
        0.0,
        0.0,
        20.0,
        20.0,
        [Segment(Point(0.0, 10.0), Point(20.0, 10.0))],
        [label],
        (),
    )

    position, reason = find_new_position(geometry, label, {id(label): (label.left, label.top)})

    assert position is None
    assert reason == "no valid position"


def test_find_new_position_prefers_above_original_data_point() -> None:
    from results_analysis_app.envelope_label_placement import (
        ChartGeometry,
        Point,
        Segment,
        find_new_position,
    )

    label = _label(
        left=45.0,
        top=55.0,
        anchor=Point(50.0, 50.0),
        preferred_side="above",
    )
    geometry = ChartGeometry(
        0.0,
        0.0,
        100.0,
        100.0,
        [Segment(Point(0.0, 50.0), Point(100.0, 50.0))],
        [label],
        (),
    )

    position, reason = find_new_position(geometry, label, {id(label): (label.left, label.top)})

    assert reason == "vertical-above"
    assert position == (45.0, 34.0)
    assert label.anchor == Point(50.0, 50.0)


def test_find_new_position_falls_below_when_above_has_no_space() -> None:
    from results_analysis_app.envelope_label_placement import (
        ChartGeometry,
        Point,
        Segment,
        find_new_position,
    )

    label = _label(
        left=5.0,
        top=5.0,
        anchor=Point(10.0, 2.0),
        preferred_side="above",
    )
    geometry = ChartGeometry(
        0.0,
        0.0,
        30.0,
        30.0,
        [Segment(Point(0.0, 2.0), Point(30.0, 2.0))],
        [label],
        (),
    )

    position, reason = find_new_position(geometry, label, {id(label): (label.left, label.top)})

    assert reason == "vertical-below"
    assert position is not None
    assert position[1] > label.anchor.y


def test_ll_labels_default_to_the_above_side() -> None:
    from results_analysis_app.envelope_label_placement import (
        ChartGeometry,
        Point,
        Segment,
        find_new_position,
    )

    label = _label(left=45.0, top=55.0, anchor=Point(50.0, 50.0))
    geometry = ChartGeometry(
        0.0,
        0.0,
        100.0,
        100.0,
        [Segment(Point(0.0, 50.0), Point(100.0, 50.0))],
        [label],
        (),
    )

    position, reason = find_new_position(geometry, label, {id(label): (label.left, label.top)})

    assert reason == "vertical-above"
    assert position == (45.0, 34.0)


def test_lg_gap_is_checked_across_the_complete_label_width() -> None:
    from results_analysis_app.envelope_label_placement import (
        ChartGeometry,
        Point,
        _lg_position_ranges,
        _lg_position_valid,
    )

    label = _label(
        left=45.0,
        top=30.0,
        width=20.0,
        height=10.0,
        anchor=Point(50.0, 80.0),
        series_index=2,
        point_index=1,
    )
    geometry = ChartGeometry(0.0, 0.0, 100.0, 100.0, [], [label], ())
    points = {
        1: [Point(0.0, 20.0), Point(40.0, 30.0), Point(100.0, 60.0)],
        2: [Point(0.0, 80.0), Point(40.0, 80.0), Point(100.0, 80.0)],
    }

    ranges = _lg_position_ranges(geometry, label, label.left, points)

    assert ranges[0][0] == "between"
    assert _lg_position_valid(geometry, label, label.left, 52.0, points)
    assert not _lg_position_valid(geometry, label, label.left, 30.0, points)


def test_lg_uses_below_trace_when_the_gap_cannot_fit_the_label() -> None:
    from results_analysis_app.envelope_label_placement import (
        ChartGeometry,
        Point,
        _lg_position_ranges,
    )

    label = _label(
        left=45.0,
        top=30.0,
        width=20.0,
        height=20.0,
        anchor=Point(50.0, 50.0),
        series_index=2,
        point_index=1,
    )
    geometry = ChartGeometry(0.0, 0.0, 100.0, 100.0, [], [label], ())
    points = {
        1: [Point(0.0, 40.0), Point(40.0, 40.0), Point(100.0, 40.0)],
        2: [Point(0.0, 55.0), Point(40.0, 55.0), Point(100.0, 55.0)],
    }

    ranges = _lg_position_ranges(geometry, label, label.left, points)

    assert [kind for kind, _minimum, _maximum in ranges] == ["below-lg"]


def test_leader_repair_moves_obstructed_label_down_without_horizontal_shift() -> None:
    from results_analysis_app.envelope_label_placement import (
        ChartGeometry,
        LabelBox,
        Point,
        _leader_conflicts,
        _plan_leader_line_repairs,
    )

    obstructed = LabelBox(
        2,
        2,
        "first LG",
        None,
        70.0,
        90.0,
        30.0,
        20.0,
        None,
        None,
    )
    source = LabelBox(
        2,
        15,
        "second LG",
        None,
        140.0,
        20.0,
        30.0,
        20.0,
        Point(20.0, 150.0),
        None,
    )
    geometry = ChartGeometry(
        0.0,
        0.0,
        220.0,
        220.0,
        [],
        [obstructed, source],
        (),
    )
    positions = {
        id(obstructed): (obstructed.left, obstructed.top),
        id(source): (source.left, source.top),
    }

    assert len(_leader_conflicts(geometry, positions)) == 1
    repairs = _plan_leader_line_repairs(geometry, positions, {})

    assert repairs
    repaired_label, repaired_left, repaired_top, _reason = repairs[0]
    assert repaired_label is obstructed
    assert repaired_left == obstructed.left
    assert repaired_top > obstructed.top
    positions[id(repaired_label)] = (repaired_left, repaired_top)
    assert not _leader_conflicts(geometry, positions)


def test_leader_repair_skips_valid_first_ll_label() -> None:
    from results_analysis_app.envelope_label_placement import (
        ChartGeometry,
        LabelBox,
        Point,
        _plan_leader_line_repairs,
    )

    first_ll = LabelBox(
        1,
        2,
        "first LL",
        None,
        70.0,
        90.0,
        30.0,
        20.0,
        Point(20.0, 60.0),
        "above",
    )
    source = LabelBox(
        2,
        15,
        "second LG",
        None,
        140.0,
        20.0,
        30.0,
        20.0,
        Point(20.0, 150.0),
        None,
    )
    geometry = ChartGeometry(
        0.0,
        0.0,
        220.0,
        220.0,
        [],
        [first_ll, source],
        (),
    )
    positions = {
        id(first_ll): (first_ll.left, first_ll.top),
        id(source): (source.left, source.top),
    }

    repairs = _plan_leader_line_repairs(
        geometry,
        positions,
        {},
        protect_first_ll=True,
    )

    assert repairs
    assert all(label is not first_ll for label, _left, _top, _reason in repairs)
