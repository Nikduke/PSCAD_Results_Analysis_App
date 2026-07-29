from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
import threading
from typing import Iterable

from PySide6 import QtCore, QtGui, QtWidgets

from results_analysis_app import (
    actions,
    project_scan_cache,
    project_scan_runner,
    reporting,
    resonance_checks,
    scanner,
    storage,
)
from results_analysis_app.background import BackgroundTask, CancelToken
from results_analysis_app.exclusions import (
    ExclusionRule,
    normalize_case_run_exclusions,
    normalize_exclusion_rules,
    normalize_high_voltage_exclusions,
)
from results_analysis_app.models import (
    DEFAULT_EVENTS,
    DEFAULT_RESONANCE_CHECKS,
    DEFAULT_VOLTAGES,
    AppSession,
    DashboardFigure,
    ProjectEntry,
    ScopeEntry,
)
from results_analysis_app.project_config import load_voltage_configs
from results_analysis_app.styles import (
    apply_choice_button_style,
    apply_run_button_style,
    apply_secondary_button_style,
    apply_stop_button_style,
    make_muted_label,
    make_section_label,
)
from results_analysis_app.voltage_envelope import FREQUENCY_FALLBACK_MESSAGE_PREFIX


USER_ROLE_PATH = QtCore.Qt.ItemDataRole.UserRole
USER_ROLE_SCOPE_FOLDER = QtCore.Qt.ItemDataRole.UserRole + 1
USER_ROLE_FIGURE_ID = QtCore.Qt.ItemDataRole.UserRole + 2


class _FrequencyFallbackPrompt:
    def __init__(self, message: str) -> None:
        self.message = message
        self.action = "continue"
        self.done = threading.Event()


class MainWindow(QtWidgets.QMainWindow):
    frequency_fallback_prompt_requested = QtCore.Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("PSCAD Results Analysis")
        self.session = storage.load_autosave()
        self.session.ensure_full_scope()
        self.project_scans: dict[str, scanner.ProjectScan] = {}
        self.dashboard_figures: dict[str, list[DashboardFigure]] = {}
        self._loading = False
        self._busy = False
        self._worker: BackgroundTask | None = None
        self._cancel_token: CancelToken | None = None
        self._close_when_idle = False
        self._frequency_fallback_prompted = False
        self._open_settings_after_task = False
        self._table_shortcuts: list[QtGui.QShortcut] = []
        self._autosave_timer = QtCore.QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.setInterval(750)
        self._autosave_timer.timeout.connect(self._save_autosave_now)

        self.frequency_fallback_prompt_requested.connect(self._show_frequency_fallback_prompt)
        self._build_ui()
        self._load_session_to_ui()
        self.refresh_project_scans()

    def _build_ui(self) -> None:
        root = QtWidgets.QWidget(self)
        self.setCentralWidget(root)
        root_layout = QtWidgets.QVBoxLayout(root)
        root_layout.setContentsMargins(6, 6, 6, 6)
        root_layout.setSpacing(6)

        root_layout.addWidget(self._build_top_bar(root))

        self.workspace_splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal, root)
        self.left_workspace_splitter = QtWidgets.QSplitter(
            QtCore.Qt.Orientation.Vertical,
            self.workspace_splitter,
        )
        self.project_scope_splitter = QtWidgets.QSplitter(
            QtCore.Qt.Orientation.Horizontal,
            self.left_workspace_splitter,
        )
        self.project_scope_splitter.addWidget(self._build_projects_panel(self.project_scope_splitter))
        self.project_scope_splitter.addWidget(self._build_scopes_panel(self.project_scope_splitter))
        self.project_scope_splitter.setStretchFactor(0, 4)
        self.project_scope_splitter.setStretchFactor(1, 7)
        self.project_scope_splitter.setSizes([400, 720])
        self.left_workspace_splitter.addWidget(self.project_scope_splitter)
        self.project_exclusions_panel = self._build_project_exclusions_panel(self.left_workspace_splitter)
        self.left_workspace_splitter.addWidget(self.project_exclusions_panel)
        self.left_workspace_splitter.setStretchFactor(0, 1)
        self.left_workspace_splitter.setStretchFactor(1, 1)
        self.left_workspace_splitter.setSizes([560, 460])
        self.workspace_splitter.addWidget(self.left_workspace_splitter)
        self.workspace_splitter.addWidget(self._build_preview_panel(self.workspace_splitter))
        self.workspace_splitter.setStretchFactor(0, 8)
        self.workspace_splitter.setStretchFactor(1, 5)
        self.workspace_splitter.setSizes([1160, 720])
        root_layout.addWidget(self.workspace_splitter, 1)
        self._build_status_bar()

    def _build_status_bar(self) -> None:
        self.status_label = QtWidgets.QLabel("Ready", self)
        self.status_label.setMinimumWidth(420)
        self.busy_progress = QtWidgets.QProgressBar(self)
        self.busy_progress.setRange(0, 0)
        self.busy_progress.setFixedWidth(160)
        self.busy_progress.setVisible(False)
        self.statusBar().addWidget(self.status_label, 1)
        self.statusBar().addPermanentWidget(self.busy_progress)

    def _panel(self, parent: QtWidgets.QWidget) -> QtWidgets.QFrame:
        panel = QtWidgets.QFrame(parent)
        panel.setObjectName("panel")
        return panel

    def _build_top_bar(self, parent: QtWidgets.QWidget) -> QtWidgets.QWidget:
        bar = self._panel(parent)
        layout = QtWidgets.QHBoxLayout(bar)
        layout.setContentsMargins(8, 5, 8, 5)
        layout.setSpacing(6)

        self.settings_button = QtWidgets.QPushButton("Settings", bar)
        self.settings_button.setMinimumWidth(88)
        apply_secondary_button_style(self.settings_button)
        self.settings_button.setToolTip("Analysis and chart settings.")
        self.settings_button.clicked.connect(self.open_settings_dialog)
        layout.addWidget(self.settings_button)

        layout.addSpacing(12)
        layout.addWidget(make_section_label("Voltages", bar))
        self.voltage_checks: dict[str, QtWidgets.QCheckBox] = {}
        self.voltage_widget = QtWidgets.QWidget(bar)
        self.voltage_layout = QtWidgets.QHBoxLayout(self.voltage_widget)
        self.voltage_layout.setContentsMargins(0, 0, 0, 0)
        self.voltage_layout.setSpacing(6)
        layout.addWidget(self.voltage_widget)

        layout.addSpacing(12)
        layout.addWidget(make_section_label("Events", bar))
        self.event_checks: dict[str, QtWidgets.QCheckBox] = {}
        for event in DEFAULT_EVENTS:
            check = QtWidgets.QCheckBox(event, bar)
            check.toggled.connect(self._on_global_selection_changed)
            self.event_checks[event] = check
            layout.addWidget(check)

        layout.addSpacing(12)
        layout.addWidget(make_section_label("Analysis", bar))
        resonance_short_labels = {
            "Post_Event_Stress": "Stress",
            "Late_Growth": "Late",
            "No_Settle_Growth": "No-settle",
        }
        self.resonance_checkboxes: dict[str, QtWidgets.QCheckBox] = {}
        for check_name in DEFAULT_RESONANCE_CHECKS:
            check = QtWidgets.QCheckBox(resonance_short_labels.get(check_name, check_name), bar)
            check.setToolTip(resonance_checks.CHECK_DEFINITIONS[check_name]["label"])
            check.toggled.connect(self._on_global_selection_changed)
            self.resonance_checkboxes[check_name] = check
            layout.addWidget(check)

        layout.addStretch(1)

        self.scan_high_voltage_log_button = QtWidgets.QPushButton("Scan HV log", bar)
        self.scan_high_voltage_log_button.setMinimumWidth(104)
        apply_secondary_button_style(self.scan_high_voltage_log_button)
        self.scan_high_voltage_log_button.setToolTip(
            "Read PSCAD_log.txt, then scan raw waveform maxima for matching case/MM buses before envelope build."
        )
        self.scan_high_voltage_log_button.clicked.connect(self.scan_high_voltage_log)
        layout.addWidget(self.scan_high_voltage_log_button)

        self.scan_dashboard_figures_button = QtWidgets.QPushButton("Scan figures", bar)
        self.scan_dashboard_figures_button.setMinimumWidth(106)
        apply_secondary_button_style(self.scan_dashboard_figures_button)
        self.scan_dashboard_figures_button.setToolTip(
            "Read dashboard chart names from existing dashboard files without refreshing Excel data."
        )
        self.scan_dashboard_figures_button.clicked.connect(self.scan_dashboard_figures)
        layout.addWidget(self.scan_dashboard_figures_button)

        self.refresh_dashboards_button = QtWidgets.QPushButton("Dashboards update", bar)
        self.refresh_dashboards_button.setMinimumWidth(148)
        apply_choice_button_style(self.refresh_dashboards_button)
        self.refresh_dashboards_button.setToolTip(
            "Refresh dashboard workbook data in Excel, then scan available dashboard figures."
        )
        self.refresh_dashboards_button.clicked.connect(self.refresh_dashboards)
        layout.addWidget(self.refresh_dashboards_button)

        self.run_full_button = QtWidgets.QPushButton("Run analysis", bar)
        self.run_full_button.setMinimumWidth(116)
        apply_run_button_style(self.run_full_button)
        self.run_full_button.setToolTip(
            "Build envelopes, create plot batches, render plots, and build reports. Dashboards are not updated."
        )
        self.run_full_button.clicked.connect(self.run_full_analysis)
        layout.addWidget(self.run_full_button)

        self.build_reports_button = QtWidgets.QPushButton("Rebuild reports", bar)
        self.build_reports_button.setMinimumWidth(128)
        apply_choice_button_style(self.build_reports_button)
        self.build_reports_button.setToolTip(
            "Create DOCX reports only. This does not run envelopes, batches, plots, or dashboard update."
        )
        self.build_reports_button.clicked.connect(self.build_reports_only)
        layout.addWidget(self.build_reports_button)

        self.stop_button = QtWidgets.QPushButton("Stop", bar)
        self.stop_button.setMinimumWidth(66)
        apply_stop_button_style(self.stop_button)
        self.stop_button.setEnabled(False)
        self.stop_button.setToolTip("Stop after the current file or Excel operation finishes.")
        self.stop_button.clicked.connect(self.stop_current_task)
        layout.addWidget(self.stop_button)

        return bar

    def _build_projects_panel(self, parent: QtWidgets.QWidget) -> QtWidgets.QWidget:
        panel = self._panel(parent)
        panel.setMinimumWidth(360)
        layout = QtWidgets.QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        layout.addWidget(make_section_label("Projects to Analyse", panel))

        controls = QtWidgets.QHBoxLayout()
        self.add_project_button = QtWidgets.QPushButton("Add", panel)
        self.delete_project_button = QtWidgets.QPushButton("Delete", panel)
        self.select_all_projects_button = QtWidgets.QPushButton("All", panel)
        self.select_no_projects_button = QtWidgets.QPushButton("None", panel)
        for button in (
            self.add_project_button,
            self.delete_project_button,
            self.select_all_projects_button,
            self.select_no_projects_button,
        ):
            apply_secondary_button_style(button)
            controls.addWidget(button)
        layout.addLayout(controls)

        self.project_tree = QtWidgets.QTreeWidget(panel)
        self.project_tree.setHeaderLabels(["Project", "Status"])
        self.project_tree.setRootIsDecorated(False)
        self.project_tree.setAlternatingRowColors(True)
        self.project_tree.setMinimumWidth(340)
        self.project_tree.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        project_header = self.project_tree.header()
        project_header.setStretchLastSection(False)
        project_header.setMinimumSectionSize(90)
        project_header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        project_header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Interactive)
        self.project_tree.setColumnWidth(1, 170)
        self.project_tree.itemChanged.connect(self._on_project_item_changed)
        self.project_tree.currentItemChanged.connect(self._on_project_selection_changed)

        layout.addWidget(self.project_tree, 1)

        session_controls = QtWidgets.QHBoxLayout()
        self.save_session_button = QtWidgets.QPushButton("Save session", panel)
        self.load_session_button = QtWidgets.QPushButton("Load session", panel)
        self.clear_session_button = QtWidgets.QPushButton("Clear session", panel)
        apply_secondary_button_style(self.save_session_button)
        apply_secondary_button_style(self.load_session_button)
        apply_secondary_button_style(self.clear_session_button)
        session_controls.addWidget(self.save_session_button)
        session_controls.addWidget(self.load_session_button)
        session_controls.addWidget(self.clear_session_button)
        layout.addLayout(session_controls)

        self.add_project_button.clicked.connect(self.add_project)
        self.delete_project_button.clicked.connect(self.delete_selected_projects)
        self.select_all_projects_button.clicked.connect(lambda: self._set_all_projects(True))
        self.select_no_projects_button.clicked.connect(lambda: self._set_all_projects(False))
        self.save_session_button.clicked.connect(self.save_session_as)
        self.load_session_button.clicked.connect(self.load_session_from_file)
        self.clear_session_button.clicked.connect(self.clear_session)
        return panel

    def _build_project_exclusions_panel(self, parent: QtWidgets.QWidget) -> QtWidgets.QWidget:
        box = QtWidgets.QGroupBox("Project Exclusions", parent)
        layout = QtWidgets.QVBoxLayout(box)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)
        self.project_exclusion_label = make_muted_label("Select a project.", box)
        layout.addWidget(self.project_exclusion_label)

        self.exclusion_tabs = QtWidgets.QTabWidget(box)
        tabs = self.exclusion_tabs

        manual_tab = QtWidgets.QWidget(tabs)
        manual_layout = QtWidgets.QVBoxLayout(manual_tab)
        manual_layout.setContentsMargins(6, 6, 6, 6)
        self.manual_exclusion_table = QtWidgets.QTableWidget(0, 4, manual_tab)
        self._configure_exclusion_table(
            self.manual_exclusion_table,
            ["Apply", "Case", "Run", "Bus"],
            editable=True,
        )
        manual_header = self.manual_exclusion_table.horizontalHeader()
        manual_header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Stretch)
        manual_header.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.Fixed)
        manual_header.setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.manual_exclusion_table.setColumnWidth(2, 64)
        self.manual_exclusion_table.itemChanged.connect(self._on_manual_exclusion_table_changed)
        self._enable_table_clipboard(self.manual_exclusion_table, paste=True)
        manual_layout.addWidget(self.manual_exclusion_table)
        manual_buttons = QtWidgets.QHBoxLayout()
        self.add_manual_exclusion_button = QtWidgets.QPushButton("Add", manual_tab)
        self.delete_manual_exclusion_button = QtWidgets.QPushButton("Delete", manual_tab)
        apply_secondary_button_style(self.add_manual_exclusion_button)
        apply_secondary_button_style(self.delete_manual_exclusion_button)
        self.add_manual_exclusion_button.clicked.connect(self._add_manual_exclusion_row)
        self.delete_manual_exclusion_button.clicked.connect(self._delete_manual_exclusion_rows)
        manual_buttons.addWidget(self.add_manual_exclusion_button)
        manual_buttons.addWidget(self.delete_manual_exclusion_button)
        manual_buttons.addStretch(1)
        self._add_apply_buttons(
            manual_buttons,
            manual_tab,
            self.manual_exclusion_table,
            "manual exclusion",
        )
        manual_layout.addLayout(manual_buttons)
        tabs.addTab(manual_tab, "Manual")

        nonconv_tab = QtWidgets.QWidget(tabs)
        nonconv_layout = QtWidgets.QVBoxLayout(nonconv_tab)
        nonconv_layout.setContentsMargins(6, 6, 6, 6)
        self.nonconv_proposal_table = QtWidgets.QTableWidget(0, 6, nonconv_tab)
        self._configure_exclusion_table(
            self.nonconv_proposal_table,
            ["Apply", "Case", "Run", "Fault", "Signal", "Reason"],
        )
        nonconv_header = self.nonconv_proposal_table.horizontalHeader()
        nonconv_header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Interactive)
        nonconv_header.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.Fixed)
        nonconv_header.setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeMode.Fixed)
        nonconv_header.setSectionResizeMode(4, QtWidgets.QHeaderView.ResizeMode.Interactive)
        nonconv_header.setSectionResizeMode(5, QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.nonconv_proposal_table.setColumnWidth(1, 150)
        self.nonconv_proposal_table.setColumnWidth(2, 54)
        self.nonconv_proposal_table.setColumnWidth(3, 70)
        self.nonconv_proposal_table.setColumnWidth(4, 110)
        self.nonconv_proposal_table.itemChanged.connect(self._on_nonconv_table_changed)
        self._enable_table_clipboard(self.nonconv_proposal_table)
        nonconv_layout.addWidget(self.nonconv_proposal_table)
        nonconv_buttons = QtWidgets.QHBoxLayout()
        nonconv_buttons.addStretch(1)
        self._add_apply_buttons(
            nonconv_buttons,
            nonconv_tab,
            self.nonconv_proposal_table,
            "non-convergent exclusion",
        )
        nonconv_layout.addLayout(nonconv_buttons)
        tabs.addTab(nonconv_tab, "NonConv")

        self.high_voltage_tab = QtWidgets.QWidget(tabs)
        high_layout = QtWidgets.QVBoxLayout(self.high_voltage_tab)
        high_layout.setContentsMargins(6, 6, 6, 6)
        self.high_voltage_proposal_table = QtWidgets.QTableWidget(0, 8, self.high_voltage_tab)
        self._configure_exclusion_table(
            self.high_voltage_proposal_table,
            ["Apply", "kV", "Case", "Run", "Bus", "Max", "Limit", "Signal"],
        )
        high_header = self.high_voltage_proposal_table.horizontalHeader()
        high_header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Fixed)
        high_header.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.Interactive)
        high_header.setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeMode.Fixed)
        high_header.setSectionResizeMode(4, QtWidgets.QHeaderView.ResizeMode.Stretch)
        high_header.setSectionResizeMode(5, QtWidgets.QHeaderView.ResizeMode.Fixed)
        high_header.setSectionResizeMode(6, QtWidgets.QHeaderView.ResizeMode.Fixed)
        high_header.setSectionResizeMode(7, QtWidgets.QHeaderView.ResizeMode.Interactive)
        self.high_voltage_proposal_table.setColumnWidth(1, 52)
        self.high_voltage_proposal_table.setColumnWidth(2, 150)
        self.high_voltage_proposal_table.setColumnWidth(3, 54)
        self.high_voltage_proposal_table.setColumnWidth(5, 82)
        self.high_voltage_proposal_table.setColumnWidth(6, 82)
        self.high_voltage_proposal_table.setColumnWidth(7, 112)
        self.high_voltage_proposal_table.itemChanged.connect(self._on_high_voltage_table_changed)
        self._enable_table_clipboard(self.high_voltage_proposal_table)
        high_layout.addWidget(self.high_voltage_proposal_table)
        high_buttons = QtWidgets.QHBoxLayout()
        high_buttons.addStretch(1)
        self._add_apply_buttons(
            high_buttons,
            self.high_voltage_tab,
            self.high_voltage_proposal_table,
            "high-voltage exclusion",
        )
        high_layout.addLayout(high_buttons)
        tabs.addTab(self.high_voltage_tab, "High Voltage")

        layout.addWidget(tabs)
        return box

    def _configure_exclusion_table(
        self,
        table: QtWidgets.QTableWidget,
        headers: list[str],
        *,
        editable: bool = False,
    ) -> None:
        table.setHorizontalHeaderLabels(headers)
        table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        table.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.AllEditTriggers
            if editable
            else QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers
        )
        table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Fixed)
        table.setColumnWidth(0, 56)

    def _add_apply_buttons(
        self,
        layout: QtWidgets.QHBoxLayout,
        parent: QtWidgets.QWidget,
        table: QtWidgets.QTableWidget,
        row_name: str,
    ) -> None:
        apply_all = QtWidgets.QPushButton("Apply all", parent)
        apply_none = QtWidgets.QPushButton("Apply none", parent)
        apply_all.setToolTip(f"Check every {row_name} row.")
        apply_none.setToolTip(f"Uncheck every {row_name} row.")
        apply_secondary_button_style(apply_all)
        apply_secondary_button_style(apply_none)
        apply_all.clicked.connect(
            lambda _checked=False, target=table: self._set_all_exclusion_rows_checked(
                target,
                True,
            )
        )
        apply_none.clicked.connect(
            lambda _checked=False, target=table: self._set_all_exclusion_rows_checked(
                target,
                False,
            )
        )
        layout.addWidget(apply_all)
        layout.addWidget(apply_none)

    def _build_scopes_panel(self, parent: QtWidgets.QWidget) -> QtWidgets.QWidget:
        panel = self._panel(parent)
        panel.setMinimumWidth(460)
        layout = QtWidgets.QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        layout.addWidget(make_section_label("Scopes", panel))
        layout.addWidget(
            make_muted_label("Scopes are token filters. Voltages and events are global.", panel)
        )

        self.scope_list = QtWidgets.QListWidget(panel)
        self.scope_list.itemChanged.connect(self._on_scope_item_changed)
        self.scope_list.currentItemChanged.connect(lambda _new, _old: self.update_preview())
        layout.addWidget(self.scope_list, 1)

        self.scope_tokens_edit = QtWidgets.QLineEdit(panel)
        self.scope_tokens_edit.setPlaceholderText("Tokens, for example: C25, C23")
        layout.addWidget(self.scope_tokens_edit)

        scope_controls = QtWidgets.QGridLayout()
        self.add_exclude_scope_button = QtWidgets.QPushButton("Add Exclude", panel)
        self.add_include_scope_button = QtWidgets.QPushButton("Add Include", panel)
        self.rename_scope_button = QtWidgets.QPushButton("Rename", panel)
        self.delete_scope_button = QtWidgets.QPushButton("Delete", panel)
        for button in (
            self.add_exclude_scope_button,
            self.add_include_scope_button,
            self.rename_scope_button,
            self.delete_scope_button,
        ):
            apply_secondary_button_style(button)
        scope_controls.addWidget(self.add_exclude_scope_button, 0, 0)
        scope_controls.addWidget(self.add_include_scope_button, 0, 1)
        scope_controls.addWidget(self.rename_scope_button, 1, 0)
        scope_controls.addWidget(self.delete_scope_button, 1, 1)
        layout.addLayout(scope_controls)

        advanced = QtWidgets.QGroupBox("Analysis Steps", panel)
        advanced_layout = QtWidgets.QVBoxLayout(advanced)
        self.build_envelopes_button = QtWidgets.QPushButton("Build envelope data/checks", advanced)
        apply_secondary_button_style(self.build_envelopes_button)
        advanced_layout.addWidget(self.build_envelopes_button)
        step_columns = QtWidgets.QHBoxLayout()
        event_steps = QtWidgets.QGroupBox("TOV/SFO/SA", advanced)
        event_layout = QtWidgets.QVBoxLayout(event_steps)
        analysis_steps = QtWidgets.QGroupBox("Analysis", advanced)
        analysis_layout = QtWidgets.QVBoxLayout(analysis_steps)

        self.rebuild_envelope_charts_button = QtWidgets.QPushButton("Rebuild charts", event_steps)
        self.create_event_batches_button = QtWidgets.QPushButton("Create batches", event_steps)
        self.render_event_plots_button = QtWidgets.QPushButton("Render plots", event_steps)
        self.rebuild_analysis_charts_button = QtWidgets.QPushButton("Rebuild charts", analysis_steps)
        self.create_analysis_batches_button = QtWidgets.QPushButton("Create batches", analysis_steps)
        self.render_analysis_plots_button = QtWidgets.QPushButton("Render plots", analysis_steps)
        for button in (self.rebuild_envelope_charts_button, self.create_event_batches_button, self.render_event_plots_button):
            apply_secondary_button_style(button)
            event_layout.addWidget(button)
        for button in (self.rebuild_analysis_charts_button, self.create_analysis_batches_button, self.render_analysis_plots_button):
            apply_secondary_button_style(button)
            analysis_layout.addWidget(button)
        step_columns.addWidget(event_steps)
        step_columns.addWidget(analysis_steps)
        advanced_layout.addLayout(step_columns)

        self.build_envelopes_button.setToolTip("Build voltage envelope data workbooks and selected analysis checks. Existing chart workbooks are not rebuilt.")
        self.rebuild_envelope_charts_button.setToolTip("Recreate combined envelope chart workbooks from existing envelope workbooks.")
        self.create_event_batches_button.setToolTip("Create SFO/TOV/SA plot batch workbooks from existing envelopes.")
        self.render_event_plots_button.setToolTip("Render SFO/TOV/SA plots from existing event batch workbooks.")
        self.rebuild_analysis_charts_button.setToolTip("Recreate analysis charts inside existing Resonance_Checks.xlsx workbooks.")
        self.create_analysis_batches_button.setToolTip("Create analysis plot batch workbooks from Resonance_Checks.xlsx.")
        self.render_analysis_plots_button.setToolTip("Render analysis plots from existing analysis batch workbooks.")
        layout.addWidget(advanced)

        self.add_exclude_scope_button.clicked.connect(lambda: self.add_scope("exclude"))
        self.add_include_scope_button.clicked.connect(lambda: self.add_scope("include"))
        self.rename_scope_button.clicked.connect(self.rename_selected_scope)
        self.delete_scope_button.clicked.connect(self.delete_selected_scope)
        self.build_envelopes_button.clicked.connect(self.build_envelopes_only)
        self.rebuild_envelope_charts_button.clicked.connect(self.rebuild_envelope_charts_only)
        self.create_event_batches_button.clicked.connect(self.create_event_batches_only)
        self.render_event_plots_button.clicked.connect(self.render_event_plots_only)
        self.rebuild_analysis_charts_button.clicked.connect(self.rebuild_analysis_charts_only)
        self.create_analysis_batches_button.clicked.connect(self.create_analysis_batches_only)
        self.render_analysis_plots_button.clicked.connect(self.render_analysis_plots_only)
        return panel

    def _build_preview_panel(self, parent: QtWidgets.QWidget) -> QtWidgets.QWidget:
        panel = self._panel(parent)
        layout = QtWidgets.QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        layout.addWidget(make_section_label("Preview and Run Log", panel))

        self.preview_table = QtWidgets.QTableWidget(panel)
        self.preview_table.setColumnCount(5)
        self.preview_table.setHorizontalHeaderLabels(
            ["Project", "Scope", "Cases", "Outputs", "Warnings"]
        )
        preview_header = self.preview_table.horizontalHeader()
        preview_header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Interactive)
        preview_header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Fixed)
        preview_header.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.Fixed)
        preview_header.setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeMode.Stretch)
        preview_header.setSectionResizeMode(4, QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.preview_table.setColumnWidth(0, 160)
        self.preview_table.setColumnWidth(1, 64)
        self.preview_table.setColumnWidth(2, 62)
        self.preview_table.setWordWrap(False)
        self.preview_table.setTextElideMode(QtCore.Qt.TextElideMode.ElideMiddle)
        self.preview_table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.preview_table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._enable_table_clipboard(self.preview_table)
        layout.addWidget(self.preview_table, 2)

        layout.addWidget(make_section_label("Dashboard Figures Shared Across Projects", panel))
        layout.addWidget(
            make_muted_label(
                "Choose once. Matching figures are used for every selected project report.",
                panel,
            )
        )
        self.dashboard_figure_list = QtWidgets.QListWidget(panel)
        self.dashboard_figure_list.itemChanged.connect(self._on_dashboard_figure_item_changed)
        layout.addWidget(self.dashboard_figure_list, 1)

        layout.addWidget(make_section_label("Log", panel))
        self.log_edit = QtWidgets.QPlainTextEdit(panel)
        self.log_edit.setReadOnly(True)
        layout.addWidget(self.log_edit, 1)
        return panel

    def _load_session_to_ui(self) -> None:
        was_loading = self._loading
        self._loading = True
        try:
            self._set_voltage_options(self.session.voltages or DEFAULT_VOLTAGES, self.session.voltages)
            for voltage, check in self.voltage_checks.items():
                check.setChecked(voltage in self.session.voltages)
            for event, check in self.event_checks.items():
                check.setChecked(event in self.session.events)
            for check_name, check in self.resonance_checkboxes.items():
                check.setChecked(check_name in self.session.resonance_enabled_checks)
            self._reload_project_tree()
            self._reload_scope_list()
            self._reload_project_exclusions()
        finally:
            self._loading = was_loading

    def open_settings_dialog(self, initial_tab: str | None = None) -> None:
        from results_analysis_app.settings_dialog import edit_settings

        edit_settings(self, initial_tab)


    def _set_voltage_options(
        self,
        voltages: Iterable[str],
        selected: Iterable[str] | None = None,
    ) -> None:
        options = self._sorted_voltages(voltages)
        if not options:
            options = list(DEFAULT_VOLTAGES)
        selected_values = set(selected if selected is not None else self.session.voltages)
        if not selected_values:
            selected_values = set(options)

        was_loading = self._loading
        self._loading = True
        try:
            while self.voltage_layout.count():
                item = self.voltage_layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()
            self.voltage_checks = {}
            for voltage in options:
                check = QtWidgets.QCheckBox(voltage, self.voltage_widget)
                check.setChecked(voltage in selected_values)
                check.toggled.connect(self._on_global_selection_changed)
                self.voltage_checks[voltage] = check
                self.voltage_layout.addWidget(check)
        finally:
            self._loading = was_loading
        if not self._loading:
            self._sync_global_selections_from_ui()

    def _sorted_voltages(self, voltages: Iterable[str]) -> list[str]:
        unique = {str(voltage).strip() for voltage in voltages if str(voltage).strip()}
        return sorted(unique, key=self._voltage_sort_key)

    def _is_number(self, value: str) -> bool:
        try:
            float(value)
        except ValueError:
            return False
        return True

    def _reload_project_tree(self) -> None:
        self.project_tree.clear()
        for project in self.session.projects:
            item = QtWidgets.QTreeWidgetItem(self.project_tree)
            item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                0,
                QtCore.Qt.CheckState.Checked
                if project.selected
                else QtCore.Qt.CheckState.Unchecked,
            )
            item.setText(0, project.name)
            item.setData(0, USER_ROLE_PATH, project.path)
            status_text = ", ".join(self.session.status_cache.get(project.path, []))
            item.setText(1, status_text)
            item.setToolTip(0, project.path)
            item.setToolTip(1, status_text)
        self.project_tree.setColumnWidth(1, 180)
        if self.project_tree.columnWidth(0) < 260:
            self.project_tree.setColumnWidth(0, 260)

    def _reload_scope_list(self) -> None:
        self.scope_list.clear()
        for scope in self.session.scopes:
            item = QtWidgets.QListWidgetItem(self._scope_item_text(scope), self.scope_list)
            item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                QtCore.Qt.CheckState.Checked
                if scope.selected
                else QtCore.Qt.CheckState.Unchecked
            )
            item.setData(USER_ROLE_SCOPE_FOLDER, scope.folder)
            item.setToolTip(self._scope_item_text(scope))

    def _scope_item_text(self, scope: ScopeEntry) -> str:
        return f"{scope.name}    [{scope.folder}]    {scope.description}"

    def _sync_global_selections_from_ui(self) -> None:
        self.session.voltages = [
            voltage for voltage, check in self.voltage_checks.items() if check.isChecked()
        ]
        self.session.events = [
            event for event, check in self.event_checks.items() if check.isChecked()
        ]
        self.session.resonance_enabled_checks = [
            check_name
            for check_name, check in self.resonance_checkboxes.items()
            if check.isChecked()
        ]
        self._save_current_project_exclusions()

    def _voltage_sort_key(self, value: str) -> tuple[int, float | str]:
        return (0, float(value)) if self._is_number(value) else (1, value)

    def _selected_scan(self) -> scanner.ProjectScan | None:
        project_path = self._current_project_path()
        return self.project_scans.get(project_path) if project_path is not None else None

    def _reload_project_exclusions(self) -> None:
        project_path = self._current_project_path()
        scan = self._selected_scan()
        was_loading = self._loading
        self._loading = True
        try:
            if project_path is None:
                self.project_exclusion_label.setText("Select a project.")
            else:
                self.project_exclusion_label.setText(Path(project_path).name)
            self._set_manual_exclusion_rows(
                self.session.manual_exclusions_by_project.get(project_path or "", [])
            )
            self._set_nonconv_proposal_rows(scan.nonconv_cases if scan else [])
            self._set_high_voltage_proposal_rows(scan.high_voltage_exclusions if scan else [])
        finally:
            self._loading = was_loading

    @contextmanager
    def _table_bulk_update(self, table: QtWidgets.QTableWidget):
        blocker = QtCore.QSignalBlocker(table)
        table.setUpdatesEnabled(False)
        try:
            yield
        finally:
            table.setUpdatesEnabled(True)
            del blocker

    def _set_manual_exclusion_rows(self, rows: list[ExclusionRule]) -> None:
        normalized = normalize_exclusion_rules(rows)
        with self._table_bulk_update(self.manual_exclusion_table):
            self.manual_exclusion_table.setRowCount(len(normalized))
            for row, rule in enumerate(normalized):
                self.manual_exclusion_table.setItem(
                    row,
                    0,
                    self._checkbox_item(
                        rule.apply,
                        "Checked rows are excluded from envelope builds.",
                    ),
                )
                for column, value in enumerate(
                    (rule.case, "" if rule.run is None else rule.run, rule.bus),
                    start=1,
                ):
                    self.manual_exclusion_table.setItem(
                        row,
                        column,
                        self._editable_table_item(value),
                    )

    def _checkbox_item(self, checked: bool, tooltip: str) -> QtWidgets.QTableWidgetItem:
        item = QtWidgets.QTableWidgetItem("")
        item.setFlags(
            QtCore.Qt.ItemFlag.ItemIsEnabled
            | QtCore.Qt.ItemFlag.ItemIsSelectable
            | QtCore.Qt.ItemFlag.ItemIsUserCheckable
        )
        item.setCheckState(
            QtCore.Qt.CheckState.Checked if checked else QtCore.Qt.CheckState.Unchecked
        )
        item.setToolTip(tooltip)
        return item

    def _table_item(self, value: object) -> QtWidgets.QTableWidgetItem:
        text = str(value)
        item = QtWidgets.QTableWidgetItem(text)
        item.setToolTip(text)
        item.setFlags(QtCore.Qt.ItemFlag.ItemIsEnabled | QtCore.Qt.ItemFlag.ItemIsSelectable)
        return item

    def _editable_table_item(self, value: object = "") -> QtWidgets.QTableWidgetItem:
        text = str(value)
        item = QtWidgets.QTableWidgetItem(text)
        item.setToolTip(text)
        return item

    def _set_nonconv_proposal_rows(self, rows: list[scanner.NonConvergentCase]) -> None:
        project_path = self._current_project_path() or ""
        disabled = set(self.session.disabled_nonconv_by_project.get(project_path, []))
        prepared_rows = []
        for proposal in rows:
            key = normalize_case_run_exclusions([(proposal.case, proposal.run)])
            prepared_rows.append(
                (
                    not key or key[0] not in disabled,
                    (proposal.case, str(proposal.run), proposal.fault_type, proposal.signal, proposal.reason),
                )
            )
        with self._table_bulk_update(self.nonconv_proposal_table):
            self.nonconv_proposal_table.setRowCount(len(prepared_rows))
            for row, (checked, values) in enumerate(prepared_rows):
                self.nonconv_proposal_table.setItem(
                    row,
                    0,
                    self._checkbox_item(checked, "Checked rows are excluded from envelope builds."),
                )
                for column, value in enumerate(values, start=1):
                    self.nonconv_proposal_table.setItem(row, column, self._table_item(value))

    def _set_high_voltage_proposal_rows(self, rows: list[scanner.HighVoltageExclusion]) -> None:
        project_path = self._current_project_path() or ""
        applied = set(
            normalize_high_voltage_exclusions(
                self.session.high_voltage_exclusions_by_project.get(project_path, [])
            )
        )
        seen: set[tuple[str, str, int, str]] = set()
        prepared_rows = []
        for proposal in rows:
            normalized = normalize_high_voltage_exclusions(
                [(proposal.voltage, proposal.case, proposal.run, proposal.bus)]
            )
            if not normalized:
                continue
            key = normalized[0]
            seen.add(key)
            prepared_rows.append(
                (
                    key in applied,
                    (
                        proposal.voltage,
                        proposal.case,
                        str(proposal.run),
                        proposal.bus,
                        proposal.max_abs,
                        proposal.limit,
                        proposal.signal,
                    ),
                )
            )

        for voltage, case, run, bus in sorted(applied - seen, key=lambda item: (item[0], item[1], item[2], item[3])):
            prepared_rows.append((True, (voltage, case, str(run), bus, "", "", "")))

        with self._table_bulk_update(self.high_voltage_proposal_table):
            self.high_voltage_proposal_table.setRowCount(len(prepared_rows))
            for row, (checked, values) in enumerate(prepared_rows):
                self.high_voltage_proposal_table.setItem(
                    row,
                    0,
                    self._checkbox_item(
                        checked,
                        "Checked rows are excluded from envelope builds.",
                    ),
                )
                for column, value in enumerate(values, start=1):
                    self.high_voltage_proposal_table.setItem(row, column, self._table_item(value))
        self._set_high_voltage_ui_visible(bool(rows or applied))

    def _set_high_voltage_ui_visible(self, visible: bool) -> None:
        index = self.exclusion_tabs.indexOf(self.high_voltage_tab)
        if visible and index < 0:
            self.exclusion_tabs.addTab(self.high_voltage_tab, "High Voltage")
        elif not visible and index >= 0:
            self.exclusion_tabs.removeTab(index)

    def _append_manual_exclusion_row(self, rule: ExclusionRule | None = None) -> int:
        rule = rule or ExclusionRule()
        row = self.manual_exclusion_table.rowCount()
        self.manual_exclusion_table.insertRow(row)
        self.manual_exclusion_table.setItem(
            row,
            0,
            self._checkbox_item(
                rule.apply,
                "Checked rows are excluded from envelope builds.",
            ),
        )
        for column, value in enumerate(
            (rule.case, "" if rule.run is None else rule.run, rule.bus),
            start=1,
        ):
            self.manual_exclusion_table.setItem(
                row,
                column,
                self._editable_table_item(value),
            )
        return row

    def _enable_table_clipboard(
        self,
        table: QtWidgets.QTableWidget,
        *,
        paste: bool = False,
    ) -> None:
        shortcut = QtGui.QShortcut(QtGui.QKeySequence.StandardKey.Copy, table)
        shortcut.setContext(QtCore.Qt.ShortcutContext.WidgetWithChildrenShortcut)
        shortcut.activated.connect(lambda checked=False, target=table: self._copy_table_selection(target))
        self._table_shortcuts.append(shortcut)
        if paste:
            paste_shortcut = QtGui.QShortcut(QtGui.QKeySequence.StandardKey.Paste, table)
            paste_shortcut.setContext(QtCore.Qt.ShortcutContext.WidgetWithChildrenShortcut)
            paste_shortcut.activated.connect(self._paste_manual_exclusions)
            self._table_shortcuts.append(paste_shortcut)

    def _table_clipboard_value(self, table: QtWidgets.QTableWidget, row: int, column: int) -> str:
        item = table.item(row, column)
        if item is None:
            return ""
        if item.flags() & QtCore.Qt.ItemFlag.ItemIsUserCheckable and not item.text():
            return "Yes" if item.checkState() == QtCore.Qt.CheckState.Checked else "No"
        return item.text()

    def _copy_table_selection(self, table: QtWidgets.QTableWidget) -> None:
        indexes = table.selectedIndexes()
        if not indexes:
            return
        rows = sorted({index.row() for index in indexes})
        columns = sorted({index.column() for index in indexes})
        lines: list[str] = []
        if len(rows) == table.rowCount() and len(columns) == table.columnCount():
            lines.append(
                "\t".join(
                    table.horizontalHeaderItem(column).text()
                    if table.horizontalHeaderItem(column) is not None
                    else ""
                    for column in columns
                )
            )
        for row in rows:
            lines.append(
                "\t".join(self._table_clipboard_value(table, row, column) for column in columns)
            )
        QtWidgets.QApplication.clipboard().setText("\n".join(lines))

    def _selected_rows(self, table: QtWidgets.QTableWidget) -> list[int]:
        return sorted({index.row() for index in table.selectedIndexes()}, reverse=True)

    def _manual_exclusion_rows(self) -> list[ExclusionRule]:
        rows: list[dict[str, object]] = []
        for row in range(self.manual_exclusion_table.rowCount()):
            apply_item = self.manual_exclusion_table.item(row, 0)
            values = [
                self.manual_exclusion_table.item(row, column).text()
                if self.manual_exclusion_table.item(row, column) is not None
                else ""
                for column in range(1, 4)
            ]
            rows.append(
                {
                    "apply": (
                        apply_item is not None
                        and apply_item.checkState() == QtCore.Qt.CheckState.Checked
                    ),
                    "case": values[0],
                    "run": values[1],
                    "bus": values[2],
                }
            )
        return normalize_exclusion_rules(rows)

    def _paste_manual_exclusions(self) -> None:
        lines = [
            line.split("\t")
            for line in QtWidgets.QApplication.clipboard().text().splitlines()
            if line.strip()
        ]
        if not lines:
            return

        header_names = {"apply", "case", "run", "bus"}
        first = [value.strip().casefold() for value in lines[0]]
        has_header = (
            all(value in header_names for value in first)
            and (len(first) > 1 or first == ["apply"])
        )
        if has_header:
            column_map = {
                source: ("apply", "case", "run", "bus").index(name)
                for source, name in enumerate(first)
            }
            data_rows = lines[1:]
        else:
            current_column = self.manual_exclusion_table.currentColumn()
            if current_column < 0:
                current_column = 0 if len(first) >= 4 else 1
            column_map = {
                source: current_column + source
                for source in range(len(first))
                if current_column + source < self.manual_exclusion_table.columnCount()
            }
            data_rows = lines
        if not data_rows:
            return

        start_row = self.manual_exclusion_table.currentRow()
        if start_row < 0:
            start_row = self.manual_exclusion_table.rowCount()
        with self._table_bulk_update(self.manual_exclusion_table):
            for offset, values in enumerate(data_rows):
                target_row = start_row + offset
                while target_row >= self.manual_exclusion_table.rowCount():
                    self._append_manual_exclusion_row()
                for source_column, value in enumerate(values):
                    target_column = column_map.get(source_column)
                    if target_column is None:
                        continue
                    if target_column == 0:
                        checked = value.strip().casefold() not in {
                            "0",
                            "false",
                            "no",
                            "off",
                            "unchecked",
                            "none",
                        }
                        item = self.manual_exclusion_table.item(target_row, 0)
                        if item is not None:
                            item.setCheckState(
                                QtCore.Qt.CheckState.Checked
                                if checked
                                else QtCore.Qt.CheckState.Unchecked
                            )
                    else:
                        item = self.manual_exclusion_table.item(target_row, target_column)
                        if item is None:
                            item = self._editable_table_item()
                            self.manual_exclusion_table.setItem(target_row, target_column, item)
                        item.setText(value.strip())
                        item.setToolTip(value.strip())
        self._on_project_exclusions_changed()

    def _disabled_nonconv_rows(self) -> list[tuple[str, int]]:
        rows: list[tuple[str, int]] = []
        for row in range(self.nonconv_proposal_table.rowCount()):
            apply_item = self.nonconv_proposal_table.item(row, 0)
            if apply_item is None or apply_item.checkState() == QtCore.Qt.CheckState.Checked:
                continue
            case_item = self.nonconv_proposal_table.item(row, 1)
            run_item = self.nonconv_proposal_table.item(row, 2)
            if case_item is not None and run_item is not None:
                rows.append((case_item.text(), run_item.text()))
        return normalize_case_run_exclusions(rows)

    def _high_voltage_rows(self) -> list[tuple[str, str, int, str]]:
        rows: list[tuple[str, str, str, str]] = []
        for row in range(self.high_voltage_proposal_table.rowCount()):
            apply_item = self.high_voltage_proposal_table.item(row, 0)
            if apply_item is None or apply_item.checkState() != QtCore.Qt.CheckState.Checked:
                continue
            values = [
                self.high_voltage_proposal_table.item(row, column).text()
                if self.high_voltage_proposal_table.item(row, column) is not None
                else ""
                for column in range(1, 5)
            ]
            rows.append((values[0], values[1], values[2], values[3]))
        return normalize_high_voltage_exclusions(rows)

    def _save_current_project_exclusions(self) -> None:
        project_path = self._current_project_path()
        if project_path is None:
            return
        manual_exclusions = self._manual_exclusion_rows()
        if manual_exclusions:
            self.session.manual_exclusions_by_project[project_path] = manual_exclusions
        else:
            self.session.manual_exclusions_by_project.pop(project_path, None)

        disabled_nonconv = self._disabled_nonconv_rows()
        if disabled_nonconv:
            self.session.disabled_nonconv_by_project[project_path] = disabled_nonconv
        else:
            self.session.disabled_nonconv_by_project.pop(project_path, None)

        high_voltage = self._high_voltage_rows()
        if high_voltage:
            self.session.high_voltage_exclusions_by_project[project_path] = high_voltage
        else:
            self.session.high_voltage_exclusions_by_project.pop(project_path, None)

    def _on_project_exclusions_changed(self) -> None:
        if self._loading:
            return
        self._save_current_project_exclusions()
        self.autosave()

    def _on_manual_exclusion_table_changed(
        self,
        _item: QtWidgets.QTableWidgetItem,
    ) -> None:
        self._on_project_exclusions_changed()

    def _on_nonconv_table_changed(self, item: QtWidgets.QTableWidgetItem) -> None:
        if item.column() == 0:
            self._on_project_exclusions_changed()

    def _on_high_voltage_table_changed(self, item: QtWidgets.QTableWidgetItem) -> None:
        if item.column() == 0:
            self._on_project_exclusions_changed()

    def _set_all_exclusion_rows_checked(
        self,
        table: QtWidgets.QTableWidget,
        checked: bool,
    ) -> None:
        was_loading = self._loading
        self._loading = True
        try:
            with self._table_bulk_update(table):
                for row in range(table.rowCount()):
                    item = table.item(row, 0)
                    if item is not None:
                        item.setCheckState(
                            QtCore.Qt.CheckState.Checked
                            if checked
                            else QtCore.Qt.CheckState.Unchecked
                        )
        finally:
            self._loading = was_loading
        self._on_project_exclusions_changed()

    def _add_manual_exclusion_row(self) -> None:
        with self._table_bulk_update(self.manual_exclusion_table):
            row = self._append_manual_exclusion_row()
        self.manual_exclusion_table.setCurrentCell(row, 1)
        self.manual_exclusion_table.editItem(self.manual_exclusion_table.item(row, 1))
        self._on_project_exclusions_changed()

    def _delete_manual_exclusion_rows(self) -> None:
        for row in self._selected_rows(self.manual_exclusion_table):
            self.manual_exclusion_table.removeRow(row)
        self._on_project_exclusions_changed()

    def _on_global_selection_changed(self) -> None:
        if self._loading:
            return
        self._sync_global_selections_from_ui()
        self.autosave()
        self.update_preview()

    def _on_project_item_changed(self, item: QtWidgets.QTreeWidgetItem, column: int) -> None:
        if self._loading or column != 0:
            return
        path = item.data(0, USER_ROLE_PATH)
        for project in self.session.projects:
            if project.path == path:
                project.selected = item.checkState(0) == QtCore.Qt.CheckState.Checked
                break
        self._update_voltage_options_from_scans()
        self.autosave()
        self.update_preview()

    def _on_project_selection_changed(
        self,
        current: QtWidgets.QTreeWidgetItem | None,
        _previous: QtWidgets.QTreeWidgetItem | None,
    ) -> None:
        if current is None:
            self._load_dashboard_figure_list(None)
            self._reload_project_exclusions()
            return
        self._load_dashboard_figure_list(str(current.data(0, USER_ROLE_PATH)))
        self._reload_project_exclusions()
        self.update_preview()

    def _on_scope_item_changed(self, item: QtWidgets.QListWidgetItem) -> None:
        if self._loading:
            return
        folder = item.data(USER_ROLE_SCOPE_FOLDER)
        for scope in self.session.scopes:
            if scope.folder == folder:
                scope.selected = item.checkState() == QtCore.Qt.CheckState.Checked
                break
        self.autosave()
        self.update_preview()

    def _on_dashboard_figure_item_changed(self, item: QtWidgets.QListWidgetItem) -> None:
        if self._loading:
            return
        checked = self._checked_dashboard_figure_ids()
        self.session.dashboard_figure_selection = checked
        self.session.dashboard_figure_selection_initialized = True
        self.autosave()

    def _current_project_path(self) -> str | None:
        item = self.project_tree.currentItem()
        if item is None:
            return None
        return str(item.data(0, USER_ROLE_PATH))

    def _checked_dashboard_figure_ids(self) -> list[str]:
        checked: list[str] = []
        for row in range(self.dashboard_figure_list.count()):
            item = self.dashboard_figure_list.item(row)
            if item.checkState() == QtCore.Qt.CheckState.Checked:
                checked.append(str(item.data(USER_ROLE_FIGURE_ID)))
        return checked

    def _dashboard_figure_source_paths(self, project_path: str | None) -> list[str]:
        if project_path and self.dashboard_figures.get(project_path):
            return [project_path]
        selected_paths = [
            project.path
            for project in self.session.projects
            if project.selected and self.dashboard_figures.get(project.path)
        ]
        if selected_paths:
            return selected_paths
        return [path for path, figures in self.dashboard_figures.items() if figures]

    def _load_dashboard_figure_list(self, project_path: str | None) -> None:
        was_loading = self._loading
        self._loading = True
        try:
            self.dashboard_figure_list.setUpdatesEnabled(False)
            blocker = QtCore.QSignalBlocker(self.dashboard_figure_list)
            try:
                self.dashboard_figure_list.clear()
                figures_by_id: dict[str, DashboardFigure] = {}
                for source_path in self._dashboard_figure_source_paths(project_path):
                    for figure in self.dashboard_figures.get(source_path, []):
                        figures_by_id.setdefault(figure.id, figure)
                selected_ids = set(self.session.dashboard_figure_selection)
                for figure in figures_by_id.values():
                    item = QtWidgets.QListWidgetItem(figure.label, self.dashboard_figure_list)
                    item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
                    item.setData(USER_ROLE_FIGURE_ID, figure.id)
                    item.setToolTip(figure.label)
                    item.setCheckState(
                        QtCore.Qt.CheckState.Checked
                        if figure.id in selected_ids
                        else QtCore.Qt.CheckState.Unchecked
                    )
            finally:
                del blocker
                self.dashboard_figure_list.setUpdatesEnabled(True)
        finally:
            self._loading = was_loading

    def add_project(self) -> None:
        directory = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            "Select PSCAD result project folder",
            str(Path.cwd()),
        )
        if not directory:
            return
        project_path = str(Path(directory).resolve())
        self.session.add_project(project_path)
        self._loading = True
        try:
            self._reload_project_tree()
        finally:
            self._loading = False
        self.autosave()
        self._select_project_path(project_path)
        self._reload_project_exclusions()
        self.refresh_project_scans(project_paths=[project_path])

    def delete_selected_projects(self) -> None:
        selected_items = self.project_tree.selectedItems()
        if not selected_items:
            return
        paths = {str(item.data(0, USER_ROLE_PATH)) for item in selected_items}
        self.session.remove_projects(paths)
        for path in paths:
            self.project_scans.pop(path, None)
            self.dashboard_figures.pop(path, None)
        try:
            project_scan_cache.remove_projects(paths)
        except OSError as exc:
            self.log(f"Project scan cache cleanup failed: {exc}")
        self._loading = True
        try:
            self._reload_project_tree()
        finally:
            self._loading = False
        self._reload_project_exclusions()
        self.autosave()
        self.update_preview()

    def _set_all_projects(self, selected: bool) -> None:
        self._loading = True
        try:
            for project in self.session.projects:
                project.selected = selected
            self._reload_project_tree()
        finally:
            self._loading = False
        self.autosave()
        self.update_preview()

    def add_scope(self, mode: str) -> None:
        try:
            self.session.add_scope(mode, self.scope_tokens_edit.text())
        except ValueError as exc:
            QtWidgets.QMessageBox.warning(self, "Scope", str(exc))
            return
        self.scope_tokens_edit.clear()
        self._loading = True
        try:
            self._reload_scope_list()
        finally:
            self._loading = False
        self.autosave()
        self.update_preview()

    def rename_selected_scope(self) -> None:
        item = self.scope_list.currentItem()
        if item is None:
            return
        folder = item.data(USER_ROLE_SCOPE_FOLDER)
        scope = self._scope_by_folder(str(folder))
        if scope is None or scope.mode == "full":
            return
        name, ok = QtWidgets.QInputDialog.getText(
            self,
            "Rename Scope",
            "Scope display name:",
            text=scope.name,
        )
        if not ok or not name.strip():
            return
        scope.name = name.strip()
        self._loading = True
        try:
            self._reload_scope_list()
        finally:
            self._loading = False
        self.autosave()
        self.update_preview()

    def delete_selected_scope(self) -> None:
        item = self.scope_list.currentItem()
        if item is None:
            return
        folder = str(item.data(USER_ROLE_SCOPE_FOLDER))
        scope = self._scope_by_folder(folder)
        if scope is None or scope.mode == "full":
            return
        self.session.scopes = [value for value in self.session.scopes if value.folder != folder]
        self._loading = True
        try:
            self._reload_scope_list()
        finally:
            self._loading = False
        self.autosave()
        self.update_preview()

    def _scope_by_folder(self, folder: str) -> ScopeEntry | None:
        for scope in self.session.scopes:
            if scope.folder == folder:
                return scope
        return None

    def save_session_as(self) -> None:
        storage.SESSION_DIR.mkdir(parents=True, exist_ok=True)
        path_text, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Save Analysis Session",
            str(storage.SESSION_DIR / "analysis.analysis_session.json"),
            "Analysis sessions (*.analysis_session.json);;JSON (*.json)",
        )
        if not path_text:
            return
        storage.save_session(Path(path_text), self.session)
        self.log(f"Saved session: {path_text}")

    def load_session_from_file(self) -> None:
        path_text, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Load Analysis Session",
            str(storage.SESSION_DIR),
            "Analysis sessions (*.analysis_session.json);;JSON (*.json)",
        )
        if not path_text:
            return
        self.session = storage.load_session(Path(path_text))
        self.session.ensure_full_scope()
        self._load_session_to_ui()
        self.autosave()
        self.refresh_project_scans()
        self.log(f"Loaded session: {path_text}")

    def clear_session(self) -> None:
        answer = QtWidgets.QMessageBox.question(
            self,
            "Clear Session",
            "Clear projects, scopes, selected voltages/events, dashboard figure choices, and autosave?",
        )
        if answer != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        self.session = AppSession.default()
        self.project_scans.clear()
        self.dashboard_figures.clear()
        self._autosave_timer.stop()
        storage.clear_autosave()
        try:
            project_scan_cache.clear()
        except OSError as exc:
            self.log(f"Project scan cache cleanup failed: {exc}")
        self._load_session_to_ui()
        self._load_dashboard_figure_list(None)
        self.update_preview()
        self.set_status("Session cleared")
        self.log("Session cleared. Autosave was removed.")

    def autosave(self) -> None:
        self._autosave_timer.start()

    def _save_autosave_now(self) -> None:
        storage.save_autosave(self.session)

    def selected_project_paths(self) -> list[str]:
        return [project.path for project in self.session.projects if project.selected]

    def selected_scopes(self) -> list[ScopeEntry]:
        return [scope for scope in self.session.scopes if scope.selected]

    def _selected_work(self, action: str) -> tuple[list[str], list[ScopeEntry]] | None:
        projects = self.selected_project_paths()
        scopes = self.selected_scopes()
        if not projects or not scopes:
            self.log(f"{action} skipped: select at least one project and one scope.")
            return None
        return projects, scopes

    def _ensure_voltage_um(self, projects: list[str], voltages: list[str]) -> bool:
        for project_path in projects:
            overrides = self.session.voltage_um_overrides_by_project.get(project_path, {})
            configs = load_voltage_configs(project_path, um_overrides=overrides)
            missing = [voltage for voltage in voltages if voltage not in configs]
            if not missing:
                continue
            self._select_project_path(project_path)
            message = QtWidgets.QMessageBox(self)
            message.setIcon(QtWidgets.QMessageBox.Icon.Warning)
            message.setWindowTitle("Missing Um")
            message.setText(
                f"{Path(project_path).name}: Um is missing for {', '.join(missing)} kV."
            )
            message.setInformativeText("Open Settings and enter Um on the Voltage Um tab before building envelopes.")
            settings_button = message.addButton("Open Settings", QtWidgets.QMessageBox.ButtonRole.AcceptRole)
            message.addButton(QtWidgets.QMessageBox.StandardButton.Cancel)
            message.exec()
            if message.clickedButton() is not settings_button:
                return False
            self.open_settings_dialog("Voltage Um")
            overrides = self.session.voltage_um_overrides_by_project.get(project_path, {})
            configs = load_voltage_configs(project_path, um_overrides=overrides)
            still_missing = [voltage for voltage in voltages if voltage not in configs]
            if still_missing:
                QtWidgets.QMessageBox.warning(
                    self,
                    "Missing Um",
                    f"Envelope build skipped. Um is still missing for {', '.join(still_missing)} kV.",
                )
                return False
        return True

    def _effective_exclusions_by_project(self) -> dict[str, list[ExclusionRule]]:
        result = {
            project: [rule for rule in normalize_exclusion_rules(exclusions) if rule.apply]
            for project, exclusions in self.session.manual_exclusions_by_project.items()
        }
        for project_path, scan in self.project_scans.items():
            disabled = set(self.session.disabled_nonconv_by_project.get(project_path, []))
            detected = [
                ExclusionRule(case=row.case, run=row.run)
                for row in scan.nonconv_cases
                if (row.case, row.run) not in disabled
            ]
            result.setdefault(project_path, []).extend(detected)
        for project_path, exclusions in self.session.high_voltage_exclusions_by_project.items():
            result.setdefault(project_path, []).extend(
                ExclusionRule(voltage=voltage, case=case, run=run, bus=bus)
                for voltage, case, run, bus in normalize_high_voltage_exclusions(exclusions)
            )
        for project_path in list(result):
            normalized = normalize_exclusion_rules(result[project_path])
            if normalized:
                result[project_path] = normalized
            else:
                result.pop(project_path)
        return result

    def refresh_project_scans(
        self,
        project_paths: Iterable[str] | None = None,
        *,
        force: bool = False,
    ) -> None:
        if self._busy:
            return
        current_path = self._current_project_path()
        paths = list(
            dict.fromkeys(
                str(Path(path).resolve())
                for path in (
                    project_paths
                    if project_paths is not None
                    else [project.path for project in self.session.projects]
                )
            )
        )
        if not paths:
            self.project_scans.clear()
            self.session.status_cache.clear()
            try:
                project_scan_cache.clear()
            except OSError as exc:
                self.log(f"Project scan cache cleanup failed: {exc}")
            self.update_preview()
            return
        iip_limit = float(self.session.nonconv_cb_iip_limit)
        iir_limit = float(self.session.nonconv_cb_iir_limit)

        def work(log, cancel):
            return project_scan_runner.scan_projects_cached(
                paths,
                current_path,
                iip_limit,
                iir_limit,
                force=force,
                check_cancel=cancel.throw_if_cancelled,
                log=log,
            )

        title = "Rebuilding project cache" if force else "Checking project cache"
        self._start_background_task(title, work, self._project_scans_finished)

    def _project_scans_finished(self, result: project_scan_runner.ProjectScanBatch) -> None:
        current_path = result.current_path
        scans = result.scans
        known_paths = {project.path for project in self.session.projects}
        self.project_scans.update(
            {
                project_path: scan
                for project_path, scan in scans.items()
                if project_path in known_paths
            }
        )
        self.project_scans = {
            project_path: scan
            for project_path, scan in self.project_scans.items()
            if project_path in known_paths
        }
        self.session.status_cache = {
            project_path: scan.chips
            for project_path, scan in self.project_scans.items()
        }
        self._update_voltage_options_from_scans()
        restore_path = current_path or self._current_project_path()
        self._loading = True
        try:
            self._reload_project_tree()
            if restore_path is not None:
                self._select_project_path(restore_path)
        finally:
            self._loading = False
        self._load_dashboard_figure_list(self._current_project_path())
        self._reload_project_exclusions()
        self.autosave()
        self.update_preview()

    def _update_voltage_options_from_scans(self) -> None:
        selected_project_paths = {
            project.path for project in self.session.projects if project.selected
        }
        discovered: set[str] = set()
        for project_path in selected_project_paths:
            scan = self.project_scans.get(project_path)
            if scan is not None:
                discovered.update(scan.available_voltages)
        if not discovered:
            return

        current_selected = set(self.session.voltages)
        selected = current_selected.intersection(discovered)
        if not selected:
            selected = discovered
        self._set_voltage_options(discovered, selected)

    def _refresh_project_status_after_action(
        self,
        project_paths: Iterable[str],
        *,
        refresh_dashboards: bool = False,
        refresh_envelopes: bool = False,
        refresh_plots: bool = False,
        refresh_reports: bool = False,
        refresh_high_voltage_exclusions: bool = False,
    ) -> None:
        paths = list(dict.fromkeys(str(Path(path).resolve()) for path in project_paths))
        for project_path in paths:
            scan = self.project_scans.get(project_path)
            if scan is None:
                continue
            scanner.refresh_project_scan_outputs(
                scan,
                refresh_dashboards=refresh_dashboards,
                refresh_envelopes=refresh_envelopes,
                refresh_plots=refresh_plots,
                refresh_reports=refresh_reports,
                refresh_high_voltage_exclusions=refresh_high_voltage_exclusions,
            )
            self.session.status_cache[project_path] = scan.chips

        if not paths:
            return
        try:
            project_scan_cache.update_project_scans(
                self.project_scans,
                paths,
                (
                    float(self.session.nonconv_cb_iip_limit),
                    float(self.session.nonconv_cb_iir_limit),
                ),
            )
        except (OSError, TypeError, ValueError) as exc:
            self.log(f"Project scan cache could not be saved: {exc}")

        current_path = self._current_project_path()
        self._loading = True
        try:
            self._reload_project_tree()
            if current_path is not None:
                self._select_project_path(current_path)
        finally:
            self._loading = False
        self._reload_project_exclusions()
        self.autosave()
        self.update_preview()

    def _select_project_path(self, project_path: str) -> None:
        for row in range(self.project_tree.topLevelItemCount()):
            item = self.project_tree.topLevelItem(row)
            if str(item.data(0, USER_ROLE_PATH)) == project_path:
                self.project_tree.setCurrentItem(item)
                return

    def scan_dashboard_figures(self) -> None:
        projects = self.selected_project_paths()
        if not projects:
            self.log("No checked projects for dashboard figure scan.")
            return

        def work(log, cancel):
            result: dict[str, tuple[list[DashboardFigure], list[str]]] = {}
            for project_path in projects:
                cancel.throw_if_cancelled()
                root = Path(project_path)
                log(f"Scanning dashboard figures without updating Excel data: {root.name}")
                figures, warnings = scanner.scan_dashboard_figures(root)
                result[project_path] = (figures, warnings)
                log(f"Dashboard figure scan complete: {root.name} | {len(figures)} figures")
                for warning in warnings:
                    log(warning)
            return result

        self._start_background_task(
            "Scanning dashboard figures",
            work,
            self._dashboard_figures_scan_finished,
        )

    def refresh_dashboards(self) -> None:
        projects = self.selected_project_paths()
        if not projects:
            self.log("No checked projects for dashboard refresh.")
            return

        def work(log, cancel):
            result: dict[str, tuple[list[DashboardFigure], list[str]]] = {}
            for project_path in projects:
                cancel.throw_if_cancelled()
                root = Path(project_path)
                log(f"Dashboard refresh started: {root.name}")
                try:
                    actions.refresh_dashboards(root, log)
                except Exception as exc:
                    log(f"Dashboard refresh failed for {root.name}: {exc}")

                cancel.throw_if_cancelled()
                log(f"Scanning available dashboard figures: {root.name}")
                figures, warnings = scanner.scan_dashboard_figures(root)
                result[project_path] = (figures, warnings)
                log(f"Dashboard figure scan complete: {root.name} | {len(figures)} figures")
                for warning in warnings:
                    log(warning)
            return result

        self._start_background_task(
            "Refreshing dashboards",
            work,
            self._dashboard_refresh_finished,
        )

    def _dashboard_refresh_finished(
        self,
        result: dict[str, tuple[list[DashboardFigure], list[str]]],
    ) -> None:
        self._update_dashboard_figures(result)
        self._refresh_project_status_after_action(
            result,
            refresh_dashboards=True,
        )
        self.autosave()
        self._load_dashboard_figure_list(self._current_project_path())

    def _update_dashboard_figures(
        self,
        result: dict[str, tuple[list[DashboardFigure], list[str]]],
    ) -> None:
        for project_path, (figures, _warnings) in result.items():
            self.dashboard_figures[project_path] = figures
            if not self.session.dashboard_figure_selection_initialized and figures:
                self.session.dashboard_figure_selection = [figure.id for figure in figures]
                self.session.dashboard_figure_selection_initialized = True

    def _dashboard_figures_scan_finished(
        self,
        result: dict[str, tuple[list[DashboardFigure], list[str]]],
    ) -> None:
        self._update_dashboard_figures(result)
        self.autosave()
        self._load_dashboard_figure_list(self._current_project_path())

    def scan_high_voltage_log(self) -> None:
        projects = self.selected_project_paths()
        if not projects:
            self.log("No checked projects for PSCAD log high-voltage scan.")
            return
        limit_factor = float(self.session.high_voltage_limit_factor)
        voltage_overrides = dict(self.session.voltage_um_overrides_by_project)

        def work(log, cancel):
            result: dict[str, tuple[list[scanner.HighVoltageExclusion], list[str]]] = {}
            for project_path in projects:
                cancel.throw_if_cancelled()
                root = Path(project_path)
                log(f"Scanning PSCAD log high-voltage proposals: {root.name}")
                rows, warnings = scanner.scan_high_voltage_from_pscad_log(
                    root,
                    limit_factor,
                    voltage_overrides.get(project_path, {}),
                    check_cancel=cancel.throw_if_cancelled,
                )
                result[project_path] = (rows, warnings)
                log(f"PSCAD log high-voltage scan complete: {root.name} | {len(rows)} proposals")
                for warning in warnings:
                    log(warning)
            return result

        self._start_background_task(
            "Scanning PSCAD log high voltage",
            work,
            self._high_voltage_log_scan_finished,
        )

    def _high_voltage_log_scan_finished(
        self,
        result: dict[str, tuple[list[scanner.HighVoltageExclusion], list[str]]],
    ) -> None:
        current_path = self._current_project_path()
        for project_path, (rows, _warnings) in result.items():
            scan = self.project_scans.get(project_path)
            if scan is None:
                scan = scanner.ProjectScan(path=Path(project_path), exists=Path(project_path).is_dir())
                self.project_scans[project_path] = scan
            kept = [
                row
                for row in scan.high_voltage_exclusions
                if row.file not in scanner.PSCAD_LOG_HIGH_VOLTAGE_SOURCES
            ]
            seen = {(row.voltage, row.case, row.run, row.bus) for row in kept}
            for row in rows:
                key = (row.voltage, row.case, row.run, row.bus)
                if key not in seen:
                    kept.append(row)
                    seen.add(key)
            scan.high_voltage_exclusions = kept
            scan.chips = [chip for chip in scan.chips if not chip.startswith("High voltage proposals:")]
            if scan.high_voltage_exclusions:
                scan.chips.append(f"High voltage proposals: {len(scan.high_voltage_exclusions)}")
            self.session.status_cache[project_path] = scan.chips

        self._loading = True
        try:
            self._reload_project_tree()
            if current_path is not None:
                self._select_project_path(current_path)
        finally:
            self._loading = False
        self._reload_project_exclusions()
        self.autosave()

    def run_full_analysis(self) -> None:
        selected = self._selected_work("Run analysis")
        if selected is None:
            return
        projects, scopes = selected
        voltages = list(self.session.voltages)
        events = list(self.session.events)
        if not self._ensure_voltage_um(projects, voltages):
            return
        dashboard_figure_ids = list(self.session.dashboard_figure_selection)
        envelope_kwargs = self._envelope_build_kwargs()

        def work(log, cancel):
            log("Analysis started.")
            log("Dashboard update will not run. Existing dashboard files are used for reports.")
            prompt_log = self._frequency_prompting_log(log, cancel)
            written = actions.run_analysis_pipeline(
                projects,
                scopes,
                voltages,
                events,
                dashboard_figure_ids=dashboard_figure_ids,
                **envelope_kwargs,
                log=prompt_log,
                check_cancel=cancel.throw_if_cancelled,
            )
            log(f"Analysis finished. Reports written: {len(written)}")
            return written

        self._start_background_task(
            "Running analysis",
            work,
            lambda _result: self._refresh_project_status_after_action(
                projects,
                refresh_envelopes=True,
                refresh_plots=True,
                refresh_reports=True,
                refresh_high_voltage_exclusions=True,
            ),
        )

    def build_envelopes_only(self) -> None:
        selected = self._selected_work("Build envelopes")
        if selected is None:
            return
        projects, scopes = selected
        voltages = list(self.session.voltages)
        if not self._ensure_voltage_um(projects, voltages):
            return
        envelope_kwargs = self._envelope_build_kwargs()

        def work(log, cancel):
            log("Envelope build started.")
            prompt_log = self._frequency_prompting_log(log, cancel)
            written = actions.build_voltage_envelopes(
                projects,
                scopes,
                voltages,
                self.session.events,
                **envelope_kwargs,
                build_charts=False,
                log=prompt_log,
                check_cancel=cancel.throw_if_cancelled,
            )
            log(f"Envelope data/check build complete: {len(written)} workbooks.")
            return written

        self._start_background_task(
            "Building envelope data/checks",
            work,
            lambda _result: self._refresh_project_status_after_action(
                projects,
                refresh_envelopes=True,
            ),
        )

    def rebuild_envelope_charts_only(self) -> None:
        selected = self._selected_work("Rebuild envelope charts")
        if selected is None:
            return
        projects, scopes = selected

        def work(log, cancel):
            log("Envelope chart rebuild started.")
            written = actions.rebuild_envelope_charts(
                projects,
                scopes,
                self.session.voltages,
                **self._envelope_chart_kwargs(),
                log=log,
                check_cancel=cancel.throw_if_cancelled,
            )
            log(f"Envelope chart rebuild complete: {len(written)} workbooks.")
            return written

        self._start_background_task(
            "Rebuilding envelope charts",
            work,
            lambda _result: self._refresh_project_status_after_action(
                projects,
                refresh_envelopes=True,
                refresh_high_voltage_exclusions=True,
            ),
        )

    def create_event_batches_only(self) -> None:
        selected = self._selected_work("Create event batches")
        if selected is None:
            return
        projects, scopes = selected

        def work(log, cancel):
            log("Event plot batch creation started.")
            written = actions.create_plot_batches(
                projects,
                scopes,
                self.session.voltages,
                self.session.events,
                dict(self.session.event_times),
                log=log,
                check_cancel=cancel.throw_if_cancelled,
            )
            log(f"Event plot batch creation complete: {len(written)} workbooks.")
            return written

        self._start_background_task("Creating event plot batches", work)

    def render_event_plots_only(self) -> None:
        selected = self._selected_work("Render event plots")
        if selected is None:
            return
        projects, scopes = selected

        def work(log, cancel):
            log("Event plot rendering started.")
            actions.render_plot_batches(
                projects,
                scopes,
                self.session.events,
                log=log,
                check_cancel=cancel.throw_if_cancelled,
            )
            log("Event plot rendering complete.")

        self._start_background_task(
            "Rendering event plots",
            work,
            lambda _result: self._refresh_project_status_after_action(
                projects,
                refresh_plots=True,
            ),
        )

    def rebuild_analysis_charts_only(self) -> None:
        selected = self._selected_work("Rebuild analysis charts")
        if selected is None:
            return
        projects, scopes = selected

        def work(log, cancel):
            log("Analysis chart rebuild started.")
            written = actions.rebuild_analysis_charts(
                projects,
                scopes,
                envelope_chart_x_max=self.session.envelope_chart_x_max,
                log=log,
                check_cancel=cancel.throw_if_cancelled,
            )
            log(f"Analysis chart rebuild complete: {len(written)} workbooks.")
            return written

        self._start_background_task(
            "Rebuilding analysis charts",
            work,
            lambda _result: self._refresh_project_status_after_action(
                projects,
                refresh_envelopes=True,
            ),
        )

    def create_analysis_batches_only(self) -> None:
        selected = self._selected_work("Create analysis batches")
        if selected is None:
            return
        projects, scopes = selected
        resonance_settings = self._resonance_settings()

        def work(log, cancel):
            log("Analysis plot batch creation started.")
            written = actions.create_plot_batches(
                projects,
                scopes,
                self.session.voltages,
                (),
                dict(self.session.event_times),
                resonance_settings=resonance_settings,
                log=log,
                check_cancel=cancel.throw_if_cancelled,
            )
            log(f"Analysis plot batch creation complete: {len(written)} workbooks.")
            return written

        self._start_background_task("Creating analysis plot batches", work)

    def render_analysis_plots_only(self) -> None:
        selected = self._selected_work("Render analysis plots")
        if selected is None:
            return
        projects, scopes = selected
        resonance_settings = self._resonance_settings()

        def work(log, cancel):
            log("Analysis plot rendering started.")
            actions.render_plot_batches(
                projects,
                scopes,
                (),
                resonance_settings=resonance_settings,
                log=log,
                check_cancel=cancel.throw_if_cancelled,
            )
            log("Analysis plot rendering complete.")

        self._start_background_task(
            "Rendering analysis plots",
            work,
            lambda _result: self._refresh_project_status_after_action(
                projects,
                refresh_plots=True,
            ),
        )

    def build_reports_only(self) -> None:
        selected = self._selected_work("Build reports")
        if selected is None:
            return
        projects, scopes = selected
        voltages = list(self.session.voltages)
        events = list(self.session.events)
        resonance_settings = self._resonance_settings()

        def work(log, cancel):
            log("Report rebuild started.")
            log("Report-only mode: no envelopes, batches, plot rendering, or dashboard update will run.")
            log("Using saved dashboard workbooks. Save manual Excel edits before rebuilding reports.")
            cancel.throw_if_cancelled()
            written = reporting.build_reports_from_existing_plots(
                projects,
                scopes,
                voltages,
                events,
                self.session.dashboard_figure_selection,
                resonance_settings=resonance_settings,
                event_times=dict(self.session.event_times),
                log=log,
            )
            cancel.throw_if_cancelled()
            log(f"Report rebuild complete: {len(written)} files.")
            return written

        self._start_background_task(
            "Building reports",
            work,
            lambda _result: self._refresh_project_status_after_action(
                projects,
                refresh_reports=True,
            ),
        )

    def update_preview(self) -> None:
        projects = [project for project in self.session.projects if project.selected]
        scopes = [scope for scope in self.session.scopes if scope.selected]
        rows: list[tuple[ProjectEntry, ScopeEntry]] = [
            (project, scope) for project in projects for scope in scopes
        ]
        with self._table_bulk_update(self.preview_table):
            self.preview_table.setRowCount(len(rows))
            for row_index, (project, scope) in enumerate(rows):
                scan = self.project_scans.get(project.path)
                preview = scanner.preview_scope(scan, scope) if scan else None
                cases = (
                    f"{preview.matched_count}/{preview.total_count}"
                    if preview is not None
                    else "not scanned"
                )
                warnings = preview.warning if preview is not None else ""
                if scan and "Missing Results" in scan.chips:
                    warnings = f"{warnings}; missing results".strip("; ")
                if scan and scan.available_voltages:
                    missing_voltages = [
                        voltage
                        for voltage in self.session.voltages
                        if voltage not in scan.available_voltages
                    ]
                    if missing_voltages:
                        warning = f"missing voltages: {', '.join(missing_voltages)}"
                        warnings = f"{warnings}; {warning}".strip("; ")
                outputs = self._outputs_text(scope, self.session.events)
                values = [project.name, scope.folder, cases, outputs, warnings]
                for column, value in enumerate(values):
                    item = QtWidgets.QTableWidgetItem(value)
                    item.setToolTip(value)
                    self.preview_table.setItem(row_index, column, item)

    def _outputs_text(self, scope: ScopeEntry, events: Iterable[str]) -> str:
        event_text = ", ".join(events) if events else "no events"
        return (
            f"Voltage_envelope/{scope.folder}; "
            f"Plots/Generated/{scope.folder}/({event_text}); "
            f"Reports/{scope.folder}"
        )

    def _resonance_settings(self) -> dict[str, object]:
        return resonance_checks.ResonanceSettings.from_session(self.session).to_mapping()

    def _envelope_chart_kwargs(self) -> dict[str, object]:
        return {
            "event_times": dict(self.session.event_times),
            "envelope_chart_x_max": float(self.session.envelope_chart_x_max),
            "envelope_chart_x_major": float(self.session.envelope_chart_x_major),
            "envelope_chart_y_limits_by_voltage": dict(self.session.envelope_chart_y_limits_by_voltage),
            "envelope_chart_show_sa_label": bool(self.session.envelope_chart_show_sa_label),
            "envelope_chart_top_left_cell": self.session.envelope_chart_top_left_cell,
            "envelope_chart_width": float(self.session.envelope_chart_width),
            "envelope_chart_height": float(self.session.envelope_chart_height),
        }

    def _envelope_build_kwargs(self) -> dict[str, object]:
        return {
            "envelope_workers": int(self.session.envelope_workers),
            "envelope_time_step": float(self.session.envelope_time_step),
            "envelope_time_end": float(self.session.envelope_time_end),
            "envelope_fallback_frequency": float(self.session.envelope_fallback_frequency),
            **self._envelope_chart_kwargs(),
            "high_voltage_limit_factor": float(self.session.high_voltage_limit_factor),
            "nonconv_cb_iip_limit": float(self.session.nonconv_cb_iip_limit),
            "nonconv_cb_iir_limit": float(self.session.nonconv_cb_iir_limit),
            "voltage_um_overrides_by_project": dict(self.session.voltage_um_overrides_by_project),
            "exclusions_by_project": self._effective_exclusions_by_project(),
            "resonance_settings": self._resonance_settings(),
        }

    def _start_background_task(self, title: str, work, on_success=None) -> None:
        if self._busy:
            self.log(f"Busy: finish the current task before starting '{title}'.")
            return
        self._set_busy(True, title)
        self.log(f"{title} started.")
        self._frequency_fallback_prompted = False
        self._open_settings_after_task = False
        cancel_token = CancelToken()
        self._cancel_token = cancel_token
        worker = BackgroundTask(work, cancel_token, self)
        self._worker = worker
        worker.message.connect(self._on_worker_message)
        worker.succeeded.connect(lambda result: self._task_succeeded(title, result, on_success))
        worker.failed.connect(lambda message, details: self._task_failed(title, message, details))
        worker.finished.connect(self._worker_finished)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def stop_current_task(self) -> None:
        if self._worker is None or not self._worker.isRunning():
            return
        self.log("Stop requested. Waiting for the current file/Excel operation to exit.")
        self.set_status("Stopping current task")
        if self._cancel_token is not None:
            self._cancel_token.cancel()
        self._worker.requestInterruption()

    def _on_worker_message(self, message: str) -> None:
        if message.startswith(FREQUENCY_FALLBACK_MESSAGE_PREFIX):
            self._handle_frequency_fallback_message(message)
            return
        self.set_status(message)
        self.log(message)

    def _frequency_prompting_log(self, log, cancel):
        def emit(message: str) -> None:
            if not message.startswith(FREQUENCY_FALLBACK_MESSAGE_PREFIX):
                log(message)
                return
            request = _FrequencyFallbackPrompt(message)
            self.frequency_fallback_prompt_requested.emit(request)
            request.done.wait()
            if request.action == "continue":
                return
            cancel.cancel()
            raise RuntimeError("Operation stopped by user.")

        return emit

    def _show_frequency_fallback_prompt(self, request: _FrequencyFallbackPrompt) -> None:
        request.action = self._frequency_fallback_prompt_action(request.message)
        request.done.set()

    def _handle_frequency_fallback_message(self, message: str) -> None:
        action = self._frequency_fallback_prompt_action(message)
        if action == "continue":
            return
        if self._cancel_token is not None:
            self._cancel_token.cancel()
        if self._worker is not None:
            self._worker.requestInterruption()

    def _frequency_fallback_prompt_action(self, message: str) -> str:
        payload = message.removeprefix(FREQUENCY_FALLBACK_MESSAGE_PREFIX)
        project, frequency, context = (payload.split("|", 2) + ["", "", ""])[:3]
        warning = (
            f"Frequency auto-detection failed; using fallback {frequency} Hz"
            f"{f' for {project}' if project else ''}"
            f"{f': {context}' if context else ''}"
        )
        self.set_status(warning)
        self.log(f"WARNING: {warning}")
        if self._frequency_fallback_prompted:
            return "continue"
        self._frequency_fallback_prompted = True

        message_box = QtWidgets.QMessageBox(self)
        message_box.setIcon(QtWidgets.QMessageBox.Icon.Warning)
        message_box.setWindowTitle("Frequency Detection Failed")
        message_box.setText(f"Automatic frequency detection failed. Fallback {frequency} Hz is being used.")
        message_box.setInformativeText(
            "Continue only if this fallback is correct for the project. "
            "To change it, stop this run and open Settings."
        )
        continue_button = message_box.addButton(
            f"Continue with {frequency} Hz",
            QtWidgets.QMessageBox.ButtonRole.AcceptRole,
        )
        stop_button = message_box.addButton("Stop run", QtWidgets.QMessageBox.ButtonRole.RejectRole)
        settings_button = message_box.addButton(
            "Stop and open Settings",
            QtWidgets.QMessageBox.ButtonRole.ActionRole,
        )
        message_box.exec()
        clicked = message_box.clickedButton()
        if clicked is continue_button:
            return "continue"
        open_settings = clicked is settings_button
        self._open_settings_after_task = open_settings
        self.set_status("Stopping current task")
        self.log("Stop requested after frequency fallback warning.")
        return "settings" if open_settings else "stop"

    def _task_succeeded(self, title: str, result, on_success) -> None:
        self._set_busy(False, "Updating project status")
        self._worker = None
        self._cancel_token = None
        if on_success is not None:
            on_success(result)
        self.log(f"{title} finished.")
        if not self._busy:
            self.set_status("Ready")
            self._open_settings_if_requested()

    def _task_failed(self, title: str, message: str, details: str) -> None:
        if message == "Operation stopped by user.":
            self.log(f"{title} stopped by user.")
            self._set_busy(False, "Stopped")
        else:
            self.log(f"{title} failed: {message}")
            self.log(f"{title} traceback:\n{details.rstrip()}")
            self._set_busy(False, f"{title} failed")
        self._worker = None
        self._cancel_token = None
        self._open_settings_if_requested()

    def _worker_finished(self) -> None:
        if self._close_when_idle:
            QtCore.QTimer.singleShot(0, self.close)

    def _open_settings_if_requested(self) -> None:
        if not self._open_settings_after_task:
            return
        self._open_settings_after_task = False
        QtCore.QTimer.singleShot(0, lambda: self.open_settings_dialog("Envelope Build"))

    def _set_busy(self, busy: bool, status: str) -> None:
        self._busy = busy
        self.workspace_splitter.setEnabled(not busy)
        self.scan_high_voltage_log_button.setEnabled(not busy)
        self.scan_dashboard_figures_button.setEnabled(not busy)
        self.refresh_dashboards_button.setEnabled(not busy)
        self.run_full_button.setEnabled(not busy)
        self.build_reports_button.setEnabled(not busy)
        self.settings_button.setEnabled(not busy)
        self.build_envelopes_button.setEnabled(not busy)
        self.rebuild_envelope_charts_button.setEnabled(not busy)
        self.create_event_batches_button.setEnabled(not busy)
        self.render_event_plots_button.setEnabled(not busy)
        self.rebuild_analysis_charts_button.setEnabled(not busy)
        self.create_analysis_batches_button.setEnabled(not busy)
        self.render_analysis_plots_button.setEnabled(not busy)
        for check in self.voltage_checks.values():
            check.setEnabled(not busy)
        for check in self.event_checks.values():
            check.setEnabled(not busy)
        for check in self.resonance_checkboxes.values():
            check.setEnabled(not busy)
        self.busy_progress.setVisible(busy)
        self.stop_button.setEnabled(busy)
        self.set_status(status)
        if busy:
            QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
        else:
            QtWidgets.QApplication.restoreOverrideCursor()

    def set_status(self, message: str) -> None:
        self.status_label.setText(message)
        self.statusBar().clearMessage()

    def log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_edit.appendPlainText(f"[{timestamp}] {message}")
        self.log_edit.verticalScrollBar().setValue(self.log_edit.verticalScrollBar().maximum())

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override name
        if self._worker is not None and self._worker.isRunning():
            self._close_when_idle = True
            self.stop_current_task()
            event.ignore()
            return
        if self._autosave_timer.isActive():
            self._autosave_timer.stop()
            self._save_autosave_now()
        super().closeEvent(event)
