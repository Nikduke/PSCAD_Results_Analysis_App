from __future__ import annotations


def test_embedded_plotter_core_imports() -> None:
    import pscad_plotter_app_v3
    from pscad_plotter_app_v3.models import PlotMode
    from pscad_plotter_app_v3.services.batch_excel import BatchExcelService
    from pscad_plotter_app_v3.services.renderer import MatplotlibRenderer

    assert getattr(pscad_plotter_app_v3, "__embedded_source__", "")
    assert PlotMode.MM.value == "MM Overvoltage"
    assert list(PlotMode) == [PlotMode.MM]
    assert "MM" in BatchExcelService.SHEET_DEFINITIONS
    assert MatplotlibRenderer.FIGSIZE


def test_shared_out_readers_check_cancellation_during_file_read(tmp_path) -> None:
    import numpy as np
    import pytest

    from pscad_plotter_app_v3.services.waveform_io import (
        load_out_columns,
        load_out_frame,
    )

    out_path = tmp_path / "C1_r00001_01.out"
    values = np.column_stack(
        [
            np.arange(5000, dtype=float),
            np.arange(5000, dtype=float) * 2.0,
        ]
    )
    np.savetxt(out_path, values, header="time signal", comments="")

    for reader in (
        lambda callback: load_out_columns(out_path, [0, 1], callback),
        lambda callback: load_out_frame(out_path, callback),
    ):
        calls = 0

        def cancel() -> None:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("cancelled")

        with pytest.raises(RuntimeError, match="cancelled"):
            reader(cancel)
        assert calls == 2


def test_create_plot_batches_reads_base_envelope_workbook(tmp_path, monkeypatch) -> None:
    from openpyxl import Workbook

    from results_analysis_app import analysis_engine
    from results_analysis_app.models import ScopeEntry

    project = tmp_path / "Project"
    envelope_dir = project / "Voltage_envelope" / "Full"
    envelope_dir.mkdir(parents=True)

    workbook = Workbook()
    ws = workbook.active
    ws.title = "LLp"
    ws.append(["Time (s)", "Case_all", "Run_all", "MM_name_all", "Fault_type_all"])
    ws.append([0.004, "C1", 4, "MM_66_StA", "AG"])
    ws.append([0.03, "C2", 5, "MM_66_StB", "AB"])
    lg = workbook.create_sheet("LGp")
    lg.append(["Time (s)", "Case_all", "Run_all", "MM_name_all", "Fault_type_all"])
    lg.append([0.1, "C3", 6, "MM_66_StC", "ABC"])
    workbook.save(envelope_dir / "MM_66.xlsx")
    workbook.close()

    (envelope_dir / "MM_66_with_combined_plot.xlsx").write_bytes(b"not an xlsx")

    written = []

    def fake_create_batch(path, rows):
        written.append((path.name, rows))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("ok", encoding="utf-8")

    monkeypatch.setattr(analysis_engine, "_create_batch_workbook", fake_create_batch)

    outputs = analysis_engine.create_plot_batches(
        project,
        [ScopeEntry.full()],
        ["66"],
        ["SFO", "TOV", "SA"],
        {"SFO": 0.004, "TOV": 0.03, "SA": 0.1},
    )

    assert [path.name for path in outputs] == [
        "batch_paste_Full_SFO.xlsx",
        "batch_paste_Full_TOV.xlsx",
        "batch_paste_Full_SA.xlsx",
    ]
    rows_by_name = {name: rows for name, rows in written}
    assert rows_by_name["batch_paste_Full_SFO.xlsx"][0]["case"] == "C1"
    assert rows_by_name["batch_paste_Full_TOV.xlsx"][0]["case"] == "C2"
    assert rows_by_name["batch_paste_Full_SA.xlsx"][0]["case"] == "C3"


def test_nearest_envelope_row_tie_keeps_earlier_source_row() -> None:
    from openpyxl import Workbook

    from results_analysis_app.analysis_engine import _batch_points_from_sheet

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "LLp"
    sheet.append(["Time (s)", "Case_all", "Run_all", "MM_name_all"])
    sheet.append([0.0, "Earlier", 1, "MM_66_A"])
    sheet.append([0.002, "Later", 2, "MM_66_B"])

    points = _batch_points_from_sheet(workbook, "LLp", {"SFO": 0.001})

    assert points["SFO"]["case"] == "Earlier"


def test_empty_batch_removes_stale_generated_event_directory(tmp_path, monkeypatch) -> None:
    from types import SimpleNamespace

    from results_analysis_app import analysis_engine
    from results_analysis_app.models import ScopeEntry

    project = tmp_path / "Project"
    batch = project / "Plots" / "Plot_batch" / "batch_paste_Full_SFO.xlsx"
    analysis_engine._create_batch_workbook(batch, [])
    generated = project / "Plots" / "Generated" / "Full" / "SFO"
    generated.mkdir(parents=True)
    (generated / "stale.png").write_bytes(b"old")

    monkeypatch.setattr(
        analysis_engine,
        "_load_embedded_plotter_session",
        lambda *_args, **_kwargs: (SimpleNamespace(), {}, object(), object()),
    )

    analysis_engine.render_plot_batches(project, [ScopeEntry.full()], ["SFO"])

    assert not generated.exists()


def test_plot_render_failure_keeps_previous_event_output(tmp_path, monkeypatch) -> None:
    from types import SimpleNamespace

    import pytest

    from pscad_plotter_app_v3.models import PlotMode
    from pscad_plotter_app_v3.services.batch_excel import BatchExcelService
    from pscad_plotter_app_v3.services import batching
    from results_analysis_app import analysis_engine
    from results_analysis_app.models import ScopeEntry

    project = tmp_path / "Project"
    batch = project / "Plots" / "Plot_batch" / "batch_paste_Full_SFO.xlsx"
    batch.parent.mkdir(parents=True)
    batch.write_bytes(b"batch")
    generated = project / "Plots" / "Generated" / "Full" / "SFO"
    generated.mkdir(parents=True)
    previous = generated / "previous.png"
    previous.write_bytes(b"good")
    request = SimpleNamespace(
        mode=PlotMode.MM,
        output_dir="",
        voltage_kv=66.0,
        show_limits=False,
        case_name="C1",
        elements=["MM_66_A"],
    )
    monkeypatch.setattr(
        BatchExcelService,
        "load_requests",
        lambda *_args, **_kwargs: SimpleNamespace(requests=[request], errors=[]),
    )

    def fake_jobs(plot_request, _limit):
        return [
            SimpleNamespace(
                case_name="C1",
                group_label="MM_66_A",
                run_number=1,
                excel_export=False,
                output_dir=plot_request.output_dir,
            )
        ]

    monkeypatch.setattr(batching, "build_mm_jobs", fake_jobs)

    class FailingRenderer:
        def render(self, _job):
            raise RuntimeError("render failed")

    monkeypatch.setattr(
        analysis_engine,
        "_load_embedded_plotter_session",
        lambda *_args, **_kwargs: (SimpleNamespace(), {}, FailingRenderer(), object()),
    )

    with pytest.raises(RuntimeError, match="Plot rendering failed"):
        analysis_engine.render_plot_batches(project, [ScopeEntry.full()], ["SFO"])

    assert previous.read_bytes() == b"good"
    assert not list(generated.parent.glob(".SFO.render-*"))


def test_successful_render_directory_commit_removes_obsolete_files(tmp_path) -> None:
    from results_analysis_app.analysis_engine import _replace_generated_directory

    output = tmp_path / "SFO"
    output.mkdir()
    (output / "obsolete.png").write_bytes(b"old")
    stage = tmp_path / ".SFO.render-test"
    stage.mkdir()
    (stage / "current.png").write_bytes(b"new")

    _replace_generated_directory(stage, output)

    assert sorted(path.name for path in output.iterdir()) == ["current.png"]
    assert not stage.exists()


def test_plot_render_cancellation_is_not_wrapped_as_failure(tmp_path, monkeypatch) -> None:
    from types import SimpleNamespace

    import pytest

    from pscad_plotter_app_v3.models import PlotMode
    from pscad_plotter_app_v3.services.batch_excel import BatchExcelService
    from pscad_plotter_app_v3.services import batching
    from results_analysis_app import analysis_engine
    from results_analysis_app.background import OperationCancelled
    from results_analysis_app.models import ScopeEntry

    project = tmp_path / "Project"
    batch = project / "Plots" / "Plot_batch" / "batch_paste_Full_SFO.xlsx"
    batch.parent.mkdir(parents=True)
    batch.write_bytes(b"batch")
    request = SimpleNamespace(
        mode=PlotMode.MM,
        output_dir="",
        voltage_kv=66.0,
        show_limits=False,
        case_name="C1",
        elements=["MM_66_A"],
    )
    monkeypatch.setattr(
        BatchExcelService,
        "load_requests",
        lambda *_args, **_kwargs: SimpleNamespace(requests=[request], errors=[]),
    )
    monkeypatch.setattr(
        batching,
        "build_mm_jobs",
        lambda plot_request, _limit: [
            SimpleNamespace(
                case_name="C1",
                group_label="MM_66_A",
                run_number=1,
                excel_export=False,
                output_dir=plot_request.output_dir,
            )
        ],
    )

    class CancelledRenderer:
        def render(self, _job):
            raise OperationCancelled()

    monkeypatch.setattr(
        analysis_engine,
        "_load_embedded_plotter_session",
        lambda *_args, **_kwargs: (SimpleNamespace(), {}, CancelledRenderer(), object()),
    )

    with pytest.raises(OperationCancelled):
        analysis_engine.render_plot_batches(project, [ScopeEntry.full()], ["SFO"])


def test_resonance_batches_are_authoritative_for_current_settings(tmp_path, monkeypatch) -> None:
    from results_analysis_app import analysis_engine, resonance_checks
    from results_analysis_app.models import ScopeEntry

    project = tmp_path / "Project"
    batch_dir = project / "Plots" / "Plot_batch"
    batch_dir.mkdir(parents=True)
    disabled_event = resonance_checks.plot_event_name("Late_Growth", "LGp")
    stale = batch_dir / f"batch_paste_Full_{disabled_event}.xlsx"
    stale.write_bytes(b"stale")
    written = []

    def fake_write(path, rows):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"current")
        written.append((path.name, rows))

    monkeypatch.setattr(analysis_engine, "_create_batch_workbook", fake_write)

    analysis_engine.create_plot_batches(
        project,
        [ScopeEntry.full()],
        [],
        [],
        resonance_settings={"enabled_checks": ["Post_Event_Stress"]},
    )

    expected = {
        f"batch_paste_Full_{resonance_checks.plot_event_name('Post_Event_Stress', voltage_type)}.xlsx"
        for voltage_type in resonance_checks.VOLTAGE_TYPES
    }
    assert {name for name, _rows in written} == expected
    assert all(rows == [] for _name, rows in written)
    assert not stale.exists()


def test_event_batch_creation_does_not_touch_resonance_batches(tmp_path, monkeypatch) -> None:
    from results_analysis_app import analysis_engine, resonance_checks
    from results_analysis_app.models import ScopeEntry

    project = tmp_path / "Project"
    batch_dir = project / "Plots" / "Plot_batch"
    batch_dir.mkdir(parents=True)
    event_name = resonance_checks.plot_event_name("Late_Growth", "LGp")
    resonance_batch = batch_dir / f"batch_paste_Full_{event_name}.xlsx"
    resonance_batch.write_bytes(b"existing analysis batch")
    monkeypatch.setattr(
        analysis_engine,
        "_create_batch_workbook",
        lambda path, _rows: path.write_bytes(b"event batch"),
    )

    analysis_engine.create_plot_batches(
        project,
        [ScopeEntry.full()],
        [],
        ["SFO"],
        resonance_settings=None,
    )

    assert resonance_batch.read_bytes() == b"existing analysis batch"


def test_inf_case_run_parser_accepts_uppercase_run_marker(tmp_path) -> None:
    from pscad_plotter_app_v3.services.project_conventions import case_run_from_inf_path
    from pscad_plotter_app_v3.services.waveform_io import case_run_from_inf_path as waveform_parser

    path = tmp_path / "Case_A_R00012.inf"

    assert case_run_from_inf_path(path) == ("Case_A", 12)
    assert waveform_parser(path) == ("Case_A", 12)


def test_mm_batch_workbook_contains_only_supported_sheet(tmp_path) -> None:
    from openpyxl import load_workbook

    from results_analysis_app.analysis_engine import _create_batch_workbook

    path = tmp_path / "batch.xlsx"
    _create_batch_workbook(path, [{"case": "C1", "run": 1, "element": "MM_66_A"}])
    workbook = load_workbook(path, read_only=True)
    try:
        assert workbook.sheetnames == ["MM"]
    finally:
        workbook.close()


def test_embedded_plotter_session_loads_minimal_mm_catalog(tmp_path) -> None:
    from results_analysis_app.analysis_engine import _load_embedded_plotter_session

    project = tmp_path / "Project"
    case_root = project / "Case_folder"
    results = project / "Results"
    case_root.mkdir(parents=True)
    results.mkdir()
    inf_path = case_root / "C1_r00001.inf"
    inf_path.write_text(
        'PGB(1) Output Desc="MM_LGp_a" Group="MM_66_A" Units="kV"',
        encoding="utf-8",
    )
    (results / "MM results.csv").write_text(
        "Case name,Run#,Bus voltage [kV],Bus name,Fault_type\n"
        "C1,1,66,MM_66_A,AG\n",
        encoding="utf-8",
    )

    check_cancel = lambda: None
    catalog, limits, renderer, exporter = _load_embedded_plotter_session(
        project,
        check_cancel=check_cancel,
    )

    assert catalog.runs_by_case == {"C1": [1]}
    assert [(record.element_name, record.available_runs) for record in catalog.mm_elements] == [
        ("MM_66_A", [1])
    ]
    assert limits == {}
    assert renderer.resolve_inf_path("C1", 1) == inf_path
    assert renderer._check_cancel is check_cancel
    assert exporter.renderer is renderer


def test_embedded_mm_renderer_and_excel_export(tmp_path) -> None:
    import numpy as np
    from openpyxl import load_workbook

    from pscad_plotter_app_v3.models import PlotJob, PlotMode
    from pscad_plotter_app_v3.services.exporter import ExcelExporter
    from pscad_plotter_app_v3.services.renderer import MatplotlibRenderer

    case_root = tmp_path / "C1.if18"
    case_root.mkdir()
    inf_path = case_root / "C1_r00001.inf"
    descriptions = ["MM_LGp_a", "MM_LGp_b", "MM_LGp_c", "MM_LLp_a", "MM_LLp_b", "MM_LLp_c"]
    inf_path.write_text(
        "\n".join(
            f'PGB({index}) Output Desc="{description}" Group="MM_66_A" Units="kV"'
            for index, description in enumerate(descriptions, start=1)
        ),
        encoding="utf-8",
    )
    time = np.arange(0.0, 0.101, 0.001)
    phases = [120.0 * np.sin(2 * np.pi * 50 * time + phase) for phase in (0.0, 2.1, 4.2)]
    values = np.column_stack([time, *phases, *(1.2 * phase for phase in phases)])
    np.savetxt(case_root / "C1_r00001_01.out", values, header="time a b c ab bc ca", comments="")

    renderer = MatplotlibRenderer({"C1": {1: inf_path}})
    job = PlotJob(
        mode=PlotMode.MM,
        case_name="C1",
        run_number=1,
        group_label="MM_66_A",
        output_dir=str(tmp_path / "plots"),
        trace_type="Both",
        show_limits=False,
        excel_export=True,
        voltage_kv=66.0,
    )

    image_path = renderer.render(job)
    workbook_path = ExcelExporter(renderer).export(job)

    assert image_path.is_file() and image_path.stat().st_size > 1000
    workbook = load_workbook(workbook_path, read_only=True)
    try:
        assert workbook.sheetnames == ["LGp", "LLp"]
    finally:
        workbook.close()


def test_renderer_parses_each_statistic_file_once_for_multiple_runs(tmp_path, monkeypatch) -> None:
    from pscad_plotter_app_v3.services import renderer as renderer_module
    from pscad_plotter_app_v3.services.renderer import MatplotlibRenderer

    stat_path = tmp_path / "Statistic_01.out"
    stat_path.write_text("placeholder", encoding="utf-8")
    find_calls = 0
    parse_calls = 0

    def fake_find(directory):
        nonlocal find_calls
        find_calls += 1
        assert directory == tmp_path
        return stat_path

    def fake_parse(path):
        nonlocal parse_calls
        parse_calls += 1
        assert path == stat_path
        return [
            {"run_number": 1, "fault_label": "AG"},
            {"run_number": 2, "fault_label": "AB"},
        ]

    monkeypatch.setattr(renderer_module, "find_stat_file", fake_find)
    monkeypatch.setattr(renderer_module, "parse_stat_rows", fake_parse)
    renderer = MatplotlibRenderer({})

    assert renderer._find_stat_file(tmp_path) == stat_path
    assert renderer._find_stat_file(tmp_path) == stat_path
    assert renderer._load_event_info(stat_path, 1)["fault_label"] == "AG"
    assert renderer._load_event_info(stat_path, 2)["fault_label"] == "AB"
    assert renderer._load_event_info(stat_path, 1)["fault_label"] == "AG"
    assert find_calls == 1
    assert parse_calls == 1
