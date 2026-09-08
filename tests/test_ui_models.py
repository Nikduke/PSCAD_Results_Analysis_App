from __future__ import annotations


def test_positive_setting_normalization_rejects_nonfinite_values() -> None:
    from results_analysis_app.models import normalize_positive_float

    assert normalize_positive_float("2.5", 1.0) == 2.5
    assert normalize_positive_float("inf", 1.0) == 1.0
    assert normalize_positive_float("nan", 1.0) == 1.0


def test_session_event_times_round_trip() -> None:
    from results_analysis_app.exclusions import ExclusionRule
    from results_analysis_app.models import AppSession

    session = AppSession.default()
    session.event_times["SFO"] = 0.005
    session.envelope_workers = 32
    session.envelope_workers_auto = False
    session.envelope_time_step = 0.001
    session.envelope_time_end = 0.5
    session.envelope_time_end_auto = False
    session.envelope_fallback_frequency = 60.0
    session.excel_waveform_exports_enabled = False
    session.envelope_chart_top_left_cell = "J2"
    session.envelope_chart_width = 800.0
    session.envelope_chart_height = 400.0
    session.envelope_chart_y_limits_by_voltage = {"330": {"y_min": 200.0, "y_max": 800.0, "y_major": 100.0}}
    session.envelope_chart_show_sa_label = True
    session.high_voltage_limit_factor = 4.5
    session.nonconv_cb_iip_limit = 450.0
    session.nonconv_cb_iir_limit = 250.0
    session.resonance_enabled_checks = ["Post_Event_Stress", "Late_Growth"]
    session.resonance_top_n = 2
    session.resonance_limit_multiplier = 1.8
    session.resonance_auto_release = False
    session.resonance_manual_analysis_start = 0.05
    session.resonance_peak_search_fraction = 0.3
    session.resonance_release_decay_ratio = 0.75
    session.resonance_release_rebound_ratio = 0.9
    session.resonance_release_hold_time = 0.04
    session.resonance_rolling_p95_window = 0.03
    session.resonance_rolling_min_samples = 5
    session.resonance_log_floor_vlim_factor = 1e-5
    session.resonance_log_floor_absolute = 1e-3
    session.resonance_growth_window_fraction = 0.25
    session.resonance_min_positive_fraction = 0.7
    session.resonance_min_growth_ratio = 1.1
    session.resonance_min_level_over_vlim = 0.6
    session.resonance_min_growth_delta_factor = 0.02
    session.sustained_sdpf_enabled = True
    session.sustained_sdpf_duration_ms = 37.5
    project = r"C:\Project"
    session.sustained_sdpf_ranking_settings_by_project = {
        project: {
            "highest_voltage_sustained": False,
            "cumulative_stress": True,
            "continuous_duration": False,
        }
    }
    session.sustained_sdpf_heatmap_settings_by_project = {
        project: [{
            "name": "Faults",
            "enabled": False,
            "y_grouping": "P",
            "x_grouping": "S",
            "split_by": None,
            "max_cases_per_heatmap": 12,
            "layout": "separate",
            "max_panels_per_heatmap": 4,
        }]
    }
    session.sustained_sdpf_limit_overrides_by_project = {
        project: {"66": {"LGp": 141.0, "LLp": 142.0}}
    }
    session.envelope_chart_x_max_overrides_by_project = {project: 1.0}
    session.envelope_chart_x_major_overrides_by_project = {project: 0.1}
    session.manual_exclusions_by_project = {
        project: [
            ExclusionRule(case="C5_S1_66OFT2", run=4),
            ExclusionRule(apply=False, run=7),
            ExclusionRule(bus="MM_66_StA"),
        ]
    }
    session.disabled_nonconv_by_project = {project: [("C7_S1_66OFT2", 8)]}
    session.high_voltage_include_overrides_by_project = {
        project: [("66", "C2", 4, "MM_66_Interested")]
    }
    session.dashboard_figure_selection_by_project = {
        project: ["Dashboard.xlsx|Graphs|1|Initial voltages"]
    }
    session.dashboard_figure_apply_to_all = True
    session.dashboard_figure_shared_selection = [
        "Dashboard.xlsx|Graphs|1|Initial voltages"
    ]
    session.dashboard_figure_shared_selection_initialized = True
    session.voltage_um_overrides_by_project = {project: {"330": 362.0}}

    persisted = session.to_dict()
    persisted["high_voltage_exclusions_by_project"] = {
        project: [{"voltage": "230", "case": "C1", "run": 39, "bus": "MM_230_StA"}]
    }
    loaded = AppSession.from_dict(persisted)

    assert loaded.event_times["TOV"] == 0.03
    assert loaded.event_times["SFO"] == 0.005
    assert loaded.event_times["SA"] == 0.1
    assert loaded.envelope_workers == 32
    assert loaded.envelope_workers_auto is False
    assert loaded.envelope_time_step == 0.001
    assert loaded.envelope_time_end == 0.5
    assert loaded.envelope_time_end_auto is False
    assert loaded.envelope_fallback_frequency == 60.0
    assert loaded.excel_waveform_exports_enabled is False
    assert loaded.envelope_chart_x_max_overrides_by_project == {project: 1.0}
    assert loaded.envelope_chart_x_major_overrides_by_project == {project: 0.1}
    assert loaded.envelope_chart_top_left_cell == "J2"
    assert loaded.envelope_chart_width == 800.0
    assert loaded.envelope_chart_height == 400.0
    assert loaded.envelope_chart_y_limits_by_voltage["330"] == {"y_min": 200.0, "y_max": 800.0, "y_major": 100.0}
    assert loaded.envelope_chart_show_sa_label is True
    assert loaded.high_voltage_limit_factor == 4.5
    assert loaded.nonconv_cb_iip_limit == 450.0
    assert loaded.nonconv_cb_iir_limit == 250.0
    assert loaded.resonance_enabled_checks == ["Post_Event_Stress", "Late_Growth"]
    assert loaded.resonance_top_n == 2
    assert loaded.resonance_limit_multiplier == 1.8
    assert loaded.resonance_auto_release is False
    assert loaded.resonance_manual_analysis_start == 0.05
    assert loaded.resonance_peak_search_fraction == 0.3
    assert loaded.resonance_release_decay_ratio == 0.75
    assert loaded.resonance_release_rebound_ratio == 0.9
    assert loaded.resonance_release_hold_time == 0.04
    assert loaded.resonance_rolling_p95_window == 0.03
    assert loaded.resonance_rolling_min_samples == 5
    assert loaded.resonance_log_floor_vlim_factor == 1e-5
    assert loaded.resonance_log_floor_absolute == 1e-3
    assert loaded.resonance_growth_window_fraction == 0.25
    assert loaded.resonance_min_positive_fraction == 0.7
    assert loaded.resonance_min_growth_ratio == 1.1
    assert loaded.resonance_min_level_over_vlim == 0.6
    assert loaded.resonance_min_growth_delta_factor == 0.02
    assert loaded.sustained_sdpf_enabled is True
    assert loaded.sustained_sdpf_duration_ms == 37.5
    assert loaded.sustained_sdpf_ranking_settings_by_project == session.sustained_sdpf_ranking_settings_by_project
    assert loaded.sustained_sdpf_heatmap_settings_by_project == session.sustained_sdpf_heatmap_settings_by_project
    assert loaded.sustained_sdpf_limit_overrides_by_project == session.sustained_sdpf_limit_overrides_by_project
    assert loaded.events == ["SFO", "TOV", "SA"]
    assert loaded.manual_exclusions_by_project == session.manual_exclusions_by_project
    assert loaded.disabled_nonconv_by_project == {project: [("C7_S1_66OFT2", 8)]}
    assert loaded.high_voltage_include_overrides_by_project == {
        project: [("66", "C2", 4, "MM_66_Interested")]
    }
    assert loaded.dashboard_figure_selection_by_project == {
        project: ["Dashboard.xlsx|Graphs|1|Initial voltages"]
    }
    assert loaded.dashboard_figure_apply_to_all is True
    assert loaded.dashboard_figure_shared_selection == [
        "Dashboard.xlsx|Graphs|1|Initial voltages"
    ]
    assert loaded.dashboard_figure_shared_selection_initialized is True
    assert "high_voltage_exclusions_by_project" not in loaded.to_dict()
    assert loaded.voltage_um_overrides_by_project == {project: {"330": 362.0}}
    assert "bus_exclusions_by_project" not in loaded.to_dict()
    assert "manual_case_run_exclusions_by_project" not in loaded.to_dict()


def test_session_ignores_legacy_global_chart_axis_settings() -> None:
    from results_analysis_app.models import AppSession

    loaded = AppSession.from_dict(
        {
            "projects": [{"path": r"C:\Project", "selected": True}],
            "envelope_chart_x_max": 2.0,
            "envelope_chart_x_major": 0.2,
        }
    )

    assert loaded.envelope_chart_x_max_overrides_by_project == {}
    assert loaded.envelope_chart_x_major_overrides_by_project == {}
    assert "envelope_chart_x_max" not in loaded.to_dict()
    assert "envelope_chart_x_major" not in loaded.to_dict()


def test_session_migrates_legacy_exclusions() -> None:
    from results_analysis_app.exclusions import ExclusionRule
    from results_analysis_app.models import AppSession

    project = r"C:\Project"
    loaded = AppSession.from_dict(
        {
            "bus_exclusions_by_project": {
                project: {"66": ["MM_66_StA"], "230": ["MM_230_StA"]}
            },
            "manual_case_run_exclusions_by_project": {
                project: [{"case": "C1", "run": 4}]
            },
        }
    )

    assert loaded.manual_exclusions_by_project == {
        project: [
            ExclusionRule(bus="MM_66_StA"),
            ExclusionRule(bus="MM_230_StA"),
            ExclusionRule(case="C1", run=4),
        ]
    }


def test_session_migrates_legacy_global_dashboard_selection_per_project() -> None:
    from results_analysis_app.models import AppSession

    first = r"C:\Project\O1"
    second = r"C:\Project\O2"
    figure_ids = ["Dashboard.xlsx|Graphs|1|Initial voltages"]

    loaded = AppSession.from_dict(
        {
            "projects": [
                {"path": first, "selected": True},
                {"path": second, "selected": True},
            ],
            "dashboard_figure_selection": figure_ids,
            "dashboard_figure_selection_initialized": True,
        }
    )

    assert loaded.dashboard_figure_selection_by_project == {
        first: figure_ids,
        second: figure_ids,
    }
    assert loaded.dashboard_figure_apply_to_all is True
    assert loaded.dashboard_figure_shared_selection == figure_ids
    assert loaded.dashboard_figure_shared_selection_initialized is True
    persisted = loaded.to_dict()
    assert persisted["dashboard_figure_selection_by_project"] == {
        first: figure_ids,
        second: figure_ids,
    }
    assert "dashboard_figure_selection" not in persisted
    assert "dashboard_figure_selection_initialized" not in persisted


def test_session_migrates_project_dashboard_selections_to_shared_selection() -> None:
    from results_analysis_app.models import AppSession

    first = r"C:\Project\O1"
    second = r"C:\Project\O2"
    loaded = AppSession.from_dict(
        {
            "projects": [
                {"path": first, "selected": True},
                {"path": second, "selected": True},
            ],
            "dashboard_figure_selection_by_project": {
                first: ["A", "B"],
                second: ["B", "C"],
            },
        }
    )

    assert loaded.dashboard_figure_apply_to_all is True
    assert loaded.dashboard_figure_shared_selection == ["A", "B", "C"]
    assert loaded.dashboard_figure_shared_selection_initialized is True


def test_removing_project_purges_all_project_specific_session_state() -> None:
    from results_analysis_app.exclusions import ExclusionRule
    from results_analysis_app.models import AppSession, ProjectEntry

    project = r"C:\Project"
    session = AppSession.default()
    session.projects = [ProjectEntry(project)]
    session.envelope_chart_x_max_overrides_by_project = {project: 0.5}
    session.envelope_chart_x_major_overrides_by_project = {project: 0.05}
    session.voltage_um_overrides_by_project = {project: {"66": 72.5}}
    session.manual_exclusions_by_project = {project: [ExclusionRule(case="C1")]}
    session.disabled_nonconv_by_project = {project: [("C1", 1)]}
    session.high_voltage_include_overrides_by_project = {
        project: [("230", "C2", 2, "MM_230_B")]
    }
    session.sustained_sdpf_heatmap_settings_by_project = {project: {"enabled": True}}
    session.status_cache = {project: ["Ready"]}

    session.remove_projects({project.lower()})

    assert session.projects == []
    for mapping in (
        session.envelope_chart_x_max_overrides_by_project,
        session.envelope_chart_x_major_overrides_by_project,
        session.voltage_um_overrides_by_project,
        session.manual_exclusions_by_project,
        session.disabled_nonconv_by_project,
        session.high_voltage_include_overrides_by_project,
        session.dashboard_figure_selection_by_project,
        session.sustained_sdpf_heatmap_settings_by_project,
        session.status_cache,
    ):
        assert mapping == {}


def test_session_default_envelope_workers_use_automatic_selection() -> None:
    from results_analysis_app.models import AppSession

    assert AppSession.default().envelope_workers == 0
    assert AppSession.default().envelope_workers_auto is True
    assert AppSession.default().envelope_time_end_auto is True
    assert AppSession.default().excel_waveform_exports_enabled is True


def test_top_bar_uses_envelope_and_sdpf_labels_with_dividers(monkeypatch) -> None:
    from PySide6 import QtCore, QtWidgets

    from results_analysis_app import storage
    from results_analysis_app.main_window import MainWindow
    from results_analysis_app.models import AppSession

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    session = AppSession.default()
    session.voltages = ["66", "161", "230"]
    monkeypatch.setattr(storage, "load_autosave", lambda: session)
    monkeypatch.setattr(storage, "save_autosave", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(MainWindow, "refresh_project_scans", lambda *_args, **_kwargs: None)
    window = MainWindow()
    try:
        section_labels = {
            label.text()
            for label in window.findChildren(QtWidgets.QLabel)
            if label.property("labelRole") == "section"
        }
        assert "Envelopes:" in section_labels
        assert "Analysis:" in section_labels
        assert "Envelopes" not in section_labels
        assert "Events" not in section_labels
        assert window.voltage_button.text() == "Voltages (all)"
        assert window.voltage_button.menu() is window.voltage_menu
        assert len(window.voltage_menu.actions()) == 1
        assert window.voltage_menu.actions()[0].defaultWidget() is window.voltage_popup_scroll
        assert window.voltage_popup_content.all_voltages_check is window.all_voltages_check
        assert window.all_voltages_check.text() == "All voltages"
        assert [check.text() for check in window.voltage_checks.values()] == ["66", "161", "230"]
        assert all(
            row.layout().contentsMargins().left() == 20
            for row in window.voltage_popup_content.child_rows
        )
        assert all(check.isChecked() for check in window.voltage_checks.values())
        assert window.all_voltages_check.checkState() == QtCore.Qt.CheckState.Checked
        window.voltage_checks["161"].setChecked(False)
        app.processEvents()
        assert window.session.voltages == ["66", "230"]
        assert window.voltage_button.text() == "Voltages (2/3)"
        assert window.all_voltages_check.checkState() == QtCore.Qt.CheckState.PartiallyChecked
        window.all_voltages_check.setChecked(False)
        app.processEvents()
        assert window.session.voltages == []
        assert window.voltage_button.text() == "Voltages (none)"
        assert window.all_voltages_check.checkState() == QtCore.Qt.CheckState.Unchecked
        window.all_voltages_check.setChecked(True)
        app.processEvents()
        assert window.session.voltages == ["66", "161", "230"]
        assert window.voltage_button.text() == "Voltages (all)"
        window._set_voltage_options(["330", "230"], ["330"])
        app.processEvents()
        assert list(window.voltage_checks) == ["230", "330"]
        assert window.session.voltages == ["330"]
        assert window.voltage_button.text() == "Voltages (1/2)"
        assert window.all_voltages_check.checkState() == QtCore.Qt.CheckState.PartiallyChecked
        assert window.sustained_sdpf_checkbox.text() == "SDPF"
        assert window.sustained_sdpf_checkbox.toolTip() == "Sustained SDPF Stress"
        assert window.rms_checkbox.text() == ""
        assert window.rms_button.text() == "RMS"
        assert not window.rms_checkbox.isEnabled()
        assert not window.rms_button.isEnabled()

        dividers = window.findChildren(QtWidgets.QFrame, "topBarDivider")
        assert len(dividers) == 2
        assert all(
            divider.frameShape() == QtWidgets.QFrame.Shape.VLine
            for divider in dividers
        )
    finally:
        window.close()
        app.processEvents()


def test_chart_axis_settings_use_project_duration_and_per_project_overrides() -> None:
    from pathlib import Path
    from types import SimpleNamespace

    from results_analysis_app.main_window import MainWindow
    from results_analysis_app.models import AppSession
    from results_analysis_app.scanner import ProjectScan

    automatic_project = str(Path(r"C:\Automatic").resolve())
    manual_project = str(Path(r"C:\Manual").resolve())
    session = AppSession.default()
    session.envelope_chart_x_max_overrides_by_project[manual_project] = 0.8
    session.envelope_chart_x_major_overrides_by_project[manual_project] = 0.1
    window = SimpleNamespace(
        session=session,
        project_scans={
            automatic_project: ProjectScan(
                path=Path(automatic_project),
                exists=True,
                final_duration=0.5,
            ),
            manual_project: ProjectScan(
                path=Path(manual_project),
                exists=True,
                final_duration=0.4,
            ),
        },
    )

    values = MainWindow._project_chart_axis_kwargs(
        window,
        [automatic_project, manual_project],
    )

    assert values["envelope_chart_x_max_by_project"] == {
        automatic_project: 0.5,
        manual_project: 0.8,
    }
    assert values["envelope_chart_x_major_by_project"] == {
        automatic_project: None,
        manual_project: 0.1,
    }


def test_heatmap_settings_dialog_restores_saved_dimensions(monkeypatch, tmp_path) -> None:
    from PySide6 import QtWidgets

    from results_analysis_app import settings_dialog, storage
    from results_analysis_app.main_window import MainWindow
    from results_analysis_app.models import AppSession
    from results_analysis_app.scanner import CaseInfo, ProjectScan

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    project = str(tmp_path.resolve())
    session = AppSession.default()
    session.add_project(project)
    session.sustained_sdpf_heatmap_settings_by_project[project] = [{
        "name": "Faults",
        "enabled": True,
        "y_grouping": "S",
        "x_grouping": "P",
        "split_by": "RA",
        "max_cases_per_heatmap": 12,
    }]
    monkeypatch.setattr(storage, "load_autosave", lambda: session)
    monkeypatch.setattr(storage, "save_autosave", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(MainWindow, "refresh_project_scans", lambda *_args, **_kwargs: None)
    window = MainWindow()
    try:
        names = [
            "O2_P1_S1_RA0",
            "O2_P2_S1_RA0",
            "O2_P1_S2_RA1",
            "O2_P2_S2_RA1",
        ]
        window.project_scans[project] = ProjectScan(
            path=tmp_path,
            exists=True,
            case_infos=[CaseInfo(name, tmp_path / f"{name}.inf") for name in names],
        )
        window._select_project_path(project)
        captured: list[list[object]] = []
        dialog_calls = 0

        def dialog_exec(dialog) -> int:
            nonlocal dialog_calls
            dialog_calls += 1
            if dialog_calls == 1:
                combos_by_value = {
                    combo.currentData(): combo
                    for combo in dialog.findChildren(QtWidgets.QComboBox)
                    if combo.currentData() is not None
                }
                combos_by_value["S"].setCurrentIndex(combos_by_value["S"].findData("P"))
                combos_by_value["P"].setCurrentIndex(combos_by_value["P"].findData("S"))
                return QtWidgets.QDialog.DialogCode.Accepted
            current_values = [
                combo.currentData()
                for combo in dialog.findChildren(QtWidgets.QComboBox)
                if combo.currentData() is not None
            ]
            captured.append(current_values)
            if dialog_calls == 2:
                combos_by_value = {
                    combo.currentData(): combo
                    for combo in dialog.findChildren(QtWidgets.QComboBox)
                    if combo.currentData() is not None
                }
                y_combo = combos_by_value["P"]
                y_combo.setCurrentIndex(y_combo.findData("None"))
                return QtWidgets.QDialog.DialogCode.Accepted
            return QtWidgets.QDialog.DialogCode.Rejected

        monkeypatch.setattr(QtWidgets.QDialog, "exec", dialog_exec)
        settings_dialog.edit_settings(window)
        settings_dialog.edit_settings(window)
        settings_dialog.edit_settings(window)

        assert captured == [
            ["P", "S", "RA", "separate"],
            ["None", "S", "RA", "separate"],
        ]
        assert session.sustained_sdpf_heatmap_settings_by_project[project] == [{
            "name": "Faults",
            "enabled": True,
            "y_grouping": "None",
            "x_grouping": "S",
            "split_by": "RA",
            "max_cases_per_heatmap": 12,
            "layout": "separate",
            "max_panels_per_heatmap": 4,
        }]
    finally:
        window.close()
        app.processEvents()


def test_add_project_accepts_multiple_folders_without_rescanning_duplicates(
    monkeypatch,
    tmp_path,
) -> None:
    from PySide6 import QtWidgets

    from results_analysis_app import main_window, storage
    from results_analysis_app.main_window import MainWindow
    from results_analysis_app.models import AppSession

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    first = tmp_path / "First"
    second = tmp_path / "Second"
    first.mkdir()
    second.mkdir()
    session = AppSession.default()
    session.add_project(str(first))
    monkeypatch.setattr(storage, "load_autosave", lambda: session)
    monkeypatch.setattr(MainWindow, "refresh_project_scans", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        main_window,
        "_select_project_directories",
        lambda *_args: [str(first), str(second), str(second)],
    )
    window = MainWindow()
    scan_requests = []
    window.refresh_project_scans = lambda project_paths=None, **_kwargs: scan_requests.append(
        project_paths
    )
    try:
        window.add_project()

        assert [project.path for project in window.session.projects] == [
            str(first.resolve()),
            str(second.resolve()),
        ]
        assert scan_requests == [[str(second.resolve())]]
    finally:
        window.close()
        app.processEvents()


def test_project_selection_is_visible_and_double_click_opens_settings(
    monkeypatch,
    tmp_path,
) -> None:
    from pathlib import Path

    from PySide6 import QtGui, QtWidgets

    from results_analysis_app import storage
    from results_analysis_app.main_window import MainWindow
    from results_analysis_app.models import AppSession

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    first = tmp_path / "First"
    second = tmp_path / "Second"
    session = AppSession.default()
    session.add_project(str(first))
    session.add_project(str(second))
    monkeypatch.setattr(storage, "load_autosave", lambda: session)
    monkeypatch.setattr(MainWindow, "refresh_project_scans", lambda *_args, **_kwargs: None)
    window = MainWindow()
    try:
        first_item = window.project_tree.topLevelItem(0)
        second_item = window.project_tree.topLevelItem(1)
        window._select_project_path(str(second.resolve()))

        assert second_item.font(0).bold()
        assert not first_item.font(0).bold()

        opened_for: list[str | None] = []
        monkeypatch.setattr(
            window,
            "open_settings_dialog",
            lambda: opened_for.append(window._current_project_path()),
        )
        window.project_tree.itemDoubleClicked.emit(first_item, 0)

        assert opened_for == [str(first.resolve())]
        assert window.project_tree.currentItem() is first_item
        assert first_item.font(0).bold()
        assert not second_item.font(0).bold()

        opened_folders: list[str] = []
        monkeypatch.setattr(
            QtGui.QDesktopServices,
            "openUrl",
            lambda url: opened_folders.append(url.toLocalFile()) or True,
        )
        window.project_tree.itemDoubleClicked.emit(first_item, 1)

        assert len(opened_folders) == 1
        assert Path(opened_folders[0]) == first.resolve()
        assert opened_for == [str(first.resolve())]
    finally:
        window.close()
        app.processEvents()


def test_dashboard_figure_list_uses_shared_catalog_by_default_and_local_override(
    monkeypatch,
    tmp_path,
) -> None:
    from PySide6 import QtCore, QtWidgets

    from results_analysis_app import storage
    from results_analysis_app.main_window import MainWindow
    from results_analysis_app.models import AppSession, DashboardFigure

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    first = tmp_path / "O1"
    second = tmp_path / "O2"
    first_path = str(first.resolve())
    second_path = str(second.resolve())
    session = AppSession.default()
    session.add_project(first_path)
    session.add_project(second_path)
    session.dashboard_figure_shared_selection = [
        "A.xlsx|Graphs|1|Initial voltages",
    ]
    session.dashboard_figure_shared_selection_initialized = True
    monkeypatch.setattr(storage, "load_autosave", lambda: session)
    monkeypatch.setattr(MainWindow, "refresh_project_scans", lambda *_args, **_kwargs: None)
    window = MainWindow()
    try:
        window.dashboard_figures = {
            first_path: [
                DashboardFigure(
                    "A.xlsx|Graphs|1|Initial voltages",
                    "A.xlsx",
                    "Graphs",
                    1,
                    "Initial voltages",
                ),
                DashboardFigure("A.xlsx|Graphs|2|Other", "A.xlsx", "Graphs", 2, "Other"),
            ],
            second_path: [
                DashboardFigure(
                    "B.xlsx|Graphs|1|Initial voltages",
                    "B.xlsx",
                    "Graphs",
                    1,
                    "Initial voltages",
                )
            ],
        }

        window._select_project_path(first_path)
        app.processEvents()
        assert window.dashboard_figure_apply_all_checkbox.isChecked()
        assert window.dashboard_figure_list.count() == 3
        assert window.dashboard_figure_list.item(0).checkState() == QtCore.Qt.CheckState.Checked
        assert window.dashboard_figure_list.item(1).checkState() == QtCore.Qt.CheckState.Unchecked
        assert window.dashboard_figure_header.text() == "Dashboard Figures"

        window._select_project_path(second_path)
        app.processEvents()
        assert window.dashboard_figure_list.count() == 3
        assert window.dashboard_figure_list.item(2).text().startswith("B.xlsx")
        assert window.dashboard_figure_list.item(0).checkState() == QtCore.Qt.CheckState.Checked

        window.dashboard_figure_apply_all_checkbox.setChecked(False)
        app.processEvents()
        assert window.dashboard_figure_header.text() == "Dashboard Figures for Current Project"
        assert window.dashboard_figure_list.count() == 1
        assert window.dashboard_figure_list.item(0).text().startswith("B.xlsx")
        assert window.dashboard_figure_list.item(0).checkState() == QtCore.Qt.CheckState.Unchecked
        assert window.session.dashboard_figure_selection_by_project == {
            first_path: ["A.xlsx|Graphs|1|Initial voltages"],
            second_path: [],
        }

        window.dashboard_figure_list.item(0).setCheckState(QtCore.Qt.CheckState.Checked)
        app.processEvents()
        window.dashboard_figure_apply_all_checkbox.setChecked(True)
        app.processEvents()
        assert window.session.dashboard_figure_shared_selection == [
            "B.xlsx|Graphs|1|Initial voltages"
        ]
        assert window.session.dashboard_figure_selection_by_project == {
            first_path: ["A.xlsx|Graphs|1|Initial voltages"],
            second_path: ["B.xlsx|Graphs|1|Initial voltages"],
        }

        window.dashboard_figure_apply_all_checkbox.setChecked(False)
        app.processEvents()
        assert window.dashboard_figure_list.item(0).checkState() == QtCore.Qt.CheckState.Checked
    finally:
        window.close()
        app.processEvents()


def test_project_exclusion_tabs_are_isolated_when_switching_projects(
    monkeypatch,
    tmp_path,
) -> None:
    from PySide6 import QtWidgets

    from results_analysis_app import scanner, storage
    from results_analysis_app.main_window import MainWindow
    from results_analysis_app.models import AppSession

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    first = tmp_path / "O1"
    second = tmp_path / "O2_Active_faults"
    first_path = str(first.resolve())
    second_path = str(second.resolve())
    session = AppSession.default()
    session.add_project(first_path)
    session.add_project(second_path)
    monkeypatch.setattr(storage, "load_autosave", lambda: session)
    monkeypatch.setattr(MainWindow, "refresh_project_scans", lambda *_args, **_kwargs: None)
    window = MainWindow()
    try:
        window.project_scans = {
            first_path: scanner.ProjectScan(
                path=first,
                exists=True,
                chips=["Ready", "No envelopes"],
            ),
            second_path: scanner.ProjectScan(
                path=second,
                exists=True,
                nonconv_cases=[scanner.NonConvergentCase("O2_CASE", 1)],
                high_voltage_exclusions=[
                    scanner.HighVoltageExclusion(
                        voltage="230",
                        case="O2_CASE",
                        run=1,
                        bus="MM_230_A",
                        excluded=True,
                    )
                ],
            ),
        }

        window._select_project_path(second_path)
        app.processEvents()
        assert [
            window.exclusion_tabs.tabText(index)
            for index in range(window.exclusion_tabs.count())
        ] == ["Manual", "NonConv", "High Voltage"]
        assert window.nonconv_proposal_table.rowCount() == 1
        assert window.high_voltage_proposal_table.rowCount() == 1
        assert window.high_voltage_proposal_table.item(0, 2).text() == "O2_CASE"

        window._select_project_path(first_path)
        app.processEvents()
        assert [
            window.exclusion_tabs.tabText(index)
            for index in range(window.exclusion_tabs.count())
        ] == ["Manual"]
        assert window.nonconv_proposal_table.rowCount() == 0
        assert window.high_voltage_proposal_table.rowCount() == 0
        assert window._current_project_path() == first_path
    finally:
        window.close()
        app.processEvents()


def test_project_exclusion_panel_clears_without_an_active_project(
    monkeypatch,
    tmp_path,
) -> None:
    from PySide6 import QtWidgets

    from results_analysis_app import scanner, storage
    from results_analysis_app.main_window import MainWindow
    from results_analysis_app.models import AppSession

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    high_voltage_project = tmp_path / "O2_Active_faults"
    plain_project = tmp_path / "O1"
    high_voltage_path = str(high_voltage_project.resolve())
    plain_path = str(plain_project.resolve())
    session = AppSession.default()
    session.add_project(high_voltage_path)
    session.add_project(plain_path)
    monkeypatch.setattr(storage, "load_autosave", lambda: session)
    monkeypatch.setattr(MainWindow, "refresh_project_scans", lambda *_args, **_kwargs: None)
    window = MainWindow()
    try:
        window.project_scans = {
            high_voltage_path: scanner.ProjectScan(
                path=high_voltage_project,
                exists=True,
                high_voltage_exclusions=[
                    scanner.HighVoltageExclusion(
                        voltage="230",
                        case="O2_CASE",
                        run=1,
                        bus="MM_230_A",
                        excluded=True,
                    )
                ],
            ),
            plain_path: scanner.ProjectScan(
                path=plain_project,
                exists=True,
                chips=["Ready", "No envelopes"],
            ),
        }

        window._select_project_path(plain_path)
        app.processEvents()
        assert window._current_project_path() == plain_path
        assert window.high_voltage_proposal_table.rowCount() == 0
        assert window.exclusion_tabs.indexOf(window.high_voltage_tab) < 0

        window.project_tree.clear()
        app.processEvents()
        assert window._current_project_path() is None
        assert window.high_voltage_proposal_table.rowCount() == 0
        assert window.nonconv_proposal_table.rowCount() == 0
        assert window.exclusion_tabs.indexOf(window.nonconv_tab) < 0
        assert window.exclusion_tabs.indexOf(window.high_voltage_tab) < 0
    finally:
        window.close()
        app.processEvents()


def test_project_scan_discards_stale_high_voltage_include_overrides(
    monkeypatch,
    tmp_path,
) -> None:
    from PySide6 import QtWidgets

    from results_analysis_app import project_scan_cache, scanner, storage
    from results_analysis_app.main_window import MainWindow
    from results_analysis_app.models import AppSession
    from results_analysis_app.project_scan_runner import ProjectScanBatch

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    first = tmp_path / "O1"
    active_faults = tmp_path / "O2_Active_faults"
    load_rejection = tmp_path / "O2_Load_Rejection"
    first_path = str(first.resolve())
    active_faults_path = str(active_faults.resolve())
    load_rejection_path = str(load_rejection.resolve())
    stale_key = ("161", "O2_CASE", 9, "MM_161_ONT1")
    session = AppSession.default()
    session.add_project(first_path)
    session.add_project(active_faults_path)
    session.add_project(load_rejection_path)
    session.high_voltage_include_overrides_by_project = {
        first_path: [stale_key],
    }
    monkeypatch.setattr(storage, "load_autosave", lambda: session)
    monkeypatch.setattr(storage, "save_autosave", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(MainWindow, "refresh_project_scans", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(project_scan_cache, "update_project_scans", lambda *_args, **_kwargs: None)
    window = MainWindow()
    try:
        window._reload_project_exclusions(first_path)
        assert window.high_voltage_proposal_table.rowCount() == 0
        assert window.exclusion_tabs.indexOf(window.high_voltage_tab) < 0

        active_row = scanner.HighVoltageExclusion(
            voltage=stale_key[0],
            case=stale_key[1],
            run=stale_key[2],
            bus=stale_key[3],
            source=scanner.HIGH_VOLTAGE_SOURCE_ANALYSIS,
            excluded=True,
        )
        window._project_scans_finished(
            ProjectScanBatch(
                current_path=first_path,
                scans={
                    first_path: scanner.ProjectScan(path=first, exists=True),
                    active_faults_path: scanner.ProjectScan(
                        path=active_faults,
                        exists=True,
                        high_voltage_exclusions=[active_row],
                    ),
                    load_rejection_path: scanner.ProjectScan(
                        path=load_rejection,
                        exists=True,
                    ),
                },
            )
        )
        app.processEvents()

        assert window.session.high_voltage_include_overrides_by_project == {}

        window._select_project_path(first_path)
        app.processEvents()
        assert window.high_voltage_proposal_table.rowCount() == 0
        assert window.exclusion_tabs.indexOf(window.high_voltage_tab) < 0

        window._select_project_path(active_faults_path)
        app.processEvents()
        assert window.high_voltage_proposal_table.rowCount() == 1
        assert window.exclusion_tabs.indexOf(window.high_voltage_tab) >= 0

        window._select_project_path(load_rejection_path)
        app.processEvents()
        assert window.high_voltage_proposal_table.rowCount() == 0
        assert window.exclusion_tabs.indexOf(window.high_voltage_tab) < 0
    finally:
        window.close()
        app.processEvents()


def test_project_folder_dialog_returns_multiple_selected_folders(
    monkeypatch,
    tmp_path,
) -> None:
    from pathlib import Path

    from PySide6 import QtCore, QtWidgets

    from results_analysis_app.main_window import _select_project_directories

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    expected = {tmp_path / "First", tmp_path / "Second"}
    for path in expected:
        path.mkdir()

    def select_folders(dialog) -> int:
        dialog.show()
        app.processEvents()
        view = dialog.findChild(QtWidgets.QListView, "listView")
        assert view.selectionMode() == QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection
        selection = view.selectionModel()
        selection.clearSelection()
        for path in expected:
            index = view.model().index(str(path.resolve()))
            assert index.isValid()
            selection.select(
                index,
                QtCore.QItemSelectionModel.SelectionFlag.Select
                | QtCore.QItemSelectionModel.SelectionFlag.Rows,
            )
        return QtWidgets.QDialog.DialogCode.Accepted

    monkeypatch.setattr(QtWidgets.QFileDialog, "exec", select_folders)

    selected = _select_project_directories(None, tmp_path)

    assert {Path(path) for path in selected} == {path.resolve() for path in expected}


def test_exclusion_normalizers_drop_invalid_values() -> None:
    from results_analysis_app.exclusions import (
        ExclusionMatcher,
        ExclusionRule,
        normalize_case_run_exclusions,
        normalize_exclusion_rules,
        normalize_high_voltage_exclusions,
    )

    assert normalize_case_run_exclusions(
        [{"case": "C1", "run": "4.0"}, ["C1", 4], ["C2", "bad"], ["", 1]]
    ) == [("C1", 4)]
    assert normalize_high_voltage_exclusions(
        [{"voltage": "230.0", "case": "C1", "run": "39", "bus": "MM_230_StA"}, ["", "C2", 1, "MM"]]
    ) == [("230", "C1", 39, "MM_230_StA")]
    rules = normalize_exclusion_rules(
        [
            {"case": " C1 ", "run": "4.0"},
            {"case": "C1", "run": 4},
            {"run": "r00007"},
            {"bus": " MM_66_StA "},
            {"case": "", "run": "", "bus": ""},
            {"case": "C2", "run": "bad"},
            {"apply": "no", "case": "C3"},
        ]
    )
    assert rules == [
        ExclusionRule(case="C1", run=4),
        ExclusionRule(run=7),
        ExclusionRule(bus="MM_66_StA"),
        ExclusionRule(apply=False, case="C3"),
    ]
    assert normalize_exclusion_rules(
        [
            {
                "case": "C4",
                "run": "1, r00004; 7",
                "bus": "MM_230_A, MM_230_B\nMM_230_A",
            }
        ]
    ) == [
        ExclusionRule(case="C4", run=1, bus="MM_230_A"),
        ExclusionRule(case="C4", run=1, bus="MM_230_B"),
        ExclusionRule(case="C4", run=4, bus="MM_230_A"),
        ExclusionRule(case="C4", run=4, bus="MM_230_B"),
        ExclusionRule(case="C4", run=7, bus="MM_230_A"),
        ExclusionRule(case="C4", run=7, bus="MM_230_B"),
    ]
    assert normalize_exclusion_rules(
        [{"case": "C5", "run": "1, bad", "bus": "MM_230_A"}]
    ) == []

    matcher = ExclusionMatcher(
        [
            ExclusionRule(case="C1", run=4),
            ExclusionRule(case="C2", bus="MM_66_StA"),
            ExclusionRule(run=7),
            ExclusionRule(bus="MM_230_StA"),
            ExclusionRule(apply=False, case="C3"),
            ExclusionRule(voltage="66", case="C4", run=2, bus="MM_66_StB"),
        ]
    )
    assert matcher.excludes("66", "C1", 4, "MM_66_Any")
    assert matcher.excludes("66", "C2", 99, "MM_66_StA")
    assert matcher.excludes("230", "Any", 7, "Any")
    assert matcher.excludes("230", "Any", 1, "MM_230_StA")
    assert matcher.excludes("66", "C4", 2, "MM_66_StB")
    assert not matcher.excludes("230", "C4", 2, "MM_66_StB")
    assert not matcher.excludes("66", "C3", 1, "MM_66_StA")


def test_exclusion_table_is_universal_and_supports_tsv_paste(monkeypatch) -> None:
    from pathlib import Path

    from PySide6 import QtCore, QtWidgets

    from results_analysis_app import storage
    from results_analysis_app.exclusions import ExclusionRule
    from results_analysis_app.main_window import MainWindow
    from results_analysis_app.models import AppSession
    from results_analysis_app.scanner import (
        HighVoltageExclusion,
        NonConvergentCase,
        ProjectScan,
    )

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    monkeypatch.setattr(storage, "load_autosave", AppSession.default)
    monkeypatch.setattr(MainWindow, "refresh_project_scans", lambda *_args, **_kwargs: None)
    window = MainWindow()
    try:
        tab_names = [
            window.exclusion_tabs.tabText(index)
            for index in range(window.exclusion_tabs.count())
        ]
        assert tab_names == ["Manual"]
        assert [
            window.manual_exclusion_table.horizontalHeaderItem(column).text()
            for column in range(window.manual_exclusion_table.columnCount())
        ] == ["Apply", "Case", "Run", "Bus"]

        QtWidgets.QApplication.clipboard().setText(
            "Apply\tCase\tRun\tBus\n"
            "Yes\tC1\t4\tMM_66_StA\n"
            "No\t\t7\t\n"
            "Yes\tC2\t\tMM_230_StA\n"
            "Yes\t\t\t\n"
        )
        window._paste_manual_exclusions()

        assert window._manual_exclusion_rows() == [
            ExclusionRule(case="C1", run=4, bus="MM_66_StA"),
            ExclusionRule(apply=False, run=7),
            ExclusionRule(case="C2", bus="MM_230_StA"),
        ]
        assert (
            window.manual_exclusion_table.item(0, 0).checkState()
            == QtCore.Qt.CheckState.Checked
        )
        project = r"C:\Project"
        window.session.manual_exclusions_by_project = {
            project: [
                ExclusionRule(bus="MM_66_StA"),
                ExclusionRule(apply=False, run=9),
            ]
        }
        window.session.disabled_nonconv_by_project = {project: [("C2", 2)]}
        window.project_scans = {
            project: ProjectScan(
                path=Path(project),
                exists=True,
                nonconv_cases=[
                    NonConvergentCase("C1", 1),
                    NonConvergentCase("C2", 2),
                ],
                high_voltage_exclusions=[
                    HighVoltageExclusion(
                        voltage="230",
                        case="C3",
                        run=3,
                        bus="MM_230_StA",
                        excluded=True,
                    )
                ],
            )
        }
        window._reload_project_exclusions(project)
        assert window._effective_exclusions_by_project() == {
            project: [
                ExclusionRule(bus="MM_66_StA"),
                ExclusionRule(case="C1", run=1),
                ExclusionRule(
                    voltage="230",
                    case="C3",
                    run=3,
                    bus="MM_230_StA",
                ),
            ]
        }
        for tab in (
            window.exclusion_tabs.widget(0),
            window.exclusion_tabs.widget(1),
            window.high_voltage_tab,
        ):
            labels = {button.text() for button in tab.findChildren(QtWidgets.QPushButton)}
            assert {"Apply all", "Apply none"} <= labels
    finally:
        window.close()
        app.processEvents()


def test_manual_exclusion_cells_expand_delimited_runs_and_buses(monkeypatch) -> None:
    from PySide6 import QtWidgets

    from results_analysis_app import storage
    from results_analysis_app.exclusions import ExclusionRule
    from results_analysis_app.main_window import MainWindow
    from results_analysis_app.models import AppSession

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    monkeypatch.setattr(storage, "load_autosave", AppSession.default)
    monkeypatch.setattr(MainWindow, "refresh_project_scans", lambda *_args, **_kwargs: None)
    window = MainWindow()
    try:
        row = window._append_manual_exclusion_row()
        window.manual_exclusion_table.item(row, 1).setText("C4")
        window.manual_exclusion_table.item(row, 2).setText("1, r00004; 7")
        window.manual_exclusion_table.item(row, 3).setText("MM_230_A, MM_230_B")

        assert window._manual_exclusion_rows() == [
            ExclusionRule(case="C4", run=1, bus="MM_230_A"),
            ExclusionRule(case="C4", run=1, bus="MM_230_B"),
            ExclusionRule(case="C4", run=4, bus="MM_230_A"),
            ExclusionRule(case="C4", run=4, bus="MM_230_B"),
            ExclusionRule(case="C4", run=7, bus="MM_230_A"),
            ExclusionRule(case="C4", run=7, bus="MM_230_B"),
        ]
    finally:
        window.close()
        app.processEvents()


def test_high_voltage_fault_column_uses_cached_statistic_run_mapping(tmp_path) -> None:
    from results_analysis_app.main_window import _fault_types_by_case_run_for_scan
    from results_analysis_app.scanner import CaseInfo, ProjectScan

    scan = ProjectScan(
        path=tmp_path,
        exists=True,
        case_infos=[CaseInfo(name="C1", inf_path=tmp_path / "C1_r00001.inf")],
        fault_types_by_run={1: "AG", 2: "None"},
    )

    assert _fault_types_by_case_run_for_scan(scan) == {
        ("c1", 1): "AG",
        ("c1", 2): "None",
    }


def test_high_voltage_project_switch_reuses_cached_rows_and_fault_types(
    monkeypatch,
    tmp_path,
) -> None:
    from PySide6 import QtWidgets

    from results_analysis_app import main_window as main_window_module, scanner, storage
    from results_analysis_app.main_window import MainWindow
    from results_analysis_app.models import AppSession

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    project = str((tmp_path / "Project").resolve())
    session = AppSession.default()
    session.add_project(project)
    monkeypatch.setattr(storage, "load_autosave", lambda: session)
    monkeypatch.setattr(MainWindow, "refresh_project_scans", lambda *_args, **_kwargs: None)

    calls = {"groups": 0}
    original_group = main_window_module._group_high_voltage_proposals

    def counted_group(rows):
        calls["groups"] += 1
        return original_group(rows)

    monkeypatch.setattr(main_window_module, "_group_high_voltage_proposals", counted_group)
    rows = [
        scanner.HighVoltageExclusion(
            voltage="66",
            case="C1",
            run=1,
            bus="MM_66_A",
            source=scanner.HIGH_VOLTAGE_SOURCE_PSCAD_LOG,
        )
    ]
    window = MainWindow()
    try:
        window.project_scans[project] = scanner.ProjectScan(
            path=tmp_path / "Project",
            exists=True,
            case_infos=[scanner.CaseInfo("C1", tmp_path / "C1_r00001.inf")],
            fault_types_by_run={1: "AG"},
        )
        window._select_project_path(project)
        window._set_high_voltage_proposal_rows(rows)
        window._set_high_voltage_proposal_rows(rows)
        assert calls == {"groups": 1}
        assert window.high_voltage_proposal_table.item(0, 4).text() == "AG"
    finally:
        window.close()
        app.processEvents()


def test_high_voltage_table_checks_log_and_applied_analysis_exclusions(
    monkeypatch,
    tmp_path,
) -> None:
    from PySide6 import QtCore, QtWidgets

    from results_analysis_app import scanner, storage
    from results_analysis_app.main_window import MainWindow
    from results_analysis_app.models import AppSession

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    project = str((tmp_path / "Project").resolve())
    session = AppSession.default()
    session.add_project(project)
    monkeypatch.setattr(storage, "load_autosave", lambda: session)
    monkeypatch.setattr(MainWindow, "refresh_project_scans", lambda *_args, **_kwargs: None)
    window = MainWindow()
    try:
        proposals = [
            scanner.HighVoltageExclusion(
                voltage="66",
                case="Earlier",
                run=1,
                bus="MM_66_A",
                fault_type="AG",
                max_abs="600",
                limit="500",
                signal="Va",
                source=scanner.HIGH_VOLTAGE_SOURCE_PSCAD_LOG,
            ),
            scanner.HighVoltageExclusion(
                voltage="230",
                case="Additional",
                run=2,
                bus="MM_230_B",
                max_abs="1800",
                limit="1700",
                signal="Va",
                source=scanner.HIGH_VOLTAGE_SOURCE_ANALYSIS,
                excluded=True,
            ),
            scanner.HighVoltageExclusion(
                voltage="230",
                case="Additional",
                run=2,
                bus="MM_230_B",
                max_abs="1900",
                limit="1700",
                signal="Vb",
                source=scanner.HIGH_VOLTAGE_SOURCE_ANALYSIS,
                excluded=True,
            ),
            scanner.HighVoltageExclusion(
                voltage="161",
                case="LogOnly",
                run=3,
                bus="MM_161_C",
                max_abs="1200",
                limit="1100",
                signal="Vc",
                source=scanner.HIGH_VOLTAGE_SOURCE_PSCAD_LOG,
            ),
        ]
        window.project_scans[project] = scanner.ProjectScan(
            path=tmp_path / "Project",
            exists=True,
            high_voltage_exclusions=proposals,
        )
        window._select_project_path(project)
        window._set_high_voltage_proposal_rows(proposals)

        assert window.high_voltage_proposal_table.rowCount() == 3
        rows = {
            window.high_voltage_proposal_table.item(row, 2).text(): row
            for row in range(window.high_voltage_proposal_table.rowCount())
        }
        earlier = rows["Earlier"]
        additional = rows["Additional"]
        log_only = rows["LogOnly"]
        assert (
            window.high_voltage_proposal_table.item(earlier, 0).checkState()
            == QtCore.Qt.CheckState.Checked
        )
        assert (
            window.high_voltage_proposal_table.item(additional, 0).checkState()
            == QtCore.Qt.CheckState.Checked
        )
        assert (
            window.high_voltage_proposal_table.item(log_only, 0).checkState()
            == QtCore.Qt.CheckState.Checked
        )
        assert window.high_voltage_proposal_table.item(earlier, 4).text() == "AG"
        assert window.high_voltage_proposal_table.item(earlier, 9).text() == "PSCAD log"
        assert window.high_voltage_proposal_table.item(additional, 6).text() == "1900"
        assert window.high_voltage_proposal_table.item(additional, 8).text() == "Va, Vb"
        assert window.high_voltage_proposal_table.item(additional, 9).text() == "Analysis"
    finally:
        window.close()
        app.processEvents()


def test_applied_pscad_log_hv_rows_are_left_for_detailed_envelope_scan(
    monkeypatch,
    tmp_path,
) -> None:
    from PySide6 import QtWidgets

    from results_analysis_app import scanner, storage
    from results_analysis_app.main_window import MainWindow
    from results_analysis_app.models import AppSession

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    project = str((tmp_path / "Project").resolve())
    session = AppSession.default()
    session.add_project(project)
    monkeypatch.setattr(storage, "load_autosave", lambda: session)
    monkeypatch.setattr(MainWindow, "refresh_project_scans", lambda *_args, **_kwargs: None)
    window = MainWindow()
    try:
        window.project_scans = {
            project: scanner.ProjectScan(
                path=tmp_path / "Project",
                exists=True,
                high_voltage_exclusions=[
                    scanner.HighVoltageExclusion(
                        voltage="66",
                        case="C1",
                        run=1,
                        bus="MM_66_A",
                        file=scanner.PSCAD_LOG_HIGH_VOLTAGE_SOURCE,
                        source=scanner.HIGH_VOLTAGE_SOURCE_PSCAD_LOG,
                    )
                ],
            )
        }

        assert window._effective_exclusions_by_project() == {}
    finally:
        window.close()
        app.processEvents()


def test_unchecking_high_voltage_row_creates_include_override(monkeypatch, tmp_path) -> None:
    from PySide6 import QtCore, QtWidgets

    from results_analysis_app import scanner, storage
    from results_analysis_app.main_window import MainWindow
    from results_analysis_app.models import AppSession

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    project = str((tmp_path / "Project").resolve())
    session = AppSession.default()
    session.add_project(project)
    proposal = scanner.HighVoltageExclusion(
        voltage="66",
        case="C1",
        run=1,
        bus="MM_66_A",
        source=scanner.HIGH_VOLTAGE_SOURCE_PSCAD_LOG,
    )
    monkeypatch.setattr(storage, "load_autosave", lambda: session)
    monkeypatch.setattr(MainWindow, "refresh_project_scans", lambda *_args, **_kwargs: None)
    window = MainWindow()
    try:
        window.project_scans[project] = scanner.ProjectScan(
            path=tmp_path / "Project",
            exists=True,
            high_voltage_exclusions=[proposal],
        )
        window._select_project_path(project)
        window._set_high_voltage_proposal_rows([proposal])
        apply_item = window.high_voltage_proposal_table.item(0, 0)

        assert apply_item.checkState() == QtCore.Qt.CheckState.Checked
        apply_item.setCheckState(QtCore.Qt.CheckState.Unchecked)
        app.processEvents()

        assert window.session.high_voltage_include_overrides_by_project[project] == [
            ("66", "C1", 1, "MM_66_A")
        ]
        assert window._effective_exclusions_by_project().get(project, []) == []

        apply_item.setCheckState(QtCore.Qt.CheckState.Checked)
        app.processEvents()

        assert project not in window.session.high_voltage_include_overrides_by_project
    finally:
        window.close()
        app.processEvents()


def test_inf_descriptor_filter_uses_universal_exclusion_matcher() -> None:
    from results_analysis_app.exclusions import ExclusionMatcher, ExclusionRule
    from results_analysis_app.voltage_envelope import _filter_inf_descriptors
    from pscad_plotter_app_v3.services.waveform_io import InfDescriptor

    descriptors = [
        InfDescriptor(1, "LGp_A p_", "MM_66_StA"),
        InfDescriptor(2, "LGp_A p_", "MM_66_StB"),
    ]
    matcher = ExclusionMatcher(
        [ExclusionRule(case="C1", run=4, bus="MM_66_StA")]
    )

    filtered = _filter_inf_descriptors(
        descriptors,
        "MM_66",
        "66",
        "C1",
        4,
        matcher,
    )

    assert filtered["Group"].tolist() == ["MM_66_StB"]


def test_application_themes_have_readable_roles() -> None:
    from PySide6 import QtCore, QtGui, QtWidgets

    from results_analysis_app.styles import (
        DARK_THEME,
        LIGHT_THEME,
        _ThemeProxyStyle,
        _application_stylesheet,
        apply_application_theme,
        apply_run_button_style,
        install_system_theme,
        make_muted_label,
    )

    def luminance(value: str) -> float:
        channels = [
            int(value[index : index + 2], 16) / 255.0
            for index in (1, 3, 5)
        ]
        linear = [
            channel / 12.92
            if channel <= 0.04045
            else ((channel + 0.055) / 1.055) ** 2.4
            for channel in channels
        ]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    def contrast(first: str, second: str) -> float:
        bright, dark = sorted((luminance(first), luminance(second)), reverse=True)
        return (bright + 0.05) / (dark + 0.05)

    for theme in (LIGHT_THEME, DARK_THEME):
        assert contrast(theme.text, theme.window) >= 4.5
        assert contrast(theme.text, theme.base) >= 4.5
        assert contrast(theme.muted_text, theme.panel) >= 4.5
        assert contrast(theme.selected_text, theme.selection) >= 4.5
        assert contrast(theme.indicator_border, theme.input) >= 3.0
        assert contrast(theme.scrollbar_handle, theme.scrollbar_track) >= 3.0
        assert contrast(theme.run_text, theme.run) >= 4.5
        assert contrast(theme.stop_text, theme.stop) >= 4.5
        stylesheet = _application_stylesheet(theme)
        assert "QScrollBar:vertical" in stylesheet
        assert "QScrollBar:horizontal" in stylesheet
        assert theme.scrollbar_handle in stylesheet

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    original_palette = QtGui.QPalette(app.palette())
    original_stylesheet = app.styleSheet()
    original_scheme = app.property("colorScheme")
    try:
        for dark, expected in ((False, LIGHT_THEME), (True, DARK_THEME)):
            applied = apply_application_theme(app, dark=dark)
            assert applied is expected
            assert app.property("colorScheme") == ("dark" if dark else "light")
            assert isinstance(
                getattr(app, "_results_analysis_theme_proxy", None),
                _ThemeProxyStyle,
            )
            assert (
                app.palette().color(QtGui.QPalette.ColorRole.Window).name()
                == expected.window
            )
            button = QtWidgets.QPushButton()
            apply_run_button_style(button)
            assert button.property("buttonRole") == "run"
            label = make_muted_label("Muted", button)
            assert label.property("labelRole") == "muted"
        install_system_theme(app)
        app.styleHints().colorSchemeChanged.emit(QtCore.Qt.ColorScheme.Dark)
        assert app.property("colorScheme") == "dark"
    finally:
        app.setPalette(original_palette)
        app.setStyleSheet(original_stylesheet)
        app.setProperty("colorScheme", original_scheme)


def test_theme_proxy_paints_widget_and_item_checkboxes_consistently() -> None:
    from PySide6 import QtCore, QtGui, QtWidgets

    from results_analysis_app.styles import (
        DARK_THEME,
        _ThemeProxyStyle,
        apply_application_theme,
    )

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    apply_application_theme(app, dark=True)
    style = getattr(app, "_results_analysis_theme_proxy")

    assert style.pixelMetric(
        QtWidgets.QStyle.PixelMetric.PM_IndicatorWidth
    ) == _ThemeProxyStyle.INDICATOR_SIZE

    def render(element, checked: bool) -> QtGui.QImage:
        image = QtGui.QImage(
            20,
            20,
            QtGui.QImage.Format.Format_ARGB32,
        )
        image.fill(QtCore.Qt.GlobalColor.transparent)
        option = QtWidgets.QStyleOption()
        option.rect = QtCore.QRect(2, 2, 16, 16)
        option.state = QtWidgets.QStyle.StateFlag.State_Enabled
        if checked:
            option.state |= QtWidgets.QStyle.StateFlag.State_On
        painter = QtGui.QPainter(image)
        style.drawPrimitive(element, option, painter)
        painter.end()
        return image

    elements = (
        QtWidgets.QStyle.PrimitiveElement.PE_IndicatorCheckBox,
        QtWidgets.QStyle.PrimitiveElement.PE_IndicatorItemViewItemCheck,
    )
    for element in elements:
        unchecked = render(element, False)
        checked = render(element, True)
        assert unchecked != checked
        assert any(
            checked.pixelColor(x, y).name() == DARK_THEME.selection
            for x in range(20)
            for y in range(20)
        )
        assert any(
            checked.pixelColor(x, y).name() == DARK_THEME.selected_text
            for x in range(20)
            for y in range(20)
        )


def test_background_task_preserves_traceback() -> None:
    from results_analysis_app.background import BackgroundTask, CancelToken

    failures = []

    def fail(_log, _cancel):
        raise ValueError("nested failure")

    task = BackgroundTask(fail, CancelToken())
    task.failed.connect(lambda message, details: failures.append((message, details)))
    task.run()

    assert failures[0][0] == "nested failure"
    assert "ValueError: nested failure" in failures[0][1]
    assert "in fail" in failures[0][1]


def test_background_task_reports_cancellation_separately() -> None:
    from results_analysis_app.background import BackgroundTask, CancelToken

    cancelled = []
    failures = []
    token = CancelToken()
    token.cancel()

    def stop(_log, cancel):
        cancel.throw_if_cancelled()

    task = BackgroundTask(stop, token)
    task.cancelled.connect(lambda: cancelled.append(True))
    task.failed.connect(lambda message, details: failures.append((message, details)))
    task.run()

    assert cancelled == [True]
    assert failures == []


def test_busy_state_keeps_only_log_interactive_and_preserves_manual_scroll(
    monkeypatch,
) -> None:
    from PySide6 import QtWidgets

    from results_analysis_app import storage
    from results_analysis_app.main_window import MainWindow
    from results_analysis_app.models import AppSession

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    monkeypatch.setattr(storage, "load_autosave", AppSession.default)
    monkeypatch.setattr(MainWindow, "refresh_project_scans", lambda *_args, **_kwargs: None)
    window = MainWindow()
    window.resize(1200, 800)
    window.show()
    app.processEvents()
    try:
        window.log_edit.setPlainText("\n".join(f"old line {index}" for index in range(100)))
        app.processEvents()
        scrollbar = window.log_edit.verticalScrollBar()
        assert scrollbar.maximum() > 0

        scrollbar.setValue(0)
        window._set_busy(True, "Running")
        window.log("new line while reviewing history")
        app.processEvents()

        assert window.log_edit.isEnabled()
        assert scrollbar.value() == 0
        assert not window.preview_table.isEnabled()
        assert not window.dashboard_figure_apply_all_checkbox.isEnabled()
        assert not window.dashboard_figure_list.isEnabled()
        assert not window.left_workspace_splitter.isEnabled()
        assert not window.workspace_splitter.handle(1).isEnabled()

        scrollbar.setValue(scrollbar.maximum())
        window.log("new line while following output")
        app.processEvents()
        assert scrollbar.value() == scrollbar.maximum()
    finally:
        window._set_busy(False, "Ready")
        window.close()
        app.processEvents()


def test_dashboard_refresh_callback_preserves_failed_project_state() -> None:
    from types import SimpleNamespace

    from results_analysis_app.main_window import MainWindow

    calls = {}
    window = SimpleNamespace(
        _update_dashboard_figures=lambda result: calls.setdefault("figures", result),
        _refresh_project_status_after_action=lambda paths, **kwargs: calls.update(
            paths=list(paths), kwargs=kwargs
        ),
        _load_dashboard_figure_list=lambda _path: None,
        _current_project_path=lambda: None,
    )

    MainWindow._dashboard_refresh_finished(
        window,
        {
            "good": ([], [], True),
            "failed": ([], ["warning"], False),
        },
    )

    assert calls["paths"] == ["good"]
    assert calls["kwargs"] == {
        "refresh_dashboards": True,
        "dashboard_failed_paths": ["failed"],
    }
    assert set(calls["figures"]) == {"good", "failed"}


def test_invalid_manual_session_load_preserves_active_session(monkeypatch, tmp_path) -> None:
    from types import SimpleNamespace

    from PySide6 import QtWidgets

    from results_analysis_app import storage
    from results_analysis_app.main_window import MainWindow
    from results_analysis_app.models import AppSession

    active = AppSession.default()
    active.events = ["SFO"]
    logs = []
    warnings = []
    path = tmp_path / "invalid.analysis_session.json"
    monkeypatch.setattr(
        QtWidgets.QFileDialog,
        "getOpenFileName",
        lambda *_args, **_kwargs: (str(path), ""),
    )
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "warning",
        lambda *_args, **_kwargs: warnings.append(True),
    )
    monkeypatch.setattr(storage, "load_session", lambda _path: (_ for _ in ()).throw(TypeError("bad shape")))
    window = SimpleNamespace(session=active, log=logs.append)

    MainWindow.load_session_from_file(window)

    assert window.session is active
    assert window.session.events == ["SFO"]
    assert warnings == [True]
    assert any("could not be loaded" in message for message in logs)


def test_close_event_defers_while_worker_is_running() -> None:
    from types import SimpleNamespace

    from results_analysis_app.main_window import MainWindow

    state = {"stopped": False, "ignored": False}
    worker = SimpleNamespace(isRunning=lambda: True)
    window = SimpleNamespace(
        _worker=worker,
        _close_when_idle=False,
        stop_current_task=lambda: state.__setitem__("stopped", True),
    )
    event = SimpleNamespace(ignore=lambda: state.__setitem__("ignored", True))

    MainWindow.closeEvent(window, event)

    assert window._close_when_idle is True
    assert state == {"stopped": True, "ignored": True}
