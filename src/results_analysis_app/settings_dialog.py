from __future__ import annotations

import math
from pathlib import Path

from PySide6 import QtCore, QtWidgets

from results_analysis_app.models import (
    DEFAULT_ENVELOPE_CHART_X_MAJOR,
    DEFAULT_ENVELOPE_CHART_X_MAX,
    DEFAULT_ENVELOPE_TIME_END,
    DEFAULT_EVENTS,
    DEFAULT_EXCEL_WAVEFORM_EXPORTS,
    MAX_ENVELOPE_WORKERS,
    automatic_worker_count,
    normalize_chart_y_limits,
)
from results_analysis_app.project_config import (
    automatic_time_major,
    load_project_timing,
    load_voltage_configs,
)
from results_analysis_app import sustained_sdpf, sustained_sdpf_heatmap
from results_analysis_app.styles import make_muted_label, make_section_label


def edit_settings(window, initial_tab: str | None = None) -> None:
    """Open the settings editor and apply accepted values to the window session."""
    self = window
    dialog = QtWidgets.QDialog(self)
    dialog.setWindowTitle("Analysis Settings")
    dialog.resize(1120, 760)
    layout = QtWidgets.QVBoxLayout(dialog)

    project_path = self._current_project_path()
    project_scan = self.project_scans.get(project_path) if project_path else None
    project_timing = (
        load_project_timing(project_path)
        if project_path and project_scan is None
        else None
    )
    project_frequency = (
        project_scan.project_frequency
        if project_scan is not None
        else project_timing.frequency if project_timing is not None else None
    )
    project_duration = (
        project_scan.final_duration
        if project_scan is not None
        else project_timing.final_duration if project_timing is not None else None
    )

    tabs = QtWidgets.QTabWidget(dialog)
    build_tab = QtWidgets.QWidget(tabs)
    build_form = QtWidgets.QFormLayout(build_tab)
    workers_auto_check = QtWidgets.QCheckBox("Automatic", build_tab)
    workers_auto_check.setChecked(bool(self.session.envelope_workers_auto))
    workers_spin = QtWidgets.QSpinBox(build_tab)
    workers_spin.setRange(1, MAX_ENVELOPE_WORKERS)
    workers_spin.setValue(
        max(1, min(MAX_ENVELOPE_WORKERS, int(self.session.envelope_workers or automatic_worker_count())))
    )
    workers_spin.setToolTip("Manual worker count used while reading envelope waveform files.")
    workers_auto_check.setToolTip(
        "Use the ceiling of 80% of detected logical CPUs, capped for Windows process pools."
    )
    workers_spin.setEnabled(not workers_auto_check.isChecked())
    workers_auto_check.toggled.connect(workers_spin.setDisabled)
    workers_row = QtWidgets.QHBoxLayout()
    workers_row.addWidget(workers_auto_check)
    workers_row.addWidget(workers_spin)
    workers_row.addStretch()
    build_form.addRow("Envelope workers", workers_row)

    rebuild_cache_requested = False
    rebuild_cache_button = QtWidgets.QPushButton("Rebuild project cache", build_tab)
    rebuild_cache_button.setToolTip("Force a fresh scan of all saved project folders.")

    def request_cache_rebuild() -> None:
        nonlocal rebuild_cache_requested
        rebuild_cache_requested = True
        dialog.accept()

    rebuild_cache_button.clicked.connect(request_cache_rebuild)
    build_form.addRow("Project scans", rebuild_cache_button)

    excel_exports_check = QtWidgets.QCheckBox("Create automatic Excel waveform exports", build_tab)
    excel_exports_check.setChecked(
        bool(
            getattr(
                self.session,
                "excel_waveform_exports_enabled",
                DEFAULT_EXCEL_WAVEFORM_EXPORTS,
            )
        )
    )
    excel_exports_check.setToolTip(
        "Include one waveform Excel file with each automatically generated plot."
    )
    build_form.addRow("Waveform exports", excel_exports_check)

    time_step_spin = QtWidgets.QDoubleSpinBox(build_tab)
    time_step_spin.setDecimals(4)
    time_step_spin.setRange(0.0001, 1.0)
    time_step_spin.setSingleStep(0.001)
    time_step_spin.setSuffix(" s")
    time_step_spin.setValue(float(self.session.envelope_time_step))
    build_form.addRow("Envelope time step", time_step_spin)

    time_end_spin = QtWidgets.QDoubleSpinBox(build_tab)
    time_end_spin.setDecimals(3)
    time_end_spin.setRange(0.001, 10.0)
    time_end_spin.setSingleStep(0.1)
    time_end_spin.setSuffix(" s")
    time_end_auto_check = QtWidgets.QCheckBox("Use project duration", build_tab)
    time_end_auto_check.setChecked(bool(self.session.envelope_time_end_auto))
    time_end_auto_check.setToolTip(
        "Use the selected project's Final duration; each run remains capped by its available waveform."
    )
    time_end_widget = QtWidgets.QWidget(build_tab)
    time_end_layout = QtWidgets.QHBoxLayout(time_end_widget)
    time_end_layout.setContentsMargins(0, 0, 0, 0)
    time_end_layout.addWidget(time_end_spin)
    time_end_layout.addWidget(time_end_auto_check)
    time_end_layout.addStretch()
    build_form.addRow("Envelope time end", time_end_widget)

    def update_time_end_controls() -> None:
        time_end_spin.setEnabled(not time_end_auto_check.isChecked())
        if time_end_auto_check.isChecked():
            time_end_spin.setValue(float(project_duration or DEFAULT_ENVELOPE_TIME_END))

    time_end_auto_check.toggled.connect(update_time_end_controls)
    update_time_end_controls()

    fallback_frequency_spin = QtWidgets.QDoubleSpinBox(build_tab)
    fallback_frequency_spin.setDecimals(2)
    fallback_frequency_spin.setRange(1.0, 1000.0)
    fallback_frequency_spin.setSingleStep(1.0)
    fallback_frequency_spin.setSuffix(" Hz")
    fallback_frequency_spin.setValue(float(project_frequency or self.session.envelope_fallback_frequency))
    fallback_frequency_spin.setEnabled(project_frequency is None)
    build_form.addRow("Fallback frequency", fallback_frequency_spin)
    frequency_source = (
        f"Input_Data!B16 for selected project. Settings fallback remains {self.session.envelope_fallback_frequency:g} Hz."
        if project_frequency is not None
        else "Settings fallback; used when Input_Data!B16 is unavailable."
    )
    build_form.addRow("Frequency source", make_muted_label(frequency_source, build_tab))

    high_voltage_factor_spin = QtWidgets.QDoubleSpinBox(build_tab)
    high_voltage_factor_spin.setDecimals(2)
    high_voltage_factor_spin.setRange(0.01, 100.0)
    high_voltage_factor_spin.setSingleStep(0.5)
    high_voltage_factor_spin.setValue(float(self.session.high_voltage_limit_factor))
    build_form.addRow("High voltage factor", high_voltage_factor_spin)

    nonconv_iip_spin = QtWidgets.QDoubleSpinBox(build_tab)
    nonconv_iip_spin.setDecimals(1)
    nonconv_iip_spin.setRange(0.1, 100000.0)
    nonconv_iip_spin.setSingleStep(10.0)
    nonconv_iip_spin.setValue(float(self.session.nonconv_cb_iip_limit))
    build_form.addRow("NonConv CB_IIp limit", nonconv_iip_spin)

    nonconv_iir_spin = QtWidgets.QDoubleSpinBox(build_tab)
    nonconv_iir_spin.setDecimals(1)
    nonconv_iir_spin.setRange(0.1, 100000.0)
    nonconv_iir_spin.setSingleStep(10.0)
    nonconv_iir_spin.setValue(float(self.session.nonconv_cb_iir_limit))
    build_form.addRow("NonConv CB_IIr limit", nonconv_iir_spin)
    tabs.addTab(build_tab, "Envelope Build")

    chart_tab = QtWidgets.QWidget(tabs)
    chart_layout = QtWidgets.QVBoxLayout(chart_tab)
    chart_form = QtWidgets.QFormLayout()
    chart_form.addRow(
        "Project",
        make_muted_label(Path(project_path).name if project_path else "No project selected", chart_tab),
    )
    x_max_override = self.session.envelope_chart_x_max_overrides_by_project.get(project_path or "")
    chart_x_max_spin = QtWidgets.QDoubleSpinBox(chart_tab)
    chart_x_max_spin.setDecimals(6)
    chart_x_max_spin.setRange(0.000001, 1000000.0)
    chart_x_max_spin.setSingleStep(0.1)
    chart_x_max_spin.setSuffix(" s")
    chart_x_max_spin.setValue(float(x_max_override or project_duration or DEFAULT_ENVELOPE_CHART_X_MAX))
    chart_x_max_auto = QtWidgets.QCheckBox("Use project duration", chart_tab)
    chart_x_max_auto.setChecked(x_max_override is None)
    chart_x_max_widget = QtWidgets.QWidget(chart_tab)
    chart_x_max_layout = QtWidgets.QHBoxLayout(chart_x_max_widget)
    chart_x_max_layout.setContentsMargins(0, 0, 0, 0)
    chart_x_max_layout.addWidget(chart_x_max_spin)
    chart_x_max_layout.addWidget(chart_x_max_auto)
    chart_form.addRow("Chart x max", chart_x_max_widget)

    x_major_override = self.session.envelope_chart_x_major_overrides_by_project.get(project_path or "")
    chart_x_major_spin = QtWidgets.QDoubleSpinBox(chart_tab)
    chart_x_major_spin.setDecimals(6)
    chart_x_major_spin.setRange(0.000001, 1000000.0)
    chart_x_major_spin.setSingleStep(0.01)
    chart_x_major_spin.setSuffix(" s")
    chart_x_major_spin.setValue(
        float(
            x_major_override
            or automatic_time_major(chart_x_max_spin.value())
            or DEFAULT_ENVELOPE_CHART_X_MAJOR
        )
    )
    chart_x_major_auto = QtWidgets.QCheckBox("Use approximately 10 intervals", chart_tab)
    chart_x_major_auto.setChecked(x_major_override is None)
    chart_x_major_widget = QtWidgets.QWidget(chart_tab)
    chart_x_major_layout = QtWidgets.QHBoxLayout(chart_x_major_widget)
    chart_x_major_layout.setContentsMargins(0, 0, 0, 0)
    chart_x_major_layout.addWidget(chart_x_major_spin)
    chart_x_major_layout.addWidget(chart_x_major_auto)
    chart_form.addRow("Chart x major", chart_x_major_widget)

    def update_chart_x_controls() -> None:
        enabled = project_path is not None
        chart_x_max_auto.setEnabled(enabled)
        chart_x_major_auto.setEnabled(enabled)
        chart_x_max_spin.setEnabled(enabled and not chart_x_max_auto.isChecked())
        chart_x_major_spin.setEnabled(enabled and not chart_x_major_auto.isChecked())
        if chart_x_max_auto.isChecked():
            chart_x_max_spin.setValue(float(project_duration or DEFAULT_ENVELOPE_CHART_X_MAX))
        if chart_x_major_auto.isChecked():
            chart_x_major_spin.setValue(
                float(
                    automatic_time_major(chart_x_max_spin.value())
                    or DEFAULT_ENVELOPE_CHART_X_MAJOR
                )
            )

    chart_x_max_auto.toggled.connect(update_chart_x_controls)
    chart_x_major_auto.toggled.connect(update_chart_x_controls)
    chart_x_max_spin.valueChanged.connect(lambda _value: update_chart_x_controls())
    update_chart_x_controls()

    chart_top_left_edit = QtWidgets.QLineEdit(chart_tab)
    chart_top_left_edit.setText(self.session.envelope_chart_top_left_cell)
    chart_form.addRow("Chart top-left cell", chart_top_left_edit)

    chart_width_spin = QtWidgets.QDoubleSpinBox(chart_tab)
    chart_width_spin.setDecimals(2)
    chart_width_spin.setRange(10.0, 5000.0)
    chart_width_spin.setValue(float(self.session.envelope_chart_width))
    chart_form.addRow("Chart width", chart_width_spin)

    chart_height_spin = QtWidgets.QDoubleSpinBox(chart_tab)
    chart_height_spin.setDecimals(2)
    chart_height_spin.setRange(10.0, 5000.0)
    chart_height_spin.setValue(float(self.session.envelope_chart_height))
    chart_form.addRow("Chart height", chart_height_spin)

    show_sa_label_check = QtWidgets.QCheckBox("Show SA label", chart_tab)
    show_sa_label_check.setChecked(bool(self.session.envelope_chart_show_sa_label))
    chart_form.addRow("Annotations", show_sa_label_check)
    chart_layout.addLayout(chart_form)

    y_limit_table = QtWidgets.QTableWidget(0, 4, chart_tab)
    y_limit_table.setHorizontalHeaderLabels(["kV", "Y min", "Y max", "Y major"])
    y_limit_table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
    y_limit_table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Stretch)
    y_limit_table.horizontalHeader().setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.Stretch)
    y_limit_table.horizontalHeader().setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeMode.Stretch)
    chart_limits = normalize_chart_y_limits(self.session.envelope_chart_y_limits_by_voltage)
    voltage_options = set(chart_limits)
    voltage_options.update(self.session.voltages)
    for scan in self.project_scans.values():
        voltage_options.update(scan.available_voltages)
    for voltage in self._sorted_voltages(voltage_options):
        row = y_limit_table.rowCount()
        y_limit_table.insertRow(row)
        limits = chart_limits.get(voltage, {})
        for column, value in enumerate(
            (
                voltage,
                "" if limits.get("y_min") is None else str(limits.get("y_min")),
                "" if limits.get("y_max") is None else str(limits.get("y_max")),
                "" if limits.get("y_major") is None else str(limits.get("y_major")),
            )
        ):
            y_limit_table.setItem(row, column, QtWidgets.QTableWidgetItem(value))
    chart_layout.addWidget(make_section_label("Chart Y Limits By Voltage", chart_tab))
    chart_layout.addWidget(y_limit_table)
    tabs.addTab(chart_tab, "Envelope Chart")

    um_tab = QtWidgets.QWidget(tabs)
    um_layout = QtWidgets.QVBoxLayout(um_tab)
    um_layout.addWidget(
        make_muted_label(
            f"Project: {Path(project_path).name}" if project_path else "Select a project to edit Um values.",
            um_tab,
        )
    )
    um_table = QtWidgets.QTableWidget(0, 3, um_tab)
    um_table.setHorizontalHeaderLabels(["kV", "Um", "Source"])
    um_table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
    um_table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Stretch)
    um_table.horizontalHeader().setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.Stretch)
    xlsx_configs = {}
    um_overrides = {}
    if project_path:
        um_overrides = self.session.voltage_um_overrides_by_project.get(project_path, {})
        scan = self.project_scans.get(project_path)
        xlsx_configs = (
            scan.voltage_configs
            if scan is not None
            else load_voltage_configs(project_path, um_overrides={})
        )
        voltages = set(self.session.voltages)
        voltages.update(xlsx_configs)
        voltages.update(um_overrides)
        if scan is not None:
            voltages.update(scan.available_voltages)
        for voltage in self._sorted_voltages(voltages):
            row = um_table.rowCount()
            um_table.insertRow(row)
            voltage_item = QtWidgets.QTableWidgetItem(voltage)
            voltage_item.setFlags(QtCore.Qt.ItemFlag.ItemIsEnabled | QtCore.Qt.ItemFlag.ItemIsSelectable)
            um_table.setItem(row, 0, voltage_item)
            if voltage in um_overrides:
                um_value = um_overrides[voltage]
                source = "Manual"
            elif voltage in xlsx_configs:
                um_value = xlsx_configs[voltage].um
                source = "Input xlsx"
            else:
                um_value = ""
                source = "Missing"
            um_table.setItem(row, 1, QtWidgets.QTableWidgetItem(str(um_value)))
            source_item = QtWidgets.QTableWidgetItem(source)
            source_item.setFlags(QtCore.Qt.ItemFlag.ItemIsEnabled | QtCore.Qt.ItemFlag.ItemIsSelectable)
            um_table.setItem(row, 2, source_item)
    um_layout.addWidget(um_table)
    tabs.addTab(um_tab, "Voltage Um")

    events_tab = QtWidgets.QWidget(tabs)
    events_form = QtWidgets.QFormLayout(events_tab)
    event_spins: dict[str, QtWidgets.QDoubleSpinBox] = {}
    for event in DEFAULT_EVENTS:
        spin = QtWidgets.QDoubleSpinBox(events_tab)
        spin.setDecimals(4)
        spin.setRange(0.0, 10.0)
        spin.setSingleStep(0.001)
        spin.setSuffix(" s")
        spin.setValue(float(self.session.event_times.get(event, 0.0)))
        event_spins[event] = spin
        events_form.addRow(event, spin)
    tabs.addTab(events_tab, "Events")

    resonance_tab = QtWidgets.QWidget(tabs)
    resonance_layout = QtWidgets.QVBoxLayout(resonance_tab)
    resonance_form = QtWidgets.QFormLayout()
    resonance_layout.addWidget(
        make_muted_label("Enable checks from the top Analysis row. This page controls their thresholds.", resonance_tab)
    )

    resonance_top_n_spin = QtWidgets.QSpinBox(resonance_tab)
    resonance_top_n_spin.setRange(1, 20)
    resonance_top_n_spin.setValue(int(self.session.resonance_top_n))
    resonance_form.addRow("Top N per voltage/type/check", resonance_top_n_spin)

    resonance_limit_spin = QtWidgets.QDoubleSpinBox(resonance_tab)
    resonance_limit_spin.setDecimals(4)
    resonance_limit_spin.setRange(0.001, 100.0)
    resonance_limit_spin.setSingleStep(0.1)
    resonance_limit_spin.setValue(float(self.session.resonance_limit_multiplier))
    resonance_form.addRow("Voltage limit multiplier", resonance_limit_spin)

    resonance_auto_release_check = QtWidgets.QCheckBox("Auto-detect release/recovery time", resonance_tab)
    resonance_auto_release_check.setChecked(bool(self.session.resonance_auto_release))
    resonance_form.addRow("Release mode", resonance_auto_release_check)

    resonance_manual_start_spin = QtWidgets.QDoubleSpinBox(resonance_tab)
    resonance_manual_start_spin.setDecimals(4)
    resonance_manual_start_spin.setRange(0.0, 10.0)
    resonance_manual_start_spin.setSingleStep(0.001)
    resonance_manual_start_spin.setSuffix(" s")
    resonance_manual_start_spin.setValue(float(self.session.resonance_manual_analysis_start))
    resonance_manual_start_spin.setEnabled(not resonance_auto_release_check.isChecked())
    resonance_auto_release_check.toggled.connect(lambda checked: resonance_manual_start_spin.setEnabled(not checked))
    resonance_form.addRow("Manual analysis start time", resonance_manual_start_spin)
    resonance_layout.addLayout(resonance_form)

    sustained_tab = QtWidgets.QWidget(tabs)
    sustained_tab_layout = QtWidgets.QVBoxLayout(sustained_tab)
    sustained_group = QtWidgets.QGroupBox("Sustained SDPF Stress", sustained_tab)
    sustained_group_layout = QtWidgets.QVBoxLayout(sustained_group)
    sustained_form = QtWidgets.QFormLayout()
    sustained_duration_spin = QtWidgets.QDoubleSpinBox(sustained_group)
    sustained_duration_spin.setDecimals(2)
    sustained_duration_spin.setRange(0.1, 10000.0)
    sustained_duration_spin.setSingleStep(1.0)
    sustained_duration_spin.setSuffix(" ms")
    sustained_duration_spin.setValue(float(self.session.sustained_sdpf_duration_ms))
    sustained_duration_spin.setToolTip(
        "Minimum physical duration for the peak envelope to remain at or above the selected limit. "
        "A qualifying peak is still required in each relevant complete power-frequency cycle."
    )
    sustained_form.addRow("Minimum sustained duration", sustained_duration_spin)
    sustained_group_layout.addLayout(sustained_form)

    ranking_settings = sustained_sdpf.SustainedSDPFRankingSettings.from_mapping(
        self.session.sustained_sdpf_ranking_settings_by_project.get(project_path or "")
    )
    ranking_group = QtWidgets.QGroupBox("Representative ranking", sustained_group)
    ranking_layout = QtWidgets.QVBoxLayout(ranking_group)
    ranking_layout.addWidget(
        make_muted_label(
            "Controls selected representative plots and report subsections only; all metrics are always calculated.",
            ranking_group,
        )
    )
    highest_t_check = QtWidgets.QCheckBox(
        "Highest voltage sustained for T",
        ranking_group,
    )
    cumulative_stress_check = QtWidgets.QCheckBox(
        "Worst cumulative stress",
        ranking_group,
    )
    continuous_duration_check = QtWidgets.QCheckBox(
        "Longest continuous duration",
        ranking_group,
    )
    highest_t_check.setChecked(ranking_settings.highest_voltage_sustained)
    cumulative_stress_check.setChecked(ranking_settings.cumulative_stress)
    continuous_duration_check.setChecked(ranking_settings.continuous_duration)
    ranking_layout.addWidget(highest_t_check)
    ranking_layout.addWidget(cumulative_stress_check)
    ranking_layout.addWidget(continuous_duration_check)
    sustained_group_layout.addWidget(ranking_group)

    heatmap_metadata = (
        self._sustained_sdpf_heatmap_metadata(project_path)
        if project_path and hasattr(self, "_sustained_sdpf_heatmap_metadata")
        else sustained_sdpf_heatmap.HeatmapMetadata()
    )
    saved_heatmap_sets = [
        heatmap_set.normalized(heatmap_metadata)
        for heatmap_set in sustained_sdpf_heatmap.heatmap_sets_from_mapping(
            self.session.sustained_sdpf_heatmap_settings_by_project.get(project_path or "")
        )
    ]
    heatmap_sets = list(saved_heatmap_sets)
    active_heatmap_index = {"value": 0}
    active_heatmap_settings = {"value": heatmap_sets[0].settings}

    heatmap_set_row = QtWidgets.QHBoxLayout()
    heatmap_set_combo = QtWidgets.QComboBox(sustained_group)
    heatmap_set_combo.setToolTip("Select the named heatmap set to edit.")
    heatmap_add_button = QtWidgets.QPushButton("Add heatmap", sustained_group)
    heatmap_delete_button = QtWidgets.QPushButton("Delete", sustained_group)
    heatmap_up_button = QtWidgets.QPushButton("↑", sustained_group)
    heatmap_down_button = QtWidgets.QPushButton("↓", sustained_group)
    heatmap_set_row.addWidget(heatmap_set_combo, 1)
    heatmap_set_row.addWidget(heatmap_add_button)
    heatmap_set_row.addWidget(heatmap_delete_button)
    heatmap_set_row.addWidget(heatmap_up_button)
    heatmap_set_row.addWidget(heatmap_down_button)
    sustained_group_layout.addLayout(heatmap_set_row)
    heatmap_name_row = QtWidgets.QHBoxLayout()
    heatmap_name_row.addWidget(QtWidgets.QLabel("Set name", sustained_group))
    heatmap_name_edit = QtWidgets.QLineEdit(sustained_group)
    heatmap_name_edit.setToolTip("Display name used in the report and heatmap output folder.")
    heatmap_name_row.addWidget(heatmap_name_edit, 1)
    sustained_group_layout.addLayout(heatmap_name_row)
    heatmap_enabled_check = QtWidgets.QCheckBox("Create Sustained SDPF heatmap", sustained_group)
    sustained_group_layout.addWidget(heatmap_enabled_check)
    heatmap_form = QtWidgets.QFormLayout()
    heatmap_y_combo = QtWidgets.QComboBox(sustained_group)
    heatmap_x_combo = QtWidgets.QComboBox(sustained_group)
    heatmap_split_combo = QtWidgets.QComboBox(sustained_group)
    heatmap_max_cases_spin = QtWidgets.QSpinBox(sustained_group)
    heatmap_max_cases_spin.setRange(1, 500)
    heatmap_max_cases_spin.setValue(active_heatmap_settings["value"].max_cases_per_heatmap)
    heatmap_layout_combo = QtWidgets.QComboBox(sustained_group)
    heatmap_layout_combo.addItem("Separate files", sustained_sdpf_heatmap.HEATMAP_LAYOUT_SEPARATE)
    heatmap_layout_combo.addItem("Combined panels", sustained_sdpf_heatmap.HEATMAP_LAYOUT_COMBINED)
    heatmap_layout_combo.addItem("Automatic", sustained_sdpf_heatmap.HEATMAP_LAYOUT_AUTO)
    heatmap_layout_combo.setCurrentIndex(
        max(0, heatmap_layout_combo.findData(active_heatmap_settings["value"].layout))
    )
    heatmap_layout_combo.setToolTip(
        "Separate keeps the existing one-panel-per-file output. Combined and Automatic "
        "use shared faceted panels when split values are suitable."
    )
    heatmap_max_panels_spin = QtWidgets.QSpinBox(sustained_group)
    heatmap_max_panels_spin.setRange(1, 12)
    heatmap_max_panels_spin.setValue(active_heatmap_settings["value"].max_panels_per_heatmap)
    heatmap_max_panels_spin.setToolTip(
        "Maximum split panels in one combined image. Extra panels are paginated."
    )

    def combo_value(combo: QtWidgets.QComboBox) -> str | None:
        value = combo.currentData()
        return str(value) if value not in (None, "") else None

    def fill_combo(
        combo: QtWidgets.QComboBox,
        values: list[tuple[str, str]],
        selected: str | None,
        none_value: str | None = None,
    ) -> None:
        combo.blockSignals(True)
        try:
            combo.clear()
            combo.addItem("None", none_value)
            for label, value in values:
                combo.addItem(label, value)
            index = combo.findData(selected)
            combo.setCurrentIndex(index if index >= 0 else 0)
        finally:
            combo.blockSignals(False)

    heatmap_dimensions_initialized = False

    def refresh_heatmap_dimension_choices() -> None:
        nonlocal heatmap_dimensions_initialized
        initializing = not heatmap_dimensions_initialized
        saved_heatmap_settings = active_heatmap_settings["value"]
        y_value = saved_heatmap_settings.y_grouping if initializing else combo_value(heatmap_y_combo)
        y_values = [
            (heatmap_metadata.label(value), value)
            for value in heatmap_metadata.y_options
            if value != "All"
        ]
        fill_combo(
            heatmap_y_combo,
            y_values,
            y_value,
            sustained_sdpf_heatmap.NONE_GROUPING,
        )
        y_value = combo_value(heatmap_y_combo) or heatmap_metadata.default_y
        x_value = combo_value(heatmap_x_combo)
        if initializing and x_value is None:
            x_value = saved_heatmap_settings.x_grouping
        x_values = [
            (heatmap_metadata.label(value), value)
            for value in heatmap_metadata.token_options
            if value != y_value
        ]
        fill_combo(heatmap_x_combo, x_values, x_value if x_value != y_value else None)
        x_value = combo_value(heatmap_x_combo)
        split_value = combo_value(heatmap_split_combo)
        if initializing and split_value is None:
            split_value = saved_heatmap_settings.split_by
        split_values = [
            (heatmap_metadata.label(value), value)
            for value in heatmap_metadata.token_options
            if value not in {y_value, x_value}
        ]
        fill_combo(
            heatmap_split_combo,
            split_values,
            split_value if split_value not in {y_value, x_value} else None,
        )
        heatmap_dimensions_initialized = True

    heatmap_y_combo.currentIndexChanged.connect(lambda _index: refresh_heatmap_dimension_choices())
    heatmap_x_combo.currentIndexChanged.connect(lambda _index: refresh_heatmap_dimension_choices())
    heatmap_form.addRow("Y-axis grouping", heatmap_y_combo)
    heatmap_form.addRow("X grouping", heatmap_x_combo)
    heatmap_form.addRow("Split by", heatmap_split_combo)
    heatmap_form.addRow("Max cases per heatmap", heatmap_max_cases_spin)
    heatmap_form.addRow("Panel layout", heatmap_layout_combo)
    heatmap_form.addRow("Max panels per image", heatmap_max_panels_spin)
    sustained_group_layout.addLayout(heatmap_form)

    def refresh_heatmap_set_combo() -> None:
        heatmap_set_combo.blockSignals(True)
        try:
            heatmap_set_combo.clear()
            for heatmap_set in heatmap_sets:
                heatmap_set_combo.addItem(heatmap_set.name)
            heatmap_set_combo.setCurrentIndex(active_heatmap_index["value"])
        finally:
            heatmap_set_combo.blockSignals(False)
        heatmap_delete_button.setEnabled(len(heatmap_sets) > 1)
        heatmap_up_button.setEnabled(active_heatmap_index["value"] > 0)
        heatmap_down_button.setEnabled(active_heatmap_index["value"] < len(heatmap_sets) - 1)

    def load_heatmap_set(index: int) -> None:
        nonlocal heatmap_dimensions_initialized
        active_heatmap_index["value"] = max(0, min(index, len(heatmap_sets) - 1))
        heatmap_set = heatmap_sets[active_heatmap_index["value"]]
        active_heatmap_settings["value"] = heatmap_set.settings
        heatmap_name_edit.setText(heatmap_set.name)
        heatmap_enabled_check.setChecked(heatmap_set.settings.enabled)
        heatmap_max_cases_spin.setValue(heatmap_set.settings.max_cases_per_heatmap)
        heatmap_layout_combo.setCurrentIndex(
            max(0, heatmap_layout_combo.findData(heatmap_set.settings.layout))
        )
        heatmap_max_panels_spin.setValue(heatmap_set.settings.max_panels_per_heatmap)
        heatmap_dimensions_initialized = False
        refresh_heatmap_dimension_choices()
        refresh_heatmap_set_combo()

    def capture_heatmap_set() -> None:
        index = active_heatmap_index["value"]
        current = active_heatmap_settings["value"]
        updated = sustained_sdpf_heatmap.HeatmapSettings(
            enabled=heatmap_enabled_check.isChecked(),
            y_grouping=combo_value(heatmap_y_combo) or heatmap_metadata.default_y,
            x_grouping=combo_value(heatmap_x_combo),
            split_by=combo_value(heatmap_split_combo),
            max_cases_per_heatmap=int(heatmap_max_cases_spin.value()),
            layout=combo_value(heatmap_layout_combo) or sustained_sdpf_heatmap.HEATMAP_LAYOUT_SEPARATE,
            max_panels_per_heatmap=int(heatmap_max_panels_spin.value()),
        ).normalized(heatmap_metadata)
        name = heatmap_name_edit.text().strip() or current.name
        heatmap_sets[index] = sustained_sdpf_heatmap.HeatmapSet(name, updated)
        active_heatmap_settings["value"] = updated

    def change_heatmap_set(index: int) -> None:
        capture_heatmap_set()
        load_heatmap_set(index)

    def add_heatmap_set() -> None:
        capture_heatmap_set()
        used = {heatmap_set.name.casefold() for heatmap_set in heatmap_sets}
        number = len(heatmap_sets) + 1
        name = f"Heatmap {number}"
        while name.casefold() in used:
            number += 1
            name = f"Heatmap {number}"
        source = heatmap_sets[active_heatmap_index["value"]]
        heatmap_sets.append(sustained_sdpf_heatmap.HeatmapSet(name, source.settings))
        load_heatmap_set(len(heatmap_sets) - 1)

    def delete_heatmap_set() -> None:
        if len(heatmap_sets) <= 1:
            return
        del heatmap_sets[active_heatmap_index["value"]]
        load_heatmap_set(min(active_heatmap_index["value"], len(heatmap_sets) - 1))

    def move_heatmap_set(delta: int) -> None:
        index = active_heatmap_index["value"]
        target = index + delta
        if target < 0 or target >= len(heatmap_sets):
            return
        capture_heatmap_set()
        heatmap_sets[index], heatmap_sets[target] = heatmap_sets[target], heatmap_sets[index]
        load_heatmap_set(target)

    heatmap_set_combo.currentIndexChanged.connect(change_heatmap_set)
    heatmap_add_button.clicked.connect(add_heatmap_set)
    heatmap_delete_button.clicked.connect(delete_heatmap_set)
    heatmap_up_button.clicked.connect(lambda: move_heatmap_set(-1))
    heatmap_down_button.clicked.connect(lambda: move_heatmap_set(1))
    # The controls use the current scanner cache; no result files are read here.
    refresh_heatmap_set_combo()
    load_heatmap_set(0)
    sustained_limit_table = QtWidgets.QTableWidget(0, 7, sustained_group)
    sustained_limit_table.setHorizontalHeaderLabels(
        [
            "kV",
            "Type",
            "SDPF RMS (kV)",
            "SDPF peak (kV)",
            "SDPF/1.15 RMS (kV)",
            "SDPF/1.15 peak (kV)",
            "Source",
        ]
    )
    sustained_limit_table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.AllEditTriggers)
    sustained_limit_table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
    sustained_limit_table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
    for column in range(2, 6):
        sustained_limit_table.horizontalHeader().setSectionResizeMode(column, QtWidgets.QHeaderView.ResizeMode.Stretch)
    sustained_limit_table.horizontalHeader().setSectionResizeMode(6, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
    limits = project_scan.sustained_sdpf_limits if project_scan is not None else {}
    sustained_limit_overrides = {
        voltage: dict(values)
        for voltage, values in self.session.sustained_sdpf_limit_overrides_by_project.get(
            project_path or "", {}
        ).items()
    }
    sustained_limit_rows: dict[int, tuple[str, str]] = {}

    def sustained_limit_for_row(
        voltage: str,
        measurement: str,
        rms: float,
    ) -> sustained_sdpf.SDPFVoltageLimits:
        base = limits[voltage]
        return sustained_sdpf.SDPFVoltageLimits(
            base.voltage_kv,
            rms if measurement == "LGp" else base.sdpf_lg_rms,
            rms if measurement == "LLp" else base.sdpf_ll_rms,
            "manual" if measurement in sustained_limit_overrides.get(voltage, {}) else base.source,
        )

    def sustained_limit_source(voltage: str, measurement: str, limit: sustained_sdpf.SDPFVoltageLimits) -> str:
        if measurement in sustained_limit_overrides.get(voltage, {}):
            return "Manual"
        if str(limit.source).casefold() == "workbook":
            return "Input xlsx"
        return str(limit.source).replace("_", " ").title()

    def readonly_item(text: str) -> QtWidgets.QTableWidgetItem:
        item = QtWidgets.QTableWidgetItem(text)
        item.setFlags(QtCore.Qt.ItemFlag.ItemIsEnabled | QtCore.Qt.ItemFlag.ItemIsSelectable)
        return item

    def refresh_sustained_limit_row(row: int) -> None:
        row_key = sustained_limit_rows.get(row)
        if row_key is None:
            return
        voltage, measurement = row_key
        base = limits.get(voltage)
        rms_item = sustained_limit_table.item(row, 2)
        if base is None or rms_item is None:
            return
        try:
            rms = float(rms_item.text())
        except (TypeError, ValueError):
            return
        if not math.isfinite(rms) or rms <= 0:
            return
        limit = sustained_limit_for_row(voltage, measurement, rms)
        computed = (
            f"{limit.peak(measurement):g}",
            f"{limit.margin_rms(measurement):g}",
            f"{limit.margin_peak(measurement):g}",
            sustained_limit_source(voltage, measurement, limit),
        )
        sustained_limit_table.blockSignals(True)
        try:
            for column, text in zip((3, 4, 5, 6), computed):
                item = sustained_limit_table.item(row, column)
                if item is None:
                    item = readonly_item(text)
                    sustained_limit_table.setItem(row, column, item)
                else:
                    item.setText(text)
        finally:
            sustained_limit_table.blockSignals(False)

    def sustained_limit_item_changed(item: QtWidgets.QTableWidgetItem) -> None:
        if item.column() != 2:
            return
        row_key = sustained_limit_rows.get(item.row())
        if row_key is None:
            return
        voltage, measurement = row_key
        base = limits.get(voltage)
        if base is None:
            return
        try:
            rms = float(item.text())
        except (TypeError, ValueError):
            rms = math.nan
        if not math.isfinite(rms) or rms <= 0:
            previous = item.data(QtCore.Qt.ItemDataRole.UserRole)
            try:
                rms = float(previous)
            except (TypeError, ValueError):
                rms = base.rms(measurement)
            sustained_limit_table.blockSignals(True)
            try:
                item.setText(f"{rms:g}")
            finally:
                sustained_limit_table.blockSignals(False)
        default_rms = base.rms(measurement)
        values = sustained_limit_overrides.setdefault(voltage, {})
        if abs(rms - default_rms) <= 1e-9:
            values.pop(measurement, None)
        else:
            values[measurement] = rms
        if not values:
            sustained_limit_overrides.pop(voltage, None)
        item.setData(QtCore.Qt.ItemDataRole.UserRole, rms)
        refresh_sustained_limit_row(item.row())

    if project_path:
        for voltage, limit in sorted(limits.items(), key=lambda item: float(item[0])):
            for measurement in ("LGp", "LLp"):
                row = sustained_limit_table.rowCount()
                sustained_limit_table.insertRow(row)
                sustained_limit_rows[row] = (voltage, measurement)
                value = sustained_limit_overrides.get(voltage, {}).get(
                    measurement,
                    limit.rms(measurement),
                )
                sustained_limit_table.setItem(row, 0, readonly_item(voltage))
                sustained_limit_table.setItem(row, 1, readonly_item(measurement[:-1]))
                rms_item = QtWidgets.QTableWidgetItem(f"{value:g}")
                rms_item.setData(QtCore.Qt.ItemDataRole.UserRole, value)
                sustained_limit_table.setItem(row, 2, rms_item)
                for column in (3, 4, 5, 6):
                    sustained_limit_table.setItem(row, column, readonly_item(""))
                refresh_sustained_limit_row(row)
    sustained_limit_table.itemChanged.connect(sustained_limit_item_changed)
    sustained_group_layout.addWidget(sustained_limit_table)
    sustained_tab_layout.addWidget(sustained_group)
    sustained_tab_layout.addStretch(1)
    tabs.addTab(sustained_tab, "Sustained SDPF")

    advanced_group = QtWidgets.QGroupBox("Algorithm constants", resonance_tab)
    advanced_form = QtWidgets.QFormLayout(advanced_group)

    def fraction_spin(value: float) -> QtWidgets.QDoubleSpinBox:
        spin = QtWidgets.QDoubleSpinBox(advanced_group)
        spin.setDecimals(4)
        spin.setRange(0.0001, 1.0)
        spin.setSingleStep(0.01)
        spin.setValue(float(value))
        return spin

    def seconds_spin(value: float) -> QtWidgets.QDoubleSpinBox:
        spin = QtWidgets.QDoubleSpinBox(advanced_group)
        spin.setDecimals(4)
        spin.setRange(0.0001, 10.0)
        spin.setSingleStep(0.001)
        spin.setSuffix(" s")
        spin.setValue(float(value))
        return spin

    peak_fraction_spin = fraction_spin(self.session.resonance_peak_search_fraction)
    release_decay_spin = fraction_spin(self.session.resonance_release_decay_ratio)
    release_rebound_spin = fraction_spin(self.session.resonance_release_rebound_ratio)
    release_hold_spin = seconds_spin(self.session.resonance_release_hold_time)
    rolling_window_spin = seconds_spin(self.session.resonance_rolling_p95_window)
    rolling_min_spin = QtWidgets.QSpinBox(advanced_group)
    rolling_min_spin.setRange(1, 10000)
    rolling_min_spin.setValue(int(self.session.resonance_rolling_min_samples))
    log_floor_factor_spin = QtWidgets.QDoubleSpinBox(advanced_group)
    log_floor_factor_spin.setDecimals(8)
    log_floor_factor_spin.setRange(0.00000001, 1.0)
    log_floor_factor_spin.setValue(float(self.session.resonance_log_floor_vlim_factor))
    log_floor_absolute_spin = QtWidgets.QDoubleSpinBox(advanced_group)
    log_floor_absolute_spin.setDecimals(8)
    log_floor_absolute_spin.setRange(0.00000001, 1000.0)
    log_floor_absolute_spin.setValue(float(self.session.resonance_log_floor_absolute))
    growth_window_fraction_spin = fraction_spin(self.session.resonance_growth_window_fraction)
    min_positive_fraction_spin = fraction_spin(self.session.resonance_min_positive_fraction)
    min_growth_ratio_spin = QtWidgets.QDoubleSpinBox(advanced_group)
    min_growth_ratio_spin.setDecimals(4)
    min_growth_ratio_spin.setRange(1.0, 100.0)
    min_growth_ratio_spin.setSingleStep(0.01)
    min_growth_ratio_spin.setValue(float(self.session.resonance_min_growth_ratio))
    min_level_spin = QtWidgets.QDoubleSpinBox(advanced_group)
    min_level_spin.setDecimals(4)
    min_level_spin.setRange(0.0001, 100.0)
    min_level_spin.setSingleStep(0.05)
    min_level_spin.setValue(float(self.session.resonance_min_level_over_vlim))
    min_delta_factor_spin = QtWidgets.QDoubleSpinBox(advanced_group)
    min_delta_factor_spin.setDecimals(4)
    min_delta_factor_spin.setRange(0.0001, 100.0)
    min_delta_factor_spin.setSingleStep(0.01)
    min_delta_factor_spin.setValue(float(self.session.resonance_min_growth_delta_factor))

    advanced_form.addRow("Peak search fraction", peak_fraction_spin)
    advanced_form.addRow("Release decay ratio", release_decay_spin)
    advanced_form.addRow("Release rebound ratio", release_rebound_spin)
    advanced_form.addRow("Release hold time", release_hold_spin)
    advanced_form.addRow("Trailing rolling p95 window", rolling_window_spin)
    advanced_form.addRow("Rolling minimum samples", rolling_min_spin)
    advanced_form.addRow("Log floor Vlim factor", log_floor_factor_spin)
    advanced_form.addRow("Log floor absolute", log_floor_absolute_spin)
    advanced_form.addRow("Growth window fraction", growth_window_fraction_spin)
    advanced_form.addRow("Minimum positive fraction", min_positive_fraction_spin)
    advanced_form.addRow("Minimum growth ratio", min_growth_ratio_spin)
    advanced_form.addRow("Minimum level over Vlim", min_level_spin)
    advanced_form.addRow("Minimum growth delta factor", min_delta_factor_spin)
    resonance_layout.addWidget(advanced_group)
    resonance_layout.addStretch(1)
    tabs.addTab(resonance_tab, "Resonance Checks")

    if initial_tab:
        for index in range(tabs.count()):
            if tabs.tabText(index) == initial_tab:
                tabs.setCurrentIndex(index)
                break
    layout.addWidget(tabs)

    buttons = QtWidgets.QDialogButtonBox(
        QtWidgets.QDialogButtonBox.StandardButton.Ok
        | QtWidgets.QDialogButtonBox.StandardButton.Cancel,
        dialog,
    )
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)

    if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
        return

    def optional_number(item: QtWidgets.QTableWidgetItem | None) -> float | None:
        if item is None or not item.text().strip():
            return None
        try:
            return float(item.text())
        except ValueError:
            return None

    old_nonconv_limits = (
        float(self.session.nonconv_cb_iip_limit),
        float(self.session.nonconv_cb_iir_limit),
    )
    old_high_voltage_factor = float(self.session.high_voltage_limit_factor)
    old_fallback_frequency = float(self.session.envelope_fallback_frequency)
    old_um_overrides = dict(
        self.session.voltage_um_overrides_by_project.get(project_path or "", {})
    )
    old_sustained_limit_overrides = {
        voltage: dict(values)
        for voltage, values in self.session.sustained_sdpf_limit_overrides_by_project.get(
            project_path or "", {}
        ).items()
    }
    self.session.envelope_workers = int(workers_spin.value())
    self.session.envelope_workers_auto = workers_auto_check.isChecked()
    self.session.envelope_time_step = float(time_step_spin.value())
    self.session.envelope_time_end_auto = time_end_auto_check.isChecked()
    self.session.excel_waveform_exports_enabled = excel_exports_check.isChecked()
    if not self.session.envelope_time_end_auto:
        self.session.envelope_time_end = float(time_end_spin.value())
    if project_frequency is None:
        self.session.envelope_fallback_frequency = float(fallback_frequency_spin.value())
    if project_path:
        if chart_x_max_auto.isChecked():
            self.session.envelope_chart_x_max_overrides_by_project.pop(project_path, None)
        else:
            self.session.envelope_chart_x_max_overrides_by_project[project_path] = float(
                chart_x_max_spin.value()
            )
        if chart_x_major_auto.isChecked():
            self.session.envelope_chart_x_major_overrides_by_project.pop(project_path, None)
        else:
            self.session.envelope_chart_x_major_overrides_by_project[project_path] = float(
                chart_x_major_spin.value()
            )
    self.session.envelope_chart_top_left_cell = chart_top_left_edit.text().strip() or "H1"
    self.session.envelope_chart_width = float(chart_width_spin.value())
    self.session.envelope_chart_height = float(chart_height_spin.value())
    self.session.envelope_chart_show_sa_label = show_sa_label_check.isChecked()
    raw_y_limits = {}
    for row in range(y_limit_table.rowCount()):
        voltage_item = y_limit_table.item(row, 0)
        if voltage_item is None or not voltage_item.text().strip():
            continue
        raw_y_limits[voltage_item.text()] = {
            "y_min": optional_number(y_limit_table.item(row, 1)),
            "y_max": optional_number(y_limit_table.item(row, 2)),
            "y_major": optional_number(y_limit_table.item(row, 3)),
        }
    self.session.envelope_chart_y_limits_by_voltage = normalize_chart_y_limits(raw_y_limits)
    if project_path:
        overrides = {}
        for row in range(um_table.rowCount()):
            voltage_item = um_table.item(row, 0)
            um_item = um_table.item(row, 1)
            if voltage_item is None or um_item is None:
                continue
            voltage = voltage_item.text().strip()
            if not voltage:
                continue
            try:
                um = float(um_item.text())
            except ValueError:
                continue
            default = xlsx_configs.get(voltage)
            if default is None or abs(default.um - um) > 1e-9:
                overrides[voltage] = um
        if overrides:
            self.session.voltage_um_overrides_by_project[project_path] = overrides
        else:
            self.session.voltage_um_overrides_by_project.pop(project_path, None)
    self.session.high_voltage_limit_factor = float(high_voltage_factor_spin.value())
    self.session.nonconv_cb_iip_limit = float(nonconv_iip_spin.value())
    self.session.nonconv_cb_iir_limit = float(nonconv_iir_spin.value())
    self.session.resonance_top_n = int(resonance_top_n_spin.value())
    self.session.resonance_limit_multiplier = float(resonance_limit_spin.value())
    self.session.resonance_auto_release = resonance_auto_release_check.isChecked()
    self.session.resonance_manual_analysis_start = float(resonance_manual_start_spin.value())
    self.session.resonance_peak_search_fraction = float(peak_fraction_spin.value())
    self.session.resonance_release_decay_ratio = float(release_decay_spin.value())
    self.session.resonance_release_rebound_ratio = float(release_rebound_spin.value())
    self.session.resonance_release_hold_time = float(release_hold_spin.value())
    self.session.resonance_rolling_p95_window = float(rolling_window_spin.value())
    self.session.resonance_rolling_min_samples = int(rolling_min_spin.value())
    self.session.resonance_log_floor_vlim_factor = float(log_floor_factor_spin.value())
    self.session.resonance_log_floor_absolute = float(log_floor_absolute_spin.value())
    self.session.resonance_growth_window_fraction = float(growth_window_fraction_spin.value())
    self.session.resonance_min_positive_fraction = float(min_positive_fraction_spin.value())
    self.session.resonance_min_growth_ratio = float(min_growth_ratio_spin.value())
    self.session.resonance_min_level_over_vlim = float(min_level_spin.value())
    self.session.resonance_min_growth_delta_factor = float(min_delta_factor_spin.value())
    self.session.sustained_sdpf_duration_ms = float(sustained_duration_spin.value())
    if project_path:
        self.session.sustained_sdpf_ranking_settings_by_project[project_path] = (
            sustained_sdpf.SustainedSDPFRankingSettings(
                highest_voltage_sustained=highest_t_check.isChecked(),
                cumulative_stress=cumulative_stress_check.isChecked(),
                continuous_duration=continuous_duration_check.isChecked(),
            ).to_mapping()
        )
        capture_heatmap_set()
        self.session.sustained_sdpf_heatmap_settings_by_project[project_path] = (
            sustained_sdpf_heatmap.heatmap_sets_to_mapping(heatmap_sets)
        )
    if project_path and limits:
        if sustained_limit_overrides:
            self.session.sustained_sdpf_limit_overrides_by_project[project_path] = {
                voltage: dict(values)
                for voltage, values in sustained_limit_overrides.items()
            }
        else:
            self.session.sustained_sdpf_limit_overrides_by_project.pop(project_path, None)
    new_sustained_limit_overrides = {
        voltage: dict(values)
        for voltage, values in self.session.sustained_sdpf_limit_overrides_by_project.get(
            project_path or "", {}
        ).items()
    }
    event_times = {event: float(spin.value()) for event, spin in event_spins.items()}
    self.session.event_times = event_times
    new_nonconv_limits = (
        float(self.session.nonconv_cb_iip_limit),
        float(self.session.nonconv_cb_iir_limit),
    )
    if project_path and (
        new_nonconv_limits != old_nonconv_limits
        or float(self.session.high_voltage_limit_factor) != old_high_voltage_factor
        or self.session.voltage_um_overrides_by_project.get(project_path, {}) != old_um_overrides
        or new_sustained_limit_overrides != old_sustained_limit_overrides
        or (
            project_frequency is None
            and float(self.session.envelope_fallback_frequency) != old_fallback_frequency
        )
    ):
        sustained_sdpf.invalidate_results(project_path)
    self.autosave()
    if rebuild_cache_requested:
        QtCore.QTimer.singleShot(0, lambda: self.refresh_project_scans(force=True))
    elif (
        new_nonconv_limits != old_nonconv_limits
        or float(self.session.high_voltage_limit_factor) != old_high_voltage_factor
    ):
        self.refresh_project_scans()
    elif project_path and (
        self.session.voltage_um_overrides_by_project.get(project_path, {})
        != old_um_overrides
    ):
        self.refresh_project_scans(project_paths=[project_path])
