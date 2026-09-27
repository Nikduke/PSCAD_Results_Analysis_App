from __future__ import annotations


def _row(
    case: str,
    run: int,
    bus: str,
    voltage: float,
    *,
    lgr: float | None = None,
    lgrm: float | None = None,
    llr: float | None = None,
    llrm: float | None = None,
    lgrm_pu: float | None = None,
    llrm_pu: float | None = None,
    lls: float | None = None,
    tswitch_a: float | None = None,
    tswitch_b: float | None = None,
    tswitch_c: float | None = None,
    unique_id: str = "",
) -> dict[str, object]:
    return {
        "Unique ID": unique_id or f"{case}_{run}_{bus}",
        "Case name": case,
        "Run#": run,
        "Bus name": bus,
        "Bus voltage [kV]": voltage,
        "LLs [kV]": voltage if lls is None else lls,
        "LGr [kV]": lgr,
        "LGrm [kV]": lgrm,
        "LGr [pu]": None if lgr is None else lgr / (voltage / 3**0.5),
        "LGrm [pu]": lgrm_pu if lgrm_pu is not None else (
            None if lgrm is None else lgrm / (voltage / 3**0.5)
        ),
        "LLr [kV]": llr,
        "LLrm [kV]": llrm,
        "LLr [pu]": None if llr is None else llr / voltage,
        "LLrm [pu]": llrm_pu if llrm_pu is not None else (
            None if llrm is None else llrm / voltage
        ),
        "Tswitch_a [s]": tswitch_a,
        "Tswitch_b [s]": tswitch_b,
        "Tswitch_c [s]": tswitch_c,
    }


def test_rms_selection_ranks_each_voltage_and_quantity() -> None:
    from results_analysis_app.rms_analysis import select_rms_rows

    rows = [
        _row("C1", 1, "MM_161_A", 161, lgr=180, lgrm=20, llr=220, llrm=30),
        # A duplicate Case/Bus row must not replace the governing result.
        _row("C1", 2, "MM_161_A", 161, lgr=190, lgrm=25, llr=210, llrm=35),
        _row("C2", 1, "MM_161_B", 161, lgr=210, lgrm=10, llr=230, llrm=40),
        _row("C3", 1, "MM_66_A", 66, lgr=90, lgrm=4, llr=100, llrm=5),
        _row("C4", 1, "MM_66_A", 66, lgr=95, lgrm=0, llr=105, llrm=0),
    ]

    selections = select_rms_rows(
        rows,
        selected_elements=["MM_161_A", "MM_161_B", "MM_66_A"],
        selected_quantities=["LG", "LL"],
        selected_voltages=["66", "161"],
    )

    selected = {
        (item.voltage_key, item.quantity, item.variant): item
        for item in selections
    }
    assert set(selected) == {
        ("161", "LG", "max"),
        ("161", "LG", "min"),
        ("161", "LL", "max"),
        ("161", "LL", "min"),
        ("66", "LG", "max"),
        ("66", "LG", "min"),
        ("66", "LL", "max"),
        ("66", "LL", "min"),
    }
    assert (selected["161", "LG", "max"].case_name, selected["161", "LG", "max"].value_kv) == ("C2", 210)
    assert (selected["161", "LG", "min"].case_name, selected["161", "LG", "min"].value_kv) == ("C2", 10)
    assert (selected["161", "LL", "max"].case_name, selected["161", "LL", "max"].value_kv) == ("C2", 230)
    assert (selected["161", "LL", "min"].case_name, selected["161", "LL", "min"].value_kv) == ("C1", 30)
    # A zero RMS minimum is below the >0.05 pu qualification floor, so the
    # next valid row is selected for both quantities at 66 kV.
    assert selected["66", "LG", "min"].case_name == "C3"
    assert selected["66", "LL", "min"].case_name == "C3"


def test_rms_selection_honours_an_explicitly_empty_voltage_selection() -> None:
    from results_analysis_app.rms_analysis import select_rms_rows

    rows = [_row("C1", 1, "MM_161_A", 161, lgr=210, lgrm=30)]

    assert select_rms_rows(
        rows,
        selected_elements=["MM_161_A"],
        selected_quantities=["LG"],
        selected_voltages=[],
    ) == []


def test_catalog_rms_selection_ignores_rows_without_available_waveforms() -> None:
    from pscad_plotter_app_v3.models import MMElementRecord, ProjectCatalog
    from results_analysis_app.rms_analysis import select_rms_rows_from_catalog

    catalog = ProjectCatalog(
        mm_elements=[MMElementRecord("C1", 161, "MM_161_A", [1])],
        mm_results=[
            # This row has a larger value but no matching .inf-backed run.
            _row("Missing", 18, "MM_161_A", 161, lgr=500, lgrm=20),
            _row("C1", 1, "MM_161_A", 161, lgr=210, lgrm=30),
        ],
    )

    selections = select_rms_rows_from_catalog(
        catalog,
        {"enabled": True, "quantities": ["LG"], "elements": ["MM_161_A"]},
        ["161"],
    )

    assert {(item.variant, item.case_name, item.run_number) for item in selections} == {
        ("max", "C1", 1),
        ("min", "C1", 1),
    }


def test_rms_switching_time_filters_support_discrete_values_and_inclusive_ranges() -> None:
    from results_analysis_app.rms_analysis import (
        RMS_SWITCHING_TIME_MODE_DISCRETE,
        RMS_SWITCHING_TIME_MODE_RANGE,
        select_rms_rows,
    )

    rows = [
        _row("C1", 1, "MM_161_A", 161, lgr=180, lgrm=20, tswitch_a=1.0),
        _row("C2", 1, "MM_161_A", 161, lgr=210, lgrm=30, tswitch_a=2.0),
        _row("C3", 1, "MM_161_A", 161, lgr=230, lgrm=40, tswitch_a=3.0),
    ]

    discrete = select_rms_rows(
        rows,
        selected_elements=["MM_161_A"],
        selected_quantities=["LG"],
        switching_time_mode=RMS_SWITCHING_TIME_MODE_DISCRETE,
        selected_switching_times=[2.0],
    )
    assert {(item.variant, item.case_name) for item in discrete} == {
        ("max", "C2"),
        ("min", "C2"),
    }

    inclusive = select_rms_rows(
        rows,
        selected_elements=["MM_161_A"],
        selected_quantities=["LG"],
        switching_time_mode=RMS_SWITCHING_TIME_MODE_RANGE,
        switching_time_start_s=2.0,
        switching_time_end_s=2.0,
    )
    assert {(item.variant, item.case_name) for item in inclusive} == {
        ("max", "C2"),
        ("min", "C2"),
    }


def test_rms_switching_time_range_uses_any_available_phase_time() -> None:
    from results_analysis_app.rms_analysis import (
        RMS_SWITCHING_TIME_MODE_RANGE,
        row_matches_switching_time,
    )

    row = _row(
        "C1",
        1,
        "MM_161_A",
        161,
        lgr=180,
        lgrm=20,
        tswitch_a=1.0,
        tswitch_b=4.0,
    )
    assert row_matches_switching_time(
        row,
        mode=RMS_SWITCHING_TIME_MODE_RANGE,
        start_s=3.0,
        end_s=4.0,
    )
    assert not row_matches_switching_time(
        row,
        mode=RMS_SWITCHING_TIME_MODE_RANGE,
        start_s=2.0,
        end_s=3.0,
    )


def test_rms_switching_time_settings_normalize_legacy_and_new_shapes() -> None:
    from results_analysis_app.rms_analysis import (
        RMS_SWITCHING_TIME_MODE_ALL,
        RMS_SWITCHING_TIME_MODE_DISCRETE,
        RMS_SWITCHING_TIME_MODE_RANGE,
        normalize_rms_settings,
        switching_time_mode_for_type,
    )

    assert normalize_rms_settings(None)["switching_time_mode"] == RMS_SWITCHING_TIME_MODE_ALL
    assert normalize_rms_settings(
        {"switching_times": [2, "1", 2, "nan"]}
    )["switching_time_mode"] == RMS_SWITCHING_TIME_MODE_DISCRETE
    assert normalize_rms_settings(
        {
            "switching_time_mode": "range",
            "switching_time_start_s": "1.5",
            "switching_time_end_s": 4,
        }
    ) == {
        "enabled": False,
        "quantities": ["LG", "LL"],
        "elements": [],
        "real_rms": True,
        "switching_time_mode": RMS_SWITCHING_TIME_MODE_RANGE,
        "switching_times": [],
        "switching_time_start_s": 1.5,
        "switching_time_end_s": 4.0,
    }
    assert switching_time_mode_for_type("Sequential") == RMS_SWITCHING_TIME_MODE_DISCRETE
    assert switching_time_mode_for_type("None") == RMS_SWITCHING_TIME_MODE_DISCRETE
    assert switching_time_mode_for_type("Random") == RMS_SWITCHING_TIME_MODE_RANGE


def test_available_switching_times_are_unique_and_run_index_backed() -> None:
    from pscad_plotter_app_v3.models import MMElementRecord
    from results_analysis_app.rms_analysis import available_mm_row_keys, available_switching_times

    rows = [
        _row("C1", 1, "MM_161_A", 161, tswitch_a=2.0, tswitch_b=3.0),
        _row("C1", 2, "MM_161_A", 161, tswitch_a=4.0),
        _row("Missing", 1, "MM_161_A", 161, tswitch_a=9.0),
    ]
    keys = available_mm_row_keys(
        [MMElementRecord("C1", 161, "MM_161_A", [1, 2])]
    )
    assert available_switching_times(rows, keys) == [2.0, 3.0, 4.0]


def test_rms_batch_rows_use_separate_quantity_batches_and_variants() -> None:
    from results_analysis_app.rms_analysis import RMSSelection, rms_batch_rows

    rows = rms_batch_rows(
        [
            RMSSelection("LG", "max", "C1", 1, "MM_161_A", 161, 210, 1.3, {}),
            RMSSelection("LG", "min", "C2", 2, "MM_161_A", 161, 30, 0.18, {}),
            RMSSelection("LL", "max", "C3", 3, "MM_161_B", 161, 230, 1.4, {}),
        ],
        excel_export=False,
    )

    assert [row["trace"] for row in rows["RMS_LG"]] == ["LGr", "LGr"]
    assert "plot_variant" not in rows["RMS_LG"][0]
    assert rows["RMS_LG"][0]["annotate_max"] is True
    assert rows["RMS_LG"][0]["annotate_min"] is False
    assert rows["RMS_LG"][1]["annotate_max"] is False
    assert rows["RMS_LG"][1]["annotate_min"] is True
    assert rows["RMS_LG"][0]["excel_export"] is False
    assert rows["RMS_LL"][0]["trace"] == "LLr"


def test_real_rms_settings_can_explicitly_preserve_legacy_method() -> None:
    from results_analysis_app.rms_analysis import normalize_rms_settings

    assert normalize_rms_settings({"real_rms": False})["real_rms"] is False


def test_real_rms_disabled_keeps_legacy_catalog_values_even_with_raw_index(tmp_path) -> None:
    from pscad_plotter_app_v3.models import MMElementRecord, ProjectCatalog
    from results_analysis_app.rms_analysis import select_rms_rows_from_catalog

    catalog = ProjectCatalog(
        mm_elements=[MMElementRecord("C1", 66.0, "MM_66_A", [1])],
        mm_results=[
            _row("C1", 1, "MM_66_A", 66, lgr=210, lgrm=30, llr=230, llrm=40),
        ],
    )
    selections = select_rms_rows_from_catalog(
        catalog,
        {
            "enabled": True,
            "real_rms": False,
            "quantities": ["LG", "LL"],
            "elements": ["MM_66_A"],
        },
        ["66"],
        run_index={"C1": {1: tmp_path / "unused.inf"}},
        frequency_hz=50.0,
    )

    selected = {
        (item.quantity, item.variant): item.value_kv
        for item in selections
    }
    assert selected["LG", "max"] == 210
    assert selected["LG", "min"] == 30
    assert selected["LL", "max"] == 230
    assert selected["LL", "min"] == 40
    assert not any(item.real_rms for item in selections)


def _write_real_rms_run(tmp_path, case_name: str, amplitude_lg: float, amplitude_ll: float):
    import numpy as np

    case_dir = tmp_path / f"{case_name}.if18"
    case_dir.mkdir()
    inf_path = case_dir / f"{case_name}_r00001.inf"
    inf_path.write_text(
        "\n".join(
            [
                'PGB(1) Output Desc="MM_LGp_a" Group="MM_66_A" Units="kV"',
                'PGB(2) Output Desc="MM_LGp_b" Group="MM_66_A" Units="kV"',
                'PGB(3) Output Desc="MM_LGp_c" Group="MM_66_A" Units="kV"',
                'PGB(4) Output Desc="MM_LLp_a" Group="MM_66_A" Units="kV"',
                'PGB(5) Output Desc="MM_LLp_b" Group="MM_66_A" Units="kV"',
                'PGB(6) Output Desc="MM_LLp_c" Group="MM_66_A" Units="kV"',
            ]
        ),
        encoding="utf-8",
    )
    time = np.arange(0.0, 0.2, 0.0002)
    phases = (0.0, -2.0 * np.pi / 3.0, 2.0 * np.pi / 3.0)
    lg = [amplitude_lg * np.sin(2.0 * np.pi * 50.0 * time + phase) for phase in phases]
    ll = [amplitude_ll * np.sin(2.0 * np.pi * 50.0 * time + phase) for phase in phases]
    np.savetxt(
        case_dir / f"{case_name}_r00001_01.out",
        np.column_stack([time, *lg, *ll]),
        header="time lg_a lg_b lg_c ll_a ll_b ll_c",
        comments="",
    )
    return inf_path


def test_real_rms_recomputes_only_catalog_selected_rows(tmp_path, monkeypatch) -> None:
    import numpy as np
    import pytest

    from pscad_plotter_app_v3.models import MMElementRecord, ProjectCatalog
    from pscad_plotter_app_v3.services.waveform_io import WaveformFrame
    import results_analysis_app.real_rms as real_rms_service
    from results_analysis_app.real_rms import compute_real_rms
    from results_analysis_app.rms_analysis import select_rms_rows_from_catalog

    time = np.arange(0.0, 0.2, 0.0002)
    values = np.column_stack(
        [
            time,
            100.0 * np.sin(2.0 * np.pi * 50.0 * time),
            100.0 * np.sin(2.0 * np.pi * 50.0 * time - 2.0 * np.pi / 3.0),
            100.0 * np.sin(2.0 * np.pi * 50.0 * time + 2.0 * np.pi / 3.0),
        ]
    )
    result = compute_real_rms(
        WaveformFrame(values, ["Time (s)", "V_a", "V_b", "V_c"]),
        50.0,
    )
    assert result.max_kv == pytest.approx(100.0 / np.sqrt(2.0), abs=0.2)
    assert result.min_kv == pytest.approx(100.0 / np.sqrt(2.0), abs=0.2)
    assert np.isnan(result.frame.values[0, 1])
    assert np.isfinite(result.frame.values[:, 1:]).any()

    c1 = _write_real_rms_run(tmp_path, "C1", 100.0, 140.0)
    c2 = _write_real_rms_run(tmp_path, "C2", 80.0, 120.0)
    calls = []
    original_compute_groups = real_rms_service.compute_groups_real_rms

    def counted_compute_groups(*args, **kwargs):
        calls.append(args[0])
        return original_compute_groups(*args, **kwargs)

    monkeypatch.setattr(
        real_rms_service,
        "compute_groups_real_rms",
        counted_compute_groups,
    )
    catalog = ProjectCatalog(
        mm_elements=[
            MMElementRecord("C1", 66.0, "MM_66_A", [1]),
            MMElementRecord("C2", 66.0, "MM_66_A", [1]),
        ],
        mm_results=[
            _row("C1", 1, "MM_66_A", 66, lgr=90, lgrm=80, llr=100, llrm=90, tswitch_a=1.0),
            _row("C2", 1, "MM_66_A", 66, lgr=200, lgrm=10, llr=220, llrm=10, tswitch_a=1.0),
        ],
    )
    logs: list[str] = []
    selections = select_rms_rows_from_catalog(
        catalog,
        {
            "enabled": True,
            "real_rms": True,
            "quantities": ["LG", "LL"],
            "elements": ["MM_66_A"],
        },
        ["66"],
        run_index={"C1": {1: c1}, "C2": {1: c2}},
        frequency_hz=50.0,
        log=logs.append,
    )
    assert {(item.quantity, item.variant, item.case_name) for item in selections} == {
        ("LG", "max", "C2"),
        ("LG", "min", "C2"),
        ("LL", "max", "C2"),
        ("LL", "min", "C2"),
    }
    assert all(item.real_rms and item.frequency_hz == 50.0 for item in selections)
    assert len(calls) == 1
    assert calls[0] == c2
    assert next(item for item in selections if item.quantity == "LG" and item.variant == "max").value_kv == pytest.approx(80.0 / np.sqrt(2.0), abs=0.2)
    assert next(item for item in selections if item.quantity == "LL" and item.variant == "max").value_kv == pytest.approx(120.0 / np.sqrt(2.0), abs=0.2)
    assert any(
        "RMS catalog selection: method=MM results.csv" in line
        and "selected rows=4" in line
        for line in logs
    )
    assert any(
        "source runs=1" in line and "enriched rows=4" in line
        for line in logs
    )
    assert "RMS filters: quantities=LG,LL; elements=MM_66_A; voltages=66; switching=all" in logs


def test_real_rms_preserves_switching_time_filter(tmp_path) -> None:
    from pscad_plotter_app_v3.models import MMElementRecord, ProjectCatalog
    from results_analysis_app.rms_analysis import (
        RMS_SWITCHING_TIME_MODE_DISCRETE,
        select_rms_rows_from_catalog,
    )

    c1 = _write_real_rms_run(tmp_path, "C1", 100.0, 140.0)
    c2 = _write_real_rms_run(tmp_path, "C2", 80.0, 120.0)
    catalog = ProjectCatalog(
        mm_elements=[
            MMElementRecord("C1", 66.0, "MM_66_A", [1]),
            MMElementRecord("C2", 66.0, "MM_66_A", [1]),
        ],
        mm_results=[
            _row("C1", 1, "MM_66_A", 66, lgr=90, lgrm=80, tswitch_a=1.0),
            _row("C2", 1, "MM_66_A", 66, lgr=200, lgrm=10, tswitch_a=2.0),
        ],
    )
    selections = select_rms_rows_from_catalog(
        catalog,
        {
            "enabled": True,
            "real_rms": True,
            "quantities": ["LG"],
            "elements": ["MM_66_A"],
            "switching_time_mode": RMS_SWITCHING_TIME_MODE_DISCRETE,
            "switching_times": [2.0],
        },
        ["66"],
        run_index={"C1": {1: c1}, "C2": {1: c2}},
        frequency_hz=50.0,
    )

    assert {(item.variant, item.case_name) for item in selections} == {
        ("max", "C2"),
        ("min", "C2"),
    }


def test_real_rms_falls_back_per_selected_row_when_raw_source_is_missing() -> None:
    from pscad_plotter_app_v3.models import MMElementRecord, ProjectCatalog
    from results_analysis_app.rms_analysis import select_rms_rows_from_catalog

    catalog = ProjectCatalog(
        mm_elements=[MMElementRecord("C1", 66.0, "MM_66_A", [1])],
        mm_results=[
            _row("C1", 1, "MM_66_A", 66, lgr=210, lgrm=30),
        ],
    )
    logs: list[str] = []
    selections = select_rms_rows_from_catalog(
        catalog,
        {
            "enabled": True,
            "real_rms": True,
            "quantities": ["LG"],
            "elements": ["MM_66_A"],
        },
        ["66"],
        run_index={"C1": {}},
        log=logs.append,
    )

    assert {(item.variant, item.value_kv, item.real_rms) for item in selections} == {
        ("max", 210.0, False),
        ("min", 30.0, False),
    }
    assert any("fallback rows=2" in line and "missing source paths=1" in line for line in logs)


def test_real_rms_loads_selected_raw_columns_once_per_source_run(monkeypatch, tmp_path) -> None:
    import results_analysis_app.real_rms as real_rms

    inf_path = _write_real_rms_run(tmp_path, "C1", 100.0, 140.0)
    calls = []
    original = real_rms.load_out_columns

    def counted_load(*args, **kwargs):
        calls.append((args[0], tuple(args[1])))
        return original(*args, **kwargs)

    monkeypatch.setattr(real_rms, "load_out_columns", counted_load)
    results = real_rms.compute_groups_real_rms(
        inf_path,
        ["MM_66_A", "MM_66_A"],
        ["LG", "LL", "LG"],
        50.0,
    )

    assert set(results) == {("MM_66_A", "LG"), ("MM_66_A", "LL")}
    assert len(calls) == 1
    assert set(calls[0][1]) == set(range(7))


def test_real_rms_renderer_uses_raw_channels_and_plot_time_range(tmp_path) -> None:
    from pscad_plotter_app_v3.models import PlotJob, PlotMode
    from pscad_plotter_app_v3.services.renderer import MatplotlibRenderer

    inf_path = _write_real_rms_run(tmp_path, "C1", 100.0, 140.0)
    output_dir = tmp_path / "plots"
    renderer = MatplotlibRenderer({"C1": {1: inf_path}})
    output = renderer.render(
        PlotJob(
            mode=PlotMode.MM,
            case_name="C1",
            run_number=1,
            group_label="MM_66_A",
            output_dir=str(output_dir),
            trace_type="LGr",
            show_three_phase_overview=False,
            show_limits=False,
            time_start_s=0.05,
            time_end_s=0.15,
            real_rms=True,
            real_rms_frequency_hz=50.0,
        )
    )

    assert output.is_file()


def test_real_rms_renderer_applies_to_combined_lg_ll_plot(tmp_path, monkeypatch) -> None:
    import results_analysis_app.real_rms as real_rms
    from pscad_plotter_app_v3.models import PlotJob, PlotMode
    from pscad_plotter_app_v3.services.renderer import MatplotlibRenderer

    inf_path = _write_real_rms_run(tmp_path, "C1", 100.0, 140.0)
    calls = []
    original = real_rms.compute_real_rms

    def counted_compute(*args, **kwargs):
        calls.append(True)
        return original(*args, **kwargs)

    monkeypatch.setattr(real_rms, "compute_real_rms", counted_compute)
    output = MatplotlibRenderer({"C1": {1: inf_path}}).render(
        PlotJob(
            mode=PlotMode.MM,
            case_name="C1",
            run_number=1,
            group_label="MM_66_A",
            output_dir=str(tmp_path / "plots"),
            trace_type="Both",
            show_three_phase_overview=False,
            show_limits=False,
            real_rms=True,
            real_rms_frequency_hz=50.0,
        )
    )

    assert output.is_file()
    assert len(calls) == 2


def test_real_rms_keeps_switching_time_filter_and_batch_metadata() -> None:
    from results_analysis_app.rms_analysis import RMSSelection, rms_batch_rows

    rows = rms_batch_rows(
        [RMSSelection("LG", "max", "C1", 1, "MM_66_A", 66, 70, 1.0, {}, True, 50.0)]
    )
    assert rows["RMS_LG"][0]["real_rms"] is True
    assert rows["RMS_LG"][0]["real_rms_frequency_hz"] == 50.0


def test_rms_paths_keep_quantities_separate(tmp_path) -> None:
    from results_analysis_app.rms_analysis import rms_batch_path, rms_output_dir

    assert rms_output_dir(tmp_path, "Full", "LG") == tmp_path / "Plots" / "Generated" / "Full" / "RMS" / "LG"
    assert rms_output_dir(tmp_path, "Full", "LL") == tmp_path / "Plots" / "Generated" / "Full" / "RMS" / "LL"
    assert rms_batch_path(tmp_path, "Full", "LG").name == "batch_paste_Full_RMS_LG.xlsx"
    assert rms_batch_path(tmp_path, "Full", "LL").name == "batch_paste_Full_RMS_LL.xlsx"


def test_catalog_cache_round_trips_rms_columns(tmp_path) -> None:
    from pscad_plotter_app_v3.services.project import CatalogCache, ResultsCatalogService

    source = tmp_path / "MM results.csv"
    source.write_text("source\n", encoding="utf-8")
    rows = [_row("C1", 1, "MM_161_A", 161, lgr=210, lgrm=30, llr=230, llrm=40)]
    cache = CatalogCache(tmp_path / "state")
    try:
        parser_version = ResultsCatalogService.MM_CSV_CACHE_VERSION
        cache.store_mm_results(source, parser_version, rows)
        loaded = cache.load_mm_results(source, parser_version)
    finally:
        cache.close()

    assert loaded is not None
    assert loaded[0]["Unique ID"] == rows[0]["Unique ID"]
    assert loaded[0]["LGrm [kV]"] == 30
    assert loaded[0]["LLs [kV]"] == rows[0]["LLs [kV]"]
    assert loaded[0]["LLrm [pu]"] == rows[0]["LLrm [pu]"]


def test_rms_annotation_marks_global_maximum_and_minimum() -> None:
    import matplotlib.pyplot as plt
    import numpy as np

    from pscad_plotter_app_v3.models import PlotJob, PlotMode
    from pscad_plotter_app_v3.services.renderer import MatplotlibRenderer
    from pscad_plotter_app_v3.services.waveform_io import WaveformFrame

    renderer = MatplotlibRenderer({})
    frame = WaveformFrame(
        np.asarray([[0.0, 10.0, 8.0, 9.0], [0.1, 20.0, 7.0, 6.0]]),
        ["Time (s)", "V_a", "V_b", "V_c"],
    )
    max_job = PlotJob(
        mode=PlotMode.MM,
        case_name="C1",
        run_number=1,
        group_label="MM_161_A",
        output_dir=".",
        trace_type="LGr",
        show_three_phase_overview=False,
        annotate_max=True,
    )
    min_job = PlotJob(
        mode=PlotMode.MM,
        case_name="C1",
        run_number=1,
        group_label="MM_161_A",
        output_dir=".",
        trace_type="LGr",
        show_three_phase_overview=False,
        annotate_min=True,
    )
    figure, axis = plt.subplots()
    try:
        renderer._render_rms_annotations_if_enabled(
            axis,
            frame,
            max_job,
            {"unit_suffix": "kV"},
        )
        labels = [text.get_text() for text in axis.texts]
        assert labels == ["20 [kV]"]
        axis.clear()
        renderer._render_rms_annotations_if_enabled(
            axis,
            frame,
            min_job,
            {"unit_suffix": "kV"},
        )
        assert [text.get_text() for text in axis.texts] == ["6 [kV]"]
    finally:
        plt.close(figure)


def test_rms_report_reference_uses_steady_state_lls() -> None:
    from results_analysis_app.rms_analysis import RMSSelection, rms_change_percent, rms_reference_kv

    lg = RMSSelection("LG", "min", "C1", 1, "MM_161_A", 161, 87.5, 0.0, {"LLs [kV]": 161.0})
    ll = RMSSelection("LL", "max", "C1", 1, "MM_161_A", 161, 180.0, 0.0, {"LLs [kV]": 161.0})

    assert rms_reference_kv(lg) == 161.0 / 3**0.5
    assert rms_reference_kv(ll) == 161.0
    assert rms_change_percent(lg) == (161.0 / 3**0.5 - 87.5) / (161.0 / 3**0.5) * 100.0
    assert rms_change_percent(ll) == (180.0 - 161.0) / 161.0 * 100.0
