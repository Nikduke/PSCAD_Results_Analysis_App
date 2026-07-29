from __future__ import annotations


def test_session_event_times_round_trip() -> None:
    from results_analysis_app.exclusions import ExclusionRule
    from results_analysis_app.models import AppSession

    session = AppSession.default()
    session.event_times["SFO"] = 0.005
    session.envelope_workers = 32
    session.envelope_time_step = 0.001
    session.envelope_time_end = 0.5
    session.envelope_fallback_frequency = 60.0
    session.envelope_chart_x_max = 1.0
    session.envelope_chart_x_major = 0.1
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
    project = r"C:\Project"
    session.manual_exclusions_by_project = {
        project: [
            ExclusionRule(case="C5_S1_66OFT2", run=4),
            ExclusionRule(apply=False, run=7),
            ExclusionRule(bus="MM_66_StA"),
        ]
    }
    session.disabled_nonconv_by_project = {project: [("C7_S1_66OFT2", 8)]}
    session.high_voltage_exclusions_by_project = {project: [("230", "C1", 39, "MM_230_StA")]}
    session.voltage_um_overrides_by_project = {project: {"330": 362.0}}

    loaded = AppSession.from_dict(session.to_dict())

    assert loaded.event_times["TOV"] == 0.03
    assert loaded.event_times["SFO"] == 0.005
    assert loaded.event_times["SA"] == 0.1
    assert loaded.envelope_workers == 32
    assert loaded.envelope_time_step == 0.001
    assert loaded.envelope_time_end == 0.5
    assert loaded.envelope_fallback_frequency == 60.0
    assert loaded.envelope_chart_x_max == 1.0
    assert loaded.envelope_chart_x_major == 0.1
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
    assert loaded.events == ["SFO", "TOV", "SA"]
    assert loaded.manual_exclusions_by_project == session.manual_exclusions_by_project
    assert loaded.disabled_nonconv_by_project == {project: [("C7_S1_66OFT2", 8)]}
    assert loaded.high_voltage_exclusions_by_project == {project: [("230", "C1", 39, "MM_230_StA")]}
    assert loaded.voltage_um_overrides_by_project == {project: {"330": 362.0}}
    assert "bus_exclusions_by_project" not in loaded.to_dict()
    assert "manual_case_run_exclusions_by_project" not in loaded.to_dict()


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


def test_session_default_envelope_workers_are_bounded() -> None:
    from results_analysis_app.models import AppSession

    assert AppSession.default().envelope_workers == 4


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
    from results_analysis_app.scanner import NonConvergentCase, ProjectScan

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    monkeypatch.setattr(storage, "load_autosave", AppSession.default)
    monkeypatch.setattr(MainWindow, "refresh_project_scans", lambda *_args, **_kwargs: None)
    window = MainWindow()
    try:
        tab_names = [
            window.exclusion_tabs.tabText(index)
            for index in range(window.exclusion_tabs.count())
        ]
        assert tab_names == ["Manual", "NonConv"]
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
        window.session.high_voltage_exclusions_by_project = {
            project: [("230", "C3", 3, "MM_230_StA")]
        }
        window.project_scans = {
            project: ProjectScan(
                path=Path(project),
                exists=True,
                nonconv_cases=[
                    NonConvergentCase("C1", 1),
                    NonConvergentCase("C2", 2),
                ],
            )
        }
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
