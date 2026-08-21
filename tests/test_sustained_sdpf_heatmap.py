from __future__ import annotations


def _cycle_spikes(peaks: list[float], frequency: float = 60.0):
    import numpy as np

    period = 1.0 / frequency
    time = np.arange(0.0, (len(peaks) + 2) * period, 0.0001)
    waveform = np.zeros_like(time)
    for cycle, peak in enumerate(peaks):
        sample_time = (cycle + 0.5) * period
        waveform[np.argmin(np.abs(time - sample_time))] = peak
    return time, waveform


def _phase(*, margin: float, actual: float, duration: float = 0.03):
    from results_analysis_app.sustained_sdpf import PhaseStressResult

    return PhaseStressResult(
        "LGp", "A-G", 1.0, 2**0.5, 0.85, 0.85 * 2**0.5,
        margin, actual, 1.0, 1.0 / 2**0.5, 1.0 / 2**0.5,
        "SDPF safety margin exceeded" if margin else "No sustained TOV",
        margin_exceeded=margin >= duration,
        sdpf_exceeded=actual >= duration,
    )


def _result(case: str, run: int, mm: str, *, margin: float, actual: float, fault: str = "AG"):
    from results_analysis_app.sustained_sdpf import SustainedSDPFResult

    phase = _phase(margin=margin, actual=actual)
    return SustainedSDPFResult("Full", "66", case, run, mm, fault, 0.03, phase, (phase,))


def test_heatmap_counts_one_run_mm_and_inclusive_margin() -> None:
    from results_analysis_app.sustained_sdpf_heatmap import aggregate_observations

    first = _result("O2_P1_S1", 1, "MM_66_A", margin=0.04, actual=0.04)
    second_phase = _phase(margin=0.04, actual=0.02)
    from dataclasses import replace
    second = replace(first, run=2, phases=(second_phase, second_phase), governing=second_phase)
    layout = aggregate_observations([first, second])
    cell = layout.cell("AG", "O2_P1_S1", None)
    assert cell.eligible_count == 2
    assert cell.actual_count == 1
    assert cell.margin_count == 2
    assert cell.actual_percent <= cell.margin_percent


def test_heatmap_counts_only_duration_qualified_peak_events() -> None:
    import numpy as np

    from results_analysis_app.sustained_sdpf import analyze_phase_amplitude, classify_rows
    from results_analysis_app.sustained_sdpf_heatmap import aggregate_observations

    time = np.arange(0.0, 0.2, 0.0001)
    amplitude = np.where((time >= 0.005) & (time < 0.1), 1.3, 0.0)
    phase = analyze_phase_amplitude(time, amplitude, "LLp", "B-C", 1.0, 0.03, 60.0)
    result = classify_rows("Full", "66", "O2_P1_S1", 1, "MM_66_A", [phase], 0.03, "AG", cycle_coverage=2)

    assert result is not None
    cell = aggregate_observations([result]).cell("AG", "O2_P1_S1", None)
    assert result.governing.longest_margin_s >= result.duration_s
    assert cell.actual_count == 0
    assert cell.margin_count == 1


def test_heatmap_merges_lgp_llp_duplicates_instead_of_dropping_llp() -> None:
    from dataclasses import replace

    from results_analysis_app.sustained_sdpf_heatmap import aggregate_observations

    lg_phase = _phase(margin=0.0, actual=0.0)
    ll_phase = replace(
        lg_phase,
        measurement="LLp",
        sustained_ratio=0.90,
        longest_margin_s=0.08,
        classification="SDPF safety margin exceeded; SDPF not exceeded for at least 30 ms of peak-envelope persistence (peak)",
        margin_exceeded=True,
    )
    first = _result("O2_P1_S1", 1, "MM_66_A", margin=0.0, actual=0.0)
    second = replace(first, governing=ll_phase, phases=(ll_phase,))

    cell = aggregate_observations([first, second]).cell("AG", "O2_P1_S1", None)

    assert cell.eligible_count == 1
    assert cell.actual_count == 0
    assert cell.margin_count == 1


def test_heatmap_does_not_recover_a_finding_from_legacy_classification() -> None:
    from dataclasses import replace

    from results_analysis_app.sustained_sdpf_heatmap import aggregate_observations

    phase = replace(
        _phase(margin=0.0, actual=0.0),
        classification="SDPF safety margin exceeded; SDPF not exceeded for at least 30 ms of peak-envelope persistence (peak)",
    )
    result = _result("O2_P1_S1", 1, "MM_66_A", margin=0.0, actual=0.0)
    result = replace(result, governing=phase, phases=())
    cell = aggregate_observations([result]).cell("AG", "O2_P1_S1", None)

    assert cell.actual_count == 0
    assert cell.margin_count == 0


def test_heatmap_does_not_use_sustained_ratio_as_a_finding_fallback() -> None:
    from dataclasses import replace

    from results_analysis_app.sustained_sdpf_heatmap import aggregate_observations

    phase = replace(_phase(margin=0.0, actual=0.0), sustained_ratio=0.90)
    result = _result("O2_P1_S1", 1, "MM_66_A", margin=0.0, actual=0.0)
    result = replace(result, governing=phase, phases=(phase,))
    cell = aggregate_observations([result]).cell("AG", "O2_P1_S1", None)

    assert cell.actual_count == 0
    assert cell.margin_count == 0


def test_heatmap_does_not_use_subduration_ratio_for_current_no_candidate() -> None:
    from dataclasses import replace

    from results_analysis_app.sustained_sdpf_heatmap import aggregate_observations

    phase = replace(
        _phase(margin=0.0, actual=0.0),
        sustained_ratio=0.90,
        classification="No sustained SDPF safety-margin exceedance for at least 30 ms of peak-envelope persistence (peak)",
    )
    result = _result("O2_P1_S1", 1, "MM_66_A", margin=0.0, actual=0.0)
    result = replace(result, governing=phase, phases=(phase,))

    cell = aggregate_observations([result]).cell("AG", "O2_P1_S1", None)

    assert cell.actual_count == 0
    assert cell.margin_count == 0


def test_heatmap_settings_default_and_case_split_limit() -> None:
    from results_analysis_app.sustained_sdpf_heatmap import HeatmapSettings, _should_combine_panels

    defaults = HeatmapSettings.from_mapping(None)
    assert defaults.max_cases_per_heatmap == 12
    assert defaults.layout == "separate"
    assert defaults.max_panels_per_heatmap == 4
    assert HeatmapSettings.from_mapping({"max_cases": 0}).max_cases_per_heatmap == 1
    assert HeatmapSettings.from_mapping({"max_cases_per_heatmap": 1000}).max_cases_per_heatmap == 500
    combined = HeatmapSettings.from_mapping({"layout": "combined", "max_panels": 99})
    assert combined.layout == "combined"
    assert combined.max_panels_per_heatmap == 12
    automatic = HeatmapSettings(layout="auto", max_panels_per_heatmap=4)
    assert _should_combine_panels(automatic, 4)
    assert not _should_combine_panels(automatic, 5)


def test_heatmap_case_labels_are_center_anchored() -> None:
    import matplotlib

    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt

    from results_analysis_app.sustained_sdpf_heatmap import (
        HeatmapSettings,
        _draw_heatmap_panel,
        aggregate_observations,
    )

    layout = aggregate_observations(
        [_result("O2_P1_S1_LONG_CASE_NAME", 1, "MM_66_A", margin=0.04, actual=0.04)],
        HeatmapSettings(),
    )
    figure, axis = plt.subplots()
    _draw_heatmap_panel(axis, layout, None)

    assert axis.get_xticklabels()[0].get_ha() == "center"
    assert axis.get_xticklabels()[0].get_rotation_mode() == "anchor"
    plt.close(figure)


def test_heatmap_keeps_report_governing_result_when_observation_list_is_partial(tmp_path) -> None:
    from results_analysis_app import sustained_sdpf, sustained_sdpf_heatmap

    result = _result("O2_P1_S1", 1, "MM_66_A", margin=0.04, actual=0.0)
    source = tmp_path / "Input_Data.xlsx"
    source.write_text("source", encoding="utf-8")
    stat = source.stat()
    settings = sustained_sdpf.SustainedSDPFSettings(enabled=True, duration_ms=30.0)
    sustained_sdpf.save_results(
        tmp_path,
        "Full",
        settings,
        {"66": result},
        signature_inputs={"66": {"files": [{"path": str(source), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}]}},
        observations_by_voltage={"66": []},
    )

    images = sustained_sdpf_heatmap.generate_heatmaps(tmp_path, "Full", "66", None, settings)

    assert len(images) == 1


def test_heatmap_uses_metadata_for_no_eligible_cells_and_split_values() -> None:
    from results_analysis_app.sustained_sdpf_heatmap import (
        HeatmapSettings,
        aggregate_observations,
        metadata_from_cases,
        cell_severity,
    )

    results = [_result("O2_P1_S1_RA0", 1, "MM_66_A", margin=0.0, actual=0.0)]
    metadata = metadata_from_cases(
        ["O2_P1_S1_RA0", "O2_P1_S2_RA0", "O2_P1_S3_RA0"],
        {("O2_P1_S1_RA0", 1): "AG"},
    )
    settings = HeatmapSettings(y_grouping="Fault type", split_by="S")
    layout = aggregate_observations(results, settings, metadata)
    assert layout.split_values == ("1", "2", "3")
    assert "O2_P1_S2_RA0" in layout.cases
    empty = layout.cell("AG", "O2_P1_S2_RA0", "2")
    assert empty.eligible_count == 0
    assert cell_severity(empty) == "none"


def test_split_keeps_only_cases_with_the_selected_split_value() -> None:
    from results_analysis_app.sustained_sdpf_heatmap import (
        HeatmapSettings,
        _columns_for_split,
        aggregate_observations,
        metadata_from_cases,
    )

    cases = ["O2_P1_S1_RA0", "O2_P1_S2_RA0", "O2_P1_S3_RA0"]
    result = _result(cases[0], 1, "MM_66_A", margin=0.0, actual=0.0)
    layout = aggregate_observations(
        [result],
        HeatmapSettings(y_grouping="Fault type", split_by="S"),
        metadata_from_cases(cases, {(cases[0], 1): "AG"}),
    )

    assert _columns_for_split(layout, "1") == [cases[0]]
    assert _columns_for_split(layout, "2") == [cases[1]]
    assert _columns_for_split(layout, "3") == [cases[2]]


def test_heatmap_grouping_defaults_and_conflicts() -> None:
    from results_analysis_app.sustained_sdpf_heatmap import (
        HeatmapSettings,
        NONE_GROUPING,
        metadata_from_cases,
    )

    with_faults = metadata_from_cases(["O2_P1_S1", "O2_P2_S1"], {("o2_p1_s1", 1): "AG"})
    assert HeatmapSettings().normalized(with_faults).y_grouping == "Fault type"
    without_faults = metadata_from_cases(["O2_P1_S1", "O2_P2_S1"])
    assert without_faults.default_y == "P"
    assert "Fault type" not in without_faults.y_options
    assert "MM element" in without_faults.y_options
    assert HeatmapSettings().normalized(without_faults).y_grouping == "P"
    normalized = HeatmapSettings(y_grouping="P", x_grouping="P", split_by="P").normalized(without_faults)
    assert normalized.x_grouping is None
    assert normalized.split_by is None
    assert HeatmapSettings(y_grouping=NONE_GROUPING).normalized(with_faults).y_grouping == NONE_GROUPING


def test_default_heatmap_set_name_follows_fault_availability() -> None:
    from results_analysis_app.sustained_sdpf_heatmap import (
        default_heatmap_set_name,
        metadata_from_cases,
        migrate_legacy_default_heatmap_set,
        HeatmapSet,
        HeatmapSettings,
    )

    with_faults = metadata_from_cases(["O2_P1_S1"], {("O2_P1_S1", 1): "AG"})
    without_faults = metadata_from_cases(["O2_P1_S1", "O2_P2_S1"])
    assert default_heatmap_set_name(with_faults) == "Faults"
    assert default_heatmap_set_name(without_faults) == "Cases by P"
    migrated = migrate_legacy_default_heatmap_set(
        HeatmapSet("Faults", HeatmapSettings(y_grouping="MM element")),
        without_faults,
    )
    assert migrated.name == "Cases by P"
    assert migrated.settings.y_grouping == "P"
    unchanged = HeatmapSet("Custom", HeatmapSettings(y_grouping="MM element"))
    assert migrate_legacy_default_heatmap_set(unchanged, without_faults) == unchanged


def test_heatmap_x_grouping_orders_but_does_not_aggregate() -> None:
    from results_analysis_app.sustained_sdpf_heatmap import HeatmapSettings, aggregate_observations

    results = [
        _result("O2_P1_S2", 1, "MM_66_A", margin=0.0, actual=0.0),
        _result("O2_P1_S1", 1, "MM_66_A", margin=0.0, actual=0.0),
    ]
    layout = aggregate_observations(results, HeatmapSettings(y_grouping="All", x_grouping="S"))
    assert layout.cases == ("O2_P1_S1", "O2_P1_S2")
    assert len(layout.cells) == 2


def test_combined_heatmap_width_uses_the_widest_panel_only() -> None:
    from results_analysis_app.sustained_sdpf_heatmap import (
        _faceted_figure_width,
        _heatmap_figure_width,
    )

    labels = tuple(f"V{index}" for index in range(12))

    assert _faceted_figure_width((labels, labels)) == _heatmap_figure_width(labels)


def test_heatmap_x_group_token_is_not_repeated_in_case_labels() -> None:
    from results_analysis_app.sustained_sdpf_heatmap import (
        HeatmapObservation,
        HeatmapSettings,
        _case_display_labels,
        aggregate_observations,
        metadata_from_cases,
    )

    cases = [
        "C23_S1_V1_TT9_TC9_A2_POC",
        "C23_S1_V1_TT9_TC9_A2_VSR",
        "C23_S1_V3_TT9_TC9_A2_POC",
        "C25_S1_V1_TT9_TC9_A2_POC",
        "C25_S1_V1_TT9_TC9_A2_VSR",
        "C25_S1_V2_TT9_TC5_A2_POC",
    ]
    observations = [
        HeatmapObservation(case, 1, "MM_230_A", "AG", False, False)
        for case in cases
    ]
    metadata = metadata_from_cases(
        cases,
        {(case, 1): "AG" for case in cases},
    )
    layout = aggregate_observations(
        observations,
        HeatmapSettings(y_grouping="Fault type", x_grouping="C", split_by="S"),
        metadata,
    )

    labels = _case_display_labels(layout, layout.cases)

    assert labels == (
        "V1_TC9_POC",
        "V1_TC9_VSR",
        "V3_TC9_POC",
        "V1_TC9_POC",
        "V1_TC9_VSR",
        "V2_TC5_POC",
    )
    assert [layout.x_groups[case] for case in layout.cases] == [
        "C23", "C23", "C23", "C25", "C25", "C25"
    ]


def test_heatmap_titles_prioritize_split_and_x_group_context() -> None:
    import matplotlib

    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt

    from results_analysis_app.sustained_sdpf_heatmap import (
        HeatmapObservation,
        HeatmapSettings,
        _HeatmapPanelSpec,
        _draw_heatmap_panel,
        _draw_x_group_band,
        _panel_title,
        aggregate_observations,
        metadata_from_cases,
    )

    cases = [
        "C23_S1_V1_POC",
        "C25_S1_V1_POC",
        "C23_S3_V1_POC",
    ]
    observations = [
        HeatmapObservation(case, 1, "MM_230_A", "AG", False, False)
        for case in cases
    ]
    metadata = metadata_from_cases(
        cases,
        {(case, 1): "AG" for case in cases},
    )
    layout = aggregate_observations(
        observations,
        HeatmapSettings(y_grouping="Fault type", x_grouping="C", split_by="S"),
        metadata,
    )
    spec = _HeatmapPanelSpec("1", tuple(layout.cases), part_index=1, part_count=3)

    assert _panel_title(layout, spec, include_split=True) == "Split: S1"
    assert _panel_title(layout, spec, include_split=False) == ""

    figure, axis = plt.subplots()
    _draw_heatmap_panel(axis, layout, "1")
    assert all("X group:" not in text.get_text() for text in axis.texts)
    assert axis.get_ylabel() == ""
    group_figure, group_axis = plt.subplots()
    _draw_x_group_band(group_axis, layout)
    group_texts = {text.get_text(): text for text in group_axis.texts}
    assert set(group_texts) == {"C23", "C25"}
    assert all(text.get_fontweight() == "bold" for text in group_texts.values())
    plt.close(figure)
    plt.close(group_figure)


def test_mm_heatmap_labels_stay_horizontal_without_a_competing_y_caption() -> None:
    import matplotlib

    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt

    from results_analysis_app.sustained_sdpf_heatmap import (
        HeatmapObservation,
        HeatmapSettings,
        MM_GROUPING,
        _draw_heatmap_panel,
        build_heatmap_layout,
        metadata_from_cases,
    )

    observations = [
        HeatmapObservation("C1_S1", 1, mm_name, "AG", False, False)
        for mm_name in ("MM_66_OSS1", "MM_230_ONC1", "MM_230_OFT1")
    ]
    metadata = metadata_from_cases(
        [observation.case for observation in observations],
        {(observation.case, observation.run): observation.fault_type for observation in observations},
    )
    layout = build_heatmap_layout(
        observations,
        HeatmapSettings(y_grouping=MM_GROUPING),
        metadata,
    )

    figure, axis = plt.subplots()
    _draw_heatmap_panel(axis, layout, None)

    assert all(label.get_rotation() == 0 for label in axis.get_yticklabels())
    assert axis.get_ylabel() == ""
    plt.close(figure)


def test_mm_heatmap_set_name_is_human_readable() -> None:
    from results_analysis_app.sustained_sdpf_heatmap import (
        HeatmapSettings,
        MM_GROUPING,
        display_heatmap_set_name,
    )

    settings = HeatmapSettings(y_grouping=MM_GROUPING)

    assert display_heatmap_set_name("MM_HM", settings) == "MM elements"
    assert display_heatmap_set_name("Detailed MM view", settings) == "Detailed MM view"


def test_faceted_page_numbers_only_mark_true_continuations() -> None:
    from results_analysis_app.sustained_sdpf_heatmap import (
        _HeatmapPanelSpec,
        _faceted_page_number_required,
    )

    split_pages = tuple(
        (_HeatmapPanelSpec(split, (f"C_{split}",)),)
        for split in ("P0", "P1", "P2")
    )
    continuation_pages = (
        (_HeatmapPanelSpec("P0", ("C1",), 1, 2),),
        (_HeatmapPanelSpec("P0", ("C2",), 2, 2),),
    )
    unsplit_pages = (
        (_HeatmapPanelSpec(None, ("C1",), 1, 2),),
        (_HeatmapPanelSpec(None, ("C2",), 2, 2),),
    )

    assert not _faceted_page_number_required(split_pages)
    assert _faceted_page_number_required(continuation_pages)
    assert _faceted_page_number_required(unsplit_pages)


def test_generated_heatmap_views_cover_grouping_modes(tmp_path) -> None:
    """Render representative generated views without relying on a project fixture."""
    import matplotlib

    matplotlib.use("Agg", force=True)
    import matplotlib.image as mpimg

    from results_analysis_app.sustained_sdpf_heatmap import (
        HeatmapObservation,
        HeatmapSettings,
        _axis_tick_label,
        _heatmap_panel_specs,
        _layout_for_cases,
        _plot_faceted_layout,
        _plot_layout,
        _title_with_split,
        build_heatmap_layout,
        metadata_from_cases,
    )

    cases = [
        f"G{group}_S{split}_V{version}_TT9_MM_{group}"
        for group in (1, 2)
        for split in (1, 2)
        for version in (1, 2)
    ]
    observations = [
        HeatmapObservation(
            case,
            1,
            "MM_230_Very_Long_Element_Name" if case.startswith("G2_") else "MM_66_A",
            "Three phase to ground fault" if "_S1_" in case else "Line to line fault with long name",
            actual=case.startswith("G2_") and "_S2_" in case,
            margin="_S2_" in case,
        )
        for case in cases
    ]
    metadata = metadata_from_cases(
        cases,
        {(observation.case, observation.run): observation.fault_type for observation in observations},
    )
    views = (
        ("fault_combined", HeatmapSettings(y_grouping="Fault type", x_grouping="G", split_by="S", layout="combined")),
        ("mm_combined", HeatmapSettings(y_grouping="MM element", x_grouping="G", split_by="S", layout="combined")),
        ("token_y_combined", HeatmapSettings(y_grouping="V", x_grouping="G", split_by="S", layout="combined")),
        ("fault_separate", HeatmapSettings(y_grouping="Fault type", split_by="S", layout="separate")),
    )

    for name, settings in views:
        layout = build_heatmap_layout(observations, settings, metadata)
        specs = _heatmap_panel_specs(layout)
        assert specs
        if settings.layout == "combined":
            paths = [tmp_path / f"{name}.png"]
            _plot_faceted_layout(
                layout,
                specs,
                paths[0],
                _title_with_split("Generated heatmap", layout, [spec.split_value for spec in specs]),
                1,
                1,
            )
        else:
            paths = []
            for index, spec in enumerate(specs):
                path = tmp_path / f"{name}_{index}.png"
                part_layout = _layout_for_cases(layout, spec.cases)
                _plot_layout(
                    part_layout,
                    path,
                    _title_with_split("Generated heatmap", layout, [spec.split_value]),
                    spec.split_value,
                )
                paths.append(path)
        for path in paths:
            assert path.is_file()
            image = mpimg.imread(path)
            assert image.shape[0] > 400
            assert image.shape[1] > 600

    assert "\n" in _axis_tick_label("MM_230_Very_Long_Element_Name")
    assert "\n" in _axis_tick_label("Line to line fault with long name")


def test_combined_heatmap_repeats_y_group_labels_on_each_panel(tmp_path, monkeypatch) -> None:
    import results_analysis_app.sustained_sdpf_heatmap as heatmap

    observations = [
        heatmap.HeatmapObservation(
            f"C1_S{split}",
            1,
            "MM_66_A" if split == 1 else "MM_66_B",
            "AG",
            actual=False,
            margin=False,
        )
        for split in (1, 2)
    ]
    metadata = heatmap.metadata_from_cases(
        [observation.case for observation in observations],
        {(observation.case, observation.run): observation.fault_type for observation in observations},
    )
    layout = heatmap.build_heatmap_layout(
        observations,
        heatmap.HeatmapSettings(y_grouping="Fault type", split_by="S", layout="combined"),
        metadata,
    )
    specs = heatmap._heatmap_panel_specs(layout)
    calls = []
    original = heatmap._draw_heatmap_panel

    def record_draw(*args, **kwargs):
        calls.append(kwargs["show_y_labels"])
        return original(*args, **kwargs)

    monkeypatch.setattr(heatmap, "_draw_heatmap_panel", record_draw)
    heatmap._plot_faceted_layout(
        layout,
        specs,
        tmp_path / "combined.png",
        "Generated heatmap",
        1,
        1,
    )

    assert calls == [True, True]


def test_heatmap_split_normalizes_mixed_case_token_prefixes() -> None:
    from results_analysis_app.sustained_sdpf_heatmap import (
        HeatmapObservation,
        HeatmapSettings,
        _columns_for_split,
        aggregate_observations,
        metadata_from_cases,
    )

    cases = ["C22_S1_POC", "C22_S1_VSR"]
    observations = [
        HeatmapObservation(case, 1, "MM_66_A", "AG", False, False)
        for case in cases
    ]
    metadata = metadata_from_cases(
        cases,
        {(case, 1): "AG" for case in cases},
    )
    layout = aggregate_observations(
        observations,
        HeatmapSettings(y_grouping="Fault type", split_by="POC"),
        metadata,
    )

    assert layout.split_values == ("POC", "VSR")
    assert _columns_for_split(layout, "POC") == [cases[0]]
    assert _columns_for_split(layout, "VSR") == [cases[1]]
    assert metadata.token_labels["POC"] == "POC — POC, VSR"


def test_heatmap_cell_labels_show_top_and_bottom_percentages() -> None:
    from results_analysis_app.sustained_sdpf_heatmap import HeatmapCell, _heatmap_cell_label

    assert _heatmap_cell_label(HeatmapCell("All", "case", None, 10, 0, 0)) == "0%\n0%"
    assert _heatmap_cell_label(HeatmapCell("All", "case", None, 200, 1, 3)) == "<1%\n1.5%"
    assert _heatmap_cell_label(HeatmapCell("All", "case", None, 0, 0, 0)) == "—"


def test_long_case_tick_labels_wrap_without_truncation() -> None:
    from results_analysis_app.sustained_sdpf_heatmap import _case_tick_label

    short = "C1_P0_S1"
    long = "C99_P2_S4_V1_TT9_TC9_A2_ONT_A_VERY_LONG_CASE_NAME"
    assert _case_tick_label(short) == short
    wrapped = _case_tick_label(long)
    assert "\n" in wrapped
    assert all(len(line) <= 16 for line in wrapped.splitlines())
    assert "C99" in wrapped and "CASE" in wrapped and "NAME" in wrapped


def test_mm_grouping_aggregates_all_faults_per_case() -> None:
    from results_analysis_app.sustained_sdpf_heatmap import (
        HeatmapObservation,
        HeatmapSettings,
        aggregate_observations,
        MM_GROUPING,
        metadata_from_cases,
    )

    observations = [
        HeatmapObservation("O2_P1_S1", 1, "MM_A", "AG", True, True),
        HeatmapObservation("O2_P1_S1", 2, "MM_A", "AG", False, True),
        HeatmapObservation("O2_P2_S1", 1, "MM_A", "AG", False, False),
        HeatmapObservation("O2_P1_S1", 1, "MM_B", "AG", False, True),
        HeatmapObservation("O2_P2_S1", 1, "MM_B", "AG", False, False),
    ]
    metadata = metadata_from_cases(
        [observation.case for observation in observations],
        {(observation.case, observation.run): observation.fault_type for observation in observations},
    )

    layout = aggregate_observations(
        observations,
        HeatmapSettings(y_grouping=MM_GROUPING, x_grouping="P"),
        metadata,
    )

    assert layout.y_values == ("MM_A", "MM_B")
    assert layout.cases == ("O2_P1_S1", "O2_P2_S1")
    assert layout.cell("MM_A", "O2_P1_S1", None).eligible_count == 2
    assert layout.cell("MM_A", "O2_P1_S1", None).actual_count == 1
    assert layout.cell("MM_A", "O2_P1_S1", None).margin_count == 2
    assert layout.cell("MM_B", "O2_P1_S1", None).margin_only_count == 1


def test_non_fault_y_grouping_compacts_the_selected_token_into_rows() -> None:
    from results_analysis_app.sustained_sdpf_heatmap import (
        HeatmapSettings,
        aggregate_observations,
        metadata_from_cases,
    )

    cases = ["O2_P1_S1_RA0", "O2_P1_S2_RA0"]
    results = [
        _result(cases[0], 1, "MM_66_A", margin=0.0, actual=0.0),
        _result(cases[1], 1, "MM_66_A", margin=0.04, actual=0.04),
    ]
    layout = aggregate_observations(
        results,
        HeatmapSettings(y_grouping="S"),
        metadata_from_cases(cases),
    )

    assert layout.cases == ("O2_P1_RA0",)
    assert layout.cell("1", "O2_P1_RA0", None).eligible_count == 1
    assert layout.cell("2", "O2_P1_RA0", None).actual_count == 1


def test_heatmap_case_labels_remove_visible_context_without_truncating_identity() -> None:
    from results_analysis_app.sustained_sdpf_heatmap import (
        HeatmapSettings,
        _case_display_labels,
        aggregate_observations,
        metadata_from_cases,
    )

    cases = ["O2_P1_S1_230ONC", "O2_P1_S1_230ONS"]
    results = [
        _result(case, 1, "MM_66_A", margin=0.0, actual=0.0)
        for case in cases
    ]
    layout = aggregate_observations(
        results,
        HeatmapSettings(y_grouping="Fault type", x_grouping="S", split_by="P"),
        metadata_from_cases(cases, {(case, 1): "AG" for case in cases}),
    )

    assert _case_display_labels(layout, layout.cases) == ("230ONC", "230ONS")


def test_heatmap_severity_and_small_percentage_display() -> None:
    from results_analysis_app.sustained_sdpf_heatmap import (
        HeatmapCell,
        _severity_rgba,
        _text_color_for_background,
        cell_severity,
        format_incidence,
    )
    from matplotlib import colors

    assert format_incidence(1, 200) == "<1%"
    assert cell_severity(HeatmapCell("All", "C", None, 100, 1, 1)) == "actual"
    assert cell_severity(HeatmapCell("All", "C", None, 100, 0, 1)) == "margin"
    assert cell_severity(HeatmapCell("All", "C", None, 100, 0, 0)) == "clear"

    actual = _severity_rgba(
        HeatmapCell("All", "C", None, 100, 100, 100),
        actual_scale_max=100.0,
    )
    margin = _severity_rgba(
        HeatmapCell("All", "C", None, 100, 0, 100),
        margin_scale_max=100.0,
    )
    assert colors.to_hex(actual).upper() == "#8E1B2A"
    assert colors.to_hex(margin).upper() == "#C98200"
    assert _text_color_for_background(actual) == "#ffffff"
    assert _text_color_for_background(margin) == "#111827"


def test_heatmap_persists_complete_observations_and_renders_without_excel(tmp_path) -> None:
    from results_analysis_app import sustained_sdpf, sustained_sdpf_heatmap
    from results_analysis_app.sustained_sdpf import RESULT_VERSION

    result = _result("O2_P1_S1", 1, "MM_66_A", margin=0.04, actual=0.04)
    source = tmp_path / "Input_Data.xlsx"
    source.write_text("source", encoding="utf-8")
    stat = source.stat()
    settings = sustained_sdpf.SustainedSDPFSettings(enabled=True, duration_ms=30.0)
    sustained_sdpf.save_results(
        tmp_path,
        "Full",
        settings,
        {"66": result},
        signature_inputs={"66": {"files": [{"path": str(source), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}]}},
        observations_by_voltage={"66": [result]},
    )
    images = sustained_sdpf_heatmap.generate_heatmaps(tmp_path, "Full", "66", None, settings)
    assert len(images) == 1
    assert images[0].is_file()
    assert not list((tmp_path / "Voltage_envelope" / "Full").glob("*.xlsx"))

    import json

    payload = json.loads((tmp_path / "Voltage_envelope" / "Full" / "Sustained_SDpf.json").read_text())
    assert payload["version"] == RESULT_VERSION
    assert set(payload["observations"]["66"][0]) == {
        "case", "run", "mm_name", "fault_type", "actual", "margin",
    }


def test_combined_heatmap_layout_paginates_real_split_panels(tmp_path) -> None:
    from results_analysis_app import sustained_sdpf, sustained_sdpf_heatmap

    results = [
        _result(f"O2_P1_S{index}", 1, "MM_66_A", margin=index > 1, actual=index == 4)
        for index in range(1, 6)
    ]
    source = tmp_path / "Input_Data.xlsx"
    source.write_text("source", encoding="utf-8")
    stat = source.stat()
    sustained_settings = sustained_sdpf.SustainedSDPFSettings(
        enabled=True,
        duration_ms=30.0,
    )
    sustained_sdpf.save_results(
        tmp_path,
        "Full",
        sustained_settings,
        {"66": results[0]},
        signature_inputs={
            "66": {
                "files": [
                    {"path": str(source), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}
                ],
                "heatmap_case_names": [result.case for result in results],
            }
        },
        observations_by_voltage={"66": results},
    )

    images = sustained_sdpf_heatmap.generate_heatmaps(
        tmp_path,
        "Full",
        "66",
        sustained_sdpf_heatmap.HeatmapSettings(
            y_grouping="Fault type",
            split_by="S",
            max_cases_per_heatmap=12,
            layout="combined",
            max_panels_per_heatmap=2,
        ),
        sustained_settings,
    )

    assert [image.name for image in images] == [
        "MM_66_faceted_01_heatmap.png",
        "MM_66_faceted_02_heatmap.png",
        "MM_66_faceted_03_heatmap.png",
    ]
    assert all(image.is_file() for image in images)


def test_named_heatmap_sets_render_in_ordered_subfolders(tmp_path) -> None:
    from results_analysis_app import sustained_sdpf, sustained_sdpf_heatmap

    results = [
        _result(f"O2_P{index}_S1", 1, f"MM_66_{index}", margin=index > 1, actual=index == 3)
        for index in range(1, 4)
    ]
    source = tmp_path / "Input_Data.xlsx"
    source.write_text("source", encoding="utf-8")
    stat = source.stat()
    sustained_settings = sustained_sdpf.SustainedSDPFSettings(
        enabled=True,
        duration_ms=30.0,
    )
    sustained_sdpf.save_results(
        tmp_path,
        "Full",
        sustained_settings,
        {"66": results[0]},
        signature_inputs={
            "66": {
                "files": [
                    {"path": str(source), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}
                ],
                "heatmap_case_names": [result.case for result in results],
            }
        },
        observations_by_voltage={"66": results},
    )

    settings = [
        sustained_sdpf_heatmap.HeatmapSet(
            "Faults",
            sustained_sdpf_heatmap.HeatmapSettings(y_grouping="Fault type"),
        ),
        sustained_sdpf_heatmap.HeatmapSet(
            "MM elements",
            sustained_sdpf_heatmap.HeatmapSettings(y_grouping="MM element"),
        ),
    ]
    groups = sustained_sdpf_heatmap.generate_heatmap_sets(
        tmp_path,
        "Full",
        "66",
        settings,
        sustained_settings,
    )

    assert [name for name, _paths in groups] == ["Faults", "MM elements"]
    assert all(path.is_file() for _name, paths in groups for path in paths)
    assert all(
        path.parent.name in {"01_Faults", "02_MM_elements"}
        for _name, paths in groups
        for path in paths
    )


def test_heatmap_rebuild_removes_disabled_sets_and_obsolete_voltages(tmp_path) -> None:
    from results_analysis_app import sustained_sdpf, sustained_sdpf_heatmap

    result = _result("O2_P1_S1", 1, "MM_66_A", margin=0.04, actual=0.04)
    source = tmp_path / "Input_Data.xlsx"
    source.write_text("source", encoding="utf-8")
    stat = source.stat()
    sustained_settings = sustained_sdpf.SustainedSDPFSettings(enabled=True, duration_ms=30.0)
    sustained_sdpf.save_results(
        tmp_path,
        "Full",
        sustained_settings,
        {"66": result},
        signature_inputs={
            "66": {
                "files": [
                    {"path": str(source), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}
                ],
                "heatmap_case_names": [result.case],
            }
        },
        observations_by_voltage={"66": [result]},
    )
    root = sustained_sdpf_heatmap.heatmap_output_dir(tmp_path, "Full")
    stale_set = root / "02_Disabled"
    stale_set.mkdir(parents=True)
    (stale_set / "stale.png").write_bytes(b"old")
    active_dir = root / "01_Faults"
    active_dir.mkdir(parents=True)
    stale_voltage = active_dir / "MM_230_All_heatmap.png"
    stale_voltage.write_bytes(b"old")

    groups = sustained_sdpf_heatmap.generate_heatmap_sets(
        tmp_path,
        "Full",
        "66",
        [
            sustained_sdpf_heatmap.HeatmapSet(
                "Faults",
                sustained_sdpf_heatmap.HeatmapSettings(y_grouping="Fault type"),
            ),
            sustained_sdpf_heatmap.HeatmapSet(
                "Disabled",
                sustained_sdpf_heatmap.HeatmapSettings(enabled=False),
            ),
        ],
        sustained_settings,
    )

    assert groups
    assert not stale_set.exists()
    assert stale_voltage.exists()

    sustained_sdpf_heatmap.clear_obsolete_heatmap_voltages(tmp_path, "Full", ["66"])

    assert not stale_voltage.exists()
