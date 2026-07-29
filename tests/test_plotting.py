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

    catalog, limits, renderer, exporter = _load_embedded_plotter_session(project)

    assert catalog.runs_by_case == {"C1": [1]}
    assert [(record.element_name, record.available_runs) for record in catalog.mm_elements] == [
        ("MM_66_A", [1])
    ]
    assert limits == {}
    assert renderer.resolve_inf_path("C1", 1) == inf_path
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
