from __future__ import annotations

from collections import OrderedDict
import hashlib
import math
import re
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.gridspec import GridSpec

from pscad_plotter_app_v3.models import (
    DEFAULT_TOV_WINDOW_S,
    FFT_OUTPUT_DC,
    FFT_OUTPUT_MAGNITUDES,
    FFT_OUTPUT_PHASE_ANGLES,
    FFT_PHASE_DEGREES,
    PlotJob,
    PlotMode,
    SignalReference,
)
from pscad_plotter_app_v3.services.axis_labels import unit_axis_label, unit_suffix
from pscad_plotter_app_v3.services.fft import parse_harmonic_selection, rolling_fft
from pscad_plotter_app_v3.services.project_conventions import find_stat_file, load_run_event_info
from pscad_plotter_app_v3.services.signal_classification import is_any_rms_signal
from pscad_plotter_app_v3.services.waveform_io import (
    InfDescriptor,
    WaveformFrame,
    load_out_frame,
    parse_inf_descriptors,
    pgb_to_out_location,
    standard_out_file_path,
)


class MatplotlibRenderer:
    """Legacy plot renderer extracted from the current plotting script."""

    FIGSIZE = (15, 8)
    DPI = 300
    PHASE_COLS = [1, 2, 3]
    PHASE_COLOURS = ["red", "green", "blue"]
    COMBINED_COLOURS = ["#005f8a", "#d95f02", "#1b7837", "#984ea3", "#a6761d", "#666666", "#e7298a", "#66a61e"]
    LINEWIDTH_GRID = 0.25
    GRID_ALPHA = 0.6
    LINEWIDTH_TRACE = 0.6
    LINEWIDTH_ANNO = 0.7
    LINEWIDTH_LIMIT_THIN = 0.5
    LINEWIDTH_LIMIT_THICK = 1.0
    FONTSIZE_TITLE = 13
    FONTSIZE_ANNO = 10
    FONTSIZE_LEGEND = 9
    ANNOTATION_COLOUR = "#b04cff"
    PAD_YLIM = 0.07
    WINDOW_MULTIPLIER = 1
    ANNO_X_OFFSET = -0.002
    ANNO_Y_OFFSET = 0.02
    ANNO_Y_LIMIT_PAD = 0.10
    TIGHT_LAYOUT_PAD = 2.0
    SAFETY_MARGIN = 1.15
    TIME_TOV = DEFAULT_TOV_WINDOW_S
    INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*]+')
    MAX_FILENAME_STEM_LENGTH = 180
    COMBINED_FILENAME_SIGNAL_LIMIT = 2
    MAX_INF_CACHE = 128
    MAX_EVENT_INFO_CACHE = 256
    MAX_OUT_FILE_CACHE = 256

    def __init__(self, run_index: dict[str, dict[int, Path]]) -> None:
        self.run_index = run_index
        self._inf_cache: OrderedDict[Path, list[InfDescriptor]] = OrderedDict()
        self._event_info_cache: OrderedDict[tuple[Path, int], dict[str, object] | None] = OrderedDict()
        self._out_file_cache: OrderedDict[Path, WaveformFrame] = OrderedDict()

    def render(self, job: PlotJob) -> Path:
        inf_path = self._resolve_inf_path(job.case_name, job.run_number)
        stat_path = find_stat_file(inf_path.parent)
        event_info = self._load_event_info(stat_path, job.run_number) if stat_path is not None else None
        desc_df = self._load_inf_descriptors(inf_path)
        output_dir = Path(job.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        if job.mode is PlotMode.MM:
            if job.trace_type == "Both":
                if job.show_limits and job.limits is None:
                    raise ValueError(f"No MM limits configured for {job.group_label} ({job.voltage_kv:g} kV)")
                return self._render_mm_combined(job, inf_path, desc_df, event_info, output_dir)
            if job.show_limits and job.limits is None:
                raise ValueError(f"No MM limits configured for {job.group_label} ({job.voltage_kv:g} kV)")
            return self._render_single(job, inf_path, desc_df, event_info, output_dir, finder=job.trace_type or "LGp")

        if job.mode is PlotMode.CB:
            return self._render_single(job, inf_path, desc_df, event_info, output_dir, finder="IIp")

        if job.mode is PlotMode.FFT:
            return self._render_fft_channel(job, inf_path, desc_df, event_info, output_dir)

        if job.mode is PlotMode.COMB:
            return self._render_combined_channels(job, inf_path, desc_df, event_info, output_dir)

        return self._render_any_channel(job, inf_path, desc_df, event_info, output_dir)

    def resolve_inf_path(self, case_name: str, run_number: int) -> Path:
        return self._resolve_inf_path(case_name, run_number)

    def load_inf_descriptors(self, inf_path: Path) -> list[InfDescriptor]:
        return self._load_inf_descriptors(inf_path)

    def select_any_signal_rows(self, desc_df: list[InfDescriptor], group_name: str, signal_name: str, signal_view: str) -> list[InfDescriptor]:
        return self._select_any_signal_rows(desc_df, group_name, signal_name, signal_view)

    def load_any_signal_frame(self, inf_path: Path, rows: list[InfDescriptor]) -> WaveformFrame:
        return self._load_out_files(inf_path, rows, {})

    def load_standardized_group_frame(
        self,
        inf_path: Path,
        desc_df: list[InfDescriptor],
        group_label: str,
        finder: str,
    ) -> WaveformFrame:
        idx_map = self._filter_signals(desc_df, group_label)
        if finder not in idx_map:
            raise ValueError(f"Signal '{finder}' not available for {group_label}")
        policy = self._get_group_policy(group_label)
        frame = self._load_out_files(inf_path, idx_map[finder], {})
        return self._standardize_phase_labels(frame, finder, policy["kind"], group_label)

    def _resolve_inf_path(self, case_name: str, run_number: int) -> Path:
        try:
            return self.run_index[case_name][run_number]
        except KeyError as exc:
            raise FileNotFoundError(f"Missing .inf file for case '{case_name}' run {run_number}") from exc

    def _render_mm_combined(self, job: PlotJob, inf_path: Path, desc_df: list[InfDescriptor], event_info: dict[str, object] | None, output_dir: Path) -> Path:
        idx_map = self._filter_signals(desc_df, job.group_label)
        if "LGp" not in idx_map or "LLp" not in idx_map:
            raise ValueError(f"Combined MM plot requires LGp and LLp for {job.group_label}")

        policy = self._get_group_policy(job.group_label, None)
        out_cache: dict[int, WaveformFrame] = {}
        bundle_lg = self._process_finder(job, inf_path, idx_map["LGp"], "LGp", "LGp", event_info, policy, out_cache, show_limits=job.show_limits, tov_window_s=job.tov_window_s)
        bundle_ll = self._process_finder(job, inf_path, idx_map["LLp"], "LLp", "LLp", event_info, policy, out_cache, show_limits=job.show_limits, tov_window_s=job.tov_window_s)
        basename, title = self._make_labels(job.case_name, job.group_label, job.run_number, "LGp", event_info, combine=True)

        out = output_dir / f"{basename}_3Ph.png"
        plt.figure(figsize=(self.FIGSIZE[0], 2 * self.FIGSIZE[1]))
        if job.show_three_phase_overview:
            gs = GridSpec(4, 3, height_ratios=[1, 1, 1, 1])

            ax_top_lg = plt.subplot(gs[0, :])
            self._configure_axes(ax_top_lg, bundle_lg["df"], bundle_lg["ylim"], bundle_lg["policy"], legends_left=job.legends_left)
            self._add_limits_if_applicable(ax_top_lg, bundle_lg["limits_pack"], legends_left=job.legends_left)

            for index in range(3):
                axis = plt.subplot(gs[1, index])
                self._configure_axes(axis, bundle_lg["df"], bundle_lg["ylim"], bundle_lg["policy"], phase_y=[index + 1], colors=[self.PHASE_COLOURS[index]])
                axis.set_xlim(bundle_lg["xwin_peak"])
                self._render_window_markers_if_enabled(axis, job, bundle_lg["t_peak"])
                self._render_insulation_limits(axis, bundle_lg["limits_pack"])
                if index == bundle_lg["phase_idx"]:
                    self._render_peak_annotation(axis, bundle_lg["t_peak"], bundle_lg["y_peak"], bundle_lg["unit_suffix"], "black")

            ax_top_ll = plt.subplot(gs[2, :])
            self._configure_axes(ax_top_ll, bundle_ll["df"], bundle_ll["ylim"], bundle_ll["policy"], legends_left=job.legends_left)
            self._add_limits_if_applicable(ax_top_ll, bundle_ll["limits_pack"], legends_left=job.legends_left)

            for index in range(3):
                axis = plt.subplot(gs[3, index])
                self._configure_axes(axis, bundle_ll["df"], bundle_ll["ylim"], bundle_ll["policy"], phase_y=[index + 1], colors=[self.PHASE_COLOURS[index]])
                axis.set_xlim(bundle_ll["xwin_peak"])
                self._render_window_markers_if_enabled(axis, job, bundle_ll["t_peak"])
                self._render_insulation_limits(axis, bundle_ll["limits_pack"])
                if index == bundle_ll["phase_idx"]:
                    self._render_peak_annotation(axis, bundle_ll["t_peak"], bundle_ll["y_peak"], bundle_ll["unit_suffix"], "black")
        else:
            gs = GridSpec(2, 1)
            ax_top_lg = plt.subplot(gs[0, 0])
            self._configure_axes(ax_top_lg, bundle_lg["df"], bundle_lg["ylim"], bundle_lg["policy"], legends_left=job.legends_left)
            self._add_limits_if_applicable(ax_top_lg, bundle_lg["limits_pack"], legends_left=job.legends_left)

            ax_top_ll = plt.subplot(gs[1, 0])
            self._configure_axes(ax_top_ll, bundle_ll["df"], bundle_ll["ylim"], bundle_ll["policy"], legends_left=job.legends_left)
            self._add_limits_if_applicable(ax_top_ll, bundle_ll["limits_pack"], legends_left=job.legends_left)

        self._finalize_plot(out, title)
        return out

    def _render_single(self, job: PlotJob, inf_path: Path, desc_df: list[InfDescriptor], event_info: dict[str, object] | None, output_dir: Path, finder: str) -> Path:
        idx_map = self._filter_signals(desc_df, job.group_label)
        if finder not in idx_map:
            raise ValueError(f"Signal '{finder}' not available for {job.group_label}")
        policy = self._get_group_policy(job.group_label)
        bundle = self._process_finder(job, inf_path, idx_map[finder], finder, finder, event_info, policy, {}, show_limits=job.show_limits, tov_window_s=job.tov_window_s)
        out = output_dir / f"{bundle['basename']}_3Ph.png"

        plt.figure(figsize=self.FIGSIZE)
        self._render_three_phase_signal_axes(
            job,
            bundle["df"],
            bundle["ylim"],
            bundle["policy"],
            bundle,
            limits_pack=bundle["limits_pack"],
        )
        self._finalize_plot(out, bundle["title"])
        return out

    def _render_three_phase_signal_axes(
        self,
        job: PlotJob,
        data: WaveformFrame,
        ylim: tuple[float, float],
        policy: dict[str, Any],
        analysis: dict[str, Any],
        *,
        limits_pack: dict[str, float] | None = None,
        annotate_rms: bool = False,
    ) -> None:
        if job.show_three_phase_overview:
            gs = GridSpec(2, 3, height_ratios=[1, 1])
            ax_top = plt.subplot(gs[0, :])
            self._configure_axes(ax_top, data, ylim, policy, legends_left=job.legends_left)
            if limits_pack:
                self._add_limits_if_applicable(ax_top, limits_pack, legends_left=job.legends_left)
            if annotate_rms:
                self._render_rms_annotations_if_enabled(ax_top, job, data, policy)

            for index in range(3):
                axis = plt.subplot(gs[1, index])
                self._configure_axes(axis, data, ylim, policy, phase_y=[index + 1], colors=[self.PHASE_COLOURS[index]])
                axis.set_xlim(analysis["xwin_peak"])
                self._render_window_markers_if_enabled(axis, job, analysis["t_peak"])
                if limits_pack:
                    self._render_insulation_limits(axis, limits_pack)
                if index == analysis["phase_idx"]:
                    self._render_peak_annotation(axis, analysis["t_peak"], analysis["y_peak"], policy["unit_suffix"], "black")
            return

        axis = plt.subplot(111)
        self._configure_axes(axis, data, ylim, policy, legends_left=job.legends_left)
        if limits_pack:
            self._add_limits_if_applicable(axis, limits_pack, legends_left=job.legends_left)
        if annotate_rms:
            self._render_rms_annotations_if_enabled(axis, job, data, policy)

    def _render_any_channel(self, job: PlotJob, inf_path: Path, desc_df: list[InfDescriptor], event_info: dict[str, object] | None, output_dir: Path) -> Path:
        signal_view = job.signal_view or "bundle"
        if signal_view == "individual":
            return self._render_any_channel_single(job, inf_path, desc_df, event_info, output_dir)
        return self._render_any_channel_bundle(job, inf_path, desc_df, event_info, output_dir)

    def _render_any_channel_bundle(self, job: PlotJob, inf_path: Path, desc_df: list[InfDescriptor], event_info: dict[str, object] | None, output_dir: Path) -> Path:
        if not job.signal_name:
            raise ValueError(f"Missing bundled signal selection for {job.group_label}")
        signal_rows = self._select_any_signal_rows(desc_df, job.group_label, job.signal_name, "bundle")
        combined_label = f"{job.group_label}:{job.signal_name}"
        unit = str(signal_rows[0].Unit)
        policy = self._get_group_policy(combined_label, unit)
        policy = self._apply_custom_y_axis_name(policy, unit, job.custom_y_axis_name)
        data = self._load_out_files(inf_path, signal_rows, {})
        phase_labels = [str(row.Description) for row in signal_rows]
        data = data.renamed([data.columns[0]] + phase_labels)
        data = self._crop_to_job_time_range(job, data)
        analysis = self._analyze_data(data, job.signal_name or "bundle", policy, None, False, job.tov_window_s, job.tov_window_count)
        basename, title = self._make_labels(job.case_name, combined_label, job.run_number, job.signal_name, event_info)
        basename = self._basename_with_time_range(job, basename)
        out = output_dir / f"{basename}_3Ph.png"

        plt.figure(figsize=self.FIGSIZE)
        self._render_three_phase_signal_axes(job, data, analysis["ylim"], policy, analysis, annotate_rms=True)
        self._finalize_plot(out, title)
        return out

    def _render_any_channel_single(self, job: PlotJob, inf_path: Path, desc_df: list[InfDescriptor], event_info: dict[str, object] | None, output_dir: Path) -> Path:
        if not job.signal_name:
            raise ValueError(f"Missing individual signal selection for {job.group_label}")
        signal_rows = self._select_any_signal_rows(desc_df, job.group_label, job.signal_name, "individual")
        combined_label = f"{job.group_label}:{job.signal_name}"
        unit = str(signal_rows[0].Unit)
        policy = self._get_group_policy(combined_label, unit)
        policy = self._apply_custom_y_axis_name(policy, unit, job.custom_y_axis_name)
        data = self._load_out_files(inf_path, signal_rows, {})
        data = data.renamed([data.columns[0], job.signal_name])
        data = self._crop_to_job_time_range(job, data)
        ylim = self._compute_ylimits(data, {})
        basename, title = self._make_labels(job.case_name, combined_label, job.run_number, job.signal_name, event_info)
        basename = self._basename_with_time_range(job, basename)
        out = output_dir / f"{basename}_1Ch.png"

        plt.figure(figsize=self.FIGSIZE)
        axis = plt.subplot(111)
        self._configure_axes(axis, data, ylim, policy, phase_y=[1], colors=["navy"], legends_left=job.legends_left)
        self._render_rms_annotations_if_enabled(axis, job, data, policy)
        self._finalize_plot(out, title)
        return out

    def _render_fft_channel(self, job: PlotJob, inf_path: Path, desc_df: list[InfDescriptor], event_info: dict[str, object] | None, output_dir: Path) -> Path:
        if not job.signal_name:
            raise ValueError(f"Missing FFT signal selection for {job.group_label}")
        signal_rows = self._select_any_signal_rows(desc_df, job.group_label, job.signal_name, "individual")
        combined_label = f"{job.group_label}:{job.signal_name}"
        unit = str(signal_rows[0].Unit)
        policy = self._get_group_policy(combined_label, unit)
        policy = self._apply_custom_y_axis_name(policy, unit, job.custom_y_axis_name)
        data = self._load_out_files(inf_path, signal_rows, {})
        data = data.renamed([data.columns[0], job.signal_name])
        harmonics = parse_harmonic_selection(job.fft_harmonics, job.fft_max_harmonic)
        result = rolling_fft(
            data,
            base_frequency_hz=job.fft_base_frequency_hz,
            max_harmonic=job.fft_max_harmonic,
            harmonics=harmonics,
            magnitude_mode=job.fft_magnitude,
            phase_units=job.fft_phase_units,
            phase_reference=job.fft_phase_reference,
        )
        output_type = job.fft_output or FFT_OUTPUT_MAGNITUDES
        plot_frame, y_label, title_suffix, file_token, details, y_limits = self._fft_plot_payload(job, result, policy, output_type)
        plot_frame = self._crop_to_job_time_range(job, plot_frame)
        if output_type != FFT_OUTPUT_PHASE_ANGLES:
            y_limits = self._compute_ylimits(plot_frame, {})
        basename, title = self._fft_labels(job, file_token, title_suffix, details, event_info)
        basename = self._basename_with_time_range(job, basename)
        out = output_dir / f"{basename}.png"

        plt.figure(figsize=self.FIGSIZE)
        axis = plt.subplot(111)
        self._configure_fft_axes(axis, plot_frame, y_label, y_limits)
        self._finalize_plot(out, title)
        return out

    def _render_combined_channels(self, job: PlotJob, inf_path: Path, desc_df: list[InfDescriptor], event_info: dict[str, object] | None, output_dir: Path) -> Path:
        signal_refs = [
            self._combined_ref_with_source(signal, job)
            for signal in job.combined_signals
            if signal.group_name and signal.signal_name
        ]
        if len(signal_refs) < 2:
            raise ValueError("Combined plot requires at least 2 individual signals.")
        units = self._combined_unit_order(signal_refs)
        if len(units) > 2:
            raise ValueError("Combined plot supports up to 2 units.")

        series_by_unit: dict[str, list[tuple[str, np.ndarray, str]]] = {unit: [] for unit in units}
        out_cache_by_inf: dict[Path, dict[int, WaveformFrame]] = {}
        time_values: np.ndarray | None = None
        for index, signal_ref in enumerate(signal_refs):
            source_inf_path = self._resolve_inf_path(signal_ref.case_name, signal_ref.run_number)
            source_desc_df = self._load_inf_descriptors(source_inf_path)
            rows = self._select_any_signal_rows(source_desc_df, signal_ref.group_name, signal_ref.signal_name, "individual")
            frame = self._load_out_files(source_inf_path, rows, out_cache_by_inf.setdefault(source_inf_path, {}))
            if time_values is None:
                frame = self._crop_to_job_time_range(job, frame)
                time_values = frame.column_values(0)
                values = frame.column_values(1)
            else:
                values = self._align_signal_to_time(time_values, frame)
            color = self.COMBINED_COLOURS[index % len(self.COMBINED_COLOURS)]
            label = self._combined_legend_label(signal_ref, signal_refs, include_unit=len(units) > 1)
            series_by_unit.setdefault(signal_ref.unit.strip(), []).append((label, values, color))
        if time_values is None:
            raise ValueError("Combined plot has no signal data.")

        basename = self._basename_with_time_range(job, self._combined_basename(signal_refs))
        title = self._combined_title(signal_refs)
        out = output_dir / f"{basename}.png"

        plt.figure(figsize=self.FIGSIZE)
        axis = plt.subplot(111)
        if len(units) == 1:
            unit = units[0]
            y_frame = WaveformFrame(np.column_stack([time_values] + [values for _label, values, _color in series_by_unit[unit]]))
            axis.set_ylim(self._compute_ylimits(y_frame, {}))
            self._plot_combined_unit(axis, time_values, series_by_unit[unit], self._combined_y_axis_label(unit, job.custom_y_axis_name))
            axis.legend(loc="upper right", fontsize=self.FONTSIZE_LEGEND)
        else:
            left_unit, right_unit = units
            left_frame = WaveformFrame(np.column_stack([time_values] + [values for _label, values, _color in series_by_unit[left_unit]]))
            right_frame = WaveformFrame(np.column_stack([time_values] + [values for _label, values, _color in series_by_unit[right_unit]]))
            axis.set_ylim(self._compute_ylimits(left_frame, {}))
            left_lines = self._plot_combined_unit(axis, time_values, series_by_unit[left_unit], self._combined_y_axis_label(left_unit, job.custom_y_axis_name))
            right_axis = axis.twinx()
            right_axis.set_ylim(self._compute_ylimits(right_frame, {}))
            right_lines = self._plot_combined_unit(right_axis, time_values, series_by_unit[right_unit], self._combined_y_axis_label(right_unit, job.custom_y_axis_name_right))
            lines = left_lines + right_lines
            axis.legend(lines, [line.get_label() for line in lines], loc="upper right", fontsize=self.FONTSIZE_LEGEND)
        axis.set_xlabel("Time [s]")
        axis.grid(True, linewidth=self.LINEWIDTH_GRID, color="gray", linestyle="-", alpha=self.GRID_ALPHA)
        self._finalize_plot(out, title)
        return out

    @staticmethod
    def _combined_ref_with_source(signal: SignalReference, job: PlotJob) -> SignalReference:
        if signal.has_source:
            return signal
        return SignalReference(signal.group_name, signal.signal_name, signal.unit, job.case_name, job.run_number)

    @staticmethod
    def _combined_unit_order(signal_refs: list[SignalReference]) -> list[str]:
        units: list[str] = []
        for signal_ref in signal_refs:
            unit = signal_ref.unit.strip()
            if unit not in units:
                units.append(unit)
        return units

    def _combined_basename(self, signal_refs: list[SignalReference]) -> str:
        sources = self._combined_sources(signal_refs)
        if len(sources) == 1:
            case_name, run_number = sorted(sources)[0]
            event_info = self._event_info_for_case_run(case_name, run_number)
            signal_token = "__".join(self._combined_filename_signal_tokens(signal_refs))
            parts = [self._compact_filename_token(case_name)]
            if event_info is not None:
                fault_raw = str(event_info.get("fault_raw", "0"))
                fault_label = str(event_info.get("fault_label", fault_raw or "No fault"))
                if fault_label != "No fault" and fault_raw != "0":
                    parts.append(self._compact_filename_token(fault_label))
            parts.extend([f"R{run_number:03d}", "COMB", signal_token])
            stem = "_".join(parts)
            return self._filename_stem_with_fallback(
                stem,
                "_".join(parts[:-1] + [f"{len(signal_refs)}sig"]),
                [signal.label for signal in signal_refs],
            )
        case_count = len({case_name for case_name, _run_number in sources})
        signal_tokens = [
            f"{self._compact_filename_token(signal.case_name)}_R{signal.run_number:03d}_{self._signal_filename_token(signal)}"
            for signal in signal_refs[: self.COMBINED_FILENAME_SIGNAL_LIMIT]
        ]
        if len(signal_refs) > self.COMBINED_FILENAME_SIGNAL_LIMIT:
            signal_tokens.append(f"{len(signal_refs)}channels")
        stem = "COMB_" + "__".join(signal_tokens)
        fallback = f"COMB_{case_count}case_{len(sources)}src_{len(signal_refs)}sig"
        return self._filename_stem_with_fallback(
            stem,
            fallback,
            [f"{signal.case_name}|{signal.run_number}|{signal.label}" for signal in signal_refs],
        )

    def _combined_filename_signal_tokens(self, signal_refs: list[SignalReference]) -> list[str]:
        tokens = [
            self._signal_filename_token(signal_ref)
            for signal_ref in signal_refs[: self.COMBINED_FILENAME_SIGNAL_LIMIT]
        ]
        if len(signal_refs) > self.COMBINED_FILENAME_SIGNAL_LIMIT:
            tokens.append(f"{len(signal_refs)}channels")
        return tokens

    def _combined_title(self, signal_refs: list[SignalReference]) -> str:
        sources = self._combined_sources(signal_refs)
        if len(sources) == 1:
            case_name, run_number = sorted(sources)[0]
            parts = [f"Case: {case_name}", f"Run: {run_number}"]
            event_info = self._event_info_for_case_run(case_name, run_number)
            if event_info is not None:
                fault_raw = str(event_info.get("fault_raw", "0"))
                fault_label = str(event_info.get("fault_label", fault_raw or "No fault"))
                if fault_label != "No fault" and fault_raw != "0":
                    parts.append(f"Fault: {fault_label}")
                parts.append(self._format_event_title(event_info))
            parts.append(self._combined_title_signal_summary(signal_refs))
            return " | ".join(parts)

        case_names = sorted({case_name for case_name, _run_number in sources})
        if len(case_names) == 1:
            run_count = len({run_number for _case_name, run_number in sources})
            return f"Case: {case_names[0]} | {run_count} runs | {len(signal_refs)} signals"
        return f"{len(case_names)} cases | {len(sources)} case-run sources | {len(signal_refs)} signals"

    @staticmethod
    def _combined_sources(signal_refs: list[SignalReference]) -> set[tuple[str, int]]:
        return {(signal.case_name, signal.run_number) for signal in signal_refs}

    @staticmethod
    def _combined_title_signal_summary(signal_refs: list[SignalReference]) -> str:
        if len(signal_refs) == 2:
            return " & ".join(signal.label for signal in signal_refs)
        return f"{len(signal_refs)} signals"

    def _combined_legend_label(self, signal_ref: SignalReference, all_refs: list[SignalReference], *, include_unit: bool) -> str:
        sources = self._combined_sources(all_refs)
        case_names = {case_name for case_name, _run_number in sources}
        signal_label = signal_ref.label
        if len(sources) == 1:
            label = signal_label
        elif len(case_names) == 1:
            label = f"Run {signal_ref.run_number}: {signal_label}"
        else:
            label = f"{signal_ref.case_name} R{signal_ref.run_number}: {signal_label}"
        unit = signal_ref.unit.strip()
        if include_unit and unit:
            return f"{label} [{unit}]"
        return label

    def _event_info_for_case_run(self, case_name: str, run_number: int) -> dict[str, object] | None:
        source_inf_path = self._resolve_inf_path(case_name, run_number)
        stat_path = find_stat_file(source_inf_path.parent)
        return self._load_event_info(stat_path, run_number) if stat_path is not None else None


    @staticmethod
    def _align_signal_to_time(target_time: np.ndarray, frame: WaveformFrame) -> np.ndarray:
        source_time = frame.column_values(0)
        source_values = frame.column_values(1)
        if source_time.shape == target_time.shape and np.allclose(source_time, target_time):
            return source_values
        if target_time[0] < source_time[0] or target_time[-1] > source_time[-1]:
            raise ValueError("Combined signals do not share a common time range.")
        return np.interp(target_time, source_time, source_values)

    def _plot_combined_unit(
        self,
        axis: plt.Axes,
        time_values: np.ndarray,
        series: list[tuple[str, np.ndarray, str]],
        y_label: str,
        *,
        linestyle: str = "-",
    ) -> list:
        axis.set_ylabel(y_label)
        lines = []
        for label, values, color in series:
            lines.extend(axis.plot(time_values, values, color=color, lw=self.LINEWIDTH_TRACE, linestyle=linestyle, label=label))
        return lines

    def _combined_y_axis_label(self, unit: str, custom_y_axis_name: str | None = None) -> str:
        if custom_y_axis_name is not None:
            return custom_y_axis_name.strip()
        unit = unit.strip()
        if not unit:
            return self._unitless_y_axis_label(custom_y_axis_name)
        return unit_axis_label(unit)

    @staticmethod
    def _fft_value_label(policy: dict[str, Any], custom_y_axis_name: str | None) -> str:
        if custom_y_axis_name is not None:
            return custom_y_axis_name.strip()
        return str(policy.get("unit_suffix", "")).strip() or "Value"

    def _fft_plot_payload(
        self,
        job: PlotJob,
        result,
        policy: dict[str, Any],
        output_type: str,
    ) -> tuple[WaveformFrame, str, str, str, str, tuple[float, float]]:
        harmonic_labels = [
            self._format_fft_harmonic_label(harmonic, frequency)
            for harmonic, frequency in zip(result.harmonic_numbers, result.harmonic_frequencies_hz)
        ]
        harmonic_summary = self._format_harmonic_summary(result.harmonic_numbers)
        base_frequency = f"{job.fft_base_frequency_hz:g} Hz"
        value_label = self._fft_value_label(policy, job.custom_y_axis_name)
        if output_type == FFT_OUTPUT_PHASE_ANGLES:
            frame = WaveformFrame(np.column_stack([result.time_s, result.phase_angles]), ["Time (s)"] + harmonic_labels)
            unit = "deg" if job.fft_phase_units == FFT_PHASE_DEGREES else "rad"
            limits = (-180.0, 180.0) if job.fft_phase_units == FFT_PHASE_DEGREES else (-math.pi, math.pi)
            return (
                frame,
                f"Phase Angle [{unit}]",
                "FFT Harmonic Phase Angles",
                self._fft_file_token(job, output_type, result.harmonic_numbers),
                f"{job.fft_phase_units} | {job.fft_phase_reference} ref | {base_frequency} | {harmonic_summary}",
                limits,
            )
        if output_type == FFT_OUTPUT_DC:
            frame = WaveformFrame(np.column_stack([result.time_s, result.dc_component]), ["Time (s)", "DC"])
            return (
                frame,
                f"DC Component [{value_label}]" if value_label else "DC Component",
                "FFT DC Component",
                self._fft_file_token(job, output_type, result.harmonic_numbers),
                f"one-cycle average | {base_frequency}",
                self._compute_ylimits(frame, {}),
            )
        frame = WaveformFrame(np.column_stack([result.time_s, result.magnitudes]), ["Time (s)"] + harmonic_labels)
        unit = f"{value_label} {job.fft_magnitude}".strip()
        return (
            frame,
            f"Magnitude [{unit}]" if unit else "Magnitude",
            "FFT Harmonic Magnitudes",
            self._fft_file_token(job, output_type, result.harmonic_numbers),
            f"{job.fft_magnitude} | {base_frequency} | {harmonic_summary}",
            self._compute_ylimits(frame, {}),
        )

    def _fft_labels(
        self,
        job: PlotJob,
        file_token: str,
        title_suffix: str,
        details: str,
        event_info: dict[str, object] | None,
    ) -> tuple[str, str]:
        source_label = f"{job.group_label}:{job.signal_name}"
        source_token = self._signal_filename_token(
            SignalReference(job.group_label, job.signal_name or ""),
            separator="_",
        )
        parts = [self._compact_filename_token(job.case_name)]
        title_parts = [f"Case: {job.case_name}", f"Group: {source_label}", f"Run: {job.run_number}"]
        if event_info is not None:
            fault_raw = str(event_info.get("fault_raw", "0"))
            fault_label = str(event_info.get("fault_label", fault_raw or "No fault"))
            if fault_label != "No fault" and fault_raw != "0":
                parts.append(self._compact_filename_token(fault_label))
                title_parts.append(f"Fault: {fault_label}")
            title_parts.append(self._format_event_title(event_info))
        parts.extend([f"R{job.run_number:03d}", source_token, file_token])
        title_parts.extend([title_suffix, details])
        return "_".join(parts), " | ".join(title_parts)

    def _fft_file_token(self, job: PlotJob, output_type: str, harmonics: list[int]) -> str:
        frequency_token = f"{job.fft_base_frequency_hz:g}Hz"
        if output_type == FFT_OUTPUT_DC:
            return f"FFT-DC_{frequency_token}"
        harmonic_token = self._format_harmonic_filename_token(harmonics)
        if output_type == FFT_OUTPUT_PHASE_ANGLES:
            units_token = "deg" if job.fft_phase_units == FFT_PHASE_DEGREES else "rad"
            reference_token = "cos" if str(job.fft_phase_reference).lower().startswith("cos") else "sin"
            return f"FFT-Ph-{units_token}-{reference_token}_{frequency_token}_{harmonic_token}"
        return f"FFT-Mag-{job.fft_magnitude}_{frequency_token}_{harmonic_token}"

    @staticmethod
    def _format_fft_harmonic_label(harmonic: int, frequency_hz: float) -> str:
        return f"H{harmonic} ({frequency_hz:g} Hz)"

    @staticmethod
    def _format_harmonic_summary(harmonics: list[int]) -> str:
        if not harmonics:
            return "no harmonics"
        if harmonics == list(range(harmonics[0], harmonics[-1] + 1)):
            return f"H{harmonics[0]}-H{harmonics[-1]}"
        return ", ".join(f"H{harmonic}" for harmonic in harmonics)

    @staticmethod
    def _format_harmonic_filename_token(harmonics: list[int]) -> str:
        if not harmonics:
            return "H"
        if harmonics == list(range(harmonics[0], harmonics[-1] + 1)):
            return f"H{harmonics[0]}-{harmonics[-1]}"
        return "_".join(f"H{harmonic}" for harmonic in harmonics)

    def _process_finder(
        self,
        job: PlotJob,
        inf_path: Path,
        idx_df: list[InfDescriptor],
        finder: str,
        type_tag: str,
        event_info: dict[str, object] | None,
        policy: dict[str, Any],
        out_cache: dict[int, WaveformFrame],
        show_limits: bool,
        tov_window_s: float,
    ) -> dict[str, Any]:
        data = self._load_out_files(inf_path, idx_df, out_cache)
        group_label = job.group_label if job.mode is not PlotMode.ANY else f"{job.group_label}:{job.signal_name}"
        data = self._standardize_phase_labels(data, finder, policy["kind"], group_label)
        data = self._crop_to_job_time_range(job, data)
        analysis = self._analyze_data(data, type_tag, policy, job.limits, show_limits, tov_window_s, job.tov_window_count)
        basename, title = self._make_labels(job.case_name, group_label, job.run_number, finder, event_info)
        basename = self._basename_with_time_range(job, basename)
        return {
            "df": data,
            "finder": finder,
            "policy": policy,
            "unit_suffix": policy["unit_suffix"],
            "title": title,
            "basename": basename,
            "ylim": analysis["ylim"],
            "limits_pack": analysis["limits_pack"],
            "t_peak": analysis["t_peak"],
            "y_peak": analysis["y_peak"],
            "phase_idx": analysis["phase_idx"],
            "xwin_peak": analysis["xwin_peak"],
        }

    def _load_inf_descriptors(self, inf_path: Path) -> list[InfDescriptor]:
        if inf_path in self._inf_cache:
            self._inf_cache.move_to_end(inf_path)
            return self._inf_cache[inf_path]
        desc_df = parse_inf_descriptors(inf_path)
        self._remember_cache_item(self._inf_cache, inf_path, desc_df, self.MAX_INF_CACHE)
        return desc_df

    def _load_event_info(self, stat_path: Path, run_number: int) -> dict[str, object] | None:
        if not stat_path.exists():
            return None
        cache_key = (stat_path, run_number)
        if cache_key in self._event_info_cache:
            self._event_info_cache.move_to_end(cache_key)
            return self._event_info_cache[cache_key]
        event_info = load_run_event_info(stat_path, run_number)
        self._remember_cache_item(self._event_info_cache, cache_key, event_info, self.MAX_EVENT_INFO_CACHE)
        return event_info

    def _load_out_frame(self, out_file: Path) -> WaveformFrame:
        if out_file in self._out_file_cache:
            self._out_file_cache.move_to_end(out_file)
            return self._out_file_cache[out_file]
        frame = load_out_frame(out_file)
        self._remember_cache_item(self._out_file_cache, out_file, frame, self.MAX_OUT_FILE_CACHE)
        return frame

    def _remember_cache_item(self, cache: OrderedDict, key: Any, value: Any, max_size: int) -> None:
        cache[key] = value
        cache.move_to_end(key)
        while len(cache) > max_size:
            cache.popitem(last=False)

    def _select_any_signal_rows(self, desc_df: list[InfDescriptor], group_name: str, signal_name: str, signal_view: str) -> list[InfDescriptor]:
        sub = [row for row in desc_df if row.Group == group_name]
        if signal_view == "individual":
            rows = sorted([row for row in sub if str(row.Description) == signal_name], key=lambda row: row.Description)
            if not rows:
                raise ValueError(f"Signal '{signal_name}' not available for {group_name}")
            if len(rows) != 1:
                raise ValueError(f"Expected 1 channel for '{group_name}:{signal_name}', found {len(rows)}")
            return rows

        rows = [row for row in sub if self._matches_exact_bundle_signal(str(row.Description), signal_name)]
        if not rows:
            raise ValueError(f"Signal '{signal_name}' not available for {group_name}")
        rows = sorted(rows, key=lambda row: row.Description)
        if len(rows) != 3:
            raise ValueError(f"Expected 3 phase channels for '{group_name}:{signal_name}', found {len(rows)}")
        return rows

    @staticmethod
    def _matches_exact_bundle_signal(description: str, signal_name: str) -> bool:
        pattern = rf"^{re.escape(signal_name)}(?::[123]|_[abcABC])$"
        return bool(re.match(pattern, description))

    def _filter_signals(self, desc_df: list[InfDescriptor], group_label: str) -> dict[str, list[InfDescriptor]]:
        group_name, signal_name = self._split_group_and_signal(group_label)
        sub = [row for row in desc_df if row.Group == group_name]
        idx_map: dict[str, list[InfDescriptor]] = {}
        if signal_name:
            pattern = rf"^{re.escape(signal_name)}($|[:_])"
            rows = [row for row in sub if re.match(pattern, str(row.Description))]
            if not rows:
                rows = [row for row in sub if re.search(re.escape(signal_name), str(row.Description))]
            if not rows:
                raise ValueError(f"No signals found for Group='{group_name}' and Signal='{signal_name}'")
            rows = sorted(rows, key=lambda row: row.Description)
            if len(rows) != 3:
                raise ValueError(f"Expected 3 phase channels for '{group_name}:{signal_name}', found {len(rows)}")
            idx_map[signal_name] = rows
            return idx_map

        tags = ["LGp", "LLp"] if "MM_" in group_name else ["IIp"]
        for tag in tags:
            pattern = rf"(?:^|[_:]){re.escape(tag)}(?:$|[_:])"
            rows = [row for row in sub if re.search(pattern, str(row.Description))]
            if rows:
                idx_map[tag] = sorted(rows, key=lambda row: row.Description)
        if not idx_map:
            raise ValueError(f"No matching instantaneous signals for {group_label}")
        return idx_map

    def _split_group_and_signal(self, label: str) -> tuple[str, str | None]:
        raw = (label or "").strip().rstrip("*").replace("/", ":")
        if ":" not in raw:
            return raw, None
        parts = [part for part in raw.split(":") if part]
        if len(parts) < 2:
            return raw, None
        return ":".join(parts[:-1]), parts[-1]

    def _load_out_files(self, inf_file: Path, idx_df: list[InfDescriptor], out_cache: dict[int, WaveformFrame]) -> WaveformFrame:
        arrays: list[np.ndarray] = []
        columns: list[str] = []
        for row in idx_df:
            pgb = int(row.PGB)
            name = str(row.Description)
            file_number, col_number = pgb_to_out_location(pgb)
            if file_number not in out_cache:
                out_file = standard_out_file_path(inf_file, file_number)
                out_cache[file_number] = self._load_out_frame(out_file)
            data = out_cache[file_number]
            if not arrays:
                arrays.append(data.column_values(0))
                columns.append("Time (s)")
            arrays.append(data.column_values(col_number))
            columns.append(name)
        if len(arrays) < 2:
            raise ValueError(f"Expected at least 2 columns (time + signal), got {len(arrays)}")
        return WaveformFrame(np.column_stack(arrays), columns)

    def _get_group_policy(self, group_label: str, unit: str | None = None) -> dict[str, Any]:
        group_name, _ = self._split_group_and_signal(group_label)
        if unit and unit.strip():
            policy = self._policy_from_unit(unit)
        elif "MM_" in group_name:
            policy = {"kind": "MM", "unit_suffix": "kV", "draw_limits": True, "yaxis_label": "Voltage [kV]", "limits_mode": "MM"}
        elif "CB_" in group_name:
            policy = {"kind": "CB", "unit_suffix": "kA", "draw_limits": False, "yaxis_label": "Current [kA]", "limits_mode": None}
        else:
            _, signal_name = self._split_group_and_signal(group_label)
            signal_hint = (signal_name or "").strip()
            if signal_hint[:1].upper() == "V":
                policy = {"kind": "UNK", "unit_suffix": "kV", "draw_limits": False, "yaxis_label": "Voltage [kV]", "limits_mode": None}
            elif signal_hint[:1].upper() == "I":
                policy = {"kind": "UNK", "unit_suffix": "kA", "draw_limits": False, "yaxis_label": "Current [kA]", "limits_mode": None}
            else:
                policy = {"kind": "UNK", "unit_suffix": "", "draw_limits": False, "yaxis_label": "Value", "limits_mode": None}
        return policy

    def _policy_from_unit(self, unit: str) -> dict[str, Any]:
        normalized = unit.strip()
        return {"kind": "UNK", "unit_suffix": unit_suffix(normalized), "draw_limits": False, "yaxis_label": unit_axis_label(normalized), "limits_mode": None}

    def _apply_custom_y_axis_name(self, policy: dict[str, Any], unit: str | None, custom_y_axis_name: str | None) -> dict[str, Any]:
        if custom_y_axis_name is None:
            return policy
        updated_policy = dict(policy)
        updated_policy["yaxis_label"] = custom_y_axis_name.strip()
        return updated_policy

    @staticmethod
    def _unitless_y_axis_label(custom_y_axis_name: str | None) -> str:
        if custom_y_axis_name is None:
            return "Value"
        return custom_y_axis_name.strip()

    def _standardize_phase_labels(self, df: WaveformFrame, finder: str, kind: str, group_label: str) -> WaveformFrame:
        phase_cols = df.columns[1:]
        prefix_default = "V_" if kind == "MM" else "I_" if kind == "CB" else ""
        ll_mapping = {"a": "ab", "b": "bc", "c": "ca"}
        phase_map = {"1": "a", "2": "b", "3": "c", "a": "a", "b": "b", "c": "c"}
        new_cols = []
        for col in phase_cols:
            col_text = str(col)
            if kind in ("MM", "CB"):
                group_prefix = group_label.split("_")[0] if "_" in group_label else ""
                col_clean = col_text.replace(f"{group_prefix}_", "") if group_prefix else col_text
                col_clean = col_clean.replace(f"{finder}_", "")
                if "LL" in finder:
                    col_clean = ll_mapping.get(col_clean, col_clean)
                new_cols.append(f"{prefix_default}{col_clean}")
                continue
            if ":" in col_text:
                base, phase = col_text.rsplit(":", 1)
                phase = phase_map.get(phase.strip(), phase.strip())
            elif "_" in col_text:
                base, phase = col_text.rsplit("_", 1)
                phase = phase_map.get(phase.strip(), phase.strip())
            else:
                base, phase = col_text, ""
            prefix = "V_" if base[:1].upper() == "V" else "I_" if base[:1].upper() == "I" else prefix_default
            new_cols.append(f"{prefix}{phase}" if phase else f"{prefix}{base}")
        return df.renamed([df.columns[0]] + new_cols)

    def _analyze_data(
        self,
        df: WaveformFrame,
        type_tag: str,
        policy: dict[str, Any],
        limits: Any,
        show_limits: bool,
        tov_window_s: float,
        tov_window_count: int,
    ) -> dict[str, Any]:
        limits_pack = self._compute_insulation_limits(type_tag, policy, limits) if show_limits else {}
        t_peak, y_peak, phase_idx = self._compute_peaks(df)
        ylim = self._compute_ylimits(df, limits_pack if policy["draw_limits"] else {})
        xwin_peak = self._window_peak_centered(t_peak, tov_window_s, tov_window_count)
        return {
            "limits_pack": limits_pack if policy["draw_limits"] else {},
            "t_peak": t_peak,
            "y_peak": y_peak,
            "phase_idx": phase_idx,
            "ylim": ylim,
            "xwin_peak": xwin_peak,
        }

    def _compute_insulation_limits(self, type_tag: str, policy: dict[str, Any], limits: Any) -> dict[str, float]:
        if policy.get("limits_mode") != "MM" or limits is None:
            return {}
        result: dict[str, float] = {}
        if type_tag == "LGp":
            result["siwl"] = limits.siwl_lg
            result["sdpf"] = limits.sdpf_lg * math.sqrt(2)
        elif type_tag == "LLp":
            result["siwl"] = limits.siwl_ll
            result["sdpf"] = limits.sdpf_ll * math.sqrt(2)
        else:
            return {}
        result["siwl_margin"] = result["siwl"] / self.SAFETY_MARGIN
        result["sdpf_margin"] = result["sdpf"] / self.SAFETY_MARGIN
        return result

    def _compute_peaks(self, df: WaveformFrame) -> tuple[float, float, int]:
        return df.peak_abs()

    def _compute_ylimits(self, df: WaveformFrame, limits_pack: dict[str, float]) -> tuple[float, float]:
        return df.y_limits(limits_pack, self.PAD_YLIM)

    @staticmethod
    def _crop_to_job_time_range(job: PlotJob, frame: WaveformFrame) -> WaveformFrame:
        return frame.time_window(job.time_start_s, job.time_end_s)

    def _basename_with_time_range(self, job: PlotJob, basename: str) -> str:
        token = self._time_range_filename_token(job.time_start_s, job.time_end_s)
        return f"{basename}_{token}" if token else basename

    @staticmethod
    def _time_range_filename_token(start_s: float | None, end_s: float | None) -> str:
        if start_s is None and end_s is None:
            return ""
        if start_s is None:
            return f"Tto{float(end_s):g}s"
        if end_s is None:
            return f"Tfrom{float(start_s):g}s"
        return f"T{float(start_s):g}-{float(end_s):g}s"

    def _window_peak_centered(self, t_peak: float, tov_window_s: float, tov_window_count: int) -> tuple[float, float]:
        width = float(tov_window_s) * max(1, int(tov_window_count)) * self.WINDOW_MULTIPLIER
        return t_peak - width, t_peak + width

    def _make_labels(self, case_name: str, group_label: str, run_number: int, finder: str, event_info: dict[str, object] | None, combine: bool = False) -> tuple[str, str]:
        group_safe = self._sanitize_filename_token(group_label)
        finder_safe = self._sanitize_filename_token(finder)
        if event_info is not None:
            fault_raw = str(event_info.get("fault_raw", "0"))
            fault_label = str(event_info.get("fault_label", fault_raw or "No fault"))
            event_title = self._format_event_title(event_info)
            if fault_label == "No fault" or fault_raw == "0":
                basename = f"{case_name}_{group_safe}_{run_number:03d}_{finder_safe}"
                title = f"Case: {case_name} | Group: {group_label} | Run: {run_number} | {event_title} | {finder}"
            else:
                fault_safe = self._sanitize_filename_token(fault_label)
                basename = f"{case_name}_{group_safe}_{fault_safe}_{run_number:03d}_{finder_safe}"
                title = f"Case: {case_name} | Group: {group_label} | Run: {run_number} | Fault: {fault_label} | {event_title} | {finder}"
        else:
            basename = f"{case_name}_{group_safe}_{run_number:03d}_{finder_safe}"
            title = f"Case: {case_name} | Group: {group_label} | Run: {run_number} | {finder}"
        if combine:
            basename = re.sub(f"_{re.escape(finder_safe)}$", "_LGp_LLp", basename)
            title = re.sub(f" \\| {re.escape(finder)}$", " | LGp & LLp", title)
        return basename, title

    def _format_event_title(self, event_info: dict[str, object]) -> str:
        phase_values = event_info.get("event_times_s")
        if isinstance(phase_values, dict):
            phase_parts = [
                (phase, self._format_event_time(phase_values.get(phase)))
                for phase in ("a", "b", "c")
                if phase_values.get(phase) is not None
            ]
            if len(phase_parts) > 1 and len({value for _, value in phase_parts}) > 1:
                return " | ".join(f"Tevent_{phase}: {value}" for phase, value in phase_parts)
        return f"Tevent: {self._format_event_time(event_info.get('event_time_s'))}"

    @staticmethod
    def _format_event_time(value: object) -> str:
        if value is None:
            return "N/A"
        try:
            return f"{float(value):.4f}s"
        except (TypeError, ValueError):
            return str(value)

    def _sanitize_filename_token(self, value: str) -> str:
        sanitized = self.INVALID_FILENAME_CHARS.sub("_", value.strip())
        sanitized = re.sub(r"\s+", "_", sanitized)
        sanitized = sanitized.rstrip(". ")
        return sanitized or "value"

    def _compact_filename_token(self, value: str) -> str:
        sanitized = self._sanitize_filename_token(value)
        sanitized = re.sub(r"_+", "_", sanitized).strip("_")
        return sanitized or "value"

    def _signal_filename_token(self, signal_ref: SignalReference, *, separator: str = "-") -> str:
        group_token = self._compact_filename_token(signal_ref.group_name)
        signal_token = self._compact_filename_token(signal_ref.signal_name)
        if group_token and signal_token:
            return f"{group_token}{separator}{signal_token}"
        return group_token or signal_token or "signal"

    def _filename_stem_with_fallback(self, stem: str, fallback: str, hash_parts: list[str]) -> str:
        if len(stem) <= self.MAX_FILENAME_STEM_LENGTH:
            return stem
        digest = hashlib.sha1("|".join(hash_parts).encode("utf-8")).hexdigest()[:8]
        return f"{fallback}_{digest}"

    def _render_insulation_limits(self, ax: plt.Axes, limits_pack: dict[str, float]) -> None:
        if "siwl" in limits_pack:
            for value in [limits_pack["siwl"], -limits_pack["siwl"]]:
                ax.axhline(value, color="red", linestyle="--", linewidth=self.LINEWIDTH_LIMIT_THIN)
            for value in [limits_pack["siwl_margin"], -limits_pack["siwl_margin"]]:
                ax.axhline(value, color="orange", linestyle="--", linewidth=self.LINEWIDTH_LIMIT_THIN)
        if "sdpf" in limits_pack:
            for value in [limits_pack["sdpf"], -limits_pack["sdpf"]]:
                ax.axhline(value, color="red", linestyle="--", linewidth=self.LINEWIDTH_LIMIT_THICK)
            for value in [limits_pack["sdpf_margin"], -limits_pack["sdpf_margin"]]:
                ax.axhline(value, color="orange", linestyle="--", linewidth=self.LINEWIDTH_LIMIT_THICK)

    def _render_insulation_limits_legend(self, ax: plt.Axes, limits_pack: dict[str, float], *, legends_left: bool = False) -> None:
        handles = []
        if "siwl" in limits_pack:
            handles.append(plt.Line2D([], [], color="red", ls="--", lw=self.LINEWIDTH_LIMIT_THIN, label="SIWL limit"))
            handles.append(plt.Line2D([], [], color="orange", ls="--", lw=self.LINEWIDTH_LIMIT_THIN, label="SIWL safety margin"))
        if "sdpf" in limits_pack:
            handles.append(plt.Line2D([], [], color="red", ls="--", lw=self.LINEWIDTH_LIMIT_THICK, label="SDPF limit"))
            handles.append(plt.Line2D([], [], color="orange", ls="--", lw=self.LINEWIDTH_LIMIT_THICK, label="SDPF safety margin"))
        if handles:
            ax.legend(handles=handles, loc="lower left" if legends_left else "lower right", fontsize=self.FONTSIZE_LEGEND)

    def _add_limits_if_applicable(self, ax: plt.Axes, limits_pack: dict[str, float], *, legends_left: bool = False) -> None:
        if limits_pack:
            self._render_insulation_limits(ax, limits_pack)
            self._render_insulation_limits_legend(ax, limits_pack, legends_left=legends_left)

    def _render_tov_window(self, ax: plt.Axes, t_peak: float, tov_window_s: float, tov_window_count: int) -> None:
        for index in range(0, max(1, int(tov_window_count)) + 1):
            offset = index * float(tov_window_s)
            ax.axvline(t_peak - offset, color="violet", lw=self.LINEWIDTH_ANNO, ls="--")
            ax.axvline(t_peak + offset, color="violet", lw=self.LINEWIDTH_ANNO, ls="--")

    def _render_window_markers_if_enabled(self, ax: plt.Axes, job: PlotJob, t_peak: float) -> None:
        if not job.show_tov_windows:
            return
        self._render_tov_window(ax, t_peak, job.tov_window_s, job.tov_window_count)

    def _render_peak_annotation(self, ax: plt.Axes, t_peak: float, y_peak: float, unit_suffix: str, color: str) -> None:
        ylim = ax.get_ylim()
        y_range = ylim[1] - ylim[0]
        y_offset = self.ANNO_Y_OFFSET * y_range
        y_text = y_peak + y_offset if y_peak >= 0 else y_peak - y_offset
        vertical_align = "bottom" if y_peak >= 0 else "top"
        self._expand_ylim_for_peak_annotation(ax, y_text, vertical_align, y_range)
        ax.axvline(t_peak, color=color, lw=self.LINEWIDTH_ANNO, ls="--")
        unit = f" {unit_suffix}" if unit_suffix else ""
        ax.annotate(
            f"{y_peak:.1f}{unit} @ {t_peak:.3f} s",
            xy=(t_peak, y_peak),
            xytext=(t_peak + self.ANNO_X_OFFSET, y_text),
            textcoords="data",
            color=color,
            fontsize=self.FONTSIZE_ANNO,
            ha="right",
            va=vertical_align,
        )

    def _expand_ylim_for_peak_annotation(self, ax: plt.Axes, y_text: float, vertical_align: str, y_range: float) -> None:
        bottom, top = ax.get_ylim()
        padding = max(abs(y_range) * self.ANNO_Y_LIMIT_PAD, 1e-9)
        if vertical_align == "bottom" and y_text + padding > top:
            ax.set_ylim(bottom, y_text + padding)
        elif vertical_align == "top" and y_text - padding < bottom:
            ax.set_ylim(y_text - padding, top)

    def _render_rms_annotations_if_enabled(self, ax: plt.Axes, job: PlotJob, df: WaveformFrame, policy: dict[str, Any]) -> None:
        if not (job.annotate_max or job.annotate_min):
            return
        if job.show_three_phase_overview:
            return
        if not job.signal_name or not is_any_rms_signal(job.group_label, job.signal_name):
            return
        if job.annotate_max:
            self._render_extreme_annotation(ax, df, policy, use_max=True)
        if job.annotate_min:
            self._render_extreme_annotation(ax, df, policy, use_max=False)

    def _render_extreme_annotation(self, ax: plt.Axes, df: WaveformFrame, policy: dict[str, Any], *, use_max: bool) -> None:
        if df.values.shape[1] < 2:
            return
        y_values = df.values[:, 1:]
        flat_index = int(np.nanargmax(y_values) if use_max else np.nanargmin(y_values))
        row_idx, _col_idx = np.unravel_index(flat_index, y_values.shape)
        t_value = float(df.values[row_idx, 0])
        y_value = float(y_values[row_idx, _col_idx])
        vertical_offset = 10 if use_max else -14
        vertical_align = "bottom" if use_max else "top"
        ax.annotate(
            self._format_value_with_unit(y_value, str(policy.get("unit_suffix", ""))),
            xy=(t_value, y_value),
            xytext=(6, vertical_offset),
            textcoords="offset points",
            color=self.ANNOTATION_COLOUR,
            fontsize=self.FONTSIZE_ANNO,
            ha="left",
            va=vertical_align,
        )

    @staticmethod
    def _format_value_with_unit(value: float, unit_suffix: str) -> str:
        text = f"{value:.1f}".rstrip("0").rstrip(".")
        unit = unit_suffix.strip()
        return f"{text} [{unit}]" if unit else text

    def _configure_axes(
        self,
        ax: plt.Axes,
        df: WaveformFrame,
        ylim: tuple[float, float],
        policy: dict[str, Any],
        phase_y: list[int] | None = None,
        colors: list[str] | None = None,
        legends_left: bool = False,
    ) -> None:
        phase_y = phase_y or self.PHASE_COLS
        colors = colors or self.PHASE_COLOURS
        ax.set_ylim(ylim)
        ax.set_ylabel(policy["yaxis_label"])
        ax.set_xlabel("Time [s]")
        time_values = df.column_values(0)
        for column_index, color in zip(phase_y, colors):
            ax.plot(
                time_values,
                df.column_values(column_index),
                color=color,
                lw=self.LINEWIDTH_TRACE,
                label=str(df.columns[column_index]),
            )
        ax.grid(True, linewidth=self.LINEWIDTH_GRID, color="gray", linestyle="-", alpha=self.GRID_ALPHA)
        phase_legend = ax.legend(loc="upper left" if legends_left else "upper right", fontsize=self.FONTSIZE_LEGEND)
        ax.add_artist(phase_legend)

    def _configure_fft_axes(self, ax: plt.Axes, df: WaveformFrame, y_label: str, y_limits: tuple[float, float]) -> None:
        ax.set_ylim(y_limits)
        ax.set_ylabel(y_label)
        ax.set_xlabel("Time [s]")
        time_values = df.column_values(0)
        for column_index in range(1, df.values.shape[1]):
            ax.step(
                time_values,
                df.column_values(column_index),
                where="post",
                lw=self.LINEWIDTH_TRACE,
                label=str(df.columns[column_index]),
            )
        ax.grid(True, linewidth=self.LINEWIDTH_GRID, color="gray", linestyle="-", alpha=self.GRID_ALPHA)
        legend = ax.legend(loc="upper right", fontsize=self.FONTSIZE_LEGEND)
        ax.add_artist(legend)

    def _finalize_plot(self, out_path: Path, title: str) -> None:
        figure = plt.gcf()
        figure.suptitle(title, fontsize=self.FONTSIZE_TITLE)
        figure.subplots_adjust(top=0.9)
        figure.tight_layout(pad=self.TIGHT_LAYOUT_PAD)
        figure.savefig(out_path, dpi=self.DPI)
        plt.close(figure)
