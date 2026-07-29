from __future__ import annotations


def test_voltage_configs_read_mm_blocks(tmp_path) -> None:
    from openpyxl import Workbook

    from results_analysis_app.project_config import load_voltage_configs

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "MM_blocks"
    sheet.append(["Group", "Un", "Um"])
    sheet.append(["MM_161_A", 161, 170.0])
    sheet.append(["MM_330_B", 330, 362.0])
    workbook.save(tmp_path / "Input_Data_PSCAD_Python_v11.xlsx")
    workbook.close()

    configs = load_voltage_configs(tmp_path)

    assert configs["161"].bus_prefix == "MM_161"
    assert configs["161"].um == 170.0
    assert configs["330"].bus_prefix == "MM_330"
    assert configs["330"].um == 362.0


def test_project_frequency_reads_input_data_b16(tmp_path) -> None:
    from openpyxl import Workbook

    from results_analysis_app.project_config import load_project_frequency

    workbook = Workbook()
    workbook.active.title = "Input_Data"
    workbook["Input_Data"]["B16"] = "60 Hz"
    workbook.save(tmp_path / "Input_Data_PSCAD_Python_v11.xlsx")
    workbook.close()

    assert load_project_frequency(tmp_path) == 60.0


def test_voltage_configs_missing_workbook_has_no_legacy_fallback(tmp_path) -> None:
    from results_analysis_app.project_config import load_voltage_configs

    assert load_voltage_configs(tmp_path) == {}


def test_voltage_configs_use_inf_prefix_with_um_override(tmp_path) -> None:
    from results_analysis_app.project_config import discover_voltage_prefixes, load_voltage_configs

    case_dir = tmp_path / "Case_folder" / "C1.if15_x86"
    case_dir.mkdir(parents=True)
    (case_dir / "C1_r00001.inf").write_text(
        '1 Desc="MM_330_LGp_A" Group="MM_330_BUS1"\n',
        encoding="utf-8",
    )

    assert discover_voltage_prefixes(tmp_path) == {"330": "MM_330"}
    configs = load_voltage_configs(tmp_path, um_overrides={"330": 362.0})

    assert configs["330"].bus_prefix == "MM_330"
    assert configs["330"].um == 362.0


def test_project_scan_voltage_sources_ignore_results_csv_and_outputs(tmp_path) -> None:
    from openpyxl import Workbook

    from results_analysis_app import scanner

    project = tmp_path / "Project"
    case_dir = project / "Case_folder" / "C1.if18"
    case_dir.mkdir(parents=True)
    (case_dir / "C1_r00001.inf").write_text(
        '1 Desc="MM_66_LGp_A" Group="MM_66_BUS1"\n',
        encoding="utf-8",
    )
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "MM_blocks"
    sheet.append(["Group", "Un", "Um"])
    sheet.append(["MM_161_A", 161, 170.0])
    workbook.save(project / "Input_Data_PSCAD_Python_v11.xlsx")
    workbook.close()

    results = project / "Results"
    results.mkdir()
    (results / "MM results.csv").write_text(
        "Case name,Bus name,Bus voltage [kV],Run#\nC1,MM_999_A,999,1\n",
        encoding="utf-8",
    )
    general_plots = results / "General Plots"
    general_plots.mkdir()
    (general_plots / "MM_888_dummy.png").write_bytes(b"not used")

    scan = scanner.scan_project(project)

    assert scan.available_voltages == ["66", "161"]


def test_project_scan_ignores_corrupt_envelope_workbook(tmp_path) -> None:
    from results_analysis_app import scanner

    project = tmp_path / "Project"
    (project / "Case_folder").mkdir(parents=True)
    envelope_dir = project / "Voltage_envelope" / "Full"
    envelope_dir.mkdir(parents=True)
    (envelope_dir / "MM_66_with_combined_plot.xlsx").write_bytes(b"not an xlsx")

    scan = scanner.scan_project(project)

    assert scan.exists is True
    assert scan.has_envelopes is True
    assert any("Could not read high-voltage proposals" in message for message in scan.messages)


def test_project_scan_cache_reuses_unchanged_scan_and_invalidates_changed_inputs(tmp_path) -> None:
    from results_analysis_app import project_scan_cache, scanner

    project = tmp_path / "Project"
    case_root = project / "Case_folder"
    case_root.mkdir(parents=True)
    inf_path = case_root / "C1_r00001.inf"
    inf_path.write_text('1 Desc="MM_66_LGp_A" Group="MM_66_BUS1"\n', encoding="utf-8")
    project_path = str(project.resolve())
    scan = scanner.ProjectScan(
        path=project.resolve(),
        exists=True,
        chips=["Ready"],
        case_infos=[scanner.CaseInfo(name="C1", inf_path=inf_path)],
        available_voltages=["66"],
    )
    cache_path = tmp_path / "project_scan_cache.json"

    project_scan_cache.update_project_scans(
        {project_path: scan},
        [project_path],
        (450.0, 250.0),
        cache_path,
    )
    cached = project_scan_cache.cached_scan(
        project_scan_cache.load(cache_path),
        project_path,
        (450.0, 250.0),
    )

    assert cached is not None
    assert cached.available_voltages == ["66"]
    inf_path.write_text(inf_path.read_text(encoding="utf-8") + "changed\n", encoding="utf-8")

    assert (
        project_scan_cache.cached_scan(
            project_scan_cache.load(cache_path),
            project_path,
            (450.0, 250.0),
        )
        is None
    )


def test_cached_project_scan_runner_skips_hot_scan_and_supports_force(tmp_path, monkeypatch) -> None:
    from pathlib import Path

    from results_analysis_app import project_scan_runner, scanner

    project = tmp_path / "Project"
    project.mkdir()
    project_path = str(project.resolve())
    cache_path = tmp_path / "project_scan_cache.json"
    calls = 0
    cache_updates = 0

    def fake_scan(path, **_kwargs):
        nonlocal calls
        calls += 1
        return scanner.ProjectScan(path=Path(path).resolve(), exists=True, chips=["Ready"])

    monkeypatch.setattr(project_scan_runner.scanner, "scan_project", fake_scan)
    original_update = project_scan_runner.project_scan_cache.update_project_scans

    def counting_update(*args, **kwargs):
        nonlocal cache_updates
        cache_updates += 1
        return original_update(*args, **kwargs)

    monkeypatch.setattr(project_scan_runner.project_scan_cache, "update_project_scans", counting_update)
    project_scan_runner.scan_projects_cached(
        [project_path],
        project_path,
        450.0,
        250.0,
        cache_path=cache_path,
    )
    project_scan_runner.scan_projects_cached(
        [project_path],
        project_path,
        450.0,
        250.0,
        cache_path=cache_path,
    )
    project_scan_runner.scan_projects_cached(
        [project_path],
        project_path,
        450.0,
        250.0,
        force=True,
        cache_path=cache_path,
    )

    assert calls == 2
    assert cache_updates == 2


def test_dashboard_figure_list_falls_back_to_scanned_selected_projects() -> None:
    from types import SimpleNamespace

    from results_analysis_app.main_window import MainWindow
    from results_analysis_app.models import AppSession, DashboardFigure, ProjectEntry

    selected_without_figures = r"C:\Project\O3"
    selected_with_figures = r"C:\Project\O1"
    unselected_with_figures = r"C:\Project\O2"
    session = AppSession.default()
    session.projects = [
        ProjectEntry(selected_without_figures, selected=True),
        ProjectEntry(selected_with_figures, selected=True),
        ProjectEntry(unselected_with_figures, selected=False),
    ]
    dashboard_figures = {
        selected_with_figures: [DashboardFigure("id-1", "A.xlsx", "Graphs", 1, "Chart")],
        unselected_with_figures: [DashboardFigure("id-2", "B.xlsx", "Graphs", 1, "Chart")],
    }
    window = SimpleNamespace(session=session, dashboard_figures=dashboard_figures)

    assert MainWindow._dashboard_figure_source_paths(window, None) == [selected_with_figures]
    assert MainWindow._dashboard_figure_source_paths(window, selected_without_figures) == [selected_with_figures]
    assert MainWindow._dashboard_figure_source_paths(window, selected_with_figures) == [selected_with_figures]


def test_pscad_log_high_voltage_scan_uses_raw_waveform_runs(tmp_path) -> None:
    import pytest

    from results_analysis_app import scanner

    project = tmp_path / "Project"
    project.mkdir()
    (project / "PSCAD_log.txt").write_text(
        " WARNING: C1 - MM_66_A has very high values. Please check it. Values have been treated to lower\n",
        encoding="utf-8",
    )
    case_dir = project / "Case_folder" / "C1.if18"
    case_dir.mkdir(parents=True)
    for run, ll_peak in ((1, 260.0), (2, 150.0)):
        stem = f"C1_r{run:05d}"
        (case_dir / f"{stem}.inf").write_text(
            "\n".join(
                [
                    'PGB(1) Output Desc="MM_LGp_a" Group="MM_66_A" Max=2 Min=-2 Units="kV"',
                    'PGB(2) Output Desc="MM_LLp_a" Group="MM_66_A" Max=2 Min=-2 Units="kV"',
                    'PGB(3) Output Desc="MM_LLp_a" Group="MM_66_B" Max=2 Min=-2 Units="kV"',
                ]
            ),
            encoding="utf-8",
        )
        (case_dir / f"{stem}_01.out").write_text(
            "\n".join(
                [
                    "time ch1 ch2 ch3",
                    f"0.0 100.0 {ll_peak} 9999.0",
                    "0.1 120.0 130.0 9999.0",
                ]
            ),
            encoding="utf-8",
        )

    rows, warnings = scanner.scan_high_voltage_from_pscad_log(
        project,
        high_voltage_limit_factor=2.0,
        um_overrides={"66": 72.5},
    )

    assert warnings == []
    assert len(rows) == 1
    assert rows[0].case == "C1"
    assert rows[0].run == 1
    assert rows[0].bus == "MM_66_A"
    assert rows[0].signal == "MM_66_A-LLp_a"
    assert rows[0].file == scanner.PSCAD_LOG_HIGH_VOLTAGE_SOURCE
    assert float(rows[0].max_abs) == pytest.approx(260.0)
    assert float(rows[0].limit) == pytest.approx(2.0 * 72.5 * 2**0.5)


def test_raw_high_voltage_scan_checks_cancellation_inside_descriptor_loop(tmp_path) -> None:
    import pytest

    from results_analysis_app import scanner

    inf_path = tmp_path / "C1_r00001.inf"
    inf_path.write_text(
        '\n'.join(
            f'PGB({index}) Output Desc="MM_LGp_a" Group="MM_66_A" Units="kV"'
            for index in range(1, 6)
        ),
        encoding="utf-8",
    )
    calls = 0

    def cancel() -> None:
        nonlocal calls
        calls += 1
        if calls >= 3:
            raise RuntimeError("cancelled")

    with pytest.raises(RuntimeError, match="cancelled"):
        scanner._raw_high_voltage_records_for_inf(
            inf_path,
            {"MM_66_A"},
            {"MM_66_A": "66"},
            {"MM_66_A": 100.0},
            cancel,
        )

    assert calls == 3


def test_cached_project_scan_updates_only_changed_entry(tmp_path, monkeypatch) -> None:
    from pathlib import Path

    from results_analysis_app import project_scan_runner, scanner

    projects = [tmp_path / "A", tmp_path / "B"]
    for project in projects:
        case_root = project / "Case_folder"
        case_root.mkdir(parents=True)
        (case_root / f"{project.name}_r00001.inf").write_text("one\n", encoding="utf-8")
    paths = [str(project.resolve()) for project in projects]
    cache_path = tmp_path / "cache.json"
    scanned: list[str] = []

    def fake_scan(path, **_kwargs):
        resolved = str(Path(path).resolve())
        scanned.append(resolved)
        return scanner.ProjectScan(path=Path(resolved), exists=True, chips=["Ready"])

    monkeypatch.setattr(project_scan_runner.scanner, "scan_project", fake_scan)
    project_scan_runner.scan_projects_cached(paths, paths[0], 1.0, 1.0, cache_path=cache_path)
    scanned.clear()
    updated: list[list[str]] = []
    original_update = project_scan_runner.project_scan_cache.update_project_scans

    def capture_update(scans, project_paths, limits, path):
        selected = list(project_paths)
        updated.append(selected)
        return original_update(scans, selected, limits, path)

    monkeypatch.setattr(project_scan_runner.project_scan_cache, "update_project_scans", capture_update)
    changed_inf = projects[0] / "Case_folder" / "A_r00001.inf"
    changed_inf.write_text("changed content\n", encoding="utf-8")
    project_scan_runner.scan_projects_cached(paths, paths[0], 1.0, 1.0, cache_path=cache_path)

    assert scanned == [paths[0]]
    assert updated == [[paths[0]]]
