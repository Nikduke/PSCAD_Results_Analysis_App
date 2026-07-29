from __future__ import annotations


def test_project_timing_reads_input_data_labels(tmp_path) -> None:
    from openpyxl import Workbook

    from results_analysis_app.project_config import load_project_timing

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Input_Data"
    sheet.append(["Parameter", "Value"])
    sheet.append(["Frequency", 60])
    sheet.append(["Final duration", 0.5])
    workbook.save(tmp_path / "Input_Data_PSCAD_test.xlsx")
    workbook.close()

    timing = load_project_timing(tmp_path)

    assert timing.frequency == 60.0
    assert timing.final_duration == 0.5


def test_envelope_descriptor_cache_deduplicates_identical_inf(tmp_path, monkeypatch) -> None:
    from results_analysis_app import voltage_envelope

    inf_content = 'PGB(1) Desc="MM_66_LGp_A" Group="MM_66_BUS1" Units="kV"\n'
    inf_one = tmp_path / "C1_r00001.inf"
    inf_two = tmp_path / "C2_r00001.inf"
    inf_one.write_text(inf_content, encoding="utf-8")
    inf_two.write_text(inf_content, encoding="utf-8")

    original_parser = voltage_envelope.parse_inf_descriptors
    parse_count = 0

    def counting_parser(path):
        nonlocal parse_count
        parse_count += 1
        return original_parser(path)

    monkeypatch.setattr(voltage_envelope, "parse_inf_descriptors", counting_parser)
    cache = voltage_envelope._read_inf_descriptor_cache([inf_one, inf_two], 2, None)

    assert parse_count == 1
    assert cache[inf_one] is cache[inf_two]


def test_output_tree_does_not_precreate_generated_plot_folders(tmp_path) -> None:
    from results_analysis_app.actions import ensure_output_tree
    from results_analysis_app.models import ScopeEntry

    project = tmp_path / "Project"
    ensure_output_tree(project, [ScopeEntry.full()])

    assert (project / "Voltage_envelope" / "Full").is_dir()
    assert (project / "Reports" / "Full").is_dir()
    assert (project / "Plots" / "Plot_batch").is_dir()
    assert not (project / "Plots" / "Generated").exists()


def test_rebuild_envelope_charts_uses_existing_workbooks(tmp_path, monkeypatch) -> None:
    from results_analysis_app import actions
    from results_analysis_app.models import ScopeEntry

    project = tmp_path / "Project"
    envelope_dir = project / "Voltage_envelope" / "Full"
    envelope_dir.mkdir(parents=True)
    input_path = envelope_dir / "MM_66.xlsx"
    input_path.write_bytes(b"placeholder")

    class DummyExcelApp:
        def __enter__(self):
            return object()

        def __exit__(self, _exc_type, _exc, _tb):
            return False

    calls = []

    def fake_create_combined(input_file, output_file, excel, **kwargs):
        calls.append((input_file, output_file, excel, kwargs))
        output_file.write_bytes(b"chart")
        return output_file

    monkeypatch.setattr(actions, "excel_app", DummyExcelApp)
    monkeypatch.setattr(actions, "create_combined_envelope_plot", fake_create_combined)

    outputs = actions.rebuild_envelope_charts(
        [project],
        [ScopeEntry.full()],
        ["66", "230"],
        event_times={"SFO": 0.005},
        envelope_chart_x_max=0.7,
        envelope_chart_x_major=0.1,
        envelope_chart_y_limits_by_voltage={"66": {"y_min": 40.0}},
        envelope_chart_show_sa_label=True,
        envelope_chart_top_left_cell="J2",
        envelope_chart_width=800.0,
        envelope_chart_height=400.0,
    )

    assert outputs == [envelope_dir / "MM_66_with_combined_plot.xlsx"]
    assert len(calls) == 1
    assert calls[0][0] == input_path
    assert calls[0][1] == envelope_dir / "MM_66_with_combined_plot.xlsx"
    assert calls[0][3]["axis_limits_override"] == {"x_max": 0.7, "x_major": 0.1}
    assert calls[0][3]["axis_limits_by_voltage"] == {"66": {"y_min": 40.0}}
    assert calls[0][3]["event_times"] == {"SFO": 0.005}
    assert calls[0][3]["show_sa_label"] is True
    assert calls[0][3]["chart_top_left_cell"] == "J2"
    assert calls[0][3]["chart_size"] == {"width": 800.0, "height": 400.0}


def test_corrupt_autosave_falls_back_to_default(tmp_path, monkeypatch) -> None:
    from results_analysis_app import storage

    autosave_path = tmp_path / "last_session.json"
    autosave_path.write_text("{not valid json", encoding="utf-8")
    monkeypatch.setattr(storage, "AUTOSAVE_PATH", autosave_path)

    session = storage.load_autosave()

    assert session.projects == []
    assert session.scopes[0].mode == "full"


def test_fast_array_envelope_matches_dataframe_path() -> None:
    import numpy as np
    import pandas as pd

    from results_analysis_app.voltage_envelope import _apply_envelope, _apply_envelope_arrays

    time = np.round(np.arange(0.0, 0.1, 0.0002), 6)
    phases = [
        np.sin(2 * np.pi * 50 * time) * 100,
        np.sin(2 * np.pi * 50 * time + 2.1) * 80,
        np.zeros_like(time),
    ]
    source = pd.DataFrame(
        {
            "Time (s)": time,
            "A": phases[0],
            "B": phases[1],
            "C": phases[2],
        }
    )

    slow = _apply_envelope(source, time_step=0.002, time_end=0.05)
    fast = _apply_envelope_arrays(time, phases, time_step=0.002, time_end=0.05)
    fast_reused = _apply_envelope_arrays(
        time,
        phases,
        time_step=0.002,
        time_end=0.05,
        absolute_phase_values=[np.abs(phase) for phase in phases],
    )

    pd.testing.assert_frame_equal(fast, slow)
    pd.testing.assert_frame_equal(fast_reused, fast)


def test_envelope_processing_stops_at_available_waveform_end() -> None:
    import numpy as np
    import pandas as pd

    from results_analysis_app.voltage_envelope import _apply_envelope, _apply_envelope_arrays

    time = np.round(np.arange(0.0, 0.101, 0.001), 6)
    phases = [np.full_like(time, 10.0), np.full_like(time, 8.0)]
    source = pd.DataFrame({"Time (s)": time, "A": phases[0], "B": phases[1]})

    slow = _apply_envelope(source, time_step=0.01, time_end=0.2)
    fast = _apply_envelope_arrays(time, phases, time_step=0.01, time_end=0.2)

    pd.testing.assert_frame_equal(fast, slow)
    assert fast.index[-1] == 0.09
    assert fast.notna().all().all()
    assert (fast["Max_A"] == 10.0).all()


def test_chart_x_max_is_bounded_by_available_data() -> None:
    from results_analysis_app.envelope_chart import _bounded_x_axis

    assert _bounded_x_axis({"x_max": 1.0}, 0.5)["x_max"] == 0.5
    assert _bounded_x_axis({"x_max": 0.2}, 0.5)["x_max"] == 0.2
    assert _bounded_x_axis({"x_max": None}, 0.5)["x_max"] == 0.5


def test_envelope_inf_inventory_is_filtered_before_scope_selection(tmp_path) -> None:
    from results_analysis_app.exclusions import ExclusionMatcher, ExclusionRule
    from results_analysis_app.models import ScopeEntry
    from results_analysis_app.voltage_envelope import _inf_inventory, _selected_inf_paths

    case_root = tmp_path / "Case_folder"
    case_root.mkdir()
    first = case_root / "C1_r00001.inf"
    second = case_root / "C2_r00001.inf"
    first.write_text("", encoding="utf-8")
    second.write_text("", encoding="utf-8")

    inventory = _inf_inventory(
        case_root,
        ExclusionMatcher([ExclusionRule(case="C2", run=1)]),
    )

    assert inventory == [first]
    assert _selected_inf_paths(inventory, ScopeEntry.full()) == [first]


def test_envelope_workbook_is_formatted_during_write(tmp_path) -> None:
    from openpyxl import load_workbook
    import pandas as pd

    from results_analysis_app.voltage_envelope import HIGH_VOLTAGE_COLUMNS, NONCONV_COLUMNS, _write_workbook

    path = tmp_path / "MM_66.xlsx"
    data = pd.DataFrame({"Time (s)": [0.0], "Max_A": [1.0]})
    _write_workbook(
        path,
        data,
        data,
        pd.DataFrame(columns=NONCONV_COLUMNS),
        pd.DataFrame(columns=HIGH_VOLTAGE_COLUMNS),
    )

    workbook = load_workbook(path, read_only=False)
    try:
        assert workbook["LGp"].freeze_panes == "A2"
        assert workbook["LGp"].auto_filter.ref == "A1:B1"
    finally:
        workbook.close()


def test_frequency_detection_tries_later_phases_before_fallback() -> None:
    import numpy as np

    from results_analysis_app.voltage_envelope import _detect_frequency_from_arrays

    time = np.round(np.arange(0.0, 0.1, 0.0002), 6)
    no_crossings = np.ones_like(time)
    valid_60hz = np.sin(2 * np.pi * 60 * time)
    fallback_events: list[str] = []

    detected = _detect_frequency_from_arrays(
        time,
        [no_crossings, valid_60hz],
        50.0,
        "case run bus",
        fallback_events.append,
    )

    assert detected == 60.0
    assert fallback_events == []

    detected = _detect_frequency_from_arrays(
        time,
        [no_crossings],
        50.0,
        "case run bus",
        fallback_events.append,
    )

    assert detected == 50.0
    assert fallback_events == ["case run bus"]


def test_voltage_run_cache_cancels_queued_reads(tmp_path, monkeypatch) -> None:
    import pytest

    from results_analysis_app import voltage_envelope
    from results_analysis_app.exclusions import ExclusionMatcher

    paths = [tmp_path / f"C1_r{i:05d}.inf" for i in range(20)]
    state = {"cancelled": False, "calls": 0}

    def check_cancel() -> None:
        if state["cancelled"]:
            raise RuntimeError("Operation stopped by user.")

    def fake_read_run_entries(*args):
        state["calls"] += 1
        state["cancelled"] = True
        next(arg for arg in reversed(args) if callable(arg))()
        return [], []

    monkeypatch.setattr(voltage_envelope, "_read_run_entries", fake_read_run_entries)

    with pytest.raises(RuntimeError, match="Operation stopped by user"):
        voltage_envelope._read_voltage_run_cache(
            paths,
            "66",
            "MM_66",
            72.5,
            ExclusionMatcher(),
            1,
            None,
            check_cancel,
        )

    assert state["calls"] == 1


def test_envelope_build_reuses_shared_run_executor(tmp_path, monkeypatch) -> None:
    import pandas as pd

    from results_analysis_app import voltage_envelope
    from results_analysis_app.models import ScopeEntry
    from results_analysis_app.project_config import ProjectTiming

    project = tmp_path / "Project"
    (project / "Case_folder").mkdir(parents=True)
    inf_path = project / "Case_folder" / "C1_r00001.inf"
    inf_path.write_text("", encoding="utf-8")

    monkeypatch.setattr(voltage_envelope, "_read_stat_files", lambda _root: pd.DataFrame())
    monkeypatch.setattr(voltage_envelope, "_find_non_convergent_cases", lambda *_args, **_kwargs: pd.DataFrame())
    monkeypatch.setattr(voltage_envelope, "_selected_inf_paths", lambda *_args: [inf_path])
    monkeypatch.setattr(voltage_envelope, "_read_inf_descriptor_cache", lambda *_args: {})
    monkeypatch.setattr(voltage_envelope, "load_project_timing", lambda _root: ProjectTiming())
    monkeypatch.setattr(voltage_envelope, "load_voltage_configs", lambda *_args, **_kwargs: {})

    calls = []

    def fake_build(*args, **kwargs):
        calls.append((args[5], args[14], args[20]))
        return voltage_envelope._VoltageBuildResult([], [], [])

    monkeypatch.setattr(voltage_envelope, "_build_voltage_workbooks", fake_build)

    voltage_envelope.build_voltage_envelopes(
        project,
        [ScopeEntry.full()],
        ["66", "161"],
        envelope_workers=4,
        build_charts=False,
    )

    assert [call[0] for call in calls] == ["66", "161"]
    assert [call[1] for call in calls] == [4, 4]
    assert len({id(call[2]) for call in calls}) == 1


def test_envelope_reduction_preserves_ranked_source_provenance() -> None:
    import numpy as np
    import pandas as pd

    from results_analysis_app.voltage_envelope import _reduce_merge

    first = pd.DataFrame(
        {
            "Max_A": [10.0, 1.0, np.nan],
            "Max_B": [9.0, 5.0, np.nan],
            "MM_name": ["MM_1"] * 3,
            "Case": ["C1-1"] * 3,
        }
    )
    second = pd.DataFrame(
        {
            "Max_A": [9.0, 8.0, 7.0],
            "Max_B": [9.0, 7.0, np.nan],
            "MM_name": ["MM_2"] * 3,
            "Case": ["C2-2"] * 3,
        }
    )

    result = _reduce_merge([first, second], time_step=0.01)

    assert result["Max_A"].tolist() == [10.0, 8.0, 7.0]
    assert result["Case_A"].tolist() == ["C1", "C2", "C2"]
    assert result["Run_A"].tolist() == [1, 2, 2]
    assert result.loc[0, "Case_B"] == "C1"
    assert result.loc[1, "Case_B"] == "C2"
    assert np.isnan(result.loc[2, "Max_B"])
